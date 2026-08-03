-- 0001 core: people/companies mirror, suppressions, mailboxes, ops tables.
--
-- HubSpot is the system of record for people. These tables exist because the
-- enrollment layer needs fields HubSpot does not hold (icp_reasons,
-- office_signal_evidence, last_emailed_at, do_not_contact) and because
-- suppression must be enforced in our code before enrollment, globally.

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ---------------------------------------------------------------- companies

CREATE TABLE companies (
    id                      bigserial PRIMARY KEY,
    apollo_org_id           text,
    name                    text NOT NULL,
    domain                  text,
    website_url             text,
    linkedin_url            text,
    founded_year            int,

    -- Only obtainable from organizations/bulk_enrich, at 1 credit per matched
    -- company. NULL means "not enriched yet" -> pending qualification, NOT fail.
    latest_funding_stage    text,
    funding_enriched_at     timestamptz,
    funding_enrich_attempts int NOT NULL DEFAULT 0,

    -- Apollo cannot query in-office working. Scored, never filtered.
    office_signal           text NOT NULL DEFAULT 'unknown',
    office_signal_evidence  jsonb NOT NULL DEFAULT '[]'::jsonb,

    hubspot_company_id      text,
    hubspot_synced_at       timestamptz,

    raw_source              jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT companies_office_signal_valid CHECK (
        office_signal IN ('confirmed_in_office', 'likely_in_office',
                          'likely_remote', 'unknown')
    ),
    -- Stage vocabulary is closed; NULL is the "unknown" member.
    CONSTRAINT companies_funding_stage_valid CHECK (
        latest_funding_stage IS NULL OR latest_funding_stage IN (
            'pre_seed', 'seed', 'series_a', 'series_b', 'series_c',
            'series_d_plus', 'public', 'acquired', 'bootstrapped', 'other'
        )
    ),
    -- Evidence must accompany any non-unknown office signal, so the value is
    -- always auditable back to something real.
    CONSTRAINT companies_office_signal_needs_evidence CHECK (
        office_signal = 'unknown' OR jsonb_array_length(office_signal_evidence) > 0
    )
);

-- Partial unique indexes: these keys are genuinely absent for some rows and
-- NULL-vs-NULL must not collide.
CREATE UNIQUE INDEX companies_apollo_org_id_key
    ON companies (apollo_org_id) WHERE apollo_org_id IS NOT NULL;
CREATE UNIQUE INDEX companies_domain_key
    ON companies (lower(domain)) WHERE domain IS NOT NULL;
CREATE UNIQUE INDEX companies_hubspot_company_id_key
    ON companies (hubspot_company_id) WHERE hubspot_company_id IS NOT NULL;
CREATE INDEX companies_funding_stage_idx ON companies (latest_funding_stage);
CREATE INDEX companies_pending_enrich_idx
    ON companies (id) WHERE latest_funding_stage IS NULL;

CREATE TRIGGER companies_set_updated_at BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ----------------------------------------------------------------- contacts

CREATE TABLE contacts (
    id                    bigserial PRIMARY KEY,

    -- Dedup key. HubSpot's native key is email, which is absent for every
    -- lead we have not paid to reveal -- which is most of them.
    apollo_person_id      text,

    first_name            text,
    last_name             text,
    title                 text,
    linkedin_url          text,
    person_location       text,

    -- Only obtainable from people/bulk_match, at >=1 credit. NULL until
    -- revealed at enrollment; search never returns it.
    email                 text,
    email_revealed_at     timestamptz,
    email_status          text,

    company_id            bigint REFERENCES companies (id) ON DELETE SET NULL,

    priority_score        numeric(8,3) NOT NULL DEFAULT 0,
    icp_status            text NOT NULL DEFAULT 'pending',
    icp_reasons           jsonb NOT NULL DEFAULT '[]'::jsonb,
    seed_lifecycle_stage  text NOT NULL DEFAULT 'sourced',

    hubspot_contact_id    text,
    hubspot_synced_at     timestamptz,

    last_emailed_at       timestamptz,
    do_not_contact        boolean NOT NULL DEFAULT false,

    raw_source            jsonb NOT NULL DEFAULT '{}'::jsonb,
    sourced_at            timestamptz NOT NULL DEFAULT now(),
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT contacts_icp_status_valid CHECK (
        icp_status IN ('pending', 'qualified', 'disqualified')
    ),
    CONSTRAINT contacts_seed_lifecycle_valid CHECK (
        seed_lifecycle_stage IN ('sourced', 'qualified', 'enrolled',
                                 'engaged', 'replied', 'meeting', 'disqualified')
    ),
    CONSTRAINT contacts_email_revealed_together CHECK (
        (email IS NULL) = (email_revealed_at IS NULL)
    )
);

CREATE UNIQUE INDEX contacts_apollo_person_id_key
    ON contacts (apollo_person_id) WHERE apollo_person_id IS NOT NULL;
CREATE UNIQUE INDEX contacts_email_key
    ON contacts (lower(email)) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX contacts_hubspot_contact_id_key
    ON contacts (hubspot_contact_id) WHERE hubspot_contact_id IS NOT NULL;
CREATE INDEX contacts_company_id_idx ON contacts (company_id);
CREATE INDEX contacts_priority_idx ON contacts (priority_score DESC);
CREATE INDEX contacts_last_emailed_idx ON contacts (last_emailed_at);
-- Enrollment candidate scan: not suppressed, not recently mailed, by priority.
CREATE INDEX contacts_enrollable_idx ON contacts (priority_score DESC)
    WHERE do_not_contact = false AND icp_status <> 'disqualified';

CREATE TRIGGER contacts_set_updated_at BEFORE UPDATE ON contacts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ------------------------------------------------------------- suppressions
-- Authoritative here, mirrored to HubSpot's native opt-out so reps can see it.
-- Enforced globally before enrollment, never per-campaign.

CREATE TABLE suppressions (
    id           bigserial PRIMARY KEY,
    scope        text NOT NULL,
    -- Stored already normalised (lowercased, trimmed) by the application.
    value        text NOT NULL,
    reason       text NOT NULL,
    source       text NOT NULL,
    notes        text,
    created_at   timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT suppressions_scope_valid CHECK (scope IN ('email', 'domain')),
    CONSTRAINT suppressions_reason_valid CHECK (
        reason IN ('unsubscribe', 'hard_bounce', 'spam_complaint', 'manual',
                   'competitor', 'customer', 'open_opportunity', 'free_mail')
    ),
    CONSTRAINT suppressions_value_normalised CHECK (
        value = lower(btrim(value)) AND value <> ''
    )
);

CREATE UNIQUE INDEX suppressions_scope_value_key ON suppressions (scope, value);
-- Domain suppression must cover subdomains; the suffix match is done in code
-- against this index-backed set.
CREATE INDEX suppressions_domain_idx ON suppressions (value) WHERE scope = 'domain';


-- ---------------------------------------------------------------- mailboxes

CREATE TABLE mailboxes (
    id                   bigserial PRIMARY KEY,
    provider             text NOT NULL DEFAULT 'smartlead',
    provider_account_id  text NOT NULL,
    email                text NOT NULL,
    sending_domain       text NOT NULL,
    daily_cap            int NOT NULL,
    status               text NOT NULL DEFAULT 'active',
    warmup_started_at    timestamptz,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT mailboxes_status_valid CHECK (
        status IN ('active', 'warming', 'paused', 'burned')
    ),
    -- Cold mailboxes die above ~50/day. Enforced, not documented.
    CONSTRAINT mailboxes_daily_cap_sane CHECK (daily_cap > 0 AND daily_cap <= 50)
);

CREATE UNIQUE INDEX mailboxes_provider_account_key
    ON mailboxes (provider, provider_account_id);
CREATE UNIQUE INDEX mailboxes_email_key ON mailboxes (lower(email));
CREATE INDEX mailboxes_domain_idx ON mailboxes (sending_domain);

CREATE TRIGGER mailboxes_set_updated_at BEFORE UPDATE ON mailboxes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ----------------------------------------------------------------- job_runs

CREATE TABLE job_runs (
    id            bigserial PRIMARY KEY,
    job_name      text NOT NULL,
    status        text NOT NULL,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    duration_ms   int,
    -- Every external call gets a row here; credits spent are tracked so the
    -- 200-credit ask-first ceiling is measurable rather than notional.
    items_in      int NOT NULL DEFAULT 0,
    items_out     int NOT NULL DEFAULT 0,
    credits_spent int NOT NULL DEFAULT 0,
    error         text,
    detail        jsonb NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT job_runs_status_valid CHECK (
        status IN ('running', 'succeeded', 'failed', 'skipped_locked')
    ),
    CONSTRAINT job_runs_finished_consistent CHECK (
        (status = 'running') = (finished_at IS NULL)
    )
);

CREATE INDEX job_runs_name_started_idx ON job_runs (job_name, started_at DESC);
CREATE INDEX job_runs_failed_idx ON job_runs (started_at DESC)
    WHERE status = 'failed';


-- ----------------------------------------------------------- source_cursors
-- Facet rotation state. Both Apollo searches cap at 50,000 records per filter
-- set (100/page x 500 pages), so rotating facets is mandatory to reach past it.

CREATE TABLE source_cursors (
    id                bigserial PRIMARY KEY,
    source            text NOT NULL,
    facet_key         text NOT NULL,
    facet             jsonb NOT NULL,
    next_page         int NOT NULL DEFAULT 1,
    pages_exhausted   boolean NOT NULL DEFAULT false,
    total_seen        int NOT NULL DEFAULT 0,
    last_run_at       timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT source_cursors_page_in_range CHECK (next_page BETWEEN 1 AND 501)
);

CREATE UNIQUE INDEX source_cursors_source_facet_key
    ON source_cursors (source, facet_key);
CREATE INDEX source_cursors_rotation_idx ON source_cursors (last_run_at NULLS FIRST)
    WHERE pages_exhausted = false;

CREATE TRIGGER source_cursors_set_updated_at BEFORE UPDATE ON source_cursors
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

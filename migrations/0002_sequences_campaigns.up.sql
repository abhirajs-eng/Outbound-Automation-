-- 0002 sequences and campaigns.
--
-- Sequences are synced from Google Drive and versioned by content hash, so a
-- metric can always be tied to the exact copy that produced it. Campaign
-- activation is gated in the database, not only in application code.

-- ---------------------------------------------------------------- sequences

CREATE TABLE sequences (
    id            bigserial PRIMARY KEY,
    name          text NOT NULL,
    source_ref    text,               -- Drive file id
    archived      boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX sequences_name_key ON sequences (lower(name));

CREATE TRIGGER sequences_set_updated_at BEFORE UPDATE ON sequences
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


CREATE TABLE sequence_versions (
    id                  bigserial PRIMARY KEY,
    sequence_id         bigint NOT NULL REFERENCES sequences (id) ON DELETE CASCADE,
    version             int NOT NULL,
    -- sha256 of normalised parsed content. Re-syncing unchanged copy must not
    -- create a new version, or every metric cut fragments for no reason.
    content_hash        text NOT NULL,

    -- CAN-SPAM. Both must be present or the version cannot be activated.
    -- Checked here so it cannot be bypassed by a code path that forgot.
    has_unsubscribe     boolean NOT NULL DEFAULT false,
    has_physical_address boolean NOT NULL DEFAULT false,
    compliance_errors   jsonb NOT NULL DEFAULT '[]'::jsonb,

    synced_at           timestamptz NOT NULL DEFAULT now(),
    created_at          timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT sequence_versions_version_positive CHECK (version >= 1)
);

CREATE UNIQUE INDEX sequence_versions_seq_version_key
    ON sequence_versions (sequence_id, version);
CREATE UNIQUE INDEX sequence_versions_seq_hash_key
    ON sequence_versions (sequence_id, content_hash);

-- Read by the activation trigger and by the approval screen.
CREATE VIEW sequence_version_compliance AS
    SELECT id AS sequence_version_id,
           (has_unsubscribe AND has_physical_address) AS compliance_ok
    FROM sequence_versions;


CREATE TABLE sequence_steps (
    id                  bigserial PRIMARY KEY,
    sequence_version_id bigint NOT NULL
        REFERENCES sequence_versions (id) ON DELETE CASCADE,
    step_number         int NOT NULL,
    delay_days          int NOT NULL DEFAULT 0,
    created_at          timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT sequence_steps_number_positive CHECK (step_number >= 1),
    CONSTRAINT sequence_steps_delay_nonneg CHECK (delay_days >= 0)
);

CREATE UNIQUE INDEX sequence_steps_version_number_key
    ON sequence_steps (sequence_version_id, step_number);


-- In-campaign step variants: same audience, same mailboxes, same weeks. This
-- is the only comparison that is not confounded, so variants live on the step.
CREATE TABLE step_variants (
    id                bigserial PRIMARY KEY,
    sequence_step_id  bigint NOT NULL
        REFERENCES sequence_steps (id) ON DELETE CASCADE,
    variant_label     text NOT NULL,          -- 'A', 'B', ...
    subject           text NOT NULL,
    body              text NOT NULL,
    distribution_pct  int NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT step_variants_distribution_range CHECK (
        distribution_pct BETWEEN 0 AND 100
    )
);

CREATE UNIQUE INDEX step_variants_step_label_key
    ON step_variants (sequence_step_id, variant_label);


-- ---------------------------------------------------------------- campaigns

CREATE TABLE campaigns (
    id                     bigserial PRIMARY KEY,
    name                   text NOT NULL,
    sequence_version_id    bigint NOT NULL REFERENCES sequence_versions (id),
    segment                text,
    status                 text NOT NULL DEFAULT 'draft',

    provider               text NOT NULL DEFAULT 'smartlead',
    provider_campaign_id   text,

    daily_volume           int,
    approved_by            text,
    approved_at            timestamptz,
    launched_at            timestamptz,

    paused_reason          text,
    paused_at              timestamptz,

    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT campaigns_status_valid CHECK (
        status IN ('draft', 'pending_approval', 'approved', 'active',
                   'paused', 'stopped', 'completed')
    ),

    -- The approval gate, as a constraint rather than a convention: a campaign
    -- cannot be active without a recorded approver and a launch timestamp.
    CONSTRAINT campaigns_approval_gate CHECK (
        status <> 'active' OR (
            approved_by IS NOT NULL
            AND approved_at IS NOT NULL
            AND launched_at IS NOT NULL
        )
    ),
    CONSTRAINT campaigns_approved_together CHECK (
        (approved_by IS NULL) = (approved_at IS NULL)
    ),
    CONSTRAINT campaigns_paused_has_reason CHECK (
        status <> 'paused' OR paused_reason IS NOT NULL
    )
);

CREATE UNIQUE INDEX campaigns_name_key ON campaigns (lower(name));
CREATE UNIQUE INDEX campaigns_provider_campaign_key
    ON campaigns (provider, provider_campaign_id)
    WHERE provider_campaign_id IS NOT NULL;
CREATE INDEX campaigns_status_idx ON campaigns (status);

CREATE TRIGGER campaigns_set_updated_at BEFORE UPDATE ON campaigns
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- A CHECK constraint cannot reach another table, so the CAN-SPAM gate is a
-- trigger. Blocking, not warning: an activation attempt on non-compliant copy
-- raises rather than logging.
CREATE OR REPLACE FUNCTION enforce_campaign_compliance() RETURNS trigger AS $$
DECLARE
    ok boolean;
    errs jsonb;
BEGIN
    IF NEW.status NOT IN ('active', 'approved') THEN
        RETURN NEW;
    END IF;

    SELECT (has_unsubscribe AND has_physical_address), compliance_errors
      INTO ok, errs
      FROM sequence_versions
     WHERE id = NEW.sequence_version_id;

    IF NOT ok THEN
        RAISE EXCEPTION
            'CAN-SPAM: sequence_version % lacks unsubscribe and/or physical address (%); campaign % cannot be %',
            NEW.sequence_version_id, errs, NEW.name, NEW.status
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER campaigns_enforce_compliance
    BEFORE INSERT OR UPDATE OF status, sequence_version_id ON campaigns
    FOR EACH ROW EXECUTE FUNCTION enforce_campaign_compliance();


CREATE TABLE campaign_mailboxes (
    campaign_id  bigint NOT NULL REFERENCES campaigns (id) ON DELETE CASCADE,
    mailbox_id   bigint NOT NULL REFERENCES mailboxes (id) ON DELETE CASCADE,
    PRIMARY KEY (campaign_id, mailbox_id)
);


-- ----------------------------------------------------------- campaign_leads

CREATE TABLE campaign_leads (
    id                bigserial PRIMARY KEY,
    campaign_id       bigint NOT NULL REFERENCES campaigns (id) ON DELETE CASCADE,
    contact_id        bigint NOT NULL REFERENCES contacts (id) ON DELETE CASCADE,

    provider_lead_id  text,
    status            text NOT NULL DEFAULT 'enrolled',

    -- Denormalised onto the lead because a variant filter must narrow the LEAD
    -- scope. Filtering only events credits every variant with every other
    -- variant's replies, since replies attach to leads and not to events.
    variant_label     text,

    enrolled_at       timestamptz NOT NULL DEFAULT now(),
    bounced_at        timestamptz,
    replied_at        timestamptz,
    unsubscribed_at   timestamptz,
    completed_at      timestamptz,

    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT campaign_leads_status_valid CHECK (
        status IN ('enrolled', 'in_flight', 'bounced', 'replied',
                   'unsubscribed', 'completed', 'stopped')
    )
);

CREATE UNIQUE INDEX campaign_leads_campaign_contact_key
    ON campaign_leads (campaign_id, contact_id);
CREATE UNIQUE INDEX campaign_leads_provider_lead_key
    ON campaign_leads (campaign_id, provider_lead_id)
    WHERE provider_lead_id IS NOT NULL;
CREATE INDEX campaign_leads_contact_idx ON campaign_leads (contact_id);
CREATE INDEX campaign_leads_variant_idx ON campaign_leads (campaign_id, variant_label);
-- delivered = sent - bounced, so the delivered-lead scan is "not bounced".
CREATE INDEX campaign_leads_delivered_idx ON campaign_leads (campaign_id)
    WHERE bounced_at IS NULL;

CREATE TRIGGER campaign_leads_set_updated_at BEFORE UPDATE ON campaign_leads
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

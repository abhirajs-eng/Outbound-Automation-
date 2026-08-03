-- 0003 events, replies, signals, experiments.
--
-- Every table here is written by a repeatable sync. None of them may key on a
-- provider timestamp: provider timestamps drift in precision between syncs
-- (12:04:31 vs 12:04:31.472), so a natural key ending in one double-counts.

-- ------------------------------------------------------------- email_events

CREATE TABLE email_events (
    id                bigserial PRIMARY KEY,
    campaign_lead_id  bigint NOT NULL
        REFERENCES campaign_leads (id) ON DELETE CASCADE,
    step              int,
    variant_label     text,
    event_type        text NOT NULL,
    occurred_at       timestamptz NOT NULL,

    -- Provider event id when present, else
    -- sha256(campaign_lead_id, step, variant, event_type, occurred_at
    --        truncated to the second).
    event_fingerprint text NOT NULL,
    provider_event_id text,

    detail            jsonb NOT NULL DEFAULT '{}'::jsonb,
    synced_at         timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT email_events_type_valid CHECK (
        event_type IN ('sent', 'delivered', 'bounced', 'opened', 'clicked',
                       'replied', 'unsubscribed', 'spam_complaint')
    )
);

CREATE UNIQUE INDEX email_events_fingerprint_key ON email_events (event_fingerprint);
CREATE INDEX email_events_lead_idx ON email_events (campaign_lead_id);
CREATE INDEX email_events_type_time_idx ON email_events (event_type, occurred_at);
-- Metric cuts by send day/hour read this.
CREATE INDEX email_events_sent_idx ON email_events (occurred_at)
    WHERE event_type = 'sent';


-- ------------------------------------------------------------------ replies

CREATE TABLE replies (
    id                  bigserial PRIMARY KEY,
    campaign_lead_id    bigint NOT NULL
        REFERENCES campaign_leads (id) ON DELETE CASCADE,
    step                int,
    received_at         timestamptz NOT NULL,
    from_email          text,
    subject             text,
    body                text,

    dedupe_key          text NOT NULL,
    provider_message_id text,

    synced_at           timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX replies_dedupe_key ON replies (dedupe_key);
CREATE UNIQUE INDEX replies_provider_message_key
    ON replies (provider_message_id) WHERE provider_message_id IS NOT NULL;
CREATE INDEX replies_lead_idx ON replies (campaign_lead_id);
CREATE INDEX replies_received_idx ON replies (received_at);


-- Dual classification: two independent classifiers, disagreements surfaced for
-- a human rather than silently resolved by picking one.
CREATE TABLE reply_classifications (
    id             bigserial PRIMARY KEY,
    reply_id       bigint NOT NULL REFERENCES replies (id) ON DELETE CASCADE,
    classifier     text NOT NULL,
    label          text NOT NULL,
    confidence     numeric(4,3),
    rationale      text,
    created_at     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT reply_classifications_label_valid CHECK (
        label IN ('positive', 'neutral', 'negative', 'out_of_office',
                  'unsubscribe', 'referral', 'auto_reply')
    ),
    CONSTRAINT reply_classifications_confidence_range CHECK (
        confidence IS NULL OR confidence BETWEEN 0 AND 1
    )
);

CREATE UNIQUE INDEX reply_classifications_reply_classifier_key
    ON reply_classifications (reply_id, classifier);
CREATE INDEX reply_classifications_label_idx ON reply_classifications (label);


-- Resolved label per reply. Written only when classifiers agree or a human
-- adjudicates, so positive_rate never depends on an unreviewed coin flip.
CREATE TABLE reply_resolutions (
    reply_id        bigint PRIMARY KEY REFERENCES replies (id) ON DELETE CASCADE,
    label           text NOT NULL,
    resolved_by     text NOT NULL,
    disagreement    boolean NOT NULL DEFAULT false,
    resolved_at     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT reply_resolutions_label_valid CHECK (
        label IN ('positive', 'neutral', 'negative', 'out_of_office',
                  'unsubscribe', 'referral', 'auto_reply')
    ),
    CONSTRAINT reply_resolutions_resolved_by_valid CHECK (
        resolved_by IN ('agreement', 'human')
    )
);

CREATE INDEX reply_resolutions_label_idx ON reply_resolutions (label);
CREATE INDEX reply_resolutions_open_disagreements_idx ON reply_resolutions (resolved_at)
    WHERE disagreement = true;


-- ------------------------------------------------------------------ signals

CREATE TABLE signals (
    id             bigserial PRIMARY KEY,
    contact_id     bigint REFERENCES contacts (id) ON DELETE CASCADE,
    company_id     bigint REFERENCES companies (id) ON DELETE CASCADE,

    signal_type    text NOT NULL,
    provider       text NOT NULL,
    url            text,
    excerpt        text,
    observed_at    timestamptz NOT NULL,

    -- Without this a re-scan double-boosts every priority score it touches.
    dedupe_key     text NOT NULL,

    review_status  text NOT NULL DEFAULT 'pending',
    reviewed_by    text,
    reviewed_at    timestamptz,

    detail         jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT signals_type_valid CHECK (
        signal_type IN ('new_office', 'vendor_complaint', 'return_to_office',
                        'funding_announcement', 'hiring_onsite',
                        'city_expansion', 'team_growth')
    ),
    CONSTRAINT signals_provider_valid CHECK (
        provider IN ('manual', 'x_api', 'apify')
    ),
    CONSTRAINT signals_review_status_valid CHECK (
        review_status IN ('pending', 'accepted', 'rejected')
    ),
    CONSTRAINT signals_attached_to_something CHECK (
        contact_id IS NOT NULL OR company_id IS NOT NULL
    ),
    CONSTRAINT signals_reviewed_together CHECK (
        (review_status = 'pending') = (reviewed_at IS NULL)
    )
);

CREATE UNIQUE INDEX signals_dedupe_key ON signals (dedupe_key);
CREATE INDEX signals_contact_idx ON signals (contact_id);
CREATE INDEX signals_company_idx ON signals (company_id);
-- Review inbox: oldest pending first.
CREATE INDEX signals_pending_idx ON signals (observed_at DESC)
    WHERE review_status = 'pending';
-- Decay scoring reads accepted signals by recency.
CREATE INDEX signals_accepted_idx ON signals (observed_at DESC)
    WHERE review_status = 'accepted';


-- -------------------------------------------------------------- experiments

CREATE TABLE experiments (
    id                  bigserial PRIMARY KEY,
    campaign_id         bigint NOT NULL REFERENCES campaigns (id) ON DELETE CASCADE,
    sequence_step_id    bigint REFERENCES sequence_steps (id) ON DELETE SET NULL,
    name                text NOT NULL,

    -- positive_reply_rate by default; meetings_booked needs ~4x the sample and
    -- is tracked as a guardrail rather than used for the decision.
    decision_metric     text NOT NULL DEFAULT 'positive_reply_rate',
    min_delivered_per_variant int NOT NULL DEFAULT 400,

    status              text NOT NULL DEFAULT 'running',
    started_at          timestamptz NOT NULL DEFAULT now(),
    concluded_at        timestamptz,

    CONSTRAINT experiments_metric_valid CHECK (
        decision_metric IN ('positive_reply_rate', 'reply_rate', 'meeting_rate')
    ),
    CONSTRAINT experiments_status_valid CHECK (
        status IN ('running', 'winner_declared', 'stopped_futile',
                   'inconclusive', 'abandoned')
    ),
    CONSTRAINT experiments_min_sample_positive CHECK (min_delivered_per_variant > 0),
    CONSTRAINT experiments_concluded_together CHECK (
        (status = 'running') = (concluded_at IS NULL)
    )
);

CREATE UNIQUE INDEX experiments_name_key ON experiments (lower(name));
CREATE INDEX experiments_campaign_idx ON experiments (campaign_id);


-- One row per evaluation, so a decision can be re-read later with the numbers
-- it was actually made on. Point estimates are never stored without intervals.
CREATE TABLE experiment_evaluations (
    id                  bigserial PRIMARY KEY,
    experiment_id       bigint NOT NULL REFERENCES experiments (id) ON DELETE CASCADE,
    evaluated_at        timestamptz NOT NULL DEFAULT now(),

    variant_a           text NOT NULL,
    variant_b           text NOT NULL,
    delivered_a         int NOT NULL,
    delivered_b         int NOT NULL,
    conversions_a       int NOT NULL,
    conversions_b       int NOT NULL,

    z_p_value           numeric(8,6),
    bayes_prob_b_gt_a   numeric(8,6),
    diff_ci_low         numeric(8,6),
    diff_ci_high        numeric(8,6),

    min_sample_met      boolean NOT NULL,
    outcome             text NOT NULL,
    days_to_decision    int,
    detail              jsonb NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT experiment_evaluations_outcome_valid CHECK (
        outcome IN ('insufficient_sample', 'no_difference', 'winner_a',
                    'winner_b', 'futile_a', 'futile_b')
    ),
    CONSTRAINT experiment_evaluations_counts_sane CHECK (
        delivered_a >= 0 AND delivered_b >= 0
        AND conversions_a BETWEEN 0 AND delivered_a
        AND conversions_b BETWEEN 0 AND delivered_b
    )
);

CREATE INDEX experiment_evaluations_experiment_idx
    ON experiment_evaluations (experiment_id, evaluated_at DESC);


-- ----------------------------------------------------- hubspot_webhook_events
-- HubSpot notifies us of rep-side changes. Retries are expected, so receipts
-- are deduped on HubSpot's own event id.

CREATE TABLE hubspot_webhook_events (
    id                bigserial PRIMARY KEY,
    hubspot_event_id  text NOT NULL,
    subscription_type text NOT NULL,
    object_id         text NOT NULL,
    occurred_at       timestamptz NOT NULL,
    payload           jsonb NOT NULL,
    processed_at      timestamptz,
    received_at       timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX hubspot_webhook_events_event_key ON hubspot_webhook_events (hubspot_event_id);
CREATE INDEX hubspot_webhook_events_unprocessed_idx ON hubspot_webhook_events (received_at)
    WHERE processed_at IS NULL;

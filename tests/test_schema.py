"""Schema guarantees.

These are the constraints the application is allowed to rely on. If any of them
is enforced only in Python, a bad row arrives eventually -- from a migration, a
manual fix, or a code path that forgot.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError


def _seq_version(conn, *, compliant: bool) -> int:
    conn.execute(
        text("INSERT INTO sequences (id, name) VALUES (900, 'test-seq') "
             "ON CONFLICT DO NOTHING")
    )
    return conn.execute(
        text(
            "INSERT INTO sequence_versions "
            "(sequence_id, version, content_hash, has_unsubscribe, "
            " has_physical_address) "
            "VALUES (900, :v, :h, :u, :p) RETURNING id"
        ),
        {
            "v": 1 if compliant else 2,
            "h": "hash-ok" if compliant else "hash-bad",
            "u": compliant,
            "p": compliant,
        },
    ).scalar_one()


# ------------------------------------------------------- the approval gate

def test_campaign_cannot_be_active_without_an_approver(conn):
    version = _seq_version(conn, compliant=True)
    with pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO campaigns (name, sequence_version_id, status, launched_at) "
                "VALUES ('no-approver', :v, 'active', now())"
            ),
            {"v": version},
        )


def test_campaign_cannot_be_active_without_a_launch_timestamp(conn):
    version = _seq_version(conn, compliant=True)
    with pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO campaigns (name, sequence_version_id, status, "
                "approved_by, approved_at) "
                "VALUES ('no-launch', :v, 'active', 'kenny', now())"
            ),
            {"v": version},
        )


def test_fully_approved_campaign_activates(conn):
    version = _seq_version(conn, compliant=True)
    campaign_id = conn.execute(
        text(
            "INSERT INTO campaigns (name, sequence_version_id, status, "
            "approved_by, approved_at, launched_at) "
            "VALUES ('approved', :v, 'active', 'kenny', now(), now()) RETURNING id"
        ),
        {"v": version},
    ).scalar_one()
    assert campaign_id


# ------------------------------------------------------------- CAN-SPAM

def test_non_compliant_sequence_blocks_activation(conn):
    """Blocked, not warned. The trigger raises."""
    version = _seq_version(conn, compliant=False)
    with pytest.raises(DBAPIError) as excinfo:
        conn.execute(
            text(
                "INSERT INTO campaigns (name, sequence_version_id, status, "
                "approved_by, approved_at, launched_at) "
                "VALUES ('bad-copy', :v, 'active', 'kenny', now(), now())"
            ),
            {"v": version},
        )
    assert "CAN-SPAM" in str(excinfo.value)


def test_non_compliant_sequence_can_still_be_drafted(conn):
    """Draft is fine -- the gate is on activation, not on authoring."""
    version = _seq_version(conn, compliant=False)
    assert conn.execute(
        text(
            "INSERT INTO campaigns (name, sequence_version_id, status) "
            "VALUES ('draft-bad-copy', :v, 'draft') RETURNING id"
        ),
        {"v": version},
    ).scalar_one()


# ------------------------------------------------------------ idempotency

def test_email_event_fingerprint_is_unique(conn):
    lead_id = _campaign_lead(conn)
    for _ in range(1):
        conn.execute(
            text(
                "INSERT INTO email_events (campaign_lead_id, step, event_type, "
                "occurred_at, event_fingerprint) "
                "VALUES (:l, 1, 'sent', now(), 'fp-1')"
            ),
            {"l": lead_id},
        )
    with pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO email_events (campaign_lead_id, step, event_type, "
                "occurred_at, event_fingerprint) "
                "VALUES (:l, 1, 'sent', now(), 'fp-1')"
            ),
            {"l": lead_id},
        )


def test_a_contact_enrolls_in_a_campaign_only_once(conn):
    lead_id = _campaign_lead(conn)
    campaign_id, contact_id = conn.execute(
        text("SELECT campaign_id, contact_id FROM campaign_leads WHERE id = :i"),
        {"i": lead_id},
    ).one()
    with pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO campaign_leads (campaign_id, contact_id) "
                "VALUES (:c, :p)"
            ),
            {"c": campaign_id, "p": contact_id},
        )


def test_signal_dedupe_key_is_unique(conn):
    company_id = conn.execute(
        text("INSERT INTO companies (name) VALUES ('Sig Co') RETURNING id")
    ).scalar_one()
    for expect_failure in (False, True):
        stmt = text(
            "INSERT INTO signals (company_id, signal_type, provider, observed_at, "
            "dedupe_key) VALUES (:c, 'new_office', 'manual', now(), 'dk-1')"
        )
        if expect_failure:
            with pytest.raises(IntegrityError):
                conn.execute(stmt, {"c": company_id})
        else:
            conn.execute(stmt, {"c": company_id})


# --------------------------------------------------- partial unique indexes

def test_two_contacts_without_an_apollo_id_do_not_collide(conn):
    """NULL apollo_person_id is normal for a manually added contact."""
    for name in ("a", "b"):
        conn.execute(
            text("INSERT INTO contacts (first_name) VALUES (:n)"), {"n": name}
        )


def test_duplicate_apollo_person_id_is_rejected(conn):
    conn.execute(text("INSERT INTO contacts (apollo_person_id) VALUES ('dup')"))
    with pytest.raises(IntegrityError):
        conn.execute(text("INSERT INTO contacts (apollo_person_id) VALUES ('dup')"))


def test_email_uniqueness_is_case_insensitive(conn):
    conn.execute(
        text("INSERT INTO contacts (email, email_revealed_at) "
             "VALUES ('Jane@Acme.com', now())")
    )
    with pytest.raises(IntegrityError):
        conn.execute(
            text("INSERT INTO contacts (email, email_revealed_at) "
                 "VALUES ('jane@acme.com', now())")
        )


# ------------------------------------------------------------ value checks

def test_office_signal_requires_evidence(conn):
    """A non-unknown signal without evidence is not auditable, so it is invalid."""
    with pytest.raises(IntegrityError):
        conn.execute(
            text("INSERT INTO companies (name, office_signal) "
                 "VALUES ('No Evidence', 'confirmed_in_office')")
        )


def test_office_signal_with_evidence_is_accepted(conn):
    assert conn.execute(
        text(
            "INSERT INTO companies (name, office_signal, office_signal_evidence) "
            "VALUES ('Evidenced', 'confirmed_in_office', "
            "'[{\"url\": \"https://example.com\"}]'::jsonb) RETURNING id"
        )
    ).scalar_one()


def test_mailbox_daily_cap_above_fifty_is_rejected(conn):
    """Cold mailboxes die above ~50/day, so the cap is enforced, not advised."""
    with pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO mailboxes (provider_account_id, email, sending_domain, "
                "daily_cap) VALUES ('m1', 'a@b.com', 'b.com', 80)"
            )
        )


def test_suppression_value_must_be_normalised(conn):
    with pytest.raises(IntegrityError):
        conn.execute(
            text("INSERT INTO suppressions (scope, value, reason, source) "
                 "VALUES ('email', 'Jane@Acme.com', 'unsubscribe', 'test')")
        )


def test_contact_email_and_reveal_timestamp_move_together(conn):
    with pytest.raises(IntegrityError):
        conn.execute(
            text("INSERT INTO contacts (email) VALUES ('orphan@acme.com')")
        )


def test_experiment_conversions_cannot_exceed_delivered(conn):
    version = _seq_version(conn, compliant=True)
    campaign_id = conn.execute(
        text("INSERT INTO campaigns (name, sequence_version_id) "
             "VALUES ('exp-c', :v) RETURNING id"),
        {"v": version},
    ).scalar_one()
    experiment_id = conn.execute(
        text("INSERT INTO experiments (campaign_id, name) "
             "VALUES (:c, 'exp-1') RETURNING id"),
        {"c": campaign_id},
    ).scalar_one()
    with pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO experiment_evaluations (experiment_id, variant_a, "
                "variant_b, delivered_a, delivered_b, conversions_a, conversions_b, "
                "min_sample_met, outcome) "
                "VALUES (:e, 'A', 'B', 100, 100, 200, 5, true, 'no_difference')"
            ),
            {"e": experiment_id},
        )


# ------------------------------------------------------------------ helpers

def _campaign_lead(conn) -> int:
    version = _seq_version(conn, compliant=True)
    campaign_id = conn.execute(
        text("INSERT INTO campaigns (name, sequence_version_id) "
             "VALUES ('cl-campaign', :v) RETURNING id"),
        {"v": version},
    ).scalar_one()
    contact_id = conn.execute(
        text("INSERT INTO contacts (first_name) VALUES ('Lead') RETURNING id")
    ).scalar_one()
    return conn.execute(
        text("INSERT INTO campaign_leads (campaign_id, contact_id) "
             "VALUES (:c, :p) RETURNING id"),
        {"c": campaign_id, "p": contact_id},
    ).scalar_one()

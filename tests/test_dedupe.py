"""Idempotency keys.

The failure these guard against is not a crash -- it is a metric that drifts
upward every time a sync runs twice.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.dedupe import event_fingerprint, reply_dedupe_key, signal_dedupe_key

BASE = datetime(2026, 7, 30, 12, 4, 31, tzinfo=timezone.utc)


def test_timestamp_precision_drift_does_not_create_a_second_event():
    """The exact bug: 12:04:31 one sync, 12:04:31.472 the next."""
    coarse = event_fingerprint(
        campaign_lead_id=1, step=2, variant="A", event_type="sent", occurred_at=BASE
    )
    fine = event_fingerprint(
        campaign_lead_id=1, step=2, variant="A", event_type="sent",
        occurred_at=BASE.replace(microsecond=472000),
    )
    assert coarse == fine


def test_provider_event_id_wins_when_present():
    with_id = event_fingerprint(
        campaign_lead_id=1, step=2, variant="A", event_type="sent",
        occurred_at=BASE, provider_event_id="evt_123",
    )
    assert with_id == "provider:evt_123"


def test_provider_id_makes_otherwise_identical_events_distinct():
    a = event_fingerprint(
        campaign_lead_id=1, step=1, variant="A", event_type="opened",
        occurred_at=BASE, provider_event_id="evt_1",
    )
    b = event_fingerprint(
        campaign_lead_id=1, step=1, variant="A", event_type="opened",
        occurred_at=BASE, provider_event_id="evt_2",
    )
    assert a != b


def test_naive_timestamps_are_treated_as_utc():
    aware = event_fingerprint(
        campaign_lead_id=1, step=1, variant="A", event_type="sent", occurred_at=BASE
    )
    naive = event_fingerprint(
        campaign_lead_id=1, step=1, variant="A", event_type="sent",
        occurred_at=BASE.replace(tzinfo=None),
    )
    assert aware == naive


def test_same_event_in_a_different_timezone_is_the_same_event():
    other_tz = BASE.astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert event_fingerprint(
        campaign_lead_id=1, step=1, variant="A", event_type="sent", occurred_at=BASE
    ) == event_fingerprint(
        campaign_lead_id=1, step=1, variant="A", event_type="sent", occurred_at=other_tz
    )


def test_different_step_or_variant_are_different_events():
    def fp(step, variant):
        return event_fingerprint(
            campaign_lead_id=1, step=step, variant=variant,
            event_type="sent", occurred_at=BASE,
        )

    assert len({fp(1, "A"), fp(2, "A"), fp(1, "B")}) == 3


def test_reply_dedupe_survives_precision_drift():
    a = reply_dedupe_key(campaign_lead_id=7, received_at=BASE, body="sure, next week")
    b = reply_dedupe_key(
        campaign_lead_id=7, received_at=BASE.replace(microsecond=900000),
        body="sure, next week",
    )
    assert a == b


def test_reply_dedupe_distinguishes_different_bodies():
    a = reply_dedupe_key(campaign_lead_id=7, received_at=BASE, body="yes")
    b = reply_dedupe_key(campaign_lead_id=7, received_at=BASE, body="no")
    assert a != b


def test_signal_dedupe_keys_on_url_so_a_rescan_does_not_double_boost():
    first = signal_dedupe_key(
        signal_type="new_office", url="https://x.com/a/status/1",
        company_id=3, contact_id=None, observed_at=BASE,
    )
    rescan = signal_dedupe_key(
        signal_type="new_office", url="https://X.com/a/status/1 ",
        company_id=3, contact_id=None,
        observed_at=BASE + timedelta(hours=6),   # re-scan sees a later observed_at
    )
    assert first == rescan


def test_signal_without_url_falls_back_to_entity_and_time():
    a = signal_dedupe_key(
        signal_type="team_growth", url=None, company_id=3,
        contact_id=None, observed_at=BASE,
    )
    b = signal_dedupe_key(
        signal_type="team_growth", url=None, company_id=4,
        contact_id=None, observed_at=BASE,
    )
    assert a != b

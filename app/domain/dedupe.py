"""Idempotency keys.

The rule these all obey: never key on a raw provider timestamp. Providers
change timestamp precision between syncs -- the same event arrives as
12:04:31 one day and 12:04:31.472 the next -- and a natural key ending in one
silently double-counts on re-sync. Every timestamp here is truncated to the
second before it reaches the hash.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone


def _truncate_to_second(moment: datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _digest(*parts: object) -> str:
    joined = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def event_fingerprint(
    *,
    campaign_lead_id: int,
    step: int | None,
    variant: str | None,
    event_type: str,
    occurred_at: datetime,
    provider_event_id: str | None = None,
) -> str:
    """Provider event id when present, else a hash of the natural key."""
    if provider_event_id:
        return f"provider:{provider_event_id}"
    return _digest(
        campaign_lead_id,
        step,
        variant,
        event_type,
        _truncate_to_second(occurred_at),
    )


def reply_dedupe_key(
    *,
    campaign_lead_id: int,
    received_at: datetime,
    body: str | None,
    provider_message_id: str | None = None,
) -> str:
    if provider_message_id:
        return f"provider:{provider_message_id}"
    # Body is hashed rather than stored in the key so a long reply does not
    # produce an unbounded index entry.
    body_digest = hashlib.sha256((body or "").strip().encode("utf-8")).hexdigest()[:32]
    return _digest(campaign_lead_id, _truncate_to_second(received_at), body_digest)


def signal_dedupe_key(
    *,
    signal_type: str,
    url: str | None,
    company_id: int | None,
    contact_id: int | None,
    observed_at: datetime,
) -> str:
    """A re-scan that re-emits the same post must not boost priority twice."""
    if url:
        return _digest(signal_type, url.strip().lower())
    return _digest(
        signal_type, company_id, contact_id, _truncate_to_second(observed_at)
    )

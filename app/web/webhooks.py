"""HubSpot webhook receiver.

Two properties this endpoint must have, because it is an internet-reachable
write path into the CRM mirror:

1. **Unsigned requests are refused**, including when no secret is configured.
2. **Receipts are idempotent.** HubSpot retries on any non-2xx, so the same
   event arrives more than once as a matter of course. Dedup is on HubSpot's
   own event id, enforced by a unique index rather than by a lookup-then-insert
   race.

The endpoint stores and acknowledges. Processing happens in a job, so a slow
handler cannot cause HubSpot to retry a delivery we already have.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Header, Request, Response
from sqlalchemy import text

from app.domain.webhook_auth import verify_signature

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhooks/hubspot")
async def receive_hubspot_webhook(
    request: Request,
    response: Response,
    x_hubspot_signature_v3: str | None = Header(default=None),
    x_hubspot_request_timestamp: str | None = Header(default=None),
) -> dict:
    settings = request.app.state.settings

    # Raw body, not re-serialised JSON: key order and whitespace are part of
    # what was signed.
    raw_body = (await request.body()).decode("utf-8")

    check = verify_signature(
        secret=getattr(settings, "hubspot_webhook_secret", None),
        signature=x_hubspot_signature_v3,
        method="POST",
        uri=str(request.url),
        body=raw_body,
        timestamp=x_hubspot_request_timestamp,
        now_ms=int(time.time() * 1000),
    )
    if not check.valid:
        logger.warning("rejected hubspot webhook: %s", check.reason)
        response.status_code = 401
        return {"accepted": False, "reason": check.reason}

    import json

    try:
        events = json.loads(raw_body)
    except json.JSONDecodeError:
        response.status_code = 400
        return {"accepted": False, "reason": "body is not valid JSON"}

    if isinstance(events, dict):
        events = [events]

    stored = 0
    duplicates = 0

    with request.app.state.engine.begin() as conn:
        for event in events:
            event_id = str(event.get("eventId") or "")
            if not event_id:
                continue

            occurred_ms = event.get("occurredAt")
            occurred_at = (
                datetime.fromtimestamp(occurred_ms / 1000, timezone.utc)
                if isinstance(occurred_ms, (int, float))
                else datetime.now(timezone.utc)
            )

            # ON CONFLICT rather than a SELECT-then-INSERT: two concurrent
            # retries would both pass the lookup.
            result = conn.execute(
                text(
                    "INSERT INTO hubspot_webhook_events "
                    "(hubspot_event_id, subscription_type, object_id, "
                    " occurred_at, payload) "
                    "VALUES (:eid, :stype, :oid, :occ, CAST(:payload AS jsonb)) "
                    "ON CONFLICT (hubspot_event_id) DO NOTHING "
                    "RETURNING id"
                ),
                {
                    "eid": event_id,
                    "stype": str(event.get("subscriptionType") or "unknown"),
                    "oid": str(event.get("objectId") or ""),
                    "occ": occurred_at,
                    "payload": json.dumps(event),
                },
            ).first()

            if result is None:
                duplicates += 1
            else:
                stored += 1

    logger.info(
        "hubspot webhook accepted", extra={"stored": stored, "duplicates": duplicates}
    )
    # 200 even for an all-duplicate delivery: a non-2xx makes HubSpot retry
    # something we already hold.
    return {"accepted": True, "stored": stored, "duplicates": duplicates}

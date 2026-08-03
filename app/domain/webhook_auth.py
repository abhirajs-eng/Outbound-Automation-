"""HubSpot webhook signature verification. Pure: no framework, no network.

A webhook receiver that writes to the CRM mirror is a write path anyone on the
internet can reach. Verification is mandatory here, not optional: when no secret
is configured the receiver refuses requests outright rather than accepting
unsigned ones, because "accept everything in dev" is how an unauthenticated
write endpoint reaches production.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass

#: HubSpot rejects replays outside a five-minute window; we match that.
MAX_TIMESTAMP_SKEW_MS = 5 * 60 * 1000


class SignatureError(Exception):
    """Raised when a webhook cannot be authenticated."""


@dataclass(frozen=True)
class SignatureCheck:
    valid: bool
    reason: str = ""


def build_signature_base(
    *, method: str, uri: str, body: str, timestamp: str
) -> str:
    """HubSpot v3 signs method + full URI + raw body + timestamp, concatenated."""
    return f"{method.upper()}{uri}{body}{timestamp}"


def compute_signature(secret: str, base: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"), base.encode("utf-8"), hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def verify_signature(
    *,
    secret: str | None,
    signature: str | None,
    method: str,
    uri: str,
    body: str,
    timestamp: str | None,
    now_ms: int,
) -> SignatureCheck:
    """Verify a HubSpot v3 webhook signature.

    `body` must be the raw request body exactly as received. Re-serialising
    parsed JSON changes key order and whitespace, and the signature stops
    matching for reasons that look like a HubSpot bug.
    """
    if not secret:
        return SignatureCheck(
            False,
            "HUBSPOT_WEBHOOK_SECRET is not configured; refusing to accept "
            "unsigned webhooks",
        )
    if not signature:
        return SignatureCheck(False, "missing X-HubSpot-Signature-V3 header")
    if not timestamp:
        return SignatureCheck(False, "missing X-HubSpot-Request-Timestamp header")

    try:
        sent_at = int(timestamp)
    except ValueError:
        return SignatureCheck(False, "timestamp header is not an integer")

    # Guards replay. Also rejects timestamps from the future, which would
    # otherwise let an attacker mint a signature with an unbounded lifetime.
    if abs(now_ms - sent_at) > MAX_TIMESTAMP_SKEW_MS:
        return SignatureCheck(
            False, f"timestamp outside the {MAX_TIMESTAMP_SKEW_MS // 60000}m window"
        )

    expected = compute_signature(
        secret, build_signature_base(method=method, uri=uri, body=body,
                                     timestamp=timestamp)
    )
    # Constant-time: a plain == leaks the signature one byte at a time.
    if not hmac.compare_digest(expected, signature):
        return SignatureCheck(False, "signature mismatch")

    return SignatureCheck(True)

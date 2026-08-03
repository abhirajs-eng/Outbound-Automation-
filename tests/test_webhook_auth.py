"""Webhook signature verification.

This guards an internet-reachable write path into the CRM mirror, so the
negative cases matter more than the positive one.
"""

from __future__ import annotations

from app.domain.webhook_auth import (
    MAX_TIMESTAMP_SKEW_MS,
    build_signature_base,
    compute_signature,
    verify_signature,
)

SECRET = "shhh-private-app-secret"
URI = "https://ops.example.com/webhooks/hubspot"
BODY = '[{"eventId":1,"subscriptionType":"contact.propertyChange"}]'
NOW_MS = 1_754_222_000_000


def _sign(body: str = BODY, timestamp: str = str(NOW_MS), uri: str = URI) -> str:
    return compute_signature(
        SECRET,
        build_signature_base(method="POST", uri=uri, body=body, timestamp=timestamp),
    )


def _verify(**overrides):
    kwargs = dict(
        secret=SECRET,
        signature=_sign(),
        method="POST",
        uri=URI,
        body=BODY,
        timestamp=str(NOW_MS),
        now_ms=NOW_MS,
    )
    kwargs.update(overrides)
    return verify_signature(**kwargs)


def test_a_correctly_signed_request_is_accepted():
    assert _verify().valid is True


def test_missing_secret_refuses_rather_than_waving_it_through():
    """'Accept everything when unconfigured' is how this reaches production."""
    check = _verify(secret=None)
    assert check.valid is False
    assert "not configured" in check.reason


def test_missing_signature_is_rejected():
    assert _verify(signature=None).valid is False


def test_missing_timestamp_is_rejected():
    assert _verify(timestamp=None).valid is False


def test_non_integer_timestamp_is_rejected():
    assert _verify(timestamp="not-a-number").valid is False


def test_a_tampered_body_is_rejected():
    """The signature covers the body, so any edit invalidates it."""
    tampered = BODY.replace("propertyChange", "deletion")
    assert _verify(body=tampered).valid is False


def test_a_different_uri_is_rejected():
    assert _verify(uri="https://evil.example.com/webhooks/hubspot").valid is False


def test_a_different_method_is_rejected():
    assert _verify(method="GET").valid is False


def test_a_wrong_secret_is_rejected():
    assert _verify(secret="wrong-secret").valid is False


def test_a_replayed_request_outside_the_window_is_rejected():
    old = NOW_MS - MAX_TIMESTAMP_SKEW_MS - 1000
    check = verify_signature(
        secret=SECRET, signature=_sign(timestamp=str(old)), method="POST",
        uri=URI, body=BODY, timestamp=str(old), now_ms=NOW_MS,
    )
    assert check.valid is False
    assert "window" in check.reason


def test_a_request_just_inside_the_window_is_accepted():
    recent = NOW_MS - MAX_TIMESTAMP_SKEW_MS + 1000
    check = verify_signature(
        secret=SECRET, signature=_sign(timestamp=str(recent)), method="POST",
        uri=URI, body=BODY, timestamp=str(recent), now_ms=NOW_MS,
    )
    assert check.valid is True


def test_a_future_timestamp_is_rejected():
    """Otherwise a captured signature has an unbounded lifetime."""
    future = NOW_MS + MAX_TIMESTAMP_SKEW_MS + 1000
    check = verify_signature(
        secret=SECRET, signature=_sign(timestamp=str(future)), method="POST",
        uri=URI, body=BODY, timestamp=str(future), now_ms=NOW_MS,
    )
    assert check.valid is False


def test_signature_base_is_method_uri_body_timestamp_concatenated():
    assert build_signature_base(
        method="post", uri="https://x/y", body="{}", timestamp="123"
    ) == "POSThttps://x/y{}123"

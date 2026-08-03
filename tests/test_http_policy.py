"""The retry policy.

The distinction under test: a timeout on a mutating call means the outcome is
unknown, so retrying may double-send. An explicit 429 means the server did not
process the request, so retrying is safe. Collapsing these into one rule gives
you either double sends or needless failures.
"""

from __future__ import annotations

import pytest

from app.adapters.http import (
    HttpResponse,
    RateLimiter,
    TransportError,
    call_with_policy,
)


class FakeTransport:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def request(self, method, url, **kwargs):
        self.calls += 1
        outcome = self._responses.pop(0) if self._responses else HttpResponse(200, {})
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _call(transport, *, mutating, **kwargs):
    return call_with_policy(
        transport, "POST", "https://api.hubapi.com/x",
        mutating=mutating, sleep=lambda _s: None, **kwargs
    )


# ------------------------------------------------------ mutating vs not

def test_a_timeout_on_a_mutating_call_is_never_retried():
    """The request may have landed. A duplicate send is worse than a failure."""
    transport = FakeTransport([TransportError("timeout")])
    with pytest.raises(TransportError):
        _call(transport, mutating=True)
    assert transport.calls == 1


def test_a_timeout_on_a_read_is_retried():
    transport = FakeTransport(
        [TransportError("timeout"), TransportError("timeout"), HttpResponse(200, {"ok": True})]
    )
    response = _call(transport, mutating=False)
    assert response.ok
    assert transport.calls == 3


def test_a_429_on_a_mutating_call_is_retried():
    """Explicit rejection: nothing was processed, so this is safe."""
    transport = FakeTransport([HttpResponse(429, {}), HttpResponse(200, {"ok": True})])
    response = _call(transport, mutating=True)
    assert response.ok
    assert transport.calls == 2


def test_a_500_on_a_mutating_call_is_not_retried():
    """A 500 can follow a partial write."""
    transport = FakeTransport([HttpResponse(500, {}), HttpResponse(200, {})])
    response = _call(transport, mutating=True)
    assert response.status == 500
    assert transport.calls == 1


def test_a_500_on_a_read_is_retried():
    transport = FakeTransport([HttpResponse(500, {}), HttpResponse(200, {"ok": True})])
    assert _call(transport, mutating=False).ok
    assert transport.calls == 2


def test_a_400_is_never_retried():
    """A malformed request stays malformed."""
    transport = FakeTransport([HttpResponse(400, {"message": "bad"})])
    response = _call(transport, mutating=False)
    assert response.status == 400
    assert transport.calls == 1


def test_a_403_is_not_retried():
    transport = FakeTransport([HttpResponse(403, {"message": "missing scope"})])
    assert _call(transport, mutating=False).status == 403
    assert transport.calls == 1


def test_retries_are_bounded():
    transport = FakeTransport([HttpResponse(429, {})] * 10)
    response = _call(transport, mutating=False, attempts=3)
    assert response.status == 429
    assert transport.calls == 3


def test_retry_after_header_is_honoured():
    slept: list[float] = []
    transport = FakeTransport(
        [HttpResponse(429, {}, {"Retry-After": "7"}), HttpResponse(200, {})]
    )
    call_with_policy(
        transport, "GET", "https://api.hubapi.com/x", mutating=False,
        sleep=slept.append,
    )
    assert 7.0 in slept


# ------------------------------------------------------------ rate limiter

def test_limiter_allows_up_to_the_cap_without_waiting():
    limiter = RateLimiter(max_calls=3, per_seconds=10.0)
    waits = [limiter.acquire(now=100.0 + i * 0.1) for i in range(3)]
    assert all(w == 0.0 for w in waits)


def test_limiter_reports_a_wait_once_the_window_is_full():
    limiter = RateLimiter(max_calls=2, per_seconds=10.0)
    limiter.acquire(now=100.0)
    limiter.acquire(now=100.5)
    assert limiter.acquire(now=101.0) > 0


def test_limiter_frees_slots_once_calls_age_out():
    limiter = RateLimiter(max_calls=2, per_seconds=10.0)
    limiter.acquire(now=100.0)
    limiter.acquire(now=100.5)
    # Both original calls are now outside the 10s window.
    assert limiter.acquire(now=115.0) == 0.0


def test_limiter_rejects_a_nonsense_configuration():
    with pytest.raises(ValueError):
        RateLimiter(max_calls=0, per_seconds=10.0)

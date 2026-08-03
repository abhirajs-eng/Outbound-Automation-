"""HTTP transport with rate limiting and a retry policy that knows what is safe.

The retry rule is more precise than "don't retry mutations", because the reason
matters:

- **Timeouts and connection errors on a mutating call are never retried.** The
  request may have landed. A duplicate campaign or a double send is worse than
  a failed request.
- **An explicit 429 on a mutating call is retried.** The server is telling us it
  did not process the request. That is a different fact from silence.
- **5xx on a mutating call is not retried.** A 500 can follow a partial write.

Splitting these is the difference between a client that is safe and one that is
merely cautious.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class TransportError(Exception):
    """Network-level failure. Whether the request landed is unknown."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: Any
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class HttpTransport(Protocol):
    """Minimal transport surface, so adapters can be tested without a network."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        timeout: float = 30.0,
    ) -> HttpResponse: ...


class RateLimiter:
    """Token bucket. HubSpot Free/Starter allows 100 requests per 10 seconds.

    Thread-safe because the scheduler and the web tier can both hold a client.
    """

    def __init__(self, max_calls: int, per_seconds: float) -> None:
        if max_calls <= 0 or per_seconds <= 0:
            raise ValueError("max_calls and per_seconds must be positive")
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self._timestamps: list[float] = []
        self._lock = threading.Lock()

    def acquire(self, *, now: float | None = None, sleep=time.sleep) -> float:
        """Block until a slot is free. Returns how long it waited."""
        waited = 0.0
        while True:
            with self._lock:
                current = now if now is not None else time.monotonic()
                cutoff = current - self.per_seconds
                self._timestamps = [t for t in self._timestamps if t > cutoff]
                if len(self._timestamps) < self.max_calls:
                    self._timestamps.append(current)
                    return waited
                # Wait exactly until the oldest call ages out of the window.
                delay = self._timestamps[0] - cutoff
            if now is not None:
                # Injected clock: report the wait rather than sleeping forever.
                return delay
            sleep(delay)
            waited += delay


class HttpxTransport:
    """Real transport. Isolated here so nothing else imports httpx."""

    def __init__(self, client: Any | None = None) -> None:
        if client is None:
            import httpx

            client = httpx.Client(follow_redirects=False)
        self._client = client

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        import httpx

        try:
            response = self._client.request(
                method, url, headers=headers, params=params, json=json, timeout=timeout
            )
        except httpx.TimeoutException as exc:
            raise TransportError(f"timeout calling {method} {url}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise TransportError(f"transport error on {method} {url}: {exc}") from exc

        try:
            body = response.json()
        except Exception:  # noqa: BLE001 - non-JSON error pages are normal
            body = response.text

        return HttpResponse(
            status=response.status_code,
            body=body,
            headers=dict(response.headers),
        )

    def close(self) -> None:
        self._client.close()


def call_with_policy(
    transport: HttpTransport,
    method: str,
    url: str,
    *,
    mutating: bool,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json: Any | None = None,
    timeout: float = 30.0,
    attempts: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    limiter: RateLimiter | None = None,
    rng: random.Random | None = None,
    sleep=time.sleep,
) -> HttpResponse:
    """Issue a request under the retry policy described in this module."""
    rand = rng or random.Random()
    last_error: Exception | None = None

    for attempt in range(attempts):
        if limiter is not None:
            limiter.acquire(sleep=sleep)

        try:
            response = transport.request(
                method, url, headers=headers, params=params, json=json, timeout=timeout
            )
        except TransportError as exc:
            # Outcome unknown. For a mutation that is the end of the road.
            if mutating:
                raise
            last_error = exc
            if attempt == attempts - 1:
                raise
            _backoff(attempt, base_delay, max_delay, rand, sleep)
            continue

        if response.ok:
            return response

        if response.status == 429:
            # Explicit rejection: nothing was processed, so a retry is safe
            # even for a mutation.
            retry_after = _retry_after_seconds(response)
            if attempt == attempts - 1:
                return response
            if retry_after is not None:
                sleep(retry_after)
            else:
                _backoff(attempt, base_delay, max_delay, rand, sleep)
            continue

        if 500 <= response.status < 600 and not mutating:
            if attempt == attempts - 1:
                return response
            _backoff(attempt, base_delay, max_delay, rand, sleep)
            continue

        # 4xx other than 429, or any 5xx on a mutation: hand it back.
        return response

    if last_error is not None:
        raise last_error
    raise TransportError(f"exhausted attempts calling {method} {url}")


def _backoff(
    attempt: int, base_delay: float, max_delay: float, rand: random.Random, sleep
) -> None:
    # Full jitter. Without it every client that failed together retries together.
    delay = min(base_delay * (2**attempt), max_delay)
    sleep(rand.uniform(0, delay))


def _retry_after_seconds(response: HttpResponse) -> float | None:
    raw = response.headers.get("Retry-After") or response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None

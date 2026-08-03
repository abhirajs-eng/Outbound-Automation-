"""Job execution: advisory locking, job_runs bookkeeping, retry helper.

Two decisions worth stating, because both have bitten a previous build:

1. Locks are Postgres advisory locks, not rows in a locks table. An advisory
   lock is released when the holding connection dies, so a job killed at 3am
   does not leave a row that blocks every run until a human notices.

2. The engine is passed to the job body through JobContext. A framework that
   only uses its engine for locking and bookkeeping, while the job body reaches
   for a global session, is a framework that lies about which database it wrote.
"""

from __future__ import annotations

import logging
import random
import time
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator, TypeVar

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import session_factory

logger = logging.getLogger(__name__)

T = TypeVar("T")


class JobSkipped(Exception):
    """Another runner holds the lock. Not an error."""


def lock_key(job_name: str) -> int:
    """Stable 32-bit key from the job name.

    zlib.crc32 rather than hash(): Python's hash is salted per process, so the
    same job name would produce a different key in every container.
    """
    return zlib.crc32(job_name.encode("utf-8"))


@dataclass
class JobContext:
    """Everything a job body is allowed to depend on."""

    job_name: str
    run_id: int
    engine: Engine
    sessions: sessionmaker[Session]
    detail: dict = field(default_factory=dict)

    items_in: int = 0
    items_out: int = 0
    credits_spent: int = 0

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.sessions()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def spend_credits(self, count: int, ceiling: int | None = None) -> None:
        """Record credit spend, refusing to blow through a run's ceiling."""
        if ceiling is not None and self.credits_spent + count > ceiling:
            raise RuntimeError(
                f"{self.job_name}: credit ceiling {ceiling} would be exceeded "
                f"({self.credits_spent} already spent, {count} more requested). "
                "Raise APOLLO_CREDIT_CEILING_PER_RUN deliberately or reduce batch size."
            )
        self.credits_spent += count


def execute_job(
    job_name: str,
    body: Callable[[JobContext], None],
    *,
    engine: Engine,
    blocking: bool = False,
) -> str:
    """Run `body` under an advisory lock, recording a job_runs row.

    Returns the terminal status: succeeded, failed, or skipped_locked.
    """
    sessions = session_factory(engine)
    key = lock_key(job_name)
    started = time.monotonic()

    lock_conn = engine.connect()
    try:
        sql = "SELECT pg_advisory_lock(:k)" if blocking else "SELECT pg_try_advisory_lock(:k)"
        acquired = lock_conn.execute(text(sql), {"k": key}).scalar()
        if not blocking and not acquired:
            logger.info("job %s skipped: lock held elsewhere", job_name)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO job_runs (job_name, status, finished_at, "
                        "duration_ms) VALUES (:n, 'skipped_locked', now(), 0)"
                    ),
                    {"n": job_name},
                )
            return "skipped_locked"

        with engine.begin() as conn:
            run_id = conn.execute(
                text(
                    "INSERT INTO job_runs (job_name, status) "
                    "VALUES (:n, 'running') RETURNING id"
                ),
                {"n": job_name},
            ).scalar_one()

        ctx = JobContext(
            job_name=job_name, run_id=run_id, engine=engine, sessions=sessions
        )

        try:
            body(ctx)
        except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
            duration = int((time.monotonic() - started) * 1000)
            logger.exception("job %s failed", job_name)
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE job_runs SET status='failed', finished_at=now(), "
                        "duration_ms=:d, error=:e, items_in=:i, items_out=:o, "
                        "credits_spent=:c, detail=CAST(:detail AS jsonb) WHERE id=:id"
                    ),
                    {
                        "d": duration,
                        "e": f"{type(exc).__name__}: {exc}"[:4000],
                        "i": ctx.items_in,
                        "o": ctx.items_out,
                        "c": ctx.credits_spent,
                        "detail": _json(ctx.detail),
                        "id": run_id,
                    },
                )
            raise

        duration = int((time.monotonic() - started) * 1000)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE job_runs SET status='succeeded', finished_at=now(), "
                    "duration_ms=:d, items_in=:i, items_out=:o, credits_spent=:c, "
                    "detail=CAST(:detail AS jsonb) WHERE id=:id"
                ),
                {
                    "d": duration,
                    "i": ctx.items_in,
                    "o": ctx.items_out,
                    "c": ctx.credits_spent,
                    "detail": _json(ctx.detail),
                    "id": run_id,
                },
            )
        logger.info(
            "job %s succeeded in %dms (in=%d out=%d credits=%d)",
            job_name, duration, ctx.items_in, ctx.items_out, ctx.credits_spent,
        )
        return "succeeded"
    finally:
        try:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
        finally:
            lock_conn.close()


def _json(value: dict) -> str:
    import json

    return json.dumps(value, default=str)


def with_retries(
    fn: Callable[[], T],
    *,
    attempts: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    mutating: bool = False,
    rng: random.Random | None = None,
) -> T:
    """Exponential backoff with jitter.

    `mutating=True` disables retries entirely. A duplicate campaign or a double
    send is worse than a failed request, and a timeout tells you nothing about
    whether the write landed.
    """
    if mutating:
        return fn()

    rand = rng or random.Random()
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised below
            last = exc
            if attempt == attempts - 1:
                break
            delay = min(base_delay * (2**attempt), max_delay)
            # Full jitter: without it, every client that failed together
            # retries together.
            time.sleep(rand.uniform(0, delay))
    assert last is not None
    raise last

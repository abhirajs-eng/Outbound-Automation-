"""Job registry and scheduler process.

The scheduler runs as its own process, not inside a web worker. Scaling the web
tier to three replicas must not turn one 6am job into three.

Scheduled jobs use REST with keys. MCP connectors require a live agent session
and are the wrong transport for a cron -- they are fine for interactive work.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.engine import Engine

from app.jobs.framework import JobContext, execute_job

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JobSpec:
    name: str
    body: Callable[[JobContext], None]
    cron: str
    description: str
    #: The build phase that wires this job up. Jobs land here registered but
    #: inert so the runbook and the UI can name what is not running yet,
    #: instead of showing an empty schedule that reads as "nothing to do".
    enabled: bool = False
    phase: int = 1


REGISTRY: dict[str, JobSpec] = {}


def register(spec: JobSpec) -> JobSpec:
    if spec.name in REGISTRY:
        raise ValueError(f"duplicate job name: {spec.name}")
    REGISTRY[spec.name] = spec
    return spec


def _heartbeat(ctx: JobContext) -> None:
    """Proves the runner, the lock and the job_runs write path all work.

    Reads through ctx.session() specifically, so a regression where the job
    body talks to a different database than its bookkeeping shows up here.
    """
    from sqlalchemy import text

    with ctx.session() as session:
        applied = session.execute(
            text("SELECT count(*) FROM schema_migrations")
        ).scalar_one()
    ctx.detail["migrations_applied"] = applied
    ctx.items_out = 1


register(
    JobSpec(
        name="heartbeat",
        body=_heartbeat,
        cron="*/15 * * * *",
        description="Liveness check for the scheduler, lock and job_runs write path.",
        enabled=True,
        phase=1,
    )
)


def _provision_hubspot_properties(ctx: JobContext) -> None:
    """Create the five custom properties. Idempotent; safe on every deploy."""
    from app.adapters.hubspot import HubSpotCrmStore
    from app.config import get_settings

    settings = get_settings()
    store = HubSpotCrmStore(settings.require_hubspot_token())
    created = store.ensure_properties()
    ctx.detail["created"] = created
    ctx.items_out = sum(len(names) for names in created.values())


register(
    JobSpec(
        name="provision_hubspot_properties",
        body=_provision_hubspot_properties,
        cron="0 5 * * *",
        description=(
            "Create the five HubSpot custom properties if missing. Needs "
            "crm.schemas.*.write scopes."
        ),
        enabled=False,
        phase=2,
    )
)


def _process_hubspot_webhooks(ctx: JobContext) -> None:
    """Apply stored rep-side changes to our mirror.

    Field ownership rule, applied here rather than left to a race: HubSpot wins
    for anything a rep edits by hand (owner, native pipeline stage, notes); we
    win for everything the pipeline computes (priority_score,
    seed_lifecycle_stage, latest_funding_stage, office_signal). A rep edit to a
    pipeline-owned field is recorded and surfaced, not silently applied.
    """
    from sqlalchemy import text

    with ctx.session() as session:
        pending = session.execute(
            text(
                "SELECT id, subscription_type, object_id, payload "
                "FROM hubspot_webhook_events WHERE processed_at IS NULL "
                "ORDER BY received_at LIMIT 500"
            )
        ).all()
        ctx.items_in = len(pending)
        # Phase 2 stores and counts; the field-ownership application lands with
        # the enrollment layer that has fields to defend.
        ctx.detail["pending"] = len(pending)


register(
    JobSpec(
        name="process_hubspot_webhooks",
        body=_process_hubspot_webhooks,
        cron="*/5 * * * *",
        description="Apply stored HubSpot webhook events to the local mirror.",
        enabled=False,
        phase=2,
    )
)


def run_job(name: str, engine: Engine) -> str:
    spec = REGISTRY.get(name)
    if spec is None:
        raise KeyError(f"unknown job: {name}")
    return execute_job(spec.name, spec.body, engine=engine)


def build_scheduler(engine: Engine):
    """Wire enabled jobs into APScheduler."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    from app.config import get_settings

    settings = get_settings()
    scheduler = BlockingScheduler(timezone=settings.timezone_ops)

    for spec in REGISTRY.values():
        if not spec.enabled:
            logger.info("job %s registered but not enabled (phase %d)", spec.name, spec.phase)
            continue
        scheduler.add_job(
            run_job,
            CronTrigger.from_crontab(spec.cron, timezone=settings.timezone_ops),
            args=[spec.name, engine],
            id=spec.name,
            # Advisory locks already prevent overlap across processes; this
            # stops a slow run from queueing copies of itself in one process.
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        logger.info("scheduled %s (%s)", spec.name, spec.cron)

    return scheduler


def main() -> None:
    from app.config import get_settings
    from app.db import build_engine
    from app.logging_setup import configure_logging

    settings = get_settings()
    configure_logging(settings.log_level)
    engine = build_engine(settings.database_url)
    scheduler = build_scheduler(engine)
    logger.info("scheduler starting (tz=%s)", settings.timezone_ops)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("scheduler stopping")


if __name__ == "__main__":
    main()

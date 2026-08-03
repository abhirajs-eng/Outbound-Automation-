"""FastAPI application.

Phase 1 exposes health and a capacity readout. Everything else returns an
explicit empty state naming the phase it arrives in -- a screen of zeros reads
as a measurement, and there is nothing measured yet.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import ConfigError, get_settings
from app.db import build_engine
from app.domain import capacity as capacity_mod
from app.jobs.registry import REGISTRY
from app.logging_setup import configure_logging

logger = logging.getLogger(__name__)

DEFAULT_SEQUENCE_STEPS = 4


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    app.state.settings = settings
    app.state.engine = build_engine(settings.database_url)
    logger.info("api starting", extra={"environment": settings.environment})
    yield
    app.state.engine.dispose()


app = FastAPI(title="GTM Outbound", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> JSONResponse:
    """Liveness plus the readiness facts that actually block work."""
    settings = app.state.settings
    checks: dict[str, object] = {}

    try:
        with app.state.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            applied = conn.execute(
                text("SELECT count(*) FROM schema_migrations")
            ).scalar_one()
        checks["database"] = {"ok": True, "migrations_applied": applied}
    except Exception as exc:  # noqa: BLE001 - surfaced in the response
        checks["database"] = {"ok": False, "error": str(exc)}

    # Not a warning. Sequence activation is blocked while this is unset.
    checks["can_spam_physical_address"] = {
        "ok": bool(settings.physical_address),
        "blocks": "sequence activation",
    }

    checks["credentials"] = {
        "apollo": bool(settings.apollo_api_key),
        "hubspot": bool(settings.hubspot_private_app_token),
        "smartlead": bool(settings.smartlead_api_key),
        "drive": bool(settings.drive_sequence_folder),
    }

    report = _capacity_report()
    checks["capacity"] = {
        "status": report.status,
        "summary": report.summary(),
    }

    healthy = bool(checks["database"].get("ok"))
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )


def _capacity_report() -> capacity_mod.CapacityReport:
    settings = get_settings()
    return capacity_mod.compute(
        domains=len(settings.capacity.domains),
        mailboxes_per_domain=settings.capacity.mailboxes_per_domain,
        total_mailboxes=settings.capacity.total_mailboxes,
        sends_per_mailbox_day=settings.capacity.sends_per_mailbox_day,
        sequence_steps=DEFAULT_SEQUENCE_STEPS,
        sourcing_target=settings.daily_sourcing_target,
    )


@app.get("/capacity")
def capacity() -> dict:
    """Section 6 arithmetic. Reports 'not configured' rather than a guess."""
    report = _capacity_report()
    return {
        "configured": report.configured,
        "mailboxes": report.mailbox_count,
        "domains": report.domains,
        "emails_per_day": report.emails_per_day,
        "sustainable_enrollments_per_day": report.sustainable_enrollments_per_day,
        "sourcing_target": report.sourcing_target,
        "surplus_per_day": report.surplus_per_day,
        "backlog_per_month": report.backlog_per_month,
        "status": report.status,
        "summary": report.summary(),
    }


@app.get("/jobs")
def jobs() -> dict:
    return {
        "jobs": [
            {
                "name": spec.name,
                "cron": spec.cron,
                "enabled": spec.enabled,
                "arrives_in_phase": spec.phase,
                "description": spec.description,
            }
            for spec in REGISTRY.values()
        ]
    }


@app.get("/")
def index() -> dict:
    settings = get_settings()
    return {
        "service": "gtm-outbound",
        "company": settings.company_name,
        "phase": 1,
        "note": (
            "Phase 1 (foundation) only. Sourcing, CRM sync, sequences, sending, "
            "stats, signals and the performance loop are not wired up; screens "
            "for them will state which phase they arrive in rather than showing "
            "zeros."
        ),
    }

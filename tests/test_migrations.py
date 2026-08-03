"""The Phase 1 checkpoint: migrations run clean up and down."""

from __future__ import annotations

from sqlalchemy import inspect, text

from tools.migrate import discover, down, up

CORE_TABLES = {
    "companies", "contacts", "suppressions", "mailboxes", "job_runs",
    "source_cursors", "sequences", "sequence_versions", "sequence_steps",
    "step_variants", "campaigns", "campaign_mailboxes", "campaign_leads",
    "email_events", "replies", "reply_classifications", "reply_resolutions",
    "signals", "experiments", "experiment_evaluations", "hubspot_webhook_events",
}


def _reset(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))


def test_every_migration_has_a_reverse():
    migrations = discover()
    assert migrations, "no migrations found"
    for migration in migrations:
        assert migration.down_path.exists(), migration.label


def test_up_creates_every_table_then_down_removes_them(migration_engine):
    _reset(migration_engine)

    up(migration_engine)
    tables = set(inspect(migration_engine).get_table_names())
    missing = CORE_TABLES - tables
    assert not missing, f"missing after up: {sorted(missing)}"

    down(migration_engine, steps=len(discover()))
    remaining = set(inspect(migration_engine).get_table_names()) - {"schema_migrations"}
    assert not remaining, f"left behind after down: {sorted(remaining)}"


def test_up_is_idempotent(migration_engine):
    _reset(migration_engine)
    assert up(migration_engine) == len(discover())
    assert up(migration_engine) == 0


def test_up_down_up_leaves_a_working_schema(migration_engine):
    """A down migration that half-works shows up here, not at 3am."""
    _reset(migration_engine)
    up(migration_engine)
    down(migration_engine, steps=len(discover()))
    up(migration_engine)

    tables = set(inspect(migration_engine).get_table_names())
    assert CORE_TABLES <= tables

    # The trigger function is recreated too, not just the tables.
    with migration_engine.begin() as conn:
        exists = conn.execute(
            text("SELECT count(*) FROM pg_proc WHERE proname = 'set_updated_at'")
        ).scalar_one()
    assert exists == 1


def test_updated_at_trigger_fires(migration_engine):
    _reset(migration_engine)
    up(migration_engine)
    with migration_engine.begin() as conn:
        company_id = conn.execute(
            text("INSERT INTO companies (name) VALUES ('Trigger Co') RETURNING id")
        ).scalar_one()
        before = conn.execute(
            text("SELECT updated_at FROM companies WHERE id = :i"), {"i": company_id}
        ).scalar_one()
        conn.execute(
            text("UPDATE companies SET name = 'Trigger Co 2' WHERE id = :i"),
            {"i": company_id},
        )
        after = conn.execute(
            text("SELECT updated_at FROM companies WHERE id = :i"), {"i": company_id}
        ).scalar_one()
    assert after > before

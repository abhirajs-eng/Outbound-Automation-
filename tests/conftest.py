"""Test fixtures.

Tests run against real Postgres, never SQLite: the schema depends on JSONB,
partial unique indexes, CHECK constraints and triggers, none of which SQLite
enforces. A green SQLite suite here would be worse than no suite.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

from tools.migrate import down, up

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://outbound:outbound@localhost:5433/outbound_test",
)


@pytest.fixture(scope="session")
def engine():
    try:
        eng = create_engine(TEST_DATABASE_URL, future=True, pool_pre_ping=True)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(
            f"no Postgres at {TEST_DATABASE_URL} ({exc}). "
            "Start it with: docker compose up -d db, then create outbound_test."
        )

    # Start from a known-empty schema so a half-migrated database from an
    # earlier failed run cannot make this one pass or fail spuriously.
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    up(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine):
    """A connection in a transaction that is always rolled back."""
    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()


@pytest.fixture
def migration_engine():
    """A throwaway database for exercising up/down. Session-independent."""
    try:
        eng = create_engine(TEST_DATABASE_URL, future=True, pool_pre_ping=True)
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no Postgres at {TEST_DATABASE_URL} ({exc})")
    yield eng
    eng.dispose()

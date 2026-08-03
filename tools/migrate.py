"""Hand-written migration runner.

Applies migrations/NNNN_name.up.sql in order, records them in schema_migrations,
and reverses them with the matching .down.sql. Each migration runs in one
transaction; the whole run holds a Postgres advisory lock so two containers
booting at once cannot interleave.

    python -m tools.migrate up
    python -m tools.migrate down --steps 1
    python -m tools.migrate status
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
# Distinct from the job-runner lock namespace so a long sourcing job never
# blocks a deploy.
MIGRATION_LOCK_KEY = 8_474_021_001

FILENAME_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.(up|down)\.sql$")

BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     text PRIMARY KEY,
    name        text NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
);
"""


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    up_path: Path
    down_path: Path

    @property
    def label(self) -> str:
        return f"{self.version}_{self.name}"


def discover() -> list[Migration]:
    ups: dict[str, tuple[str, Path]] = {}
    downs: dict[str, Path] = {}

    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        match = FILENAME_RE.match(path.name)
        if not match:
            raise SystemExit(f"migration filename not understood: {path.name}")
        version, name, direction = match.groups()
        if direction == "up":
            ups[version] = (name, path)
        else:
            downs[version] = path

    missing = sorted(set(ups) - set(downs))
    if missing:
        # A migration that cannot be reversed is a migration that gets reversed
        # by hand at 3am. Refuse to start rather than find out later.
        raise SystemExit(f"missing .down.sql for versions: {', '.join(missing)}")

    return [
        Migration(version, name, up_path, downs[version])
        for version, (name, up_path) in sorted(ups.items())
    ]


def applied_versions(engine: Engine) -> set[str]:
    with engine.begin() as conn:
        conn.execute(text(BOOTSTRAP))
        rows = conn.execute(text("SELECT version FROM schema_migrations")).all()
    return {row[0] for row in rows}


def _run_sql(engine: Engine, sql: str, record: str, migration: Migration) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql))
        if record == "insert":
            conn.execute(
                text(
                    "INSERT INTO schema_migrations (version, name) "
                    "VALUES (:v, :n)"
                ),
                {"v": migration.version, "n": migration.name},
            )
        else:
            conn.execute(
                text("DELETE FROM schema_migrations WHERE version = :v"),
                {"v": migration.version},
            )


def up(engine: Engine) -> int:
    done = applied_versions(engine)
    pending = [m for m in discover() if m.version not in done]
    if not pending:
        print("up to date")
        return 0
    for migration in pending:
        print(f"applying {migration.label}")
        _run_sql(engine, migration.up_path.read_text(), "insert", migration)
    print(f"applied {len(pending)} migration(s)")
    return len(pending)


def down(engine: Engine, steps: int) -> int:
    done = applied_versions(engine)
    reversible = [m for m in discover() if m.version in done]
    targets = list(reversed(reversible))[:steps]
    if not targets:
        print("nothing to reverse")
        return 0
    for migration in targets:
        print(f"reversing {migration.label}")
        _run_sql(engine, migration.down_path.read_text(), "delete", migration)
    print(f"reversed {len(targets)} migration(s)")
    return len(targets)


def status(engine: Engine) -> None:
    done = applied_versions(engine)
    for migration in discover():
        mark = "applied" if migration.version in done else "pending"
        print(f"  [{mark}] {migration.label}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="run database migrations")
    parser.add_argument("command", choices=["up", "down", "status"])
    parser.add_argument("--steps", type=int, default=1, help="for down")
    parser.add_argument("--all", action="store_true", help="down: reverse everything")
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args(argv)

    if args.database_url:
        url = args.database_url
    else:
        from app.config import get_settings

        url = get_settings().database_url

    engine = create_engine(url, future=True, pool_pre_ping=True)

    with engine.connect() as conn:
        # Session-scoped: released when this connection closes, including on a
        # crash. A locks table would leave a row behind and block every later run.
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": MIGRATION_LOCK_KEY})
        try:
            if args.command == "up":
                up(engine)
            elif args.command == "down":
                steps = len(discover()) if args.all else args.steps
                down(engine, steps)
            else:
                status(engine)
        finally:
            conn.execute(
                text("SELECT pg_advisory_unlock(:k)"), {"k": MIGRATION_LOCK_KEY}
            )
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())

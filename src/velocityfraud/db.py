"""PostgreSQL connection helper for Layer 6 sink (and downstream consumers).

Centralizes DSN construction + a single tested connection-getter so the rest
of the codebase doesn't repeat boilerplate.

Usage:
    from velocityfraud.db import get_connection, apply_migrations

    apply_migrations()  # idempotent, run at startup
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM scored_events")
            print(cur.fetchone()[0])

Env vars:
    POSTGRES_HOST      (default: localhost)
    POSTGRES_PORT      (default: 5432)
    POSTGRES_DB        (default: velocityfraud)
    POSTGRES_USER      (default: vf)
    POSTGRES_PASSWORD  (default: vfpass)
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import psycopg
from loguru import logger


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
PG_DB = os.getenv("POSTGRES_DB", "velocityfraud")
PG_USER = os.getenv("POSTGRES_USER", "vf")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "vfpass")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = PROJECT_ROOT / "infra" / "migrations"


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_dsn() -> str:
    """Return the DSN string for psycopg.connect()."""
    return (
        f"host={PG_HOST} port={PG_PORT} dbname={PG_DB} "
        f"user={PG_USER} password={PG_PASS}"
    )


def get_connection(autocommit: bool = False) -> psycopg.Connection:
    """Open a new psycopg connection. Caller is responsible for closing it
    (use it as a context manager for safety).
    """
    return psycopg.connect(get_dsn(), autocommit=autocommit)


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------
def apply_migrations() -> None:
    """Run every .sql file in infra/migrations/ in lexical order.

    Each file should be idempotent (uses IF NOT EXISTS / CREATE OR REPLACE).
    For a real production system we'd track applied versions in a
    schema_migrations table; for the POC, idempotent SQL is enough.
    """
    if not MIGRATIONS_DIR.exists():
        logger.warning("Migrations directory not found: {}", MIGRATIONS_DIR)
        return

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        logger.warning("No .sql files found in {}", MIGRATIONS_DIR)
        return

    with get_connection(autocommit=True) as conn:
        with conn.cursor() as cur:
            for path in sql_files:
                logger.info("Applying migration: {}", path.name)
                sql = path.read_text(encoding="utf-8")
                cur.execute(sql)
    logger.info("All {} migration(s) applied.", len(sql_files))


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
def main() -> int:
    """Verify connectivity + run migrations + report row counts."""
    logger.info("=" * 60)
    logger.info("POSTGRES SMOKE TEST")
    logger.info("=" * 60)
    logger.info("DSN: host={} port={} db={} user={}", PG_HOST, PG_PORT, PG_DB, PG_USER)

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                version = cur.fetchone()[0]
                logger.info("Connected. Server version:")
                logger.info("  {}", version)
    except Exception as e:
        logger.error("Connection FAILED: {}", e)
        logger.error("Make sure Postgres is running:")
        logger.error("  docker compose -f infra/docker-compose.yml up -d postgres")
        return 1

    logger.info("-" * 60)
    apply_migrations()

    logger.info("-" * 60)
    with get_connection() as conn:
        with conn.cursor() as cur:
            for table in ("scored_events", "enriched_events"):
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                count = cur.fetchone()[0]
                logger.info("  {:25s} {} rows", table, count)

    logger.success("Postgres smoke test PASSED.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

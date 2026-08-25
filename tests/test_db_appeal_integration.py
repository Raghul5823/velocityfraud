"""Integration tests against live Postgres:

    db.py     - DSN, connection, idempotent migrations
    appeal.py - fetch / list / guard branches (read-only + no-op error paths,
                so the suite never mutates real blocklist / Kafka state)
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# db.py
# ---------------------------------------------------------------------------
def test_dsn_contains_expected_fields(pg_ready):
    dsn = pg_ready.get_dsn()
    assert "dbname=velocityfraud" in dsn
    assert "host=" in dsn and "port=" in dsn


def test_connection_and_query(pg_ready):
    with pg_ready.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM scored_events")
            n = cur.fetchone()[0]
    assert n >= 0


def test_migrations_are_idempotent(pg_ready):
    # pg_ready already applied them once; a second run must not raise.
    pg_ready.apply_migrations()


# ---------------------------------------------------------------------------
# appeal.py — helpers + public guard branches (no state mutation)
# ---------------------------------------------------------------------------
def _one_event_id(pg_ready, decision: str):
    with pg_ready.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT event_id FROM scored_events WHERE decision = %s LIMIT 1",
                (decision,),
            )
            row = cur.fetchone()
    return row[0] if row else None


def test_fetch_scored_event_reads_existing(pg_ready):
    from velocityfraud import appeal
    any_id = _one_event_id(pg_ready, "ALLOW") or _one_event_id(pg_ready, "REVIEW")
    if any_id is None:
        pytest.skip("no scored_events present to read")
    ev = appeal._fetch_scored_event(any_id)
    assert ev is not None
    assert ev["event_id"] == any_id
    assert "_original_decision" in ev


def test_fetch_missing_event_returns_none(pg_ready):
    from velocityfraud import appeal
    assert appeal._fetch_scored_event("does-not-exist-xyz") is None


def test_list_unresolved_returns_list(pg_ready):
    from velocityfraud import appeal
    out = appeal.list_unresolved()
    assert isinstance(out, list)


def test_submit_appeal_on_missing_event_is_rejected(pg_ready):
    from velocityfraud import appeal
    res = appeal.submit_appeal("no-such-event", "test reason", appellant_role="analyst")
    assert res["ok"] is False
    assert "not found" in res["error"]


def test_submit_appeal_on_allow_event_is_rejected(pg_ready):
    from velocityfraud import appeal
    allow_id = _one_event_id(pg_ready, "ALLOW")
    if allow_id is None:
        pytest.skip("no ALLOW event to test the guard branch")
    res = appeal.submit_appeal(allow_id, "should be refused", appellant_role="customer")
    assert res["ok"] is False
    assert res["original_decision"] == "ALLOW"


def test_submit_appeal_rejects_bad_role(pg_ready):
    from velocityfraud import appeal
    with pytest.raises(ValueError):
        appeal.submit_appeal("x", "reason", appellant_role="hacker")


def test_resolve_nonexistent_appeal(pg_ready):
    from velocityfraud import appeal
    res = appeal.resolve_appeal(999_999_999, "no such appeal")
    assert res["ok"] is False

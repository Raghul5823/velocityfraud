"""Integration tests for the ops-metrics collector (closes proposal gap B5).

Needs live Postgres for the Groq-RPM query and the poll()/show() round trip.
Kafka-lag collection shells out to kafka-consumer-groups.sh via `docker exec`
-- exercised for real when Kafka is reachable, and its own contract (return
[] rather than raise on any failure) is what's tested when it is not, so no
skip is needed for that half.
"""
from __future__ import annotations

import pytest

from velocityfraud.ops_metrics import (
    GROQ_MAX_RPM,
    _collect_groq_rpm,
    _collect_kafka_lag,
)

pytestmark = pytest.mark.integration


def test_collect_groq_rpm_returns_consistent_headroom(pg_ready):
    used, headroom = _collect_groq_rpm()

    assert used >= 0.0
    assert headroom == max(0.0, GROQ_MAX_RPM - used)


def test_collect_kafka_lag_never_raises_and_returns_a_list():
    """Fail-open contract: whatever Kafka's state, this returns a list --
    populated when reachable, empty when not -- and never propagates."""
    lag_rows = _collect_kafka_lag()

    assert isinstance(lag_rows, list)
    for scope, lag in lag_rows:
        assert isinstance(scope, str) and "/" in scope  # "<group>/<topic>"
        assert isinstance(lag, float)
        assert lag >= 0.0


def test_poll_persists_a_snapshot_and_show_reads_it_back(pg_ready):
    from velocityfraud.ops_metrics import poll, show

    summary = poll()

    assert set(summary) == {
        "lag_scopes", "total_lag", "groq_rpm_used", "groq_rpm_headroom",
    }
    assert summary["lag_scopes"] >= 0
    assert summary["groq_rpm_headroom"] == max(0.0, GROQ_MAX_RPM - summary["groq_rpm_used"])

    latest = show()
    names = {row["metric_name"] for row in latest}
    assert "groq_rpm_used" in names
    assert "groq_rpm_headroom" in names
    for row in latest:
        assert set(row) == {"metric_name", "scope", "value", "captured_at"}


def test_poll_overwrites_previous_groq_snapshot_in_show(pg_ready):
    """show() is documented as latest-value-per-metric+scope -- two polls in
    a row must still yield exactly one 'global' row per Groq metric, not an
    accumulating list."""
    from velocityfraud.ops_metrics import poll, show

    poll()
    poll()
    latest = show()

    global_groq_rows = [
        row for row in latest
        if row["metric_name"] in ("groq_rpm_used", "groq_rpm_headroom") and row["scope"] == "global"
    ]
    assert len(global_groq_rows) == 2  # one used, one headroom -- not duplicated

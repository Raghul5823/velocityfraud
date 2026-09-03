"""Operational metrics collector — Kafka consumer lag + Groq RPM headroom.

Closes the last data gap in the Operational Health dashboard. The proposal
(Section 5, Layer 3) requires that view to surface "Kafka consumer lag ...
Groq RPM headroom", and Layer 1 describes lag as "monitored via JMX and
surfaced in Power BI". No JMX exporter was ever built (gap B5), so both
panels had no data source.

Honest substitution, recorded rather than glossed over: instead of standing
up a JMX/Prometheus stack for two numbers, this polls the same facts from
sources that already exist --

    kafka_consumer_lag  <- Kafka's own kafka-consumer-groups.sh, summed per
                           consumer group + topic (per-partition is too
                           granular to put on a dashboard)
    groq_rpm_used       <- rows actually landed in scored_events_groq in the
                           last 60 s (a real observed rate, not an estimate)
    groq_rpm_headroom   <- GROQ_MAX_RPM minus the above; the free-tier cap we
                           already self-enforce in groq_scorer.py

Both are genuine measurements. The only thing lost versus JMX is sub-second
granularity, which a dashboard refreshed on DirectQuery cannot show anyway.

Usage:
    uv run python -m velocityfraud.ops_metrics poll
    uv run python -m velocityfraud.ops_metrics show
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from loguru import logger

from velocityfraud.db import get_connection

KAFKA_CONTAINER = os.getenv("KAFKA_CONTAINER", "vf-kafka")
KAFKA_BOOTSTRAP = os.getenv("OPS_KAFKA_BOOTSTRAP", "localhost:9092")
GROQ_MAX_RPM = int(os.getenv("GROQ_MAX_RPM", "25"))  # same default groq_scorer.py enforces


def _collect_kafka_lag() -> list[tuple[str, float]]:
    """Return [(scope, lag)] where scope is "<group>/<topic>", lag summed over partitions.

    Returns an empty list (and logs) if Kafka can't be reached -- this is a
    metrics collector, it must never take down whatever called it.
    """
    cmd = [
        "docker", "exec", KAFKA_CONTAINER,
        "/opt/kafka/bin/kafka-consumer-groups.sh",
        "--bootstrap-server", KAFKA_BOOTSTRAP,
        "--describe", "--all-groups",
    ]
    try:
        # MSYS_NO_PATHCONV stops Git Bash on Windows rewriting the in-container
        # /opt/... path into a Windows path before docker ever sees it.
        env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=90, env=env)
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("Kafka lag collection failed ({}); skipping this metric.", str(e)[:100])
        return []

    if out.returncode != 0:
        logger.warning("kafka-consumer-groups.sh exited {} ; skipping lag.", out.returncode)
        return []

    totals: dict[str, float] = {}
    for line in out.stdout.splitlines():
        parts = line.split()
        # Data rows look like: GROUP TOPIC PARTITION CURRENT LOG-END LAG ...
        # Skip headers, blanks, and the "has no active members" notices.
        if len(parts) < 6 or parts[0] in ("GROUP", "Consumer"):
            continue
        group, topic, lag_raw = parts[0], parts[1], parts[5]
        if lag_raw in ("-", ""):  # no committed offset yet -> not a real lag reading
            continue
        try:
            lag = float(lag_raw)
        except ValueError:
            continue
        totals[f"{group}/{topic}"] = totals.get(f"{group}/{topic}", 0.0) + lag

    return sorted(totals.items())


def _collect_groq_rpm() -> tuple[float, float]:
    """Return (rpm_used, rpm_headroom) from rows actually written in the last minute."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM scored_events_groq "
                "WHERE inserted_at > NOW() - INTERVAL '1 minute'"
            )
            used = float(cur.fetchone()[0] or 0)
    return used, max(0.0, GROQ_MAX_RPM - used)


def poll() -> dict:
    """Collect all operational metrics once and persist them."""
    lag_rows = _collect_kafka_lag()
    rpm_used, rpm_headroom = _collect_groq_rpm()

    rows = [("kafka_consumer_lag", scope, lag) for scope, lag in lag_rows]
    rows.append(("groq_rpm_used", "global", rpm_used))
    rows.append(("groq_rpm_headroom", "global", rpm_headroom))

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO ops_metrics (metric_name, scope, metric_value) VALUES (%s, %s, %s)",
                rows,
            )
        conn.commit()

    total_lag = sum(lag for _, lag in lag_rows)
    logger.success(
        "Polled ops metrics: {} lag scopes (total lag={:.0f}), groq_rpm_used={:.0f}, headroom={:.0f}",
        len(lag_rows), total_lag, rpm_used, rpm_headroom,
    )
    return {
        "lag_scopes": len(lag_rows),
        "total_lag": total_lag,
        "groq_rpm_used": rpm_used,
        "groq_rpm_headroom": rpm_headroom,
    }


def show() -> list[dict]:
    """Latest value per metric+scope (what the dashboard KPI tiles read)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT metric_name, scope, metric_value, captured_at "
                "FROM ops_metrics_latest ORDER BY metric_name, scope"
            )
            rows = cur.fetchall()
    return [
        {"metric_name": r[0], "scope": r[1], "value": float(r[2]),
         "captured_at": r[3].isoformat() if r[3] else None}
        for r in rows
    ]


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Operational metrics collector")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("poll", help="Collect and store one snapshot")
    sub.add_parser("show", help="Show the latest value per metric")

    args = parser.parse_args()
    if args.cmd == "poll":
        import json
        print(json.dumps(poll(), indent=2))
        return 0
    if args.cmd == "show":
        for m in show():
            print(f"  {m['metric_name']:22s} {m['scope']:45s} {m['value']:>10.0f}  @ {m['captured_at']}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(_cli())

"""Drift detection — fast-path (XGBoost) vs shadow (Groq) agreement monitor.

Closes the proposal gap tracked in docs/proposal_gap_remediation.md (§10.3):

    "Drift detection on fast-path-vs-shadow agreement — if Groq and the
    shadow XGBoost disagree on >5% of transactions in a window, an alarm
    fires; one of the two has drifted and needs investigation."

The per-event comparison (the `scorer_comparison` view, joining
`scored_events` x `scored_events_groq` on event_id) already existed from
Layer 5b. What this module adds is the WINDOWED AGGREGATION and ALARM logic
that view alone doesn't provide — this is a monitoring job, not a new
scoring path; it never influences a live decision, it only observes and
alerts on the two paths' agreement rate over time.

Usage as CLI (via scripts/check-drift.ps1):
    uv run python -m velocityfraud.drift check --window-minutes 60 --threshold 0.05
    uv run python -m velocityfraud.drift history --limit 20
"""
from __future__ import annotations

import argparse
import sys

from loguru import logger

from velocityfraud.db import get_connection

DEFAULT_WINDOW_MINUTES = 60
DEFAULT_THRESHOLD = 0.05  # 5%, exactly the proposal's named threshold


def check_drift(window_minutes: int = DEFAULT_WINDOW_MINUTES,
                 threshold: float = DEFAULT_THRESHOLD) -> dict:
    """Compare XGBoost vs Groq decisions over the last `window_minutes`.

    Returns a dict with the comparison stats and whether an alarm fired.
    Every check is recorded to `drift_checks` (even when it doesn't fire),
    so we can also prove the monitor ran and was healthy most of the time.
    """
    window_ms = window_minutes * 60 * 1000

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) AS compared,
                    SUM(CASE WHEN NOT decisions_agree THEN 1 ELSE 0 END) AS disagreements
                FROM scorer_comparison
                WHERE scored_at_ms >= (EXTRACT(EPOCH FROM NOW()) * 1000 - %s)
                """,
                (window_ms,),
            )
            compared, disagreements = cur.fetchone()
            compared = int(compared or 0)
            disagreements = int(disagreements or 0)
            rate = (disagreements / compared) if compared > 0 else 0.0
            alarm = compared > 0 and rate > threshold

            cur.execute(
                """INSERT INTO drift_checks
                   (window_minutes, compared_count, disagreement_count,
                    disagreement_rate, threshold, alarm_fired)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   RETURNING check_id""",
                (window_minutes, compared, disagreements, rate, threshold, alarm),
            )
            check_id = cur.fetchone()[0]
        conn.commit()

    result = {
        "check_id": check_id,
        "window_minutes": window_minutes,
        "compared": compared,
        "disagreements": disagreements,
        "disagreement_rate": round(rate, 4),
        "threshold": threshold,
        "alarm_fired": alarm,
    }

    if compared == 0:
        logger.info("Drift check #{}: no comparable events in the last {} min "
                    "(Groq path may not be running).", check_id, window_minutes)
    elif alarm:
        logger.critical(
            "DRIFT ALARM #{}: {}/{} events disagreed ({:.1%}) in the last {} min "
            "— exceeds the {:.0%} threshold. XGBoost and Groq have diverged; "
            "investigate which one drifted.",
            check_id, disagreements, compared, rate, window_minutes, threshold,
        )
    else:
        logger.success("Drift check #{}: {}/{} disagreed ({:.1%}) in the last {} min "
                       "— within the {:.0%} threshold.",
                       check_id, disagreements, compared, rate, window_minutes, threshold)

    return result


def history(limit: int = 20) -> list[dict]:
    """Recent drift-check history, for a health-check page or evidence pack."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT check_id, window_minutes, compared_count, disagreement_count,
                          disagreement_rate, threshold, alarm_fired, checked_at
                   FROM drift_checks ORDER BY checked_at DESC LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()
    return [
        {"check_id": r[0], "window_minutes": r[1], "compared": r[2], "disagreements": r[3],
         "disagreement_rate": float(r[4]), "threshold": float(r[5]), "alarm_fired": r[6],
         "checked_at": r[7].isoformat() if r[7] else None}
        for r in rows
    ]


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Fast-path vs shadow-model drift detection")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="Run a drift check now")
    p.add_argument("--window-minutes", type=int, default=DEFAULT_WINDOW_MINUTES)
    p.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)

    h = sub.add_parser("history", help="Show recent drift-check history")
    h.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()
    if args.cmd == "check":
        import json
        res = check_drift(args.window_minutes, args.threshold)
        print(json.dumps(res, indent=2, default=str))
        return 1 if res["alarm_fired"] else 0
    if args.cmd == "history":
        for h_row in history(args.limit):
            print(f"  #{h_row['check_id']}  window={h_row['window_minutes']}min  "
                  f"{h_row['disagreements']}/{h_row['compared']} disagreed "
                  f"({h_row['disagreement_rate']:.1%})  alarm={h_row['alarm_fired']}  "
                  f"at {h_row['checked_at']}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(_cli())

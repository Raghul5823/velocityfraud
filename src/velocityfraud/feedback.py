"""Analyst feedback loop — records ground-truth verdicts (Wk 12).

Closes the human-in-the-loop feedback loop the proposal committed to ("feedback
writeback topic; feedback loop closed"). When an analyst reviews a scored
transaction and records whether it was really FRAUD or LEGIT, we:

    1. look up the scored event (model decision + fraud score) in Postgres
    2. compute whether the model's flag AGREED with the analyst
    3. INSERT the labelled verdict into feedback_events
    4. PRODUCE the same verdict to Kafka `transactions.feedback`

Downstream, that topic is the label stream for retraining, and the
feedback_agreement view feeds the Operational Health dashboard's
"model-vs-analyst agreement rate".

Usage as CLI (via scripts/submit-feedback.ps1):
    uv run python -m velocityfraud.feedback submit \
        --event-id <uuid> --verdict FRAUD --analyst jdoe --notes "confirmed chargeback"

    uv run python -m velocityfraud.feedback list
    uv run python -m velocityfraud.feedback stats
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
from typing import Optional

import fastavro
from confluent_kafka import Producer
from loguru import logger

from velocityfraud.db import get_connection
from velocityfraud.schema import get_feedback_schema

FEEDBACK_BOOTSTRAP = os.getenv("FEEDBACK_BOOTSTRAP", "localhost:9092")
FEEDBACK_TOPIC = os.getenv("FEEDBACK_TOPIC", "transactions.feedback")

VERDICTS = ("FRAUD", "LEGIT")
ROLES = ("analyst", "system")


def _model_flagged(decision: str) -> bool:
    """A REVIEW or BLOCK is the model calling the txn suspicious; ALLOW is not."""
    return decision in ("REVIEW", "BLOCK")


def model_agrees(decision: str, verdict: str) -> bool:
    """True if the model's flag matches the analyst's ground-truth verdict."""
    return _model_flagged(decision) == (verdict == "FRAUD")


def _fetch_scored(event_id: str) -> Optional[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT decision, fraud_score FROM scored_events WHERE event_id = %s",
                (event_id,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return {"decision": row[0], "fraud_score": float(row[1])}


def _emit(event: dict) -> bool:
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, get_feedback_schema(), event)
    delivered = {"ok": False}

    def _cb(err, msg):
        delivered["ok"] = err is None

    producer = Producer({
        "bootstrap.servers": FEEDBACK_BOOTSTRAP,
        "client.id": "velocityfraud-feedback",
        "enable.idempotence": True,
        "acks": "all",
    })
    producer.produce(FEEDBACK_TOPIC, key=event["event_id"].encode("utf-8"),
                     value=buf.getvalue(), on_delivery=_cb)
    producer.flush(timeout=10)
    return delivered["ok"]


def submit_feedback(event_id: str, verdict: str, analyst_name: str = "unknown",
                    analyst_role: str = "analyst", notes: str = "") -> dict:
    """Record an analyst's ground-truth verdict on a scored event."""
    verdict = verdict.upper()
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}, got {verdict!r}")
    if analyst_role not in ROLES:
        raise ValueError(f"analyst_role must be one of {ROLES}, got {analyst_role!r}")

    scored = _fetch_scored(event_id)
    if scored is None:
        return {"ok": False, "error": f"event_id {event_id} not found in scored_events"}

    agreed = model_agrees(scored["decision"], verdict)
    submitted_at_ms = int(time.time() * 1000)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO feedback_events
                   (event_id, analyst_name, analyst_role, model_decision,
                    model_fraud_score, analyst_verdict, model_agreed, notes)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING feedback_id""",
                (event_id, analyst_name, analyst_role, scored["decision"],
                 scored["fraud_score"], verdict, agreed, notes),
            )
            feedback_id = cur.fetchone()[0]
        conn.commit()

    emitted = _emit({
        "event_id": event_id,
        "analyst_name": analyst_name,
        "analyst_role": analyst_role,
        "model_decision": scored["decision"],
        "model_fraud_score": scored["fraud_score"],
        "analyst_verdict": verdict,
        "model_agreed": agreed,
        "notes": notes,
        "submitted_at_ms": submitted_at_ms,
    })

    logger.success("Feedback #{} recorded: {}={} model={} agreed={} emitted={}",
                   feedback_id, event_id[:8], verdict, scored["decision"], agreed, emitted)
    return {"ok": True, "feedback_id": feedback_id, "model_decision": scored["decision"],
            "model_fraud_score": scored["fraud_score"], "analyst_verdict": verdict,
            "model_agreed": agreed, "emitted_to_kafka": emitted}


def list_feedback(limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT feedback_id, event_id, analyst_role, model_decision,
                          analyst_verdict, model_agreed, submitted_at
                   FROM feedback_events ORDER BY submitted_at DESC LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()
    return [
        {"feedback_id": r[0], "event_id": r[1], "analyst_role": r[2],
         "model_decision": r[3], "analyst_verdict": r[4], "model_agreed": r[5],
         "submitted_at": r[6].isoformat() if r[6] else None}
        for r in rows
    ]


def feedback_stats() -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT total_feedback, agreements, agreement_rate, "
                        "analyst_fraud, analyst_legit FROM feedback_agreement")
            r = cur.fetchone()
    if not r or r[0] == 0:
        return {"total_feedback": 0, "agreement_rate": None}
    return {"total_feedback": int(r[0]), "agreements": int(r[1]),
            "agreement_rate": float(r[2]) if r[2] is not None else None,
            "analyst_fraud": int(r[3]), "analyst_legit": int(r[4])}


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Analyst feedback loop")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("submit", help="Record a verdict on a scored event")
    p.add_argument("--event-id", required=True)
    p.add_argument("--verdict", required=True, choices=["FRAUD", "LEGIT"])
    p.add_argument("--analyst", default="unknown")
    p.add_argument("--role", default="analyst", choices=list(ROLES))
    p.add_argument("--notes", default="")

    sub.add_parser("list", help="List recent feedback")
    sub.add_parser("stats", help="Show model-vs-analyst agreement stats")

    args = parser.parse_args()
    if args.cmd == "submit":
        import json
        res = submit_feedback(args.event_id, args.verdict, args.analyst, args.role, args.notes)
        print(json.dumps(res, indent=2, default=str))
        return 0 if res.get("ok") else 1
    if args.cmd == "list":
        for f in list_feedback():
            print(f"  #{f['feedback_id']}  {f['event_id'][:8]}...  "
                  f"model={f['model_decision']}  verdict={f['analyst_verdict']}  "
                  f"agreed={f['model_agreed']}")
        return 0
    if args.cmd == "stats":
        import json
        print(json.dumps(feedback_stats(), indent=2))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(_cli())

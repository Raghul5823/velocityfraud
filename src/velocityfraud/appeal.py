"""Layer 8 — Appeal submission module.

Workflow when someone (customer / analyst / system) disputes a BLOCK/REVIEW:

    1. Look up the original event in scored_events (Postgres)
    2. Verify decision was BLOCK or REVIEW (ALLOWed events don't need appeals)
    3. Whitelist all four entities (card, merchant, IP, device) in Redis
       - Whitelist wins over blocklist -> next re-emit won't be short-circuited
    4. Insert an appeal record in the appeals table
    5. Re-publish the original event to transactions.raw with:
       - source_label = "appeal"
       - The next scorer run will:
         - See whitelist -> skip blocklist
         - Run ML fresh
         - Emit a NEW scored event with the fresh decision
    6. When the pipeline finishes processing the re-emitted event, a follow-up
       call to resolve_appeal() records the final outcome

Usage as CLI (via scripts/appeal-transaction.ps1):
    uv run python -m velocityfraud.appeal submit \
        --event-id cc78c338-... --reason "customer disputes" --role customer

    uv run python -m velocityfraud.appeal list       # unresolved appeals
    uv run python -m velocityfraud.appeal resolve --appeal-id 1 --notes "..."
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from typing import Optional

import fastavro
from confluent_kafka import Producer
from loguru import logger

from velocityfraud import blocklist
from velocityfraud.db import get_connection
from velocityfraud.schema import get_schema


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APPEAL_BOOTSTRAP = os.getenv("APPEAL_BOOTSTRAP", "localhost:9092")
APPEAL_RAW_TOPIC = os.getenv("APPEAL_RAW_TOPIC", "transactions.raw")

# TTL for whitelist entries triggered by an appeal (default: 24h)
APPEAL_WHITELIST_TTL_S = int(os.getenv("APPEAL_WHITELIST_TTL_S", str(24 * 3600)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fetch_scored_event(event_id: str) -> Optional[dict]:
    """Fetch a scored event row from Postgres. Returns None if not found."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT event_id, event_timestamp_ms, customer_id, card_token,
                       amount, currency, amount_fx_normalised, merchant_id_hash,
                       merchant_name, mcc, merchant_country, ip_address_hash,
                       device_fingerprint_hash, geo_distance_km, source_label,
                       schema_version, fraud_score, decision
                FROM scored_events
                WHERE event_id = %s
            """, (event_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "event_id":                row[0],
                "event_timestamp_ms":      int(row[1]),
                "customer_id":             row[2],
                "card_token":              row[3],
                "amount":                  float(row[4]),
                "currency":                row[5],
                "amount_fx_normalised":    float(row[6]),
                "merchant_id_hash":        row[7],
                "merchant_name":           row[8],
                "mcc":                     row[9],
                "merchant_country":        row[10],
                "ip_address_hash":         row[11],
                "device_fingerprint_hash": row[12],
                "geo_distance_km":         float(row[13]),
                "source_label":            row[14],
                "schema_version":          row[15],
                # Metadata (NOT re-emitted, used for logging only)
                "_original_fraud_score":   float(row[16]),
                "_original_decision":      row[17],
            }


def _whitelist_all_entities(event: dict, reason: str) -> list[dict]:
    """Whitelist card / merchant / ip / device from an event.

    Returns a list of {entity_type, entity_id} dicts for the audit trail.
    """
    entities = [
        ("card",     event.get("card_token")),
        ("merchant", event.get("merchant_id_hash")),
        ("ip",       event.get("ip_address_hash")),
        ("device",   event.get("device_fingerprint_hash")),
    ]
    whitelisted = []
    for entity_type, entity_id in entities:
        if entity_id:
            blocklist.add_whitelist(
                entity_type, entity_id, reason,
                ttl_s=APPEAL_WHITELIST_TTL_S,
            )
            whitelisted.append({
                "entity_type": entity_type,
                "entity_id":   entity_id,
            })
    return whitelisted


def _emit_to_raw(event: dict) -> bool:
    """Re-publish the original event to transactions.raw with source_label='appeal'."""
    raw_schema = get_schema()

    # Strip out our metadata + set source_label to indicate this is an appeal
    payload_event = {k: v for k, v in event.items() if not k.startswith("_")}
    payload_event["source_label"] = "appeal"

    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, raw_schema, payload_event)
    payload = buf.getvalue()

    delivered = {"ok": False, "err": None}

    def _on_delivery(err, msg):
        if err is not None:
            delivered["err"] = str(err)
        else:
            delivered["ok"] = True

    producer = Producer({
        "bootstrap.servers": APPEAL_BOOTSTRAP,
        "client.id": "velocityfraud-appeal",
        "enable.idempotence": True,
        "acks": "all",
    })
    producer.produce(
        topic=APPEAL_RAW_TOPIC,
        key=payload_event["customer_id"].encode("utf-8"),
        value=payload,
        on_delivery=_on_delivery,
    )
    producer.flush(timeout=10)

    if delivered["err"]:
        logger.error("Failed to re-emit appeal event: {}", delivered["err"])
        return False
    return delivered["ok"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def submit_appeal(event_id: str, reason: str,
                   appellant_name: str = "unknown",
                   appellant_role: str = "customer") -> dict:
    """Submit an appeal for a scored (BLOCK or REVIEW) event.

    Returns a dict with the outcome: {ok, appeal_id, whitelisted, ...}.
    """
    if appellant_role not in ("customer", "analyst", "system"):
        raise ValueError(f"appellant_role must be customer/analyst/system, got {appellant_role!r}")

    event = _fetch_scored_event(event_id)
    if event is None:
        return {"ok": False, "error": f"event_id {event_id} not found in scored_events"}

    original_decision = event["_original_decision"]
    original_score = event["_original_fraud_score"]

    # Only BLOCK/REVIEW decisions can be appealed — ALLOW has no reason for appeal
    if original_decision == "ALLOW":
        return {
            "ok": False,
            "error": f"event was ALLOW (no appeal needed)",
            "original_decision": original_decision,
        }

    logger.info("Processing appeal for event_id={} (original={} @ {:.4f})",
                event_id[:8], original_decision, original_score)

    # 1. Whitelist all entities in Redis
    if not blocklist.is_redis_alive():
        logger.warning("Redis unreachable — appeal proceeds without whitelist.")
        whitelisted = []
    else:
        whitelisted = _whitelist_all_entities(
            event, reason=f"appeal by {appellant_role}: {reason[:80]}",
        )

    # 2. Insert appeal record in Postgres
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO appeals (
                    event_id, appellant_name, appellant_role, reason,
                    original_decision, original_fraud_score, whitelisted_entities
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING appeal_id
            """, (
                event_id, appellant_name, appellant_role, reason,
                original_decision, original_score,
                json.dumps(whitelisted),
            ))
            appeal_id = cur.fetchone()[0]
        conn.commit()

    # 3. Re-emit to transactions.raw
    emitted = _emit_to_raw(event)

    result = {
        "ok": True,
        "appeal_id": appeal_id,
        "event_id": event_id,
        "original_decision": original_decision,
        "original_fraud_score": original_score,
        "whitelisted_count": len(whitelisted),
        "whitelist_ttl_s": APPEAL_WHITELIST_TTL_S,
        "re_emitted_to_kafka": emitted,
    }
    logger.success("Appeal #{} submitted: whitelisted={}, re-emitted={}",
                   appeal_id, len(whitelisted), emitted)
    return result


def list_unresolved() -> list[dict]:
    """List currently open appeals."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT appeal_id, event_id, appellant_role, submitted_at,
                       original_decision, original_fraud_score,
                       LEFT(reason, 80) AS reason_preview,
                       EXTRACT(EPOCH FROM (NOW() - submitted_at)) / 60 AS minutes_waiting
                FROM appeals
                WHERE resolved_at IS NULL
                ORDER BY submitted_at ASC
            """)
            rows = cur.fetchall()
            return [
                {
                    "appeal_id":            r[0],
                    "event_id":             r[1],
                    "appellant_role":       r[2],
                    "submitted_at":         r[3].isoformat() if r[3] else None,
                    "original_decision":    r[4],
                    "original_fraud_score": float(r[5]) if r[5] is not None else None,
                    "reason_preview":       r[6],
                    "minutes_waiting":      round(float(r[7]), 1) if r[7] else 0,
                }
                for r in rows
            ]


def resolve_appeal(appeal_id: int, notes: str,
                    final_decision: Optional[str] = None,
                    final_fraud_score: Optional[float] = None) -> dict:
    """Mark an appeal resolved. Called after the re-scored event has been processed."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE appeals
                SET resolved_at = NOW(),
                    final_decision = %s,
                    final_fraud_score = %s,
                    resolution_notes = %s
                WHERE appeal_id = %s AND resolved_at IS NULL
                RETURNING appeal_id
            """, (final_decision, final_fraud_score, notes, appeal_id))
            updated = cur.fetchone()
        conn.commit()
    if updated is None:
        return {"ok": False, "error": "appeal not found or already resolved"}
    return {"ok": True, "appeal_id": appeal_id}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cli() -> int:
    parser = argparse.ArgumentParser(description="Appeal a scored transaction")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_submit = sub.add_parser("submit", help="Submit an appeal")
    p_submit.add_argument("--event-id", required=True)
    p_submit.add_argument("--reason",   required=True)
    p_submit.add_argument("--name",     default="unknown", help="Appellant name")
    p_submit.add_argument("--role",     default="customer",
                           choices=["customer", "analyst", "system"])

    sub.add_parser("list", help="List unresolved appeals")

    p_resolve = sub.add_parser("resolve", help="Mark an appeal resolved")
    p_resolve.add_argument("--appeal-id",       required=True, type=int)
    p_resolve.add_argument("--notes",           required=True)
    p_resolve.add_argument("--final-decision",  choices=["ALLOW", "REVIEW", "BLOCK"])
    p_resolve.add_argument("--final-score",     type=float)

    args = parser.parse_args()

    if args.cmd == "submit":
        result = submit_appeal(args.event_id, args.reason, args.name, args.role)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("ok") else 1

    if args.cmd == "list":
        appeals = list_unresolved()
        if not appeals:
            print("No unresolved appeals.")
        else:
            print(f"{len(appeals)} unresolved appeal(s):")
            for a in appeals:
                print(f"  #{a['appeal_id']}  event={a['event_id'][:8]}...  "
                      f"role={a['appellant_role']}  waiting={a['minutes_waiting']}min  "
                      f"orig={a['original_decision']}({a['original_fraud_score']:.4f})")
                print(f"    reason: {a['reason_preview']}")
        return 0

    if args.cmd == "resolve":
        result = resolve_appeal(
            args.appeal_id, args.notes,
            final_decision=args.final_decision,
            final_fraud_score=args.final_score,
        )
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("ok") else 1

    return 1


if __name__ == "__main__":
    sys.exit(_cli())

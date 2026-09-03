"""Kafka -> PostgreSQL sink — Layer 6.

Subscribes to BOTH `transactions.scored` and `transactions.enriched` with a
single consumer. Routes each message to the correct table based on its
source topic. Uses batched, idempotent INSERTs (ON CONFLICT DO NOTHING on
event_id) so the sink is replay-safe.

Pipeline per event:
    1. consume(scored or enriched)
    2. decode via the correct Avro schema (chosen by topic name)
    3. buffer the row into the per-table batch
    4. flush when batch hits SINK_BATCH_SIZE or SINK_FLUSH_SEC elapses
    5. executemany INSERT ... ON CONFLICT (event_id) DO NOTHING

Latency: not a goal here — this is batch-flavored streaming. Default flush
is 50 rows or 2 seconds, whichever first. For Power BI we accept a few
seconds of staleness.

Usage (from velocityfraud/ root):
    uv run python -m velocityfraud.sink

Env vars:
    SINK_MAX_EVENTS   (default: 0 = no cap)
    SINK_BOOTSTRAP    (default: localhost:9092)
    SINK_GROUP        (default: velocityfraud-sink-dev)
    SINK_FROM         (default: earliest)
    SINK_BATCH_SIZE   (default: 50)
    SINK_FLUSH_SEC    (default: 2.0)
"""
from __future__ import annotations

import io
import json
import os
import signal
import sys
import time

import fastavro
from confluent_kafka import Consumer, KafkaError
from loguru import logger
import psycopg

from velocityfraud.db import apply_migrations, get_connection
from velocityfraud.schema import get_enriched_schema, get_scored_schema


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_EVENTS = int(os.getenv("SINK_MAX_EVENTS", "0"))
BOOTSTRAP = os.getenv("SINK_BOOTSTRAP", "localhost:9092")
GROUP = os.getenv("SINK_GROUP", "velocityfraud-sink-dev")
FROM = os.getenv("SINK_FROM", "earliest").lower()
BATCH_SIZE = int(os.getenv("SINK_BATCH_SIZE", "50"))
FLUSH_SEC = float(os.getenv("SINK_FLUSH_SEC", "2.0"))

SCORED_TOPIC = "transactions.scored"
ENRICHED_TOPIC = "transactions.enriched"
SCORED_GROQ_TOPIC = "transactions.scored.groq"   # Layer 5b — parallel LLM scores


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_should_stop = False


def _handle_sigint(signum, frame):
    global _should_stop
    _should_stop = True
    logger.warning("Ctrl-C received. Flushing batches and exiting...")


signal.signal(signal.SIGINT, _handle_sigint)


# ---------------------------------------------------------------------------
# INSERT statements — column order matches the row tuple order in flush_*
# ---------------------------------------------------------------------------
INSERT_SCORED_SQL = """
INSERT INTO scored_events (
    event_id, event_timestamp_ms, customer_id, card_token,
    amount, currency, amount_fx_normalised, merchant_id_hash,
    merchant_name, mcc, merchant_country, ip_address_hash,
    device_fingerprint_hash, geo_distance_km, source_label, schema_version,
    fraud_score, decision, model_name, model_version,
    scored_at_ms, scoring_latency_ms, feature_completeness,
    blocklist_hit, blocklist_tier, blocklist_reason,
    velocity_hit, velocity_window, velocity_reason
) VALUES (
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s
)
ON CONFLICT (event_id) DO UPDATE SET
    fraud_score          = EXCLUDED.fraud_score,
    decision             = EXCLUDED.decision,
    model_name           = EXCLUDED.model_name,
    model_version        = EXCLUDED.model_version,
    scored_at_ms         = EXCLUDED.scored_at_ms,
    scoring_latency_ms   = EXCLUDED.scoring_latency_ms,
    feature_completeness = EXCLUDED.feature_completeness,
    blocklist_hit        = EXCLUDED.blocklist_hit,
    blocklist_tier       = EXCLUDED.blocklist_tier,
    blocklist_reason     = EXCLUDED.blocklist_reason,
    velocity_hit         = EXCLUDED.velocity_hit,
    velocity_window      = EXCLUDED.velocity_window,
    velocity_reason      = EXCLUDED.velocity_reason
WHERE EXCLUDED.scored_at_ms >= scored_events.scored_at_ms
"""

INSERT_SCORED_GROQ_SQL = """
INSERT INTO scored_events_groq (
    event_id, event_timestamp_ms, customer_id, card_token,
    amount, currency, amount_fx_normalised, merchant_id_hash,
    merchant_name, mcc, merchant_country, ip_address_hash,
    device_fingerprint_hash, geo_distance_km, source_label, schema_version,
    fraud_score, decision, model_name, model_version,
    scored_at_ms, scoring_latency_ms, feature_completeness,
    llm_reason
) VALUES (
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s,
    %s
)
ON CONFLICT (event_id) DO UPDATE SET
    fraud_score          = EXCLUDED.fraud_score,
    decision             = EXCLUDED.decision,
    model_name           = EXCLUDED.model_name,
    model_version        = EXCLUDED.model_version,
    scored_at_ms         = EXCLUDED.scored_at_ms,
    scoring_latency_ms   = EXCLUDED.scoring_latency_ms,
    feature_completeness = EXCLUDED.feature_completeness,
    llm_reason           = EXCLUDED.llm_reason
WHERE EXCLUDED.scored_at_ms >= scored_events_groq.scored_at_ms
"""

INSERT_ENRICHED_SQL = """
INSERT INTO enriched_events (
    event_id, customer_id, amount, merchant_name, mcc,
    fraud_score, decision, feature_completeness,
    top_contributors, narrative, narrator_mode,
    enriched_at_ms, enrichment_latency_ms, narrative_grading_passed
) VALUES (
    %s, %s, %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s,
    %s, %s, %s
)
ON CONFLICT (event_id) DO UPDATE SET
    fraud_score           = EXCLUDED.fraud_score,
    decision              = EXCLUDED.decision,
    feature_completeness  = EXCLUDED.feature_completeness,
    top_contributors      = EXCLUDED.top_contributors,
    narrative             = EXCLUDED.narrative,
    narrator_mode         = EXCLUDED.narrator_mode,
    enriched_at_ms        = EXCLUDED.enriched_at_ms,
    enrichment_latency_ms = EXCLUDED.enrichment_latency_ms,
    narrative_grading_passed = EXCLUDED.narrative_grading_passed
WHERE EXCLUDED.enriched_at_ms >= enriched_events.enriched_at_ms
"""


# ---------------------------------------------------------------------------
# Row builders — convert Avro dict -> tuple in SQL param order
# ---------------------------------------------------------------------------
def _scored_row(ev: dict) -> tuple:
    return (
        ev["event_id"], ev["event_timestamp_ms"], ev["customer_id"], ev["card_token"],
        ev["amount"], ev["currency"], ev["amount_fx_normalised"], ev["merchant_id_hash"],
        ev["merchant_name"], ev["mcc"], ev["merchant_country"], ev["ip_address_hash"],
        ev["device_fingerprint_hash"], ev["geo_distance_km"], ev["source_label"], ev["schema_version"],
        ev["fraud_score"], ev["decision"], ev["model_name"], ev["model_version"],
        ev["scored_at_ms"], ev["scoring_latency_ms"], ev["feature_completeness"],
        # Layer 8 fields (backward-compat default from Avro schema)
        ev.get("blocklist_hit", False),
        ev.get("blocklist_tier", "NONE"),
        ev.get("blocklist_reason", ""),
        # Layer 8b fields (backward-compat default from Avro schema)
        ev.get("velocity_hit", False),
        ev.get("velocity_window", ""),
        ev.get("velocity_reason", ""),
    )


def _groq_row(ev: dict) -> tuple:
    """Groq scorer piggybacks the natural-language reason on blocklist_reason
    (avoids a second Avro schema). Sink unpacks it into llm_reason here."""
    return (
        ev["event_id"], ev["event_timestamp_ms"], ev["customer_id"], ev["card_token"],
        ev["amount"], ev["currency"], ev["amount_fx_normalised"], ev["merchant_id_hash"],
        ev["merchant_name"], ev["mcc"], ev["merchant_country"], ev["ip_address_hash"],
        ev["device_fingerprint_hash"], ev["geo_distance_km"], ev["source_label"], ev["schema_version"],
        ev["fraud_score"], ev["decision"], ev["model_name"], ev["model_version"],
        ev["scored_at_ms"], ev["scoring_latency_ms"], ev["feature_completeness"],
        ev.get("blocklist_reason", ""),   # <-- carries the LLM reason
    )


def _enriched_row(ev: dict) -> tuple:
    return (
        ev["event_id"], ev["customer_id"], ev["amount"], ev["merchant_name"], ev["mcc"],
        ev["fraud_score"], ev["decision"], ev["feature_completeness"],
        json.dumps(ev["top_contributors"]),  # JSONB column
        ev["narrative"], ev["narrator_mode"],
        ev["enriched_at_ms"], ev["enrichment_latency_ms"],
        # Real bug fix (2026-09-02): this field existed on the Avro schema and
        # slow_path.py's output but was never persisted -- see 006_narrative_grading.sql.
        ev.get("narrative_grading_passed", True),
    )


# ---------------------------------------------------------------------------
# Batched flusher
# ---------------------------------------------------------------------------
def _flush(conn, sql: str, batch: list, label: str) -> int:
    """Flush a batch via executemany. Returns rows attempted."""
    if not batch:
        return 0
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, batch)
        conn.commit()
        logger.info("Flushed {} batch: {} rows", label, len(batch))
        return len(batch)
    except Exception as e:
        conn.rollback()
        logger.error("Flush FAILED for {}: {} (batch dropped)", label, e)
        return 0


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main() -> int:
    global _should_stop

    logger.info("Applying migrations (idempotent)...")
    apply_migrations()

    logger.info("Loading Avro schemas...")
    scored_schema = get_scored_schema()
    enriched_schema = get_enriched_schema()

    logger.info("Connecting to Postgres...")
    conn = get_connection(autocommit=False)
    logger.info("Postgres connection OK.")

    logger.info("Connecting Kafka consumer (group={}, from={})...", GROUP, FROM)
    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        "group.id": GROUP,
        "auto.offset.reset": FROM,
        "enable.auto.commit": True,
        "isolation.level": "read_committed",
        "client.id": "velocityfraud-sink",
    })
    consumer.subscribe([SCORED_TOPIC, ENRICHED_TOPIC, SCORED_GROQ_TOPIC])

    logger.info("=" * 72)
    logger.info("SINK ONLINE  |  {} + {} + {}  ->  Postgres",
                SCORED_TOPIC, ENRICHED_TOPIC, SCORED_GROQ_TOPIC)
    logger.info("Batch: {} rows / {:.1f}s  |  Max events: {} (0 = unlimited)",
                BATCH_SIZE, FLUSH_SEC, MAX_EVENTS)
    logger.info("=" * 72)

    scored_batch: list[tuple] = []
    enriched_batch: list[tuple] = []
    groq_batch: list[tuple] = []
    n_in = 0
    n_decode_fail = 0
    n_scored_written = 0
    n_enriched_written = 0
    n_groq_written = 0
    last_flush = time.monotonic()
    start_time = time.monotonic()

    try:
        while not _should_stop:
            msg = consumer.poll(timeout=1.0)

            if msg is None:
                pass  # check flush below
            elif msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    logger.error("Consumer error: {}", msg.error())
            else:
                topic = msg.topic()
                try:
                    if topic == SCORED_TOPIC:
                        ev = fastavro.schemaless_reader(io.BytesIO(msg.value()), scored_schema)
                        scored_batch.append(_scored_row(ev))
                    elif topic == SCORED_GROQ_TOPIC:
                        ev = fastavro.schemaless_reader(io.BytesIO(msg.value()), scored_schema)
                        groq_batch.append(_groq_row(ev))
                    elif topic == ENRICHED_TOPIC:
                        ev = fastavro.schemaless_reader(io.BytesIO(msg.value()), enriched_schema)
                        enriched_batch.append(_enriched_row(ev))
                    else:
                        logger.warning("Unexpected topic: {}", topic)
                        continue
                    n_in += 1
                except Exception as e:
                    n_decode_fail += 1
                    logger.error("Decode failed t={} p={} off={}: {}",
                                 topic, msg.partition(), msg.offset(), e)

            # Flush triggers: batch full OR flush interval elapsed
            now = time.monotonic()
            time_since_flush = now - last_flush
            scored_full = len(scored_batch) >= BATCH_SIZE
            enriched_full = len(enriched_batch) >= BATCH_SIZE
            groq_full = len(groq_batch) >= BATCH_SIZE
            time_to_flush = time_since_flush >= FLUSH_SEC and (
                scored_batch or enriched_batch or groq_batch
            )

            if scored_full or enriched_full or groq_full or time_to_flush:
                n_scored_written += _flush(conn, INSERT_SCORED_SQL, scored_batch, "scored")
                n_enriched_written += _flush(conn, INSERT_ENRICHED_SQL, enriched_batch, "enriched")
                n_groq_written += _flush(conn, INSERT_SCORED_GROQ_SQL, groq_batch, "groq")
                scored_batch.clear()
                enriched_batch.clear()
                groq_batch.clear()
                last_flush = now

            if MAX_EVENTS and n_in >= MAX_EVENTS:
                logger.info("Reached max events cap ({}). Stopping.", MAX_EVENTS)
                break

    finally:
        # Final flush of any pending rows
        logger.info("Final flush...")
        n_scored_written += _flush(conn, INSERT_SCORED_SQL, scored_batch, "scored")
        n_enriched_written += _flush(conn, INSERT_ENRICHED_SQL, enriched_batch, "enriched")
        n_groq_written += _flush(conn, INSERT_SCORED_GROQ_SQL, groq_batch, "groq")
        consumer.close()
        conn.close()

        elapsed = time.monotonic() - start_time

        # Re-query totals to show what's actually in the DB
        with get_connection() as q:
            with q.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM scored_events")
                total_scored = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM enriched_events")
                total_enriched = cur.fetchone()[0]
                try:
                    cur.execute("SELECT COUNT(*) FROM scored_events_groq")
                    total_groq = cur.fetchone()[0]
                except Exception:
                    total_groq = 0  # migration not applied yet

        logger.info("=" * 72)
        logger.info("SINK SUMMARY")
        logger.info("=" * 72)
        logger.info("  Events consumed         : {}", n_in)
        logger.info("  Decode failures         : {}", n_decode_fail)
        logger.info("  Scored INSERTs attempted: {}", n_scored_written)
        logger.info("  Enriched INSERTs done   : {}", n_enriched_written)
        logger.info("  Groq  INSERTs done      : {}", n_groq_written)
        logger.info("  Total scored_events     : {} (across all runs)", total_scored)
        logger.info("  Total enriched_events   : {} (across all runs)", total_enriched)
        logger.info("  Total scored_events_groq: {} (across all runs)", total_groq)
        logger.info("  Elapsed                 : {:.1f}s", elapsed)
        logger.info("=" * 72)

    return 0


if __name__ == "__main__":
    sys.exit(main())

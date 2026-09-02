"""Text anomaly consumer — Layer 5.

Reads enriched events from Kafka (`transactions.enriched`), runs the
DistilBERT perplexity scorer on each merchant_name, and UPDATES the
corresponding row in `enriched_events` Postgres table.

Populates the three columns pre-allocated by Layer 6:
    text_anomaly_score   (0.0 - 1.0)
    text_anomaly_label   ("NORMAL" | "SUSPICIOUS")
    text_scored_at_ms    (bigint, millis since epoch)

Because Layer 6 pre-allocated these NULL columns, Layer 5 required ZERO
schema migration. This is the forward-compat pattern paying off.

Design choices:
    - Read Kafka messages ONLY to know which event_ids to score (we don't
      need to re-parse the whole enriched Avro payload here).
    - Take merchant_name straight from the Avro event to avoid a Postgres
      SELECT-then-UPDATE round trip.
    - Batched UPDATEs (executemany) — 20-50× throughput vs one-at-a-time.

Usage (from velocityfraud/ root):
    uv run python -m velocityfraud.text_anomaly_consumer

Env vars:
    TEXT_MAX_EVENTS       (default: 0 = no cap)
    TEXT_BOOTSTRAP        (default: localhost:9092)
    TEXT_GROUP            (default: velocityfraud-text-anomaly-dev)
    TEXT_IN_TOPIC         (default: transactions.enriched)
    TEXT_BATCH_SIZE       (default: 8)
    TEXT_FLUSH_SEC        (default: 2.0)
    TEXT_FROM             (default: earliest)
    TEXT_SUSPICIOUS_THRESHOLD  (default: 6.0)  # from text_anomaly.py
"""
from __future__ import annotations

import io
import os
import signal
import sys
import time

import fastavro
from confluent_kafka import Consumer, KafkaError
from loguru import logger

from velocityfraud.db import get_connection
from velocityfraud.schema import get_enriched_schema
from velocityfraud.text_anomaly import score_merchant


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_EVENTS = int(os.getenv("TEXT_MAX_EVENTS", "0"))
BOOTSTRAP = os.getenv("TEXT_BOOTSTRAP", "localhost:9092")
GROUP = os.getenv("TEXT_GROUP", "velocityfraud-text-anomaly-dev")
IN_TOPIC = os.getenv("TEXT_IN_TOPIC", "transactions.enriched")
BATCH_SIZE = int(os.getenv("TEXT_BATCH_SIZE", "8"))
FLUSH_SEC = float(os.getenv("TEXT_FLUSH_SEC", "2.0"))
FROM = os.getenv("TEXT_FROM", "earliest").lower()


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_should_stop = False


def _handle_sigint(signum, frame):
    global _should_stop
    _should_stop = True
    logger.warning("Ctrl-C received. Flushing batch and exiting...")


signal.signal(signal.SIGINT, _handle_sigint)


# ---------------------------------------------------------------------------
# UPDATE statement — batched via executemany
# ---------------------------------------------------------------------------
UPDATE_SQL = """
UPDATE enriched_events
SET
    text_anomaly_score = %s,
    text_anomaly_label = %s,
    text_scored_at_ms  = %s
WHERE event_id = %s
"""


def _flush(conn, batch: list) -> int:
    """Run batched UPDATEs. Returns number of rows attempted."""
    if not batch:
        return 0
    try:
        with conn.cursor() as cur:
            cur.executemany(UPDATE_SQL, batch)
            rows_affected = cur.rowcount
        conn.commit()
        logger.info("Flushed batch: {} rows attempted, {} rows updated",
                    len(batch), rows_affected)
        return rows_affected
    except Exception as e:
        conn.rollback()
        logger.error("Flush FAILED: {} (batch dropped)", e)
        return 0


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main() -> int:
    global _should_stop

    logger.info("Loading Avro schema...")
    enriched_schema = get_enriched_schema()

    logger.info("Warming DistilBERT (may download 250MB weights first time)...")
    # Score a throwaway string to trigger the model load NOW instead of on
    # first message (better startup experience).
    warmup = score_merchant("W-MERCHANT-warmup")
    logger.info("DistilBERT ready. Warmup score: {:.4f} label={}",
                warmup.score, warmup.label)

    logger.info("Connecting to Postgres...")
    conn = get_connection(autocommit=False)

    logger.info("Connecting Kafka consumer (group={}, from={})...", GROUP, FROM)
    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        "group.id": GROUP,
        "auto.offset.reset": FROM,
        "enable.auto.commit": True,
        "isolation.level": "read_committed",
        "client.id": "velocityfraud-text-anomaly",
    })
    consumer.subscribe([IN_TOPIC])

    logger.info("=" * 74)
    logger.info("TEXT ANOMALY CONSUMER ONLINE  |  {}  ->  Postgres.enriched_events",
                IN_TOPIC)
    logger.info("Batch: {} rows / {:.1f}s  |  Max events: {} (0 = unlimited)",
                BATCH_SIZE, FLUSH_SEC, MAX_EVENTS)
    logger.info("=" * 74)

    batch: list[tuple] = []
    n_in = 0
    n_decode_fail = 0
    n_score_fail = 0
    n_updated = 0
    label_counts = {"NORMAL": 0, "SUSPICIOUS": 0}
    latency_sum_ms = 0.0
    latency_max_ms = 0.0
    last_flush = time.monotonic()
    start_time = time.monotonic()

    try:
        while not _should_stop:
            msg = consumer.poll(timeout=1.0)

            if msg is None:
                pass  # go to flush check
            elif msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    logger.error("Consumer error: {}", msg.error())
            else:
                # Decode the enriched event (we only need event_id + merchant_name)
                try:
                    ev = fastavro.schemaless_reader(io.BytesIO(msg.value()),
                                                     enriched_schema)
                except Exception as e:
                    n_decode_fail += 1
                    logger.error("Decode failed p={} off={}: {}",
                                 msg.partition(), msg.offset(), e)
                    continue

                # Score
                t_start = time.monotonic()
                try:
                    result = score_merchant(ev["merchant_name"])
                    scored_at_ms = int(time.time() * 1000)
                except Exception as e:
                    n_score_fail += 1
                    logger.error("Score failed for event={}: {}",
                                 ev.get("event_id", "?")[:8], e)
                    continue
                latency_ms = (time.monotonic() - t_start) * 1000.0

                # Buffer the UPDATE row
                batch.append((
                    float(result.score),
                    result.label,
                    scored_at_ms,
                    ev["event_id"],
                ))
                n_in += 1
                label_counts[result.label] += 1
                latency_sum_ms += latency_ms
                if latency_ms > latency_max_ms:
                    latency_max_ms = latency_ms

                # Live log first 5, then every 10th
                if n_in <= 5 or n_in % 10 == 0:
                    logger.info(
                        "#{} event={} merchant='{}' | ppl={:.2f} log_ppl={:.4f} "
                        "score={:.4f} -> {} | lat={:.1f}ms",
                        n_in, ev["event_id"][:8], ev["merchant_name"][:40],
                        result.perplexity, result.log_perplexity, result.score,
                        result.label, latency_ms,
                    )

            # Flush triggers: batch full OR time elapsed
            now = time.monotonic()
            time_since_flush = now - last_flush
            if len(batch) >= BATCH_SIZE or (time_since_flush >= FLUSH_SEC and batch):
                n_updated += _flush(conn, batch)
                batch.clear()
                last_flush = now

            if MAX_EVENTS and n_in >= MAX_EVENTS:
                logger.info("Reached max events cap ({}). Stopping.", MAX_EVENTS)
                break

    finally:
        logger.info("Final flush...")
        n_updated += _flush(conn, batch)
        consumer.close()

        # Sanity check: query the DB to show how many rows now have text anomaly filled
        with get_connection() as q:
            with q.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM enriched_events "
                    "WHERE text_anomaly_score IS NOT NULL"
                )
                filled = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM enriched_events")
                total = cur.fetchone()[0]

        conn.close()
        elapsed = time.monotonic() - start_time
        avg_lat = latency_sum_ms / n_in if n_in else 0.0

        logger.info("=" * 74)
        logger.info("TEXT ANOMALY CONSUMER SUMMARY")
        logger.info("=" * 74)
        logger.info("  Events consumed          : {}", n_in)
        logger.info("  Decode failures          : {}", n_decode_fail)
        logger.info("  Score failures           : {}", n_score_fail)
        logger.info("  UPDATEs applied          : {}", n_updated)
        logger.info("  Label: NORMAL            : {}", label_counts["NORMAL"])
        logger.info("  Label: SUSPICIOUS        : {}", label_counts["SUSPICIOUS"])
        logger.info("  DB: rows with anomaly    : {} / {}", filled, total)
        logger.info("  Latency avg / max (ms)   : {:.2f} / {:.2f}",
                    avg_lat, latency_max_ms)
        logger.info("  Elapsed                  : {:.1f}s ({:.1f} events/s)",
                    elapsed, n_in / elapsed if elapsed else 0)
        logger.info("=" * 74)

    return 0


if __name__ == "__main__":
    sys.exit(main())

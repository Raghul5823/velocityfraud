"""Slow-path enricher — Layer 4.

Consumes scored events from `transactions.scored`, filters to REVIEW/BLOCK
only, runs SHAP + narrator, and produces enriched events to
`transactions.enriched`.

Pipeline per event:
    1. consume(transactions.scored) -> TransactionScoredEvent
    2. skip if decision == ALLOW
    3. re-build the 43-feature vector via live_features.featurize_event()
    4. explainer.explain_event() -> top-5 SHAP contributors
    5. narrator.generate_narrative() -> 2-3 sentence text (template or Gemini)
    6. build TransactionEnrichedEvent (echo 23 + add SHAP array + narrative)
    7. produce(transactions.enriched)

Latency budget: <2 seconds per event (SHAP ~50ms + narrator template ~1ms,
or Gemini ~500-1000ms; both well under the budget).

Usage (from velocityfraud/ root):
    uv run python -m velocityfraud.slow_path

Env vars:
    SLOWPATH_MAX_EVENTS    (default: 0 = no cap)
    SLOWPATH_BOOTSTRAP     (default: localhost:9092)
    SLOWPATH_GROUP         (default: velocityfraud-slowpath-dev)
    SLOWPATH_IN_TOPIC      (default: transactions.scored)
    SLOWPATH_OUT_TOPIC     (default: transactions.enriched)
    SLOWPATH_FROM          (default: earliest)
    NARRATOR_MODE          (default: auto)         template | gemini | auto
    GEMINI_API_KEY         (optional)              enables Gemini narrator
"""
from __future__ import annotations

import io
import os
import signal
import sys
import time

import fastavro
from confluent_kafka import Consumer, KafkaError, Producer
from loguru import logger

from velocityfraud.explainer import explain_event, get_explainer
from velocityfraud.live_features import featurize_event
from velocityfraud.narrator import generate_narrative
from velocityfraud.schema import get_enriched_schema, get_scored_schema


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_EVENTS = int(os.getenv("SLOWPATH_MAX_EVENTS", "0"))
BOOTSTRAP = os.getenv("SLOWPATH_BOOTSTRAP", "localhost:9092")
GROUP = os.getenv("SLOWPATH_GROUP", "velocityfraud-slowpath-dev")
IN_TOPIC = os.getenv("SLOWPATH_IN_TOPIC", "transactions.scored")
OUT_TOPIC = os.getenv("SLOWPATH_OUT_TOPIC", "transactions.enriched")
FROM = os.getenv("SLOWPATH_FROM", "earliest").lower()
TOP_N = int(os.getenv("SLOWPATH_TOP_N", "5"))


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_should_stop = False


def _handle_sigint(signum, frame):
    global _should_stop
    _should_stop = True
    logger.warning("Ctrl-C received. Flushing producer and exiting...")


signal.signal(signal.SIGINT, _handle_sigint)


# ---------------------------------------------------------------------------
# Avro codecs
# ---------------------------------------------------------------------------
def decode_scored(payload: bytes, schema: dict) -> dict:
    return fastavro.schemaless_reader(io.BytesIO(payload), schema)


def encode_enriched(event: dict, schema: dict) -> bytes:
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, schema, event)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Producer delivery callback
# ---------------------------------------------------------------------------
_produced = 0
_produce_failed = 0


def _on_delivery(err, msg):
    global _produced, _produce_failed
    if err is not None:
        _produce_failed += 1
        if _produce_failed <= 5:
            logger.error("Produce failed: key={} err={}", msg.key(), err)
    else:
        _produced += 1


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main() -> int:
    global _should_stop

    logger.info("Loading schemas...")
    scored_schema = get_scored_schema()
    enriched_schema = get_enriched_schema()
    logger.info("Schemas loaded: scored={} fields, enriched={} fields",
                len(scored_schema["fields"]), len(enriched_schema["fields"]))

    logger.info("Warming SHAP explainer (loads champion model)...")
    explainer = get_explainer()
    logger.info("SHAP explainer ready.")

    logger.info("Connecting Kafka consumer (group={}, from={})...", GROUP, FROM)
    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        "group.id": GROUP,
        "auto.offset.reset": FROM,
        "enable.auto.commit": True,
        "client.id": "velocityfraud-slowpath",
    })
    consumer.subscribe([IN_TOPIC])

    logger.info("Connecting Kafka producer...")
    producer = Producer({
        "bootstrap.servers": BOOTSTRAP,
        "client.id": "velocityfraud-slowpath-producer",
        "enable.idempotence": True,
        "acks": "all",
        "compression.type": "lz4",
        "linger.ms": 5,
        "batch.size": 16384,
    })

    narrator_mode_env = os.getenv("NARRATOR_MODE", "auto").lower()
    gemini_status = "ENABLED" if os.getenv("GEMINI_API_KEY", "").strip() else "disabled (template only)"

    logger.info("=" * 72)
    logger.info("SLOW-PATH ONLINE  |  in='{}' -> out='{}'", IN_TOPIC, OUT_TOPIC)
    logger.info("Filter: only REVIEW or BLOCK events processed")
    logger.info("Narrator mode: {} | Gemini: {}", narrator_mode_env, gemini_status)
    logger.info("Max events: {} (0 = unlimited, Ctrl-C to stop)", MAX_EVENTS)
    logger.info("=" * 72)

    n_in = 0
    n_skipped = 0
    n_enriched = 0
    n_decode_fail = 0
    n_explain_fail = 0
    narrator_counts = {"TEMPLATE": 0, "GEMINI": 0}
    latency_sum_ms = 0.0
    latency_max_ms = 0.0
    start_time = time.monotonic()

    try:
        while not _should_stop:
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error("Consumer error: {}", msg.error())
                continue

            # Decode the scored event
            try:
                scored = decode_scored(msg.value(), scored_schema)
            except Exception as e:
                n_decode_fail += 1
                logger.error("Decode failed p={} off={}: {}",
                             msg.partition(), msg.offset(), e)
                continue

            n_in += 1
            decision = scored.get("decision", "ALLOW")

            # Filter: only REVIEW or BLOCK reach the slow-path
            if decision == "ALLOW":
                n_skipped += 1
                continue

            t_start = time.monotonic()

            # Re-derive the feature vector (lightweight — Avro fields only)
            try:
                X, _completeness = featurize_event(scored)
                contribs = explain_event(explainer, X, top_n=TOP_N)
                narrative, mode_used = generate_narrative(scored, contribs)
            except Exception as e:
                n_explain_fail += 1
                logger.error("Enrichment failed for event={}: {}",
                             scored.get("event_id", "?")[:8], e)
                continue

            enrichment_latency_ms = (time.monotonic() - t_start) * 1000.0
            enriched_at_ms = int(time.time() * 1000)

            # Build the enriched event (echo all 23 scored fields + add 4 enrichment fields)
            enriched = {
                **scored,
                "top_contributors":     [fc.as_dict() for fc in contribs],
                "narrative":            narrative,
                "narrator_mode":        mode_used,
                "enriched_at_ms":       enriched_at_ms,
                "enrichment_latency_ms":int(round(enrichment_latency_ms)),
            }

            try:
                payload = encode_enriched(enriched, enriched_schema)
                producer.produce(
                    topic=OUT_TOPIC,
                    key=scored["customer_id"].encode("utf-8"),
                    value=payload,
                    on_delivery=_on_delivery,
                )
                producer.poll(0)
            except Exception as e:
                logger.error("Produce error for event={}: {}",
                             scored["event_id"][:8], e)
                continue

            n_enriched += 1
            narrator_counts[mode_used] += 1
            latency_sum_ms += enrichment_latency_ms
            if enrichment_latency_ms > latency_max_ms:
                latency_max_ms = enrichment_latency_ms

            # Live log first 5, then every 25
            if n_enriched <= 5 or n_enriched % 25 == 0:
                logger.info(
                    "#{} decision={} score={:.4f} | narrator={} | lat={:.1f}ms | "
                    "top1={} (impact {:+.3f})",
                    n_enriched, decision, scored.get("fraud_score", 0),
                    mode_used, enrichment_latency_ms,
                    contribs[0].feature_name, contribs[0].shap_value,
                )

            if MAX_EVENTS and n_enriched >= MAX_EVENTS:
                logger.info("Reached max events cap ({}). Stopping.", MAX_EVENTS)
                break

    finally:
        elapsed = time.monotonic() - start_time
        logger.info("Flushing producer...")
        producer.flush(timeout=30)
        consumer.close()

        avg_lat = latency_sum_ms / n_enriched if n_enriched else 0.0
        logger.info("=" * 72)
        logger.info("SLOW-PATH SUMMARY")
        logger.info("=" * 72)
        logger.info("  Events consumed         : {}", n_in)
        logger.info("  Events skipped (ALLOW)  : {}", n_skipped)
        logger.info("  Events enriched         : {}", n_enriched)
        logger.info("  Events produced         : {} (failed={})",
                    _produced, _produce_failed)
        logger.info("  Decode failures         : {}", n_decode_fail)
        logger.info("  Explain/narrate fails   : {}", n_explain_fail)
        logger.info("  Narrator: TEMPLATE      : {}", narrator_counts["TEMPLATE"])
        logger.info("  Narrator: GEMINI        : {}", narrator_counts["GEMINI"])
        logger.info("  Latency avg / max (ms)  : {:.2f} / {:.2f}",
                    avg_lat, latency_max_ms)
        logger.info("  Elapsed (s) / Throughput: {:.1f} / {:.1f} enriched/s",
                    elapsed, n_enriched / elapsed if elapsed else 0)
        logger.info("=" * 72)

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Fast-path scoring service — Layer 3.

The operational heart of VelocityFraud. This service:

    1. Consumes Avro events from `transactions.raw`
    2. Decodes each event with the TransactionEvent schema
    3. Maps it to a 43-feature vector via live_features.featurize_event()
    4. Calls the champion model's predict_proba()
    5. Applies a 3-tier threshold policy to derive a Decision
    6. Builds a TransactionScoredEvent (echoes original fields + score + decision)
    7. Produces it as Avro to `transactions.scored`

Threshold policy:
    score <  0.50  ->  ALLOW   (pass through)
    score >= 0.50  ->  REVIEW  (Layer 4 SHAP will explain)
    score >= 0.85  ->  BLOCK   (high-confidence fraud, take action)

Latency budget: <100 ms per event (decode + featurize + score + encode + produce).

Usage (from velocityfraud/ root):
    uv run python -m velocityfraud.scorer

Env vars:
    SCORER_MAX_EVENTS    (default: 0 = no cap)         stop after N events
    SCORER_BOOTSTRAP     (default: localhost:9092)
    SCORER_GROUP         (default: velocityfraud-scorer-dev)
    SCORER_IN_TOPIC      (default: transactions.raw)
    SCORER_OUT_TOPIC     (default: transactions.scored)
    SCORER_REVIEW_THRESH (default: 0.50)
    SCORER_BLOCK_THRESH  (default: 0.85)
    SCORER_FROM          (default: earliest)           earliest | latest
"""
from __future__ import annotations

import io
import os
import signal
import sys
import time
from pathlib import Path

import fastavro
from confluent_kafka import Consumer, KafkaError, Producer
from loguru import logger

from velocityfraud import blocklist  # Layer 8 blocklist pre-filter
from velocityfraud import velocity  # Layer 8b velocity pre-filter
from velocityfraud import score_cache  # score cache (Risk #1 mitigation)
from velocityfraud.live_features import featurize_event
from velocityfraud.predict import (
    get_champion_filename,
    get_champion_model,
    predict_proba,
)
from velocityfraud.schema import get_schema, get_scored_schema


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_EVENTS = int(os.getenv("SCORER_MAX_EVENTS", "0"))
BOOTSTRAP = os.getenv("SCORER_BOOTSTRAP", "localhost:9092")
GROUP = os.getenv("SCORER_GROUP", "velocityfraud-scorer-dev")
IN_TOPIC = os.getenv("SCORER_IN_TOPIC", "transactions.raw")
OUT_TOPIC = os.getenv("SCORER_OUT_TOPIC", "transactions.scored")
REVIEW_THRESH = float(os.getenv("SCORER_REVIEW_THRESH", "0.50"))
BLOCK_THRESH = float(os.getenv("SCORER_BLOCK_THRESH", "0.85"))
FROM = os.getenv("SCORER_FROM", "earliest").lower()

MODEL_VERSION = "v1"

# Pull the model name from CHAMPION.txt at startup — single source of truth
PROJECT_ROOT = Path(__file__).resolve().parents[2]


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
def decode_event(payload: bytes, schema: dict) -> dict:
    return fastavro.schemaless_reader(io.BytesIO(payload), schema)


def encode_scored(event: dict, schema: dict) -> bytes:
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, schema, event)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Decision policy
# ---------------------------------------------------------------------------
def decide(score: float) -> str:
    """Map a fraud probability to a Decision symbol."""
    if score >= BLOCK_THRESH:
        return "BLOCK"
    if score >= REVIEW_THRESH:
        return "REVIEW"
    return "ALLOW"


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

    # Boot: load schemas + champion model
    logger.info("Loading schemas...")
    raw_schema = get_schema()
    scored_schema = get_scored_schema()
    logger.info("Schemas loaded: raw={} fields, scored={} fields",
                len(raw_schema["fields"]), len(scored_schema["fields"]))

    logger.info("Loading champion model...")
    champion_name = get_champion_filename()
    model = get_champion_model()
    logger.info("Champion: {} ({})", champion_name, model.__class__.__name__)

    # Boot: Kafka clients
    logger.info("Connecting Kafka consumer (group={}, from={})...", GROUP, FROM)
    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        "group.id": GROUP,
        "auto.offset.reset": FROM,
        "enable.auto.commit": True,
        "isolation.level": "read_committed",
        "client.id": "velocityfraud-scorer",
    })
    consumer.subscribe([IN_TOPIC])

    logger.info("Connecting Kafka producer...")
    producer = Producer({
        "bootstrap.servers": BOOTSTRAP,
        "client.id": "velocityfraud-scorer-producer",
        "enable.idempotence": True,
        "acks": "all",
        "compression.type": "lz4",
        "linger.ms": 5,
        "batch.size": 16384,
    })

    logger.info("=" * 68)
    logger.info("SCORER ONLINE  |  in='{}' -> out='{}'", IN_TOPIC, OUT_TOPIC)
    logger.info("Thresholds: ALLOW < {} <= REVIEW < {} <= BLOCK",
                REVIEW_THRESH, BLOCK_THRESH)
    logger.info("Max events: {} (0 = unlimited, Ctrl-C to stop)", MAX_EVENTS)
    logger.info("=" * 68)

    n_in = 0
    n_decode_fail = 0
    n_score_fail = 0
    decision_counts = {"ALLOW": 0, "REVIEW": 0, "BLOCK": 0}
    # Layer 8 stats
    n_blocklist_hits = 0
    n_hotlist_hits = 0
    n_velocity_hits = 0
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

            t_start = time.monotonic()

            # Decode
            try:
                event = decode_event(msg.value(), raw_schema)
            except Exception as e:
                n_decode_fail += 1
                logger.error("Decode failed at p={} off={}: {}",
                             msg.partition(), msg.offset(), e)
                continue

            # ---- Layer 8: Blocklist check FIRST (fail-open on Redis error) ----
            v_result = velocity.VelocityResult()  # default no-hit; overwritten below if checked
            bl_result = blocklist.check(
                card_token=event.get("card_token"),
                merchant_id_hash=event.get("merchant_id_hash"),
                ip_hash=event.get("ip_address_hash"),
                device_hash=event.get("device_fingerprint_hash"),
            )

            if bl_result.hit and bl_result.tier == blocklist.Tier.BLOCK:
                # BLOCK-list hit: skip ML entirely, force decision = BLOCK
                score = 1.0
                completeness = 0.0
                decision = "BLOCK"
                n_blocklist_hits += 1
            elif bl_result.hit and bl_result.tier == blocklist.Tier.HOT:
                # HOT-list hit: skip ML, elevate to REVIEW
                score = 0.5
                completeness = 0.0
                decision = "REVIEW"
                n_hotlist_hits += 1
            else:
                # ---- Layer 8b: velocity pre-filter (fail-open on Redis error) ----
                v_result = velocity.check(
                    card_token=event.get("card_token"),
                    event_id=event.get("event_id", ""),
                )
                if v_result.hit:
                    # Card-testing burst detected: skip ML, force REVIEW.
                    score = 0.5
                    completeness = 0.0
                    decision = "REVIEW"
                    n_velocity_hits += 1
                else:
                    # No blocklist or velocity hit -> run ML normally (cached if possible)
                    try:
                        X, completeness = featurize_event(event)
                        h = score_cache.feature_hash(X)
                        cached = score_cache.get(h)
                        if cached.hit:
                            score, decision = cached.fraud_score, cached.decision
                        else:
                            score = float(predict_proba(model, X)[0])
                            decision = decide(score)
                            score_cache.set(h, score, decision)
                    except Exception as e:
                        n_score_fail += 1
                        logger.error("Scoring failed for event={}: {}",
                                     event.get("event_id", "?")[:8], e)
                        continue

            scored_at_ms = int(time.time() * 1000)
            latency_ms = (time.monotonic() - t_start) * 1000.0

            # Build the scored event (echo all raw fields + add scoring + blocklist fields)
            scored_event = {
                **event,
                "fraud_score":          score,
                "decision":             decision,
                "model_name":           champion_name,
                "model_version":        MODEL_VERSION,
                "scored_at_ms":         scored_at_ms,
                "scoring_latency_ms":   int(round(latency_ms)),
                "feature_completeness": completeness,
                # Layer 8 fields (defaults if not hit)
                "blocklist_hit":        bl_result.hit,
                "blocklist_tier":       bl_result.tier.value,
                "blocklist_reason":     bl_result.reason,
                # Layer 8b fields (defaults if not hit)
                "velocity_hit":         v_result.hit,
                "velocity_window":      v_result.window,
                "velocity_reason":      v_result.reason,
            }

            # Encode + produce
            try:
                payload = encode_scored(scored_event, scored_schema)
                producer.produce(
                    topic=OUT_TOPIC,
                    key=event["customer_id"].encode("utf-8"),
                    value=payload,
                    on_delivery=_on_delivery,
                )
                producer.poll(0)
            except Exception as e:
                logger.error("Produce error for event={}: {}",
                             event["event_id"][:8], e)
                continue

            # Stats
            n_in += 1
            decision_counts[decision] += 1
            latency_sum_ms += latency_ms
            if latency_ms > latency_max_ms:
                latency_max_ms = latency_ms

            # Live log first 10, then every 100
            if n_in <= 10 or n_in % 100 == 0:
                bl_tag = f" [{bl_result.tier.value}]" if bl_result.hit else ""
                logger.info(
                    "#{} p={} off={} key={} | score={:.4f} -> {}{} | "
                    "completeness={:.0%} | lat={:.1f}ms",
                    n_in, msg.partition(), msg.offset(),
                    event["customer_id"], score, decision, bl_tag,
                    completeness, latency_ms,
                )

            if MAX_EVENTS and n_in >= MAX_EVENTS:
                logger.info("Reached max events cap ({}). Stopping.", MAX_EVENTS)
                break

    finally:
        elapsed = time.monotonic() - start_time
        logger.info("Flushing producer...")
        producer.flush(timeout=30)
        consumer.close()

        avg_lat = latency_sum_ms / n_in if n_in else 0.0
        logger.info("=" * 68)
        logger.info("SCORER SUMMARY")
        logger.info("=" * 68)
        logger.info("  Events consumed         : {}", n_in)
        logger.info("  Events produced         : {} (failed={})",
                    _produced, _produce_failed)
        logger.info("  Decode failures         : {}", n_decode_fail)
        logger.info("  Score failures          : {}", n_score_fail)
        logger.info("  Decision: ALLOW         : {} ({:.1%})",
                    decision_counts["ALLOW"],
                    decision_counts["ALLOW"] / n_in if n_in else 0)
        logger.info("  Decision: REVIEW        : {} ({:.1%})",
                    decision_counts["REVIEW"],
                    decision_counts["REVIEW"] / n_in if n_in else 0)
        logger.info("  Blocklist hits (BLOCK)  : {} ({:.1%})",
                    n_blocklist_hits,
                    n_blocklist_hits / n_in if n_in else 0)
        logger.info("  Hot-list hits (REVIEW)  : {} ({:.1%})",
                    n_hotlist_hits,
                    n_hotlist_hits / n_in if n_in else 0)
        logger.info("  Velocity hits (REVIEW)  : {} ({:.1%})",
                    n_velocity_hits,
                    n_velocity_hits / n_in if n_in else 0)
        logger.info("  Decision: BLOCK         : {} ({:.1%})",
                    decision_counts["BLOCK"],
                    decision_counts["BLOCK"] / n_in if n_in else 0)
        logger.info("  Latency avg / max (ms)  : {:.2f} / {:.2f}",
                    avg_lat, latency_max_ms)
        logger.info("  Elapsed (s) / Throughput: {:.1f} / {:.1f} events/s",
                    elapsed, n_in / elapsed if elapsed else 0)
        logger.info("=" * 68)

    return 0


if __name__ == "__main__":
    sys.exit(main())

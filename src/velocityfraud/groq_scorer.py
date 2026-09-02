"""Groq LLM scoring path — Layer 5b (parallel to XGBoost Layer 3).

The proposal committed to "Groq near real-time transaction scoring". This
module implements that path as an LLM-as-classifier: transaction features are
formatted into a structured prompt, sent to Groq's fast LPU inference API,
and the returned JSON is parsed into a fraud score + decision.

WHY BOTH SCORERS?
    - XGBoost (Layer 3) = fast, cheap, offline. Handles the ALLOW bulk.
    - Groq LLM = second opinion with natural-language reasoning. Good for
      showing "why" this transaction looked risky in analyst-readable text.

    The two paths run in PARALLEL from the same `transactions.raw` topic and
    write to two separate downstream topics. Downstream code (sink, dashboard)
    joins them by event_id for side-by-side comparison.

SAFETY / COST GUARANTEES:
    1. Free-tier only. Model pinned to `llama-3.1-8b-instant` unless overridden.
    2. Rate-limited to 25 requests/min (Groq free tier is ~30/min).
    3. Fail-safe: if Groq API errors, we log and skip (do NOT crash the stream).
    4. Env-gated: requires GROQ_API_KEY, refuses to start without it.
    5. PII-safe prompt: only tokenized fields go to the API, never raw PAN.

Pipeline per event:
    1. consume from transactions.raw   (Avro TransactionEvent, 17 fields)
    2. build a fraud-classifier prompt from the tokenized features
    3. call Groq chat.completions with response_format=json_object
    4. parse {"fraud_score": float, "reason": str} from the LLM response
    5. threshold -> ALLOW / REVIEW / BLOCK   (same policy as XGBoost path)
    6. produce a TransactionScoredEvent to transactions.scored.groq
       (same Avro schema as XGBoost -> downstream is identical)

Usage (from velocityfraud/ root):
    uv run python -m velocityfraud.groq_scorer

Env vars:
    GROQ_API_KEY            (required) — free-tier key from console.groq.com
    GROQ_MODEL              (default: qwen/qwen3.8-27b -- llama-3.1-8b-instant
                             was removed from Groq's catalog entirely, not
                             just renamed; see docs/LAYER_5B_GROQ_SCORING.md)
    GROQ_MAX_RPM            (default: 25)   — soft rate cap
    GROQ_TIMEOUT_SEC        (default: 15)
    GROQ_SCORER_MAX_EVENTS  (default: 0 = no cap)
    GROQ_SCORER_BOOTSTRAP   (default: localhost:9092)
    GROQ_SCORER_GROUP       (default: velocityfraud-groq-scorer-dev)
    GROQ_SCORER_IN_TOPIC    (default: transactions.raw)
    GROQ_SCORER_OUT_TOPIC   (default: transactions.scored.groq)
    GROQ_SCORER_FROM        (default: earliest)
    SCORER_REVIEW_THRESH    (default: 0.50)     shared with XGBoost path
    SCORER_BLOCK_THRESH     (default: 0.85)     shared with XGBoost path
"""
from __future__ import annotations

import io
import json
import os
import signal
import sys
import time
from collections import deque

import fastavro
from confluent_kafka import Consumer, KafkaError, Producer
from dotenv import load_dotenv
from loguru import logger

from velocityfraud.schema import get_schema, get_scored_schema


# Load .env so GROQ_API_KEY is picked up even outside PowerShell env.
load_dotenv()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_KEY = os.getenv("GROQ_API_KEY", "").strip()
MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b").strip()
MAX_RPM = int(os.getenv("GROQ_MAX_RPM", "25"))
TIMEOUT_SEC = float(os.getenv("GROQ_TIMEOUT_SEC", "15"))

MAX_EVENTS = int(os.getenv("GROQ_SCORER_MAX_EVENTS", "0"))
BOOTSTRAP = os.getenv("GROQ_SCORER_BOOTSTRAP", "localhost:9092")
GROUP = os.getenv("GROQ_SCORER_GROUP", "velocityfraud-groq-scorer-dev")
IN_TOPIC = os.getenv("GROQ_SCORER_IN_TOPIC", "transactions.raw")
OUT_TOPIC = os.getenv("GROQ_SCORER_OUT_TOPIC", "transactions.scored.groq")
FROM = os.getenv("GROQ_SCORER_FROM", "earliest").lower()

# Shared thresholds so XGBoost + Groq use the same ALLOW/REVIEW/BLOCK bands.
REVIEW_THRESH = float(os.getenv("SCORER_REVIEW_THRESH", "0.50"))
BLOCK_THRESH = float(os.getenv("SCORER_BLOCK_THRESH", "0.85"))

MODEL_VERSION = "groq-v1"


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
# Rate limiter — sliding-window at MAX_RPM requests / 60 seconds.
# Free tier cap for llama-3.1-8b-instant is ~30 RPM; we default to 25 for
# safety margin so bursty traffic can't accidentally exceed the free tier.
# ---------------------------------------------------------------------------
class RateLimiter:
    def __init__(self, max_per_min: int):
        self.max_per_min = max_per_min
        self.calls: deque[float] = deque()

    def wait_slot(self) -> float:
        """Block if we've hit the RPM cap. Returns the wait time (0 if none)."""
        now = time.monotonic()
        cutoff = now - 60.0
        while self.calls and self.calls[0] < cutoff:
            self.calls.popleft()
        waited = 0.0
        if len(self.calls) >= self.max_per_min:
            wake_at = self.calls[0] + 60.0
            waited = max(0.0, wake_at - now)
            if waited > 0:
                logger.warning("Rate limit reached ({} rpm). Sleeping {:.1f}s...",
                               self.max_per_min, waited)
                time.sleep(waited)
        self.calls.append(time.monotonic())
        return waited


# ---------------------------------------------------------------------------
# Prompt engineering — the LLM sees ONLY tokenized fields, never raw PAN.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are a card-payment fraud classifier. You receive tokenized transaction "
    "features (never raw card numbers) and must return a JSON object with:\n"
    '  - "fraud_score" (float in [0.0, 1.0], probability this is fraud)\n'
    '  - "reason" (short string, <= 25 words, explaining the top risk drivers)\n'
    "Higher scores mean higher fraud likelihood. Consider: geo distance from "
    "cardholder home, unusual amounts for the MCC, mismatched merchant country, "
    "and any obviously suspicious merchant names. Base your score on the "
    "features provided; do not invent facts. Return ONLY valid JSON, no prose."
)


def build_user_prompt(event: dict) -> str:
    """Format the tokenized transaction as a compact feature block."""
    return (
        f"Transaction features:\n"
        f"  amount:           {event.get('amount'):.2f} {event.get('currency')}\n"
        f"  amount_usd:       {event.get('amount_fx_normalised'):.2f}\n"
        f"  merchant_name:    {event.get('merchant_name')}\n"
        f"  mcc:              {event.get('mcc')}\n"
        f"  merchant_country: {event.get('merchant_country')}\n"
        f"  geo_distance_km:  {event.get('geo_distance_km'):.1f}\n"
        f"  card_token:       {event.get('card_token')[:12]}...\n"
        f"  ip_hash:          {event.get('ip_address_hash')[:12]}...\n"
        f"  device_hash:      {event.get('device_fingerprint_hash')[:12]}...\n"
        f"  source:           {event.get('source_label')}\n"
        "\nReturn JSON with fraud_score and reason."
    )


# ---------------------------------------------------------------------------
# Groq API call — returns (score, reason) or raises.
# ---------------------------------------------------------------------------
def call_groq(client, event: dict) -> tuple[float, str]:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": build_user_prompt(event)},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,          # deterministic for reproducibility
        max_tokens=200,
        timeout=TIMEOUT_SEC,
    )
    raw = resp.choices[0].message.content or "{}"
    data = json.loads(raw)

    # Coerce fraud_score into a safe [0, 1] float.
    try:
        score = float(data.get("fraud_score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))

    reason = str(data.get("reason", "")).strip()[:300]  # cap for DB
    return score, reason


# ---------------------------------------------------------------------------
# Pre-warm heartbeat — closes proposal gap B9 (docs/proposal_gap_remediation.md).
# Proposal §11 Risk 8: "Groq free tier latency inconsistent on demo day...
# Pre-warm endpoint via heartbeat." A cold Groq connection's first real call
# can carry extra TLS/connection-setup latency; one cheap, throwaway call at
# startup absorbs that cost before any real transaction is scored.
# ---------------------------------------------------------------------------
def prewarm(client) -> float:
    """Fire one minimal, cheap completion to warm the connection. Best-effort —
    never raises; a failed pre-warm just means the first real call pays the
    cold-start cost instead, it does not block startup."""
    t0 = time.monotonic()
    try:
        client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
            timeout=TIMEOUT_SEC,
        )
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        logger.info("Groq pre-warm heartbeat OK ({:.0f} ms)", elapsed_ms)
        return elapsed_ms
    except Exception as e:
        logger.warning("Groq pre-warm heartbeat failed (non-fatal): {}", str(e)[:120])
        return -1.0


# ---------------------------------------------------------------------------
# Decision policy — SAME thresholds as XGBoost path for apples-to-apples.
# ---------------------------------------------------------------------------
def decide(score: float) -> str:
    if score >= BLOCK_THRESH:
        return "BLOCK"
    if score >= REVIEW_THRESH:
        return "REVIEW"
    return "ALLOW"


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

    if not API_KEY:
        logger.error("GROQ_API_KEY is not set. Add it to .env or export it.")
        logger.error("Sign up free at https://console.groq.com to get a key.")
        return 2

    # Lazy-import so a missing groq package gives a clear error later, not
    # at module load.
    try:
        from groq import Groq
    except ImportError:
        logger.error(
            "The 'groq' package is not installed. Run: uv sync"
        )
        return 2

    client = Groq(api_key=API_KEY)
    prewarm(client)

    logger.info("Loading Avro schemas...")
    raw_schema = get_schema()
    scored_schema = get_scored_schema()
    logger.info("Schemas loaded: raw={} fields, scored={} fields",
                len(raw_schema["fields"]), len(scored_schema["fields"]))

    logger.info("Groq config: model={} timeout={:.0f}s rate={} rpm",
                MODEL, TIMEOUT_SEC, MAX_RPM)

    logger.info("Connecting Kafka consumer (group={}, from={})...", GROUP, FROM)
    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        "group.id": GROUP,
        "auto.offset.reset": FROM,
        "enable.auto.commit": True,
        "isolation.level": "read_committed",
        "client.id": "velocityfraud-groq-scorer",
    })
    consumer.subscribe([IN_TOPIC])

    logger.info("Connecting Kafka producer...")
    producer = Producer({
        "bootstrap.servers": BOOTSTRAP,
        "client.id": "velocityfraud-groq-scorer-producer",
        "enable.idempotence": True,
        "acks": "all",
        "compression.type": "lz4",
        "linger.ms": 5,
        "batch.size": 16384,
    })

    rate_limiter = RateLimiter(MAX_RPM)

    logger.info("=" * 72)
    logger.info("GROQ SCORER ONLINE  |  in='{}' -> out='{}'", IN_TOPIC, OUT_TOPIC)
    logger.info("LLM: {} @ Groq   |  Thresholds: ALLOW < {} <= REVIEW < {} <= BLOCK",
                MODEL, REVIEW_THRESH, BLOCK_THRESH)
    logger.info("Max events: {} (0 = unlimited, Ctrl-C to stop)", MAX_EVENTS)
    logger.info("=" * 72)

    n_in = 0
    n_decode_fail = 0
    n_llm_fail = 0
    decision_counts = {"ALLOW": 0, "REVIEW": 0, "BLOCK": 0}
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

            # Decode
            try:
                event = decode_event(msg.value(), raw_schema)
            except Exception as e:
                n_decode_fail += 1
                logger.error("Decode failed at p={} off={}: {}",
                             msg.partition(), msg.offset(), e)
                continue

            # Rate-limit BEFORE hitting the API so we never exceed free tier.
            rate_limiter.wait_slot()

            # Groq call
            t_start = time.monotonic()
            try:
                score, reason = call_groq(client, event)
            except Exception as e:
                n_llm_fail += 1
                logger.error(
                    "Groq call failed for event={}: {} (skipping)",
                    event.get("event_id", "?")[:8], e
                )
                continue

            latency_ms = (time.monotonic() - t_start) * 1000.0
            decision = decide(score)
            scored_at_ms = int(time.time() * 1000)

            # Build the scored event. We reuse the SAME schema as XGBoost so
            # downstream (sink, Power BI) sees one shape. LLM reason lives in
            # blocklist_reason column for now — cheap way to piggyback text
            # without another schema change. (Sink will move it to llm_reason
            # for the groq table.)
            scored_event = {
                **event,
                "fraud_score":          score,
                "decision":             decision,
                "model_name":           f"groq:{MODEL}",
                "model_version":        MODEL_VERSION,
                "scored_at_ms":         scored_at_ms,
                "scoring_latency_ms":   int(round(latency_ms)),
                "feature_completeness": 1.0,  # LLM sees the full event
                "blocklist_hit":        False,
                "blocklist_tier":       "NONE",
                "blocklist_reason":     reason,   # <-- LLM natural-language reason
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

            if n_in <= 10 or n_in % 25 == 0:
                logger.info(
                    "#{} p={} off={} key={} | score={:.4f} -> {} | "
                    "lat={:.0f}ms | reason={}",
                    n_in, msg.partition(), msg.offset(),
                    event["customer_id"], score, decision, latency_ms,
                    reason[:60] + ("..." if len(reason) > 60 else ""),
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
        logger.info("=" * 72)
        logger.info("GROQ SCORER SUMMARY")
        logger.info("=" * 72)
        logger.info("  Events consumed         : {}", n_in)
        logger.info("  Events produced         : {} (failed={})",
                    _produced, _produce_failed)
        logger.info("  Decode failures         : {}", n_decode_fail)
        logger.info("  LLM API failures        : {}", n_llm_fail)
        logger.info("  Decision: ALLOW         : {} ({:.1%})",
                    decision_counts["ALLOW"],
                    decision_counts["ALLOW"] / n_in if n_in else 0)
        logger.info("  Decision: REVIEW        : {} ({:.1%})",
                    decision_counts["REVIEW"],
                    decision_counts["REVIEW"] / n_in if n_in else 0)
        logger.info("  Decision: BLOCK         : {} ({:.1%})",
                    decision_counts["BLOCK"],
                    decision_counts["BLOCK"] / n_in if n_in else 0)
        logger.info("  Latency avg / max (ms)  : {:.0f} / {:.0f}",
                    avg_lat, latency_max_ms)
        logger.info("  Elapsed (s) / Throughput: {:.1f} / {:.2f} events/s",
                    elapsed, n_in / elapsed if elapsed else 0)
        logger.info("=" * 72)

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""IEEE-CIS Fraud Detection stream consumer.

Subscribes to `transactions.raw`, decodes each Avro-encoded message back into a
Python dict using the TransactionEvent schema, and logs a one-line summary per
event. Closes Layer 1 by proving full Avro round-trip:

    producer (replayer)  →  Kafka broker  →  consumer (this file)

Usage (from velocityfraud/ root):
    uv run python -m velocityfraud.consumer

Env vars:
    CONSUMER_MAX_MESSAGES  (default: 0 = no cap)        stop after N messages
    CONSUMER_TOPIC         (default: transactions.raw)
    CONSUMER_BOOTSTRAP     (default: localhost:9092)
    CONSUMER_GROUP         (default: velocityfraud-consumer-dev)
    CONSUMER_FROM          (default: earliest)          earliest | latest
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

from velocityfraud.schema import get_schema


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MAX_MESSAGES = int(os.getenv("CONSUMER_MAX_MESSAGES", "0"))  # 0 = no cap
TOPIC = os.getenv("CONSUMER_TOPIC", "transactions.raw")
BOOTSTRAP = os.getenv("CONSUMER_BOOTSTRAP", "localhost:9092")
GROUP = os.getenv("CONSUMER_GROUP", "velocityfraud-consumer-dev")
FROM = os.getenv("CONSUMER_FROM", "earliest").lower()


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_should_stop = False


def _handle_sigint(signum, frame):
    global _should_stop
    _should_stop = True
    logger.warning("Ctrl-C received. Closing consumer...")


signal.signal(signal.SIGINT, _handle_sigint)


# ---------------------------------------------------------------------------
# Avro decoding
# ---------------------------------------------------------------------------
def decode_event(payload: bytes, schema: dict) -> dict:
    """Decode Avro bytes back into a Python dict using the local schema."""
    buf = io.BytesIO(payload)
    return fastavro.schemaless_reader(buf, schema)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main() -> int:
    global _should_stop

    logger.info("Loading Avro schema...")
    schema = get_schema()
    logger.info("Schema loaded: {} fields", len(schema["fields"]))

    logger.info(
        "Connecting to Kafka at {} (group={}, from={})",
        BOOTSTRAP, GROUP, FROM,
    )
    consumer = Consumer({
        "bootstrap.servers": BOOTSTRAP,
        "group.id": GROUP,
        "auto.offset.reset": FROM,
        "enable.auto.commit": True,
        "client.id": "velocityfraud-consumer",
    })

    consumer.subscribe([TOPIC])
    logger.info(
        "Subscribed to '{}' | max={} (0=unlimited) | Ctrl-C to stop",
        TOPIC, MAX_MESSAGES,
    )

    n_consumed = 0
    n_failed = 0
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

            try:
                event = decode_event(msg.value(), schema)
            except Exception as e:
                n_failed += 1
                logger.error(
                    "Decode failed at offset={} partition={}: {}",
                    msg.offset(), msg.partition(), e,
                )
                continue

            n_consumed += 1

            logger.info(
                "p={} off={} key={} | event={}... amount={:.2f} mcc={} merch='{}'",
                msg.partition(),
                msg.offset(),
                msg.key().decode("utf-8") if msg.key() else "",
                event["event_id"][:8],
                event["amount"],
                event["mcc"],
                event["merchant_name"][:32],
            )

            if MAX_MESSAGES and n_consumed >= MAX_MESSAGES:
                logger.info("Reached max messages cap ({}). Stopping.", MAX_MESSAGES)
                break

    finally:
        elapsed = time.monotonic() - start_time
        logger.info("Closing consumer...")
        consumer.close()
        logger.info(
            "Done. Consumed={} failed={} elapsed={:.1f}s avg={:.1f} msg/s",
            n_consumed, n_failed, elapsed,
            n_consumed / elapsed if elapsed else 0,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())

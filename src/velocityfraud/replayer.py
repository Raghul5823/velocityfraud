"""IEEE-CIS Fraud Detection stream replayer.

Reads `data/raw/train_transaction.csv` row by row, maps each row to our Avro
`TransactionEvent`, and publishes to the `transactions.raw` Kafka topic at a
configurable rate.

Usage (from velocityfraud/ root):
    uv run python -m velocityfraud.replayer

Env vars:
    REPLAYER_TPS         (default: 10)        events per second to publish
    REPLAYER_MAX_EVENTS  (default: 0 = all)   stop after N events
    REPLAYER_TOPIC       (default: transactions.raw)
    REPLAYER_BOOTSTRAP   (default: localhost:9092)
    REPLAYER_CSV         (default: data/raw/train_transaction.csv)
"""
from __future__ import annotations

import io
import os
import signal
import sys
import time
import uuid
from pathlib import Path

import fastavro
import pandas as pd
from confluent_kafka import Producer
from loguru import logger

from velocityfraud.schema import get_schema
from velocityfraud.tokenizer import tokenize


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_TPS = int(os.getenv("REPLAYER_TPS", "10"))
MAX_EVENTS = int(os.getenv("REPLAYER_MAX_EVENTS", "0"))  # 0 = no cap
TOPIC = os.getenv("REPLAYER_TOPIC", "transactions.raw")
BOOTSTRAP = os.getenv("REPLAYER_BOOTSTRAP", "localhost:9092")
CSV_PATH = Path(
    os.getenv(
        "REPLAYER_CSV",
        Path(__file__).resolve().parents[2] / "data" / "raw" / "train_transaction.csv",
    )
)
CHUNK_SIZE = 5_000
LOG_EVERY = 1_000

# Reference epoch — IEEE-CIS TransactionDT is seconds since this point.
# (Vesta's anonymisation: 2017-12-01 00:00:00 UTC is the conventional anchor.)
REFERENCE_EPOCH_MS = 1_512_086_400_000

# ProductCD → pseudo-MCC mapping (so we have a 4-digit-style merchant category)
PRODUCTCD_TO_MCC = {
    "W": "5411",  # Grocery
    "C": "5732",  # Electronics
    "R": "5812",  # Restaurants
    "H": "7011",  # Hotels
    "S": "5999",  # Specialty retail (default)
}


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
# Row → Avro mapping
# ---------------------------------------------------------------------------
def row_to_event(row: pd.Series) -> dict:
    """Map one IEEE-CIS transaction row to a TransactionEvent dict."""
    card1 = row.get("card1")
    customer_id = str(int(card1)) if pd.notna(card1) else "unknown"

    card_concat = f"{row.get('card1')}|{row.get('card2')}|{row.get('card3')}|{row.get('card5')}"

    product_cd = row.get("ProductCD", "S")
    mcc = PRODUCTCD_TO_MCC.get(product_cd, "5999")

    p_email = row.get("P_emaildomain", "anonymous.com") or "anonymous.com"
    merchant_name = f"{product_cd}-MERCHANT-{p_email}"

    addr1 = row.get("addr1")
    addr2 = row.get("addr2")
    merchant_id_concat = f"{product_cd}|{addr1}|{addr2}"

    dist = row.get("dist1")
    if pd.isna(dist):
        dist = row.get("dist2", 0.0) or 0.0
    geo_distance_km = float(dist) if pd.notna(dist) else 0.0

    txn_dt_seconds = row.get("TransactionDT", 0) or 0
    event_timestamp_ms = REFERENCE_EPOCH_MS + int(txn_dt_seconds) * 1000

    amount = float(row.get("TransactionAmt", 0.0) or 0.0)

    return {
        "event_id": str(uuid.uuid4()),
        "event_timestamp_ms": event_timestamp_ms,
        "customer_id": customer_id,
        "card_token": tokenize(card_concat),
        "amount": amount,
        "currency": "USD",
        "amount_fx_normalised": amount,
        "merchant_id_hash": tokenize(merchant_id_concat),
        "merchant_name": merchant_name,
        "mcc": mcc,
        "merchant_country": str(int(addr2)) if pd.notna(addr2) else "00",
        "ip_address_hash": tokenize(f"ip|{customer_id}"),
        "device_fingerprint_hash": tokenize(f"dev|{customer_id}"),
        "geo_distance_km": geo_distance_km,
        "source_label": "replayer",
        "schema_version": "v1",
    }


# ---------------------------------------------------------------------------
# Avro encoding
# ---------------------------------------------------------------------------
def encode_event(event: dict, schema: dict) -> bytes:
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, schema, event)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Kafka delivery callback
# ---------------------------------------------------------------------------
_delivered = 0
_failed = 0


def _delivery_report(err, msg):
    global _delivered, _failed
    if err is not None:
        _failed += 1
        if _failed <= 5:  # avoid spamming logs
            logger.error("Delivery failed for key={}: {}", msg.key(), err)
    else:
        _delivered += 1


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main() -> int:
    global _should_stop

    if not CSV_PATH.exists():
        logger.error("CSV not found at {}", CSV_PATH)
        return 1

    logger.info("Loading Avro schema...")
    schema = get_schema()
    logger.info("Schema loaded: {} fields", len(schema["fields"]))

    logger.info("Connecting to Kafka at {}", BOOTSTRAP)
    producer = Producer({
        "bootstrap.servers": BOOTSTRAP,
        "client.id": "velocityfraud-replayer",
        "enable.idempotence": True,
        "acks": "all",
        "compression.type": "lz4",
        "linger.ms": 5,
        "batch.size": 16384,
    })

    rate = DEFAULT_TPS
    sleep_between = 1.0 / rate if rate > 0 else 0
    logger.info(
        "Replayer started — rate={} tps, topic={}, csv={}",
        rate, TOPIC, CSV_PATH.name,
    )

    n_published = 0
    start_time = time.monotonic()
    last_log_time = start_time

    cols = [
        "TransactionID", "TransactionDT", "TransactionAmt",
        "ProductCD", "card1", "card2", "card3", "card4", "card5", "card6",
        "addr1", "addr2", "dist1", "dist2",
        "P_emaildomain", "R_emaildomain",
    ]

    try:
        reader = pd.read_csv(CSV_PATH, usecols=cols, chunksize=CHUNK_SIZE)
        for chunk in reader:
            if _should_stop:
                break
            for _, row in chunk.iterrows():
                if _should_stop:
                    break
                if MAX_EVENTS and n_published >= MAX_EVENTS:
                    _should_stop = True
                    break

                event = row_to_event(row)
                payload = encode_event(event, schema)
                key = event["customer_id"].encode("utf-8")

                producer.produce(
                    topic=TOPIC,
                    key=key,
                    value=payload,
                    on_delivery=_delivery_report,
                )
                producer.poll(0)

                n_published += 1
                if n_published % LOG_EVERY == 0:
                    now = time.monotonic()
                    inst_rate = LOG_EVERY / (now - last_log_time)
                    last_log_time = now
                    logger.info(
                        "Published {} events  |  delivered={}  failed={}  inst={:.1f} tps",
                        n_published, _delivered, _failed, inst_rate,
                    )

                if sleep_between:
                    time.sleep(sleep_between)
    finally:
        logger.info("Flushing producer (this may take a few seconds)...")
        producer.flush(timeout=30)
        total = time.monotonic() - start_time
        logger.info(
            "Done. Published={} delivered={} failed={} elapsed={:.1f}s avg={:.1f} tps",
            n_published, _delivered, _failed, total,
            n_published / total if total else 0,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())

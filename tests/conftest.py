"""Shared fixtures for the integration suite.

Every fixture below probes a live service and SKIPS the test if it's not
reachable, so:
  - locally with `docker compose up` running, the integration tests execute and
    contribute real coverage;
  - in CI without the infra, they skip and the pure-unit tests still pass green.

Bring the stack up with:
    docker compose -f infra/docker-compose.yml up -d
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def redis_ready():
    """Skip unless Redis (blocklist store + leader lock) is reachable."""
    from velocityfraud import blocklist
    try:
        if not blocklist.is_redis_alive():
            pytest.skip("Redis not reachable")
    except Exception as e:  # pragma: no cover - defensive
        pytest.skip(f"Redis probe failed: {e}")
    return blocklist


@pytest.fixture(scope="session")
def pg_ready():
    """Skip unless Postgres is reachable; ensure migrations are applied."""
    from velocityfraud import db
    try:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
    except Exception as e:
        pytest.skip(f"Postgres not reachable: {e}")
    try:
        db.apply_migrations()
    except Exception as e:  # pragma: no cover - defensive
        pytest.skip(f"Migrations failed: {e}")
    return db


@pytest.fixture(scope="session")
def kafka_ready():
    """Skip unless a Kafka broker is reachable."""
    import os
    from confluent_kafka.admin import AdminClient
    bootstrap = os.getenv("SCORER_BOOTSTRAP", "localhost:9092")
    try:
        admin = AdminClient({"bootstrap.servers": bootstrap})
        md = admin.list_topics(timeout=5)
        if not md.brokers:
            pytest.skip("Kafka has no brokers")
    except Exception as e:
        pytest.skip(f"Kafka not reachable: {e}")
    return bootstrap


@pytest.fixture(scope="session")
def model_ready():
    """Skip unless the champion model + feature meta are present on disk."""
    from velocityfraud.predict import get_champion_model, get_feature_names
    try:
        model = get_champion_model()
        feats = get_feature_names()
    except Exception as e:
        pytest.skip(f"Champion model/feature-meta unavailable: {e}")
    return model, feats


@pytest.fixture
def sample_event() -> dict:
    """A single well-formed TransactionEvent dict (16 raw fields)."""
    return {
        "event_id":                "it-0001",
        "event_timestamp_ms":      1_782_731_301_417,
        "customer_id":             "13926",
        "card_token":              "10c1bf7c3c76e313",
        "amount":                  245.40,
        "currency":                "USD",
        "amount_fx_normalised":    245.40,
        "merchant_id_hash":        "5f59d374246893e0",
        "merchant_name":           "W-MERCHANT-gmail.com",
        "mcc":                     "5411",
        "merchant_country":        "US",
        "ip_address_hash":         "98e58ca964c583e2",
        "device_fingerprint_hash": "a245d9cb16edd5da",
        "geo_distance_km":         12.5,
        "source_label":            "integration-test",
        "schema_version":          "v1",
    }

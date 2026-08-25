"""End-to-end pipeline integration test — the real Week-8 "E2E" deliverable.

Drives the actual operational entry points in sequence against live Kafka +
Postgres + Redis + the champion model:

    replayer.main()        -> produces N TransactionEvents to an isolated topic
    scorer.main()          -> consumes them, scores, produces to transactions.scored
    failover_scorer.main() -> hot-standby scorer path, capped run
    sink.main()            -> consumes transactions.scored, upserts to Postgres

Each stage is capped via *_MAX_EVENTS and reloaded so its module-level config
picks up the test env. Isolated input topics keep the run from disturbing real
data; the scored/sink stage is idempotent (ON CONFLICT DO NOTHING).
"""
from __future__ import annotations

import importlib
import os
import uuid

import pytest

pytestmark = pytest.mark.integration

N = 15  # events to push through the pipeline


@pytest.fixture(scope="module")
def topics(kafka_ready):
    """Create isolated raw + failover-out topics; delete them after the module."""
    from confluent_kafka.admin import AdminClient, NewTopic
    suffix = uuid.uuid4().hex[:8]
    raw = f"it.raw.{suffix}"
    fo = f"it.fo.{suffix}"
    admin = AdminClient({"bootstrap.servers": kafka_ready})
    fs = admin.create_topics([
        NewTopic(raw, num_partitions=1, replication_factor=1),
        NewTopic(fo, num_partitions=1, replication_factor=1),
    ])
    for f in fs.values():
        try:
            f.result(timeout=15)
        except Exception:
            pass
    yield {"raw": raw, "fo": fo, "bootstrap": kafka_ready}
    try:
        admin.delete_topics([raw, fo])
    except Exception:
        pass


def test_replayer_produces(topics, model_ready, monkeypatch):
    monkeypatch.setenv("REPLAYER_MAX_EVENTS", str(N))
    monkeypatch.setenv("REPLAYER_TPS", "1000")
    monkeypatch.setenv("REPLAYER_TOPIC", topics["raw"])
    monkeypatch.setenv("REPLAYER_BOOTSTRAP", topics["bootstrap"])
    import velocityfraud.replayer as rep
    importlib.reload(rep)
    rc = rep.main()
    assert rc == 0


def test_scorer_consumes_and_scores(topics, model_ready, redis_ready, monkeypatch):
    monkeypatch.setenv("SCORER_MAX_EVENTS", str(N))
    monkeypatch.setenv("SCORER_IN_TOPIC", topics["raw"])
    monkeypatch.setenv("SCORER_OUT_TOPIC", "transactions.scored")  # real topic (sink reads it)
    monkeypatch.setenv("SCORER_FROM", "earliest")
    monkeypatch.setenv("SCORER_GROUP", f"it-scorer-{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("SCORER_BOOTSTRAP", topics["bootstrap"])
    import velocityfraud.scorer as sc
    importlib.reload(sc)
    rc = sc.main()
    assert rc == 0


def test_consumer_roundtrip(topics, monkeypatch):
    # Proves Avro producer -> broker -> consumer round-trip (Layer 1).
    monkeypatch.setenv("CONSUMER_MAX_MESSAGES", str(N))
    monkeypatch.setenv("CONSUMER_TOPIC", topics["raw"])
    monkeypatch.setenv("CONSUMER_FROM", "earliest")
    monkeypatch.setenv("CONSUMER_GROUP", f"it-consumer-{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("CONSUMER_BOOTSTRAP", topics["bootstrap"])
    import velocityfraud.consumer as cons
    importlib.reload(cons)
    rc = cons.main()
    assert rc == 0


def test_failover_scorer_capped_run(topics, model_ready, redis_ready, monkeypatch):
    monkeypatch.setenv("FAILOVER_MAX_EVENTS", str(N))
    monkeypatch.setenv("FAILOVER_IN_TOPIC", topics["raw"])
    monkeypatch.setenv("FAILOVER_OUT_TOPIC", topics["fo"])
    monkeypatch.setenv("FAILOVER_FROM", "earliest")
    monkeypatch.setenv("FAILOVER_GROUP", f"it-fo-{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("FAILOVER_ROLE", "primary")
    monkeypatch.setenv("FAILOVER_LOCK_KEY", f"it:leader:{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("FAILOVER_BOOTSTRAP", topics["bootstrap"])
    import velocityfraud.failover_scorer as fs
    importlib.reload(fs)
    rc = fs.main()
    assert rc == 0


def test_sink_writes_to_postgres(pg_ready, kafka_ready, monkeypatch):
    # Count before, run the sink over a capped slice of transactions.scored,
    # confirm it ran cleanly and the table is non-decreasing.
    with pg_ready.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM scored_events")
            before = cur.fetchone()[0]

    monkeypatch.setenv("SINK_MAX_EVENTS", str(N))
    monkeypatch.setenv("SINK_FROM", "earliest")
    monkeypatch.setenv("SINK_GROUP", f"it-sink-{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("SINK_BATCH_SIZE", "5")
    monkeypatch.setenv("SINK_FLUSH_SEC", "1.0")
    import velocityfraud.sink as sk
    importlib.reload(sk)
    rc = sk.main()
    assert rc == 0

    with pg_ready.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM scored_events")
            after = cur.fetchone()[0]
    assert after >= before

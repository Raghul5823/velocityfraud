"""Integration test for the blocklist updater (Postgres -> Redis, Layer 8).

Seeds a handful of synthetic BLOCK scored_events for a unique test card / ip /
device (scored_at_ms = now), then runs the updater in both dry-run and live
mode to exercise the detection SQL and the block/hot branches. Cleans up all
seeded rows and Redis entries afterwards so real data is untouched.
"""
from __future__ import annotations

import time
import uuid

import pytest

pytestmark = pytest.mark.integration


def _base_scored(event_id: str, card: str, ip: str, device: str, now_ms: int) -> dict:
    return {
        "event_id": event_id,
        "event_timestamp_ms": now_ms,
        "customer_id": "it-cust",
        "card_token": card,
        "amount": 500.0,
        "currency": "USD",
        "amount_fx_normalised": 500.0,
        "merchant_id_hash": "it-merch",
        "merchant_name": "S-MERCHANT-anonymous.com",
        "mcc": "5999",
        "merchant_country": "00",
        "ip_address_hash": ip,
        "device_fingerprint_hash": device,
        "geo_distance_km": 9000.0,
        "source_label": "updater-test",
        "schema_version": "v1",
        "fraud_score": 0.97,
        "decision": "BLOCK",
        "model_name": "xgboost_v1",
        "model_version": "v1",
        "scored_at_ms": now_ms,
        "scoring_latency_ms": 20,
        "feature_completeness": 0.5,
        "blocklist_hit": False,
        "blocklist_tier": "NONE",
        "blocklist_reason": "",
    }


def test_updater_detects_and_blocks_repeat_offenders(pg_ready, redis_ready):
    from velocityfraud import blocklist, blocklist_updater
    from velocityfraud.sink import _scored_row, INSERT_SCORED_SQL

    tag = uuid.uuid4().hex[:10]
    card = f"itcard{tag}"
    ip = f"itip{tag}"
    device = f"itdev{tag}"
    now_ms = int(time.time() * 1000)
    event_ids = [f"it-upd-{tag}-{i}" for i in range(5)]  # 5 BLOCKs => card+device block, ip block

    # ---- seed synthetic BLOCK events ----
    rows = [_scored_row(_base_scored(eid, card, ip, device, now_ms)) for eid in event_ids]
    with pg_ready.get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(INSERT_SCORED_SQL, rows)
        conn.commit()

    try:
        # ---- dry-run: detects but does not touch Redis ----
        stats_dry = blocklist_updater.run_update(dry_run=True)
        assert stats_dry.cards_blocked >= 1        # our card has 5 BLOCKs (>=3)
        r = blocklist.check(card_token=card, merchant_id_hash=None,
                            ip_hash=None, device_hash=None)
        assert not r.hit                            # dry-run wrote nothing

        # ---- live: actually blocklists the offenders ----
        stats_live = blocklist_updater.run_update(dry_run=False)
        assert stats_live.cards_blocked >= 1
        r = blocklist.check(card_token=card, merchant_id_hash=None,
                            ip_hash=None, device_hash=None)
        assert r.hit and r.tier == blocklist.Tier.BLOCK
    finally:
        # ---- cleanup: Redis entries + seeded rows ----
        blocklist.remove_blocklist("card", card)
        blocklist.remove_blocklist("ip", ip)
        blocklist.remove_blocklist("device", device)
        with pg_ready.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM scored_events WHERE event_id = ANY(%s)",
                    (event_ids,),
                )
            conn.commit()


def test_updater_main_dry_run(pg_ready, redis_ready, monkeypatch):
    from velocityfraud import blocklist_updater
    monkeypatch.setattr("sys.argv", ["blocklist_updater", "--dry-run"])
    assert blocklist_updater.main() == 0

"""Integration tests against a live Redis:

    blocklist.py       - 3-tier block/hot/white list with guardrails + TTL
    failover_scorer.py - LeaderLock election + the shared scoring path

Uses unique key suffixes so the test never collides with real data, and cleans
up after itself.
"""
from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# blocklist.py
# ---------------------------------------------------------------------------
def test_block_check_and_whitelist_priority(redis_ready):
    bl = redis_ready
    card = f"it-card-{uuid.uuid4().hex[:10]}"

    # 1. blocklisting requires block_count >= 3
    assert bl.add_blocklist("card", card, "only 2 events", block_count=2, ttl_s=30) is False

    # 2. a valid blocklist add -> check returns a BLOCK hit
    assert bl.add_blocklist("card", card, "3 blocks in 24h", block_count=3, ttl_s=30) is True
    r = bl.check(card_token=card, merchant_id_hash=None, ip_hash=None, device_hash=None)
    assert r.hit and r.tier == bl.Tier.BLOCK

    # 3. whitelist wins over blocklist
    bl.add_whitelist("card", card, "customer appeal", ttl_s=30)
    r = bl.check(card_token=card, merchant_id_hash=None, ip_hash=None, device_hash=None)
    assert not r.hit and r.tier == bl.Tier.NONE

    # 4. cannot blocklist a whitelisted entity
    assert bl.add_blocklist("card", card, "should refuse", block_count=5, ttl_s=30) is False

    # cleanup
    bl.remove_whitelist("card", card)
    bl.remove_blocklist("card", card)


def test_hotlist_elevates_to_review(redis_ready):
    bl = redis_ready
    merch = f"it-merch-{uuid.uuid4().hex[:10]}"
    assert bl.add_hotlist("merchant", merch, "2 blocks", block_count=2, ttl_s=30) is True
    r = bl.check(card_token=None, merchant_id_hash=merch, ip_hash=None, device_hash=None)
    assert r.hit and r.tier == bl.Tier.HOT
    assert bl.remove_hotlist("merchant", merch) == 1


def test_blocklist_invalid_entity_type_raises(redis_ready):
    bl = redis_ready
    with pytest.raises(ValueError):
        bl.add_blocklist("passport", "x", "bad type", block_count=3)


def test_blocklist_miss_returns_none(redis_ready):
    bl = redis_ready
    r = bl.check(card_token=f"absent-{uuid.uuid4().hex}", merchant_id_hash=None,
                 ip_hash=None, device_hash=None)
    assert not r.hit and r.tier == bl.Tier.NONE


def test_blocklist_stats_shape(redis_ready):
    bl = redis_ready
    s = bl.stats()
    assert s["redis_alive"] is True
    assert "counts" in s
    assert "blocklist.card" in s["counts"]


# ---------------------------------------------------------------------------
# failover_scorer.py — LeaderLock election
# ---------------------------------------------------------------------------
def test_leaderlock_acquire_refresh_release(redis_ready):
    import redis as redis_lib
    from velocityfraud import blocklist
    from velocityfraud.failover_scorer import LeaderLock

    client = redis_lib.Redis(
        host=blocklist.REDIS_HOST, port=blocklist.REDIS_PORT, db=blocklist.REDIS_DB,
        socket_timeout=1.0, decode_responses=True,
    )
    key = f"it:leader:{uuid.uuid4().hex[:8]}"
    client.delete(key)
    a = LeaderLock(client, key, "inst-A", ttl_ms=2000, role="primary")
    b = LeaderLock(client, key, "inst-B", ttl_ms=2000, role="standby")

    assert a.try_acquire() is True        # A wins
    assert b.try_acquire() is False       # B blocked while A holds
    assert a.refresh() is True            # A still owns it
    a.release()
    assert b.try_acquire() is True        # freed -> B can take it
    assert a.refresh() is False           # A no longer owns it (B does)
    b.release()
    client.delete(key)


# ---------------------------------------------------------------------------
# failover_scorer.score_event — the shared scoring path (Redis + model)
# ---------------------------------------------------------------------------
def test_score_event_produces_valid_scored_event(redis_ready, model_ready, sample_event):
    from velocityfraud.failover_scorer import score_event, decode_event, encode_scored
    from velocityfraud.schema import get_scored_schema
    from velocityfraud.predict import get_champion_filename, get_champion_model

    model = get_champion_model()
    champ = get_champion_filename()
    scored, latency = score_event(sample_event, model, champ)

    assert scored["decision"] in ("ALLOW", "REVIEW", "BLOCK")
    assert 0.0 <= scored["fraud_score"] <= 1.0
    assert scored["model_name"] == champ
    assert latency >= 0.0
    # the scored event must round-trip through the Avro scored schema
    payload = encode_scored(scored, get_scored_schema())
    assert isinstance(payload, bytes) and len(payload) > 0


def test_decide_thresholds():
    from velocityfraud.failover_scorer import decide, REVIEW_THRESH, BLOCK_THRESH
    assert decide(BLOCK_THRESH) == "BLOCK"
    assert decide(REVIEW_THRESH) == "REVIEW"
    assert decide(0.0) == "ALLOW"

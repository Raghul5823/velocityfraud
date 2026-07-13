"""Layer 8 — Redis-backed blocklist for VelocityFraud.

Two tiers of pre-ML filtering, both non-destructive to the payment flow:

    BLOCK-LIST : hard action. Score decision = BLOCK, ML skipped.
    HOT-LIST   : soft action. Score decision elevated to REVIEW, ML skipped.

Priority order (evaluated top-down):
    1. Whitelist  -> skip Layer 8 entirely, run ML normally
    2. Block-list -> return BlocklistResult(hit=True, tier=BLOCK)
    3. Hot-list   -> return BlocklistResult(hit=True, tier=HOT)
    4. Nothing    -> return BlocklistResult(hit=False, tier=NONE)

Safety guardrails baked in:
    - STRICT criteria for auto-adding entries (checked by blocklist_updater.py)
    - Every entry has a TTL (auto-expires — no permanent bans)
    - Whitelist always wins (human override)
    - Add operations are audit-logged
    - Redis unavailable -> return NONE (fail-open, never fail-closed on
      infrastructure error; ML pipeline still runs, no legitimate customer
      ever gets blocked because Redis is down)

Key naming convention:
    bl:{entity_type}:{id}   -> blocklist entry
    hl:{entity_type}:{id}   -> hot-list entry
    wl:{entity_type}:{id}   -> whitelist entry

entity_type is one of: card, merchant, ip, device.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Optional

import redis
from loguru import logger


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_TIMEOUT_S = float(os.getenv("REDIS_TIMEOUT_S", "0.5"))

# Default TTLs (in seconds) per entity type.
TTL_CARD_S = int(os.getenv("BLOCKLIST_TTL_CARD_S", str(24 * 3600)))       # 24 h
TTL_MERCHANT_S = int(os.getenv("BLOCKLIST_TTL_MERCHANT_S", str(7 * 24 * 3600)))  # 7 d
TTL_IP_S = int(os.getenv("BLOCKLIST_TTL_IP_S", str(3600)))                # 1 h
TTL_DEVICE_S = int(os.getenv("BLOCKLIST_TTL_DEVICE_S", str(24 * 3600)))   # 24 h
TTL_WHITELIST_S = int(os.getenv("BLOCKLIST_TTL_WHITELIST_S", str(30 * 24 * 3600)))  # 30 d


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
class Tier(str, Enum):
    NONE = "NONE"
    HOT = "HOT"
    BLOCK = "BLOCK"


ENTITY_TYPES = ("card", "merchant", "ip", "device")


@dataclass
class BlocklistResult:
    hit: bool = False
    tier: Tier = Tier.NONE
    reason: str = ""
    matched_entity_type: str = ""
    matched_entity_id: str = ""


# ---------------------------------------------------------------------------
# Redis client (lazy, cached)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _client() -> redis.Redis:
    """Return a single Redis client for the process (cached)."""
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        socket_timeout=REDIS_TIMEOUT_S,
        socket_connect_timeout=REDIS_TIMEOUT_S,
        decode_responses=True,  # return str, not bytes
    )


def is_redis_alive() -> bool:
    """Quick health check. Returns True if PING succeeds, False otherwise."""
    try:
        return bool(_client().ping())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Key helpers
# ---------------------------------------------------------------------------
def _bl_key(entity_type: str, entity_id: str) -> str:
    return f"bl:{entity_type}:{entity_id}"


def _hl_key(entity_type: str, entity_id: str) -> str:
    return f"hl:{entity_type}:{entity_id}"


def _wl_key(entity_type: str, entity_id: str) -> str:
    return f"wl:{entity_type}:{entity_id}"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _default_ttl(entity_type: str) -> int:
    return {
        "card":     TTL_CARD_S,
        "merchant": TTL_MERCHANT_S,
        "ip":       TTL_IP_S,
        "device":   TTL_DEVICE_S,
    }[entity_type]


# ---------------------------------------------------------------------------
# CHECK — the hot path (called by scorer.py per event, must be sub-ms)
# ---------------------------------------------------------------------------
def check(
    card_token: Optional[str],
    merchant_id_hash: Optional[str],
    ip_hash: Optional[str],
    device_hash: Optional[str],
) -> BlocklistResult:
    """Check all four entities against block/hot/white lists in priority order.

    Fail-open safety: if Redis is unreachable, return NONE so ML runs normally.
    A network hiccup MUST NOT auto-flag legitimate customers as fraud.
    """
    try:
        c = _client()
        # Build the list of (entity_type, entity_id) pairs we can check
        checks = [
            ("card",     card_token),
            ("merchant", merchant_id_hash),
            ("ip",       ip_hash),
            ("device",   device_hash),
        ]
        checks = [(t, i) for t, i in checks if i]

        # 1. Whitelist wins — if ANY entity is whitelisted, skip blocklist entirely.
        for entity_type, entity_id in checks:
            if c.exists(_wl_key(entity_type, entity_id)):
                return BlocklistResult(
                    hit=False, tier=Tier.NONE,
                    reason=f"whitelist:{entity_type}={entity_id[:12]}",
                )

        # 2. Block-list — hard hit, decision = BLOCK
        for entity_type, entity_id in checks:
            raw = c.get(_bl_key(entity_type, entity_id))
            if raw:
                info = json.loads(raw) if raw.startswith("{") else {}
                reason = info.get("reason", f"{entity_type}={entity_id[:12]} on blocklist")
                return BlocklistResult(
                    hit=True, tier=Tier.BLOCK, reason=reason,
                    matched_entity_type=entity_type,
                    matched_entity_id=entity_id,
                )

        # 3. Hot-list — soft hit, decision = REVIEW
        for entity_type, entity_id in checks:
            raw = c.get(_hl_key(entity_type, entity_id))
            if raw:
                info = json.loads(raw) if raw.startswith("{") else {}
                reason = info.get("reason", f"{entity_type}={entity_id[:12]} on hot-list")
                return BlocklistResult(
                    hit=True, tier=Tier.HOT, reason=reason,
                    matched_entity_type=entity_type,
                    matched_entity_id=entity_id,
                )

        return BlocklistResult(hit=False, tier=Tier.NONE)

    except redis.RedisError as e:
        # Fail-open: log and let ML run. Never block legit customers because
        # Redis is having a bad day.
        logger.warning("Redis unavailable during blocklist check ({}). "
                       "Falling through to ML.", str(e)[:80])
        return BlocklistResult(hit=False, tier=Tier.NONE)


# ---------------------------------------------------------------------------
# ADD — called by blocklist_updater.py (NOT the scoring hot path)
# ---------------------------------------------------------------------------
def _validate_entity_type(entity_type: str) -> None:
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"entity_type must be one of {ENTITY_TYPES}, got {entity_type!r}")


def add_blocklist(
    entity_type: str,
    entity_id: str,
    reason: str,
    block_count: int,
    ttl_s: Optional[int] = None,
) -> bool:
    """Add an entity to the BLOCK-list. Returns True on success.

    Safety guardrails (enforced here for defence in depth):
        1. entity_type must be one of ENTITY_TYPES
        2. block_count must be >= 3 (never blocklist on a single event)
        3. TTL always set (no permanent entries)
        4. Whitelist takes precedence — if entity is whitelisted, refuse to blocklist
    """
    _validate_entity_type(entity_type)
    if block_count < 3:
        logger.warning("Refusing to blocklist {}={}: block_count={} < 3",
                       entity_type, entity_id[:12], block_count)
        return False

    c = _client()

    # Whitelist check — human override always wins
    if c.exists(_wl_key(entity_type, entity_id)):
        logger.warning("Refusing to blocklist {}={}: entity is on whitelist",
                       entity_type, entity_id[:12])
        return False

    ttl = ttl_s if ttl_s is not None else _default_ttl(entity_type)
    payload = {
        "added_at_ms":  _now_ms(),
        "expires_at_ms": _now_ms() + ttl * 1000,
        "reason":       reason,
        "block_count":  block_count,
        "tier":         Tier.BLOCK.value,
    }
    c.set(_bl_key(entity_type, entity_id), json.dumps(payload), ex=ttl)
    logger.info("BLOCKLIST-ADD {}={} ttl={}s reason={!r}",
                entity_type, entity_id[:12], ttl, reason)
    return True


def add_hotlist(
    entity_type: str,
    entity_id: str,
    reason: str,
    block_count: int,
    ttl_s: Optional[int] = None,
) -> bool:
    """Add an entity to the HOT-list (softer than blocklist).

    Guardrails:
        1. entity_type valid
        2. block_count must be >= 2 (looser than blocklist)
        3. TTL always set
        4. Whitelist wins
    """
    _validate_entity_type(entity_type)
    if block_count < 2:
        logger.warning("Refusing to hotlist {}={}: block_count={} < 2",
                       entity_type, entity_id[:12], block_count)
        return False

    c = _client()
    if c.exists(_wl_key(entity_type, entity_id)):
        logger.warning("Refusing to hotlist {}={}: entity is on whitelist",
                       entity_type, entity_id[:12])
        return False

    ttl = ttl_s if ttl_s is not None else _default_ttl(entity_type)
    payload = {
        "added_at_ms":   _now_ms(),
        "expires_at_ms": _now_ms() + ttl * 1000,
        "reason":        reason,
        "block_count":   block_count,
        "tier":          Tier.HOT.value,
    }
    c.set(_hl_key(entity_type, entity_id), json.dumps(payload), ex=ttl)
    logger.info("HOTLIST-ADD {}={} ttl={}s reason={!r}",
                entity_type, entity_id[:12], ttl, reason)
    return True


def add_whitelist(
    entity_type: str,
    entity_id: str,
    reason: str,
    ttl_s: Optional[int] = None,
) -> bool:
    """Add an entity to the WHITELIST (human override).

    Whitelist is the ONE operation that can be triggered by an appeal
    (appeal.py). It takes priority over both blocklist and hot-list.
    Removing a whitelist entry after the appeal is legit is optional — the
    default 30-day TTL is a safe self-cleaning fallback.
    """
    _validate_entity_type(entity_type)
    c = _client()
    ttl = ttl_s if ttl_s is not None else TTL_WHITELIST_S
    payload = {
        "added_at_ms":   _now_ms(),
        "expires_at_ms": _now_ms() + ttl * 1000,
        "reason":        reason,
    }
    c.set(_wl_key(entity_type, entity_id), json.dumps(payload), ex=ttl)
    logger.info("WHITELIST-ADD {}={} ttl={}s reason={!r}",
                entity_type, entity_id[:12], ttl, reason)
    return True


# ---------------------------------------------------------------------------
# ADMIN helpers — for CLI / ops
# ---------------------------------------------------------------------------
def remove_blocklist(entity_type: str, entity_id: str) -> int:
    """Force-remove a block-list entry. Returns 1 if removed, 0 if none existed."""
    _validate_entity_type(entity_type)
    return int(_client().delete(_bl_key(entity_type, entity_id)))


def remove_hotlist(entity_type: str, entity_id: str) -> int:
    _validate_entity_type(entity_type)
    return int(_client().delete(_hl_key(entity_type, entity_id)))


def remove_whitelist(entity_type: str, entity_id: str) -> int:
    _validate_entity_type(entity_type)
    return int(_client().delete(_wl_key(entity_type, entity_id)))


def stats() -> dict:
    """Return counts of entries by list + entity type. Useful for the health check."""
    c = _client()
    out: dict = {"redis_alive": True, "counts": {}}
    try:
        for prefix, list_name in (("bl", "blocklist"), ("hl", "hotlist"), ("wl", "whitelist")):
            for entity_type in ENTITY_TYPES:
                pattern = f"{prefix}:{entity_type}:*"
                # SCAN so we don't block Redis on a huge KEYS operation
                count = 0
                cursor = 0
                while True:
                    cursor, keys = c.scan(cursor=cursor, match=pattern, count=500)
                    count += len(keys)
                    if cursor == 0:
                        break
                out["counts"][f"{list_name}.{entity_type}"] = count
    except Exception as e:
        out["redis_alive"] = False
        out["error"] = str(e)[:120]
    return out


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
def _demo() -> int:
    logger.info("=" * 74)
    logger.info("BLOCKLIST MODULE DEMO")
    logger.info("=" * 74)

    if not is_redis_alive():
        logger.error("Redis is NOT reachable at {}:{}. Start with: "
                     "docker compose -f infra/docker-compose.yml up -d redis",
                     REDIS_HOST, REDIS_PORT)
        return 1

    logger.info("Redis alive at {}:{}", REDIS_HOST, REDIS_PORT)
    logger.info("-" * 74)

    # Scenario: repeat-offender card gets blocklisted
    card = "demo_card_abc123"
    ok = add_blocklist("card", card, "3 BLOCKs in 24h (demo)", block_count=3, ttl_s=60)
    logger.info("Added blocklist entry: {}", ok)

    # Check: card should now be blocked
    r = check(card_token=card, merchant_id_hash=None, ip_hash=None, device_hash=None)
    logger.info("check({}) -> hit={} tier={} reason={!r}",
                card, r.hit, r.tier.value, r.reason)
    assert r.hit and r.tier == Tier.BLOCK, "expected block-list hit"

    # Scenario: user files an appeal -> we whitelist -> future checks pass through
    add_whitelist("card", card, "customer appeal accepted (demo)", ttl_s=60)
    r = check(card_token=card, merchant_id_hash=None, ip_hash=None, device_hash=None)
    logger.info("After whitelist: hit={} tier={} reason={!r}",
                r.hit, r.tier.value, r.reason)
    assert not r.hit, "whitelist must win over blocklist"

    # Scenario: try to blocklist a whitelisted card -> refused
    added = add_blocklist("card", card, "should be refused (demo)", block_count=5, ttl_s=60)
    logger.info("Add blocklist on whitelisted card -> success? {}", added)
    assert added is False, "whitelist must prevent blocklist add"

    # Scenario: try to blocklist with block_count < 3 -> refused
    added = add_blocklist("card", "other_card", "only 2 events", block_count=2, ttl_s=60)
    logger.info("Add blocklist with block_count=2 -> success? {}", added)
    assert added is False, "block_count < 3 must be refused"

    # Hot-list check
    add_hotlist("merchant", "demo_merch_xyz", "2 BLOCKs in 24h", block_count=2, ttl_s=60)
    r = check(card_token=None, merchant_id_hash="demo_merch_xyz",
              ip_hash=None, device_hash=None)
    logger.info("Hot-list check: hit={} tier={} reason={!r}",
                r.hit, r.tier.value, r.reason)
    assert r.hit and r.tier == Tier.HOT, "expected hot-list hit"

    # Clean up
    remove_whitelist("card", card)
    remove_blocklist("card", card)
    remove_hotlist("merchant", "demo_merch_xyz")

    logger.info("-" * 74)
    logger.info("Current stats:")
    for k, v in stats()["counts"].items():
        logger.info("  {:25s} {}", k, v)
    logger.info("=" * 74)
    logger.success("Blocklist module demo PASSED.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_demo())

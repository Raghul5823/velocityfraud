"""Velocity counters — a live, Redis-backed sliding-window pre-filter.

Closes the proposal gap tracked in docs/proposal_gap_remediation.md (§4, B1):
the original proposal described "sliding-window velocity counters (1-min,
10-min, 60-min)" as a feature computed inside Kafka Streams and fed into the
model. That never existed. Retraining the champion model this late to accept
a new input feature was rejected as too risky (see the remediation doc for
the full reasoning) — instead this module implements velocity counting as a
**live pre-filter rule**, architecturally the same slot Layer 8's blocklist
already occupies: it runs before/alongside the ML score, not inside the
model's trained weights.

Detects card-testing bursts: many authorizations on the same card in a short
window (the proposal's own worked example: "6 transactions on the same card
within 90 seconds, small round amounts at 03:12 local time").

Design (deliberately mirrors blocklist.py's conventions):
    - One Redis SORTED SET per card: key = vl:card:{card_token}
    - score  = event timestamp (ms)   member = event_id
    - ZADD the new event, then ZREMRANGEBYSCORE to evict anything older than
      the longest window — this eviction is what makes it a genuine SLIDING
      window (continuously evicting), not a fixed/tumbling window that only
      resets on a clock boundary.
    - Three windows are all read from the SAME sorted set via ZCOUNT range
      queries (one ZADD + three cheap range counts, rather than three
      separate sets) — 1-min, 10-min, 60-min, each with its own threshold.
    - EXPIRE the key to the longest window — self-cleaning, same philosophy
      as the blocklist TTLs (nothing lives forever, no manual cleanup job).
    - Fail-open: identical to blocklist.py. If Redis is unreachable, log and
      return "no hit" — a network hiccup must never auto-flag a legitimate
      customer.

This is a pre-filter SIGNAL, not a trained model feature. It forces a
decision (REVIEW) independent of the ML score, the same way Layer 8's
HOT-list tier does — it does not claim to be "inside Kafka Streams" and does
not claim to influence the champion model's probability output.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
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

# Window definitions: (label, seconds, threshold). Threshold = count that
# triggers a hit for that window. Shorter windows use tighter thresholds
# (card-testing bursts are fast); longer windows tolerate more normal
# repeat-usage (a frequent shopper) before flagging.
WINDOWS = (
    ("1min",  int(os.getenv("VELOCITY_WINDOW_1MIN_S",  "60")),   int(os.getenv("VELOCITY_THRESH_1MIN",  "5"))),
    ("10min", int(os.getenv("VELOCITY_WINDOW_10MIN_S", "600")),  int(os.getenv("VELOCITY_THRESH_10MIN", "12"))),
    ("60min", int(os.getenv("VELOCITY_WINDOW_60MIN_S", "3600")), int(os.getenv("VELOCITY_THRESH_60MIN", "25"))),
)
_LONGEST_WINDOW_S = max(w[1] for w in WINDOWS)


@dataclass
class VelocityResult:
    hit: bool = False
    window: str = ""
    count: int = 0
    threshold: int = 0
    reason: str = ""


@lru_cache(maxsize=1)
def _client() -> redis.Redis:
    """Same cached-client pattern as blocklist.py — one client per process."""
    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        socket_timeout=REDIS_TIMEOUT_S,
        socket_connect_timeout=REDIS_TIMEOUT_S,
        decode_responses=True,
    )


def _key(card_token: str) -> str:
    return f"vl:card:{card_token}"


def check(card_token: Optional[str], event_id: str) -> VelocityResult:
    """Record this transaction and check all 3 windows for a burst.

    Fail-open: if Redis is unreachable, log and return no-hit so ML scoring
    proceeds normally — infrastructure trouble must never look like fraud.
    """
    if not card_token:
        return VelocityResult(hit=False)

    try:
        c = _client()
        key = _key(card_token)
        now_ms = int(time.time() * 1000)

        # Record this event, then evict anything older than the longest
        # window we care about — this eviction is the "sliding" part.
        c.zadd(key, {event_id: now_ms})
        cutoff_ms = now_ms - (_LONGEST_WINDOW_S * 1000)
        c.zremrangebyscore(key, "-inf", cutoff_ms)
        c.expire(key, _LONGEST_WINDOW_S)

        # Check narrowest-to-widest so the most specific (fastest-firing)
        # window reports first if multiple windows would trip at once.
        for label, window_s, threshold in WINDOWS:
            window_cutoff_ms = now_ms - (window_s * 1000)
            count = c.zcount(key, window_cutoff_ms, "+inf")
            if count >= threshold:
                return VelocityResult(
                    hit=True, window=label, count=int(count), threshold=threshold,
                    reason=f"{count} txns on card in {label} (threshold {threshold})",
                )

        return VelocityResult(hit=False)

    except redis.RedisError as e:
        logger.warning("Redis unavailable during velocity check ({}). "
                       "Falling through to ML.", str(e)[:80])
        return VelocityResult(hit=False)


def stats(card_token: str) -> dict:
    """Current counts per window for a card — used by health-check/demo tooling."""
    try:
        c = _client()
        key = _key(card_token)
        now_ms = int(time.time() * 1000)
        out = {"redis_alive": True, "counts": {}}
        for label, window_s, threshold in WINDOWS:
            cutoff_ms = now_ms - (window_s * 1000)
            out["counts"][label] = {
                "count": int(c.zcount(key, cutoff_ms, "+inf")),
                "threshold": threshold,
            }
        return out
    except redis.RedisError as e:
        return {"redis_alive": False, "error": str(e)[:120]}


# ---------------------------------------------------------------------------
# Smoke test — simulates the proposal's own worked example: 6 transactions
# on one card within 90 seconds should trip the 1-min window.
# ---------------------------------------------------------------------------
def _demo() -> int:
    logger.info("=" * 74)
    logger.info("VELOCITY COUNTER MODULE DEMO")
    logger.info("=" * 74)

    try:
        if not _client().ping():
            raise redis.RedisError("ping failed")
    except redis.RedisError:
        logger.error("Redis is NOT reachable at {}:{}. Start with: "
                     "docker compose -f infra/docker-compose.yml up -d redis",
                     REDIS_HOST, REDIS_PORT)
        return 1

    logger.info("Redis alive at {}:{}", REDIS_HOST, REDIS_PORT)
    card = "demo_velocity_card_xyz"
    _client().delete(_key(card))  # clean slate for the demo

    logger.info("-" * 74)
    logger.info("Simulating a card-testing burst: 6 rapid transactions...")
    result = None
    for i in range(6):
        result = check(card_token=card, event_id=f"demo-evt-{i}")
        logger.info("  txn {}: hit={} window={!r} count={}",
                    i + 1, result.hit, result.window, result.count)

    assert result is not None and result.hit, "expected the 1-min window to trip by the 5th/6th txn"
    logger.success("Velocity pre-filter correctly flagged the burst: {}", result.reason)

    _client().delete(_key(card))
    logger.info("=" * 74)
    logger.success("Velocity counter module demo PASSED.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_demo())

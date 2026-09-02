"""Score cache — closes proposal gap B7 (docs/proposal_gap_remediation.md).

Proposal §11 Risk 1 mitigation: "cache scores for identical feature hashes
(1-min TTL)" — protection against re-scoring the exact same transaction
fingerprint repeatedly in a short window (e.g., a retried/duplicated request
from an upstream payment gateway, or a client-side double-submit).

Deliberately minimal: a single Redis GET/SET wrapper, same fail-open
philosophy as blocklist.py and velocity.py — a cache-unavailable condition
must never block or alter a real scoring decision, only skip the optimisation.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

import redis
from loguru import logger

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_TIMEOUT_S = float(os.getenv("REDIS_TIMEOUT_S", "0.5"))
CACHE_TTL_S = int(os.getenv("SCORE_CACHE_TTL_S", "60"))  # 1-min, per the proposal


@dataclass
class CachedScore:
    hit: bool = False
    fraud_score: float = 0.0
    decision: str = ""


@lru_cache(maxsize=1)
def _client() -> redis.Redis:
    return redis.Redis(
        host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB,
        socket_timeout=REDIS_TIMEOUT_S, socket_connect_timeout=REDIS_TIMEOUT_S,
        decode_responses=True,
    )


def feature_hash(x_row) -> str:
    """Stable hash of a feature vector (numpy row or list-like)."""
    return hashlib.sha256(json.dumps(list(x_row), default=float).encode()).hexdigest()[:32]


def get(hash_key: str) -> CachedScore:
    """Look up a cached score. Fail-open: any Redis trouble = cache miss."""
    try:
        raw = _client().get(f"sc:{hash_key}")
        if raw is None:
            return CachedScore(hit=False)
        payload = json.loads(raw)
        return CachedScore(hit=True, fraud_score=payload["fraud_score"], decision=payload["decision"])
    except redis.RedisError as e:
        logger.warning("Redis unavailable during score-cache lookup ({}). Scoring fresh.", str(e)[:80])
        return CachedScore(hit=False)
    except Exception:
        return CachedScore(hit=False)


def set(hash_key: str, fraud_score: float, decision: str) -> None:
    """Store a fresh score under its feature hash, 1-min TTL. Best-effort."""
    try:
        _client().set(
            f"sc:{hash_key}",
            json.dumps({"fraud_score": fraud_score, "decision": decision, "cached_at_ms": int(time.time() * 1000)}),
            ex=CACHE_TTL_S,
        )
    except redis.RedisError as e:
        logger.warning("Redis unavailable during score-cache write ({}). Continuing without cache.", str(e)[:80])
    except Exception:
        pass

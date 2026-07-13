"""Core unit tests for VelocityFraud.

Covers:
    - RateLimiter: sliding-window request cap (groq_scorer)
    - Decision threshold constants: ALLOW / REVIEW / BLOCK (groq_scorer)
    - Row builders: _scored_row and _groq_row (sink)
    - Text anomaly: _extract_domain and empty-string short-circuit (text_anomaly)

All tests run without Kafka, PostgreSQL, or downloading the DistilBERT model.
Run: uv run pytest tests/ -v
"""
from __future__ import annotations

import time
from collections import deque

import pytest

# ---------------------------------------------------------------------------
# 1. RateLimiter
# ---------------------------------------------------------------------------
from velocityfraud.groq_scorer import RateLimiter


def test_rate_limiter_no_block_under_cap():
    """Slots under the cap are granted immediately (returned wait == 0.0)."""
    rl = RateLimiter(max_per_min=10)
    for _ in range(9):
        wait = rl.wait_slot()
        assert wait == 0.0


def test_rate_limiter_tracks_call_count():
    """Each wait_slot call appends one timestamp to the internal deque."""
    rl = RateLimiter(max_per_min=5)
    for _ in range(3):
        rl.wait_slot()
    assert len(rl.calls) == 3


def test_rate_limiter_evicts_stale_calls():
    """Timestamps older than 60 s are purged so they don't falsely block new slots."""
    rl = RateLimiter(max_per_min=3)
    old = time.monotonic() - 65.0          # 65 s ago — past the 60 s window
    rl.calls = deque([old, old, old])      # fill cap with stale entries
    wait = rl.wait_slot()
    assert wait == 0.0                     # evicted → no blocking
    assert len(rl.calls) == 1             # only the call we just made remains


# ---------------------------------------------------------------------------
# 2. Decision thresholds
# ---------------------------------------------------------------------------
from velocityfraud.groq_scorer import BLOCK_THRESH, REVIEW_THRESH


def _decide(score: float) -> str:
    """Mirror of the ALLOW / REVIEW / BLOCK logic shared by both scorers."""
    if score >= BLOCK_THRESH:
        return "BLOCK"
    if score >= REVIEW_THRESH:
        return "REVIEW"
    return "ALLOW"


def test_threshold_constants_values():
    """Thresholds must be in (0, 1) and BLOCK must be strictly above REVIEW."""
    assert 0.0 < REVIEW_THRESH < 1.0
    assert 0.0 < BLOCK_THRESH < 1.0
    assert BLOCK_THRESH > REVIEW_THRESH


def test_decision_allow():
    assert _decide(0.0) == "ALLOW"
    assert _decide(REVIEW_THRESH - 0.001) == "ALLOW"


def test_decision_review():
    mid = (REVIEW_THRESH + BLOCK_THRESH) / 2
    assert _decide(REVIEW_THRESH) == "REVIEW"
    assert _decide(mid) == "REVIEW"
    assert _decide(BLOCK_THRESH - 0.001) == "REVIEW"


def test_decision_block():
    assert _decide(BLOCK_THRESH) == "BLOCK"
    assert _decide(1.0) == "BLOCK"


# ---------------------------------------------------------------------------
# 3. Row builders
# ---------------------------------------------------------------------------
from velocityfraud.sink import _groq_row, _scored_row

_BASE_EVENT: dict = {
    "event_id": "evt-test-001",
    "event_timestamp_ms": 1_700_000_000_000,
    "customer_id": "cust-42",
    "card_token": "tok_abc123",
    "amount": 99.95,
    "currency": "USD",
    "amount_fx_normalised": 99.95,
    "merchant_id_hash": "mhash_xyz",
    "merchant_name": "W-MERCHANT-gmail.com",
    "mcc": "5411",
    "merchant_country": "840",
    "ip_address_hash": "iphash_111",
    "device_fingerprint_hash": "devhash_222",
    "geo_distance_km": 120.5,
    "source_label": "replayer",
    "schema_version": "v1",
    "fraud_score": 0.23,
    "decision": "ALLOW",
    "model_name": "xgboost_v1",
    "model_version": "v1",
    "scored_at_ms": 1_700_000_001_000,
    "scoring_latency_ms": 37,
    "feature_completeness": 1.0,
}


def test_scored_row_length():
    """_scored_row must produce a 26-element tuple matching INSERT_SCORED_SQL columns."""
    row = _scored_row(_BASE_EVENT)
    assert len(row) == 26


def test_scored_row_event_id_is_first():
    row = _scored_row(_BASE_EVENT)
    assert row[0] == "evt-test-001"


def test_scored_row_blocklist_defaults():
    """Events with no blocklist fields get safe defaults: False / NONE / empty string."""
    row = _scored_row(_BASE_EVENT)
    assert row[23] is False    # blocklist_hit
    assert row[24] == "NONE"   # blocklist_tier
    assert row[25] == ""       # blocklist_reason


def test_groq_row_length():
    """_groq_row produces a 24-element tuple — llm_reason replaces the 3 blocklist columns."""
    row = _groq_row(_BASE_EVENT)
    assert len(row) == 24


def test_groq_row_llm_reason_mapped():
    """The LLM reason is piggybacked on blocklist_reason and mapped to the last column."""
    event = {**_BASE_EVENT, "blocklist_reason": "High geo distance and suspicious merchant"}
    row = _groq_row(event)
    assert row[23] == "High geo distance and suspicious merchant"


# ---------------------------------------------------------------------------
# 4. Text anomaly — no model loading required
# ---------------------------------------------------------------------------
from velocityfraud.text_anomaly import _extract_domain, score_text


def test_extract_domain_standard_format():
    """'{ProductCD}-MERCHANT-{domain}' → domain part only."""
    assert _extract_domain("W-MERCHANT-gmail.com") == "gmail.com"
    assert _extract_domain("C-MERCHANT-anonymous.com") == "anonymous.com"
    assert _extract_domain("H-MERCHANT-paypal.com") == "paypal.com"


def test_extract_domain_passthrough_without_tag():
    """Strings without -MERCHANT- are returned unchanged."""
    assert _extract_domain("gmail.com") == "gmail.com"


def test_extract_domain_empty_string():
    assert _extract_domain("") == ""


def test_score_text_empty_short_circuits():
    """Empty string returns NORMAL immediately — no DistilBERT model is loaded."""
    result = score_text("")
    assert result.label == "NORMAL"
    assert result.score == 0.0
    assert result.perplexity == 1.0
    assert result.log_perplexity == 0.0

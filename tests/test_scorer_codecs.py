"""Unit tests for the scorer's pure Avro codec + decision helpers.

No Kafka needed: we encode a raw event with the TransactionEvent schema, decode
it back through the scorer, and check the decision policy. Round-trip fidelity
of the codec is what the live consumer relies on.
"""
from __future__ import annotations

import io

import fastavro
import pytest


def test_decide_policy():
    from velocityfraud.scorer import decide, REVIEW_THRESH, BLOCK_THRESH
    assert decide(0.0) == "ALLOW"
    assert decide(REVIEW_THRESH) == "REVIEW"
    assert decide((REVIEW_THRESH + BLOCK_THRESH) / 2) == "REVIEW"
    assert decide(BLOCK_THRESH) == "BLOCK"
    assert decide(1.0) == "BLOCK"


def test_raw_event_codec_roundtrip(sample_event):
    from velocityfraud.scorer import decode_event
    from velocityfraud.schema import get_schema

    schema = get_schema()
    buf = io.BytesIO()
    fastavro.schemaless_writer(buf, schema, sample_event)
    decoded = decode_event(buf.getvalue(), schema)
    assert decoded["event_id"] == sample_event["event_id"]
    assert decoded["amount"] == pytest.approx(sample_event["amount"])
    assert decoded["merchant_name"] == sample_event["merchant_name"]


def test_scored_event_encode(sample_event):
    from velocityfraud.scorer import encode_scored
    from velocityfraud.schema import get_scored_schema

    scored = {
        **sample_event,
        "fraud_score": 0.61,
        "decision": "REVIEW",
        "model_name": "xgboost_v1.pkl",
        "model_version": "v1",
        "scored_at_ms": 1_782_731_301_500,
        "scoring_latency_ms": 21,
        "feature_completeness": 0.34,
        "blocklist_hit": False,
        "blocklist_tier": "NONE",
        "blocklist_reason": "",
    }
    payload = encode_scored(scored, get_scored_schema())
    assert isinstance(payload, bytes) and len(payload) > 0
    # decodes back to the same decision
    decoded = fastavro.schemaless_reader(io.BytesIO(payload), get_scored_schema())
    assert decoded["decision"] == "REVIEW"
    assert decoded["fraud_score"] == pytest.approx(0.61)

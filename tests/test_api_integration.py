"""Integration tests for the FastAPI scoring service (Layer 3c) via TestClient.

TestClient drives the app through its lifespan, so the champion model is loaded
exactly as in production. Needs the model on disk + Redis (blocklist pre-filter).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client(model_ready):
    from fastapi.testclient import TestClient
    from velocityfraud.api import app
    with TestClient(app) as c:   # runs lifespan -> loads model
        yield c


def test_ping(client):
    r = client.get("/ping")
    assert r.status_code == 200
    assert r.json() == {"pong": True}


def test_health_reports_model_loaded(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["model_loaded"] is True
    assert body["champion"].endswith(".pkl")


def test_score_returns_decision(client, sample_event):
    r = client.post("/score", json=sample_event)
    assert r.status_code == 200
    body = r.json()
    assert body["decision"] in ("ALLOW", "REVIEW", "BLOCK")
    assert 0.0 <= body["fraud_score"] <= 1.0
    assert body["event_id"] == "it-0001"
    assert body["scoring_latency_ms"] >= 0.0
    assert 0.0 <= body["feature_completeness"] <= 1.0


def test_score_with_minimal_body(client):
    # All fields have defaults; an (almost) empty body must still score.
    r = client.post("/score", json={"event_id": "min-1", "amount": 10.0})
    assert r.status_code == 200
    assert r.json()["decision"] in ("ALLOW", "REVIEW", "BLOCK")


def test_score_high_amount_smoke(client, sample_event):
    ev = {**sample_event, "event_id": "hi-1", "amount": 9999.0,
          "amount_fx_normalised": 9999.0}
    r = client.post("/score", json=ev)
    assert r.status_code == 200

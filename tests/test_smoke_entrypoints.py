"""Smoke tests for each module's runnable self-test (main()/_demo()).

These are the entry points wired to `python -m velocityfraud.<module>`; asserting
they run to a clean exit verifies each module's happy path end-to-end (and covers
the demo/CLI code paths).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_predict_smoke(model_ready):
    from velocityfraud import predict
    assert predict.main() == 0


def test_db_smoke(pg_ready):
    from velocityfraud import db
    assert db.main() == 0


def test_live_features_demo(model_ready):
    from velocityfraud import live_features
    assert live_features._demo() == 0


def test_explainer_demo(model_ready):
    from velocityfraud import explainer
    assert explainer._demo() == 0


def test_narrator_demo(model_ready, monkeypatch):
    # Force template mode so the suite never depends on the Gemini network/key.
    from velocityfraud import narrator
    monkeypatch.setattr(narrator, "GEMINI_API_KEY", "")
    assert narrator._demo() == 0


def test_blocklist_demo(redis_ready):
    from velocityfraud import blocklist
    assert blocklist._demo() == 0


def test_chaos_probe(model_ready):
    from velocityfraud import chaos
    assert chaos.probe() == 0          # always produces a decision (fail-open)


def test_fraud_patterns_demo(model_ready, monkeypatch):
    from velocityfraud import fraud_patterns, narrator
    monkeypatch.setattr(narrator, "GEMINI_API_KEY", "")  # template mode, no network
    assert fraud_patterns.main() == 0  # 3 pattern explanations

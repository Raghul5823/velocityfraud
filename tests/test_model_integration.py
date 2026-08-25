"""Integration tests for the model/file-backed modules (no network needed):

    predict, live_features, explainer, narrator (template), schema, tokenizer.

These require the champion model + feature_meta.json on disk (model_ready
fixture skips if absent).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# schema.py — Avro schemas load from disk
# ---------------------------------------------------------------------------
def test_schemas_load():
    from velocityfraud.schema import (
        get_schema, get_scored_schema, get_enriched_schema,
    )
    raw = get_schema()
    scored = get_scored_schema()
    enriched = get_enriched_schema()
    # fastavro expands to the fully-qualified name (namespace.Name)
    assert raw["name"].endswith("TransactionEvent")
    assert scored["name"].endswith("TransactionScoredEvent")
    assert len(raw["fields"]) == 16
    # cached: same object back
    assert get_schema() is raw
    assert enriched["type"] == "record"


# ---------------------------------------------------------------------------
# tokenizer.py — deterministic PII hashing
# ---------------------------------------------------------------------------
def test_tokenize_deterministic_and_prefixed():
    from velocityfraud.tokenizer import tokenize
    a = tokenize("4111111111111111")
    b = tokenize("4111111111111111")
    assert a == b                      # deterministic
    assert len(a) == 16                # 16-hex-char prefix
    assert tokenize("4111111111111111") != tokenize("5222222222222222")


def test_tokenize_handles_none_and_numbers():
    from velocityfraud.tokenizer import tokenize
    assert tokenize(None) == "null"
    assert len(tokenize(12345)) == 16
    assert len(tokenize(99.95)) == 16


# ---------------------------------------------------------------------------
# predict.py — champion loading + inference
# ---------------------------------------------------------------------------
def test_champion_loads_and_feature_names(model_ready):
    from velocityfraud.predict import get_champion_filename, get_feature_names
    name = get_champion_filename()
    feats = get_feature_names()
    assert name.endswith(".pkl")
    assert len(feats) == 43
    assert "TransactionAmt" in feats


def test_predict_proba_and_label_on_test_slice(model_ready):
    import pandas as pd
    from pathlib import Path
    from velocityfraud.predict import predict_proba, predict_label, PROCESSED_DIR

    model, _ = model_ready
    x_path = Path(PROCESSED_DIR) / "X_test.parquet"
    if not x_path.exists():
        pytest.skip("X_test.parquet not present")
    X = pd.read_parquet(x_path).head(64)
    probs = predict_proba(model, X)
    labels = predict_label(model, X, threshold=0.5)
    assert len(probs) == len(X)
    assert ((probs >= 0.0) & (probs <= 1.0)).all()
    assert set(map(int, set(labels))).issubset({0, 1})


def test_predict_proba_rejects_missing_columns(model_ready):
    import pandas as pd
    from velocityfraud.predict import predict_proba
    model, _ = model_ready
    with pytest.raises(ValueError):
        predict_proba(model, pd.DataFrame([{"only_one_col": 1.0}]))


# ---------------------------------------------------------------------------
# live_features.py — event -> 43-feature vector
# ---------------------------------------------------------------------------
def test_featurize_event_shape_and_completeness(model_ready, sample_event):
    from velocityfraud.live_features import featurize_event
    X, completeness = featurize_event(sample_event)
    assert X.shape == (1, 43)
    assert 0.0 < completeness <= 1.0          # some real features filled
    # amount-derived feature should be present and non-sentinel
    assert X.iloc[0]["TransactionAmt"] == pytest.approx(245.40)


def test_featurize_batch_matches_single(model_ready, sample_event):
    from velocityfraud.live_features import featurize_batch
    X, comps = featurize_batch([sample_event, sample_event])
    assert X.shape == (2, 43)
    assert len(comps) == 2
    assert comps[0] == comps[1]


def test_featurize_empty_batch(model_ready):
    from velocityfraud.live_features import featurize_batch
    X, comps = featurize_batch([])
    assert X.shape[0] == 0
    assert comps == []


# ---------------------------------------------------------------------------
# explainer.py — SHAP attributions
# ---------------------------------------------------------------------------
def test_explainer_returns_sorted_contributions(model_ready, sample_event):
    from velocityfraud.live_features import featurize_event
    from velocityfraud.explainer import get_explainer, explain_event

    X, _ = featurize_event(sample_event)
    explainer = get_explainer()
    contribs = explain_event(explainer, X, top_n=5)
    assert len(contribs) == 5
    # sorted by |shap| descending
    mags = [abs(c.shap_value) for c in contribs]
    assert mags == sorted(mags, reverse=True)
    d = contribs[0].as_dict()
    assert {"feature_name", "feature_value", "shap_value"} <= d.keys()


# ---------------------------------------------------------------------------
# narrator.py — template mode (no API key needed)
# ---------------------------------------------------------------------------
def test_template_narrative(model_ready, sample_event):
    from velocityfraud.live_features import featurize_event
    from velocityfraud.explainer import get_explainer, explain_event
    from velocityfraud.narrator import generate_narrative

    X, completeness = featurize_event(sample_event)
    contribs = explain_event(get_explainer(), X, top_n=5)
    scored = {**sample_event, "fraud_score": 0.42, "decision": "REVIEW",
              "feature_completeness": completeness}
    text, mode = generate_narrative(scored, contribs, mode="template")
    assert mode == "TEMPLATE"
    assert "it-0001"[:8] in text or "245" in text
    assert len(text) > 30

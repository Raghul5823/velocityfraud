"""Inference helper — loads the champion fraud-detection model.

The champion model is whatever filename is listed in `models/CHAMPION.txt`.
Layer 3 (the fast-path scorer) imports `get_champion_model()` and calls
`predict_proba()` on incoming feature vectors — no hardcoded model names.

Usage as a library:
    from velocityfraud.predict import get_champion_model, predict_proba

    model = get_champion_model()
    probs = predict_proba(model, X)   # X: pd.DataFrame matching X_train schema

Usage as a smoke test (runs the full test set through the model):
    uv run python -m velocityfraud.predict
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from loguru import logger


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = PROJECT_ROOT / "models"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
CHAMPION_POINTER = MODELS_DIR / "CHAMPION.txt"
FEATURE_META = PROCESSED_DIR / "feature_meta.json"


# ---------------------------------------------------------------------------
# Champion model loading
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def get_champion_filename() -> str:
    """Read the current champion model filename from CHAMPION.txt."""
    if not CHAMPION_POINTER.exists():
        raise FileNotFoundError(
            f"Champion pointer not found at {CHAMPION_POINTER}. "
            "Run a training script first."
        )
    name = CHAMPION_POINTER.read_text().strip()
    if not name:
        raise ValueError(f"Champion pointer at {CHAMPION_POINTER} is empty.")
    return name


@lru_cache(maxsize=1)
def get_champion_model():
    """Load the champion model from disk (cached after first call)."""
    name = get_champion_filename()
    path = MODELS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Champion model file not found at {path}")
    logger.info("Loading champion model: {}", name)
    return joblib.load(path)


@lru_cache(maxsize=1)
def get_feature_names() -> list[str]:
    """Return the ordered list of feature column names the model expects."""
    if not FEATURE_META.exists():
        raise FileNotFoundError(
            f"Feature meta not found at {FEATURE_META}. "
            "Run: uv run python -m velocityfraud.training.features"
        )
    meta = json.loads(FEATURE_META.read_text())
    return meta["feature_names"]


# ---------------------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------------------
def predict_proba(model, X: pd.DataFrame) -> np.ndarray:
    """Return P(fraud) for each row of X. X must match the training schema."""
    expected = get_feature_names()
    missing = [c for c in expected if c not in X.columns]
    if missing:
        raise ValueError(f"X is missing required columns: {missing}")
    # Re-order to match training order — critical for tree models
    X_ordered = X[expected].astype("float32")
    return model.predict_proba(X_ordered)[:, 1]


def predict_label(model, X: pd.DataFrame, threshold: float = 0.5) -> np.ndarray:
    """Return 0/1 fraud labels at a given probability threshold."""
    return (predict_proba(model, X) >= threshold).astype("int8")


# ---------------------------------------------------------------------------
# Smoke test — load champion and score the test set
# ---------------------------------------------------------------------------
def main() -> int:
    logger.info("=" * 60)
    logger.info("CHAMPION MODEL SMOKE TEST")
    logger.info("=" * 60)

    name = get_champion_filename()
    logger.info("Champion: {}", name)
    model = get_champion_model()
    logger.info("Model class: {}", model.__class__.__name__)

    features = get_feature_names()
    logger.info("Expected features: {} columns", len(features))

    # Score the held-out test set as a self-check
    X_test_path = PROCESSED_DIR / "X_test.parquet"
    y_test_path = PROCESSED_DIR / "y_test.parquet"
    if not X_test_path.exists():
        logger.error("X_test.parquet not found. Run features.py first.")
        return 1

    X_test = pd.read_parquet(X_test_path)
    y_test = pd.read_parquet(y_test_path).iloc[:, 0]
    logger.info("Loaded test set: {} rows", len(X_test))

    probs = predict_proba(model, X_test)
    labels = (probs >= 0.5).astype("int8")

    actual_fraud = int(y_test.sum())
    flagged = int(labels.sum())
    caught = int(((labels == 1) & (y_test == 1)).sum())
    avg_prob = float(probs.mean())
    max_prob = float(probs.max())

    logger.info("-" * 60)
    logger.info("Smoke test results:")
    logger.info("  Test rows scored      : {}", len(X_test))
    logger.info("  Avg fraud probability : {:.4f}", avg_prob)
    logger.info("  Max fraud probability : {:.4f}", max_prob)
    logger.info("  Actual fraud in test  : {} ({:.2%})",
                actual_fraud, actual_fraud / len(X_test))
    logger.info("  Flagged by model      : {} ({:.2%})",
                flagged, flagged / len(X_test))
    logger.info("  True positives caught : {} ({:.2%} recall)",
                caught, caught / actual_fraud if actual_fraud else 0)
    logger.info("=" * 60)

    # Demo: score a single random transaction
    sample = X_test.sample(1, random_state=42)
    sample_prob = predict_proba(model, sample)[0]
    sample_label = "FRAUD" if sample_prob >= 0.5 else "LEGIT"
    logger.info("Single-row demo:")
    logger.info("  Row index: {}", sample.index[0])
    logger.info("  P(fraud)  = {:.4f}", sample_prob)
    logger.info("  Decision  = {}", sample_label)

    logger.success("Champion model smoke test PASSED — ready for Layer 3.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

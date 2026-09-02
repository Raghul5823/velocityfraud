"""Generate a tiny, schema-compatible stub model for the CI latency gate.

Closes proposal gap (docs/proposal_gap_remediation.md): §10.1's "every PR
runs a small synthetic load benchmark; a regression below the agreed p95
budget fails the build" cannot use the real champion model in CI — it's
git-ignored (models/*.pkl are never committed) specifically so the trained
artifact stays out of version control. A fresh CI checkout has no model file
at all.

This script is NOT trying to test model accuracy — it exists purely to give
the CI-run scoring API something real to load and run real inference
through, so the k6 latency gate measures genuine HTTP + FastAPI + XGBoost
serving latency (the thing that actually regresses if someone adds
accidental overhead to /score), not a mocked response.

Trained on random synthetic data matching the real 43-feature schema
(data/processed/feature_meta.json) — same shape, same dtypes, same
XGBoost class, deliberately tiny (a handful of trees) so it trains in under
a second and its inference latency is representative of the real champion
model's order of magnitude.

Run (CI only — see the safety guard below):
    uv run python scripts/make_ci_stub_model.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBClassifier

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FEATURE_META_PATH = PROJECT_ROOT / "data" / "processed" / "feature_meta.json"
MODELS_DIR = PROJECT_ROOT / "models"
STUB_MODEL_PATH = MODELS_DIR / "xgboost_v1.pkl"
CHAMPION_POINTER = MODELS_DIR / "CHAMPION.txt"


def main() -> int:
    # Hard safety guard: this script exists to fabricate a THROWAWAY model in
    # a fresh CI checkout that has no real model at all. It must never run
    # against a developer's machine and silently destroy the real, trained
    # champion model at the same path. GitHub Actions sets CI=true on every
    # runner automatically; --force is the explicit, deliberate override for
    # anyone who really means to run this outside CI.
    if os.getenv("CI", "").lower() != "true" and "--force" not in sys.argv:
        print("REFUSING TO RUN: this looks like a local machine, not a CI runner "
              "(the CI env var is not set to 'true'). This script OVERWRITES "
              f"{STUB_MODEL_PATH} — on a dev machine that file is the real, "
              "trained champion model. Pass --force only if you are certain "
              "you want to destroy that file (e.g., in a disposable clone).")
        return 1

    if not FEATURE_META_PATH.exists():
        print(f"ERROR: {FEATURE_META_PATH} not found — this file must be tracked in git.")
        return 1

    meta = json.loads(FEATURE_META_PATH.read_text())
    feature_names = meta["feature_names"]
    n_features = len(feature_names)

    rng = np.random.default_rng(seed=42)
    n_rows = 500
    X = pd.DataFrame(
        rng.standard_normal((n_rows, n_features)).astype("float32"),
        columns=feature_names,
    )
    y = rng.integers(0, 2, size=n_rows)

    model = XGBClassifier(
        n_estimators=5, max_depth=2, n_jobs=1,
        use_label_encoder=False, eval_metric="logloss",
    )
    model.fit(X, y)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, STUB_MODEL_PATH)

    if not CHAMPION_POINTER.exists() or CHAMPION_POINTER.read_text().strip() != "xgboost_v1.pkl":
        CHAMPION_POINTER.write_text("xgboost_v1.pkl")

    print(f"CI stub model written to {STUB_MODEL_PATH} ({n_features} features, {n_rows} synthetic rows).")
    print("This model is for LATENCY testing only — its predictions are meaningless "
          "(trained on random synthetic data). Never use it outside CI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

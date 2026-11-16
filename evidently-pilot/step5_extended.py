"""Step 5 - extended checks: Random Forest, out-of-time test, segments and time data.

Runs with the velocityfraud project's OWN Python, read-only on the project (same
rules as step1). No Kafka, Redis, Postgres, cloud server, Groq or Gemini. The two
XGBoost models trained here live only in memory and in this folder's out/ scores;
nothing is written to velocityfraud/models.

    A. Random Forest (models/random_forest_v1.pkl) on the same 118,108 test rows
    B. Out-of-time test: train on the first 80% of the timeline, test on the last
       20%, with frequency tables and the high-amount cut-off fitted on the
       training period only and early stopping on a validation slice (not the
       test set). Compared with the same recipe on the project's random split.
    C. Context for segment and score-over-time analysis of the test split
    D. Feature matrices for the first and last 30 days (drift over time)

Self-check: the feature rebuild, fitted on all rows the way training/features.py
does it, must reproduce data/processed/X_test.parquet exactly.

Usage (from this folder):
    ..\\.venv\\Scripts\\python.exe step5_extended.py
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # leave no __pycache__ behind in the project

import json
import subprocess
import time

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

from step1_score import OUT, PROCESSED, PROJECT, RAW_CSV, reproduce_test_split
from velocityfraud.predict import get_champion_model, get_feature_names, predict_proba  # noqa: E402
from velocityfraud.training import features as F  # noqa: E402

CAT_COLS = ["ProductCD", "card4", "card6", "P_emaildomain", "R_emaildomain"] + [f"M{i}" for i in range(1, 10)]
DAY_S = 86_400


def git_state() -> str:
    r = subprocess.run(["git", "-C", str(PROJECT), "status", "--porcelain"], capture_output=True, text=True)
    h = subprocess.run(["git", "-C", str(PROJECT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return f"HEAD {h.stdout.strip()} | changes: {r.stdout.strip() or 'none'}"


def build_features(raw: pd.DataFrame, fit_mask: np.ndarray, names: list[str]) -> pd.DataFrame:
    """training/features.py, with the data-dependent parts fitted on fit_mask rows only."""
    df = raw.copy()
    df = F._add_time_features(df)
    df = F._add_amount_features(df)
    df = F._add_email_features(df)
    amt = df["TransactionAmt"].astype("float32")
    df["is_high_amount"] = (amt > amt[fit_mask].quantile(0.95)).astype("int8")
    for col in CAT_COLS:
        freq = df.loc[fit_mask, col].value_counts(dropna=False, normalize=True)
        df[f"{col}_freq"] = df[col].map(freq).astype("float32")
    return df[names].fillna(-999).astype("float32")


def train_xgb(X_tr, y_tr, X_val, y_val) -> xgb.XGBClassifier:
    """The project's train_xgb.py recipe; early stopping on a validation slice."""
    spw = float((y_tr == 0).sum() / (y_tr == 1).sum())
    m = xgb.XGBClassifier(
        n_estimators=400, max_depth=8, learning_rate=0.05, scale_pos_weight=spw,
        objective="binary:logistic", eval_metric="auc", early_stopping_rounds=20,
        random_state=42, n_jobs=-1, tree_method="hist", verbosity=0)
    m.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], verbose=False)
    return m


def main() -> int:
    git_before = git_state()
    print("Project before:", git_before)
    names = get_feature_names()
    raw = pd.read_csv(RAW_CSV, usecols=F.RAW_COLS)
    y = raw["isFraud"].astype("int8").to_numpy()
    test_idx = reproduce_test_split(raw)
    s1 = pd.read_parquet(OUT / "scores_n118108.parquet")
    X_test = pd.read_parquet(PROCESSED / "X_test.parquet")

    # --- self-check: rebuild reproduces the project's features exactly
    X_all = build_features(raw, np.ones(len(raw), dtype=bool), names)
    if not np.array_equal(X_all.iloc[test_idx].to_numpy(), X_test[names].to_numpy()):
        raise SystemExit("Self-check FAILED - feature rebuild differs from X_test.parquet")
    print("Self-check passed: feature rebuild == project X_test.parquet (exact)")

    # --- A. Random Forest on the same rows
    t0 = time.perf_counter()
    rf = joblib.load(PROJECT / "models" / "random_forest_v1.pkl")
    rf_score = rf.predict_proba(X_test[names])[:, 1]
    del rf
    print(f"A. Random Forest scored in {time.perf_counter() - t0:.0f} s: ROC-AUC {roc_auc_score(y[test_idx], rf_score):.4f}")

    # --- B. Out-of-time vs random split, same recipe, clean early stopping
    dt = raw["TransactionDT"].to_numpy()
    cut_test, cut_val = np.quantile(dt, 0.80), np.quantile(dt, 0.72)
    oot = {"train": dt <= cut_val, "val": (dt > cut_val) & (dt <= cut_test), "test": dt > cut_test}
    X_oot = build_features(raw, dt <= cut_test, names)  # fitted on the training period only
    t0 = time.perf_counter()
    m_oot = train_xgb(X_oot[oot["train"]], y[oot["train"]], X_oot[oot["val"]], y[oot["val"]])
    s_oot = m_oot.predict_proba(X_oot[oot["test"]])[:, 1]
    print(f"B1. Out-of-time model trained in {time.perf_counter() - t0:.0f} s "
          f"(best iteration {m_oot.best_iteration}): ROC-AUC {roc_auc_score(y[oot['test']], s_oot):.4f}")

    train_idx = np.setdiff1d(np.arange(len(raw)), test_idx)
    tr_idx, val_idx = train_test_split(train_idx, test_size=0.10, random_state=42, stratify=y[train_idx])
    fit = np.zeros(len(raw), dtype=bool)
    fit[train_idx] = True
    X_rnd = build_features(raw, fit, names)
    t0 = time.perf_counter()
    m_rnd = train_xgb(X_rnd.iloc[tr_idx], y[tr_idx], X_rnd.iloc[val_idx], y[val_idx])
    s_rnd = m_rnd.predict_proba(X_rnd.iloc[test_idx])[:, 1]
    print(f"B2. Random-split model (same clean recipe) trained in {time.perf_counter() - t0:.0f} s "
          f"(best iteration {m_rnd.best_iteration}): ROC-AUC {roc_auc_score(y[test_idx], s_rnd):.4f}")

    first_day, last_day = int(dt.min() // DAY_S), int(dt.max() // DAY_S)
    pd.DataFrame({"label": y[oot["test"]], "score": s_oot, "amount": raw["TransactionAmt"].to_numpy()[oot["test"]]}
                 ).to_parquet(OUT / "ext_oot_scores.parquet", index=False)
    pd.DataFrame({"label": y[test_idx], "score": s_rnd, "amount": raw["TransactionAmt"].to_numpy()[test_idx]}
                 ).to_parquet(OUT / "ext_random_clean_scores.parquet", index=False)

    # --- C. Test-split context for segments and score over time
    t = raw.iloc[test_idx].reset_index(drop=True)
    if not np.array_equal(t["TransactionID"].to_numpy(), s1["TransactionID"].to_numpy()):
        raise SystemExit("Row order differs from step1 - stopping")
    ctx = pd.DataFrame({
        "TransactionID": t["TransactionID"], "label": y[test_idx], "amount": t["TransactionAmt"].astype("float64"),
        "day": (t["TransactionDT"] // DAY_S).astype("int32"), "ProductCD": t["ProductCD"],
        "hour": X_test["hour_of_day"].astype("int16").to_numpy(), "card4": t["card4"].fillna("missing"),
        "card6": t["card6"].fillna("missing"), "P_emaildomain": t["P_emaildomain"].fillna("missing"),
        "xgboost": s1["offline_score"], "random_forest": rf_score, "live_today": s1["live_score"],
    })
    ctx.to_parquet(OUT / "ext_test_context.parquet", index=False)

    # --- D. First and last 30 days of the full feature matrix, plus the champion's scores
    model = get_champion_model()
    early, late = dt < (first_day + 30) * DAY_S, dt >= (last_day - 29) * DAY_S
    for tag, mask in (("first30", early), ("last30", late)):
        Xp = X_all[mask].reset_index(drop=True)
        Xp["champion_score"] = predict_proba(model, X_all[mask][names])
        Xp.to_parquet(OUT / f"ext_features_{tag}.parquet", index=False)

    git_after = git_state()
    print("Project after: ", git_after)
    if git_after != git_before:
        raise SystemExit("The project changed during the run - stopping.")
    (OUT / "step5_extended.json").write_text(json.dumps({
        "self_check_feature_rebuild_equals_X_test": True,
        "random_forest_roc_auc": roc_auc_score(y[test_idx], rf_score),
        "out_of_time": {
            "train_rows": int(oot["train"].sum()), "val_rows": int(oot["val"].sum()), "test_rows": int(oot["test"].sum()),
            "test_frauds": int(y[oot["test"]].sum()), "test_days": f"day {int(cut_test // DAY_S)} to {last_day}",
            "best_iteration": int(m_oot.best_iteration), "roc_auc": roc_auc_score(y[oot["test"]], s_oot)},
        "random_split_clean": {"best_iteration": int(m_rnd.best_iteration), "roc_auc": roc_auc_score(y[test_idx], s_rnd)},
        "drift_windows": {"first30_rows": int(early.sum()), "last30_rows": int(late.sum()),
                          "first_day": first_day, "last_day": last_day},
        "project_git": {"before": git_before, "after": git_after},
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

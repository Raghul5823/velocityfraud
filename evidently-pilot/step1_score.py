"""Step 1 — score the same transactions two ways. Read-only on the project.

Runs with the velocityfraud project's OWN Python (no installs, no writes), so
the model file, xgboost/sklearn versions and live-feature code are exactly what
the pipeline runs. Nothing talks to Kafka, Redis, Postgres or the cloud server.

  A. Replica check (proves this laptop replica == the real live pipeline):
     re-score the 4,692 events the live pipeline already scored
     (data/exports/scored_events_bronze.csv) and compare with the scores it
     recorded at the time. Also attaches the true IEEE-CIS label to each one.

  B. Same-transaction comparison on the held-out test split (never trained on):
       offline score = model on the full 43 training features (X_test.parquet)
       live score    = model on what the live pipeline builds from the Avro
                       event (replayer.row_to_event -> live_features.featurize_event)

Usage (from this folder):
    ..\\.venv\\Scripts\\python.exe step1_score.py --n 500   # pilot
    ..\\.venv\\Scripts\\python.exe step1_score.py --n all   # full
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # leave no __pycache__ behind in the project

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent  # the repo root: this pilot lives in velocityfraud/evidently-pilot
sys.path.insert(0, str(PROJECT / "src"))

from velocityfraud.live_features import featurize_event  # noqa: E402
from velocityfraud.predict import (  # noqa: E402
    get_champion_filename, get_champion_model, get_feature_names, predict_proba,
)
from velocityfraud.replayer import REFERENCE_EPOCH_MS, row_to_event  # noqa: E402
from velocityfraud.training.features import RANDOM_STATE, TEST_SIZE  # noqa: E402

RAW_CSV = PROJECT / "data" / "raw" / "train_transaction.csv"
BRONZE_CSV = PROJECT / "data" / "exports" / "scored_events_bronze.csv"
PROCESSED = PROJECT / "data" / "processed"
OUT = HERE / "out"

# Columns the replayer reads from the raw CSV, plus the label.
REPLAYER_COLS = [
    "TransactionID", "TransactionDT", "TransactionAmt",
    "ProductCD", "card1", "card2", "card3", "card4", "card5", "card6",
    "addr1", "addr2", "dist1", "dist2",
    "P_emaildomain", "R_emaildomain",
]
EVENT_FIELDS = ["amount", "event_timestamp_ms", "mcc", "merchant_country", "merchant_name"]
SAMPLE_SEED = 7


def live_features_for(events: list[dict]) -> tuple[pd.DataFrame, list[float]]:
    """Run the real featurize_event on each event; return (X, completeness)."""
    rows, comps = [], []
    for ev in events:
        X, c = featurize_event(ev)
        rows.append(X.iloc[0].to_numpy())
        comps.append(c)
    X = pd.DataFrame(np.vstack(rows), columns=get_feature_names()).astype("float32")
    return X, comps


def replica_check(model, raw: pd.DataFrame) -> dict:
    """A. Re-score the real live-scored events and compare with recorded scores."""
    b = pd.read_csv(BRONZE_CSV, dtype={"customer_id": str, "mcc": str, "merchant_country": str})
    events = b[EVENT_FIELDS].to_dict("records")
    X_live, comps = live_features_for(events)
    replica = predict_proba(model, X_live)

    diff = np.abs(replica - b["fraud_score"].to_numpy())
    comp_match = float(np.mean(np.isclose(comps, b["feature_completeness"], atol=1e-4)))

    # Attach the true label (join is exact: timestamp + card1 + amount).
    keys = raw[["TransactionDT", "card1", "TransactionAmt", "isFraud", "ProductCD"]].copy()
    keys["event_timestamp_ms"] = REFERENCE_EPOCH_MS + keys["TransactionDT"].astype("int64") * 1000
    keys["customer_id"] = keys["card1"].fillna(-1).astype(int).astype(str)
    keys["amt"] = keys["TransactionAmt"].round(2)
    b["amt"] = b["amount"].round(2)
    m = b.merge(keys[["event_timestamp_ms", "customer_id", "amt", "isFraud", "ProductCD"]],
                on=["event_timestamp_ms", "customer_id", "amt"], how="left")
    if len(m) != len(b):
        raise SystemExit(f"Label join produced duplicates: {len(m)} rows for {len(b)} events")

    out = pd.DataFrame({
        "label": m["isFraud"].astype("Int8"),
        "score": b["fraud_score"].astype("float64"),     # what the server recorded
        "replica_score": replica.astype("float64"),      # what this laptop computes
        "decision": b["decision"],
        "amount": b["amount"].astype("float64"),
        "ProductCD": m["ProductCD"],
        "feature_completeness": b["feature_completeness"],
    })
    out.to_parquet(OUT / "real_live_events_labeled.parquet", index=False)

    result = {
        "events": int(len(b)),
        "labels_matched": int(out["label"].notna().sum()),
        "score_max_abs_diff": float(diff.max()),
        "score_mean_abs_diff": float(diff.mean()),
        "share_scores_within_1e-6": float(np.mean(diff <= 1e-6)),
        "share_completeness_identical": comp_match,
    }
    return result


def reproduce_test_split(raw: pd.DataFrame) -> np.ndarray:
    """Recover which raw rows features.py put in the test split, then verify it."""
    y = raw["isFraud"].astype("int8")
    _, test_idx = train_test_split(
        np.arange(len(raw)), test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y,
    )
    X_test = pd.read_parquet(PROCESSED / "X_test.parquet", columns=["TransactionAmt"])
    y_test = pd.read_parquet(PROCESSED / "y_test.parquet").iloc[:, 0]
    amt_ok = np.array_equal(
        raw["TransactionAmt"].to_numpy("float32")[test_idx], X_test["TransactionAmt"].to_numpy("float32"))
    y_ok = np.array_equal(y.to_numpy()[test_idx], y_test.to_numpy())
    if not (amt_ok and y_ok):
        raise SystemExit("Could not reproduce the training test split exactly — stopping.")
    return test_idx


def compare_on_test(model, raw: pd.DataFrame, n: int | None) -> dict:
    """B. Offline vs live score on the same held-out transactions."""
    test_idx = reproduce_test_split(raw)
    X_test = pd.read_parquet(PROCESSED / "X_test.parquet")

    positions = np.arange(len(test_idx))
    if n is not None and n < len(positions):
        # Stratified sample so the pilot keeps the real 3.5% fraud rate.
        y_pos = raw["isFraud"].to_numpy()[test_idx]
        positions, _ = train_test_split(
            positions, train_size=n, random_state=SAMPLE_SEED, stratify=y_pos)
        positions = np.sort(positions)

    raw_rows = raw.iloc[test_idx[positions]]
    events = [row_to_event(row) for _, row in raw_rows[REPLAYER_COLS].iterrows()]

    t0 = time.perf_counter()
    X_live, comps = live_features_for(events)
    featurize_s = time.perf_counter() - t0

    X_off = X_test.iloc[positions].reset_index(drop=True)
    tag = f"n{len(positions)}"
    scores = pd.DataFrame({
        "TransactionID": raw_rows["TransactionID"].to_numpy(),
        "label": raw_rows["isFraud"].astype("int8").to_numpy(),
        "offline_score": predict_proba(model, X_off).astype("float64"),
        "live_score": predict_proba(model, X_live).astype("float64"),
        "live_completeness": comps,
        "amount": raw_rows["TransactionAmt"].astype("float64").to_numpy(),
        "ProductCD": raw_rows["ProductCD"].to_numpy(),
    })
    scores.to_parquet(OUT / f"scores_{tag}.parquet", index=False)
    X_off.to_parquet(OUT / f"features_offline_{tag}.parquet", index=False)
    X_live.to_parquet(OUT / f"features_live_{tag}.parquet", index=False)

    return {
        "tag": tag,
        "rows": int(len(scores)),
        "frauds": int(scores["label"].sum()),
        "test_split_reproduced": True,
        "featurize_seconds": round(featurize_s, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", default="500", help="rows of the test split to use, or 'all'")
    args = ap.parse_args()
    n = None if args.n == "all" else int(args.n)

    OUT.mkdir(exist_ok=True)
    model = get_champion_model()
    print(f"Champion model: {get_champion_filename()}")

    raw = pd.read_csv(RAW_CSV, usecols=REPLAYER_COLS + ["isFraud"])
    print(f"Raw IEEE-CIS rows: {len(raw):,}")

    rc = replica_check(model, raw)
    print("A. Replica check:", json.dumps(rc, indent=2))
    cmp_ = compare_on_test(model, raw, n)
    print("B. Test-split comparison:", json.dumps(cmp_, indent=2))

    (OUT / f"step1_{cmp_['tag']}.json").write_text(json.dumps(
        {"champion": get_champion_filename(), "replica_check": rc, "test_split": cmp_}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

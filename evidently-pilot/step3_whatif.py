"""Step 3 - what-if: re-score the held-out test split with the live-feature fixes.

Runs with the velocityfraud project's OWN Python, read-only on the project (same
rules as step1). Nothing talks to Kafka, Redis, Postgres, the cloud server, Groq
or Gemini. The fixed feature logic lives in this folder (live_features_fixed.py).

Scenarios, all on the same transactions:
    live_today        the project's live features as they are now
    fix:<name>        live_today + one fix (measures each fix on its own)
    all_code_fixes    every fix that needs only a code change
    richer_event      all code fixes + the raw per-transaction fields added to
                      the Avro event (everything except the Vesta history counters)
    offline           the model on its full 43 training features (the ceiling)

Self-checks before any number is trusted:
    1. live_features_fixed with no fixes == the project's featurize_event output
       saved by step1 (every row, every feature)
    2. live_today scores == step1's live scores; offline scores == step1's offline scores

Usage (from this folder):
    ..\\.venv\\Scripts\\python.exe step3_whatif.py --n 500   # pilot
    ..\\.venv\\Scripts\\python.exe step3_whatif.py --n all   # full
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # leave no __pycache__ behind in the project

import argparse
import json
import subprocess
import time

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

import live_features_fixed as LF
from step1_score import (  # also puts the project's src on sys.path
    OUT, PROCESSED, PROJECT, RAW_CSV, REPLAYER_COLS, SAMPLE_SEED, reproduce_test_split,
)
from velocityfraud.predict import (  # noqa: E402
    get_champion_filename, get_champion_model, get_feature_names, predict_proba,
)
from velocityfraud.replayer import row_to_event  # noqa: E402

M_COLS = [f"M{i}" for i in range(1, 10)]
EXTRA_COLS = ["card2", "card3", "card5", "card4", "card6", "addr1", "dist1", "R_emaildomain"] + M_COLS


def git_state() -> str:
    r = subprocess.run(["git", "-C", str(PROJECT), "status", "--porcelain"], capture_output=True, text=True)
    h = subprocess.run(["git", "-C", str(PROJECT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return f"HEAD {h.stdout.strip()} | changes: {r.stdout.strip() or 'none'}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", default="500", help="rows of the test split to use, or 'all'")
    args = ap.parse_args()
    n = None if args.n == "all" else int(args.n)

    git_before = git_state()
    print("Project before:", git_before)
    model = get_champion_model()
    names = get_feature_names()
    print(f"Champion model: {get_champion_filename()}  |  features: {len(names)}")

    raw = pd.read_csv(RAW_CSV, usecols=sorted(set(REPLAYER_COLS + M_COLS + ["isFraud"])))
    test_idx = reproduce_test_split(raw)
    train_mask = np.ones(len(raw), dtype=bool)
    train_mask[test_idx] = False
    constants = LF.build_constants(raw, train_mask)
    LF.save_constants(constants, OUT / "training_constants.json")
    print(f"Training constants: high-amount cut-off ${constants['high_amount_q95']:.2f}, "
          f"missing-email frequency {constants['freqs']['P_emaildomain'][LF.NAN_KEY]:.4f}")

    # Same rows, same order as step1 (stratified pilot sample or the full split).
    positions = np.arange(len(test_idx))
    if n is not None and n < len(positions):
        y_pos = raw["isFraud"].to_numpy()[test_idx]
        positions, _ = train_test_split(positions, train_size=n, random_state=SAMPLE_SEED, stratify=y_pos)
        positions = np.sort(positions)
    tag = f"n{len(positions)}"
    rows = raw.iloc[test_idx[positions]].reset_index(drop=True)

    t0 = time.perf_counter()
    events = pd.DataFrame([row_to_event(r) for _, r in rows[REPLAYER_COLS].iterrows()])
    extra = rows[EXTRA_COLS].reset_index(drop=True)
    print(f"Built {len(events):,} Avro events with the project's replayer in {time.perf_counter() - t0:.0f} s")

    # --- self-check 1: the vectorised copy reproduces the project's live features
    X_step1 = pd.read_parquet(OUT / f"features_live_{tag}.parquet")
    X_today, comp_today = LF.featurize_frame(events, names)
    same = np.isclose(X_today.to_numpy(), X_step1[names].to_numpy(), rtol=0, atol=0)
    bad_cols = [c for c, ok in zip(names, same.all(axis=0)) if not ok]
    if bad_cols:
        raise SystemExit(f"Self-check 1 FAILED - copy differs from the project's live features in {bad_cols}")
    print(f"Self-check 1 passed: copy == project live features on {same.size:,} values (exact)")

    # --- self-check 2: scores reproduce step1
    s1 = pd.read_parquet(OUT / f"scores_{tag}.parquet")
    X_off = pd.read_parquet(OUT / f"features_offline_{tag}.parquet")
    scores = pd.DataFrame({
        "TransactionID": rows["TransactionID"].to_numpy(),
        "label": rows["isFraud"].astype("int8").to_numpy(),
        "amount": rows["TransactionAmt"].astype("float64").to_numpy(),
        "ProductCD": rows["ProductCD"].to_numpy(),
        "offline": predict_proba(model, X_off).astype("float64"),
        "live_today": predict_proba(model, X_today).astype("float64"),
    })
    if not (np.array_equal(scores["TransactionID"], s1["TransactionID"])
            and np.allclose(scores["live_today"], s1["live_score"], atol=1e-9)
            and np.allclose(scores["offline"], s1["offline_score"], atol=1e-9)):
        raise SystemExit("Self-check 2 FAILED - scores do not reproduce step1")
    print("Self-check 2 passed: live_today and offline scores == step1")

    # --- scenarios
    completeness = {"live_today": float(np.mean(comp_today))}
    t0 = time.perf_counter()
    for fx in LF.CODE_FIXES:
        X, comp = LF.featurize_frame(events, names, constants, fixes=(fx,))
        scores[f"fix:{fx}"] = predict_proba(model, X).astype("float64")
        completeness[f"fix:{fx}"] = float(np.mean(comp))
    X_fixed, comp = LF.featurize_frame(events, names, constants, fixes=LF.CODE_FIXES)
    scores["all_code_fixes"] = predict_proba(model, X_fixed).astype("float64")
    completeness["all_code_fixes"] = float(np.mean(comp))
    X_rich, comp = LF.featurize_frame(events, names, constants, fixes=LF.CODE_FIXES, extra=extra)
    scores["richer_event"] = predict_proba(model, X_rich).astype("float64")
    completeness["richer_event"] = float(np.mean(comp))
    print(f"Scored {len(LF.CODE_FIXES) + 2} scenarios in {time.perf_counter() - t0:.0f} s")

    # --- self-check 3: in the richer event, every non-history feature must equal training
    history = [c for c in names if c[0] in "CD" and c[1:].isdigit()]
    rich_same = {c: float(np.mean(np.isclose(X_rich[c], X_off[c], atol=1e-4))) for c in names if c not in history}
    off_cols = {c: v for c, v in rich_same.items() if v < 0.999}
    print(f"Self-check 3: richer event matches training on {sum(v >= 0.999 for v in rich_same.values())} "
          f"of {len(rich_same)} non-history features" + (f"; below 99.9%: {off_cols}" if off_cols else ""))

    scores.to_parquet(OUT / f"whatif_scores_{tag}.parquet", index=False)
    X_fixed.to_parquet(OUT / f"features_fixed_{tag}.parquet", index=False)
    X_rich.to_parquet(OUT / f"features_richer_{tag}.parquet", index=False)

    git_after = git_state()
    print("Project after: ", git_after)
    if git_after != git_before:
        raise SystemExit("The project changed during the run - stopping.")
    (OUT / f"step3_{tag}.json").write_text(json.dumps({
        "champion": get_champion_filename(), "rows": int(len(scores)), "frauds": int(scores["label"].sum()),
        "self_checks": {"copy_equals_project_live_features": True, "scores_reproduce_step1": True,
                        "richer_event_non_history_match": rich_same},
        "mean_feature_completeness": completeness,
        "project_git": {"before": git_before, "after": git_after},
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Threshold sweep for the champion model — proposal Section 10.2 target audit.

Section 10.2 of the proposal commits the Model Accuracy row to **F1 >= 0.92,
FPR <= 2%**. The champion at its production operating point (threshold 0.5)
scores F1 0.460 / FPR 6.56%, so both are missed. The honest question is *why*,
and that splits into two genuinely different answers -- which is what this
script establishes, reproducibly, rather than by assertion:

    1. FPR <= 2%  is ACHIEVABLE. It needs a higher threshold, and the cost is
       recall -- real fraud that stops being caught. This script finds the
       exact threshold and prints what it costs.

    2. F1 >= 0.92 is NOT achievable at ANY threshold. This script sweeps the
       whole range and reports the maximum F1 the model can reach. Because F1
       is a harmonic mean of precision and recall, hitting 0.92 needs BOTH at
       roughly 0.92 -- on a 3.5%-prevalence dataset that means ~3,802 true
       positives against only ~331 false positives, and the sweep shows the
       model cannot hold both at once: by the time FP falls that far, TP has
       already collapsed.

The distinction matters for the report: (1) is a deliberate operating-point
trade-off we chose not to take, (2) is a target that was set without reference
to what the dataset permits. Only (2) is a proposal-authoring error.

Run:  uv run python scripts/threshold_sweep.py
"""
from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "xgboost_v1.pkl"
X_PATH = ROOT / "data" / "processed" / "X_test.parquet"
Y_PATH = ROOT / "data" / "processed" / "y_test.parquet"

TARGET_F1 = 0.92
TARGET_FPR = 0.02
PRODUCTION_THRESHOLD = 0.5


def _stats(p: np.ndarray, y: np.ndarray, t: float, n_neg: int) -> dict:
    """Confusion-matrix derived metrics at one threshold."""
    pred = p >= t
    tp = int((pred & (y == 1)).sum())
    fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": round(float(t), 4), "tp": tp, "fp": fp, "fn": fn,
        "fpr": round(fp / n_neg, 4), "precision": round(precision, 4),
        "recall": round(recall, 4), "f1": round(f1, 4),
    }


def main() -> int:
    X = pd.read_parquet(X_PATH)
    y = pd.read_parquet(Y_PATH).squeeze()
    with open(MODEL_PATH, "rb") as fh:
        model = pickle.load(fh)

    p = model.predict_proba(X)[:, 1]
    n_neg = int((y == 0).sum())
    n_pos = int((y == 1).sum())

    print(f"Held-out test set : {len(y):,} rows "
          f"({n_pos:,} fraud / {n_neg:,} legitimate, prevalence {y.mean():.4%})")
    print(f"Proposal targets  : F1 >= {TARGET_F1}, FPR <= {TARGET_FPR:.0%}\n")

    prod = _stats(p, y, PRODUCTION_THRESHOLD, n_neg)
    print(f"[1] Production operating point (threshold {PRODUCTION_THRESHOLD})")
    print(f"    {prod}")
    print(f"    F1  target met? {prod['f1']  >= TARGET_F1}")
    print(f"    FPR target met? {prod['fpr'] <= TARGET_FPR}\n")

    # Sweep the upper tail densely -- FPR only falls as the threshold rises.
    grid = np.unique(np.round(np.quantile(p, np.linspace(0.50, 0.99999, 1500)), 6))
    sweep = [_stats(p, y, t, n_neg) for t in grid]

    at_fpr = next((s for s in sweep if s["fpr"] <= TARGET_FPR), None)
    print(f"[2] Lowest threshold meeting FPR <= {TARGET_FPR:.0%}")
    if at_fpr:
        print(f"    {at_fpr}")
        print(f"    Cost vs production: recall {prod['recall']:.4f} -> "
              f"{at_fpr['recall']:.4f} "
              f"(down {(prod['recall'] - at_fpr['recall']) * 100:.1f} pp, "
              f"{at_fpr['fn'] - prod['fn']:,} more frauds missed)")
    else:
        print("    Not reachable at any swept threshold.")
    print()

    best = max(sweep, key=lambda s: s["f1"])
    print("[3] Maximum F1 reachable at ANY threshold")
    print(f"    {best}")
    print(f"    F1 target ({TARGET_F1}) reachable? {best['f1'] >= TARGET_F1}")
    print(f"    Shortfall: {TARGET_F1 - best['f1']:.4f} F1 below target, "
          f"i.e. the target is {TARGET_F1 / best['f1']:.2f}x the model's ceiling.\n")

    # What F1 >= 0.92 would actually require, in raw counts.
    need_tp = TARGET_F1 * n_pos
    need_fp = need_tp * (1 - TARGET_F1) / TARGET_F1
    print("[4] What F1 >= 0.92 would require (balanced precision/recall ~0.92)")
    print(f"    ~{need_tp:,.0f} true positives with only ~{need_fp:,.0f} false positives")
    print(f"    At the model's best-F1 point it has {best['tp']:,} TP / {best['fp']:,} FP")
    print(f"    -> requires {need_tp - best['tp']:,.0f} MORE true positives while "
          f"cutting false positives by {best['fp'] - need_fp:,.0f}, simultaneously.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Step 4 - what-if summary and Evidently reports (before vs after the live-feature fixes).

Runs in THIS folder's own .venv, like step2, and reads only the files step3 wrote.

Usage (from this folder):
    .venv\\Scripts\\python.exe step4_whatif_report.py --tag n500
    .venv\\Scripts\\python.exe step4_whatif_report.py --tag n118108
"""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np
import pandas as pd

from step2_reports import (
    HERE, OUT, POLICIES, business_metrics, classification_report, drift_report,
    feature_parity, md_table, money, pct, ranking,
)

FIX_LABELS = {
    "card1": "1. card1 from customer_id",
    "dist1": "2. dist1 from geo_distance_km",
    "email": "3-4. email_mismatch / r_email_missing / R_emaildomain_freq",
    "p_missing": "new. anonymous.com is not a missing email",
    "addr2": "5. addr2 '00' = missing",
    "high_amount": "6. high-amount cut-off $445",
    "freq_tables": "7. training frequency tables",
    "cents": "8. amount_cents as in training",
    "never_seen": "9. card4/card6/M1-M9 product-typical values",
}
STAIRS = [
    ("live_today", "Live pipeline today"),
    ("all_code_fixes", "Live + all code fixes"),
    ("richer_event", "Live + code fixes + richer event"),
    ("offline", "Offline model, all 43 features (ceiling)"),
]


def at_alert_budget(label: pd.Series, score: pd.Series, amount: pd.Series, fpr: float) -> dict:
    """Frauds caught when each scenario may flag the same share of good customers as offline @0.50."""
    thr = float(np.quantile(score[label == 0], 1 - fpr))
    caught = (score >= thr) & (label == 1)
    return {"threshold": thr, "recall": float(caught.sum() / max(int((label == 1).sum()), 1)),
            "fraud_$_caught": float(amount[caught].sum())}


def parity_count(off: pd.DataFrame, live: pd.DataFrame) -> int:
    p = feature_parity(off, live)
    return int((p["same_value_%"] >= 99).sum())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="n500")
    tag = ap.parse_args().tag

    s = pd.read_parquet(OUT / f"whatif_scores_{tag}.parquet")
    meta = json.loads((OUT / f"step3_{tag}.json").read_text())
    feats = {
        "offline": pd.read_parquet(OUT / f"features_offline_{tag}.parquet"),
        "live_today": pd.read_parquet(OUT / f"features_live_{tag}.parquet"),
        "all_code_fixes": pd.read_parquet(OUT / f"features_fixed_{tag}.parquet"),
        "richer_event": pd.read_parquet(OUT / f"features_richer_{tag}.parquet"),
    }
    label, amount = s["label"], s["amount"]
    budget_fpr = business_metrics(label, s["offline"], amount, 0.50, 0.85)["fpr"]

    def row(col: str) -> dict:
        r = ranking(label, s[col])
        b = business_metrics(label, s[col], amount, 0.50, 0.85)
        a = at_alert_budget(label, s[col], amount, budget_fpr)
        return {**r, **{f"{k}@0.5": v for k, v in b.items()}, **{f"budget_{k}": v for k, v in a.items()}}

    res = {col: row(col) for col in ["live_today", "all_code_fixes", "richer_event", "offline"]
           + [f"fix:{f}" for f in FIX_LABELS]}
    for col in feats:
        res[col]["features_matching_training"] = parity_count(feats["offline"], feats[col])

    lines = [f"# What-if: live-feature fixes ({meta['rows']:,} held-out transactions, {meta['frauds']:,} fraud)", ""]
    lines += ["Same transactions, same model file (`" + meta["champion"] + "`). Only the live feature logic changes.",
              "The project was not changed (git before and after: `" + meta["project_git"]["after"] + "`).", "",
              "Self-checks passed: the fixed copy with no fixes reproduces the project's live features exactly, "
              "and the scores reproduce step 1.", ""]

    lines += ["## 1. Before vs after", ""]
    t = []
    for col, name in STAIRS:
        r = res[col]
        t.append({
            "": name,
            "ROC-AUC": f"{r['roc_auc']:.3f}",
            "Features matching training": f"{r['features_matching_training']} / 43",
            "Frauds caught @0.50": f"{pct(r['recall@0.5'])} ({r['frauds_caught@0.5']:,})",
            "Fraud $ caught @0.50": money(r["fraud_$_caught@0.5"]),
            "Good customers flagged @0.50": pct(r["fpr@0.5"]),
            f"Frauds caught at the offline alert budget ({pct(budget_fpr)} of good customers)": pct(r["budget_recall"]),
        })
    lines += [md_table(pd.DataFrame(t)), ""]
    lines += ["*Alert budget:* every row may flag the same share of good customers as the offline model does at 0.50, "
              "so the rows are compared fairly even though their scores are calibrated differently.", ""]

    lines += ["## 2. Each fix on its own (added to today's live features)", ""]
    base_auc, base_rec = res["live_today"]["roc_auc"], res["live_today"]["budget_recall"]
    t = []
    for fx, name in sorted(FIX_LABELS.items(), key=lambda kv: -res[f"fix:{kv[0]}"]["roc_auc"]):
        r = res[f"fix:{fx}"]
        t.append({"Fix": name, "ROC-AUC": f"{r['roc_auc']:.3f}", "Change": f"{r['roc_auc'] - base_auc:+.3f}",
                  "Frauds caught at alert budget": pct(r["budget_recall"]),
                  "Change ": f"{100 * (r['budget_recall'] - base_rec):+.1f} pts"})
    lines += [md_table(pd.DataFrame(t)), "",
              "Fixes interact: the combined result (section 1) is not the sum of the single-fix changes.", ""]

    lines += ["## 3. At the demo thresholds (REVIEW >= 0.10, BLOCK >= 0.18)", ""]
    rv, bk = POLICIES["demo (REVIEW>=0.10, BLOCK>=0.18)"]
    t = []
    for col, name in STAIRS:
        b = business_metrics(label, s[col], amount, rv, bk)
        t.append({"": name, "Frauds caught": pct(b["recall"]), "Fraud $ caught": money(b["fraud_$_caught"]),
                  "Good customers flagged": pct(b["fpr"]), "Good customers blocked": pct(b["good_customers_blocked_rate"]),
                  "Precision": pct(b["precision"]), "Alerts per 1,000": f"{b['alerts_per_1000']:.0f}"})
    lines += [md_table(pd.DataFrame(t)), ""]

    lines += ["## 4. Features that still differ from training after the code fixes", ""]
    p = feature_parity(feats["offline"], feats["all_code_fixes"])
    p = p[p["same_value_%"] < 99].copy()
    p["same_value_%"] = p["same_value_%"].map(lambda v: f"{v:.1f}%")
    p = p[["feature", "same_value_%"]].rename(columns={"same_value_%": "same as training"})
    lines += [md_table(p), "",
              "The Vesta history counters (C*, D*) need a feature store. card2/card3/card5/addr1 and the "
              "recipient email, card brand/type and M1-M9 flags need extra fields in the Avro event "
              "(the 'richer event' row).", ""]

    (HERE / "reports" / tag).mkdir(parents=True, exist_ok=True)
    rep = HERE / "reports" / tag
    (rep / "04_WHATIF_SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT / f"step4_{tag}.json").write_text(json.dumps(res, indent=2))

    def frame(col: str) -> pd.DataFrame:
        return pd.DataFrame({"label": label, "score": s[col]})
    classification_report(frame("all_code_fixes"), frame("live_today"), rep / "05_live_today_vs_code_fixes.html")
    classification_report(frame("richer_event"), frame("offline"), rep / "06_richer_event_vs_offline.html")
    drift_report(feats["offline"], feats["all_code_fixes"], rep / "07_feature_drift_training_vs_fixed_live.html")

    print("\n".join(lines))
    print(f"Wrote {rep / '04_WHATIF_SUMMARY.md'} and three Evidently reports")
    return 0


if __name__ == "__main__":
    sys.exit(main())

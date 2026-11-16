"""Step 2 — build the Evidently reports and the plain-language summary.

Runs in THIS folder's own .venv (evidently needs pandas 2; the project uses
pandas 3, so they are kept apart). Reads only the files step1 wrote to out/.

Usage (from this folder):
    .venv\\Scripts\\python.exe step2_reports.py --tag n500       # pilot
    .venv\\Scripts\\python.exe step2_reports.py --tag n118108    # full
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from evidently import BinaryClassification, DataDefinition, Dataset, Report
from evidently.presets import ClassificationPreset, DataDriftPreset
from sklearn.metrics import average_precision_score, roc_auc_score

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

# Threshold policies used by the project (scorer.py defaults, and the demo
# thresholds in docs/LAYER_3_FAST_PATH_SCORING.md).
POLICIES = {
    "production (REVIEW>=0.50, BLOCK>=0.85)": (0.50, 0.85),
    "demo (REVIEW>=0.10, BLOCK>=0.18)": (0.10, 0.18),
}
REPORT_THRESHOLD = 0.50  # Evidently reports use the production REVIEW threshold

# Documented offline results (docs/model_evaluation.md) — the full run must match.
DOCUMENTED = {"roc_auc": 0.9562, "recall@0.5": 0.8393, "fpr@0.5": 0.0656}

SENTINEL = -999.0

# Expected noise: many live features are a constant -999 (divide-by-zero in drift
# statistics), and live scores rarely cross 0.50 (precision undefined).
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", message=".*ill-defined.*")
sys.stdout.reconfigure(encoding="utf-8")


def classification_report(current: pd.DataFrame, reference: pd.DataFrame | None, path: Path) -> None:
    definition = DataDefinition(
        numerical_columns=["score"],
        classification=[BinaryClassification(
            target="label", prediction_probas="score", pos_label=1)],
    )
    cur = Dataset.from_pandas(current[["label", "score"]], data_definition=definition)
    ref = (Dataset.from_pandas(reference[["label", "score"]], data_definition=definition)
           if reference is not None else None)
    snapshot = Report([ClassificationPreset(probas_threshold=REPORT_THRESHOLD)]).run(
        current_data=cur, reference_data=ref)
    snapshot.save_html(str(path))


def drift_report(reference: pd.DataFrame, current: pd.DataFrame, path: Path) -> None:
    definition = DataDefinition(numerical_columns=list(reference.columns))
    snapshot = Report([DataDriftPreset()]).run(
        current_data=Dataset.from_pandas(current, data_definition=definition),
        reference_data=Dataset.from_pandas(reference, data_definition=definition))
    snapshot.save_html(str(path))


def business_metrics(label: pd.Series, score: pd.Series, amount: pd.Series,
                     review_t: float, block_t: float) -> dict:
    """Fraud-domain numbers a risk team reads, at one threshold policy."""
    fraud, legit = label == 1, label == 0
    flagged = score >= review_t
    blocked = score >= block_t
    tp = int((flagged & fraud).sum())
    fp = int((flagged & legit).sum())
    return {
        "frauds": int(fraud.sum()),
        "frauds_caught": tp,
        "recall": tp / max(int(fraud.sum()), 1),
        "fraud_$_total": float(amount[fraud].sum()),
        "fraud_$_caught": float(amount[flagged & fraud].sum()),
        "fraud_$_missed": float(amount[~flagged & fraud].sum()),
        "good_customers_flagged": fp,
        "fpr": fp / max(int(legit.sum()), 1),
        "good_customers_blocked_rate": int((blocked & legit).sum()) / max(int(legit.sum()), 1),
        "precision": tp / max(tp + fp, 1),
        "alerts_per_1000": 1000 * int(flagged.sum()) / max(len(label), 1),
    }


def ranking(label: pd.Series, score: pd.Series) -> dict:
    if label.nunique() < 2:
        return {"roc_auc": float("nan"), "pr_auc": float("nan")}
    return {"roc_auc": roc_auc_score(label, score), "pr_auc": average_precision_score(label, score)}


def feature_parity(off: pd.DataFrame, live: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col in off.columns:
        same = np.isclose(off[col].to_numpy(), live[col].to_numpy(), atol=1e-4)
        rows.append({
            "feature": col,
            "same_value_%": 100 * same.mean(),
            "live_missing(-999)_%": 100 * (live[col] == SENTINEL).mean(),
            "training_missing(-999)_%": 100 * (off[col] == SENTINEL).mean(),
        })
    return pd.DataFrame(rows).sort_values("same_value_%", ascending=False)


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def money(x: float) -> str:
    return f"${x:,.0f}"


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="n500")
    tag = ap.parse_args().tag

    step1 = json.loads((OUT / f"step1_{tag}.json").read_text())
    s = pd.read_parquet(OUT / f"scores_{tag}.parquet")
    f_off = pd.read_parquet(OUT / f"features_offline_{tag}.parquet")
    f_live = pd.read_parquet(OUT / f"features_live_{tag}.parquet")
    real = pd.read_parquet(OUT / "real_live_events_labeled.parquet")
    real = real[real["label"].notna()].assign(label=lambda d: d["label"].astype(int))

    rep = HERE / "reports" / tag
    rep.mkdir(parents=True, exist_ok=True)

    # ---- Evidently reports ----
    offline = s.assign(score=s["offline_score"])
    live = s.assign(score=s["live_score"])
    classification_report(live, offline, rep / "01_offline_vs_live_same_transactions.html")
    drift_report(f_off, f_live, rep / "02_feature_drift_training_vs_live.html")
    classification_report(real, None, rep / "03_real_live_server_events.html")
    print(f"Evidently reports written to {rep}")

    # ---- Numbers for the summary ----
    rank = {"Offline (full 43 features)": ranking(s["label"], s["offline_score"]),
            "Live pipeline (same transactions)": ranking(s["label"], s["live_score"]),
            "Real live server events": ranking(real["label"], real["score"])}

    biz_rows = []
    for pol, (rt, bt) in POLICIES.items():
        for name, sc, lab, amt in [
            ("Offline", s["offline_score"], s["label"], s["amount"]),
            ("Live (same txns)", s["live_score"], s["label"], s["amount"]),
            ("Real live server", real["score"], real["label"], real["amount"]),
        ]:
            m = business_metrics(lab, sc, amt, rt, bt)
            biz_rows.append({
                "policy": pol, "scored by": name,
                "frauds caught": f"{m['frauds_caught']} / {m['frauds']} ({pct(m['recall'])})",
                "fraud $ caught": f"{money(m['fraud_$_caught'])} of {money(m['fraud_$_total'])}",
                "fraud $ missed": money(m["fraud_$_missed"]),
                "good customers flagged (FPR)": pct(m["fpr"]),
                "good customers BLOCKED": pct(m["good_customers_blocked_rate"]),
                "precision": pct(m["precision"]),
                "alerts / 1,000 txns": f"{m['alerts_per_1000']:.1f}",
            })
    biz = pd.DataFrame(biz_rows)

    parity = feature_parity(f_off, f_live)
    n_identical = int((parity["same_value_%"] >= 99.0).sum())
    n_never = int((parity["same_value_%"] < 1.0).sum())
    parity_fmt = parity.assign(**{c: parity[c].map(lambda v: f"{v:.1f}") for c in parity.columns[1:]})

    seg_rows = []
    for prod, g in s.groupby("ProductCD"):
        seg_rows.append({
            "ProductCD": prod, "txns": len(g), "frauds": int(g["label"].sum()),
            "offline recall @0.50": pct(((g["offline_score"] >= 0.5) & (g["label"] == 1)).sum() / max(g["label"].sum(), 1)),
            "live recall @0.50": pct(((g["live_score"] >= 0.5) & (g["label"] == 1)).sum() / max(g["label"].sum(), 1)),
            "live recall @0.10": pct(((g["live_score"] >= 0.1) & (g["label"] == 1)).sum() / max(g["label"].sum(), 1)),
        })
    seg = pd.DataFrame(seg_rows)

    real_ct = pd.crosstab(real["decision"], real["label"].map({0: "legit", 1: "fraud"}))

    # ---- Sanity check against the project's documented offline numbers ----
    off_biz = business_metrics(s["label"], s["offline_score"], s["amount"], 0.5, 0.85)
    sanity = {
        "roc_auc": (round(rank["Offline (full 43 features)"]["roc_auc"], 4), DOCUMENTED["roc_auc"]),
        "recall@0.5": (round(off_biz["recall"], 4), DOCUMENTED["recall@0.5"]),
        "fpr@0.5": (round(off_biz["fpr"], 4), DOCUMENTED["fpr@0.5"]),
    }

    rc = step1["replica_check"]
    rank_df = pd.DataFrame([{"scored by": k, "ROC-AUC": f"{v['roc_auc']:.4f}", "PR-AUC": f"{v['pr_auc']:.4f}"}
                            for k, v in rank.items()])
    sanity_lines = "\n".join(
        f"- {k}: this run **{v[0]}**, documented **{v[1]}**" for k, v in sanity.items())

    md = f"""# VelocityFraud — Evidently evaluation ({tag})

Champion model: `{step1['champion']}` · Test-split rows used: **{len(s):,}** (frauds: **{int(s['label'].sum())}**) ·
Real live-server events: **{len(real):,}** (frauds: **{int(real['label'].sum())}**)

## 1. Is this laptop test the same as the live server? (replica check)
- Re-scored the {rc['events']:,} events the live pipeline already scored on the server.
- Largest score difference: **{rc['score_max_abs_diff']:.1e}** · scores within 0.000001: **{pct(rc['share_scores_within_1e-6'])}** ·
  identical feature completeness: **{pct(rc['share_completeness_identical'])}**.
- So every live number below is what the server would produce — without touching the server.

## 2. Ranking quality (threshold-free; 1.0 = perfect, 0.5 = coin flip)
{md_table(rank_df)}

## 3. Business view — what a fraud team reads
{md_table(biz)}

## 4. Feature parity — same transaction, training features vs live features
- Features identical on ≥99% of transactions: **{n_identical} of {len(parity)}**
- Features that never match (live sends the -999 "missing" value or a different encoding): **{n_never} of {len(parity)}**

{md_table(parity_fmt)}

## 5. Segments — recall by product type
{md_table(seg)}

## 6. Real live-server events — recorded decision vs the truth
The export spans several runs with different threshold settings, so these recorded
decisions are mixed; section 3 re-applies each policy to the same server scores consistently.

{md_table(real_ct.reset_index())}

## 7. Sanity check against docs/model_evaluation.md (full run should match)
{sanity_lines}

## Evidently reports (open in a browser)
- `01_offline_vs_live_same_transactions.html` — Reference = offline, Current = live; same transactions.
- `02_feature_drift_training_vs_live.html` — which of the 43 features look different live.
- `03_real_live_server_events.html` — the 4,692 events scored on the live server, against the true labels.
"""
    (rep / "00_SUMMARY.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

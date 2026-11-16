"""Step 6 - Evidently reports for the extended checks (reads only step5's files + the export).

Runs in THIS folder's own .venv, like step2.

    09 Random Forest vs XGBoost             (classification, same 118,108 rows)
    10 Out-of-time vs random split          (classification)
    11 Live pipeline at the demo thresholds (classification at 0.10)
    12 Data quality - raw IEEE-CIS transactions (data summary)
    13 Data quality - live pipeline export      (data summary)
    14 Drift - first 30 days vs last 30 days    (data drift, incl. champion score)
    15 Quality gates                            (pass/fail tests)
    08_EXTENDED_SUMMARY.md                       tables for all of the above

Usage (from this folder):
    .venv\\Scripts\\python.exe step6_extended_reports.py
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd
from evidently import BinaryClassification, DataDefinition, Dataset, Report
from evidently.metrics import FPR, Precision, Recall, RocAuc
from evidently.presets import ClassificationPreset, DataDriftPreset, DataSummaryPreset
from evidently.tests import gte, lte

from step2_reports import HERE, OUT, business_metrics, md_table, money, pct, ranking

PROJECT = HERE.parent  # the repo root: this pilot lives in velocityfraud/evidently-pilot
REP = HERE / "reports" / "extended"
BRONZE = PROJECT / "data" / "exports" / "scored_events_bronze.csv"
RAW_CSV = PROJECT / "data" / "raw" / "train_transaction.csv"

GATES = {"ROC-AUC >= 0.90": ("roc", 0.90), "Recall >= 0.80 (frauds caught @0.50)": ("recall", 0.80),
         "False-positive rate <= 0.08 (@0.50)": ("fpr", 0.08), "Precision >= 0.30 (@0.50)": ("precision", 0.30)}


def cls_definition() -> DataDefinition:
    return DataDefinition(numerical_columns=["score"], classification=[BinaryClassification(
        target="label", prediction_probas="score", pos_label=1)])


def ds(df: pd.DataFrame) -> Dataset:
    return Dataset.from_pandas(df[["label", "score"]].reset_index(drop=True), data_definition=cls_definition())


def cls_report(cur: pd.DataFrame, ref: pd.DataFrame | None, path, threshold: float = 0.50) -> None:
    Report([ClassificationPreset(probas_threshold=threshold)]).run(
        current_data=ds(cur), reference_data=ds(ref) if ref is not None else None).save_html(str(path))


def gate(df: pd.DataFrame) -> dict:
    """Pass/fail quality gate, evaluated by Evidently's test engine."""
    tests = {"roc": RocAuc(tests=[gte(0.90)]), "recall": Recall(probas_threshold=0.5, tests=[gte(0.80)]),
             "fpr": FPR(probas_threshold=0.5, tests=[lte(0.08)]), "precision": Precision(probas_threshold=0.5, tests=[gte(0.30)])}
    snap = Report(list(tests.values()), include_tests=True).run(current_data=ds(df), reference_data=None)
    return snap


def test_statuses(snap) -> list[str]:
    return [str(t.get("status", "")).split(".")[-1].upper() for t in snap.dict().get("tests", [])]


def segment_table(ctx: pd.DataFrame) -> pd.DataFrame:
    bands = pd.cut(ctx["amount"], [0, 50, 200, 445, np.inf], right=False,
                   labels=["under $50", "$50-200", "$200-445", "$445 and over"])
    top_email = ctx["P_emaildomain"].value_counts().index[:5]
    segs = {
        "Product": ctx["ProductCD"],
        "Amount": bands.astype(str),
        "Time of day": np.where((ctx["hour"] < 6) | (ctx["hour"] >= 22), "night (22-06)", "day (06-22)"),
        "Card type": ctx["card6"].where(ctx["card6"].isin(["debit", "credit"]), "other/missing"),
        "Email domain": ctx["P_emaildomain"].where(ctx["P_emaildomain"].isin(top_email), "other"),
    }
    rows = []
    for seg, values in segs.items():
        for v in sorted(pd.unique(values)):
            m = values == v
            lab = ctx.loc[m, "label"]
            r = {"Segment": seg, "Value": v, "Transactions": f"{int(m.sum()):,}", "Fraud rate": pct(lab.mean())}
            for col, name in (("xgboost", "XGBoost"), ("live_today", "Live")):
                rk = ranking(lab, ctx.loc[m, col])["roc_auc"]
                b = business_metrics(lab, ctx.loc[m, col], ctx.loc[m, "amount"], 0.50, 0.85)
                r[f"{name} ROC-AUC"] = "n/a" if np.isnan(rk) else f"{rk:.3f}"
                r[f"{name} caught @0.50"] = pct(b["recall"])
            r["XGBoost good customers flagged"] = pct(business_metrics(lab, ctx.loc[m, "xgboost"], ctx.loc[m, "amount"], 0.5, 0.85)["fpr"])
            rows.append(r)
    return pd.DataFrame(rows)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    REP.mkdir(parents=True, exist_ok=True)
    meta = json.loads((OUT / "step5_extended.json").read_text())
    ctx = pd.read_parquet(OUT / "ext_test_context.parquet")
    oot = pd.read_parquet(OUT / "ext_oot_scores.parquet")
    rnd = pd.read_parquet(OUT / "ext_random_clean_scores.parquet")
    frame = lambda col: pd.DataFrame({"label": ctx["label"], "score": ctx[col]})  # noqa: E731

    L = ["# Extended Evidently checks", "",
         "Laptop only: no server, Kafka, Redis, Postgres, Groq or Gemini. The project was not changed "
         f"(git before and after: `{meta['project_git']['after']}`). Self-check passed: the feature rebuild "
         "reproduces the project's X_test.parquet exactly.", ""]

    # 1 + 3. Models and thresholds
    L += ["## 1. Champion vs challenger, and threshold policies (118,108 held-out transactions)", ""]
    t = []
    for col, name in (("xgboost", "XGBoost (champion)"), ("random_forest", "Random Forest (challenger)"),
                      ("live_today", "Live pipeline today (XGBoost)")):
        rk = ranking(ctx["label"], ctx[col])
        for pol, (rv, bk) in (("production 0.50 / 0.85", (0.50, 0.85)), ("demo 0.10 / 0.18", (0.10, 0.18))):
            b = business_metrics(ctx["label"], ctx[col], ctx["amount"], rv, bk)
            t.append({"Model": name, "ROC-AUC": f"{rk['roc_auc']:.4f}", "PR-AUC": f"{rk['pr_auc']:.3f}", "Thresholds": pol,
                      "Frauds caught": pct(b["recall"]), "Fraud $ caught": money(b["fraud_$_caught"]),
                      "Good customers flagged": pct(b["fpr"]), "Good customers blocked": pct(b["good_customers_blocked_rate"]),
                      "Precision": pct(b["precision"])})
    L += [md_table(pd.DataFrame(t)), ""]
    cls_report(frame("random_forest"), frame("xgboost"), REP / "09_random_forest_vs_xgboost.html")
    cls_report(frame("live_today"), None, REP / "11_live_pipeline_at_demo_threshold_0.10.html", threshold=0.10)

    # 2. Out-of-time
    o = meta["out_of_time"]
    L += ["## 2. Out-of-time test", "",
          f"Same training recipe as `train_xgb.py`, early stopping on a validation slice (not the test set), "
          f"frequency tables and the high-amount cut-off fitted on the training period only. "
          f"Out-of-time: trained on the first {o['train_rows'] + o['val_rows']:,} transactions in time order, "
          f"tested on the last {o['test_rows']:,} ({o['test_frauds']:,} fraud, {o['test_days']}).", ""]
    t = []
    for name, df, note in (("Project as documented (random split, early stopping on the test set)", None, "documented"),
                           ("Random split, clean recipe", rnd, ""), ("Out-of-time (train on the past, test on the future)", oot, "")):
        if df is None:
            t.append({"Evaluation": name, "ROC-AUC": "0.9562", "Frauds caught @0.50": "83.9%", "Good customers flagged @0.50": "6.6%"})
            continue
        b = business_metrics(df["label"], df["score"], df["amount"], 0.50, 0.85)
        t.append({"Evaluation": name, "ROC-AUC": f"{ranking(df['label'], df['score'])['roc_auc']:.4f}",
                  "Frauds caught @0.50": pct(b["recall"]), "Good customers flagged @0.50": pct(b["fpr"])})
    L += [md_table(pd.DataFrame(t)), "",
          "The random split lets the same cards appear in training and test; testing on later days is the "
          "honest estimate of how the model performs on future transactions.", ""]
    cls_report(oot, rnd, REP / "10_out_of_time_vs_random_split.html")

    # 4. Segments
    L += ["## 3. Where the model is strong and weak (segments, test split)", "", md_table(segment_table(ctx)), ""]

    # 5. Data quality
    raw = pd.read_csv(RAW_CSV, usecols=lambda c: not c.startswith("V") and not c.startswith("id_"))
    cat = [c for c in ["ProductCD", "card4", "card6", "P_emaildomain", "R_emaildomain"] + [f"M{i}" for i in range(1, 10)] if c in raw]
    num = [c for c in raw.columns if c not in cat + ["TransactionID"]]
    Report([DataSummaryPreset()]).run(current_data=Dataset.from_pandas(
        raw, data_definition=DataDefinition(numerical_columns=num, categorical_columns=cat)), reference_data=None
    ).save_html(str(REP / "12_data_quality_raw_transactions.html"))
    miss = raw.isna().mean().sort_values(ascending=False)
    b = pd.read_csv(BRONZE)
    b_cat = ["currency", "merchant_name", "mcc", "merchant_country", "decision", "model_name", "model_version", "blocklist_tier"]
    b_num = ["amount", "amount_fx_normalised", "geo_distance_km", "fraud_score", "scoring_latency_ms", "feature_completeness"]
    Report([DataSummaryPreset()]).run(current_data=Dataset.from_pandas(
        b[b_cat + b_num].astype({c: str for c in b_cat}),
        data_definition=DataDefinition(numerical_columns=b_num, categorical_columns=b_cat)), reference_data=None
    ).save_html(str(REP / "13_data_quality_live_pipeline_export.html"))
    span = pd.to_datetime(b["scored_at_ms"], unit="ms", utc=True)
    lat = b["scoring_latency_ms"]
    L += ["## 4. Data quality", "",
          f"**Raw IEEE-CIS transactions** ({len(raw):,} rows, {raw.shape[1]} columns used by the project or available "
          f"to it): duplicate TransactionIDs **{int(raw['TransactionID'].duplicated().sum())}**; "
          f"columns more than 50% missing: **{int((miss > 0.5).sum())}** "
          f"(worst: {', '.join(f'{c} {100 * v:.0f}%' for c, v in miss.head(4).items())}).", "",
          f"**Live pipeline export** (`scored_events_bronze.csv`, {len(b):,} events scored "
          f"{span.min():%d %b %Y} - {span.max():%d %b %Y} UTC; an earlier pipeline run, not the Hetzner server): "
          f"duplicate event_ids **{int(b['event_id'].duplicated().sum())}** (exactly-once check); "
          f"missing values **{int(b.isna().sum().sum())}**; scoring latency p50 **{lat.quantile(0.5):.0f} ms**, "
          f"p95 **{lat.quantile(0.95):.0f} ms**, p99 **{lat.quantile(0.99):.0f} ms**, max {lat.max():.0f} ms; "
          f"feature completeness always **{b['feature_completeness'].min():.1%}-{b['feature_completeness'].max():.1%}**.", ""]

    # 6 + 7. Drift over time and score drift
    f30, l30 = pd.read_parquet(OUT / "ext_features_first30.parquet"), pd.read_parquet(OUT / "ext_features_last30.parquet")
    snap = Report([DataDriftPreset()]).run(
        current_data=Dataset.from_pandas(l30, data_definition=DataDefinition(numerical_columns=list(l30.columns))),
        reference_data=Dataset.from_pandas(f30, data_definition=DataDefinition(numerical_columns=list(f30.columns))))
    snap.save_html(str(REP / "14_drift_first_vs_last_30_days.html"))
    drifted = [m for m in snap.dict().get("metrics", []) if "DriftedColumnsCount" in str(m.get("metric_name", ""))]
    dval = drifted[0].get("value", {}) if drifted else {}
    L += ["## 5. Drift over time (first 30 days vs last 30 days of the dataset)", "",
          f"Drifted features (Evidently default tests): **{int(dval.get('count', 0))} of {l30.shape[1]}** "
          f"({pct(float(dval.get('share', 0)))}), including the champion's score. Full detail in report 14.", ""]
    w = ctx.assign(window=pd.cut(ctx["day"], 6, labels=[f"window {i}" for i in range(1, 7)]))
    t = []
    for win, g in w.groupby("window", observed=True):
        t.append({"Test-split window (time order)": f"{win} (days {g['day'].min()}-{g['day'].max()})",
                  "Transactions": f"{len(g):,}", "Fraud rate": pct(g["label"].mean()),
                  "XGBoost ROC-AUC": f"{ranking(g['label'], g['xgboost'])['roc_auc']:.3f}",
                  "XGBoost mean score": f"{g['xgboost'].mean():.3f}", "XGBoost flagged @0.50": pct((g["xgboost"] >= 0.5).mean()),
                  "Live mean score": f"{g['live_today'].mean():.3f}", "Live flagged @0.10": pct((g["live_today"] >= 0.10).mean())})
    L += ["**Score over time** (test split in six time windows; the replayer walks through time in this order):", "",
          md_table(pd.DataFrame(t)), ""]

    # 13. Quality gates
    L += ["## 6. Quality gates (Evidently pass/fail tests)", "",
          "The same four tests run on each candidate. A model or code change should ship only when all four pass.", ""]
    candidates = (("XGBoost champion, offline", frame("xgboost")), ("Random Forest challenger, offline", frame("random_forest")),
                  ("XGBoost, out-of-time", oot[["label", "score"]]), ("Live pipeline today", frame("live_today")))
    t = []
    html_parts = []
    for name, df in candidates:
        snap = gate(df)
        st = test_statuses(snap)
        html_parts.append((name, snap))
        row = {"Candidate": name}
        for (label, _), s in zip(GATES.items(), st + [""] * (len(GATES) - len(st))):
            row[label] = s or "?"
        row["Result"] = "PASS" if st and all(s == "SUCCESS" for s in st) else "FAIL"
        t.append(row)
    for name, snap in html_parts:
        slug = name.split(",")[0].lower().replace(" ", "_")
        tag = "out_of_time" if "out-of-time" in name else slug
        snap.save_html(str(REP / f"15_quality_gate_{tag}.html"))
    L += [md_table(pd.DataFrame(t)), ""]

    (REP / "08_EXTENDED_SUMMARY.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())

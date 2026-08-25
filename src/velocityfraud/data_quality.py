"""Great Expectations data-quality suite (Wk 12 QA).

Validates the model-ready IEEE-CIS feature splits in data/processed/ before they
feed training/inference: schema (43 features), no true NULLs (missing values are
the -999 sentinel), binary-flag domains, value ranges, row counts, and the fraud
label / class balance. Writes a Markdown report to docs/data_quality_report.md.

Run:
    uv run python -m velocityfraud.data_quality
Exit code 0 = all expectations passed.
"""
from __future__ import annotations

import json
from pathlib import Path

import great_expectations as gx
import pandas as pd
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DOCS_DIR = PROJECT_ROOT / "docs"

BINARY_FLAGS = ["is_night", "is_weekend", "is_round_dollar", "is_high_amount",
                "email_mismatch", "p_email_missing", "r_email_missing"]


def _batch(ctx, name: str, df: pd.DataFrame):
    ds = ctx.data_sources.add_pandas(name)
    asset = ds.add_dataframe_asset(name)
    bd = asset.add_batch_definition_whole_dataframe("all")
    return bd.get_batch(batch_parameters={"dataframe": df})


def _feature_suite(feature_names: list[str], n_rows: int) -> gx.ExpectationSuite:
    s = gx.ExpectationSuite(name="feature_quality")
    e = gx.expectations
    # Schema: exactly 43 features, the expected set, correct row count
    s.add_expectation(e.ExpectTableColumnCountToEqual(value=len(feature_names)))
    s.add_expectation(e.ExpectTableColumnsToMatchSet(column_set=feature_names))
    s.add_expectation(e.ExpectTableRowCountToEqual(value=n_rows))
    # No true NULLs anywhere (missing values were imputed to the -999 sentinel)
    for col in feature_names:
        s.add_expectation(e.ExpectColumnValuesToNotBeNull(column=col))
    # Amount is real (not sentinel) and non-negative
    s.add_expectation(e.ExpectColumnValuesToBeBetween(
        column="TransactionAmt", min_value=0, max_value=1_000_000))
    # Binary flags must be exactly 0/1
    for col in BINARY_FLAGS:
        s.add_expectation(e.ExpectColumnValuesToBeInSet(column=col, value_set=[0.0, 1.0]))
    # Time features either valid range or -999 sentinel
    s.add_expectation(e.ExpectColumnValuesToBeBetween(
        column="hour_of_day", min_value=-999, max_value=23))
    s.add_expectation(e.ExpectColumnValuesToBeBetween(
        column="day_of_week", min_value=-999, max_value=6))
    return s


def _label_suite(fraud_rate: float) -> gx.ExpectationSuite:
    s = gx.ExpectationSuite(name="label_quality")
    e = gx.expectations
    s.add_expectation(e.ExpectColumnValuesToBeInSet(column="isFraud", value_set=[0, 1]))
    s.add_expectation(e.ExpectColumnValuesToNotBeNull(column="isFraud"))
    # Class balance must stay near the known ~3.5% fraud rate
    lo, hi = max(0.0, fraud_rate - 0.01), fraud_rate + 0.01
    s.add_expectation(e.ExpectColumnMeanToBeBetween(
        column="isFraud", min_value=lo, max_value=hi))
    return s


def _report_lines(title: str, result) -> list[str]:
    lines = [f"### {title} — {'PASS' if result.success else 'FAIL'}", ""]
    for r in result.results:
        cfg = r.expectation_config
        col = cfg.kwargs.get("column", "-")
        lines.append(f"- [{'ok' if r.success else 'X'}] {cfg.type} "
                     f"(column={col})")
    lines.append("")
    return lines


def main() -> int:
    meta = json.loads((PROCESSED_DIR / "feature_meta.json").read_text())
    feats = meta["feature_names"]

    x_test = pd.read_parquet(PROCESSED_DIR / "X_test.parquet")
    y_test = pd.read_parquet(PROCESSED_DIR / "y_test.parquet")

    ctx = gx.get_context()

    logger.info("=" * 70)
    logger.info("DATA-QUALITY SUITE (Great Expectations) — X_test / y_test")
    logger.info("=" * 70)

    feat_res = _batch(ctx, "features", x_test).validate(
        _feature_suite(feats, meta["n_test"]))
    label_res = _batch(ctx, "labels", y_test).validate(
        _label_suite(meta["fraud_rate_test"]))

    all_ok = feat_res.success and label_res.success
    n_pass = sum(r.success for r in feat_res.results) + sum(r.success for r in label_res.results)
    n_total = len(feat_res.results) + len(label_res.results)

    logger.info("Features suite: {}  ({}/{} expectations)",
                "PASS" if feat_res.success else "FAIL",
                sum(r.success for r in feat_res.results), len(feat_res.results))
    logger.info("Labels suite:   {}  ({}/{} expectations)",
                "PASS" if label_res.success else "FAIL",
                sum(r.success for r in label_res.results), len(label_res.results))
    logger.info("-" * 70)
    logger.info("OVERALL: {}  ({}/{} expectations passed)",
                "PASS" if all_ok else "FAIL", n_pass, n_total)

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Data-Quality Report (Great Expectations)",
        "",
        f"Validated the model-ready feature splits in `data/processed/`. "
        f"Overall: **{'PASS' if all_ok else 'FAIL'}** ({n_pass}/{n_total} expectations).",
        "",
        f"- X_test: {len(x_test):,} rows x {x_test.shape[1]} features",
        f"- y_test fraud rate: {float(y_test.iloc[:,0].mean()):.4f} "
        f"(expected ~{meta['fraud_rate_test']:.4f})",
        "",
    ]
    lines += _report_lines("Feature suite", feat_res)
    lines += _report_lines("Label suite", label_res)
    (DOCS_DIR / "data_quality_report.md").write_text("\n".join(lines), encoding="utf-8")
    logger.success("Report written to {}", DOCS_DIR / "data_quality_report.md")

    return 0 if all_ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())

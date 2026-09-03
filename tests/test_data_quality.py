"""Unit tests for the Great Expectations data-quality suite (Wk 12 QA).

No live infra needed: great_expectations runs entirely in-process against a
tiny synthetic feature set built from the real 43-feature schema, written to
tmp_path so nothing touches the real data/processed/ or docs/ directories.
"""
from __future__ import annotations

import json

import great_expectations as gx
import pandas as pd
import pytest

from velocityfraud.data_quality import (
    BINARY_FLAGS,
    _feature_suite,
    _label_suite,
    _report_lines,
    main,
)

# ExpectationSuite.add_expectation() requires an active GX data context even
# when the suite is never validated -- same call main() makes before building
# suites. Do it once for every test in this module.
gx.get_context()

FEATURE_NAMES = [
    "TransactionAmt", "card1", "card2", "card3", "card5", "addr1", "addr2", "dist1",
    "C1", "C2", "C5", "C13", "C14", "D1", "D2", "D4", "D10", "D15",
    "hour_of_day", "day_of_week", "is_night", "is_weekend", "log_amount",
    "amount_cents", "is_round_dollar", "is_high_amount", "email_mismatch",
    "p_email_missing", "r_email_missing", "ProductCD_freq", "card4_freq",
    "card6_freq", "P_emaildomain_freq", "R_emaildomain_freq",
    "M1_freq", "M2_freq", "M3_freq", "M4_freq", "M5_freq", "M6_freq",
    "M7_freq", "M8_freq", "M9_freq",
]


def _synthetic_row(amount: float = 42.50) -> dict:
    row = {name: -999.0 for name in FEATURE_NAMES}
    row["TransactionAmt"] = amount
    row["hour_of_day"] = 14.0
    row["day_of_week"] = 2.0
    for flag in BINARY_FLAGS:
        row[flag] = 0.0
    return row


# ---------------------------------------------------------------------------
# _feature_suite / _label_suite -- expectation construction
# ---------------------------------------------------------------------------
def test_feature_suite_covers_every_feature_column():
    suite = _feature_suite(FEATURE_NAMES, n_rows=100)
    not_null_columns = {
        ex.column for ex in suite.expectations
        if ex.expectation_type == "expect_column_values_to_not_be_null"
    }
    assert not_null_columns == set(FEATURE_NAMES)


def test_feature_suite_includes_schema_and_range_checks():
    suite = _feature_suite(FEATURE_NAMES, n_rows=100)
    types = [ex.expectation_type for ex in suite.expectations]
    assert "expect_table_column_count_to_equal" in types
    assert "expect_table_columns_to_match_set" in types
    assert "expect_table_row_count_to_equal" in types
    assert "expect_column_values_to_be_between" in types  # TransactionAmt + time cols


def test_label_suite_class_balance_window():
    fraud_rate = 0.035
    suite = _label_suite(fraud_rate)
    mean_expectation = next(
        ex for ex in suite.expectations if ex.expectation_type == "expect_column_mean_to_be_between"
    )
    assert mean_expectation.min_value == pytest.approx(fraud_rate - 0.01)
    assert mean_expectation.max_value == pytest.approx(fraud_rate + 0.01)


def test_label_suite_floors_at_zero_for_low_fraud_rate():
    """A near-zero fraud rate must not produce a negative min_value window."""
    suite = _label_suite(0.001)
    mean_expectation = next(
        ex for ex in suite.expectations if ex.expectation_type == "expect_column_mean_to_be_between"
    )
    assert mean_expectation.min_value == 0.0


# ---------------------------------------------------------------------------
# _report_lines -- Markdown formatting, both PASS and FAIL
# ---------------------------------------------------------------------------
class _FakeExpectationConfig:
    def __init__(self, type_: str, column: str):
        self.type = type_
        self.kwargs = {"column": column}


class _FakeExpectationResult:
    def __init__(self, success: bool, type_: str, column: str):
        self.success = success
        self.expectation_config = _FakeExpectationConfig(type_, column)


class _FakeSuiteResult:
    def __init__(self, success: bool, results: list):
        self.success = success
        self.results = results


def test_report_lines_marks_pass_and_fail_distinctly():
    result = _FakeSuiteResult(success=False, results=[
        _FakeExpectationResult(True, "expect_column_values_to_not_be_null", "amount"),
        _FakeExpectationResult(False, "expect_column_values_to_be_between", "hour_of_day"),
    ])
    lines = _report_lines("Feature suite", result)
    text = "\n".join(lines)
    assert "Feature suite — FAIL" in text
    assert "[ok] expect_column_values_to_not_be_null (column=amount)" in text
    assert "[X] expect_column_values_to_be_between (column=hour_of_day)" in text


def test_report_lines_all_pass():
    result = _FakeSuiteResult(success=True, results=[
        _FakeExpectationResult(True, "expect_table_row_count_to_equal", "-"),
    ])
    text = "\n".join(_report_lines("Label suite", result))
    assert "Label suite — PASS" in text
    assert "[X]" not in text


# ---------------------------------------------------------------------------
# main() -- end-to-end against a tiny synthetic dataset, real GE validation
# ---------------------------------------------------------------------------
def _write_synthetic_dataset(processed_dir, n_rows: int, fraud_rate: float):
    processed_dir.mkdir(parents=True, exist_ok=True)
    n_fraud = round(n_rows * fraud_rate)
    rows = [_synthetic_row(amount=10.0 + i) for i in range(n_rows)]
    x_df = pd.DataFrame(rows, columns=FEATURE_NAMES)
    y_df = pd.DataFrame({"isFraud": [1] * n_fraud + [0] * (n_rows - n_fraud)})

    x_df.to_parquet(processed_dir / "X_test.parquet")
    y_df.to_parquet(processed_dir / "y_test.parquet")
    (processed_dir / "feature_meta.json").write_text(json.dumps({
        "feature_names": FEATURE_NAMES,
        "n_test": n_rows,
        "fraud_rate_test": fraud_rate,
    }))


def test_main_passes_on_a_clean_synthetic_dataset(monkeypatch, tmp_path):
    processed_dir = tmp_path / "processed"
    docs_dir = tmp_path / "docs"
    _write_synthetic_dataset(processed_dir, n_rows=200, fraud_rate=0.05)

    monkeypatch.setattr("velocityfraud.data_quality.PROCESSED_DIR", processed_dir)
    monkeypatch.setattr("velocityfraud.data_quality.DOCS_DIR", docs_dir)

    rc = main()

    assert rc == 0
    report = (docs_dir / "data_quality_report.md").read_text()
    assert "PASS" in report
    assert "X_test: 200 rows" in report


def test_main_fails_when_a_binary_flag_is_corrupted(monkeypatch, tmp_path):
    """A real defect (a flag value outside {0, 1}) must make the suite FAIL,
    not silently pass -- this is the property the whole module exists for."""
    processed_dir = tmp_path / "processed"
    docs_dir = tmp_path / "docs"
    processed_dir.mkdir(parents=True, exist_ok=True)

    rows = [_synthetic_row() for _ in range(20)]
    rows[5]["is_night"] = 7.0  # corrupt: not a valid binary flag
    x_df = pd.DataFrame(rows, columns=FEATURE_NAMES)
    y_df = pd.DataFrame({"isFraud": [0] * 19 + [1]})
    x_df.to_parquet(processed_dir / "X_test.parquet")
    y_df.to_parquet(processed_dir / "y_test.parquet")
    (processed_dir / "feature_meta.json").write_text(json.dumps({
        "feature_names": FEATURE_NAMES, "n_test": 20, "fraud_rate_test": 0.05,
    }))

    monkeypatch.setattr("velocityfraud.data_quality.PROCESSED_DIR", processed_dir)
    monkeypatch.setattr("velocityfraud.data_quality.DOCS_DIR", docs_dir)

    rc = main()

    assert rc == 1
    report = (docs_dir / "data_quality_report.md").read_text()
    assert "FAIL" in report

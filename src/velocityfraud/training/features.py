"""IEEE-CIS feature engineering pipeline.

Converts the raw `train_transaction.csv` (590K rows, 394 columns) into a
clean, model-ready feature matrix saved as Parquet.

Pipeline:
    1. Load curated subset of raw columns (~40 from 394)
    2. Engineer time features (hour, day-of-week from TransactionDT)
    3. Engineer amount features (log, round-dollar flag, decimal cents)
    4. Frequency-encode high-cardinality categoricals
    5. Drop columns with >70% missing values
    6. Fill remaining NaN with -999 (sentinel; tree models handle it)
    7. Split into X / y / X_train / X_test (stratified, 80/20)
    8. Persist all four splits as Parquet

Usage (from velocityfraud/ root):
    uv run python -m velocityfraud.training.features

Outputs (to data/processed/):
    X_train.parquet, y_train.parquet
    X_test.parquet,  y_test.parquet
    feature_meta.json  (column list + dtypes for re-use at inference time)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger
from sklearn.model_selection import train_test_split


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
RAW_CSV = PROJECT_ROOT / "data" / "raw" / "train_transaction.csv"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

# Reference epoch — IEEE-CIS TransactionDT is seconds since this point.
REFERENCE_EPOCH_S = 1_512_086_400  # 2017-12-01 UTC

# Random seed for reproducibility (CRITICAL for presentation: same split every run)
RANDOM_STATE = 42
TEST_SIZE = 0.20

# Drop columns whose missingness exceeds this threshold (after we've loaded them)
MISSING_THRESHOLD = 0.70

# Curated raw column list — chosen for signal-to-noise + interpretability.
# We deliberately skip V1-V339 (Vesta's anonymized engineered features) for the
# baseline because they're opaque ("V147") — bad for presentation. Drops 339
# features but typically loses only ~5 AUC points.
RAW_COLS = [
    "TransactionID",       # join key, not a feature
    "isFraud",             # TARGET
    "TransactionDT",       # seconds since epoch
    "TransactionAmt",      # transaction amount
    "ProductCD",           # product category (W/C/R/H/S)
    "card1", "card2", "card3", "card5",  # card features (card4/card6 are issuer name/type)
    "card4",               # Visa/Mastercard/Amex/Discover
    "card6",               # debit/credit
    "addr1", "addr2",      # billing address region codes
    "dist1", "dist2",      # distances between addresses (fraud signal!)
    "P_emaildomain",       # purchaser email domain
    "R_emaildomain",       # recipient email domain
    # Match flags (anti-fraud indicators by Vesta)
    "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9",
    # Count features (rolling counts by Vesta)
    "C1", "C2", "C5", "C13", "C14",
    # Time delta features (time since last activity)
    "D1", "D2", "D4", "D10", "D15",
]


# ---------------------------------------------------------------------------
# Feature engineering steps
# ---------------------------------------------------------------------------
def _add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Derive hour-of-day and day-of-week from TransactionDT seconds."""
    txn_ts = REFERENCE_EPOCH_S + df["TransactionDT"]
    txn_dt = pd.to_datetime(txn_ts, unit="s", utc=True)
    df["hour_of_day"] = txn_dt.dt.hour.astype("int16")
    df["day_of_week"] = txn_dt.dt.dayofweek.astype("int16")  # Mon=0, Sun=6
    df["is_night"] = ((df["hour_of_day"] < 6) | (df["hour_of_day"] >= 22)).astype("int8")
    df["is_weekend"] = (df["day_of_week"] >= 5).astype("int8")
    return df


def _add_amount_features(df: pd.DataFrame) -> pd.DataFrame:
    """Derive amount-shape features that often correlate with fraud."""
    amt = df["TransactionAmt"].astype("float32")
    df["log_amount"] = np.log1p(amt).astype("float32")
    df["amount_cents"] = ((amt * 100) % 100).astype("int16")  # cents portion
    df["is_round_dollar"] = (df["amount_cents"] == 0).astype("int8")
    df["is_high_amount"] = (amt > amt.quantile(0.95)).astype("int8")
    return df


def _add_email_features(df: pd.DataFrame) -> pd.DataFrame:
    """Mismatch between purchaser and recipient email domains is a fraud signal."""
    p = df["P_emaildomain"].fillna("missing")
    r = df["R_emaildomain"].fillna("missing")
    df["email_mismatch"] = (p != r).astype("int8")
    df["p_email_missing"] = (p == "missing").astype("int8")
    df["r_email_missing"] = (r == "missing").astype("int8")
    return df


def _frequency_encode(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Replace each categorical value with its frequency in the column.

    Avoids one-hot explosion for high-cardinality columns and gives the model
    a usable numeric signal (popular values vs rare ones).
    """
    for col in cols:
        if col not in df.columns:
            continue
        freq = df[col].value_counts(dropna=False, normalize=True)
        df[f"{col}_freq"] = df[col].map(freq).astype("float32")
    return df


def _drop_high_missing(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Drop columns whose missing-value fraction exceeds the threshold."""
    missing_pct = df.isna().mean()
    drop_cols = missing_pct[missing_pct > threshold].index.tolist()
    if drop_cols:
        logger.info("Dropping {} cols with >{:.0%} missing: {}",
                    len(drop_cols), threshold, drop_cols)
    return df.drop(columns=drop_cols)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def build_features() -> tuple[pd.DataFrame, pd.Series]:
    """Run the full feature engineering pipeline and return (X, y)."""
    if not RAW_CSV.exists():
        raise FileNotFoundError(f"Raw CSV not found at {RAW_CSV}")

    logger.info("Loading {} columns from {}", len(RAW_COLS), RAW_CSV.name)
    df = pd.read_csv(RAW_CSV, usecols=RAW_COLS)
    logger.info("Loaded shape: {} rows x {} cols", *df.shape)
    logger.info("Fraud rate: {:.2%} ({}/{} positive)",
                df["isFraud"].mean(), df["isFraud"].sum(), len(df))

    logger.info("Engineering time features...")
    df = _add_time_features(df)

    logger.info("Engineering amount features...")
    df = _add_amount_features(df)

    logger.info("Engineering email features...")
    df = _add_email_features(df)

    logger.info("Frequency-encoding high-cardinality categoricals...")
    cat_cols = ["ProductCD", "card4", "card6", "P_emaildomain", "R_emaildomain",
                "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9"]
    df = _frequency_encode(df, cat_cols)

    # Drop original string cols (we kept frequency-encoded versions)
    df = df.drop(columns=[c for c in cat_cols if c in df.columns])

    # Drop join key + raw timestamp (not predictive on its own)
    df = df.drop(columns=["TransactionID", "TransactionDT"])

    # Drop high-missing columns
    df = _drop_high_missing(df, MISSING_THRESHOLD)

    # Separate target from features BEFORE imputing
    y = df["isFraud"].astype("int8")
    X = df.drop(columns=["isFraud"])

    # Fill remaining NaN with sentinel (-999) — tree models split on it as
    # "missing", which is itself often informative for fraud.
    X = X.fillna(-999).astype("float32")

    logger.info("Final feature matrix: {} rows x {} cols", *X.shape)
    logger.info("Feature columns: {}", X.columns.tolist())
    return X, y


def split_and_persist(X: pd.DataFrame, y: pd.Series) -> dict:
    """Stratified 80/20 split. Persist all 4 parts as Parquet."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=y,  # preserve fraud rate in both splits
    )

    logger.info("Train: {} rows | fraud rate {:.2%}", len(X_train), y_train.mean())
    logger.info("Test:  {} rows | fraud rate {:.2%}", len(X_test), y_test.mean())

    X_train.to_parquet(PROCESSED_DIR / "X_train.parquet", index=False)
    X_test.to_parquet(PROCESSED_DIR / "X_test.parquet", index=False)
    y_train.to_frame().to_parquet(PROCESSED_DIR / "y_train.parquet", index=False)
    y_test.to_frame().to_parquet(PROCESSED_DIR / "y_test.parquet", index=False)

    meta = {
        "n_features": X.shape[1],
        "feature_names": X.columns.tolist(),
        "dtypes": {c: str(X[c].dtype) for c in X.columns},
        "n_train": len(X_train),
        "n_test": len(X_test),
        "fraud_rate_train": float(y_train.mean()),
        "fraud_rate_test": float(y_test.mean()),
        "random_state": RANDOM_STATE,
        "test_size": TEST_SIZE,
    }
    meta_path = PROCESSED_DIR / "feature_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    logger.info("Wrote meta to {}", meta_path)

    return meta


def main() -> int:
    X, y = build_features()
    meta = split_and_persist(X, y)
    logger.success("Feature engineering complete. {} features ready for training.",
                   meta["n_features"])
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

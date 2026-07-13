"""Live feature engineering — Avro TransactionEvent -> 43-feature vector.

The BRIDGE between the live Kafka stream and the trained XGBoost model.

The champion model was trained on 43 features engineered from the IEEE-CIS
training CSV. Many of those (C1-C14, D1-D15, M1-M9) are Vesta's anti-fraud
counters/deltas computed from historical card behavior — they don't exist
in a single live transaction event.

This module:
    1. Maps the 16 Avro fields to the features we CAN compute (~12-15 of 43)
    2. Fills the rest with the -999 sentinel (matches training imputation)
    3. Returns a (DataFrame, feature_completeness) tuple

In production, the missing features would come from a streaming feature
store (Feast / Tecton / Redis), populated by aggregator jobs that maintain
rolling counts per card. For this POC, we accept degraded scoring confidence
and explicitly track it via `feature_completeness` (0.0-1.0).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from velocityfraud.predict import get_feature_names


# ---------------------------------------------------------------------------
# Constants — frequency lookups derived from IEEE-CIS training data
# ---------------------------------------------------------------------------
# Sentinel value for any feature we cannot compute from a live event.
# Matches training-time NaN imputation in features.py.
SENTINEL = -999.0

# ProductCD frequencies in train_transaction.csv (computed once during EDA).
PRODUCTCD_FREQS = {
    "W": 0.7449,  # most common — non-card-present
    "C": 0.1276,
    "R": 0.0635,
    "H": 0.0498,
    "S": 0.0143,
}

# MCC -> ProductCD reverse lookup (mirror of replayer.py's PRODUCTCD_TO_MCC).
MCC_TO_PRODUCTCD = {
    "5411": "W",
    "5732": "C",
    "5812": "R",
    "7011": "H",
    "5999": "S",
}

# Most common email domain frequencies in P_emaildomain (IEEE-CIS approx).
# Used for P_emaildomain_freq; unknown domains get the median ~0.01.
EMAIL_DOMAIN_FREQS = {
    "gmail.com":      0.4373,
    "yahoo.com":      0.1681,
    "hotmail.com":    0.0743,
    "anonymous.com":  0.0518,
    "aol.com":        0.0386,
    "icloud.com":     0.0263,
    "outlook.com":    0.0192,
    "comcast.net":    0.0119,
    "msn.com":        0.0089,
    "att.net":        0.0076,
    "verizon.net":    0.0066,
    "me.com":         0.0046,
    "live.com":       0.0042,
    "sbcglobal.net":  0.0036,
    "cox.net":        0.0031,
    "ymail.com":      0.0019,
    "charter.net":    0.0017,
    "optonline.net":  0.0011,
    "earthlink.net":  0.0009,
    "rocketmail.com": 0.0007,
    "nan":            0.0010,  # represents missing email
    "missing":        0.0010,
}
EMAIL_DOMAIN_DEFAULT = 0.0050

# 95th-percentile transaction amount in training (USD).
HIGH_AMOUNT_THRESHOLD = 200.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _extract_email_domain(merchant_name: str) -> str:
    """Replayer encodes merchant_name as '{ProductCD}-MERCHANT-{email_domain}'.

    Example: 'W-MERCHANT-gmail.com' -> 'gmail.com'.
    Returns 'missing' if the suffix can't be parsed.
    """
    if not merchant_name or "-MERCHANT-" not in merchant_name:
        return "missing"
    parts = merchant_name.split("-MERCHANT-", 1)
    domain = parts[1].strip().lower() if len(parts) == 2 else "missing"
    return domain or "missing"


def _safe_int(value: str, default: float = SENTINEL) -> float:
    """Parse a numeric string. Return SENTINEL on failure."""
    try:
        return float(int(value))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def featurize_event(event: dict) -> tuple[pd.DataFrame, float]:
    """Map one Avro TransactionEvent dict -> single-row 43-feature DataFrame.

    Args:
        event: decoded Avro dict with the 16 TransactionEvent fields.

    Returns:
        (X, feature_completeness)
        X: pd.DataFrame, shape (1, 43), float32, columns ordered exactly as
           the model expects (per data/processed/feature_meta.json).
        feature_completeness: float in [0, 1] — fraction of the 43 features
           that were filled with REAL data (not the -999 sentinel).
    """
    feature_names = get_feature_names()

    amount = float(event.get("amount", 0.0) or 0.0)
    ts_ms = int(event.get("event_timestamp_ms", 0) or 0)
    mcc = str(event.get("mcc", "") or "")
    merchant_country = str(event.get("merchant_country", "00") or "00")
    merchant_name = str(event.get("merchant_name", "") or "")

    # Derive product / email signals from the Avro fields
    product_cd = MCC_TO_PRODUCTCD.get(mcc, "S")  # default to 'S' (specialty)
    productcd_freq = PRODUCTCD_FREQS.get(product_cd, 0.0143)

    email_domain = _extract_email_domain(merchant_name)
    p_email_freq = EMAIL_DOMAIN_FREQS.get(email_domain, EMAIL_DOMAIN_DEFAULT)
    p_email_missing = 1.0 if email_domain in ("missing", "nan", "anonymous.com") else 0.0

    # Time features (from event_timestamp_ms)
    if ts_ms > 0:
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        hour = float(dt.hour)
        dow = float(dt.weekday())  # Mon=0, Sun=6
        is_night = 1.0 if (hour < 6 or hour >= 22) else 0.0
        is_weekend = 1.0 if dow >= 5 else 0.0
    else:
        hour = dow = is_night = is_weekend = SENTINEL

    # Amount features
    log_amount = float(math.log1p(amount))
    amount_cents = float(int(round(amount * 100)) % 100)
    is_round_dollar = 1.0 if amount_cents == 0 else 0.0
    is_high_amount = 1.0 if amount > HIGH_AMOUNT_THRESHOLD else 0.0

    # ----------- Assemble the 43-feature row -----------
    feature_values: dict[str, float] = {}

    # Real values where we have them
    real = {
        "TransactionAmt":     amount,
        "addr2":              _safe_int(merchant_country, default=SENTINEL),
        "hour_of_day":        hour,
        "day_of_week":        dow,
        "is_night":           is_night,
        "is_weekend":         is_weekend,
        "log_amount":         log_amount,
        "amount_cents":       amount_cents,
        "is_round_dollar":    is_round_dollar,
        "is_high_amount":     is_high_amount,
        "ProductCD_freq":     productcd_freq,
        "P_emaildomain_freq": p_email_freq,
        "p_email_missing":    p_email_missing,
        # R_emaildomain unknown from Avro -> count as missing
        "r_email_missing":    1.0,
        "email_mismatch":     0.0,  # cannot detect -> assume no mismatch
    }

    n_real = 0
    for col in feature_names:
        if col in real and not (isinstance(real[col], float) and real[col] == SENTINEL):
            feature_values[col] = real[col]
            n_real += 1
        else:
            feature_values[col] = SENTINEL

    X = pd.DataFrame([feature_values], columns=feature_names).astype("float32")
    completeness = round(n_real / len(feature_names), 4)
    return X, completeness


def featurize_batch(events: list[dict]) -> tuple[pd.DataFrame, list[float]]:
    """Vectorized version of featurize_event for batches of events."""
    rows = []
    completenesses = []
    for ev in events:
        X, c = featurize_event(ev)
        rows.append(X.iloc[0])
        completenesses.append(c)
    if not rows:
        return pd.DataFrame(columns=get_feature_names()).astype("float32"), []
    return pd.DataFrame(rows).astype("float32"), completenesses


# ---------------------------------------------------------------------------
# Smoke test — show the mapping for one sample event
# ---------------------------------------------------------------------------
def _demo() -> int:
    """Print the feature vector for one synthetic event."""
    from loguru import logger
    sample = {
        "event_id":               "test-uuid-001",
        "event_timestamp_ms":     1782731301417,  # arbitrary
        "customer_id":            "13926",
        "card_token":             "10c1bf7c3c76e313",
        "amount":                 125.99,
        "currency":               "USD",
        "amount_fx_normalised":   125.99,
        "merchant_id_hash":       "5f59d374246893e0",
        "merchant_name":          "W-MERCHANT-gmail.com",
        "mcc":                    "5411",
        "merchant_country":       "87",
        "ip_address_hash":        "98e58ca964c583e2",
        "device_fingerprint_hash":"a245d9cb16edd5da",
        "geo_distance_km":        12.5,
        "source_label":           "replayer",
        "schema_version":         "v1",
    }
    X, completeness = featurize_event(sample)
    logger.info("=" * 60)
    logger.info("LIVE FEATURE MAPPING DEMO")
    logger.info("=" * 60)
    logger.info("Input event: merchant={}, mcc={}, amount=${}",
                sample["merchant_name"], sample["mcc"], sample["amount"])
    logger.info("Feature vector shape: {} (expected (1, 43))", X.shape)
    logger.info("Feature completeness: {:.2%}", completeness)
    logger.info("Sample non-sentinel features:")
    for col in X.columns:
        val = X.iloc[0][col]
        if val != SENTINEL:
            logger.info("  {:30s} {}", col, val)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_demo())

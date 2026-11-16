"""What-if copy of velocityfraud/live_features.py with the FINDINGS.md fixes applied.

Lives ONLY in this evaluation folder; the project's live_features.py is not touched.

Vectorised: one call featurises a whole frame of Avro events, so the 118,108-row
test split takes seconds instead of the ~16 minutes the per-event original takes.
With fixes=() it reproduces the original live_features.featurize_event exactly
(step3 checks this on every row before trusting any other number).

Fixes (numbers match FINDINGS.md section 3 where they exist):
    card1        1  card1 from the event's customer_id instead of -999
    dist1        2  dist1 from geo_distance_km; 0.0 treated as missing (the replayer
                    writes 0.0 when dist1 and dist2 are both missing)
    email        3,4,9  email_mismatch / r_email_missing / R_emaildomain_freq computed
                    from one recipient domain: the most common one for the product
                    type in training (the event carries no recipient email)
    p_missing    new  anonymous.com is a real domain in training, not a missing email
    addr2        5  merchant_country "00" is a missing addr2 (-999), not 0
    high_amount  6  cut-off = training 95th percentile ($445), not $200
    freq_tables  7  ProductCD_freq / P_emaildomain_freq from the training frequencies
                    (a missing email has its own frequency, 0.16, not 0.001)
    cents        8  amount arithmetic in float32 with truncation, exactly as training
    never_seen   9  card4/card6/M1-M9 frequencies: the most common value for the
                    product type in training, instead of -999 (never seen in training)

Richer event (not a code fix: needs extra fields in the Avro event): the raw
per-transaction fields card2, card3, card5, card4, card6, addr1, dist1,
R_emaildomain and M1-M9 are passed in `extra`. The ten Vesta history counters
(C1-C15, D1-D15 subsets) still need a feature store and stay -999.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

SENTINEL = -999.0
NAN_KEY = "__nan__"  # JSON key for "value was missing" in frequency/mode tables

CODE_FIXES = ("card1", "dist1", "email", "p_missing", "addr2",
              "high_amount", "freq_tables", "cents", "never_seen")

# --- the original module's hard-coded constants (copied verbatim) ------------
ORIG_PRODUCTCD_FREQS = {"W": 0.7449, "C": 0.1276, "R": 0.0635, "H": 0.0498, "S": 0.0143}
MCC_TO_PRODUCTCD = {"5411": "W", "5732": "C", "5812": "R", "7011": "H", "5999": "S"}
ORIG_EMAIL_DOMAIN_FREQS = {
    "gmail.com": 0.4373, "yahoo.com": 0.1681, "hotmail.com": 0.0743, "anonymous.com": 0.0518,
    "aol.com": 0.0386, "icloud.com": 0.0263, "outlook.com": 0.0192, "comcast.net": 0.0119,
    "msn.com": 0.0089, "att.net": 0.0076, "verizon.net": 0.0066, "me.com": 0.0046,
    "live.com": 0.0042, "sbcglobal.net": 0.0036, "cox.net": 0.0031, "ymail.com": 0.0019,
    "charter.net": 0.0017, "optonline.net": 0.0011, "earthlink.net": 0.0009,
    "rocketmail.com": 0.0007, "nan": 0.0010, "missing": 0.0010,
}
ORIG_EMAIL_DOMAIN_DEFAULT = 0.0050
ORIG_HIGH_AMOUNT_THRESHOLD = 200.0

FREQ_COLS = ["ProductCD", "card4", "card6", "P_emaildomain", "R_emaildomain",
             "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9"]
MODE_COLS = ["card4", "card6", "R_emaildomain"] + [f"M{i}" for i in range(1, 10)]
RAW_NUMERIC_EXTRA = ["card2", "card3", "card5", "addr1"]


# --- training constants -------------------------------------------------------
def build_constants(raw: pd.DataFrame, train_mask: np.ndarray) -> dict:
    """Reproduce the constants the training pipeline baked into the model.

    Frequencies and the 95th-percentile cut-off are computed on the full CSV,
    exactly as training/features.py did when the model was trained. The
    product-typical values used for fields the event lacks are a new lookup
    table, so they are fitted on the training rows only (no test information).
    """
    freqs = {}
    for col in FREQ_COLS:
        vc = raw[col].value_counts(dropna=False, normalize=True)
        freqs[col] = {(NAN_KEY if pd.isna(k) else str(k)): float(np.float32(v)) for k, v in vc.items()}
    q95 = float(raw["TransactionAmt"].astype("float32").quantile(0.95))
    train = raw[train_mask]
    modes = {}
    for col in MODE_COLS:
        modes[col] = {}
        for pc, s in train.groupby("ProductCD")[col]:
            top = s.value_counts(dropna=False).index[0]
            modes[col][str(pc)] = NAN_KEY if pd.isna(top) else str(top)
    return {"freqs": freqs, "high_amount_q95": q95, "product_modes": modes}


def save_constants(c: dict, path: Path) -> None:
    path.write_text(json.dumps(c, indent=2, sort_keys=True))


def load_constants(path: Path) -> dict:
    return json.loads(path.read_text())


# --- helpers ------------------------------------------------------------------
def _domain(merchant_name: pd.Series) -> pd.Series:
    """Same parsing as live_features._extract_email_domain."""
    s = merchant_name.fillna("").astype(str)
    has = s.str.contains("-MERCHANT-", regex=False)
    dom = s.str.split("-MERCHANT-", n=1).str[1].fillna("").str.strip().str.lower()
    dom = dom.where(has & (dom != ""), "missing")
    return dom


def _freq(values: pd.Series, table: dict) -> pd.Series:
    """Map raw category values (NaN allowed) to training frequencies.
    A value never seen in training gets the rarest training frequency."""
    rare = min(table.values())
    keys = values.astype(object).where(values.notna(), NAN_KEY).astype(str)
    return keys.map(table).fillna(rare).astype("float64")


def _product_mode(product: pd.Series, col: str, c: dict) -> pd.Series:
    """Most common training value of `col` for each row's product type (NaN if that is 'missing')."""
    m = product.map(c["product_modes"][col])
    return m.where(m != NAN_KEY, np.nan)


# --- main entry point -----------------------------------------------------------
def featurize_frame(events: pd.DataFrame, feature_names: list[str], constants: dict | None = None,
                    fixes: tuple[str, ...] = (), extra: pd.DataFrame | None = None
                    ) -> tuple[pd.DataFrame, np.ndarray]:
    """Featurise many events at once. Returns (X float32 in model column order, completeness)."""
    fixes = set(fixes)
    unknown = fixes - set(CODE_FIXES)
    if unknown:
        raise ValueError(f"unknown fixes: {sorted(unknown)}")
    if (fixes or extra is not None) and constants is None:
        raise ValueError("fixes need the training constants")
    n = len(events)
    idx = events.index

    amount = pd.to_numeric(events["amount"], errors="coerce").fillna(0.0).astype("float64")
    ts = pd.to_numeric(events["event_timestamp_ms"], errors="coerce").fillna(0).astype("int64")
    mcc = events["mcc"].fillna("").astype(str)
    country = events["merchant_country"].fillna("00").astype(str).replace("", "00")
    product = mcc.map(MCC_TO_PRODUCTCD).fillna("S")
    dom = _domain(events["merchant_name"])

    # time (unchanged - already matches training)
    dt = pd.to_datetime(ts, unit="ms", utc=True)
    hour = dt.dt.hour.astype("float64").where(ts > 0, SENTINEL)
    dow = dt.dt.weekday.astype("float64").where(ts > 0, SENTINEL)
    is_night = ((hour < 6) | (hour >= 22)).astype("float64").where(ts > 0, SENTINEL)
    is_weekend = (dow >= 5).astype("float64").where(ts > 0, SENTINEL)

    # amount
    if "cents" in fixes:
        a32 = amount.astype("float32")
        log_amount = np.log1p(a32).astype("float64")
        cents = ((a32 * 100) % 100).astype("int16").astype("float64")
    else:
        log_amount = np.log1p(amount)
        cents = (np.round(amount * 100).astype("int64") % 100).astype("float64")
    is_round = (cents == 0).astype("float64")
    if "high_amount" in fixes:
        is_high = (amount.astype("float32") > np.float32(constants["high_amount_q95"])).astype("float64")
    else:
        is_high = (amount > ORIG_HIGH_AMOUNT_THRESHOLD).astype("float64")

    # purchaser email
    p_raw = dom.where(~dom.isin(["nan", "missing"]), np.nan)  # NaN = missing in training terms
    if "freq_tables" in fixes:
        product_freq = _freq(product, constants["freqs"]["ProductCD"])
        p_freq = _freq(p_raw, constants["freqs"]["P_emaildomain"])
    else:
        product_freq = product.map(ORIG_PRODUCTCD_FREQS).fillna(0.0143)
        p_freq = dom.map(ORIG_EMAIL_DOMAIN_FREQS).fillna(ORIG_EMAIL_DOMAIN_DEFAULT)
    if "p_missing" in fixes:
        p_missing = p_raw.isna().astype("float64")
    else:
        p_missing = dom.isin(["missing", "nan", "anonymous.com"]).astype("float64")

    # recipient email (not in the event): actual value if the richer event has it
    if extra is not None:
        r_raw = extra["R_emaildomain"]
    elif "email" in fixes:
        r_raw = _product_mode(product, "R_emaildomain", constants)
    else:
        r_raw = None
    if r_raw is not None:
        p_cmp = p_raw.fillna("missing")
        r_cmp = r_raw.fillna("missing")
        email_mismatch = (p_cmp != r_cmp).astype("float64")
        r_missing = (r_cmp == "missing").astype("float64")
        r_freq = _freq(r_raw, constants["freqs"]["R_emaildomain"])
    else:
        email_mismatch = pd.Series(0.0, index=idx)
        r_missing = pd.Series(1.0, index=idx)
        r_freq = pd.Series(SENTINEL, index=idx)

    real = {
        "TransactionAmt": amount, "hour_of_day": hour, "day_of_week": dow,
        "is_night": is_night, "is_weekend": is_weekend, "log_amount": log_amount,
        "amount_cents": cents, "is_round_dollar": is_round, "is_high_amount": is_high,
        "ProductCD_freq": product_freq, "P_emaildomain_freq": p_freq,
        "p_email_missing": p_missing, "r_email_missing": r_missing,
        "email_mismatch": email_mismatch,
    }
    if r_raw is not None:
        real["R_emaildomain_freq"] = r_freq

    addr2 = pd.to_numeric(country, errors="coerce")
    if "addr2" in fixes:
        addr2 = addr2.where(country != "00", np.nan)
    real["addr2"] = addr2.fillna(SENTINEL)

    if "card1" in fixes:
        real["card1"] = pd.to_numeric(events["customer_id"], errors="coerce").fillna(SENTINEL)
    if extra is not None:
        real["dist1"] = pd.to_numeric(extra["dist1"], errors="coerce").fillna(SENTINEL)
        for col in RAW_NUMERIC_EXTRA:
            real[col] = pd.to_numeric(extra[col], errors="coerce").fillna(SENTINEL)
    elif "dist1" in fixes:
        geo = pd.to_numeric(events["geo_distance_km"], errors="coerce").fillna(0.0)
        real["dist1"] = geo.where(geo != 0.0, SENTINEL)

    for col in ["card4", "card6"] + [f"M{i}" for i in range(1, 10)]:
        if extra is not None:
            real[f"{col}_freq"] = _freq(extra[col], constants["freqs"][col])
        elif "never_seen" in fixes:
            real[f"{col}_freq"] = _freq(_product_mode(product, col, constants), constants["freqs"][col])

    cols = {}
    n_real = np.zeros(n)
    for name in feature_names:
        v = real.get(name)
        if v is None:
            cols[name] = np.full(n, SENTINEL)
        else:
            arr = np.asarray(v, dtype="float64")
            cols[name] = arr
            n_real += arr != SENTINEL
    X = pd.DataFrame(cols, columns=feature_names).astype("float32")
    return X, np.round(n_real / len(feature_names), 4)


def featurize_event(event: dict, feature_names: list[str], constants: dict,
                    fixes: tuple[str, ...] = CODE_FIXES) -> tuple[pd.DataFrame, float]:
    """Drop-in shape of the project's featurize_event (one event -> 1-row frame)."""
    X, comp = featurize_frame(pd.DataFrame([event]), feature_names, constants, fixes)
    return X, float(comp[0])

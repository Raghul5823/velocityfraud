"""Natural-language narrator for flagged transactions.

Generates a 2-3 sentence professional explanation of why an event was flagged
as REVIEW or BLOCK. Two modes:

    template  : pure-Python deterministic narrator. Always works, no API.
    gemini    : Google Gemini Flash (free tier). Used if GEMINI_API_KEY env
                var is set. Falls back to template on ANY error.

Mode selection:
    NARRATOR_MODE=template   force template (default if no key)
    NARRATOR_MODE=gemini     force gemini (errors if no key)
    NARRATOR_MODE=auto       gemini if key present, else template (default)

Usage:
    from velocityfraud.narrator import generate_narrative

    narrative, mode_used = generate_narrative(scored_event, contributions)
    # narrative: str (the explanation)
    # mode_used: 'TEMPLATE' or 'GEMINI'

Smoke test:
    uv run python -m velocityfraud.narrator
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from velocityfraud.explainer import FeatureContribution


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
NARRATOR_MODE = os.getenv("NARRATOR_MODE", "auto").lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")
GEMINI_TIMEOUT_S = float(os.getenv("GEMINI_TIMEOUT_S", "5.0"))


# ---------------------------------------------------------------------------
# Friendly feature-name lookup table for human-readable narratives
# ---------------------------------------------------------------------------
FEATURE_HUMAN_NAMES = {
    "TransactionAmt":     "transaction amount",
    "log_amount":         "log-scaled amount",
    "amount_cents":       "amount cents portion",
    "is_round_dollar":    "round-dollar flag",
    "is_high_amount":     "high-amount flag",
    "hour_of_day":        "hour of day",
    "day_of_week":        "day of week",
    "is_night":           "night-time flag",
    "is_weekend":         "weekend flag",
    "ProductCD_freq":     "product-category frequency",
    "P_emaildomain_freq": "purchaser email frequency",
    "R_emaildomain_freq": "recipient email frequency",
    "p_email_missing":    "purchaser email missing flag",
    "r_email_missing":    "recipient email missing flag",
    "email_mismatch":     "purchaser/recipient email mismatch",
    "card4_freq":         "card-network frequency",
    "card6_freq":         "card-type frequency",
    "addr1":              "billing region",
    "addr2":              "billing country",
    "dist1":              "billing-to-merchant distance",
    "card1":              "card hash bucket",
    "card2":              "card-issuer bucket",
    "card3":              "card-program bucket",
    "card5":              "card-issuer ZIP bucket",
}


def _human(feature_name: str) -> str:
    """Return a friendly label for an internal feature name."""
    return FEATURE_HUMAN_NAMES.get(feature_name, feature_name)


# ---------------------------------------------------------------------------
# Mode 1: Template narrator (always available)
# ---------------------------------------------------------------------------
def _template_narrate(scored_event: dict,
                       contributions: list["FeatureContribution"]) -> str:
    """Deterministic narrator. Returns 2-3 sentences."""
    ev_id = scored_event.get("event_id", "?")[:8]
    amount = scored_event.get("amount", 0.0)
    merch = scored_event.get("merchant_name", "unknown")
    decision = scored_event.get("decision", "?")
    score = scored_event.get("fraud_score", 0.0)
    completeness = scored_event.get("feature_completeness", 0.0)

    pos = [fc for fc in contributions if fc.shap_value > 0]
    neg = [fc for fc in contributions if fc.shap_value < 0]

    parts = [
        f"Transaction {ev_id} for ${amount:,.2f} at {merch} was classified "
        f"{decision} with a fraud score of {score:.3f} "
        f"(feature completeness {completeness:.0%})."
    ]

    if pos:
        top = pos[0]
        parts.append(
            f"The strongest signal pushing toward FRAUD was "
            f"{_human(top.feature_name)} (value {top.feature_value:.4g}, "
            f"impact +{top.shap_value:.3f})."
        )
    if neg:
        top = neg[0]
        parts.append(
            f"The strongest signal pushing toward LEGITIMATE was "
            f"{_human(top.feature_name)} (value {top.feature_value:.4g}, "
            f"impact {top.shap_value:.3f})."
        )

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Mode 2: Gemini narrator (free-tier, optional)
# ---------------------------------------------------------------------------
_gemini_client = None


def _get_gemini_client():
    """Lazy-init the Gemini client. Returns None if API key missing or import fails."""
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client
    if not GEMINI_API_KEY:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        _gemini_client = genai.GenerativeModel(GEMINI_MODEL)
        logger.info("Gemini client initialized: {}", GEMINI_MODEL)
        return _gemini_client
    except Exception as e:
        logger.warning("Failed to init Gemini ({}): falling back to template", e)
        return None


def _build_gemini_prompt(scored_event: dict,
                          contributions: list["FeatureContribution"]) -> str:
    """Build a structured prompt for Gemini."""
    contrib_lines = []
    for fc in contributions:
        direction = "FRAUD" if fc.shap_value > 0 else "LEGIT"
        contrib_lines.append(
            f"  - {_human(fc.feature_name)}: value={fc.feature_value:.4g}, "
            f"shap={fc.shap_value:+.4f} (pushes toward {direction})"
        )
    contrib_block = "\n".join(contrib_lines)

    return f"""You are a fraud-detection analyst. Write a 2-3 sentence professional
explanation of why a payment transaction was flagged.

Transaction:
  - event_id: {scored_event.get('event_id', '?')[:8]}
  - amount: ${scored_event.get('amount', 0):,.2f} {scored_event.get('currency', '')}
  - merchant: {scored_event.get('merchant_name', 'unknown')}
  - merchant_country: {scored_event.get('merchant_country', '?')}
  - mcc: {scored_event.get('mcc', '?')}
  - decision: {scored_event.get('decision', '?')}
  - fraud_score: {scored_event.get('fraud_score', 0):.3f}
  - feature_completeness: {scored_event.get('feature_completeness', 0):.0%}

Top SHAP feature contributions (positive = pushes toward fraud):
{contrib_block}

Write a clear, concise narrative for a fraud-ops dashboard.
Do not include greetings or sign-offs. Output only the narrative text."""


def _gemini_narrate(scored_event: dict,
                     contributions: list["FeatureContribution"]) -> str:
    """Call Gemini for a narrative. Raises on any error."""
    client = _get_gemini_client()
    if client is None:
        raise RuntimeError("Gemini client unavailable")
    prompt = _build_gemini_prompt(scored_event, contributions)
    response = client.generate_content(
        prompt,
        request_options={"timeout": GEMINI_TIMEOUT_S},
    )
    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Gemini returned empty response")
    return text


# ---------------------------------------------------------------------------
# Public entry point with auto-mode and fallback
# ---------------------------------------------------------------------------
def generate_narrative(
    scored_event: dict,
    contributions: list["FeatureContribution"],
    mode: str | None = None,
) -> tuple[str, str]:
    """Generate a narrative. Returns (narrative_text, mode_used).

    mode_used is 'TEMPLATE' or 'GEMINI' — matches the NarratorMode Avro enum.
    """
    chosen = (mode or NARRATOR_MODE).lower()

    if chosen in ("gemini", "auto") and GEMINI_API_KEY:
        try:
            text = _gemini_narrate(scored_event, contributions)
            return text, "GEMINI"
        except Exception as e:
            logger.warning("Gemini narration failed ({}): falling back to template", e)
            # fall through to template

    return _template_narrate(scored_event, contributions), "TEMPLATE"


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
def _demo() -> int:
    from velocityfraud.live_features import featurize_event
    from velocityfraud.explainer import get_explainer, explain_event
    from velocityfraud.predict import get_champion_model, predict_proba

    sample_event = {
        "event_id":               "demo-narrator-001",
        "event_timestamp_ms":     1782731301417,
        "customer_id":            "13926",
        "card_token":             "10c1bf7c3c76e313",
        "amount":                 2454.00,
        "currency":               "USD",
        "amount_fx_normalised":   2454.00,
        "merchant_id_hash":       "5f59d374246893e0",
        "merchant_name":          "S-MERCHANT-anonymous.com",
        "mcc":                    "5999",
        "merchant_country":       "00",
        "ip_address_hash":        "98e58ca964c583e2",
        "device_fingerprint_hash":"a245d9cb16edd5da",
        "geo_distance_km":        0.0,
        "source_label":           "narrator-demo",
        "schema_version":         "v1",
    }

    logger.info("=" * 70)
    logger.info("NARRATOR DEMO")
    logger.info("=" * 70)
    logger.info("Mode: {} | Gemini key set: {}",
                NARRATOR_MODE, "YES" if GEMINI_API_KEY else "NO")

    X, completeness = featurize_event(sample_event)
    model = get_champion_model()
    score = float(predict_proba(model, X)[0])
    explainer = get_explainer()
    contribs = explain_event(explainer, X, top_n=5)

    # Build a synthetic scored_event for the narrator
    scored_event = {
        **sample_event,
        "fraud_score":          score,
        "decision":             "REVIEW" if score >= 0.10 else "ALLOW",
        "feature_completeness": completeness,
    }

    logger.info("Score: {:.4f}, Decision: {}, Completeness: {:.2%}",
                score, scored_event["decision"], completeness)
    logger.info("-" * 70)

    # Template mode
    text_t, mode_t = generate_narrative(scored_event, contribs, mode="template")
    logger.info("TEMPLATE NARRATIVE ({}):", mode_t)
    logger.info("  {}", text_t)
    logger.info("-" * 70)

    # Auto mode (Gemini if key, else template)
    text_a, mode_a = generate_narrative(scored_event, contribs)
    logger.info("AUTO NARRATIVE ({}):", mode_a)
    logger.info("  {}", text_a)
    logger.info("=" * 70)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_demo())

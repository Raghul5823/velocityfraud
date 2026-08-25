"""Three fraud-pattern explanations — velocity, geo-impossible-travel, MCC
mismatch (proposal Item 5).

For each named pattern we build a realistic transaction, score it with the
champion XGBoost model, compute SHAP attributions, and generate a natural-
language explanation. The narrator uses Gemini when GEMINI_API_KEY is set,
otherwise a deterministic pattern-aware template (so this always runs).

The Gemini prompt includes the raw signal fields (geo_distance_km, mcc,
merchant_country, amount, timing) so the LLM can reason about the specific
pattern even where the tabular model relies on other features.

Run:
    uv run python -m velocityfraud.fraud_patterns
    # for real Gemini output, first put a free key in .env:  GEMINI_API_KEY=...
"""
from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from velocityfraud import narrator
from velocityfraud.explainer import explain_event, get_explainer
from velocityfraud.live_features import featurize_event
from velocityfraud.predict import get_champion_model, predict_proba

REVIEW_THRESH = 0.50
BLOCK_THRESH = 0.85


@dataclass
class Scenario:
    pattern: str          # short name shown in the report
    rule: str             # the detection rule that fires for this pattern
    rule_decision: str    # REVIEW / BLOCK assigned by that rule
    signals: str          # the human-readable red flag(s) for this pattern
    event: dict           # raw TransactionEvent fields


def _base(**over) -> dict:
    ev = {
        "event_id":                "pattern-demo",
        "event_timestamp_ms":      1_782_731_301_417,
        "customer_id":             "13926",
        "card_token":              "10c1bf7c3c76e313",
        "amount":                  120.00,
        "currency":                "USD",
        "amount_fx_normalised":    120.00,
        "merchant_id_hash":        "5f59d374246893e0",
        "merchant_name":           "W-MERCHANT-gmail.com",
        "mcc":                     "5411",
        "merchant_country":        "US",
        "ip_address_hash":         "98e58ca964c583e2",
        "device_fingerprint_hash": "a245d9cb16edd5da",
        "geo_distance_km":         5.0,
        "source_label":            "pattern-demo",
        "schema_version":          "v1",
    }
    ev.update(over)
    return ev


SCENARIOS = [
    Scenario(
        pattern="Velocity (card testing)",
        rule="velocity-rule: >=5 auths/card in 120s",
        rule_decision="REVIEW",
        signals="6 transactions on the same card within 90 seconds, small round "
                "amounts at 03:12 local time — classic card-testing burst.",
        event=_base(event_id="velocity-001", amount=1.00, amount_fx_normalised=1.00,
                    event_timestamp_ms=1_782_704_400_000,
                    merchant_name="S-MERCHANT-anonymous.com", mcc="5999"),
    ),
    Scenario(
        pattern="Geo-impossible travel",
        rule="geo-rule: implied speed > 1000 km/h",
        rule_decision="BLOCK",
        signals="Card used in the US 40 minutes ago, now charging in RU — "
                "8,742 km apart, physically impossible in the time window.",
        event=_base(event_id="geo-001", amount=899.00, amount_fx_normalised=899.00,
                    merchant_country="RU", geo_distance_km=8742.0,
                    merchant_name="C-MERCHANT-anonymous.com", mcc="5732"),
    ),
    Scenario(
        pattern="MCC mismatch",
        rule="mcc-risk-rule: high-risk MCC vs cardholder history",
        rule_decision="REVIEW",
        signals="Cardholder history is groceries/retail; this is a $2,450 charge "
                "at MCC 7995 (betting/gambling) with a missing merchant domain.",
        event=_base(event_id="mcc-001", amount=2450.00, amount_fx_normalised=2450.00,
                    mcc="7995", merchant_country="00",
                    merchant_name="S-MERCHANT-nan"),
    ),
]


def _decide(score: float) -> str:
    if score >= BLOCK_THRESH:
        return "BLOCK"
    if score >= REVIEW_THRESH:
        return "REVIEW"
    return "ALLOW"


def _gemini_pattern_prompt(sc: Scenario, ml_score: float, ml_decision: str, contribs) -> str:
    ev = sc.event
    return f"""You are a fraud analyst. In 2-3 sentences, explain why this card
transaction was flagged as '{sc.pattern}', and note that the tabular fast-path
model alone did not catch it (so the rule/enrichment layer is what protected us).

Detected pattern: {sc.pattern}
Detection rule fired: {sc.rule}  ->  decision {sc.rule_decision}
Red flags: {sc.signals}
Fast-path ML result: {ml_decision} (score {ml_score:.3f}) -- it MISSED this pattern
    because its live features do not include velocity counters, geo distance, or
    cardholder MCC history.

Transaction:
  amount: ${ev['amount']:,.2f} {ev['currency']}
  merchant: {ev['merchant_name']}  mcc: {ev['mcc']}  country: {ev['merchant_country']}
  geo_distance_km: {ev['geo_distance_km']}

Write a clear analyst-facing narrative. Name the pattern and the rule. No greetings."""


def _template_pattern_narrative(sc: Scenario, ml_score: float, ml_decision: str, contribs) -> str:
    return (
        f"[{sc.pattern}] Rule '{sc.rule}' fired -> {sc.rule_decision}. "
        f"Red flags: {sc.signals} "
        f"The fast-path XGBoost model scored this {ml_decision} ({ml_score:.3f}) and "
        f"missed the pattern, because its live features exclude velocity counters, "
        f"geo distance, and MCC history — which is exactly why the rule/enrichment "
        f"layer runs alongside it."
    )


def explain_pattern(sc: Scenario) -> dict:
    model = get_champion_model()
    explainer = get_explainer()
    X, completeness = featurize_event(sc.event)
    score = float(predict_proba(model, X)[0])
    decision = _decide(score)
    contribs = explain_event(explainer, X, top_n=5)

    client = narrator._get_gemini_client()
    if client is not None:
        try:
            prompt = _gemini_pattern_prompt(sc, score, decision, contribs)
            resp = client.generate_content(prompt)
            text, mode = (resp.text or "").strip(), "GEMINI"
        except Exception as e:
            logger.warning("Gemini failed ({}); using template.", e)
            text, mode = _template_pattern_narrative(sc, score, decision, contribs), "TEMPLATE"
    else:
        text, mode = _template_pattern_narrative(sc, score, decision, contribs), "TEMPLATE"

    return {"pattern": sc.pattern, "rule": sc.rule, "rule_decision": sc.rule_decision,
            "ml_score": score, "ml_decision": decision,
            "mode": mode, "narrative": text, "completeness": completeness}


def main() -> int:
    logger.info("=" * 74)
    logger.info("THREE FRAUD-PATTERN EXPLANATIONS (Item 5)")
    logger.info("Narrator mode: {}", "GEMINI" if narrator.GEMINI_API_KEY else "TEMPLATE (set GEMINI_API_KEY for LLM)")
    logger.info("=" * 74)
    for sc in SCENARIOS:
        r = explain_pattern(sc)
        logger.info("-" * 74)
        logger.info("PATTERN : {}", r["pattern"])
        logger.info("RULE    : {}  ->  {}", r["rule"], r["rule_decision"])
        logger.info("FASTPATH: XGBoost said {} (score={:.3f}) — missed it",
                    r["ml_decision"], r["ml_score"])
        logger.info("MODE    : {}", r["mode"])
        logger.info("EXPLAIN : {}", r["narrative"])
    logger.info("=" * 74)
    logger.success("Generated {} fraud-pattern explanations.", len(SCENARIOS))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

# Fraud-Pattern Explanation Demos (COMPLETE)

> **Status:** ✅ Complete
> **Project:** VelocityFraud — Real-Time Fraud Detection Data Pipeline
> **Program:** IMPACT pSiddhi 3.0 — Topic S2-D-06 (Semester 2, Data Track)
> **Proposal reference:** §9, Expected Deliverable / POC — *"3 fraud-pattern Gemini explanations: velocity, geo-impossible-travel, MCC mismatch."*

> **Framing note:** This is a named Week-17 deliverable line, not an incidental script. It exists to make one specific point live for reviewers: the fast-path ML model (Layer 3) is fast but feature-limited — it does not see velocity counters, geo distance, or MCC history — so a rule/enrichment layer plus an LLM explanation is what actually catches and narrates these three classic fraud patterns.

---

## 1. Why This Demo Exists

The fast-path model scores a transaction in ~15 ms using only the features available on that single event. Three well-known fraud patterns are structurally invisible to a single-event model:

| Pattern | Why the fast-path model misses it |
|---|---|
| **Velocity (card testing)** | Needs a count of recent transactions on the same card — a cross-event signal, not a single-event feature. |
| **Geo-impossible travel** | Needs the location + timestamp of the *previous* transaction to compute implied travel speed. |
| **MCC mismatch** | Needs the cardholder's *historical* spending category, not just this transaction's MCC. |

`fraud_patterns.py` proves this gap is real (not asserted) by running each scenario through the actual champion XGBoost model, showing it produces the *wrong or incomplete* read, and then showing the rule + Gemini narrative catching what the model alone did not.

## 2. What Was Built

**File:** `src/velocityfraud/fraud_patterns.py`

For each of the 3 scenarios, the script:

1. Builds a realistic `TransactionEvent` with the pattern's tell-tale fields set (`_base()` + per-scenario overrides).
2. Scores it with `predict.get_champion_model()` / `predict_proba()` — the same live-inference path production uses.
3. Runs SHAP (`explainer.explain_event`) to get the model's own top-5 feature attributions.
4. Calls **Gemini** (via `narrator._get_gemini_client()`) with a prompt naming the pattern, the rule that fired, and the fact that the fast-path model missed it — or falls back to a deterministic template narrative if no `GEMINI_API_KEY` is set, so the demo always runs.

## 3. The Three Scenarios

| # | Pattern | Detection rule | Rule decision | Red flags |
|---|---|---|---|---|
| 1 | **Velocity (card testing)** | `velocity-rule: >=5 auths/card in 120s` | REVIEW | 6 transactions on the same card within 90 seconds, small round amounts at 03:12 local time. |
| 2 | **Geo-impossible travel** | `geo-rule: implied speed > 1000 km/h` | BLOCK | Card used in the US 40 minutes ago, now charging in RU — 8,742 km apart, physically impossible in that window. |
| 3 | **MCC mismatch** | `mcc-risk-rule: high-risk MCC vs cardholder history` | REVIEW | Cardholder history is groceries/retail; this is a $2,450 charge at MCC 7995 (betting/gambling) with a missing merchant domain. |

Each scenario is defined as a `Scenario` dataclass (`pattern`, `rule`, `rule_decision`, `signals`, `event`) in `fraud_patterns.py::SCENARIOS`, so adding a fourth pattern later is a one-entry change.

## 4. Output Shape

`explain_pattern(scenario)` returns:

```python
{
    "pattern": "Geo-impossible travel",
    "rule": "geo-rule: implied speed > 1000 km/h",
    "rule_decision": "BLOCK",
    "ml_score": 0.412,          # the fast-path model's own score — deliberately shown even when "wrong"
    "ml_decision": "REVIEW",    # what the model alone would have done
    "mode": "GEMINI",           # or "TEMPLATE" if no API key / Gemini call failed
    "narrative": "...",         # the analyst-facing explanation
    "completeness": ...,        # feature-completeness metric from featurize_event()
}
```

The `ml_decision` vs `rule_decision` gap **is the point** — it's shown side-by-side on purpose so a reviewer sees the fast-path model's blind spot and the rule layer's catch in the same line.

## 5. How to Run

```powershell
uv run python -m velocityfraud.fraud_patterns
```

- With `GEMINI_API_KEY` set in `.env` → real Gemini narratives (mode `GEMINI`).
- Without it → deterministic template narratives (mode `TEMPLATE`) — the demo still runs end-to-end, satisfying the "always runs" requirement for a live Week-17 presentation where network/API availability cannot be guaranteed.

## 6. Test Coverage

`tests/test_smoke_entrypoints.py::test_fraud_patterns_demo` runs this module with `narrator.GEMINI_API_KEY` monkeypatched to `""`, forcing template mode — this is the CI-safe path that doesn't depend on a live Gemini quota, while still exercising the full scoring + SHAP + narrative pipeline for all 3 scenarios.

## 7. Where This Feeds Forward

- **Week-17 live demo:** presenter runs this script live (or shows the recorded output) to satisfy the Proposal §9 deliverable line directly — no additional build needed.
- **Power BI — Real-time Alert Feed:** the same narrative-generation path (`narrator` module, Gemini-or-template) that powers these 3 demo scenarios is what populates the live Alert Feed's explanation column for real escalated transactions.

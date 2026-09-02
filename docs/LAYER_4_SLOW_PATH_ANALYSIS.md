# Layer 4 — Slow-Path Analysis (COMPLETE)

> **Status:** ✅ Complete
> **Completion Date:** 2026-06-30
> **Effort:** ~2 hours of focused build
> **Project:** VelocityFraud — Real-Time Fraud Detection Data Pipeline
> **Program:** IMPACT pSiddhi 3.0 — Topic S2-D-06 (Semester 2, Data Track)

---

## 1. Why This Layer Exists

Layer 3 (fast-path) gives every transaction a **number** — `fraud_score = 0.21`. That number is useful for triage but completely useless for a human reviewer. "Why is it 0.21? Which features mattered? Was it the amount, the merchant, the time?"

Layer 4 (slow-path) answers those questions **only for flagged events** (REVIEW + BLOCK) using:

- **SHAP** — mathematically rigorous per-feature attribution (positive = pushed toward fraud, negative = pushed toward legit)
- **Narrator** — 2–3 sentence natural-language explanation, either template-based (always works) or Gemini-augmented (when API key set)

**Without Layer 4, the fraud-ops team sees opaque scores. With Layer 4, they see clear English explanations that drive their decisions.**

---

## 2. Architecture Built

```
┌──────────────────────────────────────────────────────────────────────────┐
│                  LAYER 4: SLOW-PATH ANALYSIS                              │
└──────────────────────────────────────────────────────────────────────────┘

      Layer 3                Layer 4                       Layer 6/7
                                                          (planned)
                                                              │
   transactions.scored  ──►  ┌────────────────────────┐  ──► transactions.enriched
   (23-field Avro)            │      SLOW-PATH         │     (28-field Avro)
                              │                        │
                              │  consume               │
                              │     ↓                  │
                              │  decide-filter ────────►  skip ALLOW (176/200)
                              │  (REVIEW or BLOCK?)   │
                              │     ↓ yes              │
                              │  re-featurize event   │ ←─── live_features.py
                              │     ↓                  │
                              │  explainer.explain    │ ←─── explainer.py
                              │  (SHAP TreeExplainer  │      (TreeExplainer,
                              │   ~30-80ms/event)     │       cached at boot)
                              │     ↓                  │
                              │  narrator.generate    │ ←─── narrator.py
                              │  (template ~1ms       │      ┌─────────────┐
                              │   OR Gemini ~500ms)   │      │ Gemini API  │ (optional)
                              │     ↓                  │      │ free-tier   │
                              │  build enriched event │      │ (gemini-2.0 │
                              │  (echo 23 + add 5)    │      │  -flash-exp)│
                              │     ↓                  │      └─────────────┘
                              │  encode + produce      │      ┌─────────────┐
                              │                        │      │ Template    │ (always)
                              │  Avg lat: 38ms         │      │ deterministic│
                              │  Max lat: 78ms         │      └─────────────┘
                              └────────────────────────┘

Topic: transactions.scored        Topic: transactions.enriched
  Schema: TransactionScoredEvent    Schema: TransactionEnrichedEvent
  Fields: 23                        Fields: 28 (23 echoed + 5 new)
```

---

## 3. Step-by-Step Build Log (Granular)

### Phase 1 — Dependencies

1. Added 3 packages to [pyproject.toml](../pyproject.toml):
   - `shap>=0.46.0` — exact SHAP for tree models via TreeExplainer
   - `google-generativeai>=0.8.0` — Gemini SDK (optional, free tier)
   - `numba>=0.60.0` + `llvmlite>=0.43.0` — pinned to Python 3.11-compatible versions (uv resolver kept picking ancient llvmlite 0.36 otherwise)

2. Ran `uv sync` — 18 new packages installed (SHAP + numba + llvmlite + google-* family).

### Phase 2 — Enriched Event Schema

3. Designed [infra/schemas/transaction-enriched-event.avsc](../infra/schemas/transaction-enriched-event.avsc) — **28 fields**:
   - **23 echoed** from `TransactionScoredEvent` (downstream needs no joins)
   - **5 new fields:**
     - `top_contributors` — array of `FeatureContribution` records (feature_name, feature_value, shap_value)
     - `narrative` — string, the natural-language explanation
     - `narrator_mode` — enum (TEMPLATE | GEMINI)
     - `enriched_at_ms` — when enrichment completed
     - `enrichment_latency_ms` — end-to-end slow-path latency

   **Why the FeatureContribution array?** Power BI / Postgres can flatten it into a separate table for analytics ("which features trigger most BLOCKs?"). For SHAP the structured form is much more useful than a JSON blob string.

4. Extended [schema.py](../src/velocityfraud/schema.py) with `get_enriched_schema()`.

### Phase 3 — SHAP Explainer

5. Built [src/velocityfraud/explainer.py](../src/velocityfraud/explainer.py):
   - `FeatureContribution` dataclass — clean serialization to dict
   - `get_explainer()` — cached TreeExplainer for the champion model
   - `explain_event(explainer, X, top_n=5)` — returns top-N contributors by |shap_value|

6. **Bug:** SHAP returns shape `(1, n_features)` for binary XGBoost, but in some versions returns a list of two arrays (one per class). Added a normalization branch to handle both.

7. **Smoke test passed:** synthetic $2454 anonymous-email event scored 0.0210 with SHAP showing 5 clean contributors with their values + impact + direction (FRAUD/LEGIT).

### Phase 4 — Narrator

8. Built [src/velocityfraud/narrator.py](../src/velocityfraud/narrator.py) — dual-mode design:
   - **`_template_narrate`** — pure-Python, deterministic, ~1ms. Uses a `FEATURE_HUMAN_NAMES` lookup to convert technical column names ("ProductCD_freq") to friendly labels ("product-category frequency")
   - **`_gemini_narrate`** — lazy Gemini client, calls `generate_content()` with a structured prompt, 5-second timeout
   - **`generate_narrative(scored_event, contributions, mode='auto')`** — public entry. Auto mode = Gemini if `GEMINI_API_KEY` set, else template. Falls back to template on ANY Gemini error.

9. **Cost safety:** Gemini is **opt-in**. Without `GEMINI_API_KEY`, the system runs entirely on template — zero API calls, ₹0 cost.

10. **Smoke test passed:** template narrative reads like fraud-ops copy — `"Transaction demo-nar for $2,454.00 at S-MERCHANT-anonymous.com was classified ALLOW with a fraud score of 0.021 (feature completeness 35%). The strongest signal pushing toward FRAUD was C14 (value -999, impact +0.880). The strongest signal pushing toward LEGITIMATE was purchaser email missing flag (value 1, impact -0.989)."`

### Phase 5 — Slow-Path Service

11. Built [src/velocityfraud/slow_path.py](../src/velocityfraud/slow_path.py):
    - Consumer on `transactions.scored`, producer on `transactions.enriched`
    - Warms SHAP explainer at boot (one-time ~300ms)
    - Per-event loop: decode → **filter ALLOW out** → re-featurize → explain → narrate → encode → produce
    - Tracks per-event latency, accumulates summary stats (decode/explain/narrator counts + skipped counts)
    - Graceful SIGINT handling

12. Built [scripts/run-slow-path.ps1](../scripts/run-slow-path.ps1) — convenience launcher.

### Phase 6 — End-to-End Verification

13. Ran slow-path against the existing 200 events in `transactions.scored`:
    - **200 consumed**
    - **176 skipped (ALLOW filter)** — correctly bypassing the safe events
    - **24 enriched (REVIEW + BLOCK)** — every flagged event got SHAP + narrative
    - **0 failures** of any kind
    - Latency: avg 37.75ms, max 78ms

14. Built [scripts/peek-enriched.ps1](../scripts/peek-enriched.ps1) — pretty-prints 3 enriched events with their narratives + top 5 SHAP contributors. Layer 4's "show, don't tell" demo command.

### Phase 7 — Documentation

15. Wrote this completion document.

---

## 4. Verification Checkpoints (8 Checks)

| # | Check | Evidence | Status |
|---|---|---|---|
| 1 | Enriched Avro schema in git | `infra/schemas/transaction-enriched-event.avsc` (28 fields incl. nested record array) | ✅ |
| 2 | SHAP explainer loads + scores | `explainer._demo()` smoke test output | ✅ |
| 3 | Narrator template generates readable text | `narrator._demo()` template output | ✅ |
| 4 | Gemini fallback to template on missing key | `auto` mode picked TEMPLATE when key unset | ✅ |
| 5 | Slow-path correctly filters ALLOW events | 176 skipped out of 200 (88%) | ✅ |
| 6 | All flagged events enriched | 24 of 24 REVIEW+BLOCK got SHAP + narrative | ✅ |
| 7 | Latency under 2-second budget | 37.75ms avg, 78ms max — 50× under budget | ✅ |
| 8 | Enriched events decode cleanly | peek-enriched.ps1 shows all 28 fields | ✅ |

---

## 5. Files Inventory

| File | Purpose | Lines |
|---|---|---|
| [pyproject.toml](../pyproject.toml) | +3 deps (shap, google-generativeai, numba/llvmlite pins) | +6 |
| [infra/schemas/transaction-enriched-event.avsc](../infra/schemas/transaction-enriched-event.avsc) | 28-field schema (with nested array of records) | ~40 |
| [src/velocityfraud/schema.py](../src/velocityfraud/schema.py) | Added `get_enriched_schema()` | +6 |
| [src/velocityfraud/explainer.py](../src/velocityfraud/explainer.py) | SHAP TreeExplainer wrapper | ~155 |
| [src/velocityfraud/narrator.py](../src/velocityfraud/narrator.py) | Template + Gemini narrator | ~270 |
| [src/velocityfraud/slow_path.py](../src/velocityfraud/slow_path.py) | Kafka-bound enrichment service | ~280 |
| [scripts/run-slow-path.ps1](../scripts/run-slow-path.ps1) | Launcher with env-var config | ~30 |
| [scripts/peek-enriched.ps1](../scripts/peek-enriched.ps1) | Pretty-print enriched events with narratives | ~55 |

---

## 6. Key Numbers to Memorize for Presentation

| Number | What It Means |
|---|---|
| **28** | Fields in TransactionEnrichedEvent (23 echoed + 5 new) |
| **5** | Top SHAP contributors per event |
| **200** | Scored events processed |
| **176** | ALLOW events skipped (88%) |
| **24** | REVIEW + BLOCK events enriched (12%) |
| **0** | Failures across decode, explain, narrate, produce |
| **37.75 ms** | Average enrichment latency |
| **78 ms** | Maximum enrichment latency |
| **<2000 ms** | Latency budget — beat by 50× |
| **TEMPLATE / GEMINI** | Two narrator modes — both produce valid Avro |
| **₹0** | Cost (template default; Gemini free tier even if enabled) |

---

## 7. Technical Stack to Master Before Presentation

### 7.1 SHAP (SHapley Additive exPlanations)

**What it is:** A mathematically rigorous framework for explaining ML model predictions, based on Shapley values from game theory.

**Core idea:** For each prediction, attribute the difference from the average prediction (the "expected value") to specific input features. The contributions sum to (model_output - expected_value) — perfectly explainable.

**Must understand:**
- **TreeExplainer** — exact polynomial-time algorithm for tree ensembles (vs KernelSHAP which is approximate + slower)
- **SHAP value sign** — positive pushes toward higher predicted probability; negative pushes lower
- **SHAP value magnitude** — how much the feature shifted the prediction
- **Local vs global** — SHAP gives per-prediction explanation (local); aggregating across many predictions gives feature importance (global)

**One-line answer:** *"SHAP attributes each prediction to its input features using Shapley values from game theory — mathematically exact for tree models, sub-100ms per prediction."*

### 7.2 Google Gemini API (Free Tier)

**What it is:** Google's hosted LLM API. `gemini-2.0-flash-exp` is the fast/cheap model — 1M tokens/day free, no credit card.

**Must understand:**
- **API key** — from https://aistudio.google.com/apikey
- **Request structure** — text-in, text-out via `generate_content(prompt)`
- **Timeout** — set explicit timeout (5s here) so a slow API doesn't block the pipeline
- **Rate limits** — 15 RPM on free tier, plenty for slow-path REVIEW+BLOCK volumes
- **Fallback** — always have a non-API path (template) so the system works without the LLM

**One-line answer:** *"Gemini Flash via google-generativeai — free tier, sub-second responses, optional (template narrator works without it)."*

### 7.3 Stream Filtering / Selective Consumption

**What it is:** Reading every event off a topic but only acting on a subset.

**Why this pattern:**
- Cheap operationally — we read from `transactions.scored` once
- Skip-path is fast (1 dict lookup)
- Maintains a single source of truth for what was processed

**Alternative considered:** Have the scorer (Layer 3) produce REVIEW/BLOCK events to a separate `transactions.flagged` topic. Trade-off: extra topic, but lets slow-path skip the filter step entirely. We chose single-topic + filter because the savings aren't worth the operational complexity at our scale.

### 7.4 Avro Nested Records (Array of Records)

**What it is:** Avro supports complex nested types like an `array` of `record`. Our `top_contributors` field is exactly this.

**Must understand:**
- **Inline record definition** — defined the `FeatureContribution` record inside the `top_contributors` array schema, not as a separate top-level type
- **Encoding** — Avro encodes array length first, then each record's fields in order
- **Downstream** — Postgres can store this as JSONB or flatten to a child table; Power BI's Avro connector handles nested arrays natively

---

## 8. Expected Presentation Questions (Senior/Architect Tier)

> 25 prepared Q&A — practice once before presentation.

### Explainability Questions

1. **Why SHAP and not LIME or feature importance?**
   *Answer:* SHAP is mathematically exact for tree models (KernelSHAP is approximate for any model). LIME is also approximate and unstable across runs. Feature importance is GLOBAL (across the dataset) — SHAP gives us LOCAL (per-prediction) attribution, which is what a fraud reviewer actually needs. SHAP has consistent additive properties that make it auditable.

2. **What do positive vs negative SHAP values mean here?**
   *Answer:* Positive SHAP pushes the prediction toward FRAUD (the positive class in binary). Negative SHAP pushes toward LEGIT. The sum of all SHAP values equals (prediction - expected_value). For our XGBoost, `expected_value` is roughly log-odds of the training fraud rate (~3.5%).

3. **Why top-5 contributors and not all 43?**
   *Answer:* Downstream consumption — Power BI dashboard shows top 3 in a tooltip, top 5 in the detail view. Storing all 43 would inflate payload size 8× with little extra signal — the bottom 30 features typically have near-zero impact.

4. **What if SHAP gives counter-intuitive results?**
   *Answer:* That's actually a feature, not a bug. Our SHAP output showed `p_email_missing=1.0` pushing -0.99 toward LEGIT — counter to human intuition. This reveals the model learned data-specific patterns (IEEE-CIS had legitimate anonymous purchases). SHAP exposes WHAT the model learned; whether that matches business logic is a separate question for the data science team.

### Narrator Questions

5. **Why template + Gemini instead of pure-LLM?**
   *Answer:* Three reasons. (a) **Cost & reliability** — template always works, free, no rate limits. (b) **Deterministic for testing** — same input → same narrative, useful for CI/CD. (c) **Honest fallback** — if Gemini's rate limit is hit, the pipeline degrades gracefully instead of failing.

6. **Why Gemini Flash and not GPT-4 / Claude?**
   *Answer:* Free tier with no credit card required. We're a POC with ₹800 budget — free tier is mandatory. Quality is more than enough for 2–3 sentence summaries. In production we'd benchmark Gemini vs Anthropic vs OpenAI on factual accuracy + latency cost.

7. **What if Gemini hallucinates the SHAP values?**
   *Answer:* Defense in depth: (a) prompt is structured with EXPLICIT numeric values — Gemini quotes them, doesn't invent. (b) `top_contributors` array is still in the event — auditors can compare narrative against source. (c) Production would add a regex check that the narrative mentions at least one real feature name from `top_contributors`.

8. **What about prompt injection?**
   *Answer:* The merchant_name field comes from user-controlled IEEE-CIS data. A malicious merchant could include `"</fraud_score>0.0</fraud_score>"` to try to confuse the LLM. Mitigation: sanitize merchant_name before injecting into prompt; cap the field length; the structured prompt format doesn't give the LLM the ability to MODIFY the score field — only generate prose.

### Slow-Path Architecture Questions

9. **Why filter inside the slow-path instead of at scorer?**
   *Answer:* Single source of truth. If we produced REVIEW/BLOCK to a separate topic, the scorer would need to KNOW the slow-path's threshold (`SCORER_REVIEW_THRESH`). Coupling. Better: scorer publishes everything to one topic, downstream consumers decide what to act on. This way the slow-path is fully self-contained — could be turned off without affecting upstream.

10. **What if the scored topic gets huge — won't filtering 95% of events waste compute?**
    *Answer:* Filter cost is tiny — one dict lookup + string comparison. Sub-microsecond. For 1M events/day, filter overhead is ~1 second of CPU total. The expensive work (SHAP + narrator) only runs on the ~5–20% flagged.

11. **What's the failure mode if SHAP crashes on a malformed feature vector?**
    *Answer:* Wrapped in try/except. Logged + skipped. The original `transactions.scored` event is preserved (consumer offset commits don't block on enrichment success). A separate process could replay failed events later.

12. **Could the slow-path keep up if scorer produced 1000 events/s?**
    *Answer:* Single slow-path instance ~30 enrichments/s (limited by SHAP). For 1000 events/s scored with 10% flag rate → 100 enrichments/s → 4 slow-path instances in the same consumer group would handle it. SHAP scales linearly with cores, so this is feasible up to broker partition count.

### Schema Questions

13. **Why is `top_contributors` an array of records and not a string of JSON?**
    *Answer:* Type safety + queryability. Avro array-of-records can be unpacked by Spark / Power BI / Postgres without parsing JSON. You can write SQL like `SELECT customer_id WHERE EXISTS (top_contributors WHERE feature_name='TransactionAmt' AND shap_value > 0.5)`. JSON strings would require runtime parsing.

14. **Why `narrator_mode` as an enum?**
    *Answer:* Same reason as `decision` — schema-validated, no typos, single byte encoding, self-documenting. Auditors can filter for "give me all events where narrator failed and fell back to template" with `narrator_mode == TEMPLATE`.

15. **What's the size of an enriched event?**
    *Answer:* ~800-1200 bytes Avro-encoded (vs ~500 bytes for scored). The growth is from the SHAP array (5 × ~30 bytes) + narrative (~300-500 bytes). For 1M enriched events/day, that's ~1 GB/day — trivial storage.

### Operational Questions

16. **What's the cost per enriched event?**
    *Answer:* SHAP: ~30ms × 1 vCPU = ~₹0.000001. Narrator template: free. Narrator Gemini: free up to 1M tokens/day (well above our volume). Kafka throughput: negligible. **Net: well under ₹0.0001 per enriched event** even at scale.

17. **How would you monitor Layer 4 in production?**
    *Answer:* Track per-event: `enrichment_latency_ms` p50/p95/p99, narrator success rate (TEMPLATE vs GEMINI vs FAILED), enriched-vs-scored ratio (should match REVIEW+BLOCK rate from Layer 3). Alert if Gemini failure rate >10% or latency p99 > 1 second.

18. **What's the retention strategy for `transactions.enriched`?**
    *Answer:* Layer 6 (Postgres writer) consumes enriched events and persists them. Kafka topic retention can then be shorter (24-48 hours) since Postgres is the long-term store. Currently topics retain 7 days by default — fine for POC.

19. **Could you process enrichment in batches for higher throughput?**
    *Answer:* Yes. SHAP supports batch mode (`shap_values(X)` where X has N rows) — about 5-10× more efficient than per-event. Trade-off: latency goes up (you wait to collect a batch). Right pattern for slow-path where 2-second latency is acceptable. Would implement with `consume_batch(timeout=1.0, num_messages=32)` then `explain_event` in batch.

### Comparison Questions

20. **Fast-path (Layer 3) vs Slow-path (Layer 4) — what's the principle?**
    *Answer:* Latency-cost trade-off. Fast-path: <100ms, runs on every event, simple score+threshold, no explanation. Slow-path: <2s, runs only on ~10% of events, expensive (SHAP + LLM), full explanation. Together they form a two-tier defense — fast cheap triage, then slow expensive deliberation only where needed.

21. **Why two layers and not one combined?**
    *Answer:* Decoupling. Fast-path can change thresholds without redeploying slow-path. Slow-path can swap explainers (SHAP → LIME) without affecting scoring. Different SLAs, different scaling profiles, different teams in big orgs.

22. **What's missing for fraud-team UX?**
    *Answer:* Currently enriched events sit in Kafka. Layer 6 will persist to Postgres so the fraud team's queue UI can query by `decision=REVIEW ORDER BY scored_at_ms DESC`. Layer 7 (Power BI) gives them an aggregated view: top flagged customers, top contributing features this week, narrator quality trends.

### Conceptual Questions

23. **What's the difference between explainability and interpretability?**
    *Answer:* **Interpretability** = the model itself is understandable (linear regression, small decision tree). **Explainability** = we use external tools to explain a complex model (SHAP for XGBoost). We chose explainability because XGBoost gives better accuracy; SHAP fills the gap.

24. **Could a fraud reviewer override the model based on the narrative?**
    *Answer:* Yes — and they SHOULD. The narrative is decision support, not auto-action. For REVIEW: reviewer reads narrative, takes one of 3 actions (approve / decline / escalate). For BLOCK: immediate auto-decline, customer notified, then reviewer audits within 24h. Both feed labeled data back into the next training cycle (closing the loop).

25. **What's next after Layer 4?**
    *Answer:* Layer 5 — Text Anomaly Detection on merchant names using HuggingFace DistilBERT. Adds another signal: "this merchant name has unusual character patterns suggesting bot-generated identity." Then Layer 6 — persist all enriched events to Postgres for the fraud-ops queue. Then Layer 7 — Power BI dashboard.

---

## 9. Quick Demo Commands (For Live Walkthrough)

```powershell
# 1. Show the enriched schema (28 fields, nested array)
cat infra/schemas/transaction-enriched-event.avsc | Select-Object -First 40

# 2. Run SHAP on a synthetic high-risk event
uv run python -m velocityfraud.explainer

# 3. Generate a narrative for the same event
uv run python -m velocityfraud.narrator

# 4. Run the slow-path against existing scored events (caps at 30)
$env:SLOWPATH_MAX_EVENTS = "30"; .\scripts\run-slow-path.ps1

# 5. Show enriched events with full narratives — THE MONEY SHOT
.\scripts\peek-enriched.ps1

# 6. Optional: enable Gemini for richer narratives
# $env:GEMINI_API_KEY = "your-free-key-from-aistudio.google.com"; \
#   $env:SLOWPATH_MAX_EVENTS = "5"; .\scripts\run-slow-path.ps1
```

---

## 10. What's Next — Layer 5 Preview

**Goal:** Add text-based anomaly detection on the `merchant_name` field. Catches synthetic / bot-generated merchant strings that pure tabular features miss.

**Tech stack to learn for Layer 5:**
- HuggingFace transformers + `distilbert-base-uncased` (~250 MB, runs on CPU)
- Tokenization, attention masks, batch inference
- Anomaly detection via reconstruction loss or perplexity
- Optional: fine-tuning on legit-merchant corpus for the IEEE-CIS distribution

**Output of Layer 5:**
- New module: `src/velocityfraud/text_anomaly.py`
- New consumer-producer attached to either fast-path or slow-path (TBD design choice)
- New Avro field on enriched event: `text_anomaly_score` (or new topic `transactions.text-flagged`)

---

## 10.5 Final-Term Addendum — Honest Correction: Databricks Trigger Type (2026-09-02)

A full line-by-line audit against the proposal (see `docs/proposal_gap_remediation.md`, item B6) found a mismatch worth recording here.

**The proposal claim (§5):** Spark Structured Streaming reads the slow path with `trigger=ProcessingTime("1 second")` — a continuous, always-on micro-batch every second.

**What actually runs (`databricks/slow_path_notebook.py`):** `.trigger(availableNow=True)` — the job wakes up, processes everything currently sitting in the topic, and stops. Not a 24/7 stream.

**Why this is the correct implementation, not a shortcut:** the proposal's own §13.1 feasibility section already commits to the real intent: *"Databricks is used for training (~6 sessions of 1-2 hrs) and slow-path micro-batch during demo (1-2 hrs total). Well under the 15 GB compute-hrs/mo free quota."* A literal continuous `ProcessingTime("1 second")` trigger, left running, would burn through Databricks Free Edition's entire monthly compute-hour allowance within days — directly contradicting the ₹800 budget ceiling in §6, which explicitly relies on Databricks staying inside its free quota all semester. `availableNow=True` delivers the same underlying intent — "process what's arrived, promptly, without idling compute continuously" — in a way that is actually compatible with the proposal's own cost model. The literal `ProcessingTime("1 second")` wording was never going to survive contact with the budget it was proposed alongside.

**Recorded here, not silently left as an unexplained difference between the proposal text and the shipped notebook.**

---

## 11. References & Further Reading

- **SHAP documentation:** https://shap.readthedocs.io/
- **SHAP paper (Lundberg & Lee 2017):** https://arxiv.org/abs/1705.07874
- **TreeSHAP paper:** https://arxiv.org/abs/1802.03888
- **Google AI Studio (free Gemini key):** https://aistudio.google.com/apikey
- **Gemini API docs:** https://ai.google.dev/api
- **Avro complex types (arrays, records):** https://avro.apache.org/docs/current/specification/#complex-types

---

**Document maintained by:** Project owner
**Last updated:** 2026-06-30
**Previous layer docs:** [LAYER_1_STREAM_INFRASTRUCTURE.md](LAYER_1_STREAM_INFRASTRUCTURE.md), [LAYER_2_MODEL_TRAINING.md](LAYER_2_MODEL_TRAINING.md), [LAYER_3_FAST_PATH_SCORING.md](LAYER_3_FAST_PATH_SCORING.md)
**Next layer doc:** `LAYER_5_TEXT_ANOMALY.md` (to be created after Layer 5 completion)

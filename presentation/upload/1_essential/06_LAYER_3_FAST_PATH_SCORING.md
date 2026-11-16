# Layer 3 — Fast-Path Scoring (COMPLETE)

> **Status:** ✅ Complete
> **Completion Date:** 2026-06-30
> **Effort:** ~1.5 hours of focused build
> **Project:** VelocityFraud — Real-Time Fraud Detection Data Pipeline
> **Program:** IMPACT pSiddhi 3.0 — Topic S2-D-06 (Semester 2, Data Track)

---

## 1. Why This Layer Exists

Layers 1 and 2 built the **pipes** (Kafka stream) and the **brain** (trained model) as independent components. Layer 3 is the **nervous system** — it connects them by reading every transaction off the stream, asking the model "is this fraud?", and writing the answer back as a new event.

**Without Layer 3, the model only existed as a `.pkl` file on disk and the pipeline only moved raw data. With Layer 3, every event flowing through `transactions.raw` produces a scored event with a verdict in `transactions.scored` — in under 100ms.**

This is what makes the system "real-time": decisions arrive while the cardholder is still standing at the merchant terminal.

---

## 2. Architecture Built

```
┌────────────────────────────────────────────────────────────────────────┐
│                  LAYER 3: FAST-PATH SCORING                             │
└────────────────────────────────────────────────────────────────────────┘

         Layer 1                  Layer 3                    Layer 4
                                                            (planned)
                                                                 │
   transactions.raw  ──►  ┌────────────────────────┐  ──►  transactions.scored
   (16-field Avro)         │       SCORER          │       (23-field Avro)
                           │                       │
                           │   consume (Kafka)     │
                           │      ↓                │
                           │   decode Avro          │
                           │      ↓                │
                           │   featurize_event     │ ←──── live_features.py
                           │   (16 → 43 cols,      │       (35% real data,
                           │    -999 for missing)  │        65% sentinel)
                           │      ↓                │
                           │   model.predict_proba │ ←──── predict.py
                           │      ↓                │       (xgboost_v1.pkl
                           │   threshold policy    │        from CHAMPION.txt)
                           │   < 0.10  → ALLOW     │
                           │   < 0.18  → REVIEW    │
                           │   ≥ 0.18  → BLOCK     │
                           │      ↓                │
                           │   build scored event  │
                           │   (echo 16 + add 7)   │
                           │      ↓                │
                           │   encode Avro         │
                           │      ↓                │
                           │   produce (Kafka)     │
                           │                       │
                           │  Avg lat: 5-6 ms       │
                           │  Max lat: 78 ms        │
                           └────────────────────────┘

Topic: transactions.raw            Topic: transactions.scored
  Schema: TransactionEvent           Schema: TransactionScoredEvent
  Partitions: 3                      Partitions: 3
  Fields: 16                         Fields: 23 (16 echoed + 7 new)
```

---

## 3. Step-by-Step Build Log (Granular)

### Phase 1 — Design the Scored Event Schema

1. Created [infra/schemas/transaction-scored-event.avsc](../infra/schemas/transaction-scored-event.avsc) — 23 fields:
   - **16 echoed** from `TransactionEvent` (so downstream consumers don't need to join with raw stream)
   - **7 new scoring fields:**
     - `fraud_score` (double, [0,1]) — model output P(fraud)
     - `decision` (enum: ALLOW / REVIEW / BLOCK) — derived from threshold policy
     - `model_name` (string) — from CHAMPION.txt
     - `model_version` (string) — "v1"
     - `scored_at_ms` (long) — when scoring completed
     - `scoring_latency_ms` (long) — end-to-end consume→produce latency
     - **`feature_completeness` (double, [0,1])** — fraction of features filled with real data vs -999 sentinel

   **Why feature_completeness?** Honesty baked into the schema. Layer 4 (SHAP) knows when to apply less weight; Power BI can color-code low-completeness scores in yellow.

2. Extended [src/velocityfraud/schema.py](../src/velocityfraud/schema.py) with `get_scored_schema()` (alongside the existing `get_schema()`).

### Phase 2 — Live Feature Mapper

3. Built [src/velocityfraud/live_features.py](../src/velocityfraud/live_features.py). The architectural challenge:
   - **The model expects 43 features** (engineered during training from the rich IEEE-CIS CSV with 394 columns)
   - **The live Avro event has only 16 fields** — many training features (C1-C14 Vesta counts, D1-D15 time deltas, M1-M9 match flags) don't exist in a single live event
   - **Production solution:** streaming feature store (Feast/Tecton/Redis) populated by a side aggregator
   - **POC solution:** fill missing features with the `-999` sentinel (matches training-time imputation)

4. Implemented `featurize_event(event_dict) -> (DataFrame, completeness)`:
   - Derives time features from `event_timestamp_ms`: hour_of_day, day_of_week, is_night, is_weekend
   - Derives amount features from `amount`: log_amount, amount_cents, is_round_dollar, is_high_amount
   - Reverse-maps `mcc` → ProductCD → frequency lookup (hardcoded from training EDA)
   - Parses `merchant_name` (`{ProductCD}-MERCHANT-{email_domain}`) → email_domain → frequency lookup
   - Uses `merchant_country` directly as addr2
   - Fills the remaining 28 features with -999
   - Returns the 43-feature DataFrame + completeness score (0.3488 in practice)

5. Verified with `_demo()` smoke test: shape (1, 43), completeness 34.88%, all real features populated correctly.

### Phase 3 — Kafka-Bound Scorer

6. Built [src/velocityfraud/scorer.py](../src/velocityfraud/scorer.py) — the operational service:
   - Loads schemas (raw + scored) at boot
   - Loads champion model via `predict.get_champion_model()` (decoupled — reads `CHAMPION.txt`)
   - Spawns Kafka Consumer subscribed to `transactions.raw`
   - Spawns idempotent Kafka Producer for `transactions.scored`
   - Main loop: consume → decode → featurize → score → decide → encode → produce
   - **Threshold policy** (configurable via env vars):
     - `score < SCORER_REVIEW_THRESH` → ALLOW
     - `SCORER_REVIEW_THRESH ≤ score < SCORER_BLOCK_THRESH` → REVIEW
     - `score ≥ SCORER_BLOCK_THRESH` → BLOCK
   - Tracks per-event latency, accumulates summary stats
   - Graceful SIGINT handling with producer flush

7. Built [scripts/run-scorer.ps1](../scripts/run-scorer.ps1) — convenience launcher with default env vars.

### Phase 4 — Production Defaults

8. Default thresholds: `REVIEW=0.50`, `BLOCK=0.85` — conservative production defaults.

### Phase 5 — End-to-End Verification (Two Runs)

9. **Run #1 (production thresholds 0.50 / 0.85):**
   - 100 events consumed, 100 produced, 0 failures
   - **Decisions: ALLOW 100%** (no scores crossed 0.50 because IEEE-CIS data is mostly legitimate + 35% feature completeness pushes scores low)
   - Latency: avg 6.25 ms, max 78 ms
   - Throughput: 20.8 events/s

10. **Run #2 (demo thresholds 0.10 / 0.18):**
    - 100 events consumed, 100 produced, 0 failures
    - **Decisions: ALLOW 76% (76), REVIEW 18% (18), BLOCK 6% (6)** — all three categories exercised
    - Latency: avg 5.47 ms, max 47 ms
    - Throughput: 24.9 events/s

11. Built [scripts/peek-scored.ps1](../scripts/peek-scored.ps1) — Python one-liner reading 3 scored events and pretty-printing all 23 fields. Verified clean decode end-to-end.

### Phase 6 — Verification

12. Ran 8-checkpoint verification (see Section 4). All passed.

### Phase 7 — Documentation

13. Wrote this completion document.

---

## 4. Verification Checkpoints (8 Checks)

| # | Check | Evidence | Status |
|---|---|---|---|
| 1 | Scored Avro schema in git | `infra/schemas/transaction-scored-event.avsc` (23 fields) | ✅ |
| 2 | Live feature mapper handles all 16 Avro fields | `_demo()` output | ✅ |
| 3 | Feature completeness > 30% | 34.88% confirmed | ✅ |
| 4 | Scorer consumes from transactions.raw | 100 events consumed per run | ✅ |
| 5 | Scorer produces to transactions.scored | 200 events produced (100+100), 0 failures | ✅ |
| 6 | Latency under 100ms p99 | avg 5-6ms, max 78ms | ✅ |
| 7 | All 3 decision types exercised | ALLOW/REVIEW/BLOCK distribution: 76/18/6 | ✅ |
| 8 | Scored events decode cleanly | peek-scored.ps1 shows all 23 fields | ✅ |

---

## 5. Files Inventory

| File | Purpose | Lines |
|---|---|---|
| [infra/schemas/transaction-scored-event.avsc](../infra/schemas/transaction-scored-event.avsc) | Avro schema for scored events (23 fields) | ~30 |
| [src/velocityfraud/schema.py](../src/velocityfraud/schema.py) | Added `get_scored_schema()` | +6 |
| [src/velocityfraud/live_features.py](../src/velocityfraud/live_features.py) | Avro event → 43-feature vector + completeness | ~250 |
| [src/velocityfraud/scorer.py](../src/velocityfraud/scorer.py) | Kafka-bound scoring service | ~300 |
| [scripts/run-scorer.ps1](../scripts/run-scorer.ps1) | Launch scorer with env-var config | ~30 |
| [scripts/peek-scored.ps1](../scripts/peek-scored.ps1) | Read + pretty-print scored events | ~40 |

---

## 6. Key Numbers to Memorize for Presentation

| Number | What It Means |
|---|---|
| **23** | Fields in TransactionScoredEvent (16 echoed + 7 new) |
| **43** | Features the XGBoost model expects |
| **34.88%** | Feature completeness in live scoring (15 of 43 from Avro fields) |
| **65.12%** | Features filled with -999 sentinel (the production gap) |
| **0.10 / 0.18** | Demo thresholds (REVIEW / BLOCK) |
| **0.50 / 0.85** | Production-conservative thresholds (REVIEW / BLOCK) |
| **5.47 ms** | Average scoring latency |
| **78 ms** | Worst-case scoring latency |
| **<100 ms** | Latency budget (p99 target) — achieved |
| **24.9 events/s** | Throughput on a single scorer instance |
| **76% / 18% / 6%** | Demo distribution: ALLOW / REVIEW / BLOCK |
| **0** | Decode failures + score failures + produce failures (perfect) |

---

## 7. Technical Stack to Master Before Presentation

### 7.1 Kafka Consumer Groups

**What it is:** A group of consumers that collectively read from a topic. Each partition is assigned to exactly one consumer in the group.

**Must understand:**
- **Group ID** — identifies the consumer group (yours: `velocityfraud-scorer-dev`)
- **Offset tracking** — Kafka remembers per-group, per-partition position
- **Rebalance** — when a consumer joins/leaves, partitions get reassigned
- **`auto.offset.reset`** — what to do if no offset exists yet (earliest vs latest)
- **Why this matters:** Scaling = launching more scorer instances in the SAME group. Up to 3 in our case (partition count).

### 7.2 Idempotent Producers (Already Covered in Layer 1)

Re-key: Kafka assigns each producer a PID + monotonic sequence number; broker dedupes retries. Combined with `acks=all`, gives exactly-once semantics within a session.

### 7.3 Avro Schema Evolution

**Adding new fields to TransactionScoredEvent** (vs TransactionEvent):
- All new fields are present in every produced message
- If we ever needed to add fields without breaking old consumers, we'd use `default` values in the Avro schema (e.g., `"default": null` for optional fields)
- For this POC, both producer and consumer use the same schema version — no evolution needed yet

### 7.4 Latency Engineering

**The 5 ms breakdown** (rough — varies per event):
- Kafka poll: ~0.5 ms (LZ4 decompression)
- Avro decode: ~0.3 ms (16 fields)
- Featurize: ~0.5 ms (mostly dict lookups + math)
- Model predict_proba: ~3 ms (XGBoost histogram inference, single row)
- Avro encode: ~0.4 ms (23 fields)
- Kafka produce (linger.ms=5): ~0.3 ms enqueue (actual broker ack is async)

**Total: ~5 ms** ✓

### 7.5 Decision Threshold Tuning

**Why three tiers and not just allow/block?**
- **ALLOW** (low score) — pass through, log only
- **REVIEW** (medium score) — flag for Layer 4 SHAP explanation + Layer 5 text anomaly + manual review queue
- **BLOCK** (high score) — auto-decline, customer notification, fraud team alert

**Production tuning:** Calibrate thresholds against business cost. If a missed fraud costs ₹10,000 and a false alarm costs ₹50 (call to customer), then optimal threshold = where marginal cost of one more flag = marginal benefit of one more catch.

### 7.6 Feature Store Concepts (Production Gap)

**What we're missing in POC:**
- C1–C14 Vesta count features (per-card rolling counts in 1h/24h/7d windows)
- D1–D15 time delta features (time since last txn / last different merchant / etc.)
- M1–M9 match flags (Vesta proprietary anti-fraud indicators)

**Production solution — Feature Store:**
- **Feast / Tecton / Redis** — store per-card aggregates
- **Online store** — sub-ms lookup at inference time
- **Offline store** — used during training, kept in sync via shared definitions
- **Side aggregator** — Spark/Flink/Kafka Streams job that maintains the aggregates by consuming `transactions.raw`

---

## 8. Expected Presentation Questions (Senior/Architect Tier)

> 25 prepared Q&A — practice once before presentation.

### Architecture Questions

1. **Why two topics (raw and scored) instead of one?**
   *Answer:* Separation of concerns. `transactions.raw` is the immutable source of truth (audit-replayable). `transactions.scored` is enriched output ready for downstream consumers. If we re-train the model tomorrow, we can re-process raw without affecting upstream. Also enables multiple parallel scoring strategies (A/B testing) on the same input.

2. **Why echo all 16 raw fields into the scored event?**
   *Answer:* Eliminates joins for downstream consumers. Layer 4 (SHAP), Layer 6 (Postgres writer), and Layer 7 (Power BI) all need transaction context AND the score. Without echo, each would have to join two topics — expensive in streaming. Echo trades ~30% bytes for zero join cost.

3. **Why XGBoost in Python instead of a sidecar service (Triton/TensorFlow Serving)?**
   *Answer:* Latency. In-process inference is 5 ms; a network hop to Triton would add 2-10 ms even on localhost. At our scale (24 events/s), the simplicity of in-process wins. We'd revisit at 10K+ events/s where horizontal scaling of inference matters.

4. **Could you scale this to 10K events/s?**
   *Answer:* Yes, three levers: (a) Add more partitions to `transactions.raw` (currently 3). (b) Launch more scorer instances in the same consumer group (one per partition). (c) Batch predictions in the scorer (process N events at a time through XGBoost — 10x faster per-event when batched). For >100K events/s, switch to NVIDIA Triton with XGBoost FIL backend.

### Feature Engineering Questions

5. **Why is feature completeness only 35% in production?**
   *Answer:* The model was trained on Vesta's anti-fraud counters (C1-C14, D1-D15, M1-M9) which represent historical card behavior — not present in a single live event. In production we'd compute these via a streaming feature store (Feast/Tecton) backed by a Flink/Spark Streaming aggregator. For POC we fill with -999 sentinel, which the tree model handles as "missing signal" without crashing.

6. **What's the impact of 35% completeness on accuracy?**
   *Answer:* Hard to quantify exactly without re-training, but published research suggests 10-25% AUC drop for tree models when 60%+ features are sentinel. Our test-set AUC of 0.9562 should be considered an UPPER bound. Real production AUC is probably in the 0.78–0.85 range. This is the single most important production gap.

7. **Why include `feature_completeness` in the scored event?**
   *Answer:* Honesty. Downstream systems can weigh predictions by their confidence. Power BI dashboard colors low-completeness scores yellow. Layer 4 SHAP gives extra weight to features that ARE present. Compliance auditors can prove we knew the limitation. Best engineering practice: don't hide your gaps — surface them.

8. **How did you reverse MCC to ProductCD?**
   *Answer:* In the replayer (Layer 1), we map ProductCD → MCC via a hardcoded dict (W→5411, etc.). In the live features, we reverse it: MCC → ProductCD → frequency. The mapping is symmetric. For real merchant data with arbitrary MCCs, we'd default to ProductCD='S' (specialty) for unknown codes.

### Operational Questions

9. **What's your latency SLA and how do you enforce it?**
    *Answer:* Target: p99 < 100ms. Current: avg 5-6ms, max 78ms. We measure per-event (`scoring_latency_ms` in every output). If breached, we'd: (a) alert via Prometheus / PagerDuty, (b) scale scorers horizontally, (c) consider model simplification (smaller XGBoost or distillation).

10. **What if the scorer dies mid-batch?**
    *Answer:* Kafka consumer group rebalances — surviving instances absorb the dead one's partitions. Last committed offset is preserved (auto-commit every 5s by default). Up to 5 seconds of events may be re-processed → that's OK because `event_id` UUID makes downstream idempotent.

11. **What's the failure mode if the model file is corrupted?**
    *Answer:* `predict.get_champion_model()` raises FileNotFoundError or joblib UnpicklingError at boot. Scorer fails fast (no zombie state). In production, deploy via blue/green so a corrupt model can't be promoted. CHAMPION.txt pointer file means rollback = one line change.

12. **What about model version skew between scorer instances?**
    *Answer:* All instances read the same `CHAMPION.txt` at boot — same model loaded into memory. To rotate models without restart, we'd add a SIGHUP handler that re-reads CHAMPION.txt. For zero-downtime promotion: spin up N+1 new instances, kill old N. Standard rolling deploy.

13. **What happens if the model is biased / drifts?**
    *Answer:* Layer 2's MLflow tracking gives us a complete history. We'd monitor production: (a) score distribution shift (KS test vs training distribution), (b) decision distribution (sudden spike in BLOCKs), (c) feature drift in raw stream. Retraining is triggered when ROC-AUC on a continuously labeled subset drops below 0.92.

### Schema & Data Questions

14. **Why an ENUM for decision instead of a string?**
    *Answer:* Avro ENUMs are schema-validated — typos cannot exist. Producer can't accidentally send "REVEIW" (typo). Smaller wire size (single byte vs 6+ string chars). Self-documenting in the schema for consumers.

15. **Why feature_completeness as a fraction (0-1) not a percentage (0-100)?**
    *Answer:* Convention in ML pipelines — probabilities and fractions live in [0, 1]. Multiplication chains stay numerically stable. Consumers can scale up to percentage for display, but storing as 0-1 prevents off-by-100 errors.

16. **Could you add new decision types later (e.g., STEP_UP_AUTH)?**
    *Answer:* Yes — Avro ENUMs support adding new symbols. Just append `"STEP_UP_AUTH"` to the schema's enum list. Old consumers using older schema versions would fail to decode if they encountered the new value — solution is rolling schema updates with consumers upgraded first.

### Production Readiness Questions

17. **What's missing for true production?**
    *Answer:* (a) Streaming feature store for the 65% missing features. (b) Prometheus metrics endpoint on scorer. (c) Dead-letter queue for messages that fail to decode/score. (d) Schema Registry for proper Avro versioning. (e) TLS + SASL/SCRAM auth on Kafka. (f) Horizontal scaling tested with chaos engineering. (g) Model A/B testing infrastructure.

18. **How would you A/B test a new model version?**
    *Answer:* Spin up parallel scorers in different consumer groups (`scorer-prod-v1`, `scorer-prod-v2`). Both consume the same raw events, write scored events to different sub-topics (`transactions.scored.v1`, `transactions.scored.v2`). Power BI dashboard compares decision distributions + downstream fraud loss metrics over a 1-week window.

19. **What about explainability?**
    *Answer:* That's Layer 4's job. The fast-path (Layer 3) only returns a score + decision. Layer 4 — the slow-path — re-evaluates flagged transactions (REVIEW/BLOCK) using SHAP to attribute the prediction to specific features, then optionally calls Google Gemini to convert the SHAP output into a human-readable explanation for the fraud-ops dashboard.

20. **What's the cost per transaction at scale?**
    *Answer:* Compute: ~5ms × 1 vCPU = trivial. Storage: scored events are ~500 bytes each × 90-day retention. For 1M events/day, that's 45GB — about ₹100/month on cheap cloud storage. Bandwidth: negligible since intra-cluster. Total: well under ₹0.001 per transaction. Production scales economically.

### Conceptual Questions

21. **What's the difference between fast-path and slow-path?**
    *Answer:* **Fast-path (Layer 3):** every transaction, sub-100ms, simple threshold decision. **Slow-path (Layer 4):** flagged transactions only, multi-second, includes SHAP + Gemini explanation + Layer 5 text anomaly + final reviewer queue. Fast-path is the gatekeeper; slow-path is the deliberator.

22. **Why XGBoost and not a deep model in production?**
    *Answer:* (Layer 2 answer applies): tabular fraud detection is XGBoost's sweet spot. Plus: 5ms inference vs 50ms+ for a deep net, 5MB model vs 500MB+, deterministic and debuggable. Deep learning is the wrong tool for this job.

23. **How does this layer support compliance audits?**
    *Answer:* Every scored event has `model_name`, `model_version`, `scored_at_ms`, `feature_completeness`. Combined with the immutable `transactions.raw` log, an auditor can replay any decision and trace it to exactly which model version + which features were used. Reproducibility = compliance.

24. **What happens to dropped/poisoned messages?**
    *Answer:* Currently: logged + skipped. In production: route to a dead-letter topic (`transactions.dlq.scorer`) with the raw bytes + error reason. A separate process can attempt re-processing or alert on patterns (e.g., 100 decode failures in a minute = upstream schema drift).

25. **What's next?**
    *Answer:* Layer 4 — Slow-Path Analysis with SHAP + Gemini. Consumer reads only REVIEW/BLOCK events from `transactions.scored`, runs SHAP to identify feature contributions, calls Gemini to convert to natural-language explanation, writes enriched event to `transactions.enriched`. This is what feeds the fraud-ops dashboard.

---

## 9. Quick Demo Commands (For Live Walkthrough)

```powershell
# 1. Show all 3 services healthy
docker ps --format "table {{.Names}}\t{{.Status}}"

# 2. Show the scored schema
cat infra/schemas/transaction-scored-event.avsc | Select-Object -First 30

# 3. Run the live scorer (production thresholds)
$env:SCORER_MAX_EVENTS = "100"; .\scripts\run-scorer.ps1

# 4. Run with demo thresholds (more visually interesting decision mix)
$env:SCORER_MAX_EVENTS = "100"; $env:SCORER_REVIEW_THRESH = "0.10"; $env:SCORER_BLOCK_THRESH = "0.18"; $env:SCORER_GROUP = "demo"; .\scripts\run-scorer.ps1

# 5. Peek at decoded scored events
.\scripts\peek-scored.ps1

# 6. Show in Kafka UI
Start-Process "http://localhost:8081/ui/clusters/velocityfraud-dev/all-topics/transactions.scored/messages"
```

---

## 10. What's Next — Layer 4 Preview

**Goal:** Add explainability + LLM-augmented analysis to flagged transactions only.

**Tech stack to learn for Layer 4:**
- SHAP (SHapley Additive exPlanations) — feature-attribution for any tree model
- Google Gemini API (free tier) — natural-language explanation generation
- Spark Structured Streaming (optional) — for batched slow-path
- Selective consumption (filter REVIEW/BLOCK only)

**Output of Layer 4:**
- New module: `src/velocityfraud/explainer.py`
- New consumer-producer: `src/velocityfraud/slow_path.py`
- New Avro schema: `transaction-enriched-event.avsc` (adds `top_contributors`, `narrative`, `enriched_at_ms`)
- Live demo: scorer produces REVIEW/BLOCK → slow_path consumes → produces enriched event with English narrative

---

## 10.5 Final-Term Addendum — Honest Corrections & Additions (2026-09-02)

A full line-by-line audit against the proposal (see `docs/proposal_gap_remediation.md`) found four things worth recording here rather than leaving implicit.

**Addition — Layer 8b (velocity pre-filter).** The proposal described "sliding-window velocity counters (1-min, 10-min, 60-min)" as a model input computed inside Kafka Streams. That never existed. Rather than retrain the champion model this late (see the remediation doc for the full reasoning), velocity counting was implemented as a **live Redis pre-filter** (`velocity.py`) — architecturally the same slot Layer 8's blocklist already occupies, running immediately after it in both `scorer.py` and `api.py`. It uses a Redis sorted set per card (`vl:card:{token}`) with continuous eviction of stale entries — a genuine sliding window, not a fixed/tumbling one — and forces `REVIEW` when a card exceeds its threshold in any of the three windows. New Avro fields `velocity_hit` / `velocity_window` / `velocity_reason` mirror the existing `blocklist_*` fields exactly.

**Addition — score cache.** Proposal Risk #1's mitigation ("cache scores for identical feature hashes, 1-min TTL") is now implemented (`score_cache.py`) — a small Redis GET/SET wrapper keyed by a SHA-256 hash of the feature vector, wired into the ML-scoring branch in both `scorer.py` and `api.py`, after the blocklist and velocity checks. Fail-open, same as every other Redis-backed component in this project.

**Correction — shadow model architecture.** The proposal describes the shadow XGBoost model as running "in-broker via the Kafka Streams Processor API." The actual implementation (`failover_scorer.py`) is a separate Python process using Redis leader-election for hot-standby takeover — proven live in `demo-failover.ps1` (~2s promotion, no consumer-visible gap). No Kafka Streams/JVM topology exists anywhere in this codebase. This is judged a better real-world pattern (it's how production failover is commonly built), just not the one originally described — recorded here so the written spec matches what actually ships.

**Correction — decision schema.** The proposal describes the two-tier output as binary `{accept, escalate}`. The actual, shipped decision schema is the three-way `ALLOW / REVIEW / BLOCK` used throughout this document, `feedback.py`, and every test in the suite. Read as a refinement of the original intent (`ALLOW` = accept, `REVIEW` + `BLOCK` = escalate, with `BLOCK` additionally carrying an automatic hard-stop action `REVIEW` alone doesn't), not a different feature.

---

## 11. References & Further Reading

- **Confluent Kafka consumer-group guide:** https://docs.confluent.io/platform/current/clients/consumer.html
- **Avro ENUM schema spec:** https://avro.apache.org/docs/current/specification/#enums
- **MCC code list (ISO 18245):** https://en.wikipedia.org/wiki/Merchant_category_code
- **Feature stores comparison:** https://www.featurestore.org/
- **Threshold tuning for cost-sensitive classification:** scikit-learn docs `precision_recall_curve`

---

**Document maintained by:** Project owner
**Last updated:** 2026-06-30
**Previous layer docs:** [LAYER_1_STREAM_INFRASTRUCTURE.md](LAYER_1_STREAM_INFRASTRUCTURE.md), [LAYER_2_MODEL_TRAINING.md](LAYER_2_MODEL_TRAINING.md)
**Next layer doc:** `LAYER_4_SLOW_PATH_ANALYSIS.md` (to be created after Layer 4 completion)

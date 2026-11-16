# PROPOSAL — VelocityFraud (sharpened)

## Response to RFP: S2-D-06 — Fraud Detection Data Pipeline

> **Architecture archetype:** Throughput-first, low-latency streaming fraud detection.
> **Best for:** E-commerce platforms, payment gateways, marketplaces, PSPs — workloads where transaction TPS is high and the cost of latency (cart-abandonment, settlement-window slippage) is direct revenue loss.
> **Wins on:** End-to-end latency (sub-second decisions), throughput at scale, operational simplicity (fewer custom moving parts that can fail), graceful degradation under load.
> **Budget:** **₹800 standalone** — every rupee is held as a named risk reserve rather than spent speculatively. All tooling and infrastructure are genuinely ₹0 by design (see §6).

---

## 1. Topic ID & Title

| Field | Detail |
|---|---|
| Topic ID | S2-D-06 |
| Topic Title | Fraud Detection Data Pipeline — *VelocityFraud* |

## 3. Semester & Category

Semester 2 — Data Track (E2E Development with AI Core, QA Mandatory).

## 4. Problem Understanding

At Psiog's e-commerce and PSP clients, fraud detection is not a back-office decision — it sits on the critical path between *card-tendered* and *settlement-initiated*. Three failure modes drive losses that rule engines structurally cannot solve:

- **Latency is revenue.** Every additional 100 ms of decision time at a high-traffic merchant correlates measurably with cart-abandonment and lost throughput on the payment switch. A rule engine that "works" but blocks the switch for 800 ms is itself a fraud-equivalent loss.
- **Spiky traffic kills static thresholds.** Marketplaces see 5–10× traffic surges during flash sales, BFCM, Diwali, end-of-month payroll cycles. A rule engine tuned for steady-state either over-blocks during surges (revenue damage) or under-blocks (fraud window opens). Neither is acceptable.
- **Manual scoring layers don't scale.** Bolt-on ML services that re-tokenize, re-aggregate, and re-route every event introduce additional services, additional failure surfaces, and additional latency-budget consumption. Each extra hop reduces the budget available for the model itself.

The customer-trust dimension VelocityFraud addresses: **operational reliability under traffic surges.** A merchant's customers do not see model precision — they see whether their checkout completes. A merchant's CFO does not see Kafka topic lag — they see settlement throughput. VelocityFraud is for the customer whose first question is *"What happens to my Diwali traffic?"*

## 5. Proposed Solution

**VelocityFraud** is a throughput-first streaming pipeline designed around a *two-tier scoring* topology: a sub-100 ms LLM fast-path for accept/escalate triage, and a 1–2 s ML+SHAP slow-path for enrichment and dashboards. The architecture deliberately minimises custom services — every additional service is an additional thing that can fail under load.

### Layer 1 — High-Throughput Streaming
- Apache Kafka 3.7 in Docker (single broker for POC, multi-broker-ready). **KRaft mode** to remove the ZooKeeper failure mode.
- **Apicurio Schema Registry** in the same Docker network — every transaction event carries an Avro schema reference. Producer/consumer compatibility is enforced at the broker boundary, not at runtime in scoring code.
- **3 transaction feature categories ingested:**
  - *Amount features* — value, currency, FX-normalised value, amount-z-score vs customer baseline.
  - *Merchant features* — MCC, merchant-ID, merchant country, merchant-age, merchant-recent-chargeback-rate (joined from a slow-changing dimension topic).
  - *Geographic / behavioural features* — IP-geo, device fingerprint, **sliding-window velocity counters** (1-min, 10-min, 60-min) computed inside Kafka Streams — no external state store needed.
- **Idempotent producers** with `enable.idempotence=true` and **exactly-once semantics** (`isolation.level=read_committed`) on consumer-side scoring. The pipeline cannot double-score or drop a transaction even under broker restarts.
- **Backpressure handling**: consumer lag is monitored via JMX → Power BI; producers throttle gracefully when scoring lag exceeds a threshold rather than overflowing memory.

### Layer 2 — Two-Tier Scoring Engine (AI Core)

**Fast path (sub-100 ms target):**
- **Groq Cloud Llama 3.3 70B** is the sweet spot of this architecture. Groq's LPU inference hardware delivers sub-100 ms LLM classification at sustained throughput. Triage output is binary `{accept, escalate}` with a confidence score; accept-decisions are committed back to the switch immediately.
- A pre-trained lightweight **XGBoost shadow model** also runs in-broker via the Kafka Streams Processor API. If Groq returns 5xx or breaches its latency SLO, the shadow model takes over with zero failover overhead. Both paths emit the same `{accept, escalate}` output schema, so downstream consumers cannot tell which path produced a given decision.

**Slow path (1–2 s target):**
- **Spark Structured Streaming** on Databricks Free Edition reads from the same Kafka topic with `trigger=ProcessingTime("1 second")` micro-batching. It runs the full **Random Forest and XGBoost** ensemble (both registered in MLflow) with SHAP value computation for the escalated cohort only.
- **Gemini 2.5 Flash** is called for narrative explanations on escalated transactions only — keeping Gemini RPD well under the 250/day free cap.
- **Hugging Face DistilBERT** runs as a Spark UDF on `merchant_name` and `transaction_description` to flag text-field anomalies (typosquats, suspicious patterns).

**Why two tiers:** the fast path returns a yes/no in time for the payment switch; the slow path enriches escalated cases with SHAP + narrative for the analyst review queue. Analysts see decisions that have already been made, with full reasoning. Customers see a checkout that completes.

### Layer 3 — Live Analytics Surface
- **Power BI Desktop with DirectQuery** to a Databricks SQL endpoint over a Delta table written by the slow path. Dashboards reflect live data (sub-minute latency) without manual refresh.
- 4 dashboard views:
  1. **Real-time Alert Feed** (live, DirectQuery) — escalated transactions with Gemini narrative, sorted by score.
  2. **Fraud Trend Analysis** — WoW/MoM, by MCC, geography, merchant; flash-sale anomaly overlay.
  3. **Model Performance Dashboard** — RF vs XGB precision/recall/FPR/throughput vs latency; fast-path vs slow-path agreement rate.
  4. **Operational Health Dashboard** — Kafka consumer lag, p95 / p99 latency, Groq RPM headroom, fast-path-vs-shadow-model agreement (drift indicator).
- Analyst actions (accept / escalate / false-positive) write back to a `feedback` Kafka topic feeding the retraining loop.

### Architecture (data flow)

```
                ┌───────────────────────────────────────────────┐
                │       Kafka (KRaft, Apicurio Schema Registry)  │
                └─────┬─────────────────────────┬───────────────┘
                      │                         │
          ┌───────────▼──────┐         ┌────────▼──────────────┐
          │   Fast Path      │         │   Slow Path            │
          │   (<100 ms)      │         │   (1–2 s)              │
          │                  │         │                        │
          │  Groq Llama 3.3  │         │  Spark Structured      │
          │       ║          │         │  Streaming             │
          │  XGB shadow      │         │   ├─ RF / XGBoost      │
          │  (fail-safe)     │         │   ├─ SHAP              │
          │                  │         │   ├─ HF text-anomaly   │
          └──────┬───────────┘         │   └─ Gemini narrative  │
                 │                     └────────┬───────────────┘
                 ▼                              ▼
          decisions topic                enriched-decisions topic
                                                │
                                                ▼
                                          Delta table
                                                │
                                                ▼
                                  Power BI Desktop (DirectQuery)
                                          4 views
```

### Customer-trust differentiators
- **Sub-100 ms fast-path accept decisions** — the checkout completes before the rule engine would have started.
- **Failover to local shadow XGBoost is zero-overhead** — if Groq is down, the switch never knows.
- **Operational visibility is first-class** — the Operational Health Dashboard is the same Power BI as the fraud dashboards; on-call sees both with the same query.
- **Exactly-once semantics** — no double-charges, no missed scores even under broker restarts.

## 6. Tools, Subscriptions & Cost Breakdown

**Total: ₹800 / semester | Ceiling: ₹2,500 | Unused: ₹1,700**

The infrastructure decision is the most important sharpening of this proposal. Running Kafka + Spark + MLflow + load tests on a 1 vCPU / 1 GB DigitalOcean droplet was the original plan's weak link. Upgrading to a 2 vCPU / 4 GB DigitalOcean droplet would have cost ~₹6,000 over 3 months — well over the ₹800 line. The honest answer is **Oracle Cloud Always Free Tier**, which gives materially better hardware than any paid DigitalOcean option in this budget range, at ₹0.

### Infrastructure rationale — why Oracle Cloud Always Free Tier

| Option considered | Spec | 3-month cost | Verdict |
|---|---|---|---|
| DigitalOcean s-1vcpu-1gb | 1 vCPU, 1 GB RAM | ~₹1,500 | **Rejected** — JVM-heavy stack (Kafka + Spark) will thrash on 1 GB. |
| DigitalOcean s-2vcpu-4gb | 2 vCPU, 4 GB RAM | ~₹6,000 | **Rejected** — over budget by 7× the entire VelocityFraud allocation. |
| **Oracle Cloud Always Free — Ampere A1 (split across 2 VMs)** | **4 ARM cores, 24 GB RAM, 200 GB block storage** (total quota, splittable) | **₹0** | **Selected** — always free (not 12-month trial); larger than the paid DigitalOcean tier we couldn't afford; one signup gets the full quota. |

**The Always Free quota is split across two VMs:**

| VM | Role | Spec |
|---|---|---|
| `vf-demo` | System under test — Kafka, MLflow, FastAPI scoring, Spark micro-batches | 2 ARM cores, 12 GB RAM |
| `vf-loadgen` | Wk 15 scale-test load generator (k6 / Locust) — idle until then | 2 ARM cores, 12 GB RAM |

Both VMs live in the same Oracle region, sub-millisecond network between them, both ARM (same architecture as the production demo VM). Load-test results genuinely reflect demo VM behaviour — no x86-to-ARM translation gap.

### Cost breakdown

| Tool / Service | Purpose | Tier | Cost | Justification |
|---|---|---|---|---|
| Apache Kafka 3.7 (Docker, KRaft) | Streaming backbone | OSS | ₹0 | Runs on `vf-demo` |
| Apicurio Schema Registry | Avro schema compatibility enforcement | OSS | ₹0 | Same Docker compose |
| **Oracle Cloud Always Free — Ampere A1 (`vf-demo`)** | Demo host: Kafka + MLflow + FastAPI + Spark micro-batches | Free (always) | **₹0** | 2 ARM cores + 12 GB RAM is more than the workload needs |
| **Oracle Cloud Always Free — Ampere A1 (`vf-loadgen`)** | Wk 15 scale-test load generator (k6 / Locust) | Free (always) | **₹0** | Same quota as `vf-demo`; ARM parity; same data centre |
| Databricks Free Edition | Model training + Spark Structured Streaming for slow path | Free | ₹0 | 15 GB compute-hrs/mo |
| MLflow (self-hosted on `vf-demo`) | Experiment tracking + model registry | OSS | ₹0 | Same VM, port 5000 |
| Kafka Streams (Processor API) | In-broker shadow XGBoost + windowed velocity counters | OSS | ₹0 | No external state store needed |
| HuggingFace DistilBERT (Spark UDF) | Text anomaly detection | OSS | ₹0 | ARM-compatible wheels |
| Groq Cloud — Llama 3.3 70B | Fast-path classification | Free | ₹0 | 1,000 RPD; the architecture's reason for existing |
| Google AI Studio — Gemini 2.5 Flash | Slow-path narrative generation (escalated only) | Free | ₹0 | <80 RPD typical demo load (well under 250 cap) |
| scikit-learn + XGBoost | Shadow + slow-path models | OSS | ₹0 | |
| Power BI Desktop with DirectQuery | Live dashboards over Databricks SQL | Free | ₹0 | Runs on analyst's Windows machine |
| Pytest + Locust + k6 + Great Expectations | QA framework | OSS | ₹0 | |
| GitHub + GitHub Actions | Version control + CI/CD | Free | ₹0 | 2,000 min/mo private repo, unlimited public |
| **— Subtotal: tooling and infrastructure** | | | **₹0** | Everything above is genuinely free |
| **Groq paid-overage reserve** | If 1,000 RPD free cap is hit during chaos testing or scale tests | Reserve | **₹300** | Groq's paid tier starts at $0.59 per million tokens — this covers ~50K extra requests |
| **Alternative-cloud fallback reserve** | Hetzner CAX11 (~₹350/mo) if Oracle has regional capacity issues mid-semester | Reserve | **₹350** | Named risk; do not spend unless triggered |
| **General contingency** | Unforeseen — DNS, certificates, third-party service blips | Reserve | **₹150** | |
| **— Subtotal: risk reserves** | | | **₹800** | Each line is a named risk, not generic padding |
| **TOTAL** | | | **₹800** | 32% of the ₹2,500 ceiling. ₹1,700 left visibly unused as budget discipline. |

**Why the unused ₹1,700 is a feature, not a gap:** every RFP requirement is satisfied at ₹800. Spending more would not improve model accuracy, latency, throughput, or QA coverage — it would only add tools that do not earn their cost. A senior architect's job is to spend only what creates value, and to be able to defend each rupee. The ₹800 itself is reserved against three specific, named risks — not held as padding.

## 7. Timeline & Effort

### Phase 1 — Weeks 4–9: Streaming Foundation + Fast Path

| Wk | Task | Deliverable | QA Activity |
|---|---|---|---|
| 4 | Docker compose: Kafka (KRaft) + Schema Registry + MLflow on local dev. Oracle Cloud account + `vf-demo` VM provisioned in parallel. Idempotent producer skeleton with one mock source. | Local streaming infra running; `vf-demo` accessible | Idempotency unit tests; schema-evolution test |
| 5 | 3 sources mocked → producers → Kafka. **IEEE-CIS stream replayer** built (reads `train_transaction.csv`, publishes to Kafka at configurable rate). Velocity counters via Kafka Streams Processor API. | All 3 feature categories streaming from IEEE-CIS rows | Watermarking + windowing tests; replayer-rate test |
| 6 | Random Forest + XGBoost trained in Databricks. MLflow logged. Shadow XGBoost packaged for Kafka Streams (must be ARM-compatible for Wk 14 deploy). | RF + XGB F1 ≥ 0.92 on held-out IEEE-CIS slice | Model accuracy gate in CI; **ARM-wheel verification** |
| 7 | **Groq fast-path** integrated via FastAPI scoring service. Shadow-model failover test (kill Groq, verify XGB takes over). | Sub-100 ms p95 fast-path on local dev | Failover smoke test |
| 8 | Spark Structured Streaming slow path. SHAP + Gemini narratives. DistilBERT text-anomaly as Spark UDF. | 3 explanation scenarios working end-to-end | E2E latency test (fast + slow paths) |
| 9 | Mid-term: docs, demo (recorded), Moodle upload. | Mid-term ready | Phase-1 regression green |

### Phase 2 — Weeks 11–16: Live Analytics + Scale Validation

| Wk | Task | Deliverable | QA Activity |
|---|---|---|---|
| 11 | Power BI Desktop with DirectQuery to Databricks SQL. Real-time Alert Feed + Fraud Trend views. | Dashboard v1 (live data) | DirectQuery latency tests |
| 12 | Model Performance + Operational Health dashboards. Feedback writeback topic. | 4 PBI views; feedback loop closed | Writeback integration test |
| 13 | Backpressure + graceful degradation under simulated load. Failover automation. | Pipeline self-throttles under load | Chaos test: kill broker, kill Groq, kill Databricks |
| 14 | **Deploy to `vf-demo` (Oracle Ampere A1).** Migrate Docker compose, MLflow, FastAPI scoring service to the ARM VM. | Pipeline running on `vf-demo` | Deploy-from-clean-clone smoke test on ARM |
| 15 | **Provision `vf-loadgen` (second Oracle Ampere A1 VM, same region).** Install k6 + Locust. Run sustained 10K tx/min for 30 min against `vf-demo`. p95 / p99 captured. | Throughput certificate; load-gen VM remains provisioned for re-runs | k6 + Locust load reports |
| 16 | Optimisation pass (consumer batching, JVM tuning, Kafka partition count). Final docs. Final demo prep. | Performance-tuned artefact | Full regression + load re-run |

**Total effort:** ~150 hrs across 12 weeks (~12.5 hrs/week). See §13 for the pre-Week-4 onboarding ramp.

## 8. Tech Stack

| Layer | Technology | Cost | Throughput Rationale |
|---|---|---|---|
| Language | Python 3.11 + JVM (Kafka Streams) | Free | JVM where the latency budget demands it |
| Streaming | Kafka 3.7 KRaft + Apicurio Schema Registry | Free | Schema evolution without redeploys |
| Stream processing (fast) | Kafka Streams Processor API | Free | In-broker state; no external store |
| Stream processing (slow) | Spark Structured Streaming on Databricks Free Edition | Free | 1-second micro-batches |
| Training | sklearn + XGBoost, MLflow registry | Free | |
| Fast-path classifier | Groq Llama 3.3 70B | Free | Sub-100 ms — the architecture's reason for existing |
| Shadow classifier | XGBoost inside Kafka Streams worker | Free | Zero-overhead failover |
| Text anomaly | HuggingFace DistilBERT (ARM-compatible wheels) | Free | |
| Explanation | SHAP + Gemini 2.5 Flash (escalated only) | Free | RPD stays well under cap |
| Storage | Delta table on Databricks; Kafka topic retention | Free | |
| Dashboard | Power BI Desktop with DirectQuery → Databricks SQL | Free | Live data, no manual refresh |
| QA | Pytest, Locust, k6, Great Expectations, ChaosMesh-style scripts | Free | |
| Demo VM (`vf-demo`) | Oracle Cloud Always Free Ampere A1 — 2 ARM cores, 12 GB RAM | ₹0 | System under test |
| Load-gen VM (`vf-loadgen`) | Oracle Cloud Always Free Ampere A1 — 2 ARM cores, 12 GB RAM | ₹0 | Wk 15 only; same Oracle quota; ARM parity with `vf-demo` |
| Backup cloud | Hetzner CAX11 (~₹350/mo) if Oracle has regional capacity | Reserve | Held in ₹350 contingency line |

## 9. Expected Deliverable / POC

At the Week 17 review:

- **3-category Kafka stream** from the IEEE-CIS replayer with Avro schema compatibility enforced at the broker.
- **Random Forest + XGBoost** in MLflow with precision/recall/F1/FPR documented; XGBoost selected for production with written justification.
- **Two-tier scoring demo:**
  - Fast path: Groq classifies a transaction in <100 ms (live timer on screen).
  - Failover: presenter kills Groq mid-demo; in-broker shadow XGBoost takes over with no consumer-visible interruption.
- **DistilBERT text-anomaly** integrated as a Spark UDF; flags a live typosquat injected by the replayer.
- **3 fraud-pattern Gemini explanations:** velocity, geo-impossible-travel, MCC mismatch.
- **4 Power BI views with DirectQuery** — dashboards refresh live as the replayer produces events.
- **Scale-test certificate** — k6 report from Wk 15 showing sustained 10K tx/min from `vf-loadgen` against `vf-demo` with p95 < 200 ms fast-path, p95 < 2 s slow-path. Both VMs on Oracle ARM, same region — results genuinely reflect the demo VM.
- **Operational Health dashboard** — Kafka lag, Groq RPM headroom, shadow-model agreement rate, all live.
- **QA suite ≥80% coverage**, GitHub Actions CI green.

## 10. QA Strategy (Mandatory)

### 10.1 Test Approach
For a throughput-first architecture, latency and reliability under load are first-class test concerns alongside model accuracy. Every PR runs a small synthetic load benchmark; a regression below the agreed p95 budget fails the build. Chaos tests (kill broker, kill Groq, kill Databricks) run weekly.

### 10.2 Test Types & Coverage

| Test Type | What it covers | Tool | Target |
|---|---|---|---|
| Unit | Schema validation, velocity counter logic, shadow-XGB inference | Pytest | >80% coverage |
| Integration | Kafka producer EOS, schema registry compat, Spark stream → delta | Pytest + Testcontainers | All paths |
| E2E | Producer → fast-path → slow-path → dashboard → writeback | Pytest + Playwright | 3 scenarios |
| Model Accuracy | RF + XGB + shadow on held-out IEEE-CIS slice | sklearn metrics | F1 ≥ 0.92, FPR ≤ 2% |
| Fast-Path Latency | Groq round-trip in CI | Pytest + custom harness | p95 < 100 ms |
| Failover | Kill Groq mid-flight; verify shadow takes over | Custom chaos script | Zero dropped events |
| Load | Sustained 10K tx/min for 30 min, `vf-loadgen` → `vf-demo` | k6 + Locust | p95 fast < 200 ms; p95 slow < 2 s |
| Data Validation | Schema, null, duplicate, watermark correctness | Great Expectations | Zero invalid records |
| Regression | All above on every push | GitHub Actions | 100% pass on merge |

### 10.3 AI-Assisted QA
- **AI-generated load patterns** — Gemini synthesises traffic shapes (flash-sale spike, slow-leak DDoS, mixed-currency surge) used to drive k6 scenarios; tests the architecture against patterns a hand-coded harness wouldn't invent.
- **AI-validates-AI on explanations** — second Gemini call grades each narrative for *factual against SHAP, ≤80 words, actionable*. Failing narratives are dropped from the dashboard rather than shown to analysts.
- **Drift detection on fast-path-vs-shadow agreement** — if Groq and the shadow XGBoost disagree on >5% of transactions in a window, an alarm fires; one of the two has drifted and needs investigation.

### 10.4 QA Deliverables
Pytest suite ≥80% coverage on GitHub, CI green with latency gates, k6 + Locust load report (Wk 15), chaos-test report, operational health baseline, drift dashboard. Evidence on Moodle at Wk 10 (partial) and Wk 17 (complete).

## 11. Risk & Mitigations

Risks 1–5 are the original architectural risks. Risks 6–11 explicitly address the caveats flagged in the senior-engineer review.

| # | Risk | Impact | Mitigation | Fallback |
|---|---|---|---|---|
| 1 | Groq RPM exhausted during scale demo | Fast-path collapses | Shadow XGB takes over automatically; cache scores for identical feature hashes (1-min TTL) | Shadow-only mode (still <500 ms) |
| 2 | DirectQuery latency PBI → Databricks unacceptable | Live dashboards lag | Materialise hot views every 60 s; fall back to Import mode for non-live views | Hybrid composite model |
| 3 | Spark Structured Streaming watermark misconfigured → late events dropped | Missed fraud cases | Watermark correctness tests in CI; explicit late-event reporting topic | Re-process from earliest offset |
| 4 | Schema evolution breaks consumer at deploy | Pipeline halt | Apicurio compatibility mode = `BACKWARD`; consumer rejects on schema break before processing | Roll back producer |
| 5 | Load-gen VM (`vf-loadgen`) eats into demo VM (`vf-demo`) performance | Scale-test results contaminated | They're separate VMs in Oracle's quota — only the network between them is shared, and it's sub-ms intra-region | If contention seen, throttle load-gen to 5K tx/min and extend test duration |
| 6 | **Oracle Cloud Ampere A1 capacity unavailable in your region** | No demo host (and no load-gen host) | Provision both Oracle VMs early in Wk 4; have Hetzner CAX11 as warm backup (~₹350/mo, paid from contingency) | Move both VMs to Hetzner; ARM parity preserved |
| 7 | **ARM-compatibility breaks a Python wheel (HuggingFace, XGBoost)** | Slow-path or text anomaly down | Wk 6 deliverable explicitly includes ARM-wheel verification on `vf-demo`; pin versions in `requirements.txt`; build wheels from source if needed | Run slow-path on Databricks (x86) instead of Oracle VM |
| 8 | **Groq free tier latency inconsistent on demo day** | Live sub-100 ms claim undermined | Pre-warm endpoint via heartbeat; shadow XGB hot-standby is the architectural answer | Shadow-only demo (still credible, still <500 ms); ₹300 paid-overage reserve available |
| 9 | **Gemini free quota exhausted before demo day** | Narratives unavailable | Cache last successful narrative for each scenario pre-demo; rate-limit slow-path calls | Template-based explanation from SHAP top-5 |
| 10 | **Databricks Free Edition quota exhausted mid-semester** | Slow path stops training | Reset compute-hrs at month boundary; reduce micro-batch frequency to 5 s | Train on Oracle VM (slower but free) |
| 11 | **Demo VM concurrency overload — Kafka + Spark + DirectQuery + load test simultaneously** | Demo crashes during live presentation | `vf-demo` has 12 GB RAM (vs the 1 GB the original plan assumed) — the most-flagged ChatGPT concern is resolved by the cloud choice. Load test runs on separate `vf-loadgen`, not on `vf-demo`. | Reduce live demo concurrency; show load test from pre-recorded run |

## 12. Semester Alignment

VelocityFraud is fully E2E (ingest → fast/slow scoring → dashboard → analyst → writeback). AI is structurally core — Groq is the fast path's reason for existing; without it, the sub-100 ms claim does not hold. The two-tier topology is itself an AI-design choice: ML and LLM playing complementary roles rather than one replacing the other. QA is embedded with explicit latency and chaos gates absent from architectures that prioritise model accuracy alone. Budget at ₹800 is **the lowest defensible figure** — every requirement is met, every cost is justified, ₹1,700 stays visibly unused as discipline. The differentiator is **operational reliability under traffic surges** — when Diwali traffic arrives, the checkout completes.

---

## 13. Feasibility Check & Senior Architect's Onboarding Guide

This section is **not** for the RFP reviewer. It is for the participant — me, you, the person actually building this. It answers two questions honestly:

1. *Is the ₹800 / 12.5-hr-week / 12-week plan actually achievable?*
2. *How should I start so I don't waste the first two weeks figuring out where to start?*

### 13.1 Each ChatGPT caveat, addressed

| Caveat | Resolution in this proposal |
|---|---|
| *Most development is local — avoids cloud cost* | Confirmed. Wk 4–13 run on local dev (your laptop). Oracle VMs are used Wk 14 (`vf-demo`) and Wk 15 onwards (`vf-loadgen` added). |
| *Load testing duration is short — prevents VM overrun* | Confirmed. The Wk 15 scale test is a 30-minute sustained run on `vf-loadgen`. `vf-loadgen` is free regardless, so duration is no longer cost-bounded. |
| *Groq free tier behaves reliably — avoids paid fallback* | Resolved by design: shadow XGBoost is the architectural answer to Groq failure. We never depend on Groq's free tier behaving — we plan for it to misbehave. ₹300 paid-overage reserve sits in contingency. |
| *Gemini requests stay minimal — avoids quota exhaustion* | Resolved by design: Gemini is called only on **escalated** transactions, not every event. Typical demo load is <80 RPD vs the 250 RPD free cap. Pre-cached narratives for demo day in Risk #9. |
| *Databricks free quota sufficient — avoids paid compute* | Resolved by scope: Databricks is used for *training* (~6 sessions of 1-2 hrs over the semester) and *slow-path micro-batch* during demo (1-2 hrs total). Well under the 15 GB compute-hrs/mo free quota. |
| *Demo concurrency remains moderate — infra remains stable* | **This was the biggest concern.** `vf-demo`'s 12 GB RAM is more than the workload needs even with all components running simultaneously. Load test runs on a separate VM (`vf-loadgen`) so the demo VM is never asked to be both system-under-test and load-generator at the same time. The 1 GB DigitalOcean droplet would have been wrong; this isn't. |

**Net verdict: ₹800 is achievable and defensible. The original plan's vulnerability was the 1 GB demo VM; switching to two Oracle Always Free Ampere A1 VMs resolves it at no additional cost, with ARM-on-ARM parity for load testing.**

### 13.2 Where to start — the pre-Week-4 ramp (8–10 hours, ideally in the week before Wk 4)

The biggest predictor of finishing on time is **not** the technical difficulty — it is whether you spend Wk 4 fighting your environment instead of building. Spend 8–10 hours in the preceding week on these, in this order:

**Day 1 — Kafka concepts (2 hrs).**
- Watch Confluent Developer's *Kafka 101* — first 4 videos, ~45 min total.
- Then: run `docker-compose up` on Confluent's official quickstart compose file. Produce a message with `kafka-console-producer`. Consume it with `kafka-console-consumer`. *That's it.* You now understand the smallest possible end-to-end Kafka loop.

**Day 2 — Python + Kafka (2 hrs).**
- Install `confluent-kafka-python`. Write a 20-line Python producer that sends `{"id": 1, "amount": 4500}`. Write a 20-line consumer that prints what it reads. Run them against your local Kafka.
- This is **identical** to what Wk 4–5 will ask you to do, just with smaller payloads. Doing it now means Wk 4 is *writing the real producer*, not learning what a producer is.

**Day 3 — Databricks Free Edition (2 hrs).**
- Sign up for Databricks Free Edition. Create a workspace. Run the *Quickstart: Notebook* tutorial — load a CSV, run a Spark query.
- Download `train_transaction.csv` from IEEE-CIS (Kaggle). Upload to Databricks. Run `df.count()` — you should see ~590K. Run `df.groupBy("isFraud").count()` — verify the fraud rate.

**Day 4 — Power BI Desktop (1 hr).**
- Install Power BI Desktop (Microsoft Store, free).
- Connect to any sample CSV. Make one bar chart. Click *Refresh*. That is the minimum loop you will repeat in Wk 11.

**Day 5 — Oracle Cloud Always Free signup (1 hr).**
- Create an Oracle Cloud account. Provision a `VM.Standard.A1.Flex` instance with **2 ARM cores and 12 GB RAM** (this is `vf-demo`). SSH in. Run `docker --version`. Install Docker if not present.
- **Do this early.** Oracle's ARM capacity is region-dependent and you may need to retry over a few days. Better to discover that in Wk 3 than in Wk 14.
- Do **not** provision `vf-loadgen` yet — that comes in Wk 15. But verify your Always Free quota shows 2 unused cores and 12 unused GB.

**Day 6 — Pin the IEEE-CIS dataset (1 hr).**
- Download `train_transaction.csv` and `train_identity.csv` from the IEEE-CIS competition on Kaggle. Commit them to your project (or to a private GitHub LFS repo if too big — they're ~700 MB combined).
- Skim the column descriptions. Note that `TransactionAmt`, `ProductCD`, `card4` (card brand), `addr1/addr2`, `dist1/dist2`, `P_emaildomain`, `DeviceType` will be your producer's payload fields.

**Day 7 — buffer.** Likely needed because something on Day 1–6 took longer than expected.

### 13.3 Data source decision — IEEE-CIS plus a stream replayer

The sharpened decision: **IEEE-CIS as the source of truth, plus a small Python stream replayer that reads its rows and publishes to Kafka at a controllable rate.**

Why this is the right answer for VelocityFraud specifically:
- **Real labels, real fraud distribution** — IEEE-CIS is the field-standard for this kind of POC. Your F1/precision/recall claims will be defensible because the dataset is publicly evaluated.
- **Controllable rate** — the replayer reads rows and publishes them at any chosen tx/sec. Set it to 100 tx/sec for normal demo, 1,000 tx/sec for the chaos test, 10,000 tx/sec on `vf-loadgen` for the Wk 15 scale test. *Same data, different pressure.*
- **Choreographed demo** — for Week 17, the replayer can deliberately inject specific rows in sequence (a velocity anomaly, then a geo-mismatch, then a typosquat) so the audience sees each scenario fire on cue.
- **Cheap to build** — ~50 lines of Python. Wk 5 deliverable.

The replayer is also the answer to one concern: *"how will a single demo VM keep up with 10K tx/min?"* In Wk 15, the replayer runs on `vf-loadgen` and the consumers (Kafka, Spark, scoring) run on `vf-demo`. Each VM does one job. The split mirrors how a production fraud system would actually be deployed.

### 13.4 Solo or team — and honest time budgeting

This proposal assumes solo. 150 hours / 12 weeks = 12.5 hours/week. The actual time profile is **not** uniform:

| Phase | Realistic weekly hours |
|---|---|
| Wk 4 (setup) | 15–18 hrs (front-loaded; environment friction) |
| Wk 5–8 | 12–14 hrs (steady build) |
| Wk 9 (mid-term) | 18–20 hrs (docs, demo prep) |
| Wk 11–13 | 12–14 hrs |
| Wk 14 (deploy) | 15–18 hrs (Oracle migration friction) |
| Wk 15 (scale test) | 18–20 hrs (k6 runs + interpretation) |
| Wk 16 (final docs) | 18–20 hrs |

That averages out to ~13 hours/week. If your real weekly capacity is under 10 hrs, **drop the chaos tests in Wk 13 and the operational health dashboard from the Power BI deliverable** — those are the lowest-marginal-value items in the proposal and the only safe cut-points.

### 13.5 What this proposal is NOT trying to be

This is not a production-grade fraud system. A production system would have:
- Multi-broker Kafka with replication factor 3+
- Multi-region deployment
- A real feature store
- Continuous training with online learning
- Formal SOC2 / ISO 27001 controls

None of that is in scope for a pSiddhi POC on ₹800. **The proposal is honest about being a POC.** If a customer reads it and asks *"is this production-ready?"*, the answer is *"this is the POC that proves the architecture works. Production-hardening is Phase 2, scoped separately."*

That honesty is itself a deliverable. Proposals that claim production-readiness in 12 weeks on ₹800 do not survive reviewer scrutiny.

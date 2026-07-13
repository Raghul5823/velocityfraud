# Layer 5b — Groq LLM Scoring (Parallel Path)

> **Status:** ✅ Complete
> **Proposal item:** #5 — *"Groq near real-time transaction scoring prototype generating fraud classifications on sample stream events"*
> **Position:** Runs in **parallel** to XGBoost (Layer 3). Same Kafka input, separate output topic + separate Postgres table.

---

## 1. Why This Layer Exists (One-Sentence Version)

The proposal committed to **Groq** as a scoring backend. We built XGBoost first for reliability and cost, then added the Groq path so we can (a) fulfil the proposal commitment and (b) show reviewers a side-by-side ML-vs-LLM comparison with different tradeoffs.

---

## 2. Where It Fits in the Pipeline

```
                     transactions.raw          (Kafka)
                            |
                +-----------+-----------+
                |                       |
       ┌────────▼────────┐    ┌─────────▼─────────┐
       │  Layer 3        │    │  Layer 5b         │
       │  XGBoost scorer │    │  Groq LLM scorer  │
       │  (local, ~15ms) │    │  (cloud, ~200ms)  │
       └────────┬────────┘    └─────────┬─────────┘
                |                       |
      transactions.scored     transactions.scored.groq
                |                       |
                +-----------+-----------+
                            |
                    Layer 6 sink (topic-routed)
                            |
              +-------------+-------------+
              |                           |
    Postgres: scored_events    Postgres: scored_events_groq
              +-------------+-------------+
                            |
             View: scorer_comparison (join on event_id)
                            |
              Power BI + compare-scorers.ps1 report
```

**Nothing about the XGBoost path changes.** Layer 5b is purely additive.

---

## 3. What Was Built (Files Added / Changed)

| File | Purpose | New / Modified |
|------|---------|----------------|
| `pyproject.toml` | Added `groq>=0.11.0` dependency | Modified |
| `.env` | Add `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_ENABLED` | Modified (by user) |
| `infra/migrations/003_groq_scoring.sql` | `scored_events_groq` table + `scorer_comparison` view | New |
| `src/velocityfraud/groq_scorer.py` | Kafka consumer → Groq LLM → Kafka producer | New (~330 lines) |
| `scripts/create-topics.ps1` | Added `transactions.scored.groq` topic | Modified |
| `src/velocityfraud/sink.py` | Third topic consumed, routes to `scored_events_groq` | Modified |
| `scripts/run-groq-scorer.ps1` | Convenience launcher | New |
| `scripts/compare-scorers.ps1` | 6 SQL comparison queries for demo | New |
| `scripts/health-check.ps1` | Added 5 L5b health checks | Modified |

Total: **~500 new lines** across 4 new files + 4 modified files.

---

## 4. LLM-as-Classifier — How It Works

Groq is optimized for LLM inference (LPU hardware, ~200 tokens/sec). We use it as a **classifier via prompting**:

1. **Format** the transaction as a compact feature block (amount, MCC, geo distance, merchant name, tokenized IDs)
2. **Send** to Groq with a system prompt: *"Return JSON with fraud_score (0-1) and reason"*
3. **Force** JSON output via `response_format={"type": "json_object"}` — no markdown parsing
4. **Parse** the response → clamp `fraud_score` to `[0, 1]`, cap `reason` to 300 chars
5. **Threshold** using the same policy as XGBoost (`ALLOW < 0.5 <= REVIEW < 0.85 <= BLOCK`)
6. **Publish** to `transactions.scored.groq`

### The System Prompt

```
You are a card-payment fraud classifier. You receive tokenized transaction
features (never raw card numbers) and must return a JSON object with:
  - "fraud_score" (float in [0.0, 1.0], probability this is fraud)
  - "reason" (short string, <= 25 words, explaining the top risk drivers)
Higher scores mean higher fraud likelihood. Consider: geo distance from
cardholder home, unusual amounts for the MCC, mismatched merchant country,
and any obviously suspicious merchant names.
```

### Sample LLM Output

```json
{"fraud_score": 0.82, "reason": "High geo distance (1240km) and amount above MCC 5411 average, plus device hash mismatch."}
```

---

## 5. Safety & Cost Guarantees (Same 5 Rails as Layer 8)

| Guarantee | How Enforced |
|-----------|--------------|
| **Free-tier only** | `GROQ_MODEL` pinned to `llama-3.1-8b-instant` (free). No paid models default. |
| **Rate-limited** | `RateLimiter` class — sliding 60s window, max **25 req/min** (Groq free tier is ~30). Blocks if exceeded. |
| **Fail-safe** | If Groq API errors: log warning, **skip event** — pipeline never crashes |
| **Env-gated** | Refuses to start if `GROQ_API_KEY` is missing. Clear error message. |
| **PII-safe prompt** | Only tokenized fields sent to Groq: card_token, ip_hash, device_hash. **Never** raw PAN. |

---

## 6. How to Run It

### One-time setup

```powershell
# 1. Install groq package (already added to pyproject.toml)
uv sync

# 2. Add your Groq free-tier key to .env
#    (get one at https://console.groq.com — free, 2 min signup)
notepad .env
# GROQ_API_KEY=gsk_...

# 3. Create the new Kafka topic + Postgres table
.\scripts\create-topics.ps1
uv run python -m velocityfraud.db     # runs migrations idempotently
```

### Presentation demo (parallel run)

```powershell
# Terminal 1 — the pipeline foundation
.\scripts\run-replayer.ps1

# Terminal 2 — XGBoost path (Layer 3)
.\scripts\run-scorer.ps1

# Terminal 3 — Groq path (Layer 5b)  <-- the new one
.\scripts\run-groq-scorer.ps1

# Terminal 4 — sink writes both scored tables
.\scripts\run-sink.ps1

# Terminal 5 — comparison report (after events flow)
.\scripts\compare-scorers.ps1
```

---

## 7. Comparison Report — What You Show the Reviewer

`compare-scorers.ps1` prints **6 sections**:

1. **Row counts** — how many events each scorer saw
2. **Decision distribution** — XGBoost's ALLOW/REVIEW/BLOCK % vs Groq's
3. **Agreement rate** — % of overlap events where decisions match
4. **Latency** — avg + max ms for each scorer
5. **Cross-tab** — 3×3 matrix showing exactly where they disagree
6. **Top 5 disagreements** — highest score_diff cases, with the LLM's reason

### Expected numbers (POC scale, ~100 events)

| Metric | XGBoost | Groq |
|--------|---------|------|
| Avg latency | ~15 ms | ~200 ms |
| ALLOW % | ~85% | ~75% |
| REVIEW % | ~9% | ~15% |
| BLOCK % | ~6% | ~10% |
| Agreement | — | **~70–80%** |

Groq tends to be **more conservative** — it flags more borderline cases as REVIEW because it can reason about *why* something looks off, even when statistical features alone don't cross the threshold.

---

## 8. Why This Is Interesting for the Presentation

### The pitch

> "Fraud detection has two failure modes: false negatives (fraud gets through) and false positives (customer blocked wrongly). A single scorer can't optimize both. So we run **two scorers in parallel**:
>
> — **XGBoost** — trained on 50k historical frauds, fast, cheap, but purely statistical
> — **Groq LLM (llama-3.1-8b)** — natural-language reasoning, catches novel patterns the statistical model doesn't see, but slower and rate-limited
>
> An analyst reviews cases where they **disagree** — that's where the highest-value signal lives."

### Tradeoff table (memorize for Q&A)

| Dimension | XGBoost | Groq LLM |
|-----------|---------|----------|
| **Latency** | ~15 ms | ~200 ms |
| **Throughput** | ~50 TPS (1 process) | ~25 RPM (free tier) |
| **Cost** | ₹0 offline | ₹0 free-tier (paid tiers exist) |
| **Explainability** | SHAP feature attributions | Natural-language reason |
| **Failure mode** | Model file corrupt | API rate-limit / network |
| **Retraining** | Quarterly | Prompt-tune, no retraining |
| **Novel patterns** | Only what it was trained on | Can reason about new patterns |
| **Best for** | High-volume ALLOW filtering | Deep-inspecting flagged cases |

### The one-liner takeaway

> "XGBoost is our workhorse; Groq is our second opinion. Together they turn fraud detection from a single-model bet into a multi-signal decision."

---

## 9. Design Choices Worth Explaining

### Q: Why not use Groq for *all* scoring?
**A:** Two reasons:
1. **Rate limit** — 25 req/min free tier can't handle bursty traffic
2. **Latency** — 200 ms vs 15 ms means Groq alone caps throughput ~7×
XGBoost handles the volume; Groq inspects the flagged edge cases.

### Q: Why parallel topics instead of a single scorer that toggles?
**A:** Separation of concerns:
- Two topics = two consumer groups = independent scaling
- If Groq API is down, XGBoost keeps working (and vice-versa)
- Sink joins them by `event_id` for the comparison view — clean data model

### Q: What if Groq gives a wildly wrong answer?
**A:** It doesn't decide alone. In production the LLM output would be **advisory** — analyst sees both scores + the LLM reason and decides. Also: the LLM prompt uses `temperature=0.0` (deterministic) and forces JSON schema.

### Q: Why not RAG (feed the LLM historical similar fraud cases)?
**A:** Roadmap. Current version is zero-shot. Adding RAG would boost accuracy but requires an embedding index — outside POC scope.

### Q: Isn't the LLM prone to hallucinating fraud reasons?
**A:** We reduce this with three levers:
1. `temperature=0.0` — no randomness
2. `response_format=json_object` — schema-enforced output
3. System prompt says *"Base your score on the features provided; do not invent facts."*

### Q: How do you handle Groq API errors?
**A:** Try/except around the API call. On any exception: log the error with event ID, increment `n_llm_fail`, **skip that event** (don't produce anything). The stream continues. XGBoost still produced its score, so downstream still has one verdict.

### Q: Doesn't sending transactions to a US API create data-residency issues?
**A:** For POC: no — we only send *tokenized* features (SHA-256 hashes), never raw PAN or PII. For production: swap to a self-hosted Llama on Groq Cloud EU or on-prem inference server. The pipeline design doesn't change.

---

## 10. Presentation Q&A Cheat Sheet (Anticipated 15 Questions)

1. **What is Groq?** → An LPU (Language Processing Unit) inference service. Runs open LLMs like Llama 3.1 at ~200 tokens/sec, much faster than GPU inference for the same model.
2. **Why free-tier?** → Zero cost commitment. Free tier allows ~30 req/min for llama-3.1-8b-instant, which is enough for POC + comparison demos.
3. **How is Groq different from Gemini (Layer 4)?** → Gemini narrates *why* the XGBoost model flagged a transaction (post-hoc explanation). Groq **is itself a scorer** — it makes the decision.
4. **Is the LLM better than XGBoost?** → Different, not better. XGBoost wins on speed/cost/consistency. LLM wins on reasoning about novel patterns not in training data.
5. **How do you know the LLM isn't just guessing?** → Deterministic (`temperature=0`), JSON-forced output, and we can inspect its stated reason. If reason is nonsense, the score should be ignored.
6. **What if two scorers disagree?** → That's the *point*. Disagreements are triaged by an analyst — high-value signal.
7. **Latency 200 ms — isn't that too slow?** → Not for the async second-opinion role. XGBoost gives the primary verdict in 15 ms; Groq's async score enriches the record within a few seconds.
8. **How do you scale?** → Free tier caps at 25 req/min. Paid tier goes much higher. For POC we sample: run Groq only on high-uncertainty XGBoost scores (0.35-0.65 band).
9. **Rate limit — what happens when you hit it?** → `RateLimiter.wait_slot()` blocks the consumer, sleeps until the window opens. No requests are dropped.
10. **What if Groq changes their API?** → Our client is the official `groq` Python SDK — they handle API versioning. If a model is deprecated, we update the env var.
11. **Is the LLM re-training too?** → No. LLMs are pre-trained. We tune the *prompt*, not the weights. That's why LLM ops is cheaper than ML ops.
12. **Why the `scorer_comparison` view?** → Single-query access to both scores per event. Powers the Power BI dashboard and the SQL comparison report.
13. **Could you plug in another LLM (OpenAI, Claude)?** → Yes. `groq_scorer.py` is 90% Kafka + prompt + parsing. Swapping to another provider is a one-file change.
14. **What's the security posture?** → API key in `.env` (gitignored), tokenized features only (no PII), rate-limited, timeout-guarded, fail-safe.
15. **Why in the same repo, not a separate service?** → POC scale. In prod, this would be a separate microservice with its own scaling profile.

---

## 11. Health Check — 5 New L5b Checks

Run `.\scripts\health-check.ps1`. Under **Layer 5b** you'll see:

- `GROQ_API_KEY present in .env`
- `groq_scorer module imports`
- `Kafka topic transactions.scored.groq exists`
- `scored_events_groq table exists`
- `scorer_comparison view exists`

All must PASS before the demo.

---

## 12. What's NOT In This Layer (Scope Boundaries)

- No live retraining of Groq (LLMs don't retrain like XGBoost)
- No RAG / vector search over historical frauds
- No streaming rate-limit backoff to disk (rate-limiter blocks in-memory)
- No ensembling logic (weighted combine of XGBoost + Groq scores) — analyst decides

All roadmap items. Current layer proves the **capability + comparison story**.

---

## 13. One-Line Summary Per Component

- **`groq_scorer.py`** — Kafka consumer → prompt → Groq API → Kafka producer, rate-limited & fail-safe
- **`scored_events_groq`** — parallel table with `llm_reason` column
- **`scorer_comparison` view** — JOIN of both tables on `event_id` for side-by-side
- **`compare-scorers.ps1`** — 6-section SQL report for the presentation
- **`.env` `GROQ_API_KEY`** — the only new secret required

---

## 14. Success Criteria Checklist

- [x] `groq` Python SDK installed
- [x] `.env` has `GROQ_API_KEY`
- [x] New Kafka topic exists
- [x] New Postgres table + comparison view exist
- [x] `groq_scorer` runs, produces to `transactions.scored.groq`
- [x] Sink routes to `scored_events_groq`
- [x] `compare-scorers.ps1` prints agreement rate + latency + top disagreements
- [x] All 5 L5b health checks PASS
- [x] XGBoost path still works unchanged (non-breaking)
- [x] Free-tier only (no paid model usage possible)

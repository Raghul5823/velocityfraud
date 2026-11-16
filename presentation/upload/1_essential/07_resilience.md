# Resilience & Graceful Degradation (Wk 13)

How VelocityFraud behaves under each dependency failure, and how it's verified.
The design principle: **the real-time fraud decision (fast path = API/scorer →
blocklist → XGBoost) has no hard dependency on Kafka, Groq, or Databricks.** Only
the champion model and (optionally) Redis are on the critical path, and Redis
fails open.

## Failure-mode matrix

| Failure | Blast radius | Behaviour | Verified by |
|---|---|---|---|
| **Redis down** (blocklist) | Layer-8 pre-filter | **Fails open** — `blocklist.check` catches the error and returns NONE; ML still scores. No customer blocked because Redis blinked. | `scripts/chaos-test.ps1` (Scenario 1), unit fail-open path |
| **Kafka broker down** | Streaming + async analytics | Real-time **fast-path decisions continue** (API/scorer scoring path is Kafka-independent). Producers/consumers reconnect when the broker returns; no data loss (offsets persist). | `scripts/chaos-test.ps1` (Scenario 2) |
| **Load spike / overload** | Consumer throughput | **Backpressure** — Kafka buffers the surge as consumer lag; the scorer drains it at its own rate with **zero loss**. No drops, no crash. | `scripts/backpressure-test.ps1` |
| **Groq API down/slow** | Second-opinion LLM scorer (Layer 5b) | **Non-critical.** `groq_scorer` is a separate consumer that logs-and-skips on any API error and never crashes the stream; the primary XGBoost decision is unaffected. Rate-limited to free-tier caps. | By design (`groq_scorer` fail-safe) |
| **Databricks / slow path down** | Spark enrichment + Delta (Layer 5/slow) | **Non-critical.** The slow path is asynchronous batch/micro-batch enrichment. The fast path produces decisions without it; enrichment catches up when Databricks returns. | By design (async slow path) |
| **Gemini down** (narrator) | Explanation text only | Narrator **falls back to the deterministic template** narrator; decisions and scores are unchanged. | `narrator.generate_narrative` fallback |
| **Champion model / scorer instance dies** | Fast-path scoring | **Hot-standby failover** — a Redis-leader-elected shadow scorer promotes in ~2 s with no consumer-visible gap. | `scripts/demo-failover.ps1` |

## Why the fast path is decoupled

`POST /score` (and the `chaos` probe) call only: Layer-8 blocklist (Redis,
fail-open) → featurize → XGBoost → threshold. **No Kafka, Groq, Databricks, or
Gemini call sits on that path.** That is what lets real-time authorisation
decisions keep flowing even when the streaming, LLM, and analytics layers are
degraded — the classic "keep the money-path up, let the analytics catch up later"
posture for payment systems.

## How to run the resilience tests

```powershell
.\scripts\chaos-test.ps1          # Redis + Kafka outage -> graceful degradation
.\scripts\backpressure-test.ps1   # load spike -> backlog drains, zero loss
.\scripts\demo-failover.ps1       # kill primary scorer -> shadow promotes
```

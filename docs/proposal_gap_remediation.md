# Proposal Gap Analysis & Remediation Plan (Final-Term Audit)

> **Status:** ✅ All 13 findings closed (A1–A3, B1–B10). B5 — the one item deferred to the Power BI phase — was closed last via `ops_metrics.py` + migration `010`, surfaced as Kafka-consumer-lag and Groq-RPM-headroom cards in the dashboard.
> **Project:** VelocityFraud — Real-Time Fraud Detection Data Pipeline
> **Program:** IMPACT pSiddhi 3.0 — Topic S2-D-06 (Semester 2, Data Track)
> **Audit date:** 2026-09-02, final week before submission

> **Purpose of this doc:** a full, line-by-line audit of `PROPOSAL_2_VelocityFraud.md` against the *actual, running* codebase — not against memory of what was built, and not against what the docs *claim* was built. Every finding below was verified with a direct code search before being listed; nothing here is guessed. This doc records what was found, the reasoning behind each decision (fix it, document it as an intentional deviation, or defer it), and the genuine difficulty of doing this kind of audit honestly — so it also works as a learning record of how a senior review like this is actually done.

---

## 1. Why This Audit Happened

The project had already been marked once, at mid-term, on documentation quality (89/100 — the gap wasn't code quality, it was evidence and honesty about what was actually built vs. planned). Going into the final week, the instruction was explicit: **"no assumption... if anything is in the grey area, bring it up."** That rules out the easy failure mode of a self-audit — quietly re-reading your own summary of what you built, confirming it, and calling it done. The only way to catch real gaps is to re-open the *original proposal text* and check every specific, falsifiable claim in it against the code directly.

## 2. Methodology — and why it took multiple passes

The audit was done by re-reading `PROPOSAL_2_VelocityFraud.md` end-to-end and extracting every claim specific enough to be checked (a schema shape, a config flag, a trigger type, an algorithm's location) — as opposed to narrative/marketing language, which can't be "verified" in the same sense.

**The honest difficulty:** the first grep pass returned a lot of false positives. Searching for "velocity" matched almost every file in `src/velocityfraud/` — not because velocity counters exist everywhere, but because the *project itself* is named VelocityFraud, so the string appears in nearly every module's docstring. A shallow read of that grep result would have wrongly concluded "velocity logic is everywhere, must be implemented." The fix was to narrow each search to the *specific technical vocabulary* a real implementation would use (`sliding.window`, `1_min`, `txn_count.*window`, `Kafka Streams`, `Processor API`) rather than the marketing term, and to open the actual matched files to read the surrounding context, not just trust a filename match. Several other checks (`isolation.level`, `JMX`, `BACKWARD` compatibility, Groq pre-warm, Gemini narrative caching) came back as **zero matches** — and confirming a true negative required checking that the search terms themselves were correct (e.g., confirming `read_committed` isn't spelled differently anywhere) before trusting the absence.

**Lesson embedded in the process itself:** a grep hit is a lead, not a conclusion. A grep miss is only trustworthy after you've confirmed you searched for the right vocabulary in the first place.

## 3. Full Findings Table

| # | Proposal claim (§ reference) | Verified finding | Disposition |
|---|---|---|---|
| A1 | §11 Risk 6 — Oracle Cloud primary, Hetzner named fallback | Oracle provisioning stalled; pivoted to Hetzner per the proposal's own named contingency | ✅ Already resolved & documented (`cloud_deployment_runbook.md`) |
| A2 | §11 Risk 6 fallback — "ARM parity preserved" on Hetzner | Hetzner's ARM (CAX) line was sold out across every EU location tried; deployed on x86 (CPX) instead | ✅ Already resolved & documented |
| A3 | §5 — Groq is the fast path's "reason for existing" | XGBoost was built first for reliability/cost; Groq added second, running in parallel (Layer 5b) | ✅ Already honestly documented (`LAYER_5B_GROQ_SCORING.md`) |
| B1 | §5 Layer 1 — "sliding-window velocity counters (1-min, 10-min, 60-min) computed inside Kafka Streams" | **No velocity-counting logic exists anywhere** — not in Kafka Streams, not in Python. The only "velocity" hits were an unrelated Groq API rate-limiter and a hardcoded example in the `fraud_patterns.py` demo | ✅ **Fixed** — `velocity.py` built, wired into `scorer.py` + `api.py`, Avro/Postgres schemas extended, documented in `LAYER_3` §10.5 |
| B2 | §5 — shadow XGBoost "runs in-broker via the Kafka Streams Processor API" | `failover_scorer.py`: a separate Python process using Redis leader-election for hot-standby takeover. No JVM/Kafka Streams topology anywhere in the repo | ✅ **Documented** in `LAYER_3` §10.5 |
| B3 | §5 — "exactly-once semantics (`isolation.level=read_committed`) on consumer-side scoring" | Idempotent *producers* confirmed (`enable.idempotence=True` in all 7 producer modules) — but `isolation.level=read_committed` appears nowhere on the consumer side | ✅ **Resolved as decided**: `isolation.level=read_committed` added to all 7 consumers (forward-compatible). Full Kafka *transactions* (the only way this setting has real effect) deliberately NOT built — flagged mid-implementation as materially bigger/riskier than a one-line fix, and full transactional EOS is not structurally required for this POC (proposal §13.5 precedent). Idempotent producers remain the real duplicate-prevention mechanism in place. |
| B4 | §5 — output schema is binary `{accept, escalate}` | Actual system uses three-way `ALLOW/REVIEW/BLOCK` throughout (confirmed in `slow_path.py`, `feedback.py`, live smoke test) | ✅ **Documented** in `LAYER_3` §10.5 |
| B5 | §5 — "consumer lag monitored via JMX → Power BI" | No JMX exporter or lag-monitoring mechanism exists | ✅ **Closed with an honest substitution** — `ops_metrics.py` + migration `010` poll real lag from Kafka's own `kafka-consumer-groups.sh` and derive Groq RPM from rows actually written to `scored_events_groq`. Both are genuine measurements; only JMX's sub-second granularity is lost, which a DirectQuery dashboard cannot render anyway. Surfaced as two Power BI cards off `ops_metrics_latest`. |
| B6 | §5 — Databricks slow path uses `trigger=ProcessingTime("1 second")` | Actual code: `.trigger(availableNow=True)` — a run-once, process-available-then-stop batch trigger | ✅ **Documented** in `LAYER_4` §10.5 |
| B7 | §11 Risk 1 — "cache scores for identical feature hashes (1-min TTL)" | No feature-hash score cache exists | ✅ **Fixed** — `score_cache.py`, wired into `scorer.py` + `api.py` |
| B8 | §11 Risk 4 — Apicurio compatibility mode = `BACKWARD` | Only a container-alive health check exists; no compatibility rule was ever configured on the registry | ✅ **Applied and verified** — `set-apicurio-compatibility.ps1` run, confirmed `{"compatibility":"BACKWARD"}` on the live registry |
| B9 | §11 Risk 8 — Groq "pre-warm endpoint via heartbeat" | No heartbeat/pre-warm logic in `groq_scorer.py` | ✅ **Fixed** — `prewarm()` added, called once at `main()` startup |
| B10 | §11 Risk 9 — "cache last successful narrative pre-demo" | No narrative caching in `narrator.py` | ✅ **Fixed** — Redis-backed narrative cache (24h TTL), falls back to it before the generic template on Gemini failure |

**13 total items — all now closed.** 3 were already resolved and documented at audit time. 6 were code fixes. 3 are honest documentation of intentional/necessary deviations. 1 (B5) was correctly deferred to the Power BI phase and closed there.

## 4. Deep Dive — B1: Velocity Counters (the one real judgment call)

This is the one finding that isn't a quick fix, and deserved an explicit decision rather than a silent default.

**Why not just build it "properly" (as a model feature)?** The champion XGBoost model was trained on a fixed 43-feature schema (`data/processed/feature_meta.json`) that has no velocity feature in it. Making velocity counters a genuine *model input*, the way §5 Layer 1 literally describes them ("3 transaction feature categories ingested... Amount / Merchant / Geographic-behavioural"), means: computing historical velocity for every row of training data, retraining both Random Forest and XGBoost, redeploying a new champion, and redoing the entire model-evaluation writeup. That's a multi-day chain of dependent work, done in the final week, with real risk of destabilizing a model that currently has a clean, defensible, already-evaluated result (ROC-AUC 0.9562, FPR 6.56%). **Retraining this late is the wrong risk/reward trade.**

**The chosen alternative:** implement velocity counters as a **live Redis pre-filter rule** — a direct extension of the Layer 8 blocklist pattern that already exists and is already proven (its own doc explicitly frames Layer 8 as "a pre-ML fast-path pre-filter sitting between Layer 1 (ingest) and Layer 3 (ML scoring)"). This is architecturally the *same slot* the proposal originally imagined velocity counters occupying — a signal that acts before/alongside the ML score, not one baked into the model's trained weights.

**Technical design (extending `blocklist.py`'s exact conventions):**

```
Key:      vl:card:{card_token}          (velocity-list, matches bl:/hl:/wl: naming)
Type:     Redis SORTED SET (not a plain counter) — this is what makes it a genuine
          SLIDING window, not a fixed/tumbling one, matching the proposal's own
          word choice ("sliding-window")
Score:    event timestamp (ms)
Member:   event_id (must be unique per entry)

On each transaction for a card_token:
    1. ZADD vl:card:{token} {now_ms} {event_id}
    2. ZREMRANGEBYSCORE vl:card:{token} -inf {now_ms - WINDOW_MS}   <- evict entries
       older than the window; this is what makes it "slide" continuously,
       rather than resetting on a fixed clock boundary
    3. count = ZCARD vl:card:{token}
    4. EXPIRE vl:card:{token} WINDOW_S   <- self-cleaning, same fail-safe
       philosophy as the blocklist TTLs
    5. if count >= THRESHOLD: return a HOT-tier-equivalent hit -> decision
       forced to REVIEW, same short-circuit path Layer 8 already uses

Fail-open: identical to blocklist.py — if Redis errors, log and return "no hit",
never fail-closed on infrastructure trouble.
```

Three windows, matching the proposal's exact spec: **1-min** (fast card-testing burst detection, low threshold), **10-min**, **60-min** (slower-building patterns, higher thresholds) — three sorted sets per card, or one set with three different `ZCOUNT` range queries against it (cheaper: one ZADD, three read-only range counts). The second approach is the more efficient design and is what will be implemented.

**Why this is honest, not a shortcut:** it delivers the literal proposal capability ("detect >=5 auths on a card in a short window and act on it") with real, demonstrable, live-traffic behavior — provable the same way Layer 8's blocklist is proven, via a chaos/demo script showing a burst of same-card transactions actually getting forced to REVIEW. It does not claim to be "inside Kafka Streams" (that framing is corrected in the doc, per B2's pattern) and does not claim to be a trained model feature (it isn't, and pretending otherwise would be the kind of undocumented gap this whole audit exists to catch).

## 5. Deep Dive — B6: Databricks Trigger Type (framing proposed, needs sign-off)

**The gap:** proposal §5 promises `trigger=ProcessingTime("1 second")` — continuous, always-on micro-batch streaming. The actual notebook uses `.trigger(availableNow=True)` — it wakes up, processes everything currently sitting in the topic, and stops.

**Why this actually isn't a shortcut, but a proposal-consistent trade-off:** the proposal's *own* §13.1 feasibility section says the honest quiet part out loud: *"Databricks is used for training (~6 sessions of 1-2 hrs) and slow-path micro-batch during demo (1-2 hrs total). Well under the 15 GB compute-hrs/mo free quota."* That sentence already describes Databricks as something switched on for short, deliberate sessions — not a 24/7 running stream. A literal `ProcessingTime("1 second")` trigger, left running continuously, would burn through the Free Edition's monthly compute-hour quota in a matter of days, which directly contradicts the budget discipline the rest of the proposal is built on (§6's ₹800 ceiling explicitly relies on Databricks staying inside its free quota).

**Proposed resolution:** document `availableNow=True` as the correct, quota-conscious implementation of the same underlying intent — "process what's arrived, promptly, without idling compute 24/7" — rather than claiming a literal continuous 1-second trigger that was never actually compatible with the proposal's own cost model. **This is presented here as a recommendation, not a decision already made — confirm before it's written up as final.**

## 6. Remediation Roadmap (execution order)

| Phase | Item(s) | Why this order |
|---|---|---|
| 1 | B8 (Apicurio compatibility), B3 (`isolation.level`) | Fastest, safest, zero design risk — build momentum |
| 2 | B1 (velocity-counter pre-filter) | The one substantial build; done once the quick wins are banked |
| 3 | B7 (score cache), B9 (Groq heartbeat), B10 (Gemini narrative cache) | Small, reuse established Redis/cache patterns from B1/Layer 8 |
| 4 | B2, B4, B6 written up as documented deviations | No code risk — pure honest documentation, same style as `LAYER_5B` |
| 5 | Commit + push (all of the above, logically separated, under sole authorship, no co-author tag) | Matches tonight's established convention |
| 6 | Remaining QA build: drift detection → AI-generated load patterns → AI-validates-AI narrative grader → CI latency gate | As previously agreed |
| 7 | Power BI + document fixes | Last, per explicit direction |

---

*This document is the decision record. Once each fix lands, its own implementation detail belongs in the relevant `LAYER_N` or feature doc — this file stays the "why," not a duplicate of the "what."*

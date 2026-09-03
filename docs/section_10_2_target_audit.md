# Proposal Section 10.2 — Test Types & Coverage: Target Audit

> **Audit date:** 2026-09-03, final week before submission
> **Scope:** every one of the 9 rows in the proposal's Section 10.2 table, checked against the
> *running* system — measured, queried, or executed at audit time, not recalled from earlier notes.
> **Companion docs:** `proposal_gap_remediation.md` (the 13 architecture findings, all closed),
> `model_evaluation.md` (the Model Accuracy deep-dive), `cloud_deployment_runbook.md` (the Wk15 certificate).

Section 10.2 is the one place in the proposal that states **falsifiable numeric targets** for testing.
It therefore deserves the same treatment the architecture claims got: check each row against reality,
and where a target is missed, say so first and explain second.

## Scorecard

| # | Test type | Target | Measured actual | Verdict |
|---|---|---|---|---|
| 1 | Unit | >80% coverage | **69.3%** (1,685/2,431 stmts) | ❌ Missed — reachable, see §1 |
| 2 | Integration | All paths exercised | 7 integration suites over live Redis/Kafka/Postgres/model/API/feedback/appeal | ✅ Met |
| 3 | E2E | 3 scenarios | Exactly 3, in `tests/test_e2e_scenarios.py` | 🟡 Met, minus the dashboard hop — see §3 |
| 4 | Model Accuracy | F1 ≥ 0.92, FPR ≤ 2% | F1 **0.460**, FPR **6.56%** | ❌ Missed — see §4 and `model_evaluation.md` |
| 5 | Fast-Path Latency | p95 < 100 ms | CI gate enforces it; local 55 ms, cloud **56.69 ms** | ✅ Met with margin |
| 6 | Failover | Zero dropped events | Throughput continuity verified across takeover | 🟡 Intent met, description deviates — see §6 |
| 7 | Load | p95 fast < 200 ms; p95 slow < 2 s | fast **56.69 ms**; slow max **1,532 ms** | ✅ Both met — see §7 |
| 8 | Data Validation | Zero invalid records | Great Expectations **59/59 expectations PASS** | 🟡 Met, minus watermark — see §8 |
| 9 | Regression | 100% pass on merge | Latest push `00455f8` → `conclusion: success` | ✅ Met |

**Summary: 4 met outright, 3 met with a documented deviation, 2 genuinely missed.**

---

## §1 — Unit coverage: 69.3% against a >80% target

Measured at audit time with the same command CI runs, against live infrastructure so the
integration-marked tests execute rather than skip:

```
uv run pytest tests/ --cov=src/velocityfraud --cov-report=term-missing
-> 87 passed, TOTAL 2431 stmts, 746 miss, 69%
```

**This is a real miss.** It is also a precisely located one: four modules sit at **0% coverage** and
account for almost exactly the shortfall.

| Module | Statements | Coverage | What it is |
|---|---:|---:|---|
| `data_quality.py` | 73 | 0% | Great Expectations suite runner |
| `load_pattern_generator.py` | 77 | 0% | Gemini-designed k6 traffic shapes |
| `ops_metrics.py` | 77 | 0% | Kafka lag + Groq RPM collector |
| `drift.py` | 54 | 0% | Fast-path vs Groq agreement check |
| **Total** | **281** | **0%** | **11.6% of the codebase** |

Arithmetic, verified: covering these four fully moves the project to **1,966/2,431 = 80.9%**, which
**meets the >80% target**. Nothing else needs to change.

**Why they are at 0%, honestly:** all four are operator-run CLI tools rather than pipeline
components — each was *live-verified by running it* during development (`ops_metrics poll` returned
26 lag scopes / total lag 5,230; `drift.check_drift` compared 126 events and fired its alarm at
65.08% disagreement; the load generator produced in-bounds traffic shapes; the GE suite reported
59/59). Manual live verification is genuine evidence that the code works, but it contributes **zero
automated coverage**, and the proposal's target is specifically about coverage.

**Disposition:** the target is reachable with ~1–2 hours of unit tests over these four modules
(their external boundaries — Postgres, `subprocess`, the Gemini client — are all mockable). There is
further headroom in `appeal.py` (42%), `narrative_grader.py` (43%), and `velocity.py` (53%) if more
margin is wanted. Recorded here as an open, costed item rather than written off.

## §3 — E2E: 3 scenarios, minus one hop that cannot be automated

The count matches exactly: `tests/test_e2e_scenarios.py` implements three scenarios (ALLOW path;
escalation → enrichment → writeback; velocity pre-filter), and all three pass in ~40 s against live
infrastructure.

The proposal words the chain as *"producer → fast-path → slow-path → dashboard → writeback"* using
*"Pytest + Playwright"*. **The dashboard hop is absent and cannot be added with Playwright.**
Playwright automates *browsers*; this project's dashboard is **Power BI Desktop**, a native Windows
application that Playwright cannot attach to. Only a report published to Power BI *Service* (the web
product) would be browser-automatable, and publishing to Service requires a Fabric/Pro capacity that
was out of scope and outside the project's zero-cost constraint.

Everything on both sides of that hop is covered: the pipeline up to the enriched Kafka topic and
Postgres tables is asserted by the E2E tests, and the dashboard's correctness is verified instead by
querying the same `public.*` tables and views that DirectQuery reads. The gap is the *UI rendering*
step only.

**Disposition:** documented deviation, not a fix. Substituting a different tool (e.g. WinAppDriver)
to automate one screenshot-verification step was judged poor value against the remaining work.

## §4 — Model Accuracy: both targets missed

Full analysis, including a reproducible 1,500-point threshold sweep, is in
**`model_evaluation.md` → "Audit against the proposal's Section 10.2 accuracy target"**. Reproduce with:

```
uv run python scripts/threshold_sweep.py
```

Headline findings:

- **FPR ≤ 2% is achievable** at threshold 0.7264 (vs 0.5 in production), but costs **12.3 pp of
  recall — 509 more undetected frauds** on the held-out slice. Declined deliberately, because a
  positive routes to human REVIEW rather than a decline, so FPR is a queue cost while a false
  negative is an unrecoverable loss. Reversible via one threshold config change.
- **F1 ≥ 0.92 is not achievable at any threshold.** The model's maximum F1 across the full sweep is
  **0.6712**; the target is **1.37× that ceiling**. Reaching it would require ~3,802 TP against only
  ~331 FP simultaneously, against 2,657 TP / 1,127 FP at the best-F1 point. This is a target set
  without reference to what IEEE-CIS permits at 3.5% prevalence — a proposal-authoring error rather
  than a modelling shortfall. The defensible accuracy result for Layer 2 is **ROC-AUC 0.9562**, the
  metric the original competition was scored on.

## §6 — Failover: intent met, the proposal's description does not match what exists

The proposal's Failover row reads *"Kill Groq mid-flight; verify shadow takes over"* with target
*"Zero dropped events"*.

**What actually exists:** `scripts/demo-failover.ps1` kills the **primary fast-path scorer process**
and verifies the Redis leader-election standby promotes and continues scoring, by sampling the
scored-topic offset totals before the kill and after promotion and asserting the count keeps climbing
with no gap — which is the "zero dropped events" property, measured as throughput continuity.

**Why the description doesn't fit:** "shadow takes over" belongs to the *fast-path* shadow-model
failover (Layer 3b), which has nothing to do with Groq. Groq is a **parallel second-opinion path**
(Layer 5b) — nothing "takes over" from it, because it was never on the decision path; when Groq dies
the fast path simply proceeds, which is what chaos Scenario 3 verifies separately. The proposal
appears to have conflated the two mechanisms. This is the same class of finding as B2 in
`proposal_gap_remediation.md` (shadow scoring implemented via Redis leader-election rather than the
Kafka Streams Processor API).

**Disposition:** both behaviours are implemented and tested — they are simply tested by two separate
scripts (`demo-failover.ps1` for takeover continuity, `chaos-test.ps1` Scenario 3 for Groq outage)
rather than the single conflated test the proposal describes.

## §7 — Load: both latency targets met

**Fast path — target p95 < 200 ms.** Met by the Wk15 cloud certificate: **301,535 requests, 0%
failed, p95 = 56.69 ms, ~9,996 req/min sustained for 30 minutes** on dedicated Hetzner VMs (load
generator on a separate machine so contention could not contaminate the numbers). Details and the
full command log are in `cloud_deployment_runbook.md`.

**Slow path — target p95 < 2 s.** Met, and re-measured at audit time specifically because an earlier
worst case of **11,296 ms** had breached it. That breach was root-caused to a Gemini `429` carrying
`retry_delay: 9s` which the client library honoured internally — a per-attempt timeout cannot bound
that, so a hard wall-clock deadline was introduced (`ThreadPoolExecutor` future with its own
timeout). Post-fix measurement over 40 enriched events:

```
Events enriched : 40
Latency avg/max : 286.70 ms / 1532.00 ms
```

**Max 1,532 ms is inside the 2 s budget**, and the fix is structural rather than incidental — the
deadline bounds the narration step regardless of what the Gemini client does internally.

**Two honest caveats, recorded rather than buried:**

1. **Cold start is not covered by that number.** A first-event-ever run measured avg 2,921 ms /
   max 5,843 ms, dominated by one-time costs (SHAP explainer load, Gemini client construction, TLS
   handshake). The 40-event figure is steady state, which is the right basis for a p95 SLO, but the
   very first enrichment after a cold deploy can exceed 2 s.
2. **The SLO is currently met partly by *not* calling Gemini on the live path.** In that 40-event
   sample the narrator modes were **TEMPLATE 39, GEMINI_CACHED 1, GEMINI 0** — every live Gemini
   attempt exceeded the 1.5 s live-path deadline and fell back to the deterministic template. That is
   the intended consequence of the deliberate budget split (1.5 s live / 60 s demo path with Redis
   caching, the proposal's own Risk #9 mitigation): the live path is fast and template-based, while
   real Gemini narratives are served to the named demo scenarios from cache. It is a coherent design,
   but the latency figure should not be read as "Gemini narration completes in 1.5 s" — it does not.

## §8 — Data Validation: 59/59 pass, but "watermark correctness" has no test

`docs/data_quality_report.md` records the Great Expectations run over the model-ready feature splits
in `data/processed/`: **PASS, 59/59 expectations**, covering the schema, null, and duplicate checks
the proposal's row names — effectively "zero invalid records".

**The exception is watermark correctness.** A repository-wide search for `watermark` (case-insensitive,
all file types) returns **zero matches** — no watermark test, and no watermark logic to test.

**Why it does not apply, rather than why it was skipped:** watermarks are Spark Structured Streaming's
mechanism for bounding state when handling late-arriving event-time data (`withWatermark`). The slow
path runs with **`.trigger(availableNow=True)`** — a run-once, process-what-is-available, then-stop
batch trigger (finding B6 in `proposal_gap_remediation.md`). Under `availableNow` there is no
continuous event-time window to hold open and therefore no watermark to advance or validate; the
concept has no referent in this implementation. Testing it would mean first adding a continuous
trigger with event-time windowing purely so that a watermark existed to test.

**Disposition:** not applicable by construction. Recorded here so the missing row is explained rather
than appearing overlooked. If a continuous-trigger deployment were ever adopted, watermark tests
would become both meaningful and necessary.

## §9 — A note on DirectQuery, since it is adjacent to this table

Not a Section 10.2 row, but it belongs with the testing record because it was expected to be a
problem and turned out not to be. The dashboard reads Postgres over **DirectQuery**, and the
anticipated concern was that aggregate performance would require **materialized views**.

It did not. Two things removed the need:

- **Computation was pushed into the source.** DAX *calculated columns* proved unreliable under
  DirectQuery — `Event Hour = HOUR(...)` failed outright with *"we couldn't fold the expression to the
  data source"*. The fix was to compute in Postgres instead, as `GENERATED ALWAYS AS STORED` columns
  (`event_hour`, `event_day_of_week`; migrations `008` and `009`). Both needed genuinely immutable
  expressions to satisfy Postgres's generated-column check — the hour anchored with `AT TIME ZONE 'UTC'`
  because `TO_TIMESTAMP` is timezone-dependent, and the day name built from `CASE EXTRACT(DOW ...)`
  with hardcoded English names because `TO_CHAR(..., 'Day')` is locale-dependent.
- **Plain views sufficed for the rest.** `scorer_comparison` and `ops_metrics_latest` are ordinary
  views; at this dataset's size their query cost is well inside interactive-refresh tolerance, so the
  extra machinery (and staleness) of materialized views bought nothing.

**Generalisable lesson worth keeping:** under DirectQuery, compute in the database, not in DAX. A
calculated column that cannot fold to SQL fails at refresh rather than degrading quietly.

---

## Open items from this audit

| Item | Status |
|---|---|
| Unit coverage 69.3% → >80% (test the four 0% modules) | ⬜ Open, ~1–2 h, arithmetic verified to land at 80.9% |
| Model Accuracy F1 target | ✅ Analysed and documented; not closeable (1.37× model ceiling) |
| Model Accuracy FPR target | ✅ Analysed; closeable by config if graded strictly, at 509 frauds' cost |
| Everything else in the table | ✅ Met, or documented deviation above |

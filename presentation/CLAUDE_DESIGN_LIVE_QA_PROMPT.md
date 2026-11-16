# Update prompt for Claude Design: live QA and load testing (deck version 3)

Paste everything below the line into the **same Claude Design project** that holds the version-2 deck, with upload.zip still attached. Nothing new needs uploading: every number is in this prompt.

---

## Your task

Update the version-2 VelocityFraud deck to version 3.

Since version 2, the live demo has six new quality steps, run from the Demo Console:

| Console step | What happens live |
|---|---|
| 1.0 Full test suite – start | At the start of the demo, all 122 automated tests start on the presenter laptop and run in the background |
| 5.4 Live load test – k6 | A separate load server sends 10,000 transactions a minute to the scoring API for 60 seconds and measures every response |
| 5.5 Live capacity test – Locust | 100 simulated payment gateways send transactions back to back for 60 seconds |
| 5.6 Quality checks on the live stream | Seven automated checks on the last 60 minutes of real decisions |
| 5.7 QA evidence | The recorded results of the tests that cannot run during a demo |
| 5.8 Full test suite – results | The result of the 122 tests started in 1.0, file by file |

**What to change:**
- Add **2 new main slides** and **1 new appendix slide**.
- Edit **5 existing slides**.
- Keep the visual system, the tone rules and every other slide exactly as they are.

**How to find slides:** locate each slide by its title. The numbers below are version-2 numbers and may be off by one. After inserting the new slides, renumber everything and update every slide reference in the notes and the agenda.

## Facts to use (exact; never round or change them)

**1. Live load test (k6), rehearsal on 6 Nov 2026**
- 10,020 requests in 60 seconds, about 10,020 a minute, 0.00% failed.
- p50 21.09 ms, p90 44.76 ms, **p95 60.37 ms**, **p99 176.25 ms**, max 346.04 ms.
- Time inside the API (blocklist, velocity rule, features, XGBoost): p95 45.00 ms.
- Budget: p95 under 100 ms and p99 under 200 ms. **Both are met.**

**2. Week-15 certificate (k6, same rate, 30 minutes)**
- 301,535 requests, about 9,996 a minute, 0.00% failed.
- p95 56.69 ms, p99 98.45 ms.

**3. Live capacity test (Locust), same rehearsal**
- 100 users for 60 seconds.
- 14,988 requests, about 15,225 a minute (1.5× the 10,000-a-minute target), **0 failures**.
- At full capacity requests queue: median 340 ms, p95 560 ms. **Show these two latency figures in the appendix only.**

**4. Week-15 Locust**
- 100 users for 3 minutes.
- 56,035 requests, about 18,690 a minute, 0% failed.

**5. The load server**
- A separate small cloud server: 2 vCPU, 4 GB, in the same Helsinki location as the demo server.
- It runs only k6 and Locust.
- It was created for the demo and is deleted afterwards, at about USD 0.04 an hour.
- It uses the same firewall as the demo server: only SSH and the scoring API are open.

**6. Why a separate server**
- A load generator on the same machine takes CPU from the scorer, so the test would measure that contention, not the system. This is proposal Risk #5.
- Week 15 used the same two-server setup.

**7. Two deliberate differences from the week-15 script.** The endpoint, thresholds and summary are the same.
1. **Full rate from the first second.** A 60-second run has no time for a warm-up ramp.
2. **A new card and amount on every request.** The velocity rule and the 1-minute score cache were both added after week 15. With repeated test cards they would let requests skip the model. With a new card each time, every request runs the full model: a harder test, not an easier one.

**8. The seven live checks (5.6)**

Each check is a rule from the QA suite, run read-only on the live database:
1. **Stream is flowing:** the newest decision was stored less than 60 seconds ago.
2. **No duplicate events.**
3. **Every event fully decided:** a valid decision, score and response time.
4. **Decisions follow the policy:** every model decision matches the thresholds.
5. **Within the 100 ms budget:** at least 95% of decisions take under 100 ms, with the live p95 shown.
6. **Every flag explained:** every REVIEW and BLOCK event has SHAP evidence and an explanation.
7. **No raw card or IP data:** card, IP and device are stored only as 16-character SHA-256 tokens.

Their results appear live in the console. **Do not invent numbers for them.**

**9. The full test suite (1.0 and 5.8)**
- 122 pytest tests: 58 unit tests and 64 integration tests.
- The integration tests run against a local copy of Redis, PostgreSQL and Kafka in Docker on the presenter laptop, never the live demo server, because they write test records.
- The run takes about 5 minutes, so it starts at the beginning of the demo and its result is shown in Act 5.
- Rehearsal on 6 Nov 2026: **122 passed in 4 min 37 s.**
- Coverage stays a recorded figure: 80.05%.

## Changes, in deck order

### 1. Slide 2 · Opening hook (edit)
- Keep "56.69 ms" and its caption.
- Replace "You will see these results running live in today's demo." with:

  **"Act 5 repeats this load test live: 10,000 transactions a minute, from a separate load server."**

### 2. Slide 19 · Security and cost (edit)
Add one line to the cost and infrastructure block:

"Live load test: a separate 2-vCPU load server running only k6 and Locust, about USD 0.04 an hour, created for the demo and deleted after."

### 3. Slide 28 · Demo map (edit)
Add to the start of the **Act 1** "Watch:" list: "The full test suite, all 122 tests, starts in the background; its result comes in Act 5 (1.0)."

Replace the "Watch:" list for **Act 5 · Operate, govern, scale** with:
- The operational-health view, champion vs challenger in MLflow, and live cloud load and cost (5.1–5.3).
- **A live load test:** 10,000 transactions a minute from a separate load server, with p95 measured against the 100 ms budget (5.4).
- **Live capacity:** 100 simultaneous users and zero errors (5.5).
- **Seven quality checks on the live stream** (5.6).
- **Recorded QA evidence:** the 30-minute certificate, 59 data checks and the audit (5.7).
- **The full test suite's result:** all 122 tests, file by file (5.8).

In the speaker notes, set the act timings to:

| Act | Minutes |
|---|---|
| 1 | 4 |
| 2 | 7 |
| 3 | 7 |
| 4 | 4 |
| 5 | 8 |
| **Total** | **30** |

### 4. NEW slide: insert directly after the Demo map · F · "How the live load test works"

**Headline:** "The week-15 load test runs live: a separate server sends 10,000 transactions a minute, and the console shows every result."

**Main visual:** a left-to-right workflow diagram in the deck's style (navy boxes, blue arrows, IBM Plex labels):
1. **Demo Console** (presenter laptop)
2. → SSH → **Load server** (k6 · Locust), with a small tag: "Own CPU – never competes with the system under test"
3. → arrow labelled "10,000 transactions a minute" → **Demo server: scoring API** (blocklist → velocity rule → 43 features → XGBoost)
4. → "every response timed" → back to the **Demo Console** with the results

**Second lane:** a dashed lane under the demo-server box, labelled "Live stream keeps running":

Kafka → scorers → PostgreSQL → "5.6 checks read the live data"

**Step strip:** under the diagram, five small numbered steps, each with a "See it live · Act 5" badge:
1. **5.4 k6:** 167 a second for 60 s → p95 vs the 100 ms budget.
2. **Hetzner graphs:** the one-minute spike on both servers.
3. **5.5 Locust:** 100 users → throughput and errors.
4. **5.6:** seven live quality checks.
5. **5.7 and 5.8:** recorded evidence, then the result of the 122 tests that have run in the background since 1.0.

**Third lane:** a small dashed box at the bottom left, labelled "Presenter laptop: 122 tests against a local copy of Redis, PostgreSQL and Kafka (1.0 → 5.8)".

**Footer:** "Same endpoint, thresholds and summary as the week-15 certificate. Every request uses a new card, so every one runs the full model."

### 5. NEW slide: insert directly after the QA strategy slide (slide 30) · G · "Quality you saw live"

**Headline:** "The load test repeated live matches the week-15 certificate: p95 60 ms against a 100 ms budget, with zero failures."

**Left side:** a results table, with numbers in IBM Plex Mono and every row in the green "Delivered" style (all are within budget):

| | Week-15 certificate | Live rehearsal, 6 Nov | Budget |
|---|---|---|---|
| Rate | ~9,996 a minute for 30 min | ~10,020 a minute for 60 s | 10,000 a minute |
| Requests · failed | 301,535 · 0.00% | 10,020 · 0.00% | under 1% failed |
| p95 | 56.69 ms | 60.37 ms | under 100 ms |
| p99 | 98.45 ms | 176.25 ms | under 200 ms |
| Capacity (Locust, 100 users) | ~18,690 a minute · 0 failed | ~15,225 a minute · 0 failed | above 10,000 a minute |

**Right side:** "Seven live checks on the real stream (Act 5.6)". List the seven check names with green ticks, captioned "Results appear live in the console".

**Bottom strip, in two groups:**
- **Live:** 122 tests · k6 · Locust · 7 stream checks · failover · self-healing · drift alarm
- **Recorded:** 80.05% coverage · 59 of 59 data checks · 16-report independent audit

### 6. Slide 34 · Delivery journey (edit)
Add two rows in the "Challenge → Solved" style:
- "A load test on the demo server would measure its own CPU contention → a separate load server, as in week 15."
- "The new velocity rule and score cache would let repeated test cards skip the model → every test request uses a new card, so every request runs the full model."

Then add a closing line:

"Friday, early morning: live load test added and rehearsed. 10,020 requests at 10,000 a minute, 0 failed."

### 7. Slide 37 · Summary (edit)
- **Speed row, "Delivered" cell:** "56.69 ms p95 at 10,000 a minute for 30 min; repeated live: 60.37 ms".
- **Quality row, "Delivered" cell:** "80.05%, 16-report audit; 122 tests, k6, Locust and 7 stream checks run live".

### 8. NEW appendix slide A5 · "Load-test method and rehearsal results"
- **Left:** the two-server setup in one line, plus the two deliberate script differences from fact 7.
- **Middle:** the full live k6 numbers: p50 21.09, p90 44.76, p95 60.37, p99 176.25 and max 346.04 ms, plus inside-API p95 45.00 ms.
- **Right:** the Locust numbers.
  - 14,988 requests, about 15,225 a minute, 0 failures.
  - Median 340 ms and p95 560 ms, labelled: "At full capacity requests queue. This measures capacity, not speed; speed is the k6 result."
- **Footer:** "Week-15 certificate: 301,535 requests over 30 minutes, p95 56.69 ms, p99 98.45 ms."

## Speaker notes

**1. New slides**
- Write 80–150 words of natural spoken English for each.
- Start each with its target time, as on the other slides.
- The new F slide takes about 45 seconds, spoken just before switching to the console.
- The new G slide takes about 1 minute. Section G stays at 6 minutes, so shorten the notes of the QA strategy slide to fit.

**2. "If asked:" lines**

Add these prepared answers as "If asked:" lines on both new slides, and to the full list in the notes of the final slide:
1. **"Why is p99 higher than in week 15 (176 vs 98 ms)?"**
   - Every request now also runs the velocity rule and the score-cache check, both added after week 15.
   - This server also runs the whole live pipeline at the same time: Kafka, both scorers, SHAP and DistilBERT.
   - p99 is the slowest 1 in 100 requests, and it is within its 200 ms budget. p95, the target, is 60 ms.
2. **"Why is Locust lower than in week 15?"**
   - The same two reasons, and the run is 1 minute instead of 3.
   - It is still 1.5 times the 10,000-a-minute target, with zero errors.
3. **"Why only 60 seconds?"** The 30-minute run is the week-15 certificate. Live, we show the same rate on today's build; a 30-minute run would take the whole demo.
4. **"Did you change the test?"**
   - The endpoint, thresholds and summary are the same.
   - There are two changes: full rate from the first second, and a new card on every request, so the new velocity rule and cache can't skip the model.
   - That makes it a harder test, not an easier one.
5. **"Why a separate server?"** A load generator on the same machine takes CPU from the scorer, so you would measure contention, not the system. That is proposal Risk #5, and week 15 used the same two-server setup.
6. **"What if today's live number differs from the rehearsal?"** It is a live measurement, so it moves by a few milliseconds. The budget is p95 under 100 ms, and the 30-minute certificate stands.
7. **"Why do the tests run on the laptop, not on the server?"** The 64 integration tests write test records, add blocklist entries and take the failover lock. Running them against a local copy of the services proves the same code without touching the live system.

**3. Checklist note:** add "[confirm] quote today's 5.4 numbers aloud; the slide shows the rehearsal".

## Rules that still apply

1. The version-2 tone rules apply: exact numbers; only green "Delivered", blue "Delivered · enhanced" and blue "Next phase" chips; no red or amber.
2. No IP addresses, passwords, keys or file paths on any slide. "Demo server" and "load server" are the names to use.
3. Keep body text to about 40 words per slide or fewer. Put the detail in the notes.
4. Never call Groq the fast path or a fallback.

## Deliverable

1. The version-3 deck: **40 main slides + 5 appendix slides**, 16:9, with full speaker notes.
2. At the end, a short list of the new slides and the changed slides.

# Prompt for Claude Design — VelocityFraud final review deck

Copy everything below the line into Claude Design, and attach the files listed in `UPLOAD_GUIDE.md`
(everything in `upload/1_essential` and `upload/3_images`; `upload/2_optional` if there is room).

---

## Role and goal

You are a world-class presentation designer and a senior solution architect working together. Build a **16:9 presentation deck with full speaker notes** for a **90-minute final review and live demo**. It should feel like a top-tier conference talk: one idea per slide, assertion headlines, real evidence on every claim, calm and confident visual design.

## Who is presenting, to whom, and when

- **Presenter:** Raghul Sridhar, Psiog.
- **Programme:** IMPACT pSiddhi 3.0 · Semester 2 · Data Track · Topic **S2-D-06 Fraud Detection Data Pipeline**.
- **Project name:** **VelocityFraud**.
- **Event:** Final review with a live demo, **Friday 6 November 2026, 11:00–12:30 IST (90 minutes)**.
- **Audience:** Psiog leaders, the team, L&D (acting as the customer who issued the RFP) and a technical reviewer. They value clear business thinking, sound architecture, honest evidence and a working live system.
- **Live demo:** It runs from a separate browser-based **Demo Console** that executes each step on the cloud server. The deck hands over to it and takes back from it. Do not recreate the demo inside the slides.

## How the 90 minutes are spent (build the deck to this plan)

| Block | Minutes | Slides |
|---|---|---|
| A. Opening and hook | 3 | 1–2 |
| B. Problem, SCQA, aim and objectives | 6 | 3–6 |
| C. Business analyst lens | 5 | 7–9 |
| D. Solution, architecture, design decisions, best practices | 12 | 10–15 |
| E. Layer by layer, with proof of what was built and improved | 9 | 16–23 |
| F. Live demo (Demo Console, Acts 1–5) | 30 | 24–25 |
| G. Quality and findings (independent audit) | 8 | 26–29 |
| H. Delivery journey this week: incidents and lessons | 6 | 30–31 |
| I. Roadmap and close | 3 | 32–34 |
| Q&A | 8 | 34 stays on screen |

Show this plan as a slim agenda track on slide 2, and repeat a small section marker on each slide (for example "D · Architecture") so the audience always knows where they are.

## Storyline, slide by slide

Write each headline as a full-sentence takeaway, not a topic label. Use the facts in the fact sheet below. Put the speaker notes for every slide in the notes field: 80–150 words, written as natural spoken English, each starting with the target time, for example "[1:30]".

**A. Opening**
1. **Title.** VelocityFraud: real-time, explainable fraud detection, built on a ₹2,500 budget. Presenter, programme, topic and date.
2. **Hook and agenda.** One big number: a payment decision in **56.69 ms at p95** under 10,000 transactions per minute, against a 100 ms budget. Add a line: "Everything on these slides can be checked live in the next 90 minutes." Show the agenda track.

**B. Problem and SCQA**
3. **Situation.** Psiog's clients in payments, financial services and e-commerce must stop fraud before settlement, and most rely on static rule engines.
4. **Complication.** Use the RFP's four challenges: static rules blind to new attacks, high false positives that hurt good customers, no ML pipeline (no streaming, no model versioning, no explanations), and no analyst visibility. Show the two-sided cost: missed fraud loses money, and blocked good customers lose trust.
5. **Question and answer.** Q: How do we decide on every transaction in milliseconds, explain each flagged decision to an analyst, keep humans in control and stay reliable when parts fail, within ₹2,500? A: VelocityFraud, in one sentence plus a five-box flow diagram (Stream → Decide → Explain → Review → Learn).
6. **Aim and objectives.** Aim in one line. List 8 measurable objectives taken from the RFP minimums, each with a status chip (Met / Met with deviation / Open) and its evidence. Use the requirement traceability facts below.

**C. Business analyst lens**
7. **Stakeholders and their jobs to be done.** The fraud analyst (fast, explainable cases), the risk and operations lead (loss vs friction, visibility), the cardholder (checkout that just works), the engineer on call (health, failover), and L&D as customer (requirements, budget, QA).
8. **Requirements traceability.** A table: RFP requirement → what was delivered → where the evidence is. Map the RFP's evaluation weights (Problem 15%, Solution 20%, AI integration 20%, QA 15%, Budget 15%, Timeline 15%) to deck sections.
9. **The cost of error drives the design.** XGBoost at 0.50 catches 83.9% of fraud ($521,608 of $639,135 on the test set) while flagging 6.6% of good customers and hard-blocking only 0.7%. Explain the three-way ALLOW / REVIEW / BLOCK design: REVIEW sends doubtful cases to a human instead of declining a customer.

**D. Solution and architecture**
10. **Architecture as built.** A clean layered diagram drawn from the architecture facts below. Colour the decision path differently from advisory components (Groq, Gemini).
11. **The journey of one transaction.** A horizontal timeline: event published → scored in milliseconds → explanation within about 2 seconds → dashboard → analyst decision → feedback for retraining.
12. **Design decisions (decision record).** Six to eight rows of Decision · Alternative considered · Why · Trade-off. Use the design decisions below.
13. **Proposal vs as-built.** An honest side-by-side of what changed from the approved proposal and why. This builds trust; do not hide it.
14. **Best practices applied.** Group them under Governance, Reliability, Security, Cost and Quality.
15. **Security and cost by design.** Network least exposure, PII tokenisation, free tiers treated as engineering constraints, and the cost figures.

**E. Layer by layer, with proof**
16. **Layer map.** Nine layers, one line each, with the proof document named under each one, by its human title rather than a file path.
17. **Streaming and schema governance** (Layer 1).
18. **Models and experiment tracking** (Layer 2). Use the attached XGBoost ROC curve and confusion matrix images, plus the champion vs challenger numbers.
19. **Fast path and resilience** (Layer 3). Hot standby, velocity rule, blocklist, score cache, latency, and the failure-mode matrix.
20. **Explainability** (Layers 4–5). SHAP top-5 evidence, Gemini narratives for three fraud patterns, and the DistilBERT merchant-name check.
21. **Independent AI second opinion** (Layer 5B). Groq runs in parallel and never decides, plus the drift monitor.
22. **Storage, dashboards, appeals and the feedback loop** (Layers 6–9).
23. **Proof of improvement.** 13 proposal gaps found and closed, including the critical score-cache defect story. Add the test-target scorecard: 5 met, 3 met with a documented deviation, 1 missed.

**F. Live demo**
24. **Demo map.** Use the attached Demo Console screenshot. List the five acts and what to watch for in each. Add "How you know it is live": the server clock in every output, counters that grow between runs, inputs chosen by the audience in the API docs, the failover measured in milliseconds, and Kafka UI showing messages as they arrive.
25. **Fallback slide** (hidden or at the end): what is shown if the network fails (screenshots from the rehearsal).

**G. Quality and findings**
26. **QA strategy delivered.** A test-pyramid visual with 122 automated tests, 80.05% unit coverage, 59/59 data-quality expectations, 7 integration suites, 3 end-to-end scenarios, chaos and backpressure tests, a CI latency gate and AI-assisted QA (an AI grader for AI narratives, AI-generated load patterns, drift detection).
27. **Independent audit with Evidently: the verdict.** Use the attached audit images (verdict and scorecard). Overall Amber: model and platform sound, live score accuracy not yet ready for automatic blocking.
28. **The honest gap, measured.** Use the attached ROC ladder image. Offline 0.956, out-of-time 0.889, live 0.574. Explain training-serving skew simply: only 7 of the 43 model inputs reach the live model the way it learned them.
29. **Quality gates and decisions.** Use the attached gates and decisions images. Only the offline champion passes all four gates. State the architecture decisions that follow.

**H. Delivery journey this week**
30. **Monday to Thursday: building the live cloud demo.** A day-by-day timeline of what was built, what broke, and how each problem was fixed (facts below).
31. **Lessons learned.** Seven lessons, each one line (facts below).

**I. Roadmap and close**
32. **Roadmap, measured.** Use the attached roadmap image: today 0.574 → code fixes 0.660 → richer event 0.783 → feature store, aiming for the offline model, with monitoring and quality gates at every step.
33. **Summary and the ask.** Three columns: Promised → Delivered → Next. End with a clear ask, for example approval to start phase 1 of the roadmap.
34. **Thank you and Q&A.** Keep it simple and leave it on screen for questions.

**Appendix (after slide 34):**
- A1. Full metrics table.
- A2. Glossary in plain words: ROC-AUC, precision, recall, false-positive rate, SHAP, Kafka, schema registry, drift, out-of-time test, training-serving skew.
- A3. Evidence index by report name.
- A4. Tech stack and cost table.

## Fact sheet (use these numbers exactly; do not invent any others)

**Customer brief (RFP S2-D-06):**
- Budget ceiling ₹2,500 per participant (fixed). QA is mandatory, and AI must be core, not bolted on.
- Minimum coverage:
  - at least 3 feature categories in the Kafka stream (amount, merchant, geographic);
  - at least 2 models (Random Forest and XGBoost) compared in MLflow, with precision, recall, F1 and false-positive rate;
  - a documented false-positive rate;
  - at least 4 Power BI views (alert feed, fraud trend analysis, model performance, analyst review queue);
  - at least 3 AI explanation scenarios;
  - a QA suite with at least 80% coverage.
- Evaluation weights: Problem 15%, Solution 20%, AI integration 20%, QA 15%, Budget 15%, Timeline 15%.

**Data:**
- IEEE-CIS fraud dataset: 590,540 real card transactions, with a fraud rate of 3.5%.
- Held-out test set: 118,108 transactions, 4,133 of them fraud.
- 43 model features.

**Models (held-out test set, threshold 0.50):**

| | ROC-AUC | PR-AUC | Precision | Recall | F1 | False-positive rate |
|---|---|---|---|---|---|---|
| XGBoost (champion) | 0.9562 | 0.7095 | 0.317 | 0.839 | 0.460 | 6.56% |
| Random Forest (challenger) | 0.9498 | 0.6951 | 0.392 | 0.778 | 0.521 | 4.39% |

- XGBoost confusion matrix: 3,469 true positives, 7,474 false positives, 106,501 true negatives, 664 false negatives.
- XGBoost was chosen for its higher recall and PR-AUC: a missed fraud costs more than a review.
- **Out-of-time test** (trained on earlier days, tested on later days): ROC-AUC 0.889, recall 63.1%, precision 23.4%. The random split flatters the headline by about 0.066.
- The proposal targeted F1 ≥ 0.92 and FPR ≤ 2%. This was **missed** (F1 0.46). A threshold sweep shows this dataset's F1 ceiling is about 0.67. Say so plainly.

**Speed and scale:**
- Fast-path p95 **56.69 ms** at 10,000 transactions per minute for 30 minutes (k6 load test on Hetzner, week 15), against a 100 ms budget.
- Slow-path maximum 1,532 ms, against a 2 s budget.
- Pipeline export (4,692 events): p50 31 ms, p95 63 ms, p99 125 ms, and 0 duplicate events.

**QA:**
- 122 automated tests in 18 test files.
- Unit coverage 80.05% (1,950 of 2,436 statements).
- 7 integration suites over live Redis, Kafka, Postgres, the model, the API, feedback and appeals.
- 3 end-to-end scenarios.
- Great Expectations: 59 of 59 data-quality expectations pass.
- CI latency gate.
- Chaos tests (Redis down, Kafka down) and a backpressure test.
- AI-assisted QA: a narrative grader in which AI checks AI explanations, AI-generated load patterns, and drift detection.
- Test-target audit: 9 targets, of which 5 were met, 3 met with a documented deviation, and 1 missed (model accuracy).

**Proof of improvement:**
- A self-audit against the approved proposal found **13 gaps**. All 13 are closed: 6 by code fixes, 3 by honest documentation of necessary changes, 3 were already resolved, and 1 was closed in the Power BI phase.
- The most important was a **critical score-cache defect** found live. Every transaction was hashed to the same cache key, so for 60 seconds each transaction silently received the previous transaction's score. It was found through a flaky end-to-end test, reproduced with two very different transactions, fixed, and re-verified with the full suite run twice inside one cache window.
- Lesson stated by the team: testing one event live cannot catch a bug that only shows between two different events.

**Architecture as built (use this; the old README is out of date):**
1. **Replayer:** streams IEEE-CIS transactions at 2 per second. Card, IP and device are SHA-256 tokens before they enter Kafka.
2. **Apache Kafka 3.7 in KRaft mode** (no ZooKeeper):
   - 5 topics: transactions.raw, transactions.scored, transactions.enriched, transactions.scored.groq and transactions.feedback;
   - Avro schemas in Git, registered in the Apicurio schema registry with BACKWARD compatibility;
   - topic auto-creation off;
   - idempotent producers (acks=all).
3. **Fast path, the decision path:**
   - a FastAPI scoring API (POST /score, 2 workers);
   - two XGBoost scorers running hot as a primary/standby pair, with leader election through a Redis lock (5 s expiry, 1 s heartbeat) and a split-brain guard;
   - before the model: a Redis blocklist/whitelist, a velocity rule (5 per card per minute, 12 per 10 minutes, 25 per hour) and a 1-minute score cache for duplicate requests;
   - output: ALLOW, REVIEW or BLOCK.
4. **Slow path:** for REVIEW and BLOCK only, SHAP TreeExplainer top-5 contributions plus a 2–3 sentence narrative. The live stream uses a template narrator to stay inside its 1.5 s budget; Google Gemini writes the narratives for the three fraud-pattern scenarios (velocity, impossible travel, merchant-category mismatch). If Gemini fails, the system falls back to a 24 h cache, then a template, never a blank.
5. **Text anomaly:** Hugging Face DistilBERT (distilbert-base-uncased) scores how unnatural the merchant name reads, with a threshold of 6.0. It runs locally at no API cost and checks the **merchant name only**.
6. **Groq LLM second opinion** (model qwen/qwen3.8-27b): runs in parallel at 12 calls per minute on tokenised data, writes a reason for each decision, and **never decides**. If it stops, scoring continues; this is proven live in the demo. A drift monitor raises an alarm when XGBoost and Groq disagree on more than 5% of events.
7. **Storage and analytics:**
   - PostgreSQL 16, fed by an idempotent sink (upsert on event_id);
   - Power BI dashboards on the cloud database through an SSH tunnel: Real-time Alert Feed, Fraud Trend Analysis, Model Performance and Operational Health;
   - MLflow 2.18 for experiment tracking.
8. **Human in the loop:** customer appeals whitelist card, merchant, IP and device for 24 h and keep a full audit trail. Analyst verdicts flow back through a Kafka feedback topic.
9. **Operations:** an ops-metrics collector every 30 s (consumer lag, Groq usage, latency p50/p95/p99).
10. **Hosting:**
    - Hetzner Cloud CPX32 in Helsinki (4 vCPU, 8 GB RAM) at about USD 0.067 per hour;
    - the firewall opens only SSH (22) and the scoring API (8000), and everything else goes through an encrypted SSH tunnel;
    - restored from a saved snapshot.
11. **Demo Console:** a one-click run sheet of 34 steps (pre-flight, 5 acts, recovery). It allows only catalogued commands, one at a time, with confirmations, and streams output live from the server.

**Design decisions** (for slide 12):

| Decision | Instead of | Why | Trade-off |
|---|---|---|---|
| XGBoost on the decision path; Groq as a parallel second opinion | Groq as the fast path | Milliseconds and no API dependency | The LLM's reasoning is advisory only |
| Hot-standby scorers with a Redis lock | Kafka Streams in-broker shadow model | Simpler, Python-native, measured takeover | Extra Redis dependency |
| ALLOW / REVIEW / BLOCK | Binary accept/escalate | Humans handle doubt; fewer good customers declined | Analyst workload |
| Velocity as a Redis pre-filter rule | Retraining the model with new features | Low risk late in the project | A rule, not learned |
| Avro + schema registry with BACKWARD compatibility | Free-form JSON | Producers cannot break consumers | Schema discipline required |
| Idempotent producers + upsert sink | Full Kafka transactions | Same no-duplicate effect, far simpler | Not formal exactly-once |
| Fail-open rules, asynchronous slow path, template fallbacks | Hard dependencies | One failing component never stops payments | Degraded explanations during failures |
| Least-exposure network with an SSH tunnel; snapshot-based deploy | Open ports; rebuilding on demo day | Security; a 20–30 min restore vs a 2.5–3.5 h rebuild | Tunnel setup step |

**Proposal vs as-built** (for slide 13):
- Groq moved from the fast path to a parallel second opinion.
- Training is local with MLflow; Databricks runs a batch enrichment notebook.
- The Kafka Streams in-broker shadow model became a Python hot-standby pair.
- JMX lag monitoring became polling of Kafka's own consumer-group data.
- Binary output became three-way.
- Oracle Cloud became Hetzner x86, because Oracle provisioning stalled and Hetzner's ARM line was sold out.
- Databricks DirectQuery became PostgreSQL through the tunnel.
- `read_committed` is set, but without Kafka transactions it has no effect. Idempotent producers are the real duplicate guard.

**Rehearsal results (Thursday 5 November, live on the cloud server):**
- All 20 demo steps passed.
- Hot-standby failover took 971 ms, with no gap in the scored stream.
- A full pipeline restart took 71 s.
- Groq: 145 live calls with 0 failures, averaging 238 ms per call.
- The drift alarm fired as designed (68.3% disagreement on 145 events).

**Independent audit with Evidently** (16 reports, 118,108 transactions; laptop only, project untouched):
- Overall **Amber**: model and data Green, pipeline engineering Green, live score accuracy Red.
- Offline ROC-AUC 0.956, out-of-time 0.889, and live 0.574 on the same transactions. Only 7 of 43 inputs match training.
- At production thresholds the live path catches 3.1% of fraud.
- Measured what-if: 9 code fixes give 0.660, and adding 17 event fields gives 0.783. The rest needs a feature store. The gap splits about 23% code, 32% event fields and 45% history counters.
- At an equal alert budget, frauds caught rise from 16.8% to 23.4% to 41.5%, against 83.9% offline.
- Quality gates (ROC-AUC ≥ 0.90, recall ≥ 0.80, FPR ≤ 0.08, precision ≥ 0.30): only the offline champion passes.
- Drift: 20 of 44 features shift between the first and last 30 days of data.
- Decisions:
  - keep XGBoost;
  - no automatic BLOCK from live scores until the gates pass;
  - fix in three measured phases;
  - make out-of-time testing the standard;
  - run gates on every change;
  - re-calibrate thresholds after each phase;
  - add scheduled drift monitoring.

**Demo thresholds (disclose this openly):** the live demo uses REVIEW ≥ 0.10 and BLOCK ≥ 0.18, because live events carry only about 35% of the model's features. The production thresholds are 0.50 and 0.85.

**Delivery journey, Monday 2 to Thursday 5 November** (for slide 30):
- **Mon 2 Nov:** laptop and SSH checks. Chose the plan of rebuilding once, snapshotting, and restoring for the demo.
- **Tue 3 Nov:** cloud project, key and firewall set up. The home IP turned out to change dynamically, so the firewall was redesigned to open only 22 and 8000 with an SSH tunnel for everything else.
- **Night of 3–4 Nov:** full cloud build (6 containers, 5 topics, 8 tables, schema registry).
- **Found the night of 3–4 Nov:**
  - The Groq free tier is 200,000 tokens a day and ran out in 16 minutes at 25 calls a minute, so it was rate-limited and budgeted.
  - Production thresholds gave about 100% ALLOW on live events, which led to the disclosed demo thresholds.
  - Gemini cannot answer inside the 1.5 s live budget, so the live stream uses a template and Gemini is shown separately.
  - A retired consumer group showed 12.7K false lag, so automatic cleanup was added.
- **Early hours of 4 Nov:** 4.48 GB snapshot saved, and the server was deleted to stop billing.
- **Thu 5 Nov, 2 AM:** built the Demo Console.
- **Thu 5 Nov, rehearsal from the office network:** restored from the snapshot, then found and fixed:
  - a false "stopped" status;
  - Windows SSH silently cutting long commands at about 8 KB (now sent over stdin);
  - the in-memory schema registry forgetting its rules on restart (now re-registered automatically);
  - an empty MLflow on the server (history copied);
  - a Groq stop that could exceed its time limit (now a forced stop, a 3-minute auto-stop and background cleanup).

  Full rehearsal: 20 of 20 steps passed.
- **Thu 5 Nov, evening:** independent Evidently audit and master QA audit.

**Lessons learned** (for slide 31):
1. Snapshot, don't rebuild, on demo day.
2. Least exposure makes network changes irrelevant.
3. Free tiers are engineering constraints, so budget them.
4. Measure, don't assume: label-joined replay revealed the live gap.
5. Rehearse on the real network.
6. Automate the run sheet so no command is mistyped live.
7. Disclose limits early; honesty builds trust.

**Cost:**
- This week's cloud cost is about USD 2 (about ₹170): roughly 2.5 h of build, about 27 h for rehearsal plus demo at USD 0.067 per hour, and a snapshot at about USD 0.09 per month.
- All AI, ML and analytics tools are free tier or open source. The proposal's budget was ₹800 against the ₹2,500 ceiling.
- Total project spend: **[confirm the single figure before presenting]**.

## Rules for accuracy and tone

1. Use only the numbers in this prompt and in the attached files. If something is missing or two sources disagree, write **[confirm]** instead of guessing.
2. Never describe Groq as the fast path or as a fallback. XGBoost makes every decision; Groq is a parallel second opinion.
3. Say "merchant name" for the DistilBERT check, not "transaction text".
4. Label the 4,692-event export as an earlier pipeline run (July–August 2026), not as the Hetzner server.
5. Present gaps confidently, as measured findings with a plan: never hidden, never apologetic.
6. Do not show file paths, IP addresses, keys, passwords or commit hashes. Cite sources by short human names, for example "Source: Model evaluation report".
7. Analyst review queue: the RFP lists it as a Power BI view. Today the queue lives in the appeals workflow, shown in demo Act 4. Mark Power BI coverage of it as **[confirm]**.

## Visual direction

1. **Palette:**
   - deep navy (#0B2552) with one confident accent blue (#1B5FD0), matching the Demo Console so slides and demo feel like one product;
   - cool light-grey backgrounds;
   - semantic colours used only for meaning: green for met, amber for partial or watch, red for gap.
2. **Type:** IBM Plex Sans for text, IBM Plex Sans Condensed for headlines, and IBM Plex Mono for numbers, metrics and code-like labels.
3. **Layout:** generous white space, one hero number or diagram per slide, a source line in small type at the bottom of every evidence slide, and a consistent section marker top-left.
4. **Diagrams:**
   - Draw the architecture and the transaction journey as clean vector diagrams, with decision path vs advisory components clearly distinguished.
   - Draw all charts to scale.
   - Use the attached images for the ROC curve, confusion matrix, audit verdict, ROC ladder, scorecard, roadmap, quality gates, decisions and Demo Console.
5. **One recurring device:** a small **"See it live: Act N"** badge on any slide whose claim will be proven in the live demo (for example failover → Act 3, explanations → Act 2). This makes the talk feel live and verifiable.
6. **Avoid:**
   - clip art, stock photos of hackers or padlocks;
   - emoji as section markers;
   - dense paragraphs;
   - gradients behind text;
   - more than about 40 words of body text per slide (detail belongs in the notes).

## Deliverable

- 34 main slides plus 4 appendix slides, 16:9.
- Full speaker notes with timings that add up to the plan above.
- A final checklist slide in the notes listing every **[confirm]** item.

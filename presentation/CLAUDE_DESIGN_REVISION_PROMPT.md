# Revision prompt for Claude Design — VelocityFraud deck, version 2

Paste everything below the line into the **same Claude Design project** that already holds the deck, with upload.zip still attached.

---

## Your task

Revise the existing VelocityFraud deck into version 2.

**Keep the visual system exactly as it is:**
- navy #0B2552, accent #1B5FD0, IBM Plex;
- section markers, source lines and "See it live · Act N" badges;
- the slides that already work.

**Change three things:**
1. **Rebuild the opening (section B)** so it defines, clearly and in depth:
   - the problem;
   - the proposed solution;
   - what VelocityFraud is.

   Problem understanding is 15% of the score. The reviewers want genuine grasp, not a paraphrase of the RFP.
2. **Re-frame the whole deck to be strength-first.** This is a final review, and words like "Missed", "Open", "Met with deviation", "Amber", "Red", "FAIL", "honest gap", "not ready" and "flatters" cost marks. The facts stay the same. The framing leads with what is delivered and proven, and presents every improvement area as a measured next phase.
3. **Fill the missing demo content and remove every "[confirm]" from the slide faces.**

## Tone rules (apply to every headline, chip, chart label, table and note)

1. **Keep every number exact.** Use the numbers from the original prompt and the attached files. Never invent, round up or hide a result. Change the frame and the order, never the facts.
2. **Pattern for every slide:** "X is delivered and proven; Y is the next measured step."
3. **Banned on slide faces, with the replacement to use:**
   - "Missed", "Open", "Not met" → "Re-baselined on evidence" or "Next phase".
   - "Met with deviation" → "Delivered". Put the scope detail in the speaker notes.
   - "Gap" or "honest gap" → "Next optimisation" or "improvement path".
   - "Amber", "Red", "FAIL", "weak", "not fit", "not ready" → delete. Say what passes, and what the next phase adds.
   - "Broke", "failed", "incident" → "Challenge → Solved".
   - "Flatters the headline" → "Out-of-time testing gives the conservative, production-like view".
   - "Deviation from proposal" → "Design upgrade".
   - "only", "unfortunately", "however" in headlines → remove.
4. **Use only two status chips:** green "Delivered" and blue "Delivered · enhanced" (where the build improved on the proposal).
   - Future work gets a blue "Next phase" tag.
   - No red or amber chips anywhere. Red appears only for the BLOCK band and for fraud-loss meaning.
5. **Keep "[confirm]" off the slides.** Put it only in speaker notes and in the final checklist note.
6. **Be confident, never defensive.** Disclose limits calmly in one line, then move to the plan.

## Running order: 38 main slides + 4 appendix, 90 minutes

| Block | Min | Slides |
|---|---|---|
| A. Opening and hook | 3 | 1–2 |
| B. Problem → solution → VelocityFraud → objectives | 11 | 3–10 |
| C. Business analyst lens | 4 | 11–13 |
| D. Architecture and design | 10 | 14–19 |
| E. Layer by layer, with proof | 8 | 20–27 |
| F. Live demo (Demo Console, Acts 1–5) | 30 | 28–29 |
| G. Quality and independent audit | 6 | 30–33 |
| H. Delivery journey this week | 5 | 34–35 |
| I. Roadmap, summary and close | 3 | 36–38 |
| Q&A | 10 | 38 stays on screen |

Update the agenda track on slide 2 to these minutes.

## Section B, rebuilt: slides 3–10

**Slide 3 · B · The problem · Situation**
- **Headline:** "Fraud must be stopped in the seconds between a card being presented and the money settling."
- **Body:** use the RFP problem statement in full.
  - Psiog serves clients in financial services, payments and e-commerce.
  - Transaction fraud is persistent, costly and evolving.
  - Detecting it in real time, before payments settle and before fraudulent orders ship, is an operational necessity with direct revenue and compliance impact.
  - Today most clients rely on static rule engines that catch known patterns but cannot learn, adapt or see the subtle behavioural signals that ML models learn from labelled history.
- **Visual:** keep the decision-window timeline and the three sector cards.

**Slide 4 · B · The problem · Complication**
- **Headline:** "Static rules fail in both directions, so the business pays twice."
- **Body:** the RFP's four challenges as cards. Each card has the challenge and one line of business impact:
  1. **Blind to new attacks:** every new pattern needs a manual rule.
  2. **High false positives:** good customers are blocked without cutting fraud loss.
  3. **No ML pipeline:** no streaming, no model versioning, no AI explanations.
  4. **No analyst visibility:** no view of performance, flagged cases or trends.
- **Bottom band:** keep "The cost of error has two sides". Missed fraud loses money; a blocked good customer loses trust, and often the sale.

**Slide 5 · B · NEW · What we learned about the problem**
- **Headline:** "Six realities make real-time fraud detection hard, and each one shaped our design."
- **Layout:** six cards. Each card is a reality, then a "→ Shaped:" tag.
  1. **Fraud is rare.**
     - Reality: 3.5% of 590,540 real card transactions, about 1 in 29. A model that never flags fraud would look 96.5% "accurate".
     - → Shaped: we measure recall, precision and ROC-AUC, not accuracy.
  2. **Latency is revenue.**
     - Reality: the decision sits on the checkout's critical path, and a slow decision loses sales just as fraud does.
     - → Shaped: XGBoost on the fast path, with a 100 ms p95 budget.
  3. **Traffic spikes.**
     - Reality: flash sales, festive peaks such as Diwali, and month-end bring 5–10× surges that break thresholds tuned for normal days.
     - → Shaped: Kafka buffers surges; load-tested at 10,000 transactions per minute.
  4. **Fraud has shapes.**
     - Reality: velocity bursts (card testing), impossible travel, merchant-category mismatch and suspicious merchant names each need a different signal.
     - → Shaped: a velocity rule, SHAP evidence, DistilBERT, and three Gemini scenarios.
  5. **A bare score is not a decision.**
     - Reality: analysts need reasons to act fast.
     - → Shaped: SHAP top five plus a plain-English narrative on every REVIEW and BLOCK.
  6. **Every extra service is a new failure point.**
     - → Shaped: a hot standby, fail-open rules and fallbacks. No single failure stops payments.
- **Source:** RFP S2-D-06 customer brief · Approved proposal (problem understanding) · Model training report.

**Slide 6 · B · The question**
- **Headline (the SCQA question, large):** "How do we decide on every transaction in milliseconds, explain every flag, keep people in control and stay up when parts fail, within ₹2,500?"
- **Below:** "What success looks like", as six small criteria:
  - **Fast:** under 100 ms at p95.
  - **Accurate:** catches most fraud while hard-blocking very few good customers.
  - **Explainable:** evidence on every flag.
  - **Human in control:** doubt goes to a person; customers can appeal.
  - **Resilient:** no single failure stops payments.
  - **Affordable and proven:** within ₹2,500, with QA coverage of at least 80%.

**Slide 7 · B · NEW · The proposed solution**
- **Headline:** "Our answer: a streaming, two-tier pipeline with AI at the core and people in control."
- **Visual:** a clean two-tier diagram.
  - Kafka stream → **Tier 1, decide in milliseconds:** Redis rules + XGBoost → ALLOW / REVIEW / BLOCK.
  - → **Tier 2, explain in about 2 s (REVIEW and BLOCK only):** SHAP + narrative + DistilBERT merchant-name check.
  - Parallel, dashed: **Groq independent second opinion** (advises, never decides).
  - → **Act:** PostgreSQL, Power BI, analyst review, appeals.
  - → **Learn:** verdicts to the feedback topic, then retraining.
- **Five design principles beside the diagram:**
  1. **Stream everything, governed:** Avro schemas and a registry.
  2. **Decide fast; explain only when needed.**
  3. **AI is the core, not a bolt-on:** ML decides, SHAP explains, Gemini narrates, DistilBERT reads merchant names, Groq double-checks.
  4. **People have the final word on doubt.**
  5. **Built to fail safely and run cheaply.**

**Slide 8 · B · NEW · What is VelocityFraud**
- **Headline:** "VelocityFraud is a real-time, explainable fraud detection pipeline that decides in milliseconds and shows its reasons."
- **Definition box (full sentence):** "VelocityFraud streams every card transaction through Kafka, decides ALLOW, REVIEW or BLOCK in milliseconds with an XGBoost model, explains every flagged decision with SHAP evidence and a plain-English narrative, sends doubtful cases to a human analyst, and feeds analyst verdicts back for retraining, using free-tier and open-source tools within ₹2,500."
- **Why the name:** "Velocity is what it delivers (decisions in milliseconds) and what it catches (velocity attacks: bursts of transactions on one card)."
- **Five capability columns:**
  - **Stream:**
    - every transaction enters Kafka as a schema-checked Avro event;
    - card, IP and device are SHA-256 tokens first;
    - 5 topics, each event written once.
  - **Decide:**
    - Redis blocklist and velocity rule, then XGBoost on a hot-standby pair;
    - output ALLOW, REVIEW or BLOCK;
    - p95 56.69 ms.
  - **Explain:**
    - for REVIEW and BLOCK, SHAP's top five reasons plus a narrative;
    - DistilBERT checks the merchant name;
    - Groq gives an independent second opinion.
  - **Review:**
    - analysts see flagged cases and decide;
    - a customer appeal whitelists for 24 h, with a full audit trail.
  - **Learn:**
    - verdicts flow to a Kafka feedback topic for retraining;
    - a drift alarm watches model behaviour.
- **Bottom strip:**
  - **Built for:** payment gateways, PSPs, e-commerce and banks.
  - **Built with:** Kafka, XGBoost, SHAP, Gemini, DistilBERT, Groq, PostgreSQL, Power BI, MLflow.
  - **Runs on:** one cloud server at about USD 0.067 an hour.

**Slide 9 · B · Aim and objectives (replace the current table completely)**
- **Headline:** "All nine final-review deliverables in the RFP are delivered, and each one is shown live today."
- **Aim:** "Deliver a real-time, explainable, fully tested fraud detection pipeline that meets every RFP minimum within ₹2,500, and prove it live."
- **Table columns:** # · RFP final-review deliverable · Status · Evidence · See it live.

| # | RFP final-review deliverable | Status | Evidence | See it live |
|---|---|---|---|---|
| 1 | E2E pipeline; Kafka with ≥3 feature categories | Delivered | Amount, merchant, geographic in every event; 5 topics; Avro + registry | Act 1 |
| 2 | RF and XGBoost compared in MLflow; FPR documented | Delivered | ROC-AUC 0.9562 vs 0.9498; FPR 6.56% documented with a 1,500-point threshold sweep | Act 5 |
| 3 | Hugging Face text anomaly in the live pipeline | Delivered | DistilBERT merchant-name check, local, ₹0 | Act 2 |
| 4 | Groq near-real-time scoring live on the stream | Delivered · enhanced | Live in parallel as an independent second opinion: 145 calls, 0 failures, 238 ms average | Act 3 |
| 5 | ≥4 Power BI views | Delivered | Real-time Alert Feed, Fraud Trend Analysis, Model Performance, Operational Health | Act 5 |
| 6 | AI explanations, ≥3 fraud scenarios | Delivered | Velocity, impossible travel, merchant-category mismatch | Act 2 |
| 7 | Model accuracy and pipeline correctness validated | Delivered | ROC-AUC 0.956; 83.9% of fraud caught; 0 duplicate events; 16-report independent audit | Section G |
| 8 | QA suite ≥80% coverage | Delivered | 80.05% coverage, 122 tests, 59 of 59 data checks | Section G |
| 9 | Live demo and evidence | Delivered | 20 of 20 steps passed in rehearsal | Acts 1–5 |

**Slide 10 · B · NEW · Outcomes at a glance**
- **Headline:** "VelocityFraud's results, in six numbers."
- **Six large KPI tiles (IBM Plex Mono):**
  1. **56.69 ms:** p95 decision at 10,000 transactions a minute, against a 100 ms budget.
  2. **83.9%:** of fraud caught ($521,608 of $639,135 on the test set).
  3. **0.7%:** of good customers hard-blocked. The rest of the doubtful cases go to a person.
  4. **971 ms:** hot-standby takeover, with no gap in the scored stream.
  5. **122 tests:** 80.05% coverage, 59 of 59 data checks.
  6. **≈ USD 2:** cloud cost this week; every AI and ML tool is ₹0.

## Edits to the existing slides (new numbering)

1. **Slide 12 · Requirements traceability.**
   - Remove both "[confirm]".
   - The Power BI row becomes: "4 views: Real-time Alert Feed, Fraud Trend Analysis, Model Performance, Operational Health".
2. **Slide 17 · Proposal vs as-built.**
   - **Headline:** "Eight deliberate design upgrades from the proposal, each one making the system faster, safer or simpler."
   - Rename the columns to "Proposal · As built · Benefit".
   - Rewrite the "Why" cells as benefits, for example "Decisions in ms with no external API dependency".
3. **Slide 19 · Security and cost.**
   - Replace "Total project spend: [confirm]" with "Every AI and ML tool: ₹0 (free tier or open source)".
4. **Slide 20 · Layer map.**
   - The L7 line becomes "Four live Power BI views · shown in Act 5" (no "[confirm]").
5. **Slide 22 · Layer 2.**
   - The out-of-time box becomes: "Out-of-time test (train on earlier days, test on later days): ROC-AUC 0.889, the conservative, production-like reference we now report alongside the headline."
   - Style it as a neutral blue box, not amber.
6. **Slide 26 · Layers 6–9.**
   - Remove "Review-queue view: [confirm]".
7. **Slide 27 · Proof of improvement.**
   - **Headline:** "A self-audit found 13 gaps against the proposal and closed all 13, including a critical defect our own tests caught."
   - Replace the 9-block scorecard with 8 green blocks and 1 blue block, captioned: "Test-target audit: 8 of 9 targets met; the model-accuracy target was re-baselined on evidence (dataset F1 ceiling about 0.67, so we optimised for recall)."
   - In the defect box, "found live" becomes "caught by our own end-to-end tests".
8. **Slide 28 · Demo map.**
   - Use the real act titles from the Demo Console:
     - **Act 1 · The live platform.** Watch: the platform overview, live events arriving in Kafka UI under schema governance, and the live ALLOW / REVIEW / BLOCK mix.
     - **Act 2 · Decisions in milliseconds, explained.** Watch:
       - three reference transactions scored through the API;
       - a card-testing attack stopped by the velocity rule;
       - SHAP evidence;
       - suspicious merchant names flagged by DistilBERT;
       - Gemini narratives for three fraud patterns.
     - **Act 3 · Independent AI oversight and resilience.** Watch:
       - Groq's second opinion live;
       - XGBoost vs Groq on one transaction;
       - removing the LLM while decisions never pause;
       - zero-downtime failover;
       - self-healing;
       - the drift alarm.
     - **Act 4 · Humans in control.** Watch: a customer appeal, an analyst overturning a decision with a full audit trail, and verdicts becoming training data.
     - **Act 5 · Operate, govern, scale.** Watch: the operational-health view, champion vs challenger in MLflow, and live cloud load and cost.
   - Replace the yellow "Disclosed" box with a calm blue note: "Demo calibration: the replay stream uses REVIEW ≥ 0.10 and BLOCK ≥ 0.18 so all three outcomes appear live; production thresholds are 0.50 and 0.85."
9. **Slide 29 · Fallback.**
   - Delete the five empty screenshot placeholders.
   - Keep the Demo Console image and the rehearsal numbers.
   - Label the slide "Backup".
10. **Slide 30 · QA strategy.**
    - Replace the last line with: "Test-target audit: 8 of 9 targets met; model-accuracy target re-baselined on evidence."
11. **Slide 34 · Delivery journey.**
    - **Headline:** "Monday to Thursday, every real-world challenge was solved and the live demo rehearsed to 20 out of 20."
    - Rename the column to "Challenge → Solved".
    - Write each item as challenge → solution, for example: "Groq daily quota used up in 16 minutes → rate-limited to 12 calls a minute and budgeted".
12. **Slide 35 · Lessons.**
    - Lesson 4: "Measure, don't assume: independent measurement turned a hidden risk into a costed roadmap."
    - Lesson 7: "Be transparent early: calibrations disclosed up front build trust."

## Section G and the roadmap, rebuilt as clean vector visuals

**Do not use** audit_1, audit_2, audit_3, audit_4, audit_5 or audit_6.png. They carry Amber, Red and FAIL labels. Redraw their content in the deck's own style instead.

**Keep using:**
- the XGBoost and Random Forest charts;
- demo_console_step_preview.png.

**Slide 31 · G · Independent audit**
- **Headline:** "An independent 16-report audit confirms the model, the data and the pipeline, and maps the path to production-grade live scoring."
- **Three green "Validated" cards:**
  - **Model:** ROC-AUC 0.956; 0.889 out-of-time; clears all four quality gates.
  - **Data:** 590,540 transactions profiled; training features rebuilt independently and matched exactly; 59 of 59 data checks pass.
  - **Pipeline:** 0 duplicate events; p50 31 ms, p95 63 ms, p99 125 ms, on 4,692 events exported from an earlier pipeline run (Jul–Aug 2026).
- **One blue "Next phase" card:** live feature alignment, with a measured three-phase plan (slide 36).
- **Strip:** 16 Evidently reports · 118,108 held-out transactions · 0 changes to the project (the audit ran read-only on a copy).

**Slide 32 · G · Why live scores differ, and why it is fixable**
- **Headline:** "The model is proven; aligning the live event with training is the next measured step."
- **Left, in plain words:** "The model learned from 43 inputs built from each card's full history. The demo replay sends a lighter event, so 7 inputs match training exactly today. Phase 1 brings this to 14, phase 2 to 33, and phase 3 to all 43."
- **Right:** a rising staircase chart in navy and blue, with no red, drawn to scale from 0.5 to 1.0 with a dashed 0.90 gate line:
  - live replay baseline 0.574;
  - phase 1 code fixes 0.660;
  - phase 2 richer event 0.783;
  - out-of-time reference 0.889;
  - offline champion 0.956.
- **Caption:** "Measured on the same 118,108 transactions with the same model file."

**Slide 33 · G · Quality gates**
- **Headline:** "Four quality gates now guard every release, and the champion model clears all four."
- **Four gate tiles with green ticks:**
  - ROC-AUC ≥ 0.90 → 0.956;
  - Recall ≥ 0.80 → 83.9%;
  - FPR ≤ 0.08 → 6.6%;
  - Precision ≥ 0.30 → 31.7%.
- **Governance decisions, as six short positive cards:**
  1. XGBoost stays champion: the one model that clears all four gates.
  2. Safety first: live flags route to analyst REVIEW until each phase clears the gates.
  3. Out-of-time testing becomes the standard reference.
  4. Gates run automatically on every model or feature change.
  5. Thresholds are re-calibrated after each phase.
  6. Scheduled drift and segment monitoring.

**Slide 36 · I · Roadmap**
- **Headline:** "A measured roadmap lifts live scoring to 0.660 after phase 1 and 0.783 after phase 2, on the way to the 0.956 champion."
- **Four ascending cards in blue tones:**

| | Today: live replay baseline | Phase 1: nine code fixes | Phase 2: 17 optional event fields | Phase 3: feature store |
|---|---|---|---|---|
| ROC-AUC | 0.574 | 0.660 | 0.783 | target 0.889–0.956 |
| Inputs matching training | 7 of 43 | 14 of 43 | 33 of 43 | 43 of 43 |
| Fraud caught at equal alert budget | 16.8% | 23.4% | 41.5% | up to 83.9% |
| Note | | | BACKWARD-compatible Avro change | |

- **Exit rule for every phase:** all four gates pass and thresholds are re-calibrated.
- **Footer:** "Improvement split: about 23% code, 32% event fields, 45% history counters."

**Slide 37 · I · Summary and the ask**
- **Columns:** Promised → Delivered → Next.

| | Promised | Delivered | Next |
|---|---|---|---|
| Speed | Under 100 ms | 56.69 ms p95 at 10,000 a minute | Keep the CI latency gate |
| Accuracy | Model accuracy validated | ROC-AUC 0.956; 83.9% of fraud caught; 0.7% hard-blocked | Phase 1 alignment → 0.660 |
| Explanations | ≥3 scenarios | SHAP on every flag; 3 Gemini scenarios; DistilBERT | Extend the audit to the velocity rule, blocklist and DistilBERT |
| Resilience | — | 971 ms failover; fail-open rules; 20 of 20 rehearsal | Scheduled drift monitoring |
| Quality | ≥80% coverage | 80.05%, 122 tests, 16-report audit | Out-of-time testing as standard |
| Cost | Within ₹2,500 | ≈ USD 2 cloud this week; all AI and ML tools ₹0 | Budget every free tier as a hard limit |

- **The ask:** "Approve phase 1: nine live-feature fixes, each re-measured against the four quality gates."

## Appendix

- **A1.** Rename the live row "Live replay baseline (before phase 1)".
- **A4.** Replace the total row with "Cloud spend recorded: this week ≈ USD 2 (≈ ₹170) + week-15 load test USD 0.28 (≈ ₹24)".
- **A2 and A3:** keep as they are.

## Speaker notes

1. **Every slide:**
   - 80–150 words of natural spoken English;
   - start with the target time, for example "[4:30]";
   - the timings must add up to the plan above.
2. **On slides 9, 13, 22, 27, 28, 32, 33 and 36, add an "If asked:" line** with the matching prepared answer below.
3. **In the notes of slide 38, list all the prepared answers.**
4. **End with a checklist note** of every [confirm] item.

**Prepared answers. These go in the notes only, never on slides.**

1. **"The proposal promised F1 ≥ 0.92."**
   - That was a stretch target set before we had measured the data.
   - IEEE-CIS is 3.5% fraud. A 1,500-point threshold sweep shows the best F1 this dataset allows is about 0.67.
   - So we optimised for what the business needs, which is catching fraud: 83.9% recall, ROC-AUC 0.956.
   - Doubtful cases go to REVIEW, not decline.
2. **"FPR is 6.56%, not 2%."**
   - A 2% rate would miss 509 more frauds.
   - The 6.56% go to a person, not to a decline. Only 0.7% of good customers are hard-blocked.
3. **"Why does the live path score 0.574?"**
   - The model is proven: 0.956 offline and 0.889 out-of-time.
   - The replay event is lighter than the history-rich training features, so 7 of 43 inputs match exactly.
   - We measured the fix: 0.660 after phase 1 and 0.783 after phase 2, then the feature store.
   - Until the gates pass, live flags go to analysts. That is safety first.
4. **"Why isn't Groq the fast path?"**
   - XGBoost decides in milliseconds, with no external API dependency.
   - Groq's free tier (200,000 tokens a day) ran out in 16 minutes at stream rate.
   - So Groq runs live in parallel as an independent second opinion and drift check: 145 calls, 0 failures, 238 ms on average.
   - Act 3 proves payments never wait for it.
5. **"Why the demo thresholds?"** They are disclosed up front. The replay uses 0.10 / 0.18 so all three outcomes appear live; production is 0.50 / 0.85.
6. **"Is it exactly-once?"**
   - Idempotent producers plus an upsert on event_id give the same no-duplicate result: 0 duplicates in 4,692 exported events.
   - read_committed alone has no effect without transactions.
7. **"Why not Databricks for training?"**
   - Training runs locally in MLflow, so training and serving share one environment.
   - Databricks Free Edition runs the batch enrichment.
   - Both models are logged in MLflow.
8. **"Is the analyst review queue a Power BI view?"** [confirm] Suggested answer: "The Real-time Alert Feed lists flagged cases, and analyst decisions and appeals run in the review workflow you saw in Act 4."
9. **"What did it all cost?"**
   - About USD 2 (≈ ₹170) of cloud this week, plus ₹24 for the week-15 load test.
   - Every AI and ML tool is free tier or open source.
   - The proposal budget was ₹800, against a ₹2,500 ceiling.
   - Total: [confirm].

**Checklist note:**
- [confirm] the total project spend;
- [confirm] whether the analyst review queue is a Power BI page.

## Rules that still apply

1. Never call Groq the fast path or a fallback.
2. Say "merchant name" for DistilBERT, not "transaction text".
3. Label the 4,692-event export as an earlier pipeline run (Jul–Aug 2026).
4. Show no file paths, IPs, keys, passwords or commit hashes. Cite sources by report name.
5. Keep at most about 40 words of body text per slide. Detail goes in the notes.

## Deliverable

1. The revised deck: 38 main slides + 4 appendix slides, 16:9, with full speaker notes.
2. At the end, a short list of the slides you changed.

# Update prompt for Claude Design: 60-minute technical session (deck version 4)

Paste everything below the line into the **same Claude Design project** that holds the version-3 deck, with upload.zip still attached.

---

## Your task

Turn the version-3 VelocityFraud deck into **version 4**, for a **60-minute technical session** with technical trainers who already know the big picture.

The new flow is: **picture first, then reasons, then the live demo, then proof, then discussion.**

**Keep:**
- the visual system (navy #0B2552, accent #1B5FD0, IBM Plex);
- the tone rules (exact numbers; only green "Delivered", blue "Delivered · enhanced" and blue "Next phase" chips; no red or amber chips);
- every existing slide's content, unless a change is listed below.

**Do not delete any slide.** Slides that are not in the main flow move to a **Backup** section after the close.

## 1. New order of the main deck: 19 slides

Locate each version-3 slide by its title. The old numbers are for reference only.

| New # | Section marker | Slide (version-3 title, old #) |
|---|---|---|
| 1 | — | Title (old 1), edited, see §3 |
| 2 | AGENDA | **NEW**, see §2 |
| 3 | 1 · THE BIG PICTURE | What is VelocityFraud (old 8) |
| 4 | 1 · THE BIG PICTURE | Architecture as built (old 14) |
| 5 | 2 · WHY IT IS BUILT THIS WAY | Six realities (old 5) |
| 6 | 2 · WHY IT IS BUILT THIS WAY | Eight recorded design decisions (old 16) |
| 7 | 3 · HOW ONE TRANSACTION IS SCORED | 16 fields in, six steps, one decision out (old 12), fixed, see §3 |
| 8 | 3 · HOW ONE TRANSACTION IS SCORED | Score 0 to 1 → ALLOW / REVIEW / BLOCK (old 13) |
| 9 | 4 · LIVE DEMO | Now the live system (old 28), edited |
| 10 | 4 · LIVE DEMO | How the live load test works (old 29), edited |
| 11 | 5 · PROOF AND QUALITY | Results in six numbers (old 31), edited |
| 12 | 5 · PROOF AND QUALITY | Quality you saw live (old 33), edited |
| 13 | 5 · PROOF AND QUALITY | XGBoost beats Random Forest (old 22) |
| 14 | 5 · PROOF AND QUALITY | The model is proven; aligning the live event is the next step (old 35) |
| 15 | 5 · PROOF AND QUALITY | Four quality gates (old 36) |
| 16 | 6 · ROADMAP AND THE ASK | Each phase feeds the model more (old 39) |
| 17 | 6 · ROADMAP AND THE ASK | Summary and the ask (old 40), edited |
| 18 | 7 · DISCUSSION | **NEW**: Let's discuss, see §2 |
| 19 | — | Thank you (old 41) |

**Backup section, after "Thank you":**
- Label the section **"Backup"** and number its slides B1–B23, keeping their version-3 order:

  | B# | Version-3 title (old #) |
  |---|---|
  | B1 | Situation (old 3) |
  | B2 | Complication (old 4) |
  | B3 | The question (old 6) |
  | B4 | Proposed solution (old 7) |
  | B5 | Aim and objectives (old 9) |
  | B6 | Business analyst lens (old 10) |
  | B7 | Requirements traceability (old 11) |
  | B8 | Journey of one transaction (old 15) |
  | B9 | Design upgrades (old 17) |
  | B10 | Best practices (old 18) |
  | B11 | Security and cost (old 19) |
  | B12 | Layer map (old 20) |
  | B13 | Layer 1 (old 21) |
  | B14 | Layer 3 (old 23) |
  | B15 | Layers 4–5 (old 24) |
  | B16 | Layer 5B (old 25) |
  | B17 | Layers 6–9 (old 26) |
  | B18 | Proof of improvement (old 27) |
  | B19 | Rehearsal record (old 30) |
  | B20 | QA strategy (old 32) |
  | B21 | Independent audit (old 34) |
  | B22 | Delivery journey (old 37) |
  | B23 | Lessons (old 38) |

- The appendix A1–A5 follows, unchanged except for A4 (see §4).
- Change each backup slide's section marker to "BACKUP · Bn", and keep its original topic after it.

**Cross-references:** update every slide reference to the new numbers. Examples:
- "slide 39" on the independent-audit slide;
- "Slide 19, A4" and the section letters on the traceability slide;
- the layer-map arrows.

## 2. New slides

**Slide 2 · AGENDA**
- **Headline:** "Today's 60 minutes, drawn to scale."
- **Visual:** the same proportional bar as the old agenda, with these 7 blocks:

  | Block | Minutes | Slides |
  |---|---|---|
  | 1 The big picture | 7 | 3–4 |
  | 2 Why it is built this way | 6 | 5–6 |
  | 3 How one transaction is scored | 4 | 7–8 |
  | 4 Live demo, Acts 1–5 | 28 | 9–10 + Demo Console (highlighted, accent blue) |
  | 5 Proof and quality | 7 | 11–15 |
  | 6 Roadmap and the ask | 3 | 16–17 |
  | 7 Discussion | 5 | 18 |

- **Small note under the bar:** "The full test suite (122 tests) starts in minute one and reports in Act 5."

**Slide 18 · LET'S DISCUSS**
- **Headline:** "Three questions for you."
- **Three large numbered cards:**
  1. "Phase 1 next, or straight to the feature store?"
  2. "Which failure or attack should we test next?"
  3. "What would a Psiog client need before this goes to production?"
- **Footer:** "Backup slides B1–B23 and appendix A1–A5 cover every layer in detail."

## 3. Edits to main slides

1. **Slide 1 · Title**
   - Replace "Final review and live demo · Friday 6 November 2026 · 11:00–12:30 IST" with "Technical session and live demo · [session date] · 60 minutes".
   - Keep "[session date]" as visible placeholder text; the presenter will type the date.
2. **Slide 7 · 16 fields in, six steps, one decision out:** fix the layout. The footnote "Example values are illustrative. Tokens are 16-character SHA-256 hashes." currently overlaps the "schema_version" row. Move it below the table, with clear space.
3. **Slide 9 · Demo map**
   - In the **Act 1** line, add at the start: "Full test suite starts in the background (1.0)".
   - At the end of **Act 5**, add: "· full test suite result, 122 tests (5.8)".
4. **Slide 11 · Six numbers:** replace the tile "≈ USD 2 · cloud cost this week; every AI and ML tool is ₹0" with:
   - **Big number:** "₹0"
   - **Caption:** "for every AI and ML tool. The cloud server is the only bill: USD 11.25 (≈ ₹960) in November, within the ₹2,500 ceiling."
5. **Slide 12 · Quality you saw live**
   - Change the "Live:" strip to: "122 tests · k6 · Locust · 7 stream checks · failover · self-healing · drift alarm".
   - Change the "Recorded:" strip to: "80.05% coverage · 59 of 59 data checks · 16-report independent audit".
6. **Slide 17 · Summary**
   - Change the **Cost** row's "Delivered" cell to: "All AI and ML tools ₹0; cloud USD 11.25 (≈ ₹960) in November, within ₹2,500".
   - Change the **Quality** row's "Delivered" cell to: "80.05% coverage, 16-report audit; 122 tests, k6, Locust and 7 stream checks run live".

## 4. Edits to backup and appendix slides

1. **B21 · Independent audit**
   - The 3-line headline runs behind the cards. Shorten it to: "An independent 16-report audit confirms the model, the data and the pipeline."
   - Update its "(slide 39)" reference to "(slide 16)".
2. **B10 · Best practices:** change "80.05% unit coverage" to "80.05% code coverage (full suite)".
3. **B20 · QA strategy:** change the pyramid layer "Unit · 80.05% coverage" to "Code coverage · 80.05% (full suite)".
4. **B11 · Security and cost:** change the cost bar "Cloud this week · ≈ USD 2 (≈ ₹170)" to "Cloud, November · USD 11.25 (≈ ₹960)". Draw it to scale against ₹2,500 and ₹800, and remove the "≈ 2.5 h build + ≈ 27 h…" line.
5. **A4 · Tech stack and cost**
   - Change the "Hosting, this week" row to "Hosting, November: Hetzner CPX32 + CPX22 load server, plus snapshots · USD 11.25 (≈ ₹960)".
   - Change the "Cloud spend recorded" box to: "November USD 11.25 (≈ ₹960) + week-15 load test USD 0.28 (≈ ₹24)".

## 5. Speaker notes for the main slides

For each slide:
- start with the target time;
- keep the notes to 2–4 short lines;
- the presenter has a separate full script, so these notes are reminders only.

| Slide | Start time | Note |
|---|---|---|
| 1 | [00:00] | Welcome; invite interruptions. At [00:30], click 1.0 in the console to start the 122 tests. |
| 2 | [00:45] | The hour in one breath. |
| 3 | [01:30] | One sentence plus five verbs: Stream, Decide, Explain, Review, Learn. Define p95. |
| 4 | [03:30] | Follow one transaction left to right through the five stages. Dashed boxes are advisory and can never decide. Check-in: "Is the flow clear?" |
| 5 | [07:00] | Six facts, each linked to a design choice. Fraud is 3.5%, so we measure recall, not accuracy. |
| 6 | [10:00] | Ask first: "LLM inside the decision, or beside it?" Then row 1, then three-outcome, idempotent and least-exposure. |
| 7 | [13:00] | 16 fields → 43 inputs; missing ones = −999 (matters later). |
| 8 | [15:00] | Score = 1/(1+e^−z). Thresholds 0.50 / 0.85. Results: 83.9% caught, 6.6% reviewed, 0.7% hard-blocked. Disclose the demo thresholds 0.10 / 0.18. |
| 9 | [17:00] | Five acts; how you know it's live; switch to the console. |
| 10 | Before 5.4 | Why a separate load server; new card per request. |
| 11 | [45:00] | Six numbers. |
| 12 | [46:30] | Live vs week-15 certificate. p99 is higher because of two extra Redis checks and the full pipeline on the same server; still within 200 ms. |
| 13 | [48:00] | Recall over precision: a missed fraud costs more than a review. Out-of-time 0.889. |
| 14 | [49:30] | 0.956 offline vs 0.574 live. 7 of 43 inputs match. Measured fix: 0.660, 0.783, then the feature store. Safety first. |
| 15 | [51:30] | Four gates, all passed. |
| 16 | [52:00] | 7 → 14 → 33 → 43 inputs; exit rule. |
| 17 | [53:30] | Summary; the ask: approve phase 1. |
| 18 | [55:00] | Three questions; let the room talk. |
| 19 | [60:00] | Thank you. |

## Rules that still apply

1. No IP addresses, passwords, keys or file paths on any slide.
2. Never call Groq the fast path or a fallback.
3. Say "merchant name" for DistilBERT.
4. Label the 4,692-event export as an earlier run (Jul–Aug 2026).
5. Keep body text to about 40 words per slide or fewer.

## Deliverable

1. The version-4 deck:
   - 19 main slides;
   - Backup B1–B23;
   - Appendix A1–A5;
   - 16:9, with speaker notes.
2. At the end, a short list of every moved, new and edited slide.

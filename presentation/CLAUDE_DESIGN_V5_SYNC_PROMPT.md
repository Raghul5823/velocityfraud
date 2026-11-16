# Update prompt for Claude Design: sync the deck with the session script (deck version 5)

Paste everything below the line into the **same Claude Design project** that holds the version-4 deck. Nothing new needs uploading.

---

## Your task

Make **version 5** of the VelocityFraud deck. It is a small correction pass so that each slide matches what the presenter says from the spoken script. The script is fixed; only the slides change.

**Rules for this pass:**
1. **Change only what is listed below.** Keep every other slide, number, layout, colour and chip exactly as it is in version 4.
2. **Keep the slide count and the order:** 19 main slides, backup B1–B23, appendix A1–A5.
3. **Keep the visual system:** navy #0B2552, accent #1B5FD0, IBM Plex. Use only the green "Delivered", blue "Delivered · enhanced" and blue "Next phase" chips; no red or amber chips.
4. **Locate each slide by its number and title.** If a text box grows, rebalance its slide so nothing overlaps or runs off the edge.

## A. Changes so the slides match the script

### Slide 1 · Title
- Replace "[session date] · 60 minutes" with: **"Friday 13 November 2026 · 10:00 IST · 60 minutes"**

### Slide 4 · Architecture as built (stage 5, "Store, see, act")
- **MLflow 2.18 box:** the presenter says "MLflow tracks the models". Change its caption from "ops metrics every 30 s" to **"tracks the models"**.

### Slide 7 · 16 fields in, six steps, one stored decision out
The presenter describes steps 4 and 5 like this: "Each tree adds a small value; the total is called z. Then z becomes a score, and the score becomes a decision." Make the two step cards follow that wording:
- **Step 4 card:** "**Each tree adds a small value:** z = base + Σ leaf values."
- **Step 5 card:** "**z becomes a score, then a decision:** score = 1 / (1 + e^(−z)); below 0.50 ALLOW · 0.50 to 0.85 REVIEW · 0.85 and above BLOCK."
- Keep step 4's highlighted style.

### Slide 8 · Score to decision
The presenter ends this slide with "one honest note before the demo": the live stream uses the demo thresholds.
- **Add one line** between the three bands and the "Test set" strip, as a neutral blue note:

  **"Live demo calibration: on the replay stream REVIEW starts at 0.10 and BLOCK at 0.18, so all three outcomes appear (slide 9)."**

### Slide 9 · Now the live system (demo map)
The presenter clicks 3.1–3.6 and skips step 5.7.
1. **Act 3 line:** replace it with:

   "Groq live; XGBoost vs Groq; LLM removed, decisions never pause; failover and self-healing; drift alarm"
2. **Act 5 line:** replace it with:

   "Health, MLflow champion vs challenger, cloud cost (5.1–5.3) · **live load test**: 10,000 a minute, p95 vs 100 ms (5.4) · **live capacity**: 100 users, zero errors (5.5) · **seven live stream checks** (5.6) · **full test suite result, 122 tests** (5.8). Recorded evidence: slide 12."

### Slide 10 · How the live load test works
- **Step 5 in the step strip:** replace "5.7–5.8: recorded evidence, then the 122-test result" with:

  **"5.8: the result of the 122 tests started in 1.0"**

## B. Accuracy fixes (the script does not mention these; the slides are wrong as they stand)

### Slide 8 · Score to decision, ALLOW band
- Replace "e.g. 0.413, a live decision on the cloud server: the payment proceeds" with:

  **"e.g. 0.061, the USD 25 grocery purchase in step 2.1: the payment proceeds"**

- Reason: on the live stream the demo thresholds apply, so 0.413 would be a BLOCK there. 0.061 is ALLOW under both settings.

### Slide 12 · Quality you saw live
- The table's last column has no header. Give it the header **"Status"**.

### B20 · QA strategy
- Replace "122 automated tests in 18 files" with **"122 automated tests in 17 test files"**.

### Cloud cost: use the current November figure, USD 11.43 (≈ ₹975)
The billing page now shows USD 11.43 for November. Replace the old figure everywhere it appears:
- **Slide 11 · ₹0 tile caption:** "USD 11.25 (≈ ₹960) in November" becomes **"USD 11.43 (≈ ₹975) in November so far"**.
- **Slide 17 · Cost row, "Delivered" cell:** "All AI and ML tools ₹0; cloud USD 11.43 (≈ ₹975) in November so far, within ₹2,500".
- **B11 · Security and cost:**
  - Headline: "Least exposure kept the system safe, and free-tier discipline kept November's cloud bill to USD 11.43."
  - Cost bar label: "Cloud, November so far · USD 11.43 (≈ ₹975)", still drawn to scale against ₹2,500 and ₹800.
- **A4 · Tech stack and cost:**
  - Hosting row cost: "USD 11.43 (≈ ₹975)".
  - "Cloud spend recorded" box: "November so far USD 11.43 (≈ ₹975) + week-15 load test USD 0.28 (≈ ₹24)".

## Speaker notes

1. **Format:** each main slide's note starts with its script time **and** the clock time. The session starts at 10:00 IST, for example "[17:00 · 10:17]".
2. **Clock times by slide:**

   | Slide | Script time · clock time |
   |---|---|
   | 1 | [00:00 · 10:00] |
   | 2 | [00:45 · 10:01] |
   | 3 | [01:30 · 10:02] |
   | 4 | [03:30 · 10:04] |
   | 5 | [07:00 · 10:07] |
   | 6 | [10:00 · 10:10] |
   | 7 | [13:00 · 10:13] |
   | 8 | [15:00 · 10:15] |
   | 9 | [17:00 · 10:17] |
   | 10 | shown in Act 5, after step 5.3 |
   | 11 | [45:00 · 10:45] |
   | 12 | [46:30 · 10:47] |
   | 13 | [48:00 · 10:48] |
   | 14 | [49:30 · 10:50] |
   | 15 | [51:30 · 10:52] |
   | 16 | [52:00 · 10:52] |
   | 17 | [53:30 · 10:54] |
   | 18 | [55:00 · 10:55] |
   | 19 | [60:00 · 11:00] |

3. **Note changes:**
   - **Slide 7:** "16 fields → 43 inputs; missing ones = −999 (matters later). Each tree adds a value → z → score → decision."
   - **Slide 9:** "Five acts; how you know it's live; switch to the console. Step 5.7 is skipped; slide 12 covers the recorded evidence."
   - **All other slides:** keep the version-4 notes unchanged.

## Rules that still apply

1. No IP addresses, passwords, keys or file paths on any slide.
2. Never call Groq the fast path or a fallback.
3. Say "merchant name" for DistilBERT.
4. Label the 4,692-event export as an earlier run (Jul–Aug 2026).
5. Keep body text to about 40 words per slide or fewer.

## Deliverable

1. The version-5 deck: 19 main slides, backup B1–B23 and appendix A1–A5, 16:9, with speaker notes.
2. At the end, a list of the slides you changed. It should be exactly these 12, plus the speaker-note updates:
   - main slides 1, 4, 7, 8, 9, 10, 11, 12 and 17;
   - backup slides B11 and B20;
   - appendix slide A4.

# What to give Claude Design

1. Open Claude Design and start a new presentation.
2. Attach the files listed below.
3. Paste everything below the line in `CLAUDE_DESIGN_PROMPT.md`.
4. When the deck is ready, check every **[confirm]** item and compare the numbers with the prompt's fact sheet before presenting.

All files are copies in `upload/`. The project itself was not changed, and the one password found in the documents is redacted in its copy.

## 1. Essential documents: attach all 11 (`upload/1_essential`)

| File | What it gives the deck |
|---|---|
| 01_RFP_S2-D-06_customer_brief.pdf | The customer's problem, requirements, minimum coverage and evaluation weights (slides 3–8) |
| 02_PROPOSAL_VelocityFraud.md | The original aim, problem framing, architecture and budget (slides 5, 6, 13) |
| 03_proposal_gap_remediation.md | 13 gaps found and closed, including the score-cache defect story (slides 13, 23) |
| 04_section_10_2_target_audit.md | Test targets vs measured results: 5 met, 3 met with a deviation, 1 missed (slides 23, 26) |
| 05_model_evaluation.md | Random Forest vs XGBoost, the confusion matrix and the champion decision (slides 9, 18) |
| 06_LAYER_3_FAST_PATH_SCORING.md | The decision path: thresholds, velocity rule, failover (slide 19) |
| 07_resilience.md | The failure-mode matrix: what happens when each part fails (slide 19) |
| 08_ai_assisted_qa.md | AI checks AI narratives, AI-generated load patterns, drift detection, CI latency gate (slide 26) |
| 09_EVIDENTLY_FINDINGS.md | Independent audit: offline vs live, what-if fixes, extended checks (slides 27–29, 32) |
| 10_EVIDENTLY_EXTENDED_SUMMARY.md | Champion vs challenger, out-of-time test, segments, gates (slides 28, 29) |
| 11_DEMO_CONSOLE_README.md | How the live demo is run and kept safe (slide 24) |

## 2. Images: attach all 13 (`upload/3_images`)

| File | Use on |
|---|---|
| xgboost_roc_curve.png, xgboost_confusion_matrix.png, xgboost_feature_importance.png | Slide 18 (models) |
| random_forest_roc_curve.png, random_forest_confusion_matrix.png, random_forest_feature_importance.png | Slide 18 or appendix (challenger) |
| audit_1_verdict.png | Slide 27 (audit verdict) |
| audit_2_roc_ladder.png | Slide 28 (the measured gap) |
| audit_3_scorecard.png | Slide 27 (13-component scorecard) |
| audit_4_roadmap.png | Slide 32 (roadmap) |
| audit_5_quality_gates.png | Slide 29 (pass/fail gates) |
| audit_6_decisions.png | Slide 29 (architecture decisions) |
| demo_console_step_preview.png | Slide 24 (demo map). The server IP is hidden. |

## 3. Optional deep-dive documents: attach if there is room (`upload/2_optional`)

These are the per-layer documents (Layers 1, 2, 4, 5, 5B, 6, 8, 9), plus:
- the data-quality report;
- the fraud-pattern demos;
- the cloud deployment runbook;
- the first Evidently summary and the what-if summary.

They help slides 16–22 (layer by layer).

## 4. Do not attach

- **`.env` or any key file** (Groq and Gemini API keys, SSH keys).
- **`vf-demo-notes.txt` on the Desktop.** It contains the server IP, the SSH key fingerprint and commands. The prompt already contains the safe timeline from it.
- **The project README.** It is out of date: it still says Groq is the fast path and training runs in Databricks. The prompt has the correct architecture.
- **The final-term PDF.** It has unfilled placeholders and two different Hetzner cost figures ($1.28 and $0.28). Attach it only if you want, and tell Claude Design to prefer the prompt's fact sheet.
- **The original `LAYER_6_STORAGE.md`.** It contains the database password; use the redacted copy in `upload/2_optional`.

## 5. Optional screenshots worth capturing tonight

The server is running and the tunnel works from anywhere, so 10 minutes tonight adds real "live" visuals. Save them into `upload/3_images` and attach them too.

1. **Power BI:** the four pages (Real-time Alert Feed, Fraud Trend Analysis, Model Performance, Operational Health), after Optimize → Refresh visuals.
2. **Kafka UI:** Topics → transactions.raw → Messages.
3. **MLflow:** the fraud-detection experiment, with the runs compared.
4. **API docs (Swagger):** POST /score with a response.
5. **Hetzner console:** the server's Graphs tab. Crop out the IP.
6. **Demo Console mid-run:** for example step 3.4 showing "Leadership moved to standby in … ms".

Skip any of these if time is short. The live demo shows all of them anyway.

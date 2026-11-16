# VelocityFraud — verified findings from the Evidently evaluation

Run on 2026-11-05 · full held-out test split (118,108 transactions, 4,133 fraud) plus 4,692 real live-server events.
Numbers come from `reports/n118108/00_SUMMARY.md`. Nothing in `velocityfraud/` was changed, and the cloud server was not touched.

## 1. The test is trustworthy

| Check | Result |
|---|---|
| Laptop replica vs. scores recorded by the live server (4,692 events) | Largest difference **0.000000005**. 100% identical |
| Offline numbers vs. `docs/model_evaluation.md` | ROC-AUC **0.9562**, recall **0.8393**, FPR **0.0656**. Exact match |
| Training test split reproduced | Exact (same amounts and labels, row for row) |

## 2. Headline result

| | ROC-AUC | Frauds caught @0.50 | Fraud $ caught @0.50 |
|---|---|---|---|
| **Offline model** (43 features) | **0.956** | **83.9%** (3,469 / 4,133) | $521,608 of $639,135 |
| **Live pipeline**, same transactions | **0.574** | **3.1%** (127 / 4,133) | $27,025 of $639,135 |
| **Real live-server events** | **0.597** | **0%** (0 / 95) | $0 of $18,148 |

The model is good. The live pipeline doesn't give it the inputs it was trained on: only **7 of 43** features match training on ≥99% of transactions, and **23 of 43** never match.

**Lowering the thresholds is not a fix.** At the demo thresholds (0.10 / 0.18), live catches 62% of fraud, but it does so by:
- flagging **55%** of good customers;
- **blocking 29%** of good customers;
- raising **556 alerts per 1,000** transactions.

Precision is **3.9%**, against a 3.5% fraud rate. That is barely better than flagging transactions at random.

## 3. Root causes (each verified against the data)

### A. Data the event already carries, but live features ignore (quick wins)
1. **card1.** The replayer sends it as `customer_id` (`replayer.py:87`), but live features set card1 to -999.
2. **dist1.** The replayer sends it as `geo_distance_km` (`replayer.py:104`), but live features set dist1 to -999.

### B. Live computes a value, but differently from training
3. **`email_mismatch` is hard-coded to 0** (`live_features.py:180`). In training it is 1 for about 69% of transactions. This is the single largest mismatch among features that have a value.
4. **`r_email_missing` is hard-coded to 1** (`live_features.py:179`). This is wrong for 23% of transactions.
5. **`addr2` missing becomes 0 instead of -999.** The replayer sends "00" (`replayer.py:122`) and `live_features.py:166` parses it as 0. This affects 11% of transactions.
6. **`is_high_amount` uses a different cut-off:** $200 live (`live_features.py:85`) vs. $445 in training (the 95th percentile). This is wrong for 11.4% of transactions.
7. **`ProductCD_freq` and `P_emaildomain_freq` use hard-coded frequencies that don't match training** (`live_features.py:39`, `:58`). For example, gmail.com is 0.4373 live vs. 0.3867 in training, and a missing email is 0.0010 live vs. 0.1599 in training.
8. **`amount_cents`.** Training truncates through float arithmetic, while live rounds (`live_features.py:156`). This puts live off by one cent on 7.3% of transactions. Here training is the odd one out, but live has to copy training to match the model.

### C. Values the model never saw in training
9. **`card4_freq`, `card6_freq`, `R_emaildomain_freq` and `M1`–`M9_freq` are sent as -999 live.** In training, a missing value got its own frequency, so these 12 features were never -999. The model receives inputs outside anything it learned from.

### D. Not available from a single event (needs a feature store or a richer event)
10. **C1–C14, D1–D15, card2/3/5 and addr1** are Vesta's history counters and identity fields. In production they come from a streaming feature store, which the code itself notes (`live_features.py:16-18`).

## 4. Other caveat worth stating

The training split is a **stratified random** 80/20 split, not split by time. On IEEE-CIS, the same cards appear in both train and test, so 0.956 may be optimistic. An out-of-time test is the next step: train on earlier days, test on later days.

## 5. Suggested slide: "Offline vs. Live, verified against ground truth"

- We built an independent check that compares the live pipeline with the real fraud labels, and proved it reproduces the server exactly.
- Offline the model scores 0.956 ROC-AUC. Live it scores 0.57–0.60, because only 7 of 43 features reach the model the way training saw them.
- Latency and the pipeline itself meet target. The gap is feature parity.
- Root causes are identified and ranked: 2 unused fields, 6 encoding mismatches, 12 never-seen values, and history features that need a feature store.
- Next: fix A–C, re-run this same check, and show the before/after.

## 6. What-if result: fixes A–C applied (run 2026-11-05, evening)

The fixes were applied to a **copy** of the live-feature logic in this folder (`live_features_fixed.py`). The project was not changed: git is still `a79c7f8` with no changes, and no files under `src`, `data/processed` or `models` were written. The run used no Groq, Gemini or server.

Before any number was trusted, three self-checks passed on all 118,108 transactions:
1. The copy with no fixes reproduces the project's live features exactly (5,078,644 values).
2. Today's live scores and the offline scores reproduce step 1.
3. With the richer event, all 33 non-history features equal training.

Full tables: `reports/n118108/04_WHATIF_SUMMARY.md`.

| Same 118,108 transactions, same model file | ROC-AUC | Features matching training | Frauds caught at the offline alert budget (6.6% of good customers) |
|---|---|---|---|
| Live pipeline today | **0.574** | 7 / 43 | **16.8%** |
| + all code fixes (9 fixes, code only) | **0.660** | 14 / 43 | **23.4%** |
| + richer event (17 raw per-transaction fields added to the Avro event) | **0.783** | 33 / 43 | **41.5%** |
| Offline model, all 43 features (ceiling, needs a feature store) | **0.956** | 43 / 43 | **83.9%** |

**Where the gap is.** The gap is 0.382 ROC-AUC in total:

| Part of the gap | Share |
|---|---|
| Code fixes | **~23%** (+0.086) |
| Richer event | **~32%** (+0.123) |
| Vesta history counters (C\*, D\*), which need a streaming feature store | **~45%** (+0.173) |

**What to say carefully:**
1. **Code fixes help, but they are not enough on their own.** At the same alert budget, frauds caught rise from 16.8% to 23.4%.
2. **Scores shift after the fixes, so thresholds must be re-calibrated.**
   - At 0.50, the fixed pipeline catches 38.4% of fraud ($261,595), but it also flags 16.2% of good customers.
   - At the demo thresholds it catches 77.1% of fraud, but it blocks 44.4% of good customers (29.3% today).
3. **Single fixes can lower ROC-AUC on their own,** for example the anonymous.com fix (−0.011) and the frequency tables (−0.004). The remaining out-of-range inputs interact with them. Judge the combined result.
4. **The richer event ranks better but is badly calibrated:** 49.4% of good customers are flagged at 0.50. That's because the history counters are still −999, a value the model never saw in training. This is the strongest argument for the feature store.

## 7. Suggested slide: "Closing the offline–live gap, measured"

- Same 118,108 held-out transactions, same production model file, one variable changed at a time.
- **Live today 0.574 → code fixes 0.660 → richer event 0.783 → feature store 0.956 (ceiling).**
- Roadmap, in order:
  1. apply the 9 code fixes;
  2. add 17 optional fields to the Avro event (a BACKWARD-compatible schema change);
  3. build a streaming feature store for the card-history counters;
  4. re-calibrate the thresholds after each step.
- Every step is re-measured with this same Evidently harness before it ships.

## 8. Extended checks (run 2026-11-05, evening)

These ran on the laptop only. The project is unchanged (`a79c7f8`) and no Groq, Gemini or server was used. A self-check confirmed that the feature rebuild reproduces the project's `X_test.parquet` exactly. Full tables are in `reports/extended/08_EXTENDED_SUMMARY.md`, and the Evidently reports are numbered 09–15.

1. **Champion vs challenger is confirmed.** On the same 118,108 transactions, XGBoost has a ROC-AUC of 0.9562 and Random Forest 0.9498, matching `model_evaluation.md`. At 0.50 the two models trade off differently:

   | | Frauds caught | Good customers flagged | Precision |
   |---|---|---|---|
   | XGBoost | 83.9% | 6.6% | 31.7% |
   | Random Forest | 77.8% | 4.4% | 39.2% |

   XGBoost was chosen for recall.
2. **Out-of-time test: 0.889, not 0.956.** The model was trained on the first 80% of the timeline and tested on the last 20% (days 141–182).
   - It catches **63.1%** of fraud at 0.50 (83.9% on the random split).
   - The random split, with the same clean recipe, scores 0.9548.
   - So **about 0.066 of the headline comes from the random split**. Early stopping on the test set adds only 0.0014.
3. **Thresholds.** At the demo thresholds (0.10 / 0.18), the offline model catches 97.6% of fraud, but it blocks 25.8% of good customers. The production thresholds are the right ones for real customers.
4. **Segments:**
   - Product **W** (75% of traffic) is the weakest offline: ROC-AUC 0.940, 72.9% caught.
   - Product **C** flags the most good customers: 20.6%.
   - Live, **anonymous.com** ranks worse than random (0.421). This matches the anonymous.com bug found in the what-if.
5. **Data quality:**
   - **Raw data:** 0 duplicate TransactionIDs, and 15 of 55 columns are more than 50% missing.
   - **Live pipeline export** (4,692 events, 2 Jul–12 Aug 2026, an earlier run, not the Hetzner server):
     - **0 duplicate event_ids**, which supports the exactly-once claim;
     - 0 missing values;
     - latency p50 31 ms, p95 63 ms, p99 125 ms;
     - feature completeness always 34.9%.
6. **Drift over time:** comparing the first and last 30 days of the dataset, Evidently flags **20 of 44** features as drifted, including the model score. That argues for scheduled drift monitoring and retraining.
7. **Quality gates** (Evidently pass/fail tests: ROC-AUC ≥ 0.90, recall ≥ 0.80, FPR ≤ 0.08 and precision ≥ 0.30, all at 0.50):

   | Candidate | Result |
   |---|---|
   | XGBoost champion, offline | **PASS** |
   | Random Forest | **FAIL** (recall 77.8% < 80%) |
   | XGBoost, out-of-time | **FAIL** |
   | Live pipeline today | **FAIL** |

   These gates are the bar any fix must clear before it ships.

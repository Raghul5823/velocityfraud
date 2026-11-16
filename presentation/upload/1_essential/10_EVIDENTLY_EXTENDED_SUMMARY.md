# Extended Evidently checks

Laptop only: no server, Kafka, Redis, Postgres, Groq or Gemini. The project was not changed (git before and after: `HEAD a79c7f8 | changes: none`). Self-check passed: the feature rebuild reproduces the project's X_test.parquet exactly.

## 1. Champion vs challenger, and threshold policies (118,108 held-out transactions)

| Model | ROC-AUC | PR-AUC | Thresholds | Frauds caught | Fraud $ caught | Good customers flagged | Good customers blocked | Precision |
|---|---|---|---|---|---|---|---|---|
| XGBoost (champion) | 0.9562 | 0.709 | production 0.50 / 0.85 | 83.9% | $521,608 | 6.6% | 0.7% | 31.7% |
| XGBoost (champion) | 0.9562 | 0.709 | demo 0.10 / 0.18 | 97.6% | $612,817 | 40.9% | 25.8% | 8.0% |
| Random Forest (challenger) | 0.9498 | 0.695 | production 0.50 / 0.85 | 77.8% | $472,555 | 4.4% | 0.3% | 39.2% |
| Random Forest (challenger) | 0.9498 | 0.695 | demo 0.10 / 0.18 | 98.7% | $628,508 | 53.5% | 30.7% | 6.3% |
| Live pipeline today (XGBoost) | 0.5741 | 0.056 | production 0.50 / 0.85 | 3.1% | $27,025 | 0.8% | 0.0% | 11.7% |
| Live pipeline today (XGBoost) | 0.5741 | 0.056 | demo 0.10 / 0.18 | 62.2% | $445,506 | 55.3% | 29.3% | 3.9% |

## 2. Out-of-time test

Same training recipe as `train_xgb.py`, early stopping on a validation slice (not the test set), frequency tables and the high-amount cut-off fitted on the training period only. Out-of-time: trained on the first 472,432 transactions in time order, tested on the last 118,108 (4,064 fraud, day 141 to 182).

| Evaluation | ROC-AUC | Frauds caught @0.50 | Good customers flagged @0.50 |
|---|---|---|---|
| Project as documented (random split, early stopping on the test set) | 0.9562 | 83.9% | 6.6% |
| Random split, clean recipe | 0.9548 | 83.0% | 6.4% |
| Out-of-time (train on the past, test on the future) | 0.8888 | 63.1% | 7.4% |

The random split lets the same cards appear in training and test; testing on later days is the honest estimate of how the model performs on future transactions.

## 3. Where the model is strong and weak (segments, test split)

| Segment | Value | Transactions | Fraud rate | XGBoost ROC-AUC | XGBoost caught @0.50 | Live ROC-AUC | Live caught @0.50 | XGBoost good customers flagged |
|---|---|---|---|---|---|---|---|---|
| Product | C | 13,532 | 11.8% | 0.956 | 93.8% | 0.590 | 4.0% | 20.6% |
| Product | H | 6,599 | 5.2% | 0.965 | 90.6% | 0.686 | 7.9% | 9.7% |
| Product | R | 7,448 | 3.7% | 0.957 | 85.7% | 0.626 | 8.1% | 6.2% |
| Product | S | 2,309 | 6.5% | 0.972 | 91.3% | 0.503 | 0.0% | 6.3% |
| Product | W | 88,220 | 2.0% | 0.940 | 72.9% | 0.522 | 0.8% | 4.4% |
| Amount | $200-445 | 14,142 | 4.1% | 0.942 | 82.1% | 0.603 | 13.4% | 9.9% |
| Amount | $445 and over | 5,966 | 5.5% | 0.932 | 87.2% | 0.571 | 0.0% | 13.4% |
| Amount | $50-200 | 60,507 | 2.9% | 0.955 | 81.4% | 0.605 | 2.4% | 5.5% |
| Amount | under $50 | 37,493 | 3.9% | 0.965 | 86.9% | 0.565 | 0.5% | 6.0% |
| Time of day | day (06-22) | 73,413 | 3.4% | 0.954 | 83.2% | 0.567 | 3.2% | 6.6% |
| Time of day | night (22-06) | 44,695 | 3.7% | 0.960 | 85.0% | 0.585 | 2.9% | 6.5% |
| Card type | credit | 29,703 | 6.6% | 0.956 | 89.8% | 0.572 | 4.0% | 13.0% |
| Card type | debit | 88,067 | 2.5% | 0.952 | 78.7% | 0.552 | 2.2% | 4.5% |
| Card type | other/missing | 338 | 2.4% | 0.892 | 50.0% | 0.567 | 0.0% | 1.8% |
| Email domain | anonymous.com | 7,224 | 2.1% | 0.947 | 78.7% | 0.421 | 0.0% | 4.5% |
| Email domain | gmail.com | 45,743 | 4.3% | 0.958 | 86.7% | 0.611 | 5.8% | 8.7% |
| Email domain | hotmail.com | 8,967 | 5.3% | 0.951 | 86.2% | 0.541 | 1.5% | 10.2% |
| Email domain | missing | 18,865 | 3.0% | 0.955 | 80.7% | 0.566 | 0.0% | 4.8% |
| Email domain | other | 17,004 | 2.9% | 0.959 | 80.5% | 0.493 | 0.4% | 3.5% |
| Email domain | yahoo.com | 20,305 | 2.3% | 0.948 | 79.1% | 0.541 | 0.4% | 5.2% |

## 4. Data quality

**Raw IEEE-CIS transactions** (590,540 rows, 55 columns used by the project or available to it): duplicate TransactionIDs **0**; columns more than 50% missing: **15** (worst: dist2 94%, D7 93%, D13 90%, D14 89%).

**Live pipeline export** (`scored_events_bronze.csv`, 4,692 events scored 02 Jul 2026 - 12 Aug 2026 UTC; an earlier pipeline run, not the Hetzner server): duplicate event_ids **0** (exactly-once check); missing values **0**; scoring latency p50 **31 ms**, p95 **63 ms**, p99 **125 ms**, max 391 ms; feature completeness always **34.9%-34.9%**.

## 5. Drift over time (first 30 days vs last 30 days of the dataset)

Drifted features (Evidently default tests): **20 of 44** (45.5%), including the champion's score. Full detail in report 14.

**Score over time** (test split in six time windows; the replayer walks through time in this order):

| Test-split window (time order) | Transactions | Fraud rate | XGBoost ROC-AUC | XGBoost mean score | XGBoost flagged @0.50 | Live mean score | Live flagged @0.10 |
|---|---|---|---|---|---|---|---|
| window 1 (days 1-31) | 27,596 | 2.6% | 0.946 | 0.168 | 9.0% | 0.146 | 58.0% |
| window 2 (days 32-61) | 17,841 | 3.9% | 0.958 | 0.172 | 9.5% | 0.128 | 52.7% |
| window 3 (days 62-91) | 18,643 | 4.1% | 0.965 | 0.169 | 9.6% | 0.134 | 55.9% |
| window 4 (days 92-121) | 19,472 | 4.1% | 0.953 | 0.173 | 9.9% | 0.133 | 55.1% |
| window 5 (days 122-151) | 16,568 | 3.1% | 0.958 | 0.152 | 8.2% | 0.137 | 56.2% |
| window 6 (days 152-182) | 17,988 | 3.6% | 0.958 | 0.158 | 9.3% | 0.131 | 54.3% |

## 6. Quality gates (Evidently pass/fail tests)

The same four tests run on each candidate. A model or code change should ship only when all four pass.

| Candidate | ROC-AUC >= 0.90 | Recall >= 0.80 (frauds caught @0.50) | False-positive rate <= 0.08 (@0.50) | Precision >= 0.30 (@0.50) | Result |
|---|---|---|---|---|---|
| XGBoost champion, offline | SUCCESS | SUCCESS | SUCCESS | SUCCESS | PASS |
| Random Forest challenger, offline | SUCCESS | FAIL | SUCCESS | SUCCESS | FAIL |
| XGBoost, out-of-time | FAIL | FAIL | SUCCESS | FAIL | FAIL |
| Live pipeline today | FAIL | FAIL | SUCCESS | FAIL | FAIL |

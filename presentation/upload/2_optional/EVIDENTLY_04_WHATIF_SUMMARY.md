# What-if: live-feature fixes (118,108 held-out transactions, 4,133 fraud)

Same transactions, same model file (`xgboost_v1.pkl`). Only the live feature logic changes.
The project was not changed (git before and after: `HEAD a79c7f8 | changes: none`).

Self-checks passed: the fixed copy with no fixes reproduces the project's live features exactly, and the scores reproduce step 1.

## 1. Before vs after

|  | ROC-AUC | Features matching training | Frauds caught @0.50 | Fraud $ caught @0.50 | Good customers flagged @0.50 | Frauds caught at the offline alert budget (6.6% of good customers) |
|---|---|---|---|---|---|---|
| Live pipeline today | 0.574 | 7 / 43 | 3.1% (127) | $27,025 | 0.8% | 16.8% |
| Live + all code fixes | 0.660 | 14 / 43 | 38.4% (1,588) | $261,595 | 16.2% | 23.4% |
| Live + code fixes + richer event | 0.783 | 33 / 43 | 83.5% (3,450) | $530,365 | 49.4% | 41.5% |
| Offline model, all 43 features (ceiling) | 0.956 | 43 / 43 | 83.9% (3,469) | $521,608 | 6.6% | 83.9% |

*Alert budget:* every row may flag the same share of good customers as the offline model does at 0.50, so the rows are compared fairly even though their scores are calibrated differently.

## 2. Each fix on its own (added to today's live features)

| Fix | ROC-AUC | Change | Frauds caught at alert budget | Change  |
|---|---|---|---|---|
| 3-4. email_mismatch / r_email_missing / R_emaildomain_freq | 0.605 | +0.031 | 23.2% | +6.3 pts |
| 9. card4/card6/M1-M9 product-typical values | 0.602 | +0.028 | 18.1% | +1.3 pts |
| 2. dist1 from geo_distance_km | 0.582 | +0.008 | 16.3% | -0.5 pts |
| 1. card1 from customer_id | 0.579 | +0.005 | 14.4% | -2.5 pts |
| 8. amount_cents as in training | 0.575 | +0.001 | 16.9% | +0.1 pts |
| 5. addr2 '00' = missing | 0.574 | +0.000 | 16.8% | +0.0 pts |
| 6. high-amount cut-off $445 | 0.574 | -0.000 | 16.8% | +0.0 pts |
| 7. training frequency tables | 0.570 | -0.004 | 15.6% | -1.2 pts |
| new. anonymous.com is not a missing email | 0.563 | -0.011 | 15.8% | -1.1 pts |

Fixes interact: the combined result (section 1) is not the sum of the single-fix changes.

## 3. At the demo thresholds (REVIEW >= 0.10, BLOCK >= 0.18)

|  | Frauds caught | Fraud $ caught | Good customers flagged | Good customers blocked | Precision | Alerts per 1,000 |
|---|---|---|---|---|---|---|
| Live pipeline today | 62.2% | $445,506 | 55.3% | 29.3% | 3.9% | 556 |
| Live + all code fixes | 77.1% | $533,607 | 61.1% | 44.4% | 4.4% | 617 |
| Live + code fixes + richer event | 98.5% | $631,332 | 92.1% | 84.6% | 3.7% | 923 |
| Offline model, all 43 features (ceiling) | 97.6% | $612,817 | 40.9% | 25.8% | 8.0% | 429 |

## 4. Features that still differ from training after the code fixes

| feature | same as training |
|---|---|
| r_email_missing | 97.6% |
| dist1 | 90.9% |
| email_mismatch | 87.8% |
| R_emaildomain_freq | 84.3% |
| M1_freq | 79.6% |
| card6_freq | 77.9% |
| M2_freq | 73.8% |
| M3_freq | 68.0% |
| card4_freq | 65.2% |
| M6_freq | 63.9% |
| M7_freq | 61.4% |
| M9_freq | 60.4% |
| M5_freq | 59.4% |
| M8_freq | 58.4% |
| M4_freq | 56.9% |
| D2 | 47.4% |
| D4 | 28.5% |
| D15 | 15.0% |
| D10 | 12.9% |
| addr1 | 11.0% |
| card2 | 1.5% |
| card5 | 0.7% |
| card3 | 0.3% |
| D1 | 0.2% |
| C1 | 0.0% |
| C5 | 0.0% |
| C2 | 0.0% |
| C13 | 0.0% |
| C14 | 0.0% |

The Vesta history counters (C*, D*) need a feature store. card2/card3/card5/addr1 and the recipient email, card brand/type and M1-M9 flags need extra fields in the Avro event (the 'richer event' row).

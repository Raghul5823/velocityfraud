# VelocityFraud — Evidently evaluation (n118108)

Champion model: `xgboost_v1.pkl` · Test-split rows used: **118,108** (frauds: **4133**) ·
Real live-server events: **4,692** (frauds: **95**)

## 1. Is this laptop test the same as the live server? (replica check)
- Re-scored the 4,692 events the live pipeline already scored on the server.
- Largest score difference: **5.0e-09** · scores within 0.000001: **100.0%** ·
  identical feature completeness: **100.0%**.
- So every live number below is what the server would produce — without touching the server.

## 2. Ranking quality (threshold-free; 1.0 = perfect, 0.5 = coin flip)
| scored by | ROC-AUC | PR-AUC |
|---|---|---|
| Offline (full 43 features) | 0.9562 | 0.7095 |
| Live pipeline (same transactions) | 0.5741 | 0.0557 |
| Real live server events | 0.5970 | 0.0695 |

## 3. Business view — what a fraud team reads
| policy | scored by | frauds caught | fraud $ caught | fraud $ missed | good customers flagged (FPR) | good customers BLOCKED | precision | alerts / 1,000 txns |
|---|---|---|---|---|---|---|---|---|
| production (REVIEW>=0.50, BLOCK>=0.85) | Offline | 3469 / 4133 (83.9%) | $521,608 of $639,135 | $117,526 | 6.6% | 0.7% | 31.7% | 92.7 |
| production (REVIEW>=0.50, BLOCK>=0.85) | Live (same txns) | 127 / 4133 (3.1%) | $27,025 of $639,135 | $612,109 | 0.8% | 0.0% | 11.7% | 9.2 |
| production (REVIEW>=0.50, BLOCK>=0.85) | Real live server | 0 / 95 (0.0%) | $0 of $18,148 | $18,148 | 0.0% | 0.0% | 0.0% | 0.0 |
| demo (REVIEW>=0.10, BLOCK>=0.18) | Offline | 4035 / 4133 (97.6%) | $612,817 of $639,135 | $26,318 | 40.9% | 25.8% | 8.0% | 429.1 |
| demo (REVIEW>=0.10, BLOCK>=0.18) | Live (same txns) | 2569 / 4133 (62.2%) | $445,506 of $639,135 | $193,629 | 55.3% | 29.3% | 3.9% | 555.8 |
| demo (REVIEW>=0.10, BLOCK>=0.18) | Real live server | 46 / 95 (48.4%) | $9,138 of $18,148 | $9,010 | 35.2% | 11.2% | 2.8% | 354.9 |

## 4. Feature parity — same transaction, training features vs live features
- Features identical on ≥99% of transactions: **7 of 43**
- Features that never match (live sends the -999 "missing" value or a different encoding): **23 of 43**

| feature | same_value_% | live_missing(-999)_% | training_missing(-999)_% |
|---|---|---|---|
| TransactionAmt | 100.0 | 0.0 | 0.0 |
| is_weekend | 100.0 | 0.0 | 0.0 |
| hour_of_day | 100.0 | 0.0 | 0.0 |
| day_of_week | 100.0 | 0.0 | 0.0 |
| is_night | 100.0 | 0.0 | 0.0 |
| log_amount | 100.0 | 0.0 | 0.0 |
| is_round_dollar | 99.9 | 0.0 | 0.0 |
| p_email_missing | 93.9 | 0.0 | 0.0 |
| amount_cents | 92.7 | 0.0 | 0.0 |
| addr2 | 89.0 | 0.0 | 11.0 |
| is_high_amount | 88.6 | 0.0 | 0.0 |
| r_email_missing | 77.1 | 0.0 | 0.0 |
| dist1 | 59.5 | 100.0 | 59.5 |
| D2 | 47.4 | 100.0 | 47.4 |
| email_mismatch | 31.2 | 0.0 | 0.0 |
| D4 | 28.5 | 100.0 | 28.5 |
| D15 | 15.0 | 100.0 | 15.0 |
| D10 | 12.9 | 100.0 | 12.9 |
| addr1 | 11.0 | 100.0 | 11.0 |
| card2 | 1.5 | 100.0 | 1.5 |
| card5 | 0.7 | 100.0 | 0.7 |
| card3 | 0.3 | 100.0 | 0.3 |
| D1 | 0.2 | 100.0 | 0.2 |
| P_emaildomain_freq | 0.1 | 0.0 | 0.0 |
| C2 | 0.0 | 100.0 | 0.0 |
| C1 | 0.0 | 100.0 | 0.0 |
| card1 | 0.0 | 100.0 | 0.0 |
| C5 | 0.0 | 100.0 | 0.0 |
| C14 | 0.0 | 100.0 | 0.0 |
| C13 | 0.0 | 100.0 | 0.0 |
| ProductCD_freq | 0.0 | 0.0 | 0.0 |
| card4_freq | 0.0 | 100.0 | 0.0 |
| card6_freq | 0.0 | 100.0 | 0.0 |
| R_emaildomain_freq | 0.0 | 100.0 | 0.0 |
| M1_freq | 0.0 | 100.0 | 0.0 |
| M2_freq | 0.0 | 100.0 | 0.0 |
| M3_freq | 0.0 | 100.0 | 0.0 |
| M4_freq | 0.0 | 100.0 | 0.0 |
| M5_freq | 0.0 | 100.0 | 0.0 |
| M6_freq | 0.0 | 100.0 | 0.0 |
| M7_freq | 0.0 | 100.0 | 0.0 |
| M8_freq | 0.0 | 100.0 | 0.0 |
| M9_freq | 0.0 | 100.0 | 0.0 |

## 5. Segments — recall by product type
| ProductCD | txns | frauds | offline recall @0.50 | live recall @0.50 | live recall @0.10 |
|---|---|---|---|---|---|
| C | 13532 | 1591 | 93.8% | 4.0% | 63.5% |
| H | 6599 | 340 | 90.6% | 7.9% | 86.8% |
| R | 7448 | 272 | 85.7% | 8.1% | 88.2% |
| S | 2309 | 150 | 91.3% | 0.0% | 9.3% |
| W | 88220 | 1780 | 72.9% | 0.8% | 56.7% |

## 6. Real live-server events — recorded decision vs the truth
The export spans several runs with different threshold settings, so these recorded
decisions are mixed; section 3 re-applies each policy to the same server scores consistently.

| decision | fraud | legit |
|---|---|---|
| ALLOW | 95 | 4573 |
| BLOCK | 0 | 6 |
| REVIEW | 0 | 18 |

## 7. Sanity check against docs/model_evaluation.md (full run should match)
- roc_auc: this run **0.9562**, documented **0.9562**
- recall@0.5: this run **0.8393**, documented **0.8393**
- fpr@0.5: this run **0.0656**, documented **0.0656**

## Evidently reports (open in a browser)
- `01_offline_vs_live_same_transactions.html` — Reference = offline, Current = live; same transactions.
- `02_feature_drift_training_vs_live.html` — which of the 43 features look different live.
- `03_real_live_server_events.html` — the 4,692 events scored on the live server, against the true labels.

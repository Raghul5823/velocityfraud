# Model Evaluation — Champion Selection (Item 2)

Held-out IEEE-CIS test split: **118,108 rows**, fraud rate **3.50%**. Fraud-label threshold = 0.5.

| Model | ROC-AUC | PR-AUC | Precision | Recall | F1 | **FPR** | Specificity |
|-------|--------:|-------:|----------:|-------:|---:|--------:|------------:|
| RandomForest | 0.9498 | 0.6951 | 0.392 | 0.778 | 0.521 | **0.0439** | 0.9561 |
| XGBoost | 0.9562 | 0.7095 | 0.317 | 0.839 | 0.460 | **0.0656** | 0.9344 |

## Confusion matrix @ threshold 0.5 (TP / FP / TN / FN)

| Model | TP | FP | TN | FN |
|-------|---:|---:|---:|---:|
| RandomForest | 3,217 | 4,999 | 108,976 | 916 |
| XGBoost | 3,469 | 7,474 | 106,501 | 664 |

## Why XGBoost was selected for production

- **Higher ranking quality.** XGBoost ROC-AUC 0.9562 vs RandomForest 0.9498, and PR-AUC 0.7095 vs 0.6951. PR-AUC matters most on this **3.5% fraud** (highly imbalanced) data, and XGBoost wins it.
- **Higher recall (catches more fraud).** XGBoost recall 0.839 vs RandomForest 0.778 (+6.1 pp). In fraud, a missed fraud (false negative) is far costlier than a review.
- **FPR trade-off, made deliberately.** XGBoost FPR = **0.0656** (6.56%) is modestly *higher* than RandomForest's 0.0439 (4.39%) — the price of the higher recall above. This is the right call here because, at the operating threshold 0.5, a positive routes to **human REVIEW**, not a hard decline (BLOCK only fires at score >= 0.85). So the customer-facing *decline* rate is far below the raw FPR, while the extra recall genuinely catches more fraud.
- **Latency.** XGBoost predicts in ~37 ms in-process (see the k6 fast-path certificate, p95≈55 ms), satisfying the sub-100 ms budget.
- **Operability.** Single ARM-compatible artifact, native SHAP TreeExplainer support for per-decision explanations (Layer 4).

**Decision:** XGBoost is the production champion (CHAMPION.txt = `xgboost_v1.pkl`); RandomForest is retained as the challenger baseline.

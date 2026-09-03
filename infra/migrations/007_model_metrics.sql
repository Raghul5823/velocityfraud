-- ============================================================================
-- VelocityFraud — model_metrics table (Power BI Model Performance dashboard).
--
-- The proposal's "Model Performance Dashboard" (Section 5, Layer 3) requires
-- "RF vs XGB precision/recall/FPR/throughput vs latency". Those numbers were
-- only ever recorded as prose in docs/model_evaluation.md -- there was no
-- queryable source, which would have forced the dashboard to hardcode them
-- into static text boxes (unrefreshable, and disconnected from the actual
-- evaluation run).
--
-- This table makes them a real, queryable data source. Values are copied
-- verbatim from docs/model_evaluation.md (held-out IEEE-CIS test split:
-- 118,108 rows, 3.50% fraud rate, threshold 0.5) -- NOT re-derived or
-- estimated here.
--
-- Idempotent: safe to re-run (truncates and re-inserts the same fixed rows).
-- ============================================================================

CREATE TABLE IF NOT EXISTS model_metrics (
    model_name      VARCHAR(32)   PRIMARY KEY,
    is_champion     BOOLEAN       NOT NULL,
    roc_auc         NUMERIC(6, 4) NOT NULL,
    pr_auc          NUMERIC(6, 4) NOT NULL,
    precision_score NUMERIC(6, 4) NOT NULL,
    recall_score    NUMERIC(6, 4) NOT NULL,
    f1_score        NUMERIC(6, 4) NOT NULL,
    fpr             NUMERIC(6, 4) NOT NULL,
    specificity     NUMERIC(6, 4) NOT NULL,
    true_positives  INT           NOT NULL,
    false_positives INT           NOT NULL,
    true_negatives  INT           NOT NULL,
    false_negatives INT           NOT NULL,
    test_rows       INT           NOT NULL,
    fraud_rate      NUMERIC(6, 4) NOT NULL,
    evaluated_at    TIMESTAMPTZ   DEFAULT NOW()
);

-- Idempotent refresh of the two evaluated models.
DELETE FROM model_metrics WHERE model_name IN ('RandomForest', 'XGBoost');

INSERT INTO model_metrics (
    model_name, is_champion, roc_auc, pr_auc, precision_score, recall_score,
    f1_score, fpr, specificity, true_positives, false_positives,
    true_negatives, false_negatives, test_rows, fraud_rate
) VALUES
    ('RandomForest', false, 0.9498, 0.6951, 0.392, 0.778, 0.521, 0.0439, 0.9561,
     3217, 4999, 108976, 916, 118108, 0.0350),
    ('XGBoost',      true,  0.9562, 0.7095, 0.317, 0.839, 0.460, 0.0656, 0.9344,
     3469, 7474, 106501, 664, 118108, 0.0350);

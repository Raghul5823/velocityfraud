-- ============================================================================
-- VelocityFraud — Analyst feedback table (closes the feedback loop, Wk 12).
--
-- After a scored transaction is reviewed, an analyst records the GROUND TRUTH
-- verdict (FRAUD / LEGIT). This is the labelled data that (a) measures how often
-- the model's flag agreed with a human, and (b) feeds future retraining.
--
-- Flow:
--   1. feedback.submit_feedback(event_id, verdict, analyst, notes)
--   2. We look up the scored event (model_decision + fraud_score) in Postgres
--   3. INSERT a row here + PRODUCE the same event to Kafka `transactions.feedback`
--      (so a streaming retraining/label store can consume it downstream)
--
-- Idempotent: safe to re-run.
-- ============================================================================

CREATE TABLE IF NOT EXISTS feedback_events (
    feedback_id       BIGSERIAL PRIMARY KEY,
    event_id          VARCHAR(40)  NOT NULL,
    analyst_name      VARCHAR(255),
    analyst_role      VARCHAR(20)  NOT NULL,          -- 'analyst' | 'system'
    model_decision    VARCHAR(10)  NOT NULL,          -- ALLOW | REVIEW | BLOCK
    model_fraud_score NUMERIC(10, 8),
    analyst_verdict   VARCHAR(10)  NOT NULL,          -- 'FRAUD' | 'LEGIT'
    model_agreed      BOOLEAN      NOT NULL,          -- did the model's flag match the verdict?
    notes             TEXT,
    submitted_at      TIMESTAMPTZ  DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_event_id  ON feedback_events(event_id);
CREATE INDEX IF NOT EXISTS idx_feedback_submitted ON feedback_events(submitted_at);
CREATE INDEX IF NOT EXISTS idx_feedback_verdict   ON feedback_events(analyst_verdict);

-- Model-vs-analyst agreement summary for the Operational Health dashboard.
CREATE OR REPLACE VIEW feedback_agreement AS
SELECT
    COUNT(*)                                              AS total_feedback,
    SUM(CASE WHEN model_agreed THEN 1 ELSE 0 END)         AS agreements,
    ROUND(AVG(CASE WHEN model_agreed THEN 1 ELSE 0 END), 4) AS agreement_rate,
    SUM(CASE WHEN analyst_verdict = 'FRAUD' THEN 1 ELSE 0 END) AS analyst_fraud,
    SUM(CASE WHEN analyst_verdict = 'LEGIT' THEN 1 ELSE 0 END) AS analyst_legit
FROM feedback_events;

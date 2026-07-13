-- ============================================================================
-- VelocityFraud Layer 8 — Appeals table for compliance / audit trail.
--
-- Every time a customer or analyst appeals a BLOCKED transaction, we record
-- it here. Appeal handling flow:
--
--   1. Someone calls appeal.submit_appeal(event_id, reason, appellant)
--   2. We whitelist the relevant entities in Redis (short TTL)
--   3. We INSERT a row into appeals with resolved_at = NULL
--   4. We re-emit the original event to transactions.raw with appeal_id
--   5. Scorer runs -> blocklist skipped (whitelist wins) -> ML runs fresh
--   6. When a human reviewer marks it resolved (or the pipeline decides), we
--      UPDATE resolved_at + final_decision + resolution_notes
--
-- Idempotent: safe to re-run.
-- ============================================================================

CREATE TABLE IF NOT EXISTS appeals (
    appeal_id            BIGSERIAL PRIMARY KEY,
    event_id             VARCHAR(40)  NOT NULL,
    appellant_name       VARCHAR(255),
    appellant_role       VARCHAR(20)  NOT NULL,  -- 'customer' | 'analyst' | 'system'
    reason               TEXT         NOT NULL,
    submitted_at         TIMESTAMPTZ  DEFAULT NOW(),
    original_decision    VARCHAR(10)  NOT NULL,
    original_fraud_score NUMERIC(10, 8),
    -- populated AFTER the ML re-runs on the appealed event:
    resolved_at          TIMESTAMPTZ,
    final_decision       VARCHAR(10),
    final_fraud_score    NUMERIC(10, 8),
    resolution_notes     TEXT,
    whitelisted_entities JSONB
);

CREATE INDEX IF NOT EXISTS idx_appeals_event_id     ON appeals(event_id);
CREATE INDEX IF NOT EXISTS idx_appeals_submitted    ON appeals(submitted_at);
CREATE INDEX IF NOT EXISTS idx_appeals_unresolved   ON appeals(resolved_at) WHERE resolved_at IS NULL;

-- Quick view for the fraud-ops team: unresolved appeals ordered oldest-first.
CREATE OR REPLACE VIEW unresolved_appeals AS
SELECT appeal_id, event_id, appellant_role, submitted_at,
       original_decision, original_fraud_score, LEFT(reason, 100) AS reason_preview,
       EXTRACT(EPOCH FROM (NOW() - submitted_at)) / 60 AS minutes_waiting
FROM appeals
WHERE resolved_at IS NULL
ORDER BY submitted_at ASC;

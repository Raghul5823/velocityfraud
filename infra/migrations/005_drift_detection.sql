-- ============================================================================
-- VelocityFraud — Drift detection (closes proposal gap, docs/proposal_gap_remediation.md).
--
-- Proposal §10.3: "Drift detection on fast-path-vs-shadow agreement — if Groq
-- and the shadow XGBoost disagree on >5% of transactions in a window, an
-- alarm fires; one of the two has drifted and needs investigation."
--
-- The per-event comparison (scorer_comparison view) already existed from
-- 003_groq_scoring.sql. What was missing: a TIME WINDOW to aggregate over
-- (the original view has no timestamp) and somewhere to record when an
-- alarm actually fired, for audit/evidence purposes.
--
-- Idempotent: safe to re-run.
-- ============================================================================

-- scorer_comparison already includes scored_at_ms as of 003_groq_scoring.sql
-- (that file was updated retroactively so migration replay from 001 stays
-- consistent -- see the comment there for why). Nothing to redefine here.

-- Audit log of drift-alarm checks (every check is recorded, not just the
-- ones that fired an alarm — so we can also prove the check ran and was
-- healthy most of the time, not just show the failures).
CREATE TABLE IF NOT EXISTS drift_checks (
    check_id            BIGSERIAL PRIMARY KEY,
    window_minutes      INT             NOT NULL,
    compared_count      INT             NOT NULL,
    disagreement_count  INT             NOT NULL,
    disagreement_rate   NUMERIC(6, 4)   NOT NULL,
    threshold           NUMERIC(6, 4)   NOT NULL,
    alarm_fired         BOOLEAN         NOT NULL,
    checked_at          TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_drift_checked_at ON drift_checks(checked_at);
CREATE INDEX IF NOT EXISTS idx_drift_alarm      ON drift_checks(alarm_fired) WHERE alarm_fired = TRUE;

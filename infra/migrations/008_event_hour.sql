-- ============================================================================
-- VelocityFraud — event_hour computed column (Power BI Fraud Trend dashboard).
--
-- Real bug/limitation found live: a DAX calculated column deriving hour-of-day
-- from scored_at_ms failed under DirectQuery with "we couldn't fold the
-- expression to the data source" -- a known DirectQuery limitation where
-- certain DAX date-math doesn't translate to SQL for the Postgres connector.
--
-- Fix: compute it natively in Postgres as a GENERATED ALWAYS AS STORED column
-- -- self-maintaining (recomputed automatically on every insert/update),
-- and since it's a real column (not a DAX construct), DirectQuery reads it
-- with zero folding issues.
--
-- Idempotent: safe to re-run.
-- ============================================================================

-- First attempt used EXTRACT(HOUR FROM TO_TIMESTAMP(...)) directly, which
-- Postgres rejected ("generation expression is not immutable") because
-- extracting HOUR from a timestamptz depends on the session's timezone
-- setting. Anchoring explicitly to UTC makes the expression deterministic.
ALTER TABLE scored_events
  ADD COLUMN IF NOT EXISTS event_hour INT
  GENERATED ALWAYS AS (
    EXTRACT(HOUR FROM (TO_TIMESTAMP(scored_at_ms / 1000.0) AT TIME ZONE 'UTC'))::INT
  ) STORED;

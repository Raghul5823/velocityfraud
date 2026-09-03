-- ============================================================================
-- VelocityFraud — event_day_of_week computed column (Power BI Fraud Trend).
--
-- Replaces the merchant_country chart, which showed only meaningless
-- anonymized codes ("00","87","96" -- IEEE-CIS obscures this field with no
-- published decode key). Same GENERATED ALWAYS AS STORED pattern as
-- 008_event_hour.sql, anchored to UTC for the same immutability reason.
--
-- Idempotent: safe to re-run.
-- ============================================================================

-- First attempt used TO_CHAR(..., 'Day'), which Postgres also rejected as
-- not immutable -- day-name formatting depends on the database's locale
-- setting. EXTRACT(DOW ...) is locale-independent (always 0=Sunday..
-- 6=Saturday), and the CASE below hardcodes English names ourselves instead
-- of relying on locale-sensitive formatting.
ALTER TABLE scored_events
  ADD COLUMN IF NOT EXISTS event_day_of_week TEXT
  GENERATED ALWAYS AS (
    CASE EXTRACT(DOW FROM (TO_TIMESTAMP(scored_at_ms / 1000.0) AT TIME ZONE 'UTC'))
      WHEN 0 THEN 'Sunday'
      WHEN 1 THEN 'Monday'
      WHEN 2 THEN 'Tuesday'
      WHEN 3 THEN 'Wednesday'
      WHEN 4 THEN 'Thursday'
      WHEN 5 THEN 'Friday'
      WHEN 6 THEN 'Saturday'
    END
  ) STORED;

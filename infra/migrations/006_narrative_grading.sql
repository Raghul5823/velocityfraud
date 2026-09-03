-- ============================================================================
-- VelocityFraud — narrative_grading_passed column (real bug fix, 2026-09-02).
--
-- This field was added to the TransactionEnrichedEvent Avro schema and to
-- slow_path.py's output when the AI-validates-AI narrative grader was built
-- (see docs/ai_assisted_qa.md) -- but the matching Postgres column and the
-- sink.py INSERT were never added. The field was being silently dropped on
-- the way into Postgres (no crash, no error -- it just never landed).
-- Discovered live while bulk-generating alert-feed data for Power BI, via a
-- query that referenced the column and failed with "column does not exist."
--
-- Idempotent: safe to re-run.
-- ============================================================================

ALTER TABLE enriched_events ADD COLUMN IF NOT EXISTS narrative_grading_passed BOOLEAN DEFAULT true;

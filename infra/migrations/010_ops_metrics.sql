-- ============================================================================
-- VelocityFraud — ops_metrics table (Operational Health dashboard).
--
-- Closes the last visible hole in the Operational Health dashboard. The
-- proposal (Section 5, Layer 3) requires that view to show "Kafka consumer
-- lag ... Groq RPM headroom", and Section 5 Layer 1 says lag "is monitored
-- via JMX and surfaced in Power BI". No JMX exporter was ever built (tracked
-- as gap B5), so those two panels had no data source at all.
--
-- Rather than stand up a full JMX/Prometheus stack for two numbers, this
-- takes the pragmatic route: a generic metric time-series table, populated by
-- scripts/poll-ops-metrics.ps1, which reads lag straight from Kafka's own
-- kafka-consumer-groups.sh and derives Groq RPM from rows actually written to
-- scored_events_groq. Both are real measurements, just collected by polling
-- instead of JMX -- an honest substitution, recorded as such.
--
-- Deliberately generic (metric_name/scope/value) so further operational
-- metrics can be added later without another migration.
--
-- Idempotent: safe to re-run.
-- ============================================================================

CREATE TABLE IF NOT EXISTS ops_metrics (
    metric_id    BIGSERIAL      PRIMARY KEY,
    metric_name  VARCHAR(64)    NOT NULL,   -- kafka_consumer_lag | groq_rpm_used | groq_rpm_headroom
    scope        VARCHAR(160)   NOT NULL,   -- "<group>/<topic>" for lag, 'global' for Groq
    metric_value NUMERIC(14, 4) NOT NULL,
    captured_at  TIMESTAMPTZ    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ops_metrics_name    ON ops_metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_ops_metrics_time    ON ops_metrics(captured_at);

-- Convenience view: the latest value per metric+scope, which is what the
-- dashboard cards want (a table of every historical poll is for the trend
-- charts, not the KPI tiles).
CREATE OR REPLACE VIEW ops_metrics_latest AS
SELECT DISTINCT ON (metric_name, scope)
    metric_name, scope, metric_value, captured_at
FROM ops_metrics
ORDER BY metric_name, scope, captured_at DESC;

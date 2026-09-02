-- ============================================================================
-- VelocityFraud Layer 5b — Groq LLM scoring parallel path
--
-- Mirrors `scored_events` but stores scores from the Groq LLM classifier.
-- Same primary key (event_id) so a JOIN gives XGBoost vs Groq side-by-side.
--
-- Source topic: transactions.scored.groq
-- Consumer:     src/velocityfraud/sink.py (topic-routed)
--
-- Idempotent: safe to run multiple times.
-- ============================================================================

CREATE TABLE IF NOT EXISTS scored_events_groq (
    event_id                VARCHAR(40)   PRIMARY KEY,
    event_timestamp_ms      BIGINT        NOT NULL,
    customer_id             VARCHAR(40),
    card_token              VARCHAR(20),
    amount                  NUMERIC(14, 4),
    currency                VARCHAR(3),
    amount_fx_normalised    NUMERIC(14, 4),
    merchant_id_hash        VARCHAR(20),
    merchant_name           VARCHAR(255),
    mcc                     VARCHAR(8),
    merchant_country        VARCHAR(8),
    ip_address_hash         VARCHAR(20),
    device_fingerprint_hash VARCHAR(20),
    geo_distance_km         NUMERIC(10, 4),
    source_label            VARCHAR(32),
    schema_version          VARCHAR(8),

    fraud_score             NUMERIC(10, 8) NOT NULL,
    decision                VARCHAR(10)    NOT NULL,
    model_name              VARCHAR(64),   -- e.g. "groq:llama-3.1-8b-instant"
    model_version           VARCHAR(16),   -- Groq API version tag
    scored_at_ms            BIGINT,
    scoring_latency_ms      INT,           -- includes network round-trip to Groq
    feature_completeness    NUMERIC(6, 4),

    -- Groq-specific: the natural-language reason from the LLM
    llm_reason              TEXT,

    inserted_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_groq_decision    ON scored_events_groq(decision);
CREATE INDEX IF NOT EXISTS idx_groq_customer    ON scored_events_groq(customer_id);
CREATE INDEX IF NOT EXISTS idx_groq_event_ts    ON scored_events_groq(event_timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_groq_score       ON scored_events_groq(fraud_score);


-- ---------------------------------------------------------------------------
-- View: side-by-side comparison of XGBoost vs Groq on the same event
--
-- scored_at_ms is included here (not just added later in
-- 005_drift_detection.sql) because migrations are replayed from 001 in
-- order on every consumer startup (see db.py::apply_migrations) -- if this
-- file defined a SHORTER view than what 005 later replaces it with,
-- replaying 003 after 005 has already run would try to DROP a trailing
-- column via CREATE OR REPLACE VIEW, which Postgres refuses outright. Both
-- migrations must agree on the same final shape.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW scorer_comparison AS
SELECT
    x.event_id,
    x.customer_id,
    x.amount,
    x.merchant_name,
    x.mcc,

    -- XGBoost side
    x.fraud_score  AS xgb_score,
    x.decision     AS xgb_decision,
    x.scoring_latency_ms AS xgb_latency_ms,

    -- Groq side
    g.fraud_score  AS groq_score,
    g.decision     AS groq_decision,
    g.scoring_latency_ms AS groq_latency_ms,
    g.llm_reason,

    -- Agreement
    (x.decision = g.decision)               AS decisions_agree,
    ABS(x.fraud_score - g.fraud_score)      AS score_diff,

    -- Added in 005_drift_detection.sql for windowed drift detection; kept
    -- here too so 003 and 005 never disagree on the view's shape.
    x.scored_at_ms
FROM scored_events x
INNER JOIN scored_events_groq g ON g.event_id = x.event_id;

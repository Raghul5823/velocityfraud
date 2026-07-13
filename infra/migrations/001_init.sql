-- ============================================================================
-- VelocityFraud Layer 6 — Initial PostgreSQL schema
--
-- Two tables:
--   scored_events    : every transaction the fast-path saw (one row per event)
--   enriched_events  : flagged transactions only (REVIEW + BLOCK) with SHAP +
--                      narrative + (forward-compat) Layer 5 text anomaly columns
--
-- Idempotent: safe to run multiple times.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Table: scored_events
-- One row per event seen by the fast-path scorer. Includes ALLOW/REVIEW/BLOCK.
-- Source topic: transactions.scored
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scored_events (
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
    model_name              VARCHAR(64),
    model_version           VARCHAR(16),
    scored_at_ms            BIGINT,
    scoring_latency_ms      INT,
    feature_completeness    NUMERIC(6, 4),

    inserted_at             TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for typical dashboard / fraud-ops queries
CREATE INDEX IF NOT EXISTS idx_scored_decision     ON scored_events(decision);
CREATE INDEX IF NOT EXISTS idx_scored_customer     ON scored_events(customer_id);
CREATE INDEX IF NOT EXISTS idx_scored_event_ts     ON scored_events(event_timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_scored_score        ON scored_events(fraud_score);
CREATE INDEX IF NOT EXISTS idx_scored_inserted_at  ON scored_events(inserted_at);

-- Layer 8 forward-compat columns (nullable so old rows don't break)
ALTER TABLE scored_events ADD COLUMN IF NOT EXISTS blocklist_hit    BOOLEAN;
ALTER TABLE scored_events ADD COLUMN IF NOT EXISTS blocklist_tier   VARCHAR(10);
ALTER TABLE scored_events ADD COLUMN IF NOT EXISTS blocklist_reason TEXT;
CREATE INDEX IF NOT EXISTS idx_scored_blocklist ON scored_events(blocklist_hit) WHERE blocklist_hit = TRUE;


-- ---------------------------------------------------------------------------
-- Table: enriched_events
-- One row per FLAGGED event (REVIEW or BLOCK) — has SHAP + narrative.
-- Layer 5 (text anomaly) will populate text_anomaly_* columns later via
-- UPDATE. These columns are nullable today so Layer 6 can ship now.
-- Source topic: transactions.enriched
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS enriched_events (
    event_id                VARCHAR(40)   PRIMARY KEY,
    customer_id             VARCHAR(40),
    amount                  NUMERIC(14, 4),
    merchant_name           VARCHAR(255),
    mcc                     VARCHAR(8),

    fraud_score             NUMERIC(10, 8) NOT NULL,
    decision                VARCHAR(10)    NOT NULL,
    feature_completeness    NUMERIC(6, 4),

    -- SHAP attributions: nested array of {feature_name, feature_value, shap_value}.
    -- JSONB lets us run queries like:
    --   SELECT * FROM enriched_events
    --   WHERE top_contributors @> '[{"feature_name": "TransactionAmt"}]';
    top_contributors        JSONB         NOT NULL,
    narrative               TEXT          NOT NULL,
    narrator_mode           VARCHAR(16)   NOT NULL,

    enriched_at_ms          BIGINT        NOT NULL,
    enrichment_latency_ms   INT,

    -- ---- FORWARD-COMPAT: Layer 5 (text anomaly) will populate these ----
    text_anomaly_score      NUMERIC(10, 6) NULL,
    text_anomaly_label      VARCHAR(16)    NULL,
    text_scored_at_ms       BIGINT         NULL,

    inserted_at             TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_enriched_decision        ON enriched_events(decision);
CREATE INDEX IF NOT EXISTS idx_enriched_customer        ON enriched_events(customer_id);
CREATE INDEX IF NOT EXISTS idx_enriched_narrator_mode   ON enriched_events(narrator_mode);
CREATE INDEX IF NOT EXISTS idx_enriched_inserted_at     ON enriched_events(inserted_at);
CREATE INDEX IF NOT EXISTS idx_enriched_text_anomaly    ON enriched_events(text_anomaly_score);
-- GIN index on JSONB lets us efficiently query the SHAP contributors array
CREATE INDEX IF NOT EXISTS idx_enriched_contribs_gin    ON enriched_events USING GIN (top_contributors);


-- ---------------------------------------------------------------------------
-- View: decision_distribution_24h
-- Quick aggregate for the Power BI dashboard — last 24h decision split.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW decision_distribution_24h AS
SELECT
    decision,
    COUNT(*) AS event_count,
    ROUND(AVG(fraud_score) * 100, 2) AS avg_score_pct,
    ROUND(AVG(scoring_latency_ms), 2) AS avg_latency_ms
FROM scored_events
WHERE inserted_at >= NOW() - INTERVAL '24 hours'
GROUP BY decision
ORDER BY decision;


-- ---------------------------------------------------------------------------
-- View: top_flagged_customers
-- Customers with the most REVIEW or BLOCK events.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW top_flagged_customers AS
SELECT
    customer_id,
    COUNT(*) FILTER (WHERE decision = 'BLOCK')   AS block_count,
    COUNT(*) FILTER (WHERE decision = 'REVIEW')  AS review_count,
    COUNT(*) FILTER (WHERE decision = 'ALLOW')   AS allow_count,
    ROUND(AVG(fraud_score)::numeric, 4) AS avg_fraud_score,
    MAX(fraud_score) AS max_fraud_score
FROM scored_events
GROUP BY customer_id
HAVING COUNT(*) FILTER (WHERE decision IN ('REVIEW', 'BLOCK')) > 0
ORDER BY (COUNT(*) FILTER (WHERE decision = 'BLOCK')) DESC,
         (COUNT(*) FILTER (WHERE decision = 'REVIEW')) DESC
LIMIT 100;

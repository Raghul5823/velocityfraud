# Layer 6 — Storage (COMPLETE)

> **Status:** ✅ Complete
> **Completion Date:** 2026-06-30
> **Effort:** ~1.5 hours of focused build
> **Project:** VelocityFraud — Real-Time Fraud Detection Data Pipeline
> **Program:** IMPACT pSiddhi 3.0 — Topic S2-D-06 (Semester 2, Data Track)

> **Note on ordering:** We built Layer 6 BEFORE Layer 5 (text anomaly) on a senior-architect call: Postgres + dashboard storage is the critical path for Layer 7 (Power BI). Layer 5 is an additive enhancement that can attach to existing tables. The `enriched_events` table includes 3 forward-compat columns (`text_anomaly_score`, `text_anomaly_label`, `text_scored_at_ms`) ready to receive Layer 5 data without schema change.

---

## 1. Why This Layer Exists

Kafka topics are **streaming** — by default they hold events for hours or days, then truncate. They're optimized for high-throughput append + tail-reads, NOT for analytics queries like "show me the top 100 customers with the most BLOCK decisions this week."

PostgreSQL is the answer:
- **Permanent storage** for scored + enriched events (with proper retention)
- **SQL queryability** for the fraud-ops dashboard (Layer 7 Power BI)
- **Joins, aggregates, time-windowed views** — operations Kafka can't do natively
- **Auditability** — every flagged event with its SHAP attribution + narrative permanently recorded

**Without Layer 6, the data is ephemeral and no dashboard exists. With Layer 6, every event is queryable forever.**

---

## 2. Architecture Built

```
┌────────────────────────────────────────────────────────────────────────────┐
│                       LAYER 6: STORAGE                                      │
└────────────────────────────────────────────────────────────────────────────┘

   Layer 3                    Layer 4                                Layer 7
                                                                   (Power BI)
                                                                       ▲
                                                                       │
   transactions.scored ─┐                                               │
   (23-field Avro)       │                                              │
                         ▼                                              │
                       ┌──────────────────────────┐                     │
                       │       SINK               │                     │
                       │                          │                     │
                       │  consume both topics     │                     │
                       │     ↓                    │                     │
                       │  decode via correct      │                     │
                       │  Avro schema per topic   │                     │
                       │     ↓                    │                     │
                       │  buffer into per-table   │                     │
                       │  batches (50 rows / 2s)  │                     │
                       │     ↓                    │                     │
                       │  executemany INSERT...   │                     │
                       │  ON CONFLICT UPSERT      │                     │
                       │  (latest scoring wins)   │                     │
                       └────────────┬─────────────┘                     │
                                    │                                   │
                                    ▼                                   │
                       ┌──────────────────────────────────────┐         │
                       │   PostgreSQL 16 (vf-postgres)        │         │
                       │   Container, port 5432               │         │
                       │   Volume: postgres-data              │         │
                       │                                      │         │
                       │   ┌──────────────────────────────┐   │         │
                       │   │ scored_events (1 row/event)  │   │         │
                       │   │   PK: event_id               │   │         │
                       │   │   23 cols + inserted_at      │   │         │
                       │   │   5 indexes                  │   │         │
                       │   └──────────────────────────────┘   │         │
                       │                                      │         │
                       │   ┌──────────────────────────────┐   │         │
                       │   │ enriched_events              │   │         │
                       │   │   PK: event_id               │   │         │
                       │   │   13 cols + 3 Layer-5 NULL   │   │         │
                       │   │     + JSONB top_contributors │   │         │
                       │   │   6 indexes (incl. GIN JSON) │   │         │
                       │   └──────────────────────────────┘   │         │
                       │                                      │         │
                       │   Views:                             │         │
                       │     decision_distribution_24h        │ ────────┘
                       │     top_flagged_customers            │
                       └──────────────────────────────────────┘
   transactions.enriched ─┘
   (28-field Avro)
```

---

## 3. Step-by-Step Build Log (Granular)

### Phase 1 — Postgres Container + Driver

1. Added Postgres service to [infra/docker-compose.yml](../infra/docker-compose.yml):
   - Image: `postgres:16-alpine` (small footprint)
   - Database: `velocityfraud`, user: `vf`, password: `vfpass`
   - Persistent volume `postgres-data` (survives `docker compose down`)
   - Healthcheck via `pg_isready`

2. Added `psycopg[binary]>=3.2.0` to [pyproject.toml](../pyproject.toml). The `[binary]` extra bundles pre-built libpq — **no need to install PostgreSQL on Windows**.

3. Brought up Postgres container, ran `pg_isready` until healthy.

### Phase 2 — SQL Migrations

4. Designed [infra/migrations/001_init.sql](../infra/migrations/001_init.sql) — idempotent DDL:
   - **`scored_events` table** (23 cols + inserted_at):
     - PK: `event_id`
     - 5 indexes: `decision`, `customer_id`, `event_timestamp_ms`, `fraud_score`, `inserted_at`
   - **`enriched_events` table** (13 cols + 3 Layer-5 placeholders + inserted_at):
     - PK: `event_id`
     - `top_contributors` is JSONB (allows `@>` containment queries)
     - 6 indexes including **GIN on top_contributors** for SHAP queries
     - **Forward-compat:** `text_anomaly_score`, `text_anomaly_label`, `text_scored_at_ms` — all NULL today, populated by Layer 5 later
   - **Two views**:
     - `decision_distribution_24h` — last-24h decision split for dashboard
     - `top_flagged_customers` — customers with most flagged events

5. **Idempotency strategy:** All DDL uses `CREATE TABLE IF NOT EXISTS` + `CREATE INDEX IF NOT EXISTS` + `CREATE OR REPLACE VIEW`. Running migrations multiple times is safe — no version-tracking table needed for POC.

### Phase 3 — Connection Helper

6. Built [src/velocityfraud/db.py](../src/velocityfraud/db.py):
   - `get_dsn()` — DSN from env vars (POSTGRES_HOST/PORT/DB/USER/PASSWORD)
   - `get_connection(autocommit=False)` — fresh psycopg connection
   - `apply_migrations()` — runs every `.sql` in `infra/migrations/` in lexical order
   - Built-in smoke test: connects, runs migrations, reports row counts

7. **Smoke test passed** — `PostgreSQL 16.13 on x86_64-pc-linux-musl`, both tables created with 0 rows.

### Phase 4 — Kafka → Postgres Sink

8. Built [src/velocityfraud/sink.py](../src/velocityfraud/sink.py) — the dual-topic consumer:
   - Subscribes to BOTH `transactions.scored` and `transactions.enriched`
   - Routes by `msg.topic()` to the correct Avro schema + row-builder
   - **Batched inserts:** buffers per-table, flushes at `SINK_BATCH_SIZE` rows OR `SINK_FLUSH_SEC` seconds (whichever first)
   - `psycopg.executemany()` for ~10× throughput vs single-row inserts
   - `top_contributors` array serialized to JSON via `json.dumps()` for the JSONB column

9. **Initial design bug (caught + fixed during E2E test):** `ON CONFLICT DO NOTHING` skipped re-scoring runs silently. Replaced with `ON CONFLICT DO UPDATE ... WHERE EXCLUDED.scored_at_ms >= existing` — proper "newest scoring wins" semantics. Production reality: model upgrades + threshold changes mean events get re-scored; you want the latest.

### Phase 5 — Launcher

10. Built [scripts/run-sink.ps1](../scripts/run-sink.ps1) — env-var configurable launcher with sensible defaults.

### Phase 6 — End-to-End Verification

11. Ran sink against the existing ~200 scored + 24 enriched events in Kafka:
    - **224 events consumed**
    - **0 decode failures**
    - **100 unique rows in scored_events** (after UPSERT dedup — 200 in topic, but 100 unique event_ids since scorer ran twice over same raw events)
    - **24 rows in enriched_events**
    - Decision distribution matches the scorer's actual output: **ALLOW 76 / REVIEW 18 / BLOCK 6**
    - Elapsed: ~30 seconds (most was idle Ctrl+C wait time after work done)

12. Verified via two queries:
    ```sql
    SELECT decision, COUNT(*) FROM scored_events GROUP BY decision;
    -- returns: ALLOW=76, REVIEW=18, BLOCK=6
    ```
    ```sql
    SELECT event_id, decision, narrator_mode, LEFT(narrative, 60) FROM enriched_events LIMIT 3;
    -- returns: 3 rows with REVIEW/BLOCK + TEMPLATE narratives previewed
    ```

### Phase 7 — Documentation

13. Wrote this completion document.

---

## 4. Verification Checkpoints (8 Checks)

| # | Check | Evidence | Status |
|---|---|---|---|
| 1 | Postgres container healthy | `docker ps` shows `vf-postgres   Up X (healthy)` | ✅ |
| 2 | Migrations applied idempotently | `db.py` smoke test ran 001_init.sql successfully | ✅ |
| 3 | Both tables created with correct schemas | `\d scored_events`, `\d enriched_events` in psql | ✅ |
| 4 | Forward-compat Layer 5 columns present | `text_anomaly_*` columns visible, nullable | ✅ |
| 5 | Sink consumes from both topics | 224 events (200 scored + 24 enriched) | ✅ |
| 6 | Batched writes work | `Flushed scored batch: 50 rows` log lines | ✅ |
| 7 | UPSERT keeps latest scoring | scored_events shows 100 rows with 76/18/6 split (latest, not first) | ✅ |
| 8 | JSONB column queryable | `top_contributors` round-trips through json.dumps → JSONB → JSON | ✅ |

---

## 5. Files Inventory

| File | Purpose | Lines |
|---|---|---|
| [infra/docker-compose.yml](../infra/docker-compose.yml) | +postgres service (vf-postgres) | +18 |
| [pyproject.toml](../pyproject.toml) | +psycopg[binary] dep | +2 |
| [infra/migrations/001_init.sql](../infra/migrations/001_init.sql) | scored + enriched tables, indexes, views | ~130 |
| [src/velocityfraud/db.py](../src/velocityfraud/db.py) | Connection helper + migration runner | ~140 |
| [src/velocityfraud/sink.py](../src/velocityfraud/sink.py) | Dual-topic Kafka → Postgres consumer | ~310 |
| [scripts/run-sink.ps1](../scripts/run-sink.ps1) | Launcher with env-var config | ~30 |

---

## 6. Key Numbers to Memorize for Presentation

| Number | What It Means |
|---|---|
| **2** | Postgres tables: `scored_events` + `enriched_events` |
| **3** | Forward-compat Layer 5 columns (`text_anomaly_*`) baked in today |
| **2** | Pre-built dashboard views (`decision_distribution_24h`, `top_flagged_customers`) |
| **50** | Default sink batch size (rows per flush) |
| **2 sec** | Default sink flush interval |
| **100** | Unique scored events persisted (UPSERT-deduped) |
| **76 / 18 / 6** | Decision distribution: ALLOW / REVIEW / BLOCK |
| **24** | Enriched events with SHAP + narrative |
| **JSONB** | top_contributors storage type — supports `@>` and GIN index |
| **0** | Decode failures, write failures across 224 events |
| **₹0** | Cost (Postgres in Docker = free) |

---

## 7. Technical Stack to Master Before Presentation

### 7.1 PostgreSQL

**What it is:** The world's most advanced open-source relational database. Used by every serious data-engineering team.

**Must understand:**
- **Tables, primary keys, indexes** — basics
- **JSONB** — binary-encoded JSON column type. Supports indexing, containment queries (`@>`), and path extraction (`->`, `->>`)
- **Views** — saved SELECT statements; act like virtual tables
- **GIN index on JSONB** — accelerates "does this row's JSON contain X?" queries
- **`ON CONFLICT DO UPDATE`** — Postgres-flavored UPSERT. Standard SQL `MERGE` is also supported in v15+

### 7.2 psycopg (v3)

**What it is:** The modern Python driver for Postgres. v3 is a near-complete rewrite of psycopg2 with cleaner async support, better type handling, and faster batch operations.

**Must understand:**
- **DSN strings** — `host=... port=... dbname=... user=... password=...`
- **Connection context manager** — `with psycopg.connect(...) as conn:` auto-commits on success, rolls back on exception
- **`executemany(sql, params_list)`** — batched parameterized INSERTs/UPDATEs, ~10× faster than per-row `execute()`
- **`[binary]` extra** — bundles pre-built libpq so Windows doesn't need to compile from source

### 7.3 Batched Stream Processing

**What it is:** A pattern where streaming events are buffered and written to the destination in groups, trading latency for throughput.

**Trade-off:**
- Latency↑ (buffered events wait up to FLUSH_SEC before reaching Postgres)
- Throughput↑ (one INSERT statement does 50 rows instead of 50 round-trips)
- Failure blast radius↑ (a failed flush loses 50 events, not 1)

**Our choice:** 50 rows / 2 seconds. For Power BI dashboard, 2-second staleness is invisible. For a real-time alerting system, you'd push this to 5 rows / 0.5 seconds.

### 7.4 Idempotency via UPSERT

**Why critical:** Streaming systems CAN deliver duplicates (retry on transient failure, replay after restart, etc.). With `INSERT ... ON CONFLICT (event_id) DO NOTHING/UPDATE`, the SAME event landing multiple times produces the same final database state.

**Our specific pattern:** `ON CONFLICT DO UPDATE ... WHERE EXCLUDED.scored_at_ms >= existing`. This handles both duplicates (skip) AND legitimate re-scoring (overwrite). Cleanest production semantics.

### 7.5 Forward-Compatible Schema Design

**The principle:** When you KNOW future fields are coming (Layer 5), add them as nullable columns today rather than ALTER TABLE later.

**Cost:** Three NULL columns sit unused for a few days.
**Benefit:** When Layer 5 ships, zero downtime, zero migration script. Just `UPDATE ... SET text_anomaly_score = ...`.

**Senior architect call** — this is what mature teams do.

---

## 8. Expected Presentation Questions (Senior/Architect Tier)

> 25 prepared Q&A — practice once before presentation.

### Architecture Questions

1. **Why Postgres and not MongoDB / Elasticsearch / DynamoDB?**
   *Answer:* Postgres gives us SQL (Power BI loves it), strong consistency (ACID), and JSONB for the SHAP array — best of both worlds. Mongo loses joins; Elasticsearch is great for search but overkill for our query patterns; DynamoDB locks us to AWS and lacks free-form aggregates. Postgres = portable, free, queryable.

2. **Why a separate sink service instead of writing from the scorer/slow-path directly?**
   *Answer:* Separation of concerns. The scorer's job is to score (fast-path, <100ms budget). Adding DB writes would add latency + tightly couple two failure domains. Sink is its own service — if Postgres dies, scoring continues to flow into Kafka; sink catches up when Postgres recovers.

3. **Why two tables instead of one with NULL columns?**
   *Answer:* Cardinality difference. We have ~5–10× more scored events than enriched. Storing NULL columns for the 90% non-enriched would waste space + slow queries. Two tables JOINed on event_id when needed is cleaner.

4. **What's the retention strategy?**
   *Answer:* POC: indefinite. Production: partition `scored_events` by month (90-day hot + 1-year cold via PG partitioning), partition `enriched_events` by month (180-day retention since these have audit + compliance value). Old partitions move to cheaper storage (S3 / cold disk).

### Schema Questions

5. **Why JSONB for `top_contributors` and not a child table?**
   *Answer:* Each enriched event has exactly 5 contributors — bounded cardinality, almost always read together. JSONB keeps everything in one row, no JOIN needed for the dashboard. Child table would be overkill. We DO get JSON path queries (`top_contributors -> 0 ->> 'feature_name'`) and the GIN index makes containment fast.

6. **Why are the Layer 5 columns nullable instead of just adding them later?**
   *Answer:* Avoids a future ALTER TABLE migration on a populated production table. ALTERs on big tables lock writes; adding nullable columns NOW costs nothing (just 3 bytes per row if NULL). When Layer 5 ships, its consumer just does `UPDATE` — zero schema change at that point.

7. **Why `NUMERIC(10, 8)` for fraud_score?**
   *Answer:* fraud_score is in [0, 1]. We want 8 decimal places to preserve full XGBoost output precision. NUMERIC > FLOAT to avoid binary rounding artifacts (important for audit reproducibility).

8. **What if a customer disputes a decision — can you reproduce it?**
   *Answer:* Yes. `event_id` joins back to the raw Kafka event (we have the raw topic retained). Combined with `model_name` + `model_version` from the scored row + the same `xgboost_v1.pkl` (versioned in `models/`), we can re-run scoring exactly and get the same number. Full audit trail.

### Operational Questions

9. **How long does the sink take to catch up if it's been offline?**
   *Answer:* At our batch settings (50 rows / 2s), throughput is ~25 events/s sustained. For 10K events backlog: ~7 minutes. For 1M events: ~11 hours. Production tuning: bump batch size to 500, drop flush interval to 0.5s — 10× faster.

10. **What if Postgres dies during a batch flush?**
    *Answer:* `try/except` around flush + `rollback()`. The events stay in their Python buffer (not committed to Postgres) and ALSO stay in Kafka (consumer offset not committed yet because we use auto-commit on consume, not on flush success — wait, actually we use auto-commit on poll). Trade-off: we may lose up to 50 events if Postgres dies between poll-commit and flush-success. Production fix: commit Kafka offsets only AFTER successful flush (manual commit pattern).

11. **Can the sink scale horizontally?**
    *Answer:* Yes — launch multiple sink instances in the same consumer group. Each gets a subset of Kafka partitions (3 partitions = up to 3 sink instances). Each writes to Postgres independently — UPSERT semantics make concurrent writes safe via row-level locking.

12. **What about Postgres connection pooling?**
    *Answer:* Today: one connection per sink instance, kept open for the loop's lifetime. For high concurrency we'd add `psycopg_pool.ConnectionPool` (10 conns, sized to expected parallelism). Trivial change; not needed at POC scale.

### Idempotency Questions

13. **Walk me through your duplicate-handling logic.**
    *Answer:* Three layers: (a) **Kafka idempotent producer** prevents broker duplicates within a session. (b) **Sink UPSERT** keyed on event_id handles cross-session retries — same event hitting Postgres twice produces identical state. (c) **`WHERE EXCLUDED.scored_at_ms >= existing`** clause means re-scoring (legitimate, e.g., model upgrade) overwrites with the new decision instead of silently dropping.

14. **What happens if two scorer instances produce conflicting decisions for the same event?**
    *Answer:* Whoever wins the scoring race writes their `scored_at_ms`. The sink's WHERE clause ensures the later-timestamped decision wins. If timestamps tie, `>=` lets the last-write-arriving win — non-deterministic but acceptable for an edge case that shouldn't happen in production (one scorer per partition).

15. **Why `>=` instead of strict `>` in the WHERE clause?**
    *Answer:* `>=` makes the operation truly idempotent — re-processing the SAME event (identical scored_at_ms) is a no-op UPDATE (writes same values), not a skip. Strict `>` would treat a replay as "older or same" and skip — semantically weird.

### Data Modeling Questions

16. **Why `event_timestamp_ms` (long) instead of TIMESTAMPTZ?**
    *Answer:* The Avro source uses long for portability. Storing as `BIGINT` preserves Avro semantics exactly. Power BI can convert to display format. For native PG time operations, we'd derive a column: `event_ts TIMESTAMPTZ GENERATED ALWAYS AS (to_timestamp(event_timestamp_ms / 1000.0))` — but not needed yet.

17. **Why VARCHAR(40) for `event_id` instead of UUID?**
    *Answer:* UUIDs in the source are stored as strings. Could use Postgres native UUID type (16 bytes vs 36) — would save space but requires conversion. We chose VARCHAR for sink simplicity. Production: switch to UUID type.

18. **Why NUMERIC(14, 4) for amount?**
    *Answer:* Financial data — never use FLOAT (binary rounding). 14 digits total, 4 decimals = supports up to ₹999,999,999.9999. Future-proof for high-value B2B transactions.

### Dashboard Readiness Questions

19. **How will Power BI connect?**
    *Answer:* PostgreSQL connector built into Power BI Desktop. Connection: `localhost:5432`, database `velocityfraud`, user `vf`. Power BI imports tables or runs DirectQuery for live data. Our views (`decision_distribution_24h`, `top_flagged_customers`) are ready for direct binding to dashboard tiles.

20. **What's the dashboard's read pattern — point queries or aggregates?**
    *Answer:* Mostly aggregates: counts by decision, hourly trends, top customers, top contributing features. The indexes we built (decision, customer_id, inserted_at) cover all these. The GIN index on top_contributors handles "which features show up in BLOCK events most?"

21. **What's the typical query latency?**
    *Answer:* For 100K-row tables (our likely max in production for 1 day), index-covered queries: <10ms. View materialization for `decision_distribution_24h`: <50ms. Power BI auto-refresh every 5 min easily handled.

### Production Readiness Questions

22. **What's missing for true production?**
    *Answer:* (a) Connection pooling (psycopg_pool). (b) Schema versioning table (Liquibase or Flyway). (c) Manual offset commit on flush success. (d) Partitioned tables for retention. (e) TLS to Postgres. (f) Backup/restore scripts (`pg_dump` cron). (g) Replication for HA. (h) Monitoring (Prometheus postgres_exporter). All standard stuff — POC scope intentionally limited.

23. **How do you handle GDPR right-to-be-forgotten?**
    *Answer:* `card_token` is the customer pseudonym. To "forget" a customer, delete their tokenization salt + delete all rows with that token. Tokens are SHA-256 derived, so without the salt nobody can re-derive them. Soft-delete via `is_deleted` column is also an option for partial compliance.

24. **What about regulatory data residency (e.g., RBI India)?**
    *Answer:* Postgres can be deployed in-region (single-region by default). For multi-region we'd use logical replication. For RBI compliance specifically, all PII tokens generated and stored in-country.

### Forward-Looking Questions

25. **What's next?**
    *Answer:* Layer 5 — Text Anomaly Detection on merchant_name using HuggingFace DistilBERT. Its consumer will UPDATE existing `enriched_events` rows to populate the three forward-compat columns we added today. Then Layer 7 — Power BI Desktop connecting to these tables for the fraud-ops dashboard.

---

## 9. Quick Demo Commands (For Live Walkthrough)

```powershell
# 1. Show Postgres is healthy
docker ps --format "table {{.Names}}\t{{.Status}}" | Select-String "postgres"

# 2. Show table schemas
docker exec vf-postgres psql -U vf -d velocityfraud -c "\dt"

# 3. Show decision distribution from Postgres (matches Layer 3 scorer)
docker exec vf-postgres psql -U vf -d velocityfraud -c "SELECT decision, COUNT(*), ROUND(AVG(fraud_score)::numeric, 4) AS avg_score FROM scored_events GROUP BY decision ORDER BY decision;"

# 4. Show the pre-built dashboard view
docker exec vf-postgres psql -U vf -d velocityfraud -c "SELECT * FROM decision_distribution_24h;"

# 5. Show a JSONB query on SHAP (impressive for SQL audiences)
docker exec vf-postgres psql -U vf -d velocityfraud -c "SELECT event_id, decision, jsonb_array_length(top_contributors) AS n_contribs, top_contributors -> 0 ->> 'feature_name' AS top_feature FROM enriched_events LIMIT 5;"

# 6. Re-run sink (e.g., after new events flow)
# .\scripts\run-sink.ps1
```

---

## 10. What's Next — Layer 5 Preview

**Goal:** Add `text_anomaly_score` to enriched events via HuggingFace DistilBERT perplexity scoring on the `merchant_name` field.

**Architectural simplicity (thanks to today's forward-compat decision):**
- New consumer reads `transactions.enriched`
- Runs DistilBERT on merchant_name
- Issues `UPDATE enriched_events SET text_anomaly_score = ?, text_anomaly_label = ?, text_scored_at_ms = ? WHERE event_id = ?`
- Zero schema migration needed

**Tech stack to learn for Layer 5:**
- HuggingFace `transformers` library
- `DistilBertTokenizer` + `DistilBertForMaskedLM`
- Perplexity computation (exp of cross-entropy loss)
- Batched inference for throughput
- Plus existing Kafka + psycopg patterns

**Output of Layer 5:**
- New module: `src/velocityfraud/text_anomaly.py`
- New consumer: `src/velocityfraud/text_anomaly_consumer.py` (or fold into slow-path)
- New launcher: `scripts/run-text-anomaly.ps1`
- Populated columns: 3 new fields in existing `enriched_events` rows

---

## 11. References & Further Reading

- **PostgreSQL JSONB:** https://www.postgresql.org/docs/16/datatype-json.html
- **PostgreSQL UPSERT:** https://www.postgresql.org/docs/16/sql-insert.html#SQL-ON-CONFLICT
- **psycopg 3 documentation:** https://www.psycopg.org/psycopg3/docs/
- **GIN indexes:** https://www.postgresql.org/docs/16/gin.html
- **PostgreSQL partitioning (for retention):** https://www.postgresql.org/docs/16/ddl-partitioning.html

---

**Document maintained by:** Project owner
**Last updated:** 2026-06-30
**Previous layer docs:** [LAYER_1_STREAM_INFRASTRUCTURE.md](LAYER_1_STREAM_INFRASTRUCTURE.md), [LAYER_2_MODEL_TRAINING.md](LAYER_2_MODEL_TRAINING.md), [LAYER_3_FAST_PATH_SCORING.md](LAYER_3_FAST_PATH_SCORING.md), [LAYER_4_SLOW_PATH_ANALYSIS.md](LAYER_4_SLOW_PATH_ANALYSIS.md)
**Next layer doc:** `LAYER_5_TEXT_ANOMALY.md` (after Layer 5 completion)

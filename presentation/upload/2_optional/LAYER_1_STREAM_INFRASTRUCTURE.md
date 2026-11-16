# Layer 1 — Stream Infrastructure (COMPLETE)

> **Status:** ✅ Complete
> **Completion Date:** 2026-06-29
> **Effort:** ~1 day of focused build (across multiple sessions)
> **Project:** VelocityFraud — Real-Time Fraud Detection Data Pipeline
> **Program:** IMPACT pSiddhi 3.0 — Topic S2-D-06 (Semester 2, Data Track)

---

## 1. Why This Layer Exists

The fraud detection system must process transactions **as they happen** — not in batches at midnight. To do that, every component (model scorer, dashboard, alerting) needs a reliable way to see every transaction in real-time. Layer 1 builds that **central nervous system**:

- A messaging backbone (Apache Kafka) that all components read from / write to
- A strict data contract (Avro schema) so every event has the same shape
- A way to inject historical transactions (the replayer) to simulate live traffic
- A way to read them back (the consumer) for downstream layers

**Without Layer 1, nothing else in the pipeline can function.** Layers 2–7 all depend on this stream existing.

---

## 2. Architecture Built

```
┌──────────────────────────────────────────────────────────────────────┐
│                     LAYER 1: STREAM INFRASTRUCTURE                   │
└──────────────────────────────────────────────────────────────────────┘

  ┌─────────────────┐                                ┌────────────────┐
  │  IEEE-CIS CSV   │                                │ Apicurio       │
  │  (590K rows)    │                                │ Schema Registry│
  │  train_txn.csv  │                                │ (port 8080)    │
  └────────┬────────┘                                └────────────────┘
           │                                          [Parked for POC]
           ▼
  ┌─────────────────┐    Avro    ┌─────────────────────────────────┐
  │   Replayer      │ ─────────► │  Apache Kafka 3.7 (KRaft mode)  │
  │   (Producer)    │  bytes     │                                 │
  │ replayer.py     │            │  Topics:                        │
  │                 │            │  • transactions.raw   (3 part.) │
  │ PRD.OIL CSV     │            │  • transactions.scored (3 part) │
  │  ↓ map          │            │  • transactions.enriched (1)    │
  │ TransactionEvent│            │                                 │
  │  ↓ encode       │            │  Container: vf-kafka            │
  │ Avro bytes      │            │  Port: 9092 (host)              │
  └─────────────────┘            └──────────┬──────────────────────┘
                                            │
                                            │ Avro bytes
                                            ▼
                                 ┌─────────────────────┐
                                 │   Consumer          │
                                 │   consumer.py       │
                                 │                     │
                                 │   ↓ decode          │
                                 │   Python dict       │
                                 │   ↓ log             │
                                 │   Human-readable    │
                                 └─────────────────────┘

  ┌─────────────────┐                                ┌────────────────┐
  │ Kafka UI        │                                │ MLflow         │
  │ (Provectus)     │                                │ Tracking Srv   │
  │ port 8081       │                                │ port 5000      │
  │ Browser monitor │                                │ (For Layer 2)  │
  └─────────────────┘                                └────────────────┘
```

---

## 3. Step-by-Step Build Log (Granular)

### Phase 1 — Tooling Installation (Windows Host)

1. Installed **uv** (Python package manager) via PowerShell:
   ```powershell
   irm https://astral.sh/uv/install.ps1 | iex
   ```
2. Installed **Python 3.11** via uv:
   ```powershell
   uv python install 3.11
   ```
3. Verified Git, VS Code, Docker Desktop already present.
4. Installed **Power BI Desktop** manually from `microsoft.com` (Microsoft Store install was unavailable on the machine).

### Phase 2 — Project Scaffolding

5. Created `velocityfraud/` repo with this folder layout:
   ```
   velocityfraud/
   ├── infra/
   │   ├── docker-compose.yml
   │   └── schemas/
   │       └── transaction-event.avsc
   ├── scripts/
   │   ├── create-topics.ps1
   │   ├── run-replayer.ps1
   │   └── run-consumer.ps1
   ├── src/
   │   └── velocityfraud/
   │       ├── __init__.py
   │       ├── schema.py
   │       ├── tokenizer.py
   │       ├── replayer.py
   │       └── consumer.py
   ├── data/
   │   ├── raw/        (CSV — NOT committed)
   │   └── processed/  (placeholder)
   ├── docs/
   ├── pyproject.toml
   ├── uv.lock
   └── .gitignore
   ```

6. Initialized `pyproject.toml` for **uv-managed package** mode with `confluent-kafka`, `fastavro`, `pandas`, `loguru`, `python-dotenv`.
7. Added at bottom of `pyproject.toml`:
   ```toml
   [tool.hatch.build.targets.wheel]
   packages = ["src/velocityfraud"]

   [tool.uv]
   package = true
   ```
   This made `velocityfraud` an installable Python package so `from velocityfraud.schema import get_schema` works.

8. Added `.gitignore` to exclude `data/raw/*`, `.env`, `.venv`, `mlruns`, `*.pkl`.

### Phase 3 — Docker Compose Stack

9. Wrote [docker-compose.yml](../infra/docker-compose.yml) with **4 services**:
   - **vf-kafka** — Apache Kafka 3.7 in KRaft mode (no ZooKeeper)
     - Dual listeners: `HOST://localhost:9092` (Python clients) + `DOCKER://kafka:29092` (other containers)
     - Persistent volume `kafka-data:/var/lib/kafka/data`
     - `KAFKA_AUTO_CREATE_TOPICS_ENABLE: "false"` for safety
   - **vf-apicurio** — Schema Registry with Confluent-compatible API at `/apis/ccompat/v7`
   - **vf-kafka-ui** — Provectus Kafka UI at http://localhost:8081 (read-only, no auth for POC)
   - **vf-mlflow** — MLflow tracking server at http://localhost:5000 (for Layer 2)

10. Ran `docker compose up -d` and confirmed all 4 containers `Up (healthy)`.

### Phase 4 — Topic Creation

11. Wrote [create-topics.ps1](../scripts/create-topics.ps1) to provision 3 topics via `docker exec`:

    | Topic | Partitions | Purpose |
    |---|---|---|
    | `transactions.raw` | 3 | Raw inbound stream from replayer |
    | `transactions.scored` | 3 | Output of Layer 3 fast-path scorer |
    | `transactions.enriched` | 1 | Output of Layer 4 slow-path with explanations |

    **Why 3 partitions for raw/scored:** parallelism — Kafka can route messages to 3 independent partitions, enabling 3 parallel consumers.
    **Why 1 for enriched:** lower volume, no parallelism needed.

### Phase 5 — Avro Schema Design

12. Designed [transaction-event.avsc](../infra/schemas/transaction-event.avsc) — **16 fields**:

    | Field | Type | Why |
    |---|---|---|
    | `event_id` | string (UUID) | Unique per event for idempotency / dedup |
    | `event_timestamp_ms` | long | Milliseconds since epoch — windowing / ordering |
    | `customer_id` | string | Partition key — same customer → same partition |
    | `card_token` | string | SHA-256-hashed card concat (NOT raw PAN!) |
    | `amount` | double | Transaction amount in source currency |
    | `currency` | string | USD for this dataset |
    | `amount_fx_normalised` | double | Amount in canonical currency (USD for POC) |
    | `merchant_id_hash` | string | Tokenized merchant identity |
    | `merchant_name` | string | Display-friendly name (e.g. `W-MERCHANT-gmail.com`) |
    | `mcc` | string | Merchant Category Code (4-digit, e.g. `5411` = Grocery) |
    | `merchant_country` | string | 2-char country code or `00` |
    | `ip_address_hash` | string | Hashed IP for privacy |
    | `device_fingerprint_hash` | string | Hashed device |
    | `geo_distance_km` | double | Distance from cardholder's home (fraud signal) |
    | `source_label` | string | Where the event came from — `replayer`, `live`, etc. |
    | `schema_version` | string | `v1` — for future schema evolution |

13. Built [schema.py](../src/velocityfraud/schema.py) — loads the `.avsc` file with `fastavro.schema.load_schema()` and caches it via `@lru_cache`.

### Phase 6 — PII Tokenizer

14. Built [tokenizer.py](../src/velocityfraud/tokenizer.py) — deterministic SHA-256 hashing with a per-tenant salt:
    ```python
    def tokenize(value: str) -> str:
        payload = f"{value}|{_salt()}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]
    ```
    **Why deterministic?** So the same card always produces the same token across runs — enables joining behavior over time without exposing raw PAN.
    **Why 16-char prefix?** SHA-256 outputs 64 hex chars — 16 is enough for low collision risk at our scale.

### Phase 7 — Data Acquisition

15. Downloaded the **IEEE-CIS Fraud Detection** dataset from Kaggle (~590K rows, 394 columns).
16. Placed `train_transaction.csv` and `train_identity.csv` in `data/raw/` (excluded from git via `.gitignore`).

### Phase 8 — Replayer (Producer)

17. Built [replayer.py](../src/velocityfraud/replayer.py) — streams CSV rows to `transactions.raw`:

    **Key logic:**
    - Chunked CSV reading (5,000 rows at a time) to control memory
    - `row_to_event()` maps IEEE-CIS fields → our Avro schema
    - **Customer ID strategy:** uses `card1` directly as the partition key (so same card → same partition)
    - **MCC mapping:** ProductCD → MCC (W→5411, C→5732, R→5812, H→7011, S→5999)
    - **Timestamp:** `REFERENCE_EPOCH_MS = 1_512_086_400_000` (2017-12-01 UTC, the Vesta anchor) + `TransactionDT` seconds
    - **Avro encoding:** `fastavro.schemaless_writer()` writes pure Avro bytes (no Confluent wire format wrapper)
    - **Idempotent producer:** `enable.idempotence=True` + `acks=all` — exactly-once semantics
    - **Graceful shutdown:** SIGINT handler flushes producer before exit
    - **Configurable via env vars:** `REPLAYER_TPS`, `REPLAYER_MAX_EVENTS`, `REPLAYER_TOPIC`

18. Wrote convenience launcher [run-replayer.ps1](../scripts/run-replayer.ps1) with sensible defaults.

19. **First successful run:** `$env:REPLAYER_MAX_EVENTS = "100"; .\scripts\run-replayer.ps1` →
    `Done. Published=100 delivered=100 failed=0 elapsed=5.3s avg=18.9 tps`

### Phase 9 — Consumer

20. Built [consumer.py](../src/velocityfraud/consumer.py) — reads `transactions.raw` and decodes Avro:

    **Key logic:**
    - Subscribes to `transactions.raw` with consumer group `velocityfraud-consumer-dev`
    - `auto.offset.reset: earliest` — sees existing messages on first run
    - `decode_event()` uses `fastavro.schemaless_reader()` against the local schema
    - Logs each event as a one-line summary: partition, offset, key, event_id, amount, MCC, merchant
    - Graceful Ctrl+C handler

21. Wrote convenience launcher [run-consumer.ps1](../scripts/run-consumer.ps1).

22. **First successful run:** Consumed 100 events, **0 decode failures**. Saw clean Python dicts for every message — proves full Avro round-trip works.

### Phase 10 — Verification (8 Checkpoints)

| # | Check | How verified | Status |
|---|---|---|---|
| 1 | Kafka broker healthy | Kafka UI → Dashboard | ✅ |
| 2 | 3 topics with correct partitions | Kafka UI → Topics | ✅ |
| 3 | 100+ messages in `transactions.raw` | Kafka UI → Messages tab | ✅ |
| 4 | Consumers page loads | Kafka UI → Consumers | ✅ |
| 5 | Apicurio UI loads | http://localhost:8080 | ✅ |
| 6 | MLflow UI loads | http://localhost:5000 | ✅ |
| 7 | All source files in git | `git status` | ✅ |
| 8 | Python loads 16-field schema | `uv run python -c "..."` | ✅ |

---

## 4. Files Inventory

| File | Purpose | Lines |
|---|---|---|
| [infra/docker-compose.yml](../infra/docker-compose.yml) | 4-service container stack | ~105 |
| [infra/schemas/transaction-event.avsc](../infra/schemas/transaction-event.avsc) | Avro schema (16 fields) | ~50 |
| [scripts/create-topics.ps1](../scripts/create-topics.ps1) | Provision 3 Kafka topics | ~50 |
| [scripts/run-replayer.ps1](../scripts/run-replayer.ps1) | Launch producer | ~20 |
| [scripts/run-consumer.ps1](../scripts/run-consumer.ps1) | Launch consumer | ~25 |
| [src/velocityfraud/__init__.py](../src/velocityfraud/__init__.py) | Package marker | 1 |
| [src/velocityfraud/schema.py](../src/velocityfraud/schema.py) | Avro schema loader | ~25 |
| [src/velocityfraud/tokenizer.py](../src/velocityfraud/tokenizer.py) | SHA-256 PII tokenizer | ~25 |
| [src/velocityfraud/replayer.py](../src/velocityfraud/replayer.py) | Producer | ~250 |
| [src/velocityfraud/consumer.py](../src/velocityfraud/consumer.py) | Consumer | ~140 |
| [pyproject.toml](../pyproject.toml) | Package config | ~30 |

---

## 5. Key Numbers to Memorize for Presentation

| Number | What It Means |
|---|---|
| **590,540** | Rows in IEEE-CIS train_transaction.csv |
| **394** | Columns in source CSV (we use ~16 derived fields) |
| **16** | Fields in our Avro TransactionEvent schema |
| **3** | Partitions for `transactions.raw` and `transactions.scored` |
| **1** | Partition for `transactions.enriched` (lower volume) |
| **1** | Replication factor (single-broker POC) |
| **9092** | Kafka host port |
| **8080** | Apicurio Schema Registry port |
| **8081** | Kafka UI port |
| **5000** | MLflow port |
| **100** | Events successfully published in test run |
| **0** | Decode failures in consumer run |
| **18.9 tps** | Average producer throughput |
| **~60%** | Bandwidth savings of Avro vs JSON |
| **₹800** | Total project budget |

---

## 6. Technical Stack to Master Before Presentation

> Study these in this order. Each has a 30-min crash-course suggestion.

### 6.1 Apache Kafka (core)

**What it is:** A distributed log-based message broker. Think "ordered append-only journal that many readers can tail."

**Must understand:**
- **Broker** — the Kafka server process (you have 1)
- **Topic** — a named stream of messages
- **Partition** — a topic is split into ordered logs; messages within a partition are strictly ordered
- **Offset** — a message's position in its partition (0, 1, 2, …)
- **Producer** — writes messages
- **Consumer** — reads messages
- **Consumer Group** — multiple consumers sharing the read load (each partition assigned to one consumer in the group)
- **Replication Factor** — how many brokers store a copy of each partition (=1 here, would be 3 in prod)
- **Idempotent Producer** — guarantees no duplicates even on retry
- **Exactly-once semantics** — combination of idempotent producer + transactional reads

**Crash course:** Confluent Developer "Apache Kafka 101" (free, 1 hour total)

### 6.2 KRaft Mode

**What it is:** Kafka's new consensus protocol that replaces ZooKeeper. Self-managed metadata using the Raft algorithm. We use this so we don't need a second container for ZooKeeper.

**One-line answer:** "Single-binary Kafka — no ZooKeeper dependency, simpler ops, future of Kafka."

### 6.3 Apache Avro

**What it is:** A binary serialization format with a separate schema definition. Used everywhere in data engineering.

**Must understand:**
- **Schema (`.avsc`)** — JSON file defining field names and types
- **Schemaless writer/reader** — writes/reads bytes assuming both sides have the schema
- **Schema evolution** — adding/removing fields without breaking old consumers
- **Why not JSON?** Smaller (~60% less), faster to parse, type-safe, has schema enforcement

**One-line answer:** "Compact binary format with strict schemas — like JSON but smaller and type-safe."

### 6.4 Schema Registry (Apicurio)

**What it is:** A central repository for Avro schemas. Producers register schemas; consumers fetch them by ID.

**Confluent Wire Format:** When using a registry, producers prepend each message with `[magic byte 0x00][4-byte schema ID]` so consumers know which schema to use.

**Why we parked it:** Apicurio's ccompat endpoint was flaky during setup. For POC, reading the schema file from disk is acceptable. Production would use the registry.

### 6.5 Docker Compose

**What it is:** Tool for defining and running multi-container Docker apps via a YAML file.

**Must understand:**
- **Services** — each container is a service
- **Volumes** — persistent data outside container lifecycle
- **Networks** — services on the same network can reach each other by service name
- **Health checks** — `depends_on` with `condition: service_healthy`

### 6.6 Python Libraries

| Library | What | Why |
|---|---|---|
| `confluent-kafka` | Kafka client for Python | Industry standard, C-backed (fast) |
| `fastavro` | Avro encoder/decoder | Fastest pure-Python Avro library |
| `pandas` | DataFrame for CSV reading | Chunked CSV streaming |
| `loguru` | Modern logger | Cleaner than stdlib `logging` |
| `python-dotenv` | Load `.env` files | Config without hardcoding |

### 6.7 PII Tokenization

**What it is:** Replacing sensitive identifiers (PAN, email, IP) with one-way hashes so analytics can join behavior over time without exposing the raw value.

**Must explain:**
- SHA-256 + salt → 64 hex chars → take first 16 as token
- Deterministic (same input → same token) for joinability
- Salt makes rainbow tables useless
- POC uses env var salt; production would use HashiCorp Vault

### 6.8 Idempotent Producers + Exactly-Once Semantics

**Idempotent producer:** Kafka assigns each producer a unique PID + monotonic sequence number; duplicates on retry are detected and discarded.

**Why it matters in fraud:** A duplicate transaction event could trigger a false fraud alert.

---

## 7. Expected Presentation Questions (Senior/Architect Tier)

> These are the questions an experienced reviewer **will** ask. Prepare a 2-sentence answer for each.

### Architecture & Choice Questions

1. **Why Kafka and not RabbitMQ / SQS / Kinesis?**
   *Answer:* Kafka is partitioned-log-based, giving us at-least-once-by-default plus replay capability (consumers can re-read history). RabbitMQ is queue-based — once consumed, message is gone. Kinesis is the same idea as Kafka but AWS-locked and pricier; Kafka stays portable across clouds.

2. **Why Avro and not JSON / Protobuf / MessagePack?**
   *Answer:* Avro pairs naturally with Kafka and Schema Registry for schema evolution. JSON is 2–3× larger; Protobuf is great but more rigid for analytics; Avro wins for "data engineering" use cases where SQL-on-stream is the next step.

3. **Why KRaft mode and not ZooKeeper?**
   *Answer:* KRaft is the official Kafka roadmap — ZooKeeper is being deprecated in Kafka 4.0. Simpler ops (single binary), faster failovers, lower resource footprint. For a POC, eliminates a whole container.

4. **Why only 1 broker? Doesn't that mean zero fault tolerance?**
   *Answer:* Correct — this is POC scale. Production would be 3 brokers with `replication.factor=3` and `min.insync.replicas=2`. The architecture is designed for that — just scale the broker count and bump the replication factor at deployment time.

5. **Why 3 partitions on raw/scored topics?**
   *Answer:* Allows up to 3 parallel consumers in a consumer group. Picked the lowest number that demonstrates parallelism. Production would scale this with expected peak TPS / target-per-consumer throughput.

### Schema Design Questions

6. **Why hash the card number — couldn't you just drop it?**
   *Answer:* We need a deterministic link between events from the same card for behavioral fraud features (velocity, repeat-merchant patterns). Hash gives us that link without exposing PAN. Compliance with PCI-DSS — raw PAN never leaves boundary.

7. **Why is `mcc` a string when it's a 4-digit number?**
   *Answer:* MCCs sometimes have leading zeros (`0742` = Veterinary). String preserves them. Also future-proof if ISO moves to alphanumeric.

8. **What's the strategy for schema evolution?**
   *Answer:* Add new fields with default values (backward-compatible). Never delete or change types of existing fields. `schema_version` field in payload lets us know what we're dealing with. Apicurio enforces compatibility rules in production.

9. **Why include `source_label`?**
   *Answer:* So we can run replayer events and real live events through the same pipeline without mixing them in dashboards. Filter for `source_label=live` in the prod dashboard.

### Operational Questions

10. **What happens if the consumer dies mid-batch?**
    *Answer:* With `enable.auto.commit=True`, offsets commit every 5 seconds. On restart, consumer rejoins the group and resumes from last committed offset. At-least-once delivery — downstream must be idempotent (we use `event_id` as the dedup key).

11. **How do you handle backpressure / a flood of events?**
    *Answer:* Kafka itself absorbs the flood — that's its job. Consumer can lag without dropping data. We can spawn more consumers in the group up to the partition count (3 here). Producer's `linger.ms=5` + `batch.size=16384` buffers small bursts.

12. **What if Apicurio is down?**
    *Answer:* Our current consumer reads schema from disk — Apicurio is currently advisory only. With Confluent wire format, a downed registry would block consumption. Mitigation: aggressive client-side caching with TTL, fallback to last-known-good schema.

13. **What's your idempotency strategy end-to-end?**
    *Answer:* (a) Idempotent Kafka producer prevents duplicate writes on retry. (b) `event_id` UUID per event lets downstream deduplicate. (c) Postgres in Layer 6 will have `event_id` as primary key — INSERT … ON CONFLICT DO NOTHING.

### PII & Security Questions

14. **How do you tokenize and where is the salt?**
    *Answer:* SHA-256(value + salt), take first 16 hex chars. POC reads salt from `VF_TOKEN_SALT` env var. Production would fetch from HashiCorp Vault on container start, never logged, rotated quarterly.

15. **Could someone reverse the tokens?**
    *Answer:* No — SHA-256 is a one-way function. Salt prevents pre-computed rainbow tables. To reverse, an attacker would need to know the salt AND brute-force the input space. With 16-digit card numbers (10^16 possibilities), infeasible.

16. **What's logged? Any PII?**
    *Answer:* Logs include `customer_id` (already a numeric card1 derivative, not the PAN) and `merchant_name` (email domain visible — minor). We do NOT log raw card numbers, raw emails, or IPs. Production: switch to fully-tokenized log fields.

### Performance Questions

17. **What's the end-to-end latency?**
    *Answer:* Producer → broker → consumer: <10ms on localhost. Production target is <100ms end-to-end including Layer 3 scoring. Kafka itself contributes <1ms.

18. **How do you scale TPS?**
    *Answer:* Three levers: (1) Add brokers — scales total throughput linearly. (2) Add partitions — scales single-topic throughput. (3) Add consumers up to partition count — scales read parallelism.

19. **Why batch.size=16384 and linger.ms=5?**
    *Answer:* Balance between latency and throughput. 5ms linger lets producer batch multiple messages without adding human-noticeable lag. 16KB batch fits common MTUs. These are Confluent's recommended starting points.

### Project / POC Questions

20. **Why didn't you use a managed Kafka (Confluent Cloud / MSK)?**
    *Answer:* Budget constraint — POC is ₹800. Self-hosted on Docker is ₹0. Architecture is portable: tomorrow we can point producers at Confluent Cloud by changing one env var.

21. **What's NOT in this POC that you'd add for production?**
    *Answer:* (a) 3-broker cluster + Schema Registry HA. (b) TLS + SASL/SCRAM auth. (c) Vault-backed salts. (d) Topic ACLs per service. (e) Schema compatibility enforcement. (f) Producer/consumer Prometheus metrics. (g) Disk-based dead-letter queue for poison-pill messages.

22. **How did you verify the system works?**
    *Answer:* 8-checkpoint manual verification — broker health, topic counts, message count, UI loads for all 4 services, git tracking, schema loads in Python. Plus the full producer → consumer round-trip with **0 decode failures on 100 events.**

23. **What's the next step?**
    *Answer:* Layer 2 — train Random Forest + XGBoost in Databricks Community Edition on the IEEE-CIS labeled dataset. Log model artifacts to the MLflow instance already running at localhost:5000.

---

## 8. Quick Demo Commands (For Live Walkthrough)

Run these in front of an audience to show the layer in action:

```powershell
# 1. Show the stack is healthy
docker ps --format "table {{.Names}}\t{{.Status}}"

# 2. Show topics exist
docker exec vf-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list

# 3. Publish 10 transactions live
$env:REPLAYER_MAX_EVENTS = "10"; $env:REPLAYER_TPS = "5"; .\scripts\run-replayer.ps1

# 4. Show messages in Kafka UI
# Open http://localhost:8081 → Topics → transactions.raw → Messages

# 5. Read them back, decoded
$env:CONSUMER_MAX_MESSAGES = "10"; .\scripts\run-consumer.ps1
```

---

## 9. What's Next — Layer 2 Preview

**Goal:** Train fraud detection models on the same IEEE-CIS dataset and register them in MLflow.

**Tech stack to learn for Layer 2:**
- Databricks Community Edition (free notebook environment)
- Random Forest + XGBoost (scikit-learn / xgboost libraries)
- Feature engineering for fraud (velocity features, time-since-last-txn, amount-z-score)
- MLflow tracking (experiments, runs, model registry)
- Model serialization (`.pkl` / ONNX)

**Output of Layer 2:**
- Trained `fraud_classifier_v1.pkl` (~50–200 MB)
- MLflow run with metrics: precision, recall, F1, AUC, confusion matrix
- Feature importance plot
- Holdout test set evaluation

---

## 10. References & Further Reading

- **Confluent Developer (free courses):** https://developer.confluent.io/
- **Kafka: The Definitive Guide** (O'Reilly) — chapters 1–6 for fundamentals
- **Apache Avro spec:** https://avro.apache.org/docs/current/specification/
- **IEEE-CIS Fraud Detection competition:** https://www.kaggle.com/competitions/ieee-fraud-detection
- **Confluent wire format:** https://docs.confluent.io/platform/current/schema-registry/fundamentals/serdes-develop/index.html#wire-format

---

**Document maintained by:** Project owner
**Last updated:** 2026-06-29
**Next layer doc:** `LAYER_2_MODEL_TRAINING.md` (to be created after Layer 2 completion)

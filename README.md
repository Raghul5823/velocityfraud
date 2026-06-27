# VelocityFraud — Fraud Detection Data Pipeline

> IMPACT pSiddhi 3.0 · Topic S2-D-06 · Semester 2 · Data Track
> Throughput-first streaming fraud detection on Apache Kafka with two-tier scoring (Groq fast-path + Spark slow-path), Hugging Face text anomaly, MLflow-tracked Random Forest + XGBoost, and Power BI Desktop dashboards.

## Architecture in one line

`Kafka (Docker) → fast path (Groq + shadow XGBoost) + slow path (Spark + RF/XGB + SHAP + Gemini + DistilBERT) → Power BI`

See `../PROPOSAL_2_VelocityFraud.md` (parent directory) for the full design.

## Project layout

| Path | Purpose |
|---|---|
| `src/` | Python source — producer, consumer, scoring service, replayer |
| `tests/` | Pytest unit + integration + E2E tests |
| `docs/` | Design docs (Kafka topology, schema decisions, runbook) |
| `data/raw/` | IEEE-CIS dataset (DVC-tracked, never committed to Git) |
| `scripts/` | One-off shell + Python utilities (create topics, etc.) |
| `infra/` | Docker compose files for Kafka + MLflow + Schema Registry |

## Tech stack

- Python 3.11 (uv-managed) + Java JDK 21 (Kafka Streams)
- Apache Kafka 3.7 in Docker (KRaft mode, no ZooKeeper)
- Apicurio Schema Registry + Apache Avro
- MLflow (self-hosted)
- Databricks Free Edition (Spark Structured Streaming + RF/XGB training)
- Groq Llama 3.3 70B (fast-path classifier)
- Google Gemini 2.5 Flash (slow-path narrative generation)
- Hugging Face DistilBERT (text anomaly detection)
- Power BI Desktop with DirectQuery
- Pytest, Locust, k6, Great Expectations (QA)

## Setup

```powershell
# Prerequisites: Docker Desktop running, Python 3.11 + uv installed.
cd velocityfraud
uv sync                 # installs all Python dependencies
docker compose -f infra\docker-compose.yml up -d
```

## Status

Phase 0 (setup) complete. Currently building Layer 1 (streaming foundation).

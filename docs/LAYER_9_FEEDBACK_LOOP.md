# Layer 9 — Analyst Feedback Loop (COMPLETE)

> **Status:** ✅ Complete
> **Project:** VelocityFraud — Real-Time Fraud Detection Data Pipeline
> **Program:** IMPACT pSiddhi 3.0 — Topic S2-D-06 (Semester 2, Data Track)
> **Proposal reference:** §5, Layer 3 — *"Analyst actions (accept / escalate / false-positive) write back to a `feedback` Kafka topic feeding the retraining loop."* Timeline §7, Wk 12 — *"Feedback writeback topic. Deliverable: 4 PBI views; feedback loop closed."*

> **Framing note:** Chronologically this closes the loop the proposal committed to at Wk 12. It sits downstream of Layer 3 (scoring) and Layer 8 (blocklist/appeals) — it does not change how a transaction is scored; it records what a human later decided the *correct* answer was, so the system can measure itself and (eventually) retrain on it.

---

## 1. Why This Layer Exists

A fraud model's score is a guess. The only way to know if the guess was right is a human ground-truth verdict. Without a feedback loop:

- There is no way to measure **model-vs-analyst agreement** in production.
- There is no labelled data to **retrain** on.
- The Operational Health dashboard has no drift signal beyond fast-path-vs-shadow agreement.

**Layer 9 closes this** with a simple, explicit workflow: an analyst reviews a scored transaction, records `FRAUD` or `LEGIT` as the real answer, and the system:

1. Looks up the original model decision + score for that event.
2. Computes whether the model **agreed** with the human (`REVIEW`/`BLOCK` = model called it fraud; `ALLOW` = model called it legit).
3. Persists the verdict in Postgres (`feedback_events`).
4. Publishes the same verdict as an Avro event to Kafka (`transactions.feedback`) for any downstream retraining/label-store consumer.

## 2. Architecture

```
   Analyst reviews a scored transaction
                │
                ▼
   feedback.submit_feedback(event_id, verdict, analyst, notes)
                │
     ┌──────────┴───────────┐
     │  1. SELECT decision,  │
     │     fraud_score FROM  │
     │     scored_events     │  (Postgres — Layer 6)
     └──────────┬───────────┘
                │
     model_agrees(decision, verdict)
                │
     ┌──────────┴────────────────────────┐
     │ 2. INSERT feedback_events row       │  Postgres
     │ 3. PRODUCE TransactionFeedbackEvent │  Kafka topic
     │    to transactions.feedback (Avro,  │  transactions.feedback
     │    idempotent producer, acks=all)   │
     └─────────────────────────────────────┘
                │
                ▼
     feedback_agreement VIEW (Postgres)
     total_feedback | agreements | agreement_rate
     → feeds the Operational Health dashboard's
       "model-vs-analyst agreement rate" panel
```

## 3. What Was Built

| Component | File | Purpose |
|---|---|---|
| Feedback module + CLI | `src/velocityfraud/feedback.py` | `submit_feedback`, `list_feedback`, `feedback_stats`; CLI via `uv run python -m velocityfraud.feedback {submit,list,stats}` |
| Table + view | `infra/migrations/004_feedback.sql` | `feedback_events` table, indexes on `event_id`/`submitted_at`/`analyst_verdict`, and the `feedback_agreement` summary view |
| Avro schema | `infra/schemas/transaction-feedback-event.avsc` | `TransactionFeedbackEvent` — enums for `model_decision` (`ALLOW`/`REVIEW`/`BLOCK`) and `analyst_verdict` (`FRAUD`/`LEGIT`) |
| Schema loader | `src/velocityfraud/schema.py::get_feedback_schema()` | Registers/loads the Avro schema used to serialise feedback events before producing |
| Tests | `tests/test_feedback.py`, `tests/test_feedback_integration.py` | Unit coverage of `model_agrees()` logic + integration test against live Postgres/Kafka |

## 4. Model-Agreement Logic

The core correctness rule (`feedback.py::model_agrees`) is intentionally simple and testable:

```python
def _model_flagged(decision: str) -> bool:
    return decision in ("REVIEW", "BLOCK")   # ALLOW is the only non-flag

def model_agrees(decision: str, verdict: str) -> bool:
    return _model_flagged(decision) == (verdict == "FRAUD")
```

A model that said `ALLOW` and a human who says `LEGIT` → agreement. A model that said `REVIEW`/`BLOCK` and a human who says `FRAUD` → agreement. Any other combination is a disagreement — which is exactly the signal the Operational Health dashboard's agreement-rate panel needs.

## 5. Database Schema

```sql
CREATE TABLE feedback_events (
    feedback_id       BIGSERIAL PRIMARY KEY,
    event_id          VARCHAR(40)  NOT NULL,       -- FK (logical) -> scored_events
    analyst_name      VARCHAR(255),
    analyst_role      VARCHAR(20)  NOT NULL,        -- 'analyst' | 'system'
    model_decision    VARCHAR(10)  NOT NULL,        -- ALLOW | REVIEW | BLOCK
    model_fraud_score NUMERIC(10, 8),
    analyst_verdict   VARCHAR(10)  NOT NULL,        -- 'FRAUD' | 'LEGIT'
    model_agreed      BOOLEAN      NOT NULL,
    notes             TEXT,
    submitted_at      TIMESTAMPTZ  DEFAULT NOW()
);

CREATE VIEW feedback_agreement AS
SELECT COUNT(*) AS total_feedback,
       SUM(CASE WHEN model_agreed THEN 1 ELSE 0 END) AS agreements,
       ROUND(AVG(CASE WHEN model_agreed THEN 1 ELSE 0 END), 4) AS agreement_rate,
       SUM(CASE WHEN analyst_verdict = 'FRAUD' THEN 1 ELSE 0 END) AS analyst_fraud,
       SUM(CASE WHEN analyst_verdict = 'LEGIT' THEN 1 ELSE 0 END) AS analyst_legit
FROM feedback_events;
```

## 6. How to Run

```powershell
# Record a verdict on a previously scored event
uv run python -m velocityfraud.feedback submit `
    --event-id <uuid> --verdict FRAUD --analyst jdoe --notes "confirmed chargeback"

# List recent feedback
uv run python -m velocityfraud.feedback list

# Model-vs-analyst agreement summary (feeds the Operational Health view)
uv run python -m velocityfraud.feedback stats
```

Or via the PowerShell wrapper: `scripts/submit-feedback.ps1`.

## 7. Where This Feeds Forward

- **Power BI — Operational Health Dashboard:** the `feedback_agreement` view's `agreement_rate` is the panel that quantifies model drift from a human baseline (complementary to the fast-path-vs-shadow-model agreement metric already covered by Layer 5b).
- **Retraining (future scope):** `transactions.feedback` is a durable, idempotently-produced Kafka topic — a labelled-data stream any retraining pipeline can consume without touching the scoring path. Building the retraining job itself is out of this POC's ₹800/12-week scope (see Proposal §13.5, "what this proposal is NOT trying to be").

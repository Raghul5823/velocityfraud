r"""Layer 3c — Synchronous fast-path scoring API (FastAPI).

WHY THIS EXISTS
    The proposal committed to a FastAPI scoring service (Week 7: "Groq fast-path
    integrated via FastAPI scoring service"; Week 14: "migrate ... FastAPI scoring
    service to the ARM VM"). This module delivers it as a request/response HTTP
    endpoint that runs the SAME fast-path scoring path as the Kafka scorer:

        POST /score   -> blocklist pre-filter -> featurize -> XGBoost -> decision
        GET  /health  -> liveness + whether the champion model is loaded

    It is also the endpoint the k6 benchmark hits to measure end-to-end p95/p99
    latency for the "throughput certificate" (Week 15). Because XGBoost runs
    in-process (no network hop), this comfortably holds the sub-100 ms fast-path.

Run:
    uv run uvicorn velocityfraud.api:app --host 0.0.0.0 --port 8000
    (or:  .\scripts\run-api.ps1)

Then:
    curl -X POST localhost:8000/score -H "content-type: application/json" -d '{...}'
    GET  localhost:8000/health
    GET  localhost:8000/docs        (interactive Swagger UI)
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger
from pydantic import BaseModel, Field

from velocityfraud import blocklist
from velocityfraud.live_features import featurize_event
from velocityfraud.predict import (
    get_champion_filename,
    get_champion_model,
    predict_proba,
)

# Thresholds shared with the Kafka scorer so HTTP and stream paths agree.
import os

REVIEW_THRESH = float(os.getenv("SCORER_REVIEW_THRESH", "0.50"))
BLOCK_THRESH = float(os.getenv("SCORER_BLOCK_THRESH", "0.85"))
MODEL_VERSION = "v1"

# When set, /score skips the Layer-8 Redis blocklist pre-filter and measures the
# pure in-process ML fast-path (featurize + XGBoost). Used for latency
# benchmarking: in this dev box Redis is reached through Docker Desktop's Windows
# port-proxy, which inflates every round-trip; in production Redis is co-located
# and sub-ms, so the blocklist adds negligible latency. Default OFF (faithful).
SKIP_BLOCKLIST = os.getenv("API_SKIP_BLOCKLIST", "0") == "1"


def decide(score: float) -> str:
    """Map a fraud probability to a Decision symbol (same policy as scorer.py)."""
    if score >= BLOCK_THRESH:
        return "BLOCK"
    if score >= REVIEW_THRESH:
        return "REVIEW"
    return "ALLOW"


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class TransactionIn(BaseModel):
    """Mirror of the Avro TransactionEvent (defaults let a benchmark send little)."""
    event_id: str = "api-req"
    event_timestamp_ms: int = Field(default_factory=lambda: int(time.time() * 1000))
    customer_id: str = "0"
    card_token: str = ""
    amount: float = 0.0
    currency: str = "USD"
    amount_fx_normalised: float = 0.0
    merchant_id_hash: str = ""
    merchant_name: str = ""
    mcc: str = ""
    merchant_country: str = "00"
    ip_address_hash: str = ""
    device_fingerprint_hash: str = ""
    geo_distance_km: float = 0.0
    source_label: str = "api"
    schema_version: str = "v1"


class ScoreOut(BaseModel):
    event_id: str
    fraud_score: float
    decision: str
    model_name: str
    model_version: str
    scoring_latency_ms: float
    feature_completeness: float
    blocklist_hit: bool
    blocklist_tier: str
    blocklist_reason: str


# ---------------------------------------------------------------------------
# App + model warm-up
# ---------------------------------------------------------------------------
_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm the model once at startup so the first request isn't a cold-start.
    logger.info("Loading champion model for scoring API...")
    model = get_champion_model()
    # Pin prediction to a SINGLE thread. The model was trained with n_jobs=-1
    # (all cores), which is baked into the pickle and overrides OMP_NUM_THREADS.
    # Under multiple uvicorn workers that causes catastrophic thread
    # oversubscription (workers x cores). One thread/worker gives clean
    # process-level parallelism instead.
    for setter in (
        lambda: model.set_params(n_jobs=1),
        lambda: model.get_booster().set_param({"nthread": 1}),
    ):
        try:
            setter()
        except Exception:
            pass
    _state["model"] = model
    _state["champion_name"] = get_champion_filename()
    logger.info("Scoring API ready. Champion: {} (predict nthread=1)", _state["champion_name"])
    yield
    _state.clear()


app = FastAPI(
    title="VelocityFraud Fast-Path Scoring API",
    version="1.0",
    description="Synchronous XGBoost fraud scoring (Layer 3c). Sub-100ms fast path.",
    lifespan=lifespan,
)


@app.get("/ping")
def ping() -> dict:
    """Trivial no-op endpoint (no Redis, no model) — framework/network baseline."""
    return {"pong": True}


@app.get("/health")
def health() -> dict:
    """Liveness + readiness. Reports whether the champion model is loaded."""
    return {
        "status": "ok",
        "model_loaded": "model" in _state,
        "champion": _state.get("champion_name"),
        "redis_alive": blocklist.is_redis_alive(),
        "review_thresh": REVIEW_THRESH,
        "block_thresh": BLOCK_THRESH,
    }


@app.post("/score", response_model=ScoreOut)
def score(txn: TransactionIn) -> ScoreOut:
    """Score one transaction on the fast path: blocklist -> XGBoost -> decision."""
    t_start = time.perf_counter()
    event = txn.model_dump()

    # Layer 8 pre-filter (fail-open on Redis error, identical to the Kafka scorer).
    # Skippable for pure-ML-path latency benchmarking (see SKIP_BLOCKLIST).
    if SKIP_BLOCKLIST:
        bl = blocklist.BlocklistResult(hit=False, tier=blocklist.Tier.NONE)
    else:
        bl = blocklist.check(
            card_token=event.get("card_token") or None,
            merchant_id_hash=event.get("merchant_id_hash") or None,
            ip_hash=event.get("ip_address_hash") or None,
            device_hash=event.get("device_fingerprint_hash") or None,
        )

    if bl.hit and bl.tier == blocklist.Tier.BLOCK:
        score_val, completeness, decision = 1.0, 0.0, "BLOCK"
    elif bl.hit and bl.tier == blocklist.Tier.HOT:
        score_val, completeness, decision = 0.5, 0.0, "REVIEW"
    else:
        X, completeness = featurize_event(event)
        score_val = float(predict_proba(_state["model"], X)[0])
        decision = decide(score_val)

    latency_ms = (time.perf_counter() - t_start) * 1000.0
    return ScoreOut(
        event_id=event["event_id"],
        fraud_score=score_val,
        decision=decision,
        model_name=_state["champion_name"],
        model_version=MODEL_VERSION,
        scoring_latency_ms=round(latency_ms, 3),
        feature_completeness=completeness,
        blocklist_hit=bl.hit,
        blocklist_tier=bl.tier.value,
        blocklist_reason=bl.reason,
    )

"""Chaos probe — scores one sample event and reports the degradation state.

Used by scripts/chaos-test.ps1 to prove graceful degradation: when Redis (the
Layer-8 blocklist) is down, blocklist.check fails OPEN (returns NONE) and the ML
fast path keeps producing a decision — no legitimate customer is blocked just
because an ancillary store is unavailable.

Run:
    uv run python -m velocityfraud.chaos
Exit code is 0 as long as a decision was produced (even with Redis down).
"""
from __future__ import annotations

from velocityfraud import blocklist
from velocityfraud.live_features import featurize_event
from velocityfraud.predict import get_champion_model, predict_proba

REVIEW_THRESH = 0.50
BLOCK_THRESH = 0.85

SAMPLE = {
    "event_id": "chaos-probe", "event_timestamp_ms": 1_782_731_301_417,
    "customer_id": "13926", "card_token": "10c1bf7c3c76e313", "amount": 245.40,
    "currency": "USD", "amount_fx_normalised": 245.40,
    "merchant_id_hash": "5f59d374246893e0", "merchant_name": "W-MERCHANT-gmail.com",
    "mcc": "5411", "merchant_country": "US", "ip_address_hash": "98e58ca964c583e2",
    "device_fingerprint_hash": "a245d9cb16edd5da", "geo_distance_km": 12.5,
    "source_label": "chaos", "schema_version": "v1",
}


def probe() -> int:
    redis_alive = blocklist.is_redis_alive()

    # Layer 8 — fail-open on Redis error (returns NONE, never raises)
    bl = blocklist.check(
        card_token=SAMPLE["card_token"],
        merchant_id_hash=SAMPLE["merchant_id_hash"],
        ip_hash=SAMPLE["ip_address_hash"],
        device_hash=SAMPLE["device_fingerprint_hash"],
    )

    # ML fast path still runs regardless of Redis
    X, completeness = featurize_event(SAMPLE)
    score = float(predict_proba(get_champion_model(), X)[0])
    decision = ("BLOCK" if score >= BLOCK_THRESH
                else "REVIEW" if score >= REVIEW_THRESH else "ALLOW")

    print(f"redis_alive={redis_alive} blocklist_hit={bl.hit} "
          f"blocklist_tier={bl.tier.value} score={score:.4f} decision={decision}")
    # A decision was produced -> the pipeline degraded gracefully.
    return 0 if decision in ("ALLOW", "REVIEW", "BLOCK") else 1


if __name__ == "__main__":
    import sys
    sys.exit(probe())

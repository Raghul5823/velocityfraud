"""Locust load test for the VelocityFraud fast-path scoring API (Layer 3c).

Complements the k6 latency certificate (perf/k6-score.js): where k6 fixes an
arrival rate and measures latency, Locust simulates concurrent *users* hammering
POST /score and reports sustained throughput + response-time percentiles.

Run headless (API must be up on 0.0.0.0; start it with .\scripts\run-api.ps1):
    uv run locust -f perf/locustfile.py --headless -u 50 -r 10 -t 30s \
        --host http://127.0.0.1:8010

  -u  concurrent users, -r ramp/sec, -t duration. Add --csv=perf/locust to save reports.

Or open the web UI:
    uv run locust -f perf/locustfile.py --host http://127.0.0.1:8010
"""
from __future__ import annotations

import random

from locust import HttpUser, between, task

TXNS = [
    {"amount": 125.99, "merchant_name": "W-MERCHANT-gmail.com",     "mcc": "5411", "merchant_country": "US", "card_token": "u_a1"},
    {"amount": 42.50,  "merchant_name": "R-MERCHANT-yahoo.com",     "mcc": "5812", "merchant_country": "US", "card_token": "u_b2"},
    {"amount": 999.00, "merchant_name": "S-MERCHANT-anonymous.com", "mcc": "5999", "merchant_country": "00", "card_token": "u_c3", "geo_distance_km": 8500},
    {"amount": 15.75,  "merchant_name": "C-MERCHANT-hotmail.com",   "mcc": "5732", "merchant_country": "GB", "card_token": "u_d4"},
    {"amount": 320.00, "merchant_name": "H-MERCHANT-outlook.com",   "mcc": "7011", "merchant_country": "FR", "card_token": "u_e5"},
]


class ScoringUser(HttpUser):
    """A simulated payment gateway calling the fraud fast path per transaction."""
    wait_time = between(0.01, 0.05)

    @task
    def score(self):
        base = random.choice(TXNS)
        payload = {
            "event_id": f"locust-{random.randint(0, 1_000_000)}",
            "currency": "USD",
            "amount_fx_normalised": base["amount"],
            **base,
        }
        with self.client.post("/score", json=payload, catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"status {resp.status_code}")
            else:
                try:
                    if resp.json().get("decision") in ("ALLOW", "REVIEW", "BLOCK"):
                        resp.success()
                    else:
                        resp.failure("no decision in response")
                except Exception as e:
                    resp.failure(f"bad json: {e}")

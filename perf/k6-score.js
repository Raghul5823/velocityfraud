// k6 latency benchmark for the VelocityFraud fast-path scoring API (Layer 3c).
//
// Proves the proposal's Week-15 "throughput certificate": sustained 10,000 tx/min
// against the /score endpoint with a fast-path p95 well under the 200 ms target
// (XGBoost runs in-process, so we expect p95 < 100 ms).
//
// Run via Docker (k6 not installed locally):
//   docker run --rm -v "${PWD}/perf:/perf" grafana/k6 run /perf/k6-score.js
// Target host + port are overridable:
//   ... -e BASE_URL=http://host.docker.internal:8010 ...
//
// The API must be running and bound to 0.0.0.0 so the container can reach it
// via host.docker.internal.

import http from "k6/http";
import { check } from "k6";
import { Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://host.docker.internal:8010";
const RATE_PER_SEC = parseInt(__ENV.RATE_PER_SEC || "167"); // ~10,020 tx/min target
const DURATION = __ENV.DURATION || "60s";

// Track the server-reported scoring time separately from HTTP round-trip.
const scoringLatency = new Trend("scoring_latency_ms", true);

export const options = {
  scenarios: {
    fast_path: {
      // Ramp up over 10s to avoid a cold-start thundering herd, then hold the
      // target rate for the certificate window.
      executor: "ramping-arrival-rate",
      startRate: 20,
      timeUnit: "1s",
      preAllocatedVUs: 60,
      maxVUs: 200,
      stages: [
        { target: RATE_PER_SEC, duration: "10s" },
        { target: RATE_PER_SEC, duration: DURATION },
      ],
    },
  },
  thresholds: {
    // The fast-path SLOs. p95 is the headline number for UC-05 / CC-17.
    http_req_duration: ["p(95)<100", "p(99)<200"],
    http_req_failed: ["rate<0.01"],
  },
  // Make p99 available in the end-of-test summary (k6 omits it by default).
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
};

// A small pool of varied transactions so we're not scoring one cached row.
const TXNS = [
  { amount: 125.99, merchant_name: "W-MERCHANT-gmail.com",     mcc: "5411", merchant_country: "US", card_token: "card_a1" },
  { amount: 42.5,   merchant_name: "R-MERCHANT-yahoo.com",     mcc: "5812", merchant_country: "US", card_token: "card_b2" },
  { amount: 999.0,  merchant_name: "S-MERCHANT-anonymous.com", mcc: "5999", merchant_country: "00", card_token: "card_c3", geo_distance_km: 8500 },
  { amount: 15.75,  merchant_name: "C-MERCHANT-hotmail.com",   mcc: "5732", merchant_country: "GB", card_token: "card_d4" },
  { amount: 320.0,  merchant_name: "H-MERCHANT-outlook.com",   mcc: "7011", merchant_country: "FR", card_token: "card_e5" },
];

export default function () {
  const base = TXNS[Math.floor(Math.random() * TXNS.length)];
  const payload = JSON.stringify({
    event_id: `k6-${__VU}-${__ITER}`,
    amount: base.amount,
    amount_fx_normalised: base.amount,
    currency: "USD",
    merchant_name: base.merchant_name,
    mcc: base.mcc,
    merchant_country: base.merchant_country,
    card_token: base.card_token,
    geo_distance_km: base.geo_distance_km || 0,
  });

  const res = http.post(`${BASE_URL}/score`, payload, {
    headers: { "Content-Type": "application/json" },
    timeout: "10s", // cap a stalled request so one outlier can't read as 60s
  });

  check(res, {
    "status is 200": (r) => r.status === 200,
    "has a decision": (r) => {
      try { return ["ALLOW", "REVIEW", "BLOCK"].includes(r.json("decision")); }
      catch (e) { return false; }
    },
  });

  try { scoringLatency.add(res.json("scoring_latency_ms")); } catch (e) {}
}

// Write a JSON summary artifact alongside the console output for the evidence pack.
export function handleSummary(data) {
  const out = __ENV.SUMMARY_OUT || "perf/k6-summary.json";
  const result = { stdout: textSummary(data) };
  result[out] = JSON.stringify(data, null, 2);
  return result;
}

// Minimal text summary (avoids importing the remote k6-utils module, which the
// strict-CSP / offline container can't fetch).
function textSummary(data) {
  const m = data.metrics;
  const d = m.http_req_duration ? m.http_req_duration.values : {};
  const reqs = m.http_reqs ? m.http_reqs.values.count : 0;
  const failed = m.http_req_failed ? (m.http_req_failed.values.rate * 100).toFixed(2) : "n/a";
  const rps = m.http_reqs ? m.http_reqs.values.rate.toFixed(1) : "n/a";
  const line = "-".repeat(58);
  return [
    "",
    line,
    " VelocityFraud fast-path /score  -  k6 latency certificate",
    line,
    `  total requests      : ${reqs}`,
    `  throughput          : ${rps} req/s  (~${Math.round(rps * 60)}/min)`,
    `  failed              : ${failed}%`,
    `  latency avg         : ${fmt(d.avg)} ms`,
    `  latency p50 (med)   : ${fmt(d.med)} ms`,
    `  latency p90         : ${fmt(d["p(90)"])} ms`,
    `  latency p95         : ${fmt(d["p(95)"])} ms   <- fast-path SLO`,
    `  latency p99         : ${fmt(d["p(99)"])} ms`,
    `  latency max         : ${fmt(d.max)} ms`,
    line,
    "",
  ].join("\n");
}

function fmt(v) {
  return v === undefined ? "n/a" : v.toFixed(2);
}

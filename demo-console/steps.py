"""Demo step catalogue for the VelocityFraud Live Demo Console.

Every step the console can run is defined here and nowhere else. Remote steps
are bash scripts executed on the Hetzner server inside ~/velocityfraud; local
steps are handled by server.py on this laptop. There is deliberately no way to
run a command that is not in this file.

Each step:
    id, section, num, title    identity and display order
    kind                       read | action | quota | control | local
    timeout                    seconds before the remote run is cut off
    purpose                    what the step demonstrates (shown to the audience)
    built                      what was built / configured for it (shown to the audience)
    say                        talking point for the presenter
    show                       what to put on screen next
    links                      quick-link keys shown with the step
    caution                    presenter-only warning
    confirm                    always ask before running (text of the question)
    confirm_rerun              ask before running a second time
    script / local             remote bash body, or the name of a local action

Verified against the repository on 5 Nov 2026: CLI flags (appeal, feedback,
drift, ops_metrics), table/view columns (migrations 001-010), API request
fields (api.TransactionIn), failover lock format (failover_scorer.INSTANCE_ID),
and the reference payload decisions at the 0.10 / 0.18 demo thresholds.
"""
from __future__ import annotations

SECTIONS = [
    {"id": "preflight", "title": "Pre-flight", "subtitle": "Presenter only - readiness checks before the audience joins", "presenter_only": True},
    {"id": "act1", "title": "Act 1 – The live platform", "subtitle": "Real-time event streaming on one cloud server, governed by versioned schemas"},
    {"id": "act2", "title": "Act 2 – Decisions in milliseconds, explained", "subtitle": "XGBoost scoring, velocity rule, SHAP evidence and language-model checks"},
    {"id": "act3", "title": "Act 3 – Independent AI oversight and resilience", "subtitle": "Parallel LLM second opinion, zero-downtime failover and drift monitoring"},
    {"id": "act4", "title": "Act 4 – Humans in control", "subtitle": "Customer appeals, analyst decisions and the learning loop"},
    {"id": "act5", "title": "Act 5 – Operate, govern, scale", "subtitle": "Operational health, model governance, cloud infrastructure and quality"},
    {"id": "recovery", "title": "Recovery", "subtitle": "Presenter only - one-click fixes if a component stops", "presenter_only": True},
]

LINKS = {
    "kafka_ui": {"label": "Kafka UI", "url": "http://localhost:18081", "needs_tunnel": True},
    "mlflow": {"label": "MLflow", "url": "http://localhost:15000", "needs_tunnel": True},
    "api_docs": {"label": "API docs (Swagger)", "url": "http://{ip}:8000/docs"},
    "hetzner": {"label": "Hetzner Console", "url": "https://console.hetzner.com/projects/15873826/servers"},
}

# Shared helpers prepended to every remote script.
PRELUDE = r'''set -o pipefail
export PATH="$HOME/.local/bin:$PATH"
export PYTHONUNBUFFERED=1
D="$HOME/velocityfraud"
PY="$D/.venv/bin/python"
T="SCORER_REVIEW_THRESH=0.10 SCORER_BLOCK_THRESH=0.18"
cd "$D" || { echo "[FAIL] Project folder ~/velocityfraud not found on this server"; exit 2; }
sql()    { docker exec vf-postgres psql -U vf -d velocityfraud -P pager=off -v ON_ERROR_STOP=1 -c "$1"; }
sqlv()   { docker exec vf-postgres psql -U vf -d velocityfraud -At -v ON_ERROR_STOP=1 -c "$1"; }
pane()   { tmux display-message -p -t "vf:$1" '#{pane_current_command}' 2>/dev/null; }
# A tab counts as running when any process below its shell is a real program (not bash/sh).
# (pane_current_command is not usable: tmux runs each program under "bash -c", so it reads "bash".)
running(){
  local p
  p=$(tmux display-message -p -t "vf:$1" '#{pane_pid}' 2>/dev/null)
  [ -n "$p" ] || return 1
  ps -e -o pid=,ppid=,comm= | awk -v root="$p" '
    { par[$1] = $2; cmd[$1] = $3 }
    END {
      for (x in par) {
        if (x == root || cmd[x] == "bash" || cmd[x] == "sh") continue
        y = x; n = 0
        while ((y in par) && y != root && n++ < 50) y = par[y]
        if (y == root) exit 0
      }
      exit 1
    }'
}
leader() { docker exec vf-redis redis-cli GET vf:scorer:leader 2>/dev/null | tr -d '\r'; }
hdr()    { printf '\n== %s ==\n' "$1"; }
clean()  { { grep --line-buffered -v -E 'FutureWarning|google\.generativeai|deprecated-generative-ai|All support for the|updates or bug fixes|See README for more|^\s*import google|warnings\.warn|unauthenticated requests to the HF Hub|Loading weights' || true; } | sed -u -E 's/^[0-9-]+ ([0-9:]{8})\.[0-9]+ \| ([A-Z]+) +\| [^ ]+ - /\1  \2  /; s/\*\*//g'; }
vf()     { local m="$1"; shift; uv run --quiet python -m "velocityfraud.$m" "$@" 2>&1 | clean; }
need_stack() {
  local miss="" c
  for c in vf-kafka vf-postgres vf-redis; do
    [ "$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null)" = "running" ] || miss="$miss $c"
  done
  tmux has-session -t vf 2>/dev/null || miss="$miss pipeline-programs"
  if [ -n "$miss" ]; then
    echo "[FAIL] The pipeline is not running on the server (not started:$miss)."
    echo "       Start it with Recovery > R9 Full pipeline restart, wait 3 minutes, then run P1."
    exit 1
  fi
}
'''

# Steps that need the running pipeline: they stop early with a clear message if it is down.
NEEDS_STACK_SECTIONS = {"act1", "act2", "act3", "act4", "act5"}
NEEDS_STACK_IDS = {"groq_start"}

# Reference payload helpers (fixed event time = Fri 6 Nov 2026 11:15 IST, so
# results are reproducible at any hour; decisions verified against the model).
API_HELPERS = r'''TS=1793943900000
mk()   { printf '{"event_id":"%s","customer_id":"%s","card_token":"%s","amount":%s,"merchant_name":"%s","mcc":"%s","merchant_country":"%s","geo_distance_km":%s,"event_timestamp_ms":%s}' "$1" "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$TS"; }
post() { curl -s -m 5 -X POST localhost:8000/score -H 'Content-Type: application/json' -d "$1"; }
'''

# Schema registry helper. Apicurio runs the in-memory edition, so its rule and
# subjects vanish when its container restarts; "setup" re-applies them from the
# same Avro files in Git (idempotent), "check" reports, "show" demonstrates.
REGISTRY_HELPERS = r'''registry() {
  "$PY" - "$1" <<'PYEOF'
import json, sys, urllib.request, urllib.error
B = "http://localhost:8080/apis/ccompat/v7"
SUBJECTS = {
    "transactions.raw-value": "transaction-event.avsc",
    "transactions.scored-value": "transaction-scored-event.avsc",
    "transactions.scored.groq-value": "transaction-scored-event.avsc",
    "transactions.enriched-value": "transaction-enriched-event.avsc",
    "transactions.feedback-value": "transaction-feedback-event.avsc",
}
def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(B + path, data=data, method=method,
                                 headers={"Content-Type": "application/vnd.schemaregistry.v1+json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return 0, None
def state():
    cfg = call("GET", "/config")[1] or {}
    subs = call("GET", "/subjects")[1] or []
    return cfg.get("compatibilityLevel") or cfg.get("compatibility") or "unknown", subs
mode = sys.argv[1] if len(sys.argv) > 1 else "show"
if mode == "setup":
    ok = call("PUT", "/config", {"compatibility": "BACKWARD"})[0] == 200
    for subj, f in SUBJECTS.items():
        ok = call("POST", "/subjects/%s/versions" % subj, {"schema": open("infra/schemas/" + f).read()})[0] == 200 and ok
    level, subs = state()
    if ok and level == "BACKWARD" and len(subs) >= len(SUBJECTS):
        print("  [ OK ] Schema registry ready: BACKWARD compatibility, %d Avro subjects registered" % len(subs))
    else:
        print("[FAIL] Schema registry setup incomplete (rule %s, %d subjects)" % (level, len(subs)))
        sys.exit(1)
elif mode == "check":
    level, subs = state()
    print(level, len(subs))
else:
    level, subs = state()
    print("  Global compatibility rule : " + level)
    print("  Registered Avro subjects  : " + (", ".join(subs) if subs else "none - run Recovery > R10"))
    if not subs:
        sys.exit(0)
    base = json.load(open("infra/schemas/transaction-event.avsc"))
    bad = json.loads(json.dumps(base)); bad["fields"].append({"name": "risk_band", "type": "string"})
    good = json.loads(json.dumps(base)); good["fields"].append({"name": "risk_band", "type": "string", "default": "unknown"})
    print("  Live compatibility check against transactions.raw-value (nothing is registered):")
    for label, sch, expect in (("Breaking change: new field without a default", bad, False),
                               ("Safe change: new field with a default", good, True)):
        st, res = call("POST", "/compatibility/subjects/transactions.raw-value/versions/latest", {"schema": json.dumps(sch)})
        got = (res or {}).get("is_compatible")
        verdict = "ACCEPTED" if got else ("REJECTED" if st == 200 else "no answer (HTTP %s)" % st)
        tag = "[ OK ]" if (st == 200 and got == expect) else "[WARN]"
        print("  %s %-46s -> %s" % (tag, label, verdict))
PYEOF
}
registry_wait() {
  local i
  for i in $(seq 1 30); do curl -s -m 2 localhost:8080/apis/ccompat/v7/subjects >/dev/null && return 0; sleep 2; done
  return 1
}
'''

# Groq lifecycle helpers. Each start uses a fresh consumer group reading only new
# events; each stop removes that group again, so no retired group shows false lag.
GROQ_HELPERS = r'''GRP_FILE="$HOME/.vf_groq_group"
START_FILE="$HOME/.vf_groq_start"
AUTO_STOP_S=180
groq_start() {
  local g="vf-groq-$(date +%m%d%H%M%S)"
  echo "$g" > "$GRP_FILE"
  date +%s > "$START_FILE"
  tmux send-keys -t vf:groq "clear" Enter; tmux clear-history -t vf:groq
  tmux send-keys -t vf:groq "$T GROQ_MAX_RPM=$1 GROQ_SCORER_FROM=latest GROQ_SCORER_GROUP=$g uv run python -m velocityfraud.groq_scorer" Enter
}
groq_wait_first() {
  local i
  for i in $(seq 1 "$1"); do tmux capture-pane -p -t vf:groq -S -300 | grep -q "score=" && return 0; sleep 1; done
  return 1
}
# Ctrl-C only takes effect after the scorer's current rate-limit pause, which lasts up
# to 60 s. Everything it produced is already delivered by then, so after a short grace
# period the pause is cut short with SIGTERM to the program (never the tab's shell).
groq_kill() {
  local p
  p=$(tmux display-message -p -t vf:groq '#{pane_pid}' 2>/dev/null)
  [ -n "$p" ] || return 0
  ps -e -o pid=,ppid=,comm= | awk -v root="$p" '
    { par[$1] = $2; cmd[$1] = $3 }
    END {
      for (x in par) {
        if (x == root || cmd[x] == "bash" || cmd[x] == "sh") continue
        y = x; n = 0
        while ((y in par) && y != root && n++ < 50) y = par[y]
        if (y == root) print x
      }
    }' | xargs -r kill -TERM 2>/dev/null
}
groq_stop() {
  local i
  running groq || return 0
  tmux send-keys -t vf:groq C-c
  for i in $(seq 1 8); do running groq || return 0; sleep 1; done
  groq_kill
  for i in $(seq 1 12); do running groq || return 0; sleep 1; done
  ! running groq
}
# Safety net: stops Groq by itself after AUTO_STOP_S seconds unless this start was
# already stopped (3.3 / R2 remove the group file) or replaced by a newer start.
groq_watchdog() {
  local g
  g=$(cat "$GRP_FILE" 2>/dev/null)
  setsid nohup bash -c "$(declare -f running groq_kill groq_stop)
    sleep $AUTO_STOP_S
    [ \"\$(cat '$GRP_FILE' 2>/dev/null)\" = '$g' ] && groq_stop" >/dev/null 2>&1 < /dev/null &
}
# Live second opinions since the last start, counted in the database (the tab's
# scrollback is too short to count a long run).
groq_calls() {
  local s
  s=$(cat "$START_FILE" 2>/dev/null)
  [ -n "$s" ] || { echo 0; return; }
  sqlv "select count(*) from scored_events_groq where inserted_at >= to_timestamp($s)"
}
# A program stopped with SIGTERM stays a group member until its session times out
# (up to 45 s), so the group and then its lag rows are removed in the background.
# kafka-consumer-groups exits 0 even when a delete is refused, so its message is checked.
groq_cleanup() {
  local g
  g=$(cat "$GRP_FILE" 2>/dev/null)
  rm -f "$START_FILE"
  [ -n "$g" ] || return 0
  rm -f "$GRP_FILE"
  setsid nohup bash -c '
    for i in $(seq 1 30); do
      docker exec vf-kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 --delete --group "$1" 2>&1 \
        | grep -qE "was successful|GroupIdNotFound" && break
      sleep 3
    done
    sleep 5
    docker exec vf-postgres psql -U vf -d velocityfraud -At -c "$2" >/dev/null' \
    _ "$g" "delete from ops_metrics where scope like '$g/%'" >/dev/null 2>&1 < /dev/null &
  echo "  Retired consumer group $g is being removed, so the lag figures stay accurate."
}
'''

# Load-server steps (host "loadgen") run on a separate small server, as in the
# week-15 certificate: the load generator never shares CPU with the system under
# test. TARGET (the demo server's IP) is set by the console before this prelude.
LOADGEN_PRELUDE = r'''set -o pipefail
export DEBIAN_FRONTEND=noninteractive
W="$HOME/vf-load"
LOCUST="$HOME/loadgen-env/bin/locust"
mkdir -p "$W" || { echo "[FAIL] Cannot create $W on the load server"; exit 2; }
hdr() { printf '\n== %s ==\n' "$1"; }
check_target() {
  local r
  [ -n "$TARGET" ] || { echo "[FAIL] The demo server IP is not set in Settings"; exit 1; }
  r=$(curl -s -m 5 -o "$W/health.json" -w '%{http_code} %{time_total}' "http://$TARGET:8000/health")
  if [ "${r%% *}" = "200" ] && python3 -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1])).get("model_loaded") else 1)' "$W/health.json" 2>/dev/null; then
    echo "  [ OK ] Scoring API on the demo server answers - model loaded, network round trip $(awk -v t="${r##* }" 'BEGIN { printf "%.1f", t * 1000 }') ms"
  else
    echo "[FAIL] The scoring API on the demo server is not answering (HTTP ${r%% *}) - run P1 first"; exit 1
  fi
}
# Prints the elapsed time every 10 s while a background load test runs; returns its exit code.
watch_pid() {
  local p="$1" s0
  s0=$(date +%s)
  while kill -0 "$p" 2>/dev/null; do
    sleep 10
    kill -0 "$p" 2>/dev/null && echo "  ... $(( $(date +%s) - s0 )) s - $2"
  done
  wait "$p"
}
'''

# Live-demo copy of velocityfraud/perf/k6-score.js (the week-15 certificate script):
# same endpoint, thresholds and summary. For a 60-second live run it holds the full
# rate from the first second, and every request carries a new card and amount, so
# the velocity rule and 1-minute score cache (both added after week 15) never
# short-cut the model.
K6_LIVE_JS = r'''// Live-demo copy of perf/k6-score.js (week-15 certificate): same endpoint,
// thresholds and summary. Differences for a 60-second live run:
//   1. constant arrival rate from the first second, so throughput is the held rate;
//   2. every request carries a new card token and amount, so the velocity rule and
//      the 1-minute score cache never short-cut the model - every request runs
//      blocklist -> velocity rule -> 43 features -> XGBoost.
import http from "k6/http";
import { check } from "k6";
import { Trend } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL;
const RATE_PER_SEC = parseInt(__ENV.RATE_PER_SEC || "167"); // ~10,020 tx/min
const DURATION = __ENV.DURATION || "60s";
const RUN_ID = __ENV.RUN_ID || "run";

// Track the server-reported scoring time separately from HTTP round-trip.
const scoringLatency = new Trend("scoring_latency_ms", true);

export const options = {
  scenarios: {
    fast_path: {
      executor: "constant-arrival-rate",
      rate: RATE_PER_SEC,
      timeUnit: "1s",
      duration: DURATION,
      preAllocatedVUs: 60,
      maxVUs: 200,
    },
  },
  thresholds: {
    http_req_duration: ["p(95)<100", "p(99)<200"],
    http_req_failed: ["rate<0.01"],
  },
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
};

const TXNS = [
  { amount: 125.99, merchant_name: "W-MERCHANT-gmail.com",     mcc: "5411", merchant_country: "US" },
  { amount: 42.5,   merchant_name: "R-MERCHANT-yahoo.com",     mcc: "5812", merchant_country: "US" },
  { amount: 999.0,  merchant_name: "S-MERCHANT-anonymous.com", mcc: "5999", merchant_country: "00", geo_distance_km: 8500 },
  { amount: 15.75,  merchant_name: "C-MERCHANT-hotmail.com",   mcc: "5732", merchant_country: "GB" },
  { amount: 320.0,  merchant_name: "H-MERCHANT-outlook.com",   mcc: "7011", merchant_country: "FR" },
];

export default function () {
  const base = TXNS[Math.floor(Math.random() * TXNS.length)];
  const amount = Math.round(base.amount * (0.5 + Math.random()) * 100) / 100;
  const id = `k6-${RUN_ID}-${__VU}-${__ITER}`;
  const payload = JSON.stringify({
    event_id: id,
    amount: amount,
    amount_fx_normalised: amount,
    currency: "USD",
    merchant_name: base.merchant_name,
    mcc: base.mcc,
    merchant_country: base.merchant_country,
    card_token: id,
    geo_distance_km: base.geo_distance_km || 0,
  });

  const res = http.post(`${BASE_URL}/score`, payload, {
    headers: { "Content-Type": "application/json" },
    timeout: "10s",
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

export function handleSummary(data) {
  const out = __ENV.SUMMARY_OUT || "k6-live-summary.json";
  const result = { stdout: textSummary(data) };
  result[out] = JSON.stringify(data, null, 2);
  return result;
}

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
}'''

# Live-demo copy of velocityfraud/perf/locustfile.py with the same new-card-per-request rule.
LOCUST_LIVE_PY = r'''"""Live-demo copy of perf/locustfile.py: simulated payment gateways on POST /score.

Every request carries a new card token and amount, so the velocity rule and the
1-minute score cache never short-cut the model.
"""
import random
import uuid

from locust import HttpUser, between, task

TXNS = [
    {"amount": 125.99, "merchant_name": "W-MERCHANT-gmail.com",     "mcc": "5411", "merchant_country": "US"},
    {"amount": 42.50,  "merchant_name": "R-MERCHANT-yahoo.com",     "mcc": "5812", "merchant_country": "US"},
    {"amount": 999.00, "merchant_name": "S-MERCHANT-anonymous.com", "mcc": "5999", "merchant_country": "00", "geo_distance_km": 8500},
    {"amount": 15.75,  "merchant_name": "C-MERCHANT-hotmail.com",   "mcc": "5732", "merchant_country": "GB"},
    {"amount": 320.00, "merchant_name": "H-MERCHANT-outlook.com",   "mcc": "7011", "merchant_country": "FR"},
]


class ScoringUser(HttpUser):
    """A simulated payment gateway calling the fraud fast path per transaction."""
    wait_time = between(0.01, 0.05)

    @task
    def score(self):
        base = random.choice(TXNS)
        amount = round(base["amount"] * random.uniform(0.5, 1.5), 2)
        token = "lc-" + uuid.uuid4().hex[:16]
        payload = {**base, "event_id": token, "card_token": token, "currency": "USD",
                   "amount": amount, "amount_fx_normalised": amount}
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
                    resp.failure(f"bad json: {e}")'''


def _restart(window: str, launch: str, label: str) -> str:
    """Script that cleanly stops one pipeline program (if running) and relaunches it."""
    return r'''W="%s"; L="%s"
if running "$W"; then
  echo "  $W is running - stopping it cleanly first"
  tmux send-keys -t "vf:$W" C-c
  for i in $(seq 1 25); do running "$W" || break; sleep 1; done
  if running "$W"; then echo "[FAIL] $W did not stop within 25 s - use 'Full pipeline restart'"; exit 1; fi
fi
if [ -z "$(pane "$W")" ]; then
  tmux has-session -t vf 2>/dev/null || { echo "[FAIL] tmux session 'vf' is missing - use 'Full pipeline restart'"; exit 1; }
  tmux new-window -d -t vf -n "$W" -c "$D"; sleep 1
fi
tmux send-keys -t "vf:$W" "clear" Enter; tmux clear-history -t "vf:$W"
tmux send-keys -t "vf:$W" "$L" Enter
echo "  Started %s"
sleep 12
hdr "Latest output from $W"
tmux capture-pane -p -t "vf:$W" | grep -v '^\s*$' | tail -6 | clean
running "$W" && echo "  [ OK ] $W is running" || { echo "[FAIL] $W exited - see the output above"; exit 1; }
''' % (window, launch, label)


STEPS = [
    # ------------------------------------------------------------------ PRE-FLIGHT
    {
        "id": "preflight", "section": "preflight", "num": "P1", "title": "Readiness check – every component verified",
        "purpose": "One automated health check of the whole platform, so the demo starts only when everything is green.",
        "built": [
            "Checks the server, all 6 containers, all 9 programs, the scoring API, live data flow, Kafka lag, schema registry, MLflow and server resources",
            "Read-only: it changes nothing on the server",
            "Ends with READY FOR DEMO or NOT READY, with the exact line that needs attention",
        ],
        "kind": "read", "timeout": 120,
        "say": "Run at 10:15 and again at 10:45. Every line must read OK before the audience joins.",
        "caution": "Any FAIL line: fix it with the Recovery section (or Full pipeline restart) before 10:50.",
        "script": REGISTRY_HELPERS + r'''fail=0; warn=0
ok()  { printf '  [ OK ] %s\n' "$1"; }
bad() { printf '  [FAIL] %s\n' "$1"; fail=$((fail+1)); }
wrn() { printf '  [WARN] %s\n' "$1"; warn=$((warn+1)); }

hdr "Server"
ok "Connected to $(hostname) - $(nproc) vCPU - $(date -u '+%H:%M:%S') UTC - $(uptime -p)"
for t in docker tmux curl; do command -v "$t" >/dev/null 2>&1 && ok "$t installed" || bad "$t is not installed"; done
[ -x "$PY" ] && ok "Project Python environment ready" || bad "Project virtual environment missing (~/velocityfraud/.venv)"

hdr "Platform containers"
for c in vf-kafka vf-postgres vf-redis vf-apicurio vf-mlflow vf-kafka-ui; do
  s=$(docker inspect -f '{{.State.Status}}' "$c" 2>/dev/null)
  [ "$s" = "running" ] && ok "$c running" || bad "$c is ${s:-missing}"
done

hdr "Pipeline programs (tmux session 'vf')"
if tmux has-session -t vf 2>/dev/null; then
  for w in api primary standby slowpath text sink ops replayer; do
    if [ -z "$(pane "$w")" ]; then bad "$w: window missing"
    elif running "$w"; then ok "$w: running"
    else bad "$w: stopped"; fi
  done
  if [ -z "$(pane groq)" ]; then wrn "groq: window missing"
  elif running groq; then ok "groq: running (second opinion active)"
  else ok "groq: idle (it runs live only in Act 3, steps 3.1-3.3)"; fi
else
  bad "tmux session 'vf' not found - use Recovery > Full pipeline restart"
fi

hdr "Fast-path leadership"
LD=$(leader)
[ -n "$LD" ] && ok "ACTIVE scorer: ${LD%%-*}" || bad "No scorer holds the leader lock"

hdr "Scoring API"
H=$(curl -s -m 5 localhost:8000/health)
if [ -z "$H" ]; then bad "API is not answering on port 8000"
else
  read -r ML RA RT BT CH < <(printf '%s' "$H" | "$PY" -c 'import sys,json; d=json.load(sys.stdin); print(d.get("model_loaded"), d.get("redis_alive"), d.get("review_thresh"), d.get("block_thresh"), d.get("champion"))')
  [ "$ML" = "True" ] && ok "Champion model loaded ($CH)" || bad "Model not loaded"
  [ "$RA" = "True" ] && ok "Redis reachable from the API" || bad "API cannot reach Redis"
  if [ "$RT" = "0.1" ] && [ "$BT" = "0.18" ]; then ok "Demo thresholds active: REVIEW >= 0.10, BLOCK >= 0.18"
  else bad "Thresholds are REVIEW $RT / BLOCK $BT (expected 0.1 / 0.18)"; fi
fi

hdr "Live data flow"
read -r N A R B < <(sqlv "select count(*), count(*) filter (where decision='ALLOW'), count(*) filter (where decision='REVIEW'), count(*) filter (where decision='BLOCK') from scored_events where inserted_at > now() - interval '3 minutes'" | tr '|' ' ')
if [ "${N:-0}" -gt 0 ]; then ok "$N events scored in the last 3 min (ALLOW $A / REVIEW $R / BLOCK $B)"; else bad "No events scored in the last 3 minutes"; fi
read -r E TX < <(sqlv "select count(*), count(text_anomaly_label) from enriched_events where inserted_at > now() - interval '10 minutes'" | tr '|' ' ')
if [ "${E:-0}" -gt 0 ]; then ok "$E flagged events enriched in the last 10 min ($TX with a text score)"; else wrn "No enriched events in the last 10 minutes"; fi

hdr "Kafka consumer lag"
AGE=$(sqlv "select coalesce(extract(epoch from now() - max(captured_at))::int, 99999) from ops_metrics_latest where metric_name='kafka_consumer_lag'")
if [ "${AGE:-99999}" -gt 120 ]; then wrn "Ops metrics are ${AGE}s old - check the 'ops' program"; else ok "Ops metrics fresh (${AGE}s old)"; fi
HIGH=$(sqlv "select scope || ' = ' || metric_value::bigint from ops_metrics_latest where metric_name='kafka_consumer_lag' and metric_value > 1000 order by metric_value desc limit 5")
if [ -z "$HIGH" ]; then ok "Every consumer group is within 1,000 messages of the head"
else while IFS= read -r l; do wrn "High lag: $l"; done <<< "$HIGH"; fi

hdr "Schema registry (Apicurio)"
read -r RL RN <<< "$(registry check)"
if [ "$RL" = "BACKWARD" ] && [ "${RN:-0}" -ge 5 ]; then ok "BACKWARD compatibility, $RN Avro subjects registered"
else wrn "Registry shows rule '$RL' and ${RN:-0} subjects - run Recovery > R10 (schema registry setup)"; fi

hdr "MLflow tracking server"
MR=$("$PY" - <<'PYEOF'
import json, urllib.request
def post(p, b):
    r = urllib.request.Request("http://localhost:5000/api/2.0/mlflow/" + p, data=json.dumps(b).encode(),
                               headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=5))
try:
    exps = post("experiments/search", {"max_results": 100}).get("experiments", [])
    ids = [e["experiment_id"] for e in exps]
    runs = post("runs/search", {"experiment_ids": ids, "max_results": 200}).get("runs", []) if ids else []
    print(len(exps), len(runs))
except Exception:
    print("ERR ERR")
PYEOF
)
read -r NE NR <<< "$MR"
if [ "$NE" = "ERR" ]; then wrn "MLflow API not reachable on port 5000"
elif [ "${NR:-0}" -gt 0 ]; then ok "MLflow: $NE experiment(s), $NR run(s) - available for step 5.2"
else wrn "MLflow is up but holds no runs on this server - step 5.2 uses the model_metrics table and Power BI"; fi

hdr "Server resources"
MA=$(free -m | awk '/^Mem:/ {print $7}')
DU=$(df -P / | awk 'NR==2 {gsub("%","",$5); print $5}')
[ "${MA:-0}" -gt 800 ] && ok "Memory available: ${MA} MB" || wrn "Low memory: ${MA} MB available"
[ "${DU:-100}" -lt 85 ] && ok "Disk used: ${DU}%" || wrn "Disk is ${DU}% full"

hdr "Result"
if [ "$fail" -eq 0 ]; then echo "  READY FOR DEMO - $warn warning(s)"; exit 0
else echo "  NOT READY - $fail problem(s), $warn warning(s)"; exit 1; fi
''',
    },
    {
        "id": "tunnel", "section": "preflight", "num": "P2", "title": "Secure tunnel to the cloud dashboards",
        "purpose": "Opens an encrypted SSH tunnel, so the internal dashboards and the database are reachable from this laptop without being exposed to the internet.",
        "built": [
            "Cloud firewall allows only SSH (22) and the scoring API (8000)",
            "Kafka UI -> localhost:18081, PostgreSQL -> 15432, MLflow -> 15000",
            "Authenticated with the SSH key set in Settings",
        ],
        "kind": "local", "local": "tunnel",
        "say": "Opens an encrypted SSH tunnel in its own window: Kafka UI on localhost:18081, PostgreSQL on localhost:15432 (Power BI) and MLflow on localhost:15000. Minimise that window - do not close it.",
        "caution": "If the header shows the tunnel as partial, close the old tunnel window and run this step again.",
    },
    {
        "id": "powerbi", "section": "preflight", "num": "P3", "title": "Power BI executive dashboard",
        "purpose": "Opens the Power BI report that reads the live cloud database through the tunnel - the business view of the same pipeline.",
        "built": [
            "Fraud_Detection_Dashboard_Cloud.pbix on the cloud PostgreSQL",
            "Pages used in the demo: Real-time Alert Feed, Operational Health, Model Performance",
            "Refresh with Optimize > Refresh visuals",
        ],
        "kind": "local", "local": "powerbi",
        "say": "Opens Fraud_Detection_Dashboard_Cloud.pbix, which reads the cloud PostgreSQL through the tunnel.",
        "caution": "Refresh with Optimize > Refresh visuals. Never use Home > Refresh - the archived Databricks table fails on the free plan and shows an error dialog.",
    },
    {
        "id": "groq_start", "section": "preflight", "num": "P4", "title": "Groq API connection check (stops itself)",
        "purpose": "Proves the Groq API key and network path work, using about four calls, then stops automatically.",
        "built": [
            "Starts the Groq scorer at 4 calls/minute on new events only",
            "Stops after the first decision and removes its temporary consumer group",
            "Uses about 1% of the free daily token budget",
        ],
        "kind": "quota", "timeout": 120,
        "confirm": "Check the Groq connection? Groq starts, scores the first event (about 1-2 calls, roughly 1% of the daily budget) and stops automatically.",
        "say": "Proves the Groq API key and connection work, using the smallest possible number of calls. Groq stops by itself as soon as the first event is scored.",
        "caution": "Run it once. Groq runs live only in Act 3 (3.1 start, 3.3 stop) for about 1-1.5 minutes, with a 3-minute automatic stop as a safety net.",
        "script": GROQ_HELPERS + r'''if running groq; then echo "[WARN] Groq is already running - stop it with 3.3 (or R2) before this check."; exit 1; fi
[ -n "$(pane groq)" ] || { echo "[FAIL] tmux window 'groq' is missing - use Recovery > Full pipeline restart"; exit 1; }
hdr "Starting Groq and waiting for the first scored event"
groq_start 4
if groq_wait_first 45; then FIRST=1; else FIRST=0; fi
groq_stop || { echo "[FAIL] Groq did not stop within 20 s - use R2"; exit 1; }
hdr "Groq output"
tmux capture-pane -p -t vf:groq -S -300 | grep -E "ONLINE|heartbeat|score=|429|rror|Rate" | head -8 | clean
sleep 3
N=$(groq_calls)
groq_cleanup
if [ "$FIRST" = "1" ]; then echo "  [ OK ] Groq connection is live - $N event(s) scored, then stopped automatically."
else echo "[FAIL] Groq did not score an event within 45 s - see the output above"; exit 1; fi
''',
    },
    {
        "id": "loadgen_setup", "section": "preflight", "num": "P5", "title": "Load server – one-time setup (k6 and Locust)",
        "purpose": "Installs k6 and Locust on the separate load server, as in the week-15 certificate, and checks it can reach the scoring API.",
        "built": [
            "Runs on the load server set in Settings, never on the demo server",
            "k6 from Grafana's package repository; Locust in its own Python environment",
            "Safe to run again: anything already installed is skipped",
        ],
        "kind": "control", "timeout": 600, "host": "loadgen",
        "confirm": "Install k6 and Locust on the load server? This takes 2-4 minutes and changes nothing on the demo server.",
        "caution": "Run once after creating the load server. Needs the load server IP in Settings and the demo pipeline up (P1).",
        "script": r'''hdr "Load server"
printf '  %s  |  %s vCPU  |  %s\n' "$(hostname)" "$(nproc)" "$(. /etc/os-release && echo "$PRETTY_NAME")"
APT="apt-get -o DPkg::Lock::Timeout=300 -y -qq"
if command -v k6 >/dev/null; then
  echo "  [ OK ] k6 already installed"
else
  hdr "Installing k6 from Grafana's package repository"
  $APT update >/dev/null && $APT install gpg curl ca-certificates >/dev/null || { echo "[FAIL] apt-get could not install the prerequisites"; exit 1; }
  curl -fsSL https://dl.k6.io/key.gpg | gpg --dearmor --yes -o /usr/share/keyrings/k6-archive-keyring.gpg || { echo "[FAIL] Could not download the k6 signing key"; exit 1; }
  echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" > /etc/apt/sources.list.d/k6.list
  $APT update >/dev/null && $APT install k6 >/dev/null || { echo "[FAIL] k6 installation failed"; exit 1; }
fi
echo "  $(k6 version | head -1)"
if [ -x "$LOCUST" ]; then
  echo "  [ OK ] Locust already installed"
else
  hdr "Installing Locust in its own Python environment"
  $APT install python3-venv >/dev/null || { echo "[FAIL] Could not install python3-venv"; exit 1; }
  python3 -m venv "$HOME/loadgen-env" && "$HOME/loadgen-env/bin/pip" install -q --disable-pip-version-check locust || { echo "[FAIL] Locust installation failed"; exit 1; }
fi
echo "  Locust $("$LOCUST" --version 2>&1 | awk '{ print $2; exit }')"
hdr "Connection to the demo server"
check_target
echo "  [ OK ] Load server ready. Before the demo run P6; in the demo run 5.4 and 5.5."
''',
    },
    {
        "id": "loadgen_check", "section": "preflight", "num": "P6", "title": "Load server readiness check",
        "purpose": "Confirms the load server has k6 and Locust and can reach the scoring API, before the audience joins.",
        "built": [
            "Runs on the load server; sends one health request to the demo server",
            "Shows the network round trip between the two servers",
        ],
        "kind": "read", "timeout": 60, "host": "loadgen",
        "caution": "Run at 10:45 after P1. The round trip should be a few milliseconds (both servers in the same location).",
        "script": r'''hdr "Load server"
printf '  %s  |  %s vCPU  |  load average %s\n' "$(hostname)" "$(nproc)" "$(cut -d' ' -f1-3 /proc/loadavg)"
command -v k6 >/dev/null || { echo "[FAIL] k6 is not installed - run P5"; exit 1; }
echo "  [ OK ] $(k6 version | head -1)"
[ -x "$LOCUST" ] || { echo "[FAIL] Locust is not installed - run P5"; exit 1; }
echo "  [ OK ] Locust $("$LOCUST" --version 2>&1 | awk '{ print $2; exit }')"
hdr "Connection to the demo server"
check_target
''',
    },

    # ------------------------------------------------------------------ ACT 1
    {
        "id": "tests_start", "section": "act1", "num": "1.0", "title": "Full test suite – 122 tests start in the background",
        "purpose": "The project's complete automated test suite starts now on this laptop and runs while the demo continues; the result is shown in Act 5 (step 5.8).",
        "built": [
            "122 pytest tests: 58 unit tests and 64 integration tests",
            "Integration tests run against a local copy of Redis, PostgreSQL and Kafka in Docker - never the live demo server",
            "No Gemini or Groq calls: narration is forced to the template",
            "About 5 minutes; the console stays free for the next steps",
        ],
        "kind": "local", "local": "tests_start", "timeout": 30,
        "say": "Before we start: the full test suite - 122 automated tests - is now running on this laptop against a local copy of Redis, PostgreSQL and Kafka. We will look at the result in Act 5.",
        "caution": "Needs Docker Desktop running with the velocityfraud-dev containers (vf-redis, vf-postgres, vf-kafka). Click it once at the start of the demo; 5.8 shows the result.",
    },
    {
        "id": "overview", "section": "act1", "num": "1.1", "title": "Platform overview – one cloud server, end to end",
        "purpose": "The complete platform running live: 6 infrastructure containers and 9 pipeline services on a single cloud server.",
        "built": [
            "Hetzner cloud server (Helsinki): 4 vCPU, 8 GB RAM, Ubuntu",
            "Docker: Kafka 3.7 (KRaft, no ZooKeeper), PostgreSQL 16, Redis 7, Apicurio schema registry, MLflow 2.18, Kafka UI",
            "9 Python services: scoring API, 2 XGBoost scorers, Groq, slow path, DistilBERT, database sink, ops monitor, replayer",
            "Live feed: the IEEE-CIS dataset (590K real card transactions) replayed at 2 transactions per second",
        ],
        "kind": "read", "timeout": 60,
        "say": "VelocityFraud runs end to end on one Hetzner cloud server: six platform containers and nine pipeline programs, all live right now.",
        "show": "Hetzner Console - server vf-demo is running.",
        "links": ["hetzner"],
        "script": r'''hdr "Cloud server (Hetzner)"
printf '  %s  |  %s vCPU  |  %s RAM  |  %s\n' "$(hostname)" "$(nproc)" "$(free -h | awk '/^Mem:/ {print $2}')" "$(uptime -p)"
hdr "Platform containers (Docker)"
docker ps --format '  {{printf "%-13s" .Names}}  {{.Status}}' | sort
hdr "Pipeline programs (tmux session 'vf')"
LD=$(leader); ACT=${LD%%-*}
while IFS='|' read -r w d; do
  if [ -z "$(pane "$w")" ]; then s="MISSING"; elif running "$w"; then s="running"; elif [ "$w" = "groq" ]; then s="idle"; else s="STOPPED"; fi
  [ "$w" = "$ACT" ] && d="$d   <- ACTIVE"
  printf '  %-9s %-8s %s\n' "$w" "$s" "$d"
done <<'EOF'
api|FastAPI scoring service - POST /score on port 8000
primary|Fast-path scorer A - XGBoost (hot-standby pair)
standby|Fast-path scorer B - XGBoost (hot-standby pair)
groq|Groq LLM second opinion (parallel, rate-limited)
slowpath|Slow path - SHAP attribution + narrative
text|DistilBERT text-anomaly scorer
sink|Kafka to PostgreSQL sink (idempotent upserts)
ops|Ops metrics collector (lag, Groq headroom)
replayer|IEEE-CIS transaction replayer (2 tx/s)
EOF
''',
    },
    {
        "id": "kafka", "section": "act1", "num": "1.2", "title": "Live event stream and schema governance",
        "purpose": "Proves data is flowing right now, and that every event follows a governed, versioned contract.",
        "built": [
            "Kafka topics: transactions.raw -> scored -> enriched, plus scored.groq and feedback",
            "Avro schemas version-controlled in Git and registered in Apicurio with BACKWARD compatibility",
            "Idempotent producers (acks=all): a retry never creates a duplicate event",
            "Topic auto-creation disabled, so a typo cannot create a rogue topic",
        ],
        "kind": "read", "timeout": 90,
        "say": "Every transaction enters Kafka as an Avro event. The counters are sampled 10 seconds apart to prove the stream is moving right now. The Avro schemas are version-controlled in Git and registered in Apicurio, which enforces BACKWARD compatibility - watch it reject a breaking change and accept a safe one.",
        "show": "Kafka UI - Topics - transactions.raw - Messages.",
        "links": ["kafka_ui"],
        "caution": "Kafka UI opens only while the secure tunnel (P2) is up. Do not show its Dashboard page: Production/Consumption read '0 Bytes' because broker JMX metrics are not enabled. Show Topics > transactions.raw > Messages, and Schema Registry. If asked: the services serialize with the same schema files from Git; having producers fetch schemas from the registry by ID is the production step (documented in LAYER_1).",
        "script": REGISTRY_HELPERS + r'''KB=/opt/kafka/bin
offsets() {
  if docker exec vf-kafka test -x "$KB/kafka-get-offsets.sh"; then
    docker exec vf-kafka "$KB/kafka-get-offsets.sh" --bootstrap-server localhost:9092 2>/dev/null
  else
    docker exec vf-kafka "$KB/kafka-run-class.sh" org.apache.kafka.tools.GetOffsetShell --bootstrap-server localhost:9092 2>/dev/null
  fi | awk -F: '$1 ~ /^transactions\./ {s[$1]+=$3} END {for (t in s) print t, s[t]}' | sort
}
hdr "Kafka topics - total messages and growth over 10 seconds"
A=$(offsets); sleep 10; B=$(offsets)
if [ -z "$A" ] || [ -z "$B" ]; then echo "[FAIL] Could not read topic offsets from Kafka"; exit 1; fi
join <(printf '%s\n' "$A") <(printf '%s\n' "$B") | awk '{printf "  %-26s %12d messages   +%d in the last 10 s\n", $1, $3, $3-$2}'
hdr "Schema governance (Apicurio registry)"
registry show
''',
    },
    {
        "id": "decisions", "section": "act1", "num": "1.3", "title": "Live decision mix – ALLOW, REVIEW, BLOCK",
        "purpose": "Every transaction receives one of three decisions in milliseconds; this shows how the live traffic splits between them.",
        "built": [
            "ALLOW passes, REVIEW goes to an analyst, BLOCK stops the payment",
            "Demo thresholds REVIEW >= 0.10 and BLOCK >= 0.18 (production 0.50 / 0.85) - disclosed",
            "Every decision is written to PostgreSQL by an idempotent sink (upsert on event_id)",
        ],
        "kind": "read", "timeout": 60,
        "say": "Each event receives one of three decisions - ALLOW, REVIEW or BLOCK - in a few milliseconds. REVIEW goes to a human; BLOCK stops the payment.",
        "show": "Power BI - Real-time Alert Feed (Optimize > Refresh visuals).",
        "caution": "Say it openly: the live stream uses demo thresholds 0.10 / 0.18 because only about 33% of the model's 43 features can be computed from a single live event; production thresholds are 0.50 / 0.85. The mix shifts over time because the replayer walks through 590K historical transactions and each keeps its original timestamp (hour of day is a model feature) - so the share of BLOCK changes with the slice being replayed.",
        "script": r'''hdr "Decision mix - last 5 minutes of the live stream"
sql "select decision, count(*) as events, round(100.0 * count(*) / sum(count(*)) over (), 1) as share_pct, round(avg(fraud_score)::numeric, 3) as avg_score, round(avg(scoring_latency_ms)::numeric, 1) as avg_latency_ms, count(*) filter (where velocity_hit) as velocity_rule from scored_events where inserted_at > now() - interval '5 minutes' group by decision order by events desc"
N=$(sqlv "select count(*) from scored_events where inserted_at > now() - interval '60 seconds'")
echo "  Throughput: $N events scored in the last 60 seconds"
echo "  Thresholds: REVIEW >= 0.10, BLOCK >= 0.18 (demo setting; production 0.50 / 0.85)"
''',
    },

    # ------------------------------------------------------------------ ACT 2
    {
        "id": "reference", "section": "act2", "num": "2.1", "title": "Real-time scoring API – three reference transactions",
        "purpose": "Three transactions through the public REST API - normal, suspicious and high-risk - with the response time of each.",
        "built": [
            "FastAPI service with 2 workers: POST /score on port 8000",
            "Each request: blocklist -> velocity rule -> 43 features -> XGBoost champion model",
            "Load-tested with k6 at 10,000 transactions/minute for 30 minutes: p95 56.69 ms",
            "Identical requests within 1 minute reuse a Redis-cached score (duplicate-request protection)",
        ],
        "kind": "read", "timeout": 60,
        "say": "Three fixed test transactions through the public scoring API - a normal purchase, a suspicious one and a high-risk one. Watch the response time.",
        "show": "API docs (Swagger) - POST /score - optionally try one live.",
        "links": ["api_docs"],
        "caution": "These payloads use a fixed event time, so the decision is the same at any hour. The expected decision is printed next to each result.",
        "script": API_HELPERS + r'''RUN=$(date +%H%M%S)
fmt() { "$PY" -c 'import sys,json
try:
    d = json.load(sys.stdin)
except Exception:
    print("  [FAIL] %s: no valid response from the API" % sys.argv[1]); sys.exit(1)
exp = sys.argv[2]; tag = "[ OK ]" if d["decision"] == exp else "[WARN]"
print("  %s %-42s -> %-6s score %.4f   %6.1f ms   (expected %s)" % (tag, sys.argv[1], d["decision"], d["fraud_score"], d["scoring_latency_ms"], exp))' "$1" "$2"; }
hdr "POST /score - three reference transactions (XGBoost fast path)"
post "$(mk ref-a-$RUN 7919 ref-a-$RUN 25.0 W-MERCHANT-gmail.com 5411 US 2.0)"     | fmt 'USD 25 grocery, 2 km from usual location'  ALLOW
post "$(mk ref-b-$RUN 7919 ref-b-$RUN 899.0 C-MERCHANT-hotmail.com 5732 RU 8742.0)" | fmt 'USD 899 electronics, Russia, 8,742 km away' REVIEW
post "$(mk ref-c-$RUN 7919 ref-c-$RUN 1500.0 W-MERCHANT-gmail.com 5732 US 3000.0)" | fmt 'USD 1,500 electronics, 3,000 km away'      BLOCK
echo
echo "  Response time is measured inside the API: blocklist, velocity rule, features and XGBoost."
echo "  Certified under load in week 15 (k6, 10K tx/min for 30 min): p95 = 56.69 ms."
''',
    },
    {
        "id": "velocity", "section": "act2", "num": "2.2", "title": "Card-testing attack – velocity rule in action",
        "purpose": "Simulates a card-testing attack - six USD 1 charges on one card - and shows the rule layer catching what the ML model alone misses.",
        "built": [
            "Redis sliding-window counters per card: 5 per minute, 12 per 10 minutes, 25 per hour",
            "Runs before the model; a hit escalates the transaction to REVIEW",
            "Fail-open: if Redis is unavailable, scoring continues unaffected",
        ],
        "kind": "read", "timeout": 60,
        "say": "Card testing: fraudsters try tiny USD 1 charges first. The ML model alone sees nothing unusual; the Redis sliding-window velocity rule catches the burst on the fifth attempt within one minute.",
        "caution": "Each run uses a brand-new card ID, so running it again is safe.",
        "script": API_HELPERS + r'''CARD="vel-$(date +%H%M%S)"
hdr "Six USD 1.00 authorisations on one new card ($CARD)"
for i in 1 2 3 4 5 6; do
  post "$(mk "$CARD-$i" 4497 "$CARD" 1.0 W-MERCHANT-anonymous.com 5999 US 0.0)" | "$PY" -c 'import sys,json
try:
    d = json.load(sys.stdin)
except Exception:
    print("  [FAIL] attempt %s: no valid response from the API" % sys.argv[1]); sys.exit(1)
if d.get("velocity_hit"):
    print("  attempt %s  ->  %-6s  rule-forced         VELOCITY RULE: %s" % (sys.argv[1], d["decision"], d["velocity_reason"]))
else:
    print("  attempt %s  ->  %-6s  model score %.4f   rule not triggered" % (sys.argv[1], d["decision"], d["fraud_score"]))' "$i" || exit 1
  sleep 1
done
echo
echo "  The model rates each USD 1 charge as low risk. The velocity rule (5 per card per minute)"
echo "  escalates the burst to human REVIEW before the card is used for a large purchase."
''',
    },
    {
        "id": "enrichment", "section": "act2", "num": "2.3", "title": "Explainable AI – SHAP evidence for flagged events",
        "purpose": "Every REVIEW or BLOCK decision is explained: which features pushed the risk up or down, plus a plain-English summary for the analyst.",
        "built": [
            "Slow-path service reads scored events; ALLOW decisions are skipped",
            "SHAP TreeExplainer: the top 5 feature contributions for each event",
            "2-3 sentence narrative; the live stream uses the template narrator to stay within its 1.5 s budget",
            "Published to transactions.enriched and stored in PostgreSQL",
        ],
        "kind": "read", "timeout": 60,
        "say": "Only flagged events take the slow path. SHAP shows which features pushed the score up or down, and an analyst-readable explanation is attached to each event.",
        "show": "Power BI - Real-time Alert Feed (narrative column).",
        "caution": "Value -999 means the feature is not available on a single live event (only ~35% are). SHAP truthfully shows the model leaning on those missing-value patterns - the same limitation behind the demo thresholds; the production fix is a feature store supplying the historical features at scoring time (proposal 13.5). The example shown is the most recent event with live features in its top five; the coverage line shows how common that is. Live text uses the template narrator (Gemini cannot answer inside the 1.5 s budget); real Gemini is step 2.5.",
        "script": r'''hdr "Flagged events enriched in the last 15 minutes"
read -r E TX < <(sqlv "select count(*), count(text_anomaly_label) from enriched_events where inserted_at > now() - interval '15 minutes'" | tr '|' ' ')
echo "  Enriched with SHAP + explanation: $E      with DistilBERT text score: $TX"
read -r EN LV < <(sqlv "select count(*), count(*) filter (where exists (select 1 from jsonb_array_elements(top_contributors) c where (c->>'feature_value')::numeric <> -999)) from enriched_events where inserted_at > now() - interval '60 minutes'" | tr '|' ' ')
[ "${EN:-0}" -gt 0 ] && echo "  Explanation coverage (60 min): $LV of $EN cite at least one live feature in their top 5 ($(( LV * 100 / EN ))%); the rest rely on features missing on a live event (-999)."
hdr "Latest six flagged transactions"
sql "select to_char(inserted_at at time zone 'Asia/Kolkata', 'HH24:MI:SS') as time_ist, left(event_id, 8) as event, decision, round(fraud_score, 3) as score, top_contributors->0->>'feature_name' as top_shap_feature, narrator_mode as narrator, coalesce(text_anomaly_label, 'pending') as text_check from enriched_events order by inserted_at desc limit 6"
EID=$(sqlv "select event_id from enriched_events e where inserted_at > now() - interval '15 minutes' order by (select count(*) from jsonb_array_elements(e.top_contributors) c where (c->>'feature_value')::numeric <> -999) desc, inserted_at desc limit 1")
[ -n "$EID" ] || { echo "[FAIL] No enriched events yet"; exit 1; }
hdr "Example: most recent explanation with live features in its top five (event ${EID:0:8})"
sqlv "select narrative from enriched_events where event_id = '$EID'" | fold -s -w 110 | sed 's/^/  /'
hdr "Its SHAP top contributors (positive pushes towards fraud, negative towards legitimate)"
sql "select x.ord as rank, x.c->>'feature_name' as feature, case when (x.c->>'feature_value')::numeric = -999 then 'missing on live event' else round((x.c->>'feature_value')::numeric, 4)::text end as value, round((x.c->>'shap_value')::numeric, 4) as shap from enriched_events e, jsonb_array_elements(e.top_contributors) with ordinality as x(c, ord) where e.event_id = '$EID' order by x.ord"
''',
    },
    {
        "id": "textanomaly", "section": "act2", "num": "2.4", "title": "Language-model check – suspicious merchant names",
        "purpose": "A language model reads the merchant name and flags names that look machine-generated or fake - a signal numeric models cannot see.",
        "built": [
            "DistilBERT (distilbert-base-uncased): how unnatural the name reads (log-perplexity)",
            "Threshold 6.0 -> SUSPICIOUS, set conservatively so real merchants are not flagged",
            "Runs on the server itself: no API cost, and no data leaves the platform",
            "Checks the live stream in batches, flushed every 10 seconds",
        ],
        "kind": "read", "timeout": 180,
        "say": "DistilBERT scores how unnatural a merchant name reads (perplexity). Real domains like gmail.com score low, machine-generated names score higher, and anything above the 6.0 threshold - like verify-account-now.info - is flagged SUSPICIOUS. It runs locally at no cost per call.",
        "caution": "Be precise: in this list only verify-account-now.info crosses the 6.0 threshold. XJ8K2-zzz9.com, Q7wLm2xR3.top and paypaI-secure.net score well above real domains but below the line - the threshold is deliberately conservative so real merchants are not flagged; a character-level look-alike check would catch paypaI (future scope). Scores merchant_name only.",
        "script": r'''hdr "DistilBERT perplexity check on sample merchant names"
vf text_anomaly
hdr "Live pipeline - text checks in the last 60 minutes"
sql "select text_anomaly_label as label, count(*) as merchants_checked, round(avg(text_anomaly_score)::numeric, 3) as avg_score from enriched_events where text_anomaly_label is not null and inserted_at > now() - interval '60 minutes' group by 1 order by 1"
sql "select merchant_name, text_anomaly_label as label, round(text_anomaly_score, 3) as score from enriched_events where text_anomaly_label is not null order by text_scored_at_ms desc limit 5"
''',
    },
    {
        "id": "gemini", "section": "act2", "num": "2.5", "title": "Generative AI narratives – three fraud patterns",
        "purpose": "Three classic fraud patterns - velocity, impossible travel, merchant-category mismatch - each scored, evidenced with SHAP and explained in plain English by Gemini.",
        "built": [
            "Google Gemini API, free tier: about 4 requests per run",
            "Model gemini-3.5-flash-lite: free-tier quota is counted per model, so this step does not depend on the stream's main model quota",
            "Each narrative is grounded in the model score and its SHAP evidence",
            "If Gemini fails: last good Gemini text for that pattern (24 h cache, labelled GEMINI_CACHED), else a template - never a blank",
        ],
        "kind": "quota", "timeout": 300,
        "confirm": "Run the Gemini fraud-pattern explanations? This uses about 4 Gemini requests (gemini-3.5-flash-lite free tier). Run it once during the demo.",
        "say": "Three named fraud patterns - velocity, impossible travel and merchant-category mismatch - each scored by XGBoost, explained with SHAP and narrated in plain English by Gemini.",
        "caution": "Runs on gemini-3.5-flash-lite (its own free-tier quota; gemini-3.5-flash was used up on 13 Nov and resets at 13:30 IST). It always tries live Gemini first. Only if that call fails (quota/timeout) does it serve the last successful Gemini text for that scenario, cached 24 h (label GEMINI_CACHED), else the SHAP template (TEMPLATE). Running it during the rehearsal primes that safety cache for the demo. Do not re-run repeatedly.",
        "script": r'''hdr "Three fraud patterns - XGBoost score, SHAP evidence, Gemini narrative"
export GEMINI_MODEL=gemini-3.5-flash-lite
vf fraud_patterns
''',
    },

    # ------------------------------------------------------------------ ACT 3
    {
        "id": "groq_live", "section": "act3", "num": "3.1", "title": "LLM second opinion – Groq on the live stream",
        "purpose": "A large language model independently judges the same live transactions in parallel and writes a reason for each - without touching the decision path.",
        "built": [
            "Groq API, model qwen/qwen3.8-27b, limited to 12 calls per minute",
            "Sees only tokenised data: card, IP and device are SHA-256 hashes, never raw values",
            "Own consumer group and output topic (transactions.scored.groq)",
            "Stops by itself after 3 minutes to protect the free daily budget",
        ],
        "kind": "quota", "timeout": 90,
        "confirm": "Start Groq live now? It scores new events at up to 12 calls/minute. Run 3.2 and then 3.3 straight away; Groq stops by itself after 3 minutes as a safety net.",
        "say": "Groq's LLM now scores the same live stream in parallel as an independent second opinion, with a written reason for each decision. XGBoost is still making every decision.",
        "caution": "Free tier. Go straight on to 3.2 and 3.3 - about 15-20 calls in all. Groq stops by itself after 3 minutes (about 36 calls) if 3.3 is missed. If Groq returns 429, the call is skipped and scoring is unaffected.",
        "script": GROQ_HELPERS + r'''if running groq; then echo "  [ OK ] Groq is already running - a second copy will not be started."
else
  [ -n "$(pane groq)" ] || { echo "[FAIL] tmux window 'groq' is missing - use Recovery > Full pipeline restart"; exit 1; }
  groq_start 12
  groq_watchdog
  echo "  Groq started - waiting for its first decisions"
  if ! groq_wait_first 45; then
    echo "[FAIL] Groq did not score an event within 45 s"
    tmux capture-pane -p -t vf:groq -S -200 | grep -v '^\s*$' | tail -6 | clean
    groq_stop; groq_cleanup; exit 1
  fi
  sleep 8
fi
hdr "Groq LLM decisions on the live stream"
tmux capture-pane -p -t vf:groq -S -300 | grep "score=" | tail -6 | clean
echo "  [ OK ] Groq live. Now run 3.2 to compare it with XGBoost, then 3.3 to stop it."
echo "  Safety net: Groq stops by itself $((AUTO_STOP_S / 60)) minutes after it started."
''',
    },
    {
        "id": "groq_compare", "section": "act3", "num": "3.2", "title": "Two AIs, one transaction – XGBoost vs Groq",
        "purpose": "Both opinions side by side on the same events: decision, score, latency and the LLM's written reasoning.",
        "built": [
            "The scorer_comparison view joins both scorers on event_id",
            "XGBoost decides in milliseconds; Groq's network time is measured per call (groq_ms)",
            "The agreement rate feeds the drift monitor in step 3.6",
        ],
        "kind": "read", "timeout": 60,
        "say": "The same events, judged by two different kinds of AI: XGBoost decides in a few milliseconds; Groq's LLM adds a written reason, and the groq_ms column shows its real time per call over the network.",
        "show": "Power BI - Operational Health (fast path vs Groq latency, agreement).",
        "caution": "Groq is a parallel second opinion, not the fast path. Do not describe Groq as sub-100 ms.",
        "script": r'''running groq || echo "  [WARN] Groq is not running now - showing the comparisons stored in the last 60 minutes."
hdr "XGBoost (decision path) vs Groq LLM (second opinion) - last 60 minutes"
sql "select count(*) as compared, round(100.0 * avg(case when decisions_agree then 1 else 0 end), 1) as agree_pct, round(avg(xgb_latency_ms)::numeric, 1) as xgb_avg_ms, round(avg(groq_latency_ms)::numeric, 0) as groq_avg_ms from scorer_comparison where scored_at_ms > (extract(epoch from now()) * 1000 - 3600000)"
hdr "Latest eight side-by-side decisions"
sql "select left(event_id, 8) as event, xgb_decision as xgb, round(xgb_score, 3) as xgb_score, groq_decision as groq, round(groq_score, 3) as groq_score, groq_latency_ms as groq_ms, left(llm_reason, 60) as groq_reason from scorer_comparison order by scored_at_ms desc limit 8"
''',
    },
    {
        "id": "groq_halt", "section": "act3", "num": "3.3", "title": "Remove the LLM – decisions never pause",
        "purpose": "Stops the LLM live to prove the external AI service is optional: transactions keep being scored without interruption.",
        "built": [
            "XGBoost is the only decision path; Groq is advisory",
            "Proof: XGBoost decisions counted in the 15 seconds after the stop",
            "Removes the temporary consumer group so the lag figures stay accurate",
        ],
        "kind": "control", "timeout": 90,
        "say": "I stop the LLM now. Nothing in the decision path depended on it: XGBoost keeps scoring every transaction. That is the design choice - the external AI service can disappear at any moment without affecting a single payment.",
        "script": GROQ_HELPERS + r'''if running groq; then
  groq_stop || { echo "[FAIL] Groq did not stop within 20 s - use R2"; exit 1; }
  echo "  [ OK ] Groq stopped."
elif [ -s "$GRP_FILE" ]; then
  echo "  Groq had already stopped by itself (the $((AUTO_STOP_S / 60))-minute safety net)."
else
  echo "  Groq is not running."
fi
hdr "Decision path after Groq stopped"
sleep 15
X=$(sqlv "select count(*) from scored_events where inserted_at > now() - interval '15 seconds'")
G=$(sqlv "select count(*) from scored_events_groq where inserted_at > now() - interval '15 seconds'")
echo "  XGBoost decisions in the last 15 s : $X"
echo "  Groq decisions in the last 15 s    : $G"
if [ "${X:-0}" -gt 0 ]; then echo "  [ OK ] Scoring never paused - the XGBoost decision path does not depend on Groq."
else echo "[WARN] No XGBoost decisions in the last 15 s - check the pipeline (P1)."; fi
[ -s "$START_FILE" ] && echo "  Groq gave $(groq_calls) live second opinion(s) in this session."
groq_cleanup
''',
    },
    {
        "id": "failover", "section": "act3", "num": "3.4", "title": "Zero-downtime failover – stop the active scorer",
        "purpose": "Simulates a crash of the active scoring service; the hot standby takes over automatically and the stream never stops.",
        "built": [
            "Two XGBoost scorers run hot - both score every event",
            "Leader election through a Redis lock (vf:scorer:leader): 5 s expiry, 1 s heartbeat",
            "Only the leader publishes; a split-brain guard re-checks ownership on every heartbeat",
            "Takeover time is measured live, in milliseconds",
        ],
        "kind": "control", "timeout": 90,
        "confirm": "This stops the ACTIVE fast-path scorer to simulate an outage. The hot standby takes over automatically. Continue?",
        "say": "Two XGBoost scorers run hot; a Redis lock decides which one publishes. I now stop the ACTIVE one - watch the standby take over with no gap in the scored stream.",
        "caution": "Run 3.5 straight afterwards so the system is fully redundant again.",
        "script": r'''LD=$(leader)
[ -n "$LD" ] || { echo "[FAIL] No scorer currently holds the leader lock."; exit 1; }
ACT=${LD%%-*}
case "$ACT" in primary) OTH=standby ;; standby) OTH=primary ;; *) echo "[FAIL] Unexpected lock value: $LD"; exit 1 ;; esac
running "$ACT" || { echo "[FAIL] The lock names $ACT as ACTIVE but that program is not running."; exit 1; }
running "$OTH" || { echo "[REFUSED] The $OTH scorer is not running, so there is no hot standby to take over. Run step 3.5 first."; exit 1; }
hdr "Before"
echo "  ACTIVE  : $ACT   (lock id $LD)"
echo "  STANDBY : $OTH   (scoring every event in parallel, output suppressed)"
echo "  Scored events written in the last 30 s: $(sqlv "select count(*) from scored_events where inserted_at > now() - interval '30 seconds'")"
hdr "Simulated outage - stopping the ACTIVE scorer ($ACT)"
T0=$(date +%s%N)
tmux send-keys -t "vf:$ACT" C-c
NEW=""
for i in $(seq 1 150); do NEW=$(leader); [ "${NEW%%-*}" = "$OTH" ] && break; sleep 0.1; done
T1=$(date +%s%N)
[ "${NEW%%-*}" = "$OTH" ] || { echo "[FAIL] The standby did not take over within 15 s"; exit 1; }
echo "  [ OK ] Leadership moved to $OTH in $(( (T1 - T0) / 1000000 )) ms (measured by this console)"
sleep 8
hdr "After"
echo "  ACTIVE now : $OTH"
tmux capture-pane -p -t "vf:$OTH" -S -300 | grep -E "PROMOTING" | tail -1 | clean
N=$(sqlv "select count(*) from scored_events where inserted_at > now() - interval '8 seconds'")
echo "  Scored events written in the 8 s after the takeover: $N"
if [ "${N:-0}" -gt 0 ]; then echo "  [ OK ] The scored stream never stopped - no consumer-visible interruption."
else echo "  [WARN] No new scored rows yet - check the sink program."; fi
echo "  The stopped scorer ($ACT) is now idle. Step 3.5 brings it back as the new hot standby."
''',
    },
    {
        "id": "restore", "section": "act3", "num": "3.5", "title": "Self-healing – restore full redundancy",
        "purpose": "Brings the stopped scorer back as the new hot standby, so the platform is fully redundant again.",
        "built": [
            "Restarts the stopped service with the same model and thresholds",
            "It joins as STANDBY, so leadership does not flip back",
            "Model load takes about 20-40 seconds",
        ],
        "kind": "control", "timeout": 120,
        "say": "The stopped scorer comes back as the new hot standby - the system is fully redundant again.",
        "script": r'''STOPPED=""
for r in primary standby; do running "$r" || { STOPPED="$r"; break; }; done
if [ -z "$STOPPED" ]; then
  echo "  [ OK ] Both scorers are already running - nothing to restore."
  LD=$(leader); echo "  ACTIVE: ${LD%%-*}"; exit 0
fi
[ -n "$(pane "$STOPPED")" ] || { echo "[FAIL] tmux window '$STOPPED' is missing - use Recovery > Full pipeline restart"; exit 1; }
tmux send-keys -t "vf:$STOPPED" "clear" Enter; tmux clear-history -t "vf:$STOPPED"
tmux send-keys -t "vf:$STOPPED" "$T FAILOVER_ROLE=$STOPPED uv run python -m velocityfraud.failover_scorer" Enter
echo "  Restarting the $STOPPED scorer (model load takes about 20-40 s)"
for i in $(seq 1 90); do tmux capture-pane -p -t "vf:$STOPPED" | grep -q "STATE =" && break; sleep 1; done
hdr "Status"
tmux capture-pane -p -t "vf:$STOPPED" | grep -E "ONLINE|STATE =" | tail -2 | clean
LD=$(leader)
running "$STOPPED" && echo "  [ OK ] $STOPPED is running again. ACTIVE: ${LD%%-*}" || { echo "[FAIL] $STOPPED exited - see Recovery"; exit 1; }
''',
    },
    {
        "id": "drift", "section": "act3", "num": "3.6", "title": "Model drift monitor – automated alarm and audit trail",
        "purpose": "Measures how often XGBoost and the LLM disagree; above 5% an alarm fires, and every check is recorded for audit.",
        "built": [
            "Windowed agreement rate over the scorer_comparison view",
            "Alarm threshold: 5% disagreement (from the proposal)",
            "Every check stored with its window, sample size and result",
            "Observes only - it never changes a live decision",
        ],
        "kind": "action", "timeout": 120,
        "say": "If XGBoost and Groq disagree on more than 5% of events, one of them has drifted. The monitor raises an alarm and records every check for audit.",
        "caution": "Expect the alarm to fire: the checks on 4 and 5 Nov measured 56.4% and 68.3% disagreement. Present it as the monitor doing its job - the two models judge differently, which is why REVIEW cases go to a human. Groq ran only briefly, so the check may widen its window to 72 hours - it says so in the output.",
        "script": r'''W=120
N=$(sqlv "select count(*) from scorer_comparison where scored_at_ms > (extract(epoch from now()) * 1000 - $W * 60000)")
if [ "${N:-0}" -lt 20 ]; then
  W=4320
  N=$(sqlv "select count(*) from scorer_comparison where scored_at_ms > (extract(epoch from now()) * 1000 - $W * 60000)")
  echo "  Groq ran only briefly today, so this check covers the last 72 hours of pipeline data."
fi
echo "  Events scored by both XGBoost and Groq in the window: $N"
[ "${N:-0}" -lt 20 ] && echo "  [WARN] Small sample - the rate will be noisy."
hdr "Drift check - $W-minute window, 5% threshold"
vf drift check --window-minutes "$W"
hdr "Drift-check history (audit trail)"
vf drift history --limit 5
''',
    },

    # ------------------------------------------------------------------ ACT 4
    {
        "id": "appeal_submit", "section": "act4", "num": "4.1", "title": "Customer appeal – dispute a blocked payment",
        "purpose": "A customer disputes a BLOCK: the case is recorded, the customer is protected from being re-blocked, and the payment is re-submitted.",
        "built": [
            "Appeal stored in PostgreSQL with the original decision and score",
            "Card, merchant, IP and device whitelisted in Redis for 24 hours",
            "Original event re-published to Kafka (idempotent producer)",
            "The case appears immediately in the analyst queue",
        ],
        "kind": "action", "timeout": 90, "confirm_rerun": True,
        "say": "A customer disputes a BLOCK. The system records the appeal, whitelists the customer's card, merchant, IP and device so blocklist rules cannot re-block them, and re-submits the transaction to the pipeline.",
        "caution": "Each run creates a new appeal on the newest blocked transaction that has no appeal or feedback yet.",
        "script": r'''EID=$(sqlv "select s.event_id from scored_events s where s.decision = 'BLOCK' and not exists (select 1 from appeals a where a.event_id = s.event_id) and not exists (select 1 from feedback_events f where f.event_id = s.event_id) order by s.inserted_at desc limit 1")
[ -n "$EID" ] || { echo "[FAIL] No un-appealed BLOCK decision found yet."; exit 1; }
hdr "The blocked transaction being disputed"
sql "select left(event_id, 8) as event, amount, merchant_name, mcc, decision, round(fraud_score, 3) as score, to_char(inserted_at at time zone 'Asia/Kolkata', 'HH24:MI:SS') as blocked_at_ist from scored_events where event_id = '$EID'"
hdr "Customer submits an appeal"
vf appeal submit --event-id "$EID" --reason "Customer confirms the purchase was genuine" --name "Demo Customer"
hdr "Analyst queue - unresolved appeals"
vf appeal list
''',
    },
    {
        "id": "appeal_resolve", "section": "act4", "num": "4.2", "title": "Analyst decision – overturn with a full audit trail",
        "purpose": "The analyst makes the binding decision; the original and final outcomes are kept side by side with timestamps.",
        "built": [
            "Audit trail: original decision and score, final decision, submitted and resolved times",
            "Records how many entities were whitelisted",
            "The human decision is final - the model score is never rewritten",
        ],
        "kind": "action", "timeout": 60,
        "say": "The analyst reviews the case and overturns the decision. The audit trail keeps the original and final decisions with timestamps.",
        "caution": "The binding outcome is the analyst's final decision in the audit trail. The re-submitted event is re-scored with the same features, so its model score does not change - do not claim it does.",
        "script": r'''AID=$(sqlv "select appeal_id from appeals where resolved_at is null order by submitted_at desc limit 1")
[ -n "$AID" ] || { echo "[FAIL] There is no open appeal - run step 4.1 first."; exit 1; }
hdr "Analyst resolves appeal #$AID"
vf appeal resolve --appeal-id "$AID" --notes "Verified with the customer - false positive" --final-decision ALLOW
hdr "Audit trail"
sql "select appeal_id, left(event_id, 8) as event, appellant_name, original_decision, round(original_fraud_score, 3) as original_score, final_decision, to_char(submitted_at at time zone 'Asia/Kolkata', 'HH24:MI:SS') as submitted_ist, to_char(resolved_at at time zone 'Asia/Kolkata', 'HH24:MI:SS') as resolved_ist, jsonb_array_length(coalesce(whitelisted_entities, '[]'::jsonb)) as entities_whitelisted from appeals where appeal_id = $AID"
''',
    },
    {
        "id": "feedback", "section": "act4", "num": "4.3", "title": "Learning loop – analyst verdicts become training data",
        "purpose": "Analyst verdicts flow back through Kafka into PostgreSQL as labelled data, showing where the model and the humans disagree.",
        "built": [
            "Verdicts published to transactions.feedback (idempotent producer)",
            "Stored with the model's decision and score next to the analyst's verdict",
            "Agreement statistics guide the next retraining",
        ],
        "kind": "action", "timeout": 60, "confirm_rerun": True,
        "say": "Analyst verdicts flow back through Kafka into PostgreSQL as labelled data for retraining. The agreement statistics show where the model and the humans differ.",
        "caution": "Each run records one new verdict on the newest blocked transaction without feedback. Agreement reads 0% because every demo verdict overturns a BLOCK - these are the disputed cases the loop exists to capture. It is not a model-accuracy figure; accuracy is in 5.2.",
        "script": r'''EID=$(sqlv "select s.event_id from scored_events s where s.decision = 'BLOCK' and not exists (select 1 from feedback_events f where f.event_id = s.event_id) and not exists (select 1 from appeals a where a.event_id = s.event_id) order by s.inserted_at desc limit 1")
[ -n "$EID" ] || { echo "[FAIL] No blocked transaction without feedback found yet."; exit 1; }
hdr "Analyst records a verdict on blocked event ${EID:0:8}"
vf feedback submit --event-id "$EID" --verdict LEGIT --analyst raghul --notes "Reviewed - legitimate customer, false positive"
hdr "Model vs analyst agreement (all feedback)"
vf feedback stats
''',
    },

    # ------------------------------------------------------------------ ACT 5
    {
        "id": "ops", "section": "act5", "num": "5.1", "title": "Operational health – the on-call view",
        "purpose": "What an on-call engineer watches: the backlog of every service, LLM rate-limit headroom and scoring latency.",
        "built": [
            "Collector polls every 30 seconds into a time-stamped ops_metrics table",
            "Kafka consumer lag per service and topic",
            "Groq calls used and headroom per minute",
            "Fast-path latency p50 / p95 / p99 over the last 15 minutes",
        ],
        "kind": "read", "timeout": 60,
        "say": "The on-call view: consumer lag for every service, Groq rate-limit headroom and fast-path latency percentiles - the same numbers as the Power BI Operational Health page.",
        "show": "Power BI - Operational Health.",
        "caution": "Groq headroom is measured against the collector's default cap of 25 calls/minute; the demo runs Groq at 12/minute. With Groq stopped it reads 0 used.",
        "script": r'''hdr "Kafka consumer lag - latest snapshot per consumer group"
sql "select split_part(scope, '/', 1) as consumer_group, split_part(scope, '/', 2) as topic, metric_value::bigint as lag, to_char(captured_at at time zone 'Asia/Kolkata', 'HH24:MI:SS') as captured_ist from ops_metrics_latest where metric_name = 'kafka_consumer_lag' order by lag desc"
hdr "Groq rate-limit usage"
sql "select metric_name, metric_value as per_minute from ops_metrics_latest where metric_name like 'groq_%' order by 1"
hdr "Fast-path scoring latency - last 15 minutes"
sql "select count(*) as events, round(percentile_cont(0.50) within group (order by scoring_latency_ms)::numeric, 1) as p50_ms, round(percentile_cont(0.95) within group (order by scoring_latency_ms)::numeric, 1) as p95_ms, round(percentile_cont(0.99) within group (order by scoring_latency_ms)::numeric, 1) as p99_ms, max(scoring_latency_ms) as max_ms from scored_events where inserted_at > now() - interval '15 minutes'"
''',
    },
    {
        "id": "governance", "section": "act5", "num": "5.2", "title": "Model governance – champion vs challenger, in MLflow",
        "purpose": "Two models were compared on 118,108 unseen transactions; the champion was chosen on evidence, and every run is tracked.",
        "built": [
            "XGBoost (champion) vs Random Forest (challenger) on the IEEE-CIS hold-out set",
            "ROC-AUC 0.956 vs 0.950; recall 0.84 vs 0.78",
            "Metrics stored in PostgreSQL (model_metrics) and in MLflow 2.18",
            "Production model file: xgboost_v1.pkl",
        ],
        "kind": "read", "timeout": 60,
        "say": "Random Forest and XGBoost were compared on 118,108 held-out transactions. XGBoost is the champion on ROC-AUC 0.956 and recall 0.84, because a missed fraud costs more than a human review.",
        "show": "Power BI - Model Performance; MLflow if it holds runs (see the readiness check).",
        "links": ["mlflow"],
        "caution": "Be upfront: F1 0.46 and FPR 6.56% at the 0.5 operating point. The proposal's F1 >= 0.92 is above this dataset's measured ceiling of 0.67 (threshold sweep). In MLflow, point at the finished runs (green tick); the 2 red-cross runs are early July attempts.",
        "script": r'''hdr "Champion vs challenger - held-out IEEE-CIS test set"
sql "select model_name, case when is_champion then 'CHAMPION' else 'challenger' end as role, roc_auc, pr_auc, precision_score as precision, recall_score as recall, f1_score as f1, fpr, test_rows from model_metrics order by is_champion desc"
hdr "Model in production"
curl -s -m 5 localhost:8000/health | "$PY" -c 'import sys,json; d=json.load(sys.stdin); print("  Champion: %s   |   REVIEW >= %s   BLOCK >= %s" % (d.get("champion"), d.get("review_thresh"), d.get("block_thresh")))'
hdr "MLflow experiment tracking (this server)"
"$PY" - <<'PYEOF'
import json, urllib.request
def post(p, b):
    r = urllib.request.Request("http://localhost:5000/api/2.0/mlflow/" + p, data=json.dumps(b).encode(),
                               headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=5))
try:
    exps = post("experiments/search", {"max_results": 100}).get("experiments", [])
except Exception as e:
    print("  [WARN] MLflow API not reachable on this server (%s)" % type(e).__name__)
    raise SystemExit(0)
names = {e["experiment_id"]: e["name"] for e in exps}
runs = post("runs/search", {"experiment_ids": list(names), "max_results": 50}).get("runs", []) if names else []
if not runs:
    print("  [WARN] No MLflow runs on this server. Training runs were logged to the development MLflow;")
    print("         the same metrics are shown above from the model_metrics table and in Power BI.")
for r in runs:
    info = r["info"]
    m = {x["key"]: x["value"] for x in r.get("data", {}).get("metrics", [])}
    keys = [k for k in ("roc_auc", "pr_auc", "precision", "recall", "f1") if k in m]
    print("  %-20s %-20s %s" % (names.get(info["experiment_id"], "?")[:20], (info.get("run_name") or "")[:20],
                               "  ".join("%s=%.4f" % (k, m[k]) for k in keys)))
PYEOF
''',
    },
    {
        "id": "infra", "section": "act5", "num": "5.3", "title": "Cloud infrastructure – live load and cost",
        "purpose": "The real resource use of the whole platform on one modest cloud server - and what it costs to run.",
        "built": [
            "Hetzner CPX32: 4 vCPU, 8 GB RAM, 150 GB disk",
            "About USD 0.067 per hour while it runs",
            "Firewall: only SSH and the scoring API are open to the internet",
            "Rebuilt from a saved snapshot in minutes",
        ],
        "kind": "read", "timeout": 60,
        "say": "The full pipeline runs on a single 4-vCPU Hetzner server. These are live resource figures; the Hetzner console shows the same load in its graphs.",
        "show": "Hetzner Console - vf-demo - Graphs.",
        "links": ["hetzner"],
        "script": r'''hdr "Hetzner cloud server"
printf '  %s  |  %s vCPU  |  load average %s\n' "$(hostname)" "$(nproc)" "$(cut -d' ' -f1-3 /proc/loadavg)"
free -h | awk '/^Mem:/ {printf "  Memory: %s used of %s (%s available)\n", $3, $2, $7}'
df -h / | awk 'NR==2 {printf "  Disk:   %s used of %s (%s)\n", $3, $2, $5}'
hdr "Container resource usage (live)"
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}'
hdr "Busiest pipeline processes"
ps -eo pcpu,pmem,etime,args --sort=-pcpu | grep -E "velocityfraud|uvicorn" | grep -v -E "grep|uv run" | head -8 | cut -c1-150 || true
''',
    },
    {
        "id": "k6_live", "section": "act5", "num": "5.4", "title": "Live load test – k6 at 10,000 transactions a minute",
        "purpose": "The week-15 load test, run live: a separate load server sends 10,000 transactions a minute to the scoring API for 60 seconds and measures every response.",
        "built": [
            "k6 on a separate small server in the same location - the load never competes with the system under test",
            "Same endpoint, thresholds and summary as the week-15 certificate (p95 under 100 ms, p99 under 200 ms)",
            "Every request is a new card and amount, so each one runs the full path: blocklist, velocity rule, features, XGBoost",
            "Week 15 held this rate for 30 minutes: p95 56.69 ms, p99 98.45 ms, 0% failed",
        ],
        "kind": "load", "timeout": 150, "host": "loadgen",
        "confirm": "Send 10,000 transactions a minute to the live scoring API for 60 seconds? The demo server is busier for that minute.",
        "links": ["hetzner"],
        "say": "This is the week-15 load test, live. A separate server fires 10,000 transactions a minute at the scoring API for one minute. Watch the p95 against the 100 ms budget, then the Hetzner graphs show the spike on both servers.",
        "show": "Hetzner Console - Graphs of both servers (the one-minute spike in CPU and network).",
        "caution": "Run P6 at 10:45 first. Wait for this step to finish before the next one. Differences from the week-15 script, if asked: full rate from the first second (a 60-second run has no time for a ramp) and a new card per request, because the velocity rule and score cache added after week 15 would otherwise skip the model.",
        "script": r'''command -v k6 >/dev/null || { echo "[FAIL] k6 is not installed on the load server - run P5 first"; exit 1; }
hdr "Before the test"
check_target
cat > "$W/k6-live.js" <<'K6EOF'
''' + K6_LIVE_JS + r'''
K6EOF
RUN=$(date +%H%M%S)
rm -f "$W/k6-live-summary.json"
hdr "k6 - 167 transactions a second (10,000 a minute) for 60 seconds"
echo "  From the load server $(hostname) to the scoring API on the demo server"
k6 run --quiet --no-color -e BASE_URL="http://$TARGET:8000" -e RATE_PER_SEC=167 -e DURATION=60s -e RUN_ID="$RUN" \
  -e SUMMARY_OUT="$W/k6-live-summary.json" "$W/k6-live.js" > "$W/k6-live.out" 2>&1 &
watch_pid $! "sending 167 transactions a second"
RC=$?
if [ ! -s "$W/k6-live-summary.json" ]; then echo "[FAIL] k6 did not finish (exit $RC) - its output:"; tail -20 "$W/k6-live.out"; exit 1; fi
grep -v -E '^\s*$|level=' "$W/k6-live.out" | sed 's/^/  /'
hdr "Result against the latency budget"
python3 - "$W/k6-live-summary.json" <<'PYEOF'
import json, sys
m = json.load(open(sys.argv[1]))["metrics"]
v = lambda k: m.get(k, {}).get("values", {})
d, s, r = v("http_req_duration"), v("scoring_latency_ms"), v("http_reqs")
n, per_min = int(r.get("count", 0)), r.get("rate", 0) * 60
failed, dropped = v("http_req_failed").get("rate", 0) * 100, int(v("dropped_iterations").get("count", 0))
def line(ok, label, text):
    print("  %s %-20s %s" % ("[ OK ]" if ok else "[WARN]", label, text))
line(failed < 1 and dropped == 0, "Throughput", "%s requests, ~%s a minute, %.2f%% failed%s"
     % (format(n, ","), format(round(per_min), ","), failed, ", %d not sent in time" % dropped if dropped else ""))
line(d.get("p(95)", 1e9) < 100, "p95 response time", "%.2f ms, end to end (budget: under 100 ms)" % d.get("p(95)", float("nan")))
line(d.get("p(99)", 1e9) < 200, "p99 response time", "%.2f ms (budget: under 200 ms)" % d.get("p(99)", float("nan")))
if s:
    print("         %-20s p95 %.2f ms for blocklist, velocity rule, features and XGBoost" % ("Inside the API", s["p(95)"]))
print()
print("  Week-15 certificate, 30 minutes at the same rate: p95 56.69 ms, p99 98.45 ms, 0% failed.")
PYEOF
''',
    },
    {
        "id": "locust_live", "section": "act5", "num": "5.5", "title": "Live capacity test – Locust with 100 simultaneous users",
        "purpose": "The second week-15 load test, run live: 100 simulated payment gateways send transactions back to back for 60 seconds, to show how much the API handles with no errors.",
        "built": [
            "Locust on the same separate load server",
            "A different load shape from k6: as many requests as 100 users can send, not a fixed rate",
            "Every request is a new card and amount, so each one runs the full model",
            "Week 15: 56,035 requests in 3 minutes (~18,690 a minute), 0% failed",
        ],
        "kind": "load", "timeout": 150, "host": "loadgen",
        "confirm": "Run 100 simultaneous users against the live scoring API for 60 seconds? The demo server runs at full capacity for that minute.",
        "links": ["hetzner"],
        "say": "k6 proved speed at the target rate; Locust finds the capacity. 100 simulated gateways send as fast as they can for a minute - watch the throughput against the 10,000-a-minute target and the failure count.",
        "show": "Hetzner Console - Graphs (the second spike).",
        "caution": "Response times here are higher than in 5.4 by design: at full capacity requests queue. Quote throughput and failures from this step, latency from 5.4. Run it after 5.4 has finished.",
        "script": r'''[ -x "$LOCUST" ] || { echo "[FAIL] Locust is not installed on the load server - run P5 first"; exit 1; }
hdr "Before the test"
check_target
cat > "$W/locust-live.py" <<'LCEOF'
''' + LOCUST_LIVE_PY + r'''
LCEOF
rm -f "$W"/locust-live_*.csv
hdr "Locust - 100 simultaneous users for 60 seconds"
echo "  Each simulated user is a payment gateway sending transactions back to back"
"$LOCUST" -f "$W/locust-live.py" --headless -u 100 -r 20 -t 60s --host "http://$TARGET:8000" \
  --csv "$W/locust-live" --only-summary --loglevel WARNING > "$W/locust-live.out" 2>&1 &
watch_pid $! "100 users sending transactions"
[ -s "$W/locust-live_stats.csv" ] || { echo "[FAIL] Locust did not finish - its output:"; tail -20 "$W/locust-live.out"; exit 1; }
hdr "Result"
"$HOME/loadgen-env/bin/python" - "$W/locust-live_stats.csv" <<'PYEOF'
import csv, sys
row = next(r for r in csv.DictReader(open(sys.argv[1])) if r["Name"] == "Aggregated")
n, f = int(row["Request Count"]), int(row["Failure Count"])
per_min = float(row["Requests/s"]) * 60
def line(ok, label, text):
    print("  %s %-20s %s" % ("[ OK ]" if ok else "[WARN]", label, text))
line(per_min >= 10000, "Throughput", "%s requests, ~%s a minute (%.1fx the 10,000-a-minute target)"
     % (format(n, ","), format(round(per_min), ","), per_min / 10000))
line(n > 0 and f / n < 0.01, "Failures", "%s of %s (%.2f%%)" % (format(f, ","), format(n, ","), 100.0 * f / n if n else 0))
print("         %-20s median %s ms, p95 %s ms - requests queue at full capacity; latency is measured in 5.4"
      % ("At full load", row["Median Response Time"], row["95%"]))
print()
print("  Week 15, 3 minutes with 100 users: 56,035 requests (~18,690 a minute), 0% failed.")
PYEOF
''',
    },
    {
        "id": "qa_live", "section": "act5", "num": "5.6", "title": "Quality checks on the live stream – correctness, speed, privacy",
        "purpose": "Seven automated checks run now on the last 60 minutes of real decisions: nothing duplicated, nothing missing, every decision follows the policy, within the speed budget, every flag explained, no raw card or IP data stored.",
        "built": [
            "Read-only SQL on the PostgreSQL store - nothing is changed",
            "The same rules the QA suite tests: unique events, valid decisions, thresholds, the 100 ms budget",
            "Privacy: card, IP and device are stored only as 16-character SHA-256 tokens",
            "Explanations are checked on flagged events older than 5 minutes, so the slow path has time to finish",
        ],
        "kind": "read", "timeout": 60,
        "say": "These are the rules from our test suite, run right now on the live stream: no duplicates, every event decided, every decision following the thresholds, the speed budget, every flag explained, and no raw card or IP data stored.",
        "caution": "Run it once at 6 AM after P1. A [WARN] on 'Every flag explained' just after a restart only means the slow path is still catching up - consumer lag is in 5.1. The policy check uses the demo thresholds 0.10 / 0.18 and skips blocklist hits, which are rule decisions.",
        "script": r'''hdr "Live quality checks - last 60 minutes of the stream (read-only)"
read -r N DUP BAD MIS TOK UNDER P95 AGE < <(sqlv "select count(*), count(*) - count(distinct event_id), count(*) filter (where decision not in ('ALLOW', 'REVIEW', 'BLOCK') or fraud_score < 0 or fraud_score > 1 or scoring_latency_ms is null), count(*) filter (where not coalesce(blocklist_hit, false) and decision <> case when fraud_score >= 0.18 then 'BLOCK' when fraud_score >= 0.10 then 'REVIEW' else 'ALLOW' end), count(*) filter (where card_token !~ '^([0-9a-f]{16}|null)\$' or ip_address_hash !~ '^([0-9a-f]{16}|null)\$' or device_fingerprint_hash !~ '^([0-9a-f]{16}|null)\$'), round(100.0 * count(*) filter (where scoring_latency_ms < 100) / nullif(count(*), 0), 1), round(percentile_cont(0.95) within group (order by scoring_latency_ms)::numeric, 1), extract(epoch from now() - max(inserted_at))::int from scored_events where inserted_at > now() - interval '60 minutes'" | tr '|' ' ')
[ "${N:-0}" -gt 0 ] || { echo "[FAIL] No scored events in the last 60 minutes - the pipeline is not flowing (run P1)"; exit 1; }
read -r FL EX < <(sqlv "select count(*), count(e.event_id) from scored_events s left join enriched_events e using (event_id) where s.decision in ('REVIEW', 'BLOCK') and s.inserted_at between now() - interval '60 minutes' and now() - interval '5 minutes'" | tr '|' ' ')
PASS=0; TOTAL=0
chk() { TOTAL=$((TOTAL + 1)); if [ "$1" -eq 0 ]; then PASS=$((PASS + 1)); printf '  [ OK ] %-28s %s\n' "$2" "$3"; else printf '  [WARN] %-28s %s\n' "$2" "$3"; fi; }
echo "  $N events scored in the last 60 minutes"
echo
[ "$AGE" -le 60 ];  chk $? "Stream is flowing"           "newest decision stored $AGE s ago"
[ "$DUP" -eq 0 ];   chk $? "No duplicate events"         "$DUP duplicates - each event is stored once; a re-delivered message updates its row"
[ "$BAD" -eq 0 ];   chk $? "Every event fully decided"   "$BAD with a missing or invalid decision, score or latency"
[ "$MIS" -eq 0 ];   chk $? "Decisions follow the policy" "$MIS mismatches against REVIEW >= 0.10 / BLOCK >= 0.18"
awk -v u="$UNDER" 'BEGIN { exit !(u >= 95) }'; chk $? "Within the 100 ms budget" "$UNDER% decided in under 100 ms (p95 $P95 ms)"
if [ "${FL:-0}" -gt 0 ]; then
  PCT=$(awk -v f="$FL" -v e="$EX" 'BEGIN { printf "%.1f", 100 * e / f }')
  awk -v p="$PCT" 'BEGIN { exit !(p >= 95) }'; chk $? "Every flag explained" "$EX of $FL REVIEW / BLOCK events ($PCT%) have SHAP evidence and an explanation"
else
  chk 1 "Every flag explained" "no flagged events older than 5 minutes yet"
fi
[ "$TOK" -eq 0 ];   chk $? "No raw card or IP data"      "$TOK identifiers stored outside 16-character SHA-256 tokens"
echo
echo "  Result: $PASS of $TOTAL checks passed"
''',
    },
    {
        "id": "qa_evidence", "section": "act5", "num": "5.7", "title": "QA evidence – load tests, test suite and independent audit",
        "purpose": "The tests that cannot run during a live demo - the 30-minute load tests, the full test suite, data checks and the independent audit - with their recorded results.",
        "built": [
            "k6 and Locust ran from a separate load-generator server, so the load never competed with the system under test",
            "122 automated tests, 59 Great Expectations data checks, chaos and backpressure scripts",
            "AI-assisted QA: drift alarm, AI grading of AI narratives, AI-designed load shapes",
            "Independent Evidently audit: 16 reports on 118,108 held-out transactions",
        ],
        "kind": "read", "timeout": 30,
        "say": "Some QA does not belong on a live server: a 30-minute load test at 10,000 a minute, or tests that write test records, would disturb the demo itself. These are the recorded results; each one has a report in the appendix.",
        "caution": "Recorded results, not a live run - say so. The CI latency gate is configured in the build workflow: describe it as configured, not as a run result. The live versions of the load tests are 5.4 and 5.5.",
        "script": r'''row() { printf '  %s %-24s %s\n' "$1" "$2" "$3"; }
hdr "Load tests - week-15 certificate, 30 minutes (live 60-second versions: 5.4 and 5.5)"
row "[ OK ]" "k6, 10,000 a minute" "301,535 requests in 30 minutes (~9,996 a minute), 0.00% failed"
row "      " "" "p95 56.69 ms, p99 98.45 ms (budget: p95 under 100 ms)"
row "[ OK ]" "Locust, 100 users" "56,035 requests in 3 minutes (~18,690 a minute), 0% failed"
hdr "Automated tests and data quality"
row "[ OK ]" "pytest" "122 tests passed, 80.05% code coverage (target: at least 80%)"
row "[ OK ]" "Great Expectations" "59 of 59 data checks passed on the model-ready features"
row "[INFO]" "CI latency gate" "configured in the build workflow: fails the build if p95 >= 100 ms or p99 >= 200 ms"
hdr "Resilience tests (live versions in Act 3)"
row "[ OK ]" "Redis down" "the blocklist fails open; the model keeps scoring"
row "[ OK ]" "Kafka broker down" "fast-path decisions continue; consumers reconnect with no data loss"
row "[ OK ]" "Load spike" "Kafka buffers the surge; the scorer drains it with zero loss"
hdr "AI-assisted QA"
row "[ OK ]" "Drift alarm" "fires when XGBoost and Groq disagree on more than 5% of events (live in 3.6)"
row "[ OK ]" "AI grades AI" "a second Gemini call rejects narratives not supported by SHAP; it caught a fabricated one"
row "[ OK ]" "AI-designed load" "Gemini designed 3 traffic shapes for k6: flash-sale spike, slow-leak DDoS, mixed-currency surge"
hdr "Independent audit - Evidently, 16 reports"
row "[ OK ]" "Model" "ROC-AUC 0.956 on 118,108 held-out transactions; 0.889 out-of-time"
row "[ OK ]" "Data" "training features rebuilt independently and matched exactly"
row "[ OK ]" "Pipeline" "0 duplicates; p50 31 / p95 63 / p99 125 ms on 4,692 events (earlier run, Jul-Aug 2026)"
echo
echo "  Sources: cloud deployment runbook, target audit, data-quality report, resilience matrix,"
echo "  AI-assisted QA report and the Evidently summary."
''',
    },
    {
        "id": "tests_results", "section": "act5", "num": "5.8", "title": "Full test suite – results of the 122 tests started in 1.0",
        "purpose": "The result of the complete automated test suite that has been running since the start of the demo: every test file and its outcome.",
        "built": [
            "58 unit tests: decisions, rate limiter, failover, data quality, feedback, AI load patterns, Avro codecs",
            "64 integration tests: scoring API, champion model, Redis, PostgreSQL and Kafka end-to-end scenarios",
            "Run on this laptop against a local copy of the services, so no test record reaches the live system",
        ],
        "kind": "local", "local": "tests_results", "timeout": 30,
        "say": "The 122 tests that started at the beginning of the demo have finished: every file, every result, run live today.",
        "caution": "If it says 'Still running', run it again a minute later. Coverage (80.05%) is a recorded figure - do not run coverage live.",
    },

    # ------------------------------------------------------------------ RECOVERY
    {
        "id": "tmux", "section": "recovery", "num": "R1", "title": "Live program view (tmux)",
        "purpose": "Opens a terminal on the server showing the 9 pipeline programs live, one tab each.",
        "built": [
            "Ctrl+b then a number switches tab; Ctrl+b then d leaves",
            "Never press Ctrl+C there - it stops that program",
        ],
        "kind": "local", "local": "tmux",
        "say": "Opens a terminal attached to the tmux session 'vf' on the server (Ctrl+b then a number switches tab).",
        "caution": "Leave with Ctrl+b then d. Never press Ctrl+C there - it stops the program in that tab.",
    },
    {
        "id": "groq_stop", "section": "recovery", "num": "R2", "title": "Stop the Groq second opinion",
        "purpose": "Stops the LLM immediately to protect the free budget; decisions are unaffected.",
        "built": [
            "Same stop as 3.3, without the 15-second proof",
        ],
        "kind": "control", "timeout": 60,
        "say": "Stops Groq to protect the remaining free daily budget. The XGBoost decision path is unaffected.",
        "script": GROQ_HELPERS + r'''if ! running groq; then echo "  Groq is not running - nothing to stop."; groq_cleanup; exit 0; fi
groq_stop || { echo "[FAIL] Groq did not stop within 20 s"; exit 1; }
echo "  [ OK ] Groq second opinion stopped - the remaining daily budget is preserved."
groq_cleanup
''',
    },
    {
        "id": "restart_api", "section": "recovery", "num": "R3", "title": "Restart the scoring API",
        "purpose": "Restarts the REST API if POST /score stops answering (about 15 seconds).",
        "built": [
            "Use when the header shows 'Scoring API offline', or P1 says 'api: stopped'",
            "First frees port 8000 if an old API process from before a restart still holds it ('Address already in use')",
        ],
        "kind": "control", "timeout": 90, "confirm": "Restart the scoring API? /score is unavailable for about 15 seconds.",
        "script": r'''port_pids() { ss -ltnpH "sport = :8000" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u | tr '\n' ' '; }
P=$(port_pids)
if [ -n "$P" ] && ! running api; then
  echo "  Port 8000 is held by an old API process outside the pipeline (pid $P) - stopping it"
  kill $P 2>/dev/null
  for i in $(seq 1 10); do [ -z "$(port_pids)" ] && break; sleep 1; done
  P=$(port_pids); [ -n "$P" ] && { kill -9 $P 2>/dev/null; sleep 1; }
  [ -z "$(port_pids)" ] && echo "  [ OK ] Port 8000 is free" || { echo "[FAIL] Port 8000 is still held - use R9"; exit 1; }
fi
''' + _restart("api", "$T OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 uv run uvicorn velocityfraud.api:app --host 0.0.0.0 --port 8000 --workers 2", "the scoring API"),
    },
    {
        "id": "restart_slowpath", "section": "recovery", "num": "R4", "title": "Restart the slow path",
        "purpose": "Restarts the SHAP explanation service if new flagged events stop getting explanations.",
        "built": [
            "Use when 2.3 shows no new enriched events",
        ],
        "kind": "control", "timeout": 90, "confirm": "Restart the slow-path enricher?",
        "script": _restart("slowpath", "NARRATOR_MODE=template uv run python -m velocityfraud.slow_path", "the slow-path enricher"),
    },
    {
        "id": "restart_text", "section": "recovery", "num": "R5", "title": "Restart the text-anomaly scorer",
        "purpose": "Restarts DistilBERT if text checks stay 'pending'.",
        "built": [
            "Use when 2.4 shows no recent text checks",
        ],
        "kind": "control", "timeout": 90, "confirm": "Restart the DistilBERT text-anomaly scorer?",
        "script": _restart("text", "TEXT_BATCH_SIZE=1000 TEXT_FLUSH_SEC=10 uv run python -m velocityfraud.text_anomaly_consumer", "the text-anomaly scorer"),
    },
    {
        "id": "restart_sink", "section": "recovery", "num": "R6", "title": "Restart the PostgreSQL sink",
        "purpose": "Restarts the Kafka-to-database writer if new rows stop appearing.",
        "built": [
            "Use when P1 reports no events scored in the last 3 minutes",
        ],
        "kind": "control", "timeout": 90, "confirm": "Restart the Kafka-to-PostgreSQL sink?",
        "script": _restart("sink", "SINK_FLUSH_SEC=0.5 uv run python -m velocityfraud.sink", "the PostgreSQL sink"),
    },
    {
        "id": "restart_replayer", "section": "recovery", "num": "R7", "title": "Restart the transaction replayer",
        "purpose": "Restarts the live transaction feed if no new events arrive.",
        "built": [
            "Use when 1.2 shows +0 messages on transactions.raw",
        ],
        "kind": "control", "timeout": 90, "confirm": "Restart the transaction replayer?",
        "script": _restart("replayer", "REPLAYER_TPS=2 uv run python -m velocityfraud.replayer", "the transaction replayer"),
    },
    {
        "id": "restart_ops", "section": "recovery", "num": "R8", "title": "Restart the ops metrics collector",
        "purpose": "Restarts the monitor if P1 says the ops metrics are old.",
        "built": [
            "Use when P1 warns 'Ops metrics are ...s old'",
        ],
        "kind": "control", "timeout": 90, "confirm": "Restart the ops metrics collector?",
        "script": _restart("ops", "while true; do uv run python -m velocityfraud.ops_metrics poll; sleep 30; done", "the ops metrics collector"),
    },
    {
        "id": "full_restart", "section": "recovery", "num": "R9", "title": "Full pipeline restart",
        "purpose": "Restarts all 9 programs and re-applies the schema registry. Groq stays OFF, so it uses no Groq or Gemini calls.",
        "built": [
            "About 90 seconds, then wait 3 minutes and run P1",
            "Containers and stored data are kept",
        ],
        "kind": "control", "timeout": 300,
        "confirm": "Restart the WHOLE pipeline? All nine programs stop and start again (about 90 seconds). Groq will be OFF afterwards.",
        "caution": "Last resort. After it finishes, wait 3 minutes and run the readiness check (P1).",
        "script": REGISTRY_HELPERS + r'''echo "  Stopping pipeline programs"
~/vf-stop.sh
echo "  Starting containers and all programs (about 90 s)"
~/vf-start.sh 2>&1
echo "  Re-applying the schema registry setup (Apicurio keeps it in memory)"
if registry_wait; then registry setup || echo "[WARN] Registry setup incomplete - run R10"; else echo "[WARN] Schema registry not answering yet - run R10 in a minute"; fi
echo "  [ OK ] Restart complete. Groq is OFF (it runs only in Act 3). Wait 3 minutes, then run P1."
''',
    },
    {
        "id": "registry_setup", "section": "recovery", "num": "R10", "title": "Re-apply schema registry setup",
        "purpose": "Re-registers the 5 Avro schemas and the BACKWARD rule if the registry forgot them.",
        "built": [
            "Use when P1 warns about the schema registry",
        ],
        "kind": "control", "timeout": 90,
        "say": "Sets BACKWARD compatibility and registers the 5 Avro subjects from the schema files in Git. Safe to run any time (registering an identical schema is a no-op).",
        "caution": "Needed only if P1 warns about the registry - Apicurio's in-memory edition forgets its rules when its container restarts.",
        "script": REGISTRY_HELPERS + r'''registry_wait || { echo "[FAIL] Schema registry (Apicurio) is not answering on port 8080"; exit 1; }
registry setup
''',
    },

    # ------------------------------------------------------------------ HIDDEN
    {
        "id": "connect", "section": None, "num": "", "title": "Test the connection",
        "kind": "read", "timeout": 30,
        "script": r'''echo "  [ OK ] Connected to $(hostname) - $(date -u '+%H:%M:%S') UTC - $(uptime -p)"
tmux has-session -t vf 2>/dev/null && echo "  [ OK ] Pipeline session 'vf' found" || echo "  [WARN] Pipeline session 'vf' not running yet (run ~/vf-start.sh or R9)"
''',
    },
]

NOTES = [
    ("Demo thresholds", "Live stream uses REVIEW >= 0.10 / BLOCK >= 0.18 (documented in LAYER_3_FAST_PATH_SCORING.md) because only ~33% of the 43 model features exist on a live event. Production thresholds are 0.50 / 0.85. Say it openly in Act 1."),
    ("Decision path", "XGBoost is the decision path (p95 56.69 ms certified). Groq is a parallel second opinion (about 120-170 ms per call in the 5 Nov check; 1.6-2.7 s in earlier weeks) - quote the live groq_ms column, never call Groq the fast path."),
    ("Kafka UI", "Its Dashboard shows Production/Consumption '0 Bytes' (no JMX metrics). Show Topics > transactions.raw > Messages instead."),
    ("MLflow", "Experiment fraud-detection has 5 runs: 3 finished (green tick), 2 early July attempts marked failed (red cross). Point at the finished xgboost_v1 and random_forest_v1."),
    ("Groq budget", "Free tier 200,000 tokens/day (~400 calls). Groq runs only in Act 3: 3.1 starts it (12 calls/min); go straight on to 3.2 and 3.3 (~15-20 calls). If 3.3 is missed, Groq stops by itself after 3 minutes (~36 calls). P4 is a 1-2 call connection check that stops itself. A 429 means the budget is used: calls are skipped, scoring is unaffected."),
    ("Groq is not the fallback", "XGBoost makes every decision all the time; Groq is a parallel second opinion that can stop at any moment (step 3.3 proves scoring continues). Do not say XGBoost 'takes over' from Groq."),
    ("Gemini budget", "Free tier 20 requests/day. Step 2.5 uses ~3. Live slow-path narratives use the template (1.5 s budget)."),
    ("Power BI", "Refresh with Optimize > Refresh visuals only. Home > Refresh also reloads the archived Databricks table and fails on the free plan."),
    ("Failover", "Step 3.4 stops whichever scorer holds the lock; always follow with 3.5. In the live program view never press Ctrl+C."),
    ("Text check", "DistilBERT scores merchant_name only. A few newest rows can show 'pending' for ~10 s (sink/text timing)."),
    ("Accuracy", "F1 0.46 / FPR 6.56% at 0.5 (REVIEW routes to a human). Proposal target F1 >= 0.92 is above the measured ceiling 0.67. ROC-AUC 0.956."),
    ("Appeal", "The analyst's final decision is the binding outcome; re-scoring the same features gives the same model score."),
    ("Load tests", "5.4 (k6) and 5.5 (Locust) run on the separate load server, as in week 15. Quote latency from k6 (fixed rate) and throughput / failures from Locust (full capacity). Delete the load server after the demo."),
]

KINDS = {
    "read": "Read-only",
    "action": "Writes demo data",
    "quota": "Uses API quota",
    "control": "Controls services",
    "local": "On this laptop",
    "load": "Sends test load",
}

HOSTS = {None, "loadgen"}


def compose(step: dict, target: str = "") -> str:
    """Full remote script for a step: shared prelude (+ pipeline guard) + the step body.

    Load-server steps get their own prelude, with TARGET set to the demo server's IP."""
    if step.get("host") == "loadgen":
        return f'TARGET="{target}"\n' + LOADGEN_PRELUDE + "\n" + step["script"]
    guard = "need_stack\n" if (step.get("section") in NEEDS_STACK_SECTIONS or step["id"] in NEEDS_STACK_IDS) else ""
    return PRELUDE + "\n" + guard + step["script"]


def by_id() -> dict:
    return {s["id"]: s for s in STEPS}


def validate() -> list[str]:
    """Static checks on the catalogue; returns a list of problems (empty = valid)."""
    problems = []
    seen = set()
    section_ids = {s["id"] for s in SECTIONS}
    for s in STEPS:
        sid = s.get("id")
        if not sid or sid in seen:
            problems.append(f"duplicate or empty id: {sid!r}")
        seen.add(sid)
        if s.get("section") is not None and s["section"] not in section_ids:
            problems.append(f"{sid}: unknown section {s['section']!r}")
        if s.get("kind") not in KINDS:
            problems.append(f"{sid}: unknown kind {s.get('kind')!r}")
        if s.get("host") not in HOSTS:
            problems.append(f"{sid}: unknown host {s.get('host')!r}")
        if s.get("host") == "loadgen" and s.get("kind") == "local":
            problems.append(f"{sid}: a load-server step cannot be local")
        if s.get("section") is not None and not (s.get("purpose") and s.get("built")):
            problems.append(f"{sid}: missing purpose or built")
        if s.get("kind") == "local":
            if s.get("local") not in {"tunnel", "powerbi", "tmux", "tests_start", "tests_results"}:
                problems.append(f"{sid}: unknown local action {s.get('local')!r}")
        else:
            if not s.get("script"):
                problems.append(f"{sid}: remote step without a script")
            if "docker exec -it" in s.get("script", "") or "docker exec -i " in s.get("script", ""):
                problems.append(f"{sid}: interactive docker exec would consume script stdin")
        for k in s.get("links", []):
            if k not in LINKS:
                problems.append(f"{sid}: unknown link {k!r}")
    return problems

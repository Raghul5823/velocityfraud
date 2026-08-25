# Chaos / resilience test (Wk 13) - fault injection + graceful degradation.
#
# Scenario 1: Redis (Layer-8 blocklist) dies  -> pipeline fails OPEN, still scores.
# Scenario 2: Kafka broker dies               -> real-time fast-path decisions
#             continue (the API / scoring path has no Kafka dependency; only the
#             async streaming + analytics pause and resume on reconnect).
#
# Groq and Databricks are non-critical async paths (second-opinion LLM + slow-path
# enrichment). Their outage never blocks the primary decision - see docs/resilience.md.
#
# Run from the velocityfraud root:  .\scripts\chaos-test.ps1
# (Redis and Kafka are stopped and restarted; Postgres is untouched.)

# "Continue" (not "Stop"): the Python probe logs to stderr (loguru); PS 5.1 with
# ErrorAction=Stop would treat that native stderr as a terminating error.
$ErrorActionPreference = "Continue"
$root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $root
$py = ".\.venv\Scripts\python.exe"

function Probe($label) {
    Write-Host ("[{0}]" -f $label) -ForegroundColor Cyan
    & $py -m velocityfraud.chaos | Out-Host   # stdout to console, not the return value
    return $LASTEXITCODE
}

function Wait-Container($name, $pingCmd) {
    for ($i = 0; $i -lt 25; $i++) {
        Start-Sleep -Seconds 1
        $r = & docker exec $name $pingCmd 2>$null
        if ($LASTEXITCODE -eq 0) { return $true }
    }
    return $false
}

Write-Host "==================================================================" -ForegroundColor Magenta
Write-Host " CHAOS / RESILIENCE TEST - fault injection + graceful degradation" -ForegroundColor Magenta
Write-Host "==================================================================" -ForegroundColor Magenta

# ---------------- Scenario 1: Redis outage ----------------
Write-Host "`n### Scenario 1: Redis (blocklist) outage ###" -ForegroundColor Magenta
Write-Host "[1a] Baseline (Redis UP):" -ForegroundColor Yellow
$null = Probe "baseline"
Write-Host "`n[1b] Stopping vf-redis ..." -ForegroundColor Red
docker stop vf-redis | Out-Null; Start-Sleep -Seconds 2
Write-Host "[1c] Scoring with Redis DOWN (expect fail-open):" -ForegroundColor Yellow
$rcRedisDown = Probe "redis-down"
Write-Host "`n[1d] Restarting vf-redis ..." -ForegroundColor Green
docker start vf-redis | Out-Null
$null = Wait-Container "vf-redis" "redis-cli ping"

# ---------------- Scenario 2: Kafka broker outage ----------------
Write-Host "`n### Scenario 2: Kafka broker outage ###" -ForegroundColor Magenta
Write-Host "[2a] Stopping vf-kafka ..." -ForegroundColor Red
docker stop vf-kafka | Out-Null; Start-Sleep -Seconds 2
Write-Host "[2b] Scoring with Kafka DOWN (fast path must be Kafka-independent):" -ForegroundColor Yellow
$rcKafkaDown = Probe "kafka-down"
Write-Host "`n[2c] Restarting vf-kafka ..." -ForegroundColor Green
docker start vf-kafka | Out-Null
$kafkaBack = Wait-Container "vf-kafka" "/opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server localhost:9092"
Write-Host ("      Kafka back: {0}" -f $kafkaBack) -ForegroundColor DarkGray

# ---------------- Summary ----------------
Write-Host "`n------------------------------------------------------------------" -ForegroundColor Green
$s1 = ($rcRedisDown -eq 0)
$s2 = ($rcKafkaDown -eq 0)
Write-Host (" [{0}] Redis outage  -> fail-open, decision still produced" -f $(if ($s1) {"PASS"} else {"FAIL"})) -ForegroundColor $(if ($s1) {"Green"} else {"Red"})
Write-Host (" [{0}] Kafka outage  -> fast-path decision still produced (decoupled)" -f $(if ($s2) {"PASS"} else {"FAIL"})) -ForegroundColor $(if ($s2) {"Green"} else {"Red"})
Write-Host "------------------------------------------------------------------" -ForegroundColor Green
if ($s1 -and $s2) {
    Write-Host " RESULT: PASS - graceful degradation under Redis and Kafka outages." -ForegroundColor Green
} else {
    Write-Host " RESULT: FAIL - see failed scenario(s) above." -ForegroundColor Red
}
Write-Host "------------------------------------------------------------------" -ForegroundColor Green

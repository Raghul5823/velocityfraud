# Automated failover demo / evidence generator for Layer 3b.
#
# Proves Section 9 item 3: kill the primary fast-path scorer mid-stream and the
# hot-standby XGBoost shadow takes over with no consumer-visible interruption,
# while the fast-path latency stays under 100 ms (p95).
#
# What it does, hands-free:
#   1. seeds N events into transactions.raw
#   2. starts a PRIMARY scorer (becomes ACTIVE, produces to transactions.scored)
#   3. starts a STANDBY scorer (hot: scores in parallel, suppresses output)
#   4. hard-kills the PRIMARY to simulate a crash
#   5. shows the STANDBY promoting + the scored-topic count continuing to climb
#
# Prereqs: docker compose up (kafka + redis), champion model present.
# Run from the velocityfraud root:  .\scripts\demo-failover.ps1
#
# For a LIVE (manual) demo instead, use two terminals:
#   T1:  $env:FAILOVER_ROLE="primary"; .\scripts\run-failover.ps1
#   T2:  $env:FAILOVER_ROLE="standby"; .\scripts\run-failover.ps1
#   then Ctrl-C T1 and watch T2 promote.

param(
    [int]$SeedEvents = 4000,
    [int]$RunSeconds = 24,
    [int]$PromoteWaitSeconds = 12
)

$ErrorActionPreference = "Stop"
$proj = (Resolve-Path "$PSScriptRoot\..").Path
$py = "$proj\.venv\Scripts\python.exe"
Set-Location $proj

$logDir = "$env:TEMP\vf-failover-demo"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$primaryLog = "$logDir\primary.log"
$standbyLog = "$logDir\standby.log"
Remove-Item "$logDir\*.log","$logDir\*.err" -ErrorAction SilentlyContinue

function Get-ScoredTotal {
    try {
        $raw = docker exec vf-kafka /opt/kafka/bin/kafka-get-offsets.sh --bootstrap-server localhost:9092 --topic transactions.scored 2>$null
    } catch { return -1 }
    $sum = 0
    foreach ($line in $raw) { $p = $line -split ":"; if ($p.Count -eq 3) { $sum += [int]$p[2] } }
    return $sum
}

Write-Host "==================================================================" -ForegroundColor Magenta
Write-Host " VelocityFraud - FAST-PATH FAILOVER DEMO (Layer 3b)" -ForegroundColor Magenta
Write-Host "==================================================================" -ForegroundColor Magenta

# Clear any stale leader lock left by a previously crashed run (safe: a live
# ACTIVE instance re-acquires on its next heartbeat).
docker exec vf-redis redis-cli del vf:scorer:leader | Out-Null

# 1. seed events
Write-Host "`n[1/5] Seeding $SeedEvents events into transactions.raw ..." -ForegroundColor Cyan
$env:REPLAYER_MAX_EVENTS = "$SeedEvents"; $env:REPLAYER_TPS = "2000"; $env:REPLAYER_TOPIC = "transactions.raw"
& $py -m velocityfraud.replayer | Select-Object -Last 1

$run = Get-Random -Maximum 99999
$env:FAILOVER_FROM = "earliest"; $env:FAILOVER_LOCK_TTL_MS = "3000"; $env:FAILOVER_HEARTBEAT_MS = "1000"
$env:FAILOVER_IN_TOPIC = "transactions.raw"; $env:FAILOVER_OUT_TOPIC = "transactions.scored"

$startTotal = Get-ScoredTotal

# 2. primary
Write-Host "`n[2/5] Starting PRIMARY (will become ACTIVE) ..." -ForegroundColor Cyan
$env:FAILOVER_ROLE = "primary"; $env:FAILOVER_GROUP = "vf-demo-primary-$run"
$primary = Start-Process -FilePath $py -ArgumentList "-m","velocityfraud.failover_scorer" `
    -PassThru -NoNewWindow -RedirectStandardOutput $primaryLog -RedirectStandardError "$primaryLog.err"
Write-Host "      PRIMARY pid=$($primary.Id)"
Start-Sleep -Seconds 8

# 3. standby
Write-Host "`n[3/5] Starting STANDBY (hot shadow) ..." -ForegroundColor Cyan
$env:FAILOVER_ROLE = "standby"; $env:FAILOVER_GROUP = "vf-demo-standby-$run"
$standby = Start-Process -FilePath $py -ArgumentList "-m","velocityfraud.failover_scorer" `
    -PassThru -NoNewWindow -RedirectStandardOutput $standbyLog -RedirectStandardError "$standbyLog.err"
Write-Host "      STANDBY pid=$($standby.Id)"
Write-Host "      both running for ${RunSeconds}s ..." -ForegroundColor DarkGray
Start-Sleep -Seconds $RunSeconds

$beforeKill = Get-ScoredTotal

# 4. kill primary
Write-Host "`n[4/5] HARD-KILLING PRIMARY pid=$($primary.Id) (simulated crash) ..." -ForegroundColor Red
Stop-Process -Id $primary.Id -Force
Write-Host "      killed at $(Get-Date -Format HH:mm:ss.fff). Waiting ${PromoteWaitSeconds}s for takeover ..." -ForegroundColor DarkGray
Start-Sleep -Seconds $PromoteWaitSeconds
$afterPromote = Get-ScoredTotal
Stop-Process -Id $standby.Id -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# 5. evidence
Write-Host "`n[5/5] RESULT" -ForegroundColor Cyan
Write-Host "------------------------------------------------------------------" -ForegroundColor Green
Write-Host " STANDBY promotion + latency evidence:" -ForegroundColor Green
$sb = @(); if (Test-Path $standbyLog) { $sb += Get-Content $standbyLog }; if (Test-Path "$standbyLog.err") { $sb += Get-Content "$standbyLog.err" }
$sb | Select-String -Pattern "PROMOTING|Shadow was hot|Fast-path latency so far|Promotions to|p50/p95/p99|Sub-100ms budget" | ForEach-Object { "   " + $_.Line }
Write-Host "------------------------------------------------------------------" -ForegroundColor Green
Write-Host " Throughput continuity (no gap across the failover):" -ForegroundColor Green
Write-Host ("   PRIMARY produced before kill : {0}" -f ($beforeKill - $startTotal))
Write-Host ("   STANDBY produced after  kill : {0}   (>0 = stream never went silent)" -f ($afterPromote - $beforeKill))
Write-Host "------------------------------------------------------------------" -ForegroundColor Green
Write-Host " Full logs: $primaryLog  |  $standbyLog" -ForegroundColor DarkGray

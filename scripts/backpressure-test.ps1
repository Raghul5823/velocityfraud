# Backpressure / graceful-degradation test (Wk 13).
#
# Proves the pipeline degrades gracefully under a load spike: we burst-produce
# far faster than the scorer consumes, so a large backlog (consumer lag) builds
# in Kafka. The scorer then drains it at its own pace with ZERO data loss - Kafka
# buffers the surge instead of the system dropping events or crashing.
#
# Run from the velocityfraud root:  .\scripts\backpressure-test.ps1

$ErrorActionPreference = "Continue"
$root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $root
$py = ".\.venv\Scripts\python.exe"

$N = 3000
$run = Get-Random -Maximum 99999
$raw = "bp.raw.$run"
$scored = "bp.scored.$run"

function Get-Total($topic) {
    $raw = docker exec vf-kafka /opt/kafka/bin/kafka-get-offsets.sh --bootstrap-server localhost:9092 --topic $topic 2>$null
    $sum = 0
    foreach ($line in $raw) { $p = $line -split ":"; if ($p.Count -eq 3) { $sum += [int]$p[2] } }
    return $sum
}

Write-Host "==================================================================" -ForegroundColor Magenta
Write-Host " BACKPRESSURE TEST - burst-produce $N, drain with no loss" -ForegroundColor Magenta
Write-Host "==================================================================" -ForegroundColor Magenta

foreach ($t in $raw, $scored) {
    docker exec vf-kafka /opt/kafka/bin/kafka-topics.sh --create --if-not-exists --topic $t `
        --bootstrap-server localhost:9092 --partitions 3 --replication-factor 1 2>$null | Out-Null
}

Write-Host "`n[1/3] Burst-producing $N events as fast as possible ..." -ForegroundColor Yellow
$env:REPLAYER_MAX_EVENTS = "$N"; $env:REPLAYER_TPS = "10000"; $env:REPLAYER_TOPIC = $raw
& $py -m velocityfraud.replayer | Out-Host

$backlog = Get-Total $raw
Write-Host ("`n[2/3] Backlog now waiting in Kafka (consumer lag): {0} events" -f $backlog) -ForegroundColor Cyan

Write-Host "`n[3/3] Draining with the scorer (processes at its own rate) ..." -ForegroundColor Yellow
$env:SCORER_MAX_EVENTS = "$N"; $env:SCORER_IN_TOPIC = $raw; $env:SCORER_OUT_TOPIC = $scored
$env:SCORER_FROM = "earliest"; $env:SCORER_GROUP = "bp-$run"
& $py -m velocityfraud.scorer | Out-Host

$drained = Get-Total $scored

Write-Host "`n------------------------------------------------------------------" -ForegroundColor Green
Write-Host (" Produced (surge)   : {0}" -f $backlog)
Write-Host (" Scored (drained)   : {0}" -f $drained)
Write-Host (" Lost               : {0}" -f ($backlog - $drained))
if ($drained -ge $N) {
    Write-Host " RESULT: PASS - full backlog drained, ZERO loss (backpressure handled)." -ForegroundColor Green
} else {
    Write-Host " RESULT: FAIL - some events were not scored." -ForegroundColor Red
}
Write-Host "------------------------------------------------------------------" -ForegroundColor Green

# cleanup temp topics
foreach ($t in $raw, $scored) {
    docker exec vf-kafka /opt/kafka/bin/kafka-topics.sh --delete --topic $t --bootstrap-server localhost:9092 2>$null | Out-Null
}

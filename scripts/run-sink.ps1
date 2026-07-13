# Convenience launcher for the Kafka -> Postgres sink (Layer 6).
# Run from the velocityfraud root: .\scripts\run-sink.ps1
#
# Tweak via env vars:
#   $env:SINK_MAX_EVENTS = "100";   .\scripts\run-sink.ps1   # stop after 100 events
#   $env:SINK_GROUP      = "demo";  .\scripts\run-sink.ps1   # fresh offset
#   $env:SINK_BATCH_SIZE = "10";    .\scripts\run-sink.ps1   # smaller batches

$ErrorActionPreference = "Stop"

if (-not $env:SINK_MAX_EVENTS) { $env:SINK_MAX_EVENTS = "0" }
if (-not $env:SINK_FROM)       { $env:SINK_FROM = "earliest" }
if (-not $env:SINK_GROUP)      { $env:SINK_GROUP = "velocityfraud-sink-dev" }
if (-not $env:SINK_BATCH_SIZE) { $env:SINK_BATCH_SIZE = "50" }
if (-not $env:SINK_FLUSH_SEC)  { $env:SINK_FLUSH_SEC = "2.0" }

Write-Host "Sink config:" -ForegroundColor Cyan
Write-Host "  Topics:        transactions.scored, transactions.enriched"
Write-Host "  Postgres:      localhost:5432 / velocityfraud"
Write-Host "  Max events:    $env:SINK_MAX_EVENTS (0 = unlimited, Ctrl-C to stop)"
Write-Host "  From offset:   $env:SINK_FROM"
Write-Host "  Group:         $env:SINK_GROUP"
Write-Host "  Batch:         $env:SINK_BATCH_SIZE rows / $env:SINK_FLUSH_SEC sec"
Write-Host ""

uv run python -m velocityfraud.sink

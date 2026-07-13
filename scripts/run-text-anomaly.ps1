# Convenience launcher for the text anomaly consumer (Layer 5).
# Run from the velocityfraud root: .\scripts\run-text-anomaly.ps1
#
# Tweak via env vars:
#   $env:TEXT_MAX_EVENTS = "30";     .\scripts\run-text-anomaly.ps1   # stop after 30
#   $env:TEXT_GROUP      = "demo";   .\scripts\run-text-anomaly.ps1   # fresh offsets
#   $env:TEXT_SUSPICIOUS_THRESHOLD = "4.5"; .\scripts\run-text-anomaly.ps1  # sensitive

$ErrorActionPreference = "Stop"

if (-not $env:TEXT_MAX_EVENTS) { $env:TEXT_MAX_EVENTS = "0" }
if (-not $env:TEXT_FROM)       { $env:TEXT_FROM = "earliest" }
if (-not $env:TEXT_IN_TOPIC)   { $env:TEXT_IN_TOPIC = "transactions.enriched" }
if (-not $env:TEXT_GROUP)      { $env:TEXT_GROUP = "velocityfraud-text-anomaly-dev" }
if (-not $env:TEXT_BATCH_SIZE) { $env:TEXT_BATCH_SIZE = "8" }
if (-not $env:TEXT_FLUSH_SEC)  { $env:TEXT_FLUSH_SEC = "2.0" }

$threshold = if ($env:TEXT_SUSPICIOUS_THRESHOLD) { $env:TEXT_SUSPICIOUS_THRESHOLD } else { "6.0 (default)" }

Write-Host "Text Anomaly Consumer config:" -ForegroundColor Cyan
Write-Host "  In topic:        $env:TEXT_IN_TOPIC"
Write-Host "  Postgres:        localhost:5432 / velocityfraud.enriched_events"
Write-Host "  Max events:      $env:TEXT_MAX_EVENTS (0 = unlimited, Ctrl-C to stop)"
Write-Host "  From offset:     $env:TEXT_FROM"
Write-Host "  Group:           $env:TEXT_GROUP"
Write-Host "  Batch:           $env:TEXT_BATCH_SIZE rows / $env:TEXT_FLUSH_SEC sec"
Write-Host "  Threshold:       $threshold"
Write-Host ""

uv run python -m velocityfraud.text_anomaly_consumer

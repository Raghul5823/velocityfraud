# Convenience launcher for the IEEE-CIS replayer.
# Run from the velocityfraud root: .\scripts\run-replayer.ps1
#
# Tweak rate via env: $env:REPLAYER_TPS=100; .\scripts\run-replayer.ps1
# Cap events via env: $env:REPLAYER_MAX_EVENTS=500; .\scripts\run-replayer.ps1

$ErrorActionPreference = "Stop"

if (-not $env:REPLAYER_TPS)        { $env:REPLAYER_TPS = "10" }
if (-not $env:REPLAYER_MAX_EVENTS) { $env:REPLAYER_MAX_EVENTS = "0" }
if (-not $env:REPLAYER_TOPIC)      { $env:REPLAYER_TOPIC = "transactions.raw" }

Write-Host "Replayer config:" -ForegroundColor Cyan
Write-Host "  TPS:        $env:REPLAYER_TPS"
Write-Host "  Max events: $env:REPLAYER_MAX_EVENTS (0 = all)"
Write-Host "  Topic:      $env:REPLAYER_TOPIC"
Write-Host ""

uv run python -m velocityfraud.replayer

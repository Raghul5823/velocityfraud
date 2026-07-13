# Convenience launcher for the fast-path scorer (Layer 3).
# Run from the velocityfraud root: .\scripts\run-scorer.ps1
#
# Tweak via env vars:
#   $env:SCORER_MAX_EVENTS = "100";   .\scripts\run-scorer.ps1   # stop after 100 events
#   $env:SCORER_FROM       = "latest";.\scripts\run-scorer.ps1   # only score NEW events
#   $env:SCORER_GROUP      = "demo";  .\scripts\run-scorer.ps1   # fresh offset tracking
#   $env:SCORER_REVIEW_THRESH = "0.40"; .\scripts\run-scorer.ps1 # more aggressive review

$ErrorActionPreference = "Stop"

if (-not $env:SCORER_MAX_EVENTS)    { $env:SCORER_MAX_EVENTS = "0" }
if (-not $env:SCORER_FROM)          { $env:SCORER_FROM = "earliest" }
if (-not $env:SCORER_IN_TOPIC)      { $env:SCORER_IN_TOPIC = "transactions.raw" }
if (-not $env:SCORER_OUT_TOPIC)     { $env:SCORER_OUT_TOPIC = "transactions.scored" }
if (-not $env:SCORER_GROUP)         { $env:SCORER_GROUP = "velocityfraud-scorer-dev" }
if (-not $env:SCORER_REVIEW_THRESH) { $env:SCORER_REVIEW_THRESH = "0.50" }
if (-not $env:SCORER_BLOCK_THRESH)  { $env:SCORER_BLOCK_THRESH = "0.85" }

Write-Host "Scorer config:" -ForegroundColor Cyan
Write-Host "  In topic:    $env:SCORER_IN_TOPIC"
Write-Host "  Out topic:   $env:SCORER_OUT_TOPIC"
Write-Host "  Max events:  $env:SCORER_MAX_EVENTS (0 = unlimited, Ctrl-C to stop)"
Write-Host "  From offset: $env:SCORER_FROM"
Write-Host "  Group:       $env:SCORER_GROUP"
Write-Host "  Thresholds:  ALLOW < $env:SCORER_REVIEW_THRESH <= REVIEW < $env:SCORER_BLOCK_THRESH <= BLOCK"
Write-Host ""

uv run python -m velocityfraud.scorer

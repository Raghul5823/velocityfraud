# Convenience launcher for the slow-path enricher (Layer 4).
# Run from the velocityfraud root: .\scripts\run-slow-path.ps1
#
# Tweak via env vars:
#   $env:SLOWPATH_MAX_EVENTS = "10";          .\scripts\run-slow-path.ps1
#   $env:NARRATOR_MODE       = "template";    .\scripts\run-slow-path.ps1
#   $env:GEMINI_API_KEY      = "<key>";       .\scripts\run-slow-path.ps1
#   $env:SLOWPATH_GROUP      = "demo-fresh";  .\scripts\run-slow-path.ps1

$ErrorActionPreference = "Stop"

if (-not $env:SLOWPATH_MAX_EVENTS) { $env:SLOWPATH_MAX_EVENTS = "0" }
if (-not $env:SLOWPATH_FROM)       { $env:SLOWPATH_FROM = "earliest" }
if (-not $env:SLOWPATH_IN_TOPIC)   { $env:SLOWPATH_IN_TOPIC = "transactions.scored" }
if (-not $env:SLOWPATH_OUT_TOPIC)  { $env:SLOWPATH_OUT_TOPIC = "transactions.enriched" }
if (-not $env:SLOWPATH_GROUP)      { $env:SLOWPATH_GROUP = "velocityfraud-slowpath-dev" }
if (-not $env:NARRATOR_MODE)       { $env:NARRATOR_MODE = "auto" }

$geminiStatus = if ($env:GEMINI_API_KEY) { "ENABLED" } else { "disabled (template only)" }

Write-Host "Slow-Path config:" -ForegroundColor Cyan
Write-Host "  In topic:      $env:SLOWPATH_IN_TOPIC"
Write-Host "  Out topic:     $env:SLOWPATH_OUT_TOPIC"
Write-Host "  Max events:    $env:SLOWPATH_MAX_EVENTS (0 = unlimited)"
Write-Host "  From offset:   $env:SLOWPATH_FROM"
Write-Host "  Group:         $env:SLOWPATH_GROUP"
Write-Host "  Narrator mode: $env:NARRATOR_MODE"
Write-Host "  Gemini:        $geminiStatus"
Write-Host ""

uv run python -m velocityfraud.slow_path

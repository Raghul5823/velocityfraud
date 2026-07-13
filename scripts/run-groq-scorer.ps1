# Convenience launcher for the Groq LLM scoring path (Layer 5b).
# Run from the velocityfraud root: .\scripts\run-groq-scorer.ps1
#
# Tweak via env vars:
#   $env:GROQ_SCORER_MAX_EVENTS = "50";   .\scripts\run-groq-scorer.ps1   # stop after 50 events
#   $env:GROQ_SCORER_FROM = "latest";     .\scripts\run-groq-scorer.ps1   # only score NEW events
#   $env:GROQ_MODEL = "llama-3.3-70b-versatile"; .\scripts\run-groq-scorer.ps1
#
# NOTE: GROQ_API_KEY must be set in .env (or exported in this session).

$ErrorActionPreference = "Stop"

if (-not $env:GROQ_SCORER_MAX_EVENTS) { $env:GROQ_SCORER_MAX_EVENTS = "0" }
if (-not $env:GROQ_SCORER_FROM)       { $env:GROQ_SCORER_FROM = "earliest" }
if (-not $env:GROQ_SCORER_IN_TOPIC)   { $env:GROQ_SCORER_IN_TOPIC = "transactions.raw" }
if (-not $env:GROQ_SCORER_OUT_TOPIC)  { $env:GROQ_SCORER_OUT_TOPIC = "transactions.scored.groq" }
if (-not $env:GROQ_SCORER_GROUP)      { $env:GROQ_SCORER_GROUP = "velocityfraud-groq-scorer-dev" }
if (-not $env:GROQ_MODEL)             { $env:GROQ_MODEL = "llama-3.1-8b-instant" }
if (-not $env:GROQ_MAX_RPM)           { $env:GROQ_MAX_RPM = "25" }

Write-Host "Groq scorer config:" -ForegroundColor Cyan
Write-Host "  In topic:    $env:GROQ_SCORER_IN_TOPIC"
Write-Host "  Out topic:   $env:GROQ_SCORER_OUT_TOPIC"
Write-Host "  Model:       $env:GROQ_MODEL (free-tier)"
Write-Host "  Rate limit:  $env:GROQ_MAX_RPM req/min"
Write-Host "  Max events:  $env:GROQ_SCORER_MAX_EVENTS (0 = unlimited, Ctrl-C to stop)"
Write-Host "  From offset: $env:GROQ_SCORER_FROM"
Write-Host "  Group:       $env:GROQ_SCORER_GROUP"
Write-Host ""

uv run python -m velocityfraud.groq_scorer

# Convenience launcher for the IEEE-CIS consumer.
# Run from the velocityfraud root: .\scripts\run-consumer.ps1
#
# Tweak via env vars:
#   $env:CONSUMER_MAX_MESSAGES=10;       .\scripts\run-consumer.ps1   # stop after 10 events
#   $env:CONSUMER_FROM="latest";         .\scripts\run-consumer.ps1   # only new messages
#   $env:CONSUMER_GROUP="my-group-name"; .\scripts\run-consumer.ps1   # fresh offset tracking

$ErrorActionPreference = "Stop"

if (-not $env:CONSUMER_MAX_MESSAGES) { $env:CONSUMER_MAX_MESSAGES = "0" }
if (-not $env:CONSUMER_FROM)         { $env:CONSUMER_FROM = "earliest" }
if (-not $env:CONSUMER_TOPIC)        { $env:CONSUMER_TOPIC = "transactions.raw" }
if (-not $env:CONSUMER_GROUP)        { $env:CONSUMER_GROUP = "velocityfraud-consumer-dev" }

Write-Host "Consumer config:" -ForegroundColor Cyan
Write-Host "  Max messages: $env:CONSUMER_MAX_MESSAGES (0 = unlimited, Ctrl-C to stop)"
Write-Host "  From offset:  $env:CONSUMER_FROM"
Write-Host "  Topic:        $env:CONSUMER_TOPIC"
Write-Host "  Group:        $env:CONSUMER_GROUP"
Write-Host ""

uv run python -m velocityfraud.consumer

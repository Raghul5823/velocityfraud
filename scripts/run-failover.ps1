# Launcher for the fast-path scorer with hot-standby failover (Layer 3b).
# Run TWO of these in two terminals to demo seamless failover:
#
#   Terminal 1 (primary):  $env:FAILOVER_ROLE="primary"; .\scripts\run-failover.ps1
#   Terminal 2 (standby):  $env:FAILOVER_ROLE="standby"; .\scripts\run-failover.ps1
#
# Then Ctrl-C the primary. The standby promotes to ACTIVE within FAILOVER_LOCK_TTL_MS
# and the transactions.scored stream continues with no gap.
#
# Requires Redis (leader lock) + Kafka up:  docker compose -f infra/docker-compose.yml up -d

$ErrorActionPreference = "Stop"

if (-not $env:FAILOVER_ROLE)         { $env:FAILOVER_ROLE = "auto" }
if (-not $env:FAILOVER_IN_TOPIC)     { $env:FAILOVER_IN_TOPIC = "transactions.raw" }
if (-not $env:FAILOVER_OUT_TOPIC)    { $env:FAILOVER_OUT_TOPIC = "transactions.scored" }
if (-not $env:FAILOVER_GROUP)        { $env:FAILOVER_GROUP = "velocityfraud-scorer-$($env:FAILOVER_ROLE)" }
if (-not $env:FAILOVER_LOCK_TTL_MS)  { $env:FAILOVER_LOCK_TTL_MS = "5000" }
if (-not $env:FAILOVER_HEARTBEAT_MS) { $env:FAILOVER_HEARTBEAT_MS = "1000" }
if (-not $env:FAILOVER_FROM)         { $env:FAILOVER_FROM = "latest" }
if (-not $env:FAILOVER_MAX_EVENTS)   { $env:FAILOVER_MAX_EVENTS = "0" }

Write-Host "Failover scorer config:" -ForegroundColor Cyan
Write-Host "  Role:        $env:FAILOVER_ROLE"
Write-Host "  In topic:    $env:FAILOVER_IN_TOPIC"
Write-Host "  Out topic:   $env:FAILOVER_OUT_TOPIC"
Write-Host "  Group:       $env:FAILOVER_GROUP"
Write-Host "  Lock TTL:    $env:FAILOVER_LOCK_TTL_MS ms  Heartbeat: $env:FAILOVER_HEARTBEAT_MS ms"
Write-Host "  From offset: $env:FAILOVER_FROM"
Write-Host ""

uv run python -m velocityfraud.failover_scorer

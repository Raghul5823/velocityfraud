# Closes proposal gap B8 (docs/proposal_gap_remediation.md).
#
# Proposal Section 11, Risk 4 mitigation: "Apicurio compatibility mode =
# BACKWARD; consumer rejects on schema break before processing." This was
# never actually configured on the running registry -- only a container-alive
# health check existed. This script sets the GLOBAL compatibility rule via
# Apicurio's Confluent-compatible (ccompat) API, the same API surface
# Kafka-UI already uses (see infra/docker-compose.yml's
# KAFKA_CLUSTERS_0_SCHEMAREGISTRY setting).
#
# Run from the velocityfraud root, with the stack already up:
#   .\scripts\set-apicurio-compatibility.ps1

$ErrorActionPreference = "Stop"
$apicurioUrl = "http://localhost:8080/apis/ccompat/v7/config"

Write-Host "Setting Apicurio global compatibility rule to BACKWARD..." -ForegroundColor Cyan

$body = @{ compatibility = "BACKWARD" } | ConvertTo-Json
$response = Invoke-RestMethod -Uri $apicurioUrl -Method Put -ContentType "application/json" -Body $body

Write-Host "Response: $($response | ConvertTo-Json)" -ForegroundColor Green

Write-Host "`nVerifying..." -ForegroundColor Cyan
$verify = Invoke-RestMethod -Uri $apicurioUrl -Method Get
if ($verify.compatibilityLevel -eq "BACKWARD" -or $verify.compatibility -eq "BACKWARD") {
    Write-Host "CONFIRMED: global compatibility = BACKWARD" -ForegroundColor Green
} else {
    Write-Host "WARNING: unexpected response, please check manually: $($verify | ConvertTo-Json)" -ForegroundColor Yellow
}

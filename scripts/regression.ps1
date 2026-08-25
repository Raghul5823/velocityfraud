# Full regression runner (Wk16 QA: "Full regression + load re-run").
# Verifies the whole system end-to-end and prints a consolidated PASS/FAIL summary.
# Run from the velocityfraud root:  .\scripts\regression.ps1
#
# Requires the infra up: docker compose -f infra/docker-compose.yml up -d

# "Continue" (not "Stop"): the Python stages log to stderr (loguru); in PS 5.1
# ErrorAction=Stop would treat that native stderr as a terminating error.
$ErrorActionPreference = "Continue"
$root = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $root
$py = ".\.venv\Scripts\python.exe"
$script:results = [ordered]@{}

function Run-Stage($name, [scriptblock]$body) {
    Write-Host ""
    Write-Host ("=== {0} ===" -f $name) -ForegroundColor Cyan
    $ok = [bool](& $body)
    $script:results[$name] = $ok
    if ($ok) { Write-Host ("  PASS: {0}" -f $name) -ForegroundColor Green }
    else     { Write-Host ("  FAIL: {0}" -f $name) -ForegroundColor Red }
}

Write-Host "==================================================================" -ForegroundColor Magenta
Write-Host " VelocityFraud - FULL REGRESSION" -ForegroundColor Magenta
Write-Host "==================================================================" -ForegroundColor Magenta

Run-Stage "Infra containers up" {
    $up = docker ps --format "{{.Names}}"
    $ok = $true
    foreach ($c in "vf-kafka", "vf-redis", "vf-postgres") {
        if ($up -match $c) { Write-Host "  up: $c" } else { Write-Host "  DOWN: $c"; $ok = $false }
    }
    return $ok
}

Run-Stage "Test suite (83 tests + coverage)" {
    & $py -m pytest tests/ --cov=src/velocityfraud --cov-report=term-missing -q | Out-Host
    return ($LASTEXITCODE -eq 0)
}

Run-Stage "Model evaluation (FPR + champion)" {
    & $py -m velocityfraud.training.evaluate | Out-Host
    return ($LASTEXITCODE -eq 0)
}

Run-Stage "Gemini fraud-pattern explanations" {
    & $py -m velocityfraud.fraud_patterns | Out-Host
    return ($LASTEXITCODE -eq 0)
}

Run-Stage "Feedback loop (stats)" {
    & $py -m velocityfraud.feedback stats | Out-Host
    return ($LASTEXITCODE -eq 0)
}

Run-Stage "Chaos probe (scoring works)" {
    & $py -m velocityfraud.chaos | Out-Host
    return ($LASTEXITCODE -eq 0)
}

# ---- Summary ----
Write-Host ""
Write-Host "==================================================================" -ForegroundColor Magenta
Write-Host " REGRESSION SUMMARY" -ForegroundColor Magenta
Write-Host "==================================================================" -ForegroundColor Magenta
$passed = 0; $total = 0
foreach ($k in $script:results.Keys) {
    $total++
    if ($script:results[$k]) { $passed++; $tag = "PASS"; $col = "Green" } else { $tag = "FAIL"; $col = "Red" }
    Write-Host ("  [{0}] {1}" -f $tag, $k) -ForegroundColor $col
}
Write-Host "------------------------------------------------------------------"
if ($passed -eq $total) {
    Write-Host (" RESULT: ALL GREEN - {0}/{1} stages passed" -f $passed, $total) -ForegroundColor Green
} else {
    Write-Host (" RESULT: {0}/{1} passed - see FAIL stages above" -f $passed, $total) -ForegroundColor Red
}
Write-Host "------------------------------------------------------------------"
Write-Host "Note: live failover + Redis-outage chaos are separate demos:" -ForegroundColor DarkGray
Write-Host "  .\scripts\demo-failover.ps1   .\scripts\chaos-test.ps1" -ForegroundColor DarkGray

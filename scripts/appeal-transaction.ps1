# CLI wrapper around velocityfraud.appeal for common tasks.
# Run from velocityfraud/ root.
#
# Examples:
#   .\scripts\appeal-transaction.ps1 submit -EventId <uuid> -Reason "customer says legit"
#   .\scripts\appeal-transaction.ps1 list
#   .\scripts\appeal-transaction.ps1 resolve -AppealId 1 -Notes "reviewed"

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("submit", "list", "resolve")]
    [string]$Command,

    [string]$EventId,
    [string]$Reason,
    [string]$Name = "unknown",
    [ValidateSet("customer", "analyst", "system")]
    [string]$Role = "customer",

    [int]$AppealId,
    [string]$Notes,
    [ValidateSet("ALLOW", "REVIEW", "BLOCK")]
    [string]$FinalDecision,
    [double]$FinalScore
)

$ErrorActionPreference = "Stop"

switch ($Command) {
    "submit" {
        if (-not $EventId) { Write-Host "ERROR: -EventId required" -ForegroundColor Red; exit 1 }
        if (-not $Reason)  { Write-Host "ERROR: -Reason required" -ForegroundColor Red; exit 1 }
        uv run python -m velocityfraud.appeal submit `
            --event-id $EventId --reason $Reason --name $Name --role $Role
    }
    "list" {
        uv run python -m velocityfraud.appeal list
    }
    "resolve" {
        if (-not $AppealId) { Write-Host "ERROR: -AppealId required" -ForegroundColor Red; exit 1 }
        if (-not $Notes)    { Write-Host "ERROR: -Notes required" -ForegroundColor Red; exit 1 }
        $extra = @()
        if ($FinalDecision) { $extra += "--final-decision"; $extra += $FinalDecision }
        if ($FinalScore)    { $extra += "--final-score";    $extra += $FinalScore }
        uv run python -m velocityfraud.appeal resolve `
            --appeal-id $AppealId --notes $Notes @extra
    }
}

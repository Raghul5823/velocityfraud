# Launcher for the fast-path scoring API (Layer 3c).
# Run from the velocityfraud root:  .\scripts\run-api.ps1
#
# Serves:
#   POST http://localhost:8000/score    - score one transaction
#   GET  http://localhost:8000/health   - liveness + model status
#   GET  http://localhost:8000/docs     - interactive Swagger UI
#
# Requires Redis up (blocklist pre-filter) + the champion model present.

$ErrorActionPreference = "Stop"

if (-not $env:API_HOST)    { $env:API_HOST = "0.0.0.0" }
if (-not $env:API_PORT)    { $env:API_PORT = "8000" }
if (-not $env:API_WORKERS) { $env:API_WORKERS = "4" }

# Pin BLAS/OpenMP to 1 thread per process. XGBoost predict + numpy otherwise fan
# out to all cores; with multiple workers that oversubscribes the CPU. The model
# is also pinned to n_jobs=1 in api.py (the pickle's own param overrides OMP).
$env:OMP_NUM_THREADS = "1"
$env:OPENBLAS_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"

Write-Host "Scoring API starting on http://localhost:$($env:API_PORT)  ($($env:API_WORKERS) workers, Ctrl-C to stop)" -ForegroundColor Cyan
Write-Host "  POST /score   GET /health   GET /ping   GET /docs" -ForegroundColor DarkGray
Write-Host "  (set API_SKIP_BLOCKLIST=1 to benchmark the pure ML fast path)" -ForegroundColor DarkGray
Write-Host ""

uv run uvicorn velocityfraud.api:app --host $env:API_HOST --port $env:API_PORT --workers $env:API_WORKERS

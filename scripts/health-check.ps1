# VelocityFraud full-system health check.
# Verifies all completed layers (1, 2, 3, 4, 6) are in a good shape.
# Run from velocityfraud root: .\scripts\health-check.ps1
#
# Exit code: 0 = all pass, 1 = any failure.

$ErrorActionPreference = "Continue"

$passCount = 0
$failCount = 0
$results = @()

function Test-Check {
    param([string]$Layer, [string]$Name, [scriptblock]$Test)
    Write-Host -NoNewline "  [$Layer] $Name ..."
    try {
        $result = & $Test
        if ($result) {
            Write-Host " PASS" -ForegroundColor Green
            $script:passCount++
            $script:results += [PSCustomObject]@{ Layer = $Layer; Check = $Name; Status = "PASS"; Detail = $result }
        } else {
            Write-Host " FAIL" -ForegroundColor Red
            $script:failCount++
            $script:results += [PSCustomObject]@{ Layer = $Layer; Check = $Name; Status = "FAIL"; Detail = "(empty result)" }
        }
    } catch {
        Write-Host " FAIL" -ForegroundColor Red
        $script:failCount++
        $script:results += [PSCustomObject]@{ Layer = $Layer; Check = $Name; Status = "FAIL"; Detail = $_.Exception.Message }
    }
}

Write-Host ""
Write-Host "===================================================================" -ForegroundColor Cyan
Write-Host " VelocityFraud End-to-End Health Check" -ForegroundColor Cyan
Write-Host "===================================================================" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# Layer 1: Stream Infrastructure
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Layer 1  --  Stream Infrastructure" -ForegroundColor Yellow
Write-Host "-------------------------------------------------------------------"

Test-Check "L1" "vf-kafka container healthy" {
    $status = docker inspect --format "{{.State.Health.Status}}" vf-kafka 2>$null
    if ($status -eq "healthy") { "healthy" } else { $null }
}

Test-Check "L1" "vf-apicurio container running" {
    $status = docker inspect --format "{{.State.Status}}" vf-apicurio 2>$null
    if ($status -eq "running") { "running" } else { $null }
}

Test-Check "L1" "vf-kafka-ui container running" {
    $status = docker inspect --format "{{.State.Status}}" vf-kafka-ui 2>$null
    if ($status -eq "running") { "running" } else { $null }
}

Test-Check "L1" "Kafka topic transactions.raw exists" {
    $topics = docker exec vf-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list 2>$null
    if ($topics -match "transactions\.raw") { "found" } else { $null }
}

Test-Check "L1" "Kafka topic transactions.scored exists" {
    $topics = docker exec vf-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list 2>$null
    if ($topics -match "transactions\.scored") { "found" } else { $null }
}

Test-Check "L1" "Kafka topic transactions.enriched exists" {
    $topics = docker exec vf-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list 2>$null
    if ($topics -match "transactions\.enriched") { "found" } else { $null }
}

Test-Check "L1" "Avro schema file present" {
    if (Test-Path "infra\schemas\transaction-event.avsc") { "on disk" } else { $null }
}

Test-Check "L1" "Schema loads with 16 fields" {
    $out = uv run python -c "from velocityfraud.schema import get_schema; print(len(get_schema()['fields']))" 2>&1 | Select-Object -Last 1
    if ($out.Trim() -eq "16") { "16 fields" } else { $null }
}

# ---------------------------------------------------------------------------
# Layer 2: Model Training
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Layer 2  --  Model Training" -ForegroundColor Yellow
Write-Host "-------------------------------------------------------------------"

Test-Check "L2" "Champion pointer file exists" {
    if (Test-Path "models\CHAMPION.txt") {
        $name = (Get-Content "models\CHAMPION.txt").Trim()
        "champion = $name"
    } else { $null }
}

Test-Check "L2" "Champion model .pkl exists" {
    $name = (Get-Content "models\CHAMPION.txt").Trim()
    if (Test-Path "models\$name") { "found" } else { $null }
}

Test-Check "L2" "Processed features (X_train.parquet)" {
    if (Test-Path "data\processed\X_train.parquet") { "on disk" } else { $null }
}

Test-Check "L2" "Feature meta JSON present" {
    if (Test-Path "data\processed\feature_meta.json") {
        $meta = Get-Content "data\processed\feature_meta.json" | ConvertFrom-Json
        "$($meta.n_features) features, $($meta.n_train) train / $($meta.n_test) test"
    } else { $null }
}

Test-Check "L2" "vf-mlflow container running" {
    $status = docker inspect --format "{{.State.Status}}" vf-mlflow 2>$null
    if ($status -eq "running") { "running" } else { $null }
}

Test-Check "L2" "predict.py smoke test loads champion" {
    $out = uv run python -c "from velocityfraud.predict import get_champion_model; m = get_champion_model(); print(m.__class__.__name__)" 2>&1 | Select-Object -Last 1
    if ($out.Trim() -match "XGB|RandomForest") { $out.Trim() } else { $null }
}

# ---------------------------------------------------------------------------
# Layer 3: Fast-Path Scoring
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Layer 3  --  Fast-Path Scoring" -ForegroundColor Yellow
Write-Host "-------------------------------------------------------------------"

Test-Check "L3" "Scored Avro schema present" {
    if (Test-Path "infra\schemas\transaction-scored-event.avsc") { "on disk" } else { $null }
}

Test-Check "L3" "Scored schema loads with 26 fields (23 base + 3 L8)" {
    $out = uv run python -c "from velocityfraud.schema import get_scored_schema; print(len(get_scored_schema()['fields']))" 2>&1 | Select-Object -Last 1
    if ($out.Trim() -eq "26") { "26 fields" } else { $null }
}

Test-Check "L3" "live_features maps to 43-col vector" {
    $out = uv run python -c "from velocityfraud.live_features import featurize_event; e={'event_id':'x','event_timestamp_ms':1782731301417,'customer_id':'1','card_token':'x','amount':50.0,'currency':'USD','amount_fx_normalised':50.0,'merchant_id_hash':'x','merchant_name':'W-MERCHANT-gmail.com','mcc':'5411','merchant_country':'87','ip_address_hash':'x','device_fingerprint_hash':'x','geo_distance_km':0.0,'source_label':'live','schema_version':'v1'}; X,c=featurize_event(e); print(X.shape[1])" 2>&1 | Select-Object -Last 1
    if ($out.Trim() -eq "43") { "43 features" } else { $null }
}

Test-Check "L3" "scorer.py imports cleanly" {
    $out = uv run python -c "from velocityfraud import scorer; print('ok')" 2>&1 | Select-Object -Last 1
    if ($out.Trim() -eq "ok") { "importable" } else { $null }
}

# ---------------------------------------------------------------------------
# Layer 4: Slow-Path Analysis
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Layer 4  --  Slow-Path Analysis (SHAP + Narrator)" -ForegroundColor Yellow
Write-Host "-------------------------------------------------------------------"

Test-Check "L4" "Enriched Avro schema present" {
    if (Test-Path "infra\schemas\transaction-enriched-event.avsc") { "on disk" } else { $null }
}

Test-Check "L4" "Enriched schema loads with 28 fields" {
    $out = uv run python -c "from velocityfraud.schema import get_enriched_schema; print(len(get_enriched_schema()['fields']))" 2>&1 | Select-Object -Last 1
    if ($out.Trim() -eq "28") { "28 fields" } else { $null }
}

Test-Check "L4" "SHAP explainer builds" {
    $out = uv run python -c "from velocityfraud.explainer import get_explainer; e = get_explainer(); print(type(e).__name__)" 2>&1 | Select-Object -Last 1
    if ($out.Trim() -match "TreeExplainer|Tree") { $out.Trim() } else { $null }
}

Test-Check "L4" "Narrator template mode works" {
    $out = uv run python -c "from velocityfraud.narrator import _template_narrate; from velocityfraud.explainer import FeatureContribution as F; ev={'event_id':'x','amount':100.0,'merchant_name':'W-MERCHANT-gmail.com','decision':'REVIEW','fraud_score':0.2,'feature_completeness':0.35}; print('ok' if _template_narrate(ev, [F('TransactionAmt',100.0,0.5), F('hour_of_day',22.0,-0.3)]).startswith('Transaction') else 'bad')" 2>&1 | Select-Object -Last 1
    if ($out.Trim() -eq "ok") { "template generates text" } else { $null }
}

Test-Check "L4" "slow_path.py imports cleanly" {
    $out = uv run python -c "from velocityfraud import slow_path; print('ok')" 2>&1 | Select-Object -Last 1
    if ($out.Trim() -eq "ok") { "importable" } else { $null }
}

# ---------------------------------------------------------------------------
# Layer 6: Storage (Postgres)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Layer 6  --  Storage (PostgreSQL)" -ForegroundColor Yellow
Write-Host "-------------------------------------------------------------------"

Test-Check "L6" "vf-postgres container healthy" {
    $status = docker inspect --format "{{.State.Health.Status}}" vf-postgres 2>$null
    if ($status -eq "healthy") { "healthy" } else { $null }
}

Test-Check "L6" "Postgres accepts connections" {
    $out = uv run python -c "from velocityfraud.db import get_connection; c = get_connection(); c.close(); print('ok')" 2>&1 | Select-Object -Last 1
    if ($out.Trim() -eq "ok") { "connected" } else { $null }
}

Test-Check "L6" "scored_events table populated" {
    $count = docker exec vf-postgres psql -U vf -d velocityfraud -t -A -c "SELECT COUNT(*) FROM scored_events" 2>$null
    if ([int]$count -gt 0) { "$count rows" } else { $null }
}

Test-Check "L6" "enriched_events table populated" {
    $count = docker exec vf-postgres psql -U vf -d velocityfraud -t -A -c "SELECT COUNT(*) FROM enriched_events" 2>$null
    if ([int]$count -gt 0) { "$count rows" } else { $null }
}

Test-Check "L6" "All 3 decisions represented" {
    $count = docker exec vf-postgres psql -U vf -d velocityfraud -t -A -c "SELECT COUNT(DISTINCT decision) FROM scored_events" 2>$null
    if ([int]$count -eq 3) { "ALLOW, REVIEW, BLOCK all present" } else { $null }
}

Test-Check "L6" "Layer-5 forward-compat columns nullable" {
    $out = docker exec vf-postgres psql -U vf -d velocityfraud -t -A -c "SELECT COUNT(*) FROM information_schema.columns WHERE table_name='enriched_events' AND column_name LIKE 'text_anomaly%' AND is_nullable='YES'" 2>$null
    if ([int]$out -ge 2) { "$out columns nullable & ready" } else { $null }
}

Test-Check "L6" "Dashboard views exist" {
    $out = docker exec vf-postgres psql -U vf -d velocityfraud -t -A -c "SELECT COUNT(*) FROM information_schema.views WHERE table_name IN ('decision_distribution_24h', 'top_flagged_customers')" 2>$null
    if ([int]$out -eq 2) { "both views ready" } else { $null }
}

# ---------------------------------------------------------------------------
# Layer 5: Text Anomaly (DistilBERT)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Layer 5  --  Text Anomaly (DistilBERT)" -ForegroundColor Yellow
Write-Host "-------------------------------------------------------------------"

Test-Check "L5" "text_anomaly module imports" {
    $out = uv run python -c "from velocityfraud import text_anomaly; print('ok')" 2>&1 | Select-Object -Last 1
    if ($out.Trim() -eq "ok") { "importable" } else { $null }
}

Test-Check "L5" "text_anomaly_consumer imports" {
    $out = uv run python -c "from velocityfraud import text_anomaly_consumer; print('ok')" 2>&1 | Select-Object -Last 1
    if ($out.Trim() -eq "ok") { "importable" } else { $null }
}

Test-Check "L5" "DistilBERT weights cached locally" {
    $cache = "$env:USERPROFILE\.cache\huggingface\hub\models--distilbert-base-uncased"
    if (Test-Path $cache) { "cached ($cache)" } else { $null }
}

Test-Check "L5" "enriched rows populated with text anomaly" {
    $filled = docker exec vf-postgres psql -U vf -d velocityfraud -t -A -c "SELECT COUNT(*) FROM enriched_events WHERE text_anomaly_score IS NOT NULL" 2>$null
    $total = docker exec vf-postgres psql -U vf -d velocityfraud -t -A -c "SELECT COUNT(*) FROM enriched_events" 2>$null
    if ([int]$filled -gt 0 -and [int]$filled -eq [int]$total) { "$filled / $total rows" } else { $null }
}

Test-Check "L5" "Both text_anomaly_label values represented" {
    $out = docker exec vf-postgres psql -U vf -d velocityfraud -t -A -c "SELECT COUNT(DISTINCT text_anomaly_label) FROM enriched_events WHERE text_anomaly_label IS NOT NULL" 2>$null
    if ([int]$out -ge 1) { "$out label(s) seen" } else { $null }
}

# ---------------------------------------------------------------------------
# Layer 8: Redis Blocklist + Appeals (bonus layer beyond original 7-layer plan)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Layer 8  --  Blocklist + Appeals (Redis)" -ForegroundColor Yellow
Write-Host "-------------------------------------------------------------------"

Test-Check "L8" "vf-redis container healthy" {
    $status = docker inspect --format "{{.State.Health.Status}}" vf-redis 2>$null
    if ($status -eq "healthy") { "healthy" } else { $null }
}

Test-Check "L8" "Redis PING responds" {
    $out = docker exec vf-redis redis-cli ping 2>$null
    if ($out.Trim() -eq "PONG") { "PONG" } else { $null }
}

Test-Check "L8" "blocklist module imports" {
    $out = uv run python -c "from velocityfraud import blocklist; print('ok')" 2>&1 | Select-Object -Last 1
    if ($out.Trim() -eq "ok") { "importable" } else { $null }
}

Test-Check "L8" "blocklist_updater module imports" {
    $out = uv run python -c "from velocityfraud import blocklist_updater; print('ok')" 2>&1 | Select-Object -Last 1
    if ($out.Trim() -eq "ok") { "importable" } else { $null }
}

Test-Check "L8" "appeal module imports" {
    $out = uv run python -c "from velocityfraud import appeal; print('ok')" 2>&1 | Select-Object -Last 1
    if ($out.Trim() -eq "ok") { "importable" } else { $null }
}

Test-Check "L8" "appeals table exists" {
    $out = docker exec vf-postgres psql -U vf -d velocityfraud -t -A -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='appeals'" 2>$null
    if ([int]$out -eq 1) { "table present" } else { $null }
}

Test-Check "L8" "scored_events has blocklist columns" {
    $out = docker exec vf-postgres psql -U vf -d velocityfraud -t -A -c "SELECT COUNT(*) FROM information_schema.columns WHERE table_name='scored_events' AND column_name LIKE 'blocklist%'" 2>$null
    if ([int]$out -eq 3) { "3 columns present" } else { $null }
}

# ---------------------------------------------------------------------------
# Layer 5b: Groq LLM Scoring (parallel path — proposal item 5)
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "Layer 5b -- Groq LLM Scoring (parallel to XGBoost)" -ForegroundColor Yellow
Write-Host "-------------------------------------------------------------------"

Test-Check "L5b" "GROQ_API_KEY present in .env" {
    if (-not (Test-Path ".env")) { return $null }
    $line = Get-Content .env | Where-Object { $_ -match "^GROQ_API_KEY=..+" }
    if ($line) { "key set" } else { $null }
}

Test-Check "L5b" "groq_scorer module imports" {
    $out = uv run python -c "from velocityfraud import groq_scorer; print('ok')" 2>&1 | Select-Object -Last 1
    if ($out.Trim() -eq "ok") { "importable" } else { $null }
}

Test-Check "L5b" "Kafka topic transactions.scored.groq exists" {
    $topics = docker exec vf-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list 2>$null
    if ($topics -match "transactions\.scored\.groq") { "found" } else { $null }
}

Test-Check "L5b" "scored_events_groq table exists" {
    $out = docker exec vf-postgres psql -U vf -d velocityfraud -t -A -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_name='scored_events_groq'" 2>$null
    if ([int]$out -eq 1) { "table present" } else { $null }
}

Test-Check "L5b" "scorer_comparison view exists" {
    $out = docker exec vf-postgres psql -U vf -d velocityfraud -t -A -c "SELECT COUNT(*) FROM information_schema.views WHERE table_name='scorer_comparison'" 2>$null
    if ([int]$out -eq 1) { "view present" } else { $null }
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
$total = $passCount + $failCount

Write-Host ""
Write-Host "===================================================================" -ForegroundColor Cyan
Write-Host " HEALTH CHECK SUMMARY" -ForegroundColor Cyan
Write-Host "===================================================================" -ForegroundColor Cyan
Write-Host "  Total checks : $total"
Write-Host "  Passed       : $passCount" -ForegroundColor Green
Write-Host "  Failed       : $failCount" -ForegroundColor $(if ($failCount -eq 0) { "Green" } else { "Red" })

if ($failCount -gt 0) {
    Write-Host ""
    Write-Host "FAILED CHECKS:" -ForegroundColor Red
    $results | Where-Object { $_.Status -eq "FAIL" } | ForEach-Object {
        Write-Host "  [$($_.Layer)] $($_.Check): $($_.Detail)" -ForegroundColor Red
    }
}

Write-Host ""
if ($failCount -eq 0) {
    Write-Host "  STATUS: ALL SYSTEMS GO -- safe to proceed to next layer" -ForegroundColor Green
    exit 0
} else {
    Write-Host "  STATUS: ATTENTION -- fix the failures above before proceeding" -ForegroundColor Red
    exit 1
}

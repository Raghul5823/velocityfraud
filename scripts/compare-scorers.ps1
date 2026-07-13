# Side-by-side comparison of XGBoost vs Groq LLM scoring (Layer 5b).
# Uses the `scorer_comparison` view created by migration 003_groq_scoring.sql.
#
# Presentation-ready output — shows agreement rate, latency delta, and where
# the two scorers diverge (interesting for analyst review).
#
# Run from velocityfraud root: .\scripts\compare-scorers.ps1

$ErrorActionPreference = "Stop"

$container = "vf-postgres"
$db = "velocityfraud"
$user = "vf"

function Run-Sql($label, $sql) {
    Write-Host ""
    Write-Host $label -ForegroundColor Cyan
    Write-Host ("-" * $label.Length) -ForegroundColor DarkGray
    docker exec -e PGPASSWORD=vfpass $container psql -U $user -d $db -c $sql
}

# -----------------------------------------------------------
# 1. Row counts
# -----------------------------------------------------------
Run-Sql "1. Row counts per scorer" @"
SELECT
  (SELECT COUNT(*) FROM scored_events)      AS xgboost_rows,
  (SELECT COUNT(*) FROM scored_events_groq) AS groq_rows,
  (SELECT COUNT(*) FROM scorer_comparison)  AS overlap_rows;
"@

# -----------------------------------------------------------
# 2. Decision distribution — how often each decides ALLOW/REVIEW/BLOCK
# -----------------------------------------------------------
Run-Sql "2. Decision distribution: XGBoost" @"
SELECT decision, COUNT(*) AS n,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM scored_events GROUP BY decision ORDER BY decision;
"@

Run-Sql "2. Decision distribution: Groq" @"
SELECT decision, COUNT(*) AS n,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM scored_events_groq GROUP BY decision ORDER BY decision;
"@

# -----------------------------------------------------------
# 3. Agreement rate (of overlap events)
# -----------------------------------------------------------
Run-Sql "3. Decision agreement rate" @"
SELECT
  COUNT(*)                                    AS total_overlap,
  COUNT(*) FILTER (WHERE decisions_agree)     AS agreements,
  COUNT(*) FILTER (WHERE NOT decisions_agree) AS disagreements,
  ROUND(100.0 * COUNT(*) FILTER (WHERE decisions_agree) / COUNT(*), 1)
                                              AS agreement_pct
FROM scorer_comparison;
"@

# -----------------------------------------------------------
# 4. Latency comparison
# -----------------------------------------------------------
Run-Sql "4. Latency: XGBoost vs Groq (ms)" @"
SELECT
  ROUND(AVG(xgb_latency_ms), 2)  AS xgb_avg_ms,
  MAX(xgb_latency_ms)            AS xgb_max_ms,
  ROUND(AVG(groq_latency_ms), 2) AS groq_avg_ms,
  MAX(groq_latency_ms)           AS groq_max_ms
FROM scorer_comparison;
"@

# -----------------------------------------------------------
# 5. Confusion matrix — where they diverge
# -----------------------------------------------------------
Run-Sql "5. Cross-tab: XGBoost decision vs Groq decision" @"
SELECT xgb_decision, groq_decision, COUNT(*) AS n
FROM scorer_comparison
GROUP BY xgb_decision, groq_decision
ORDER BY xgb_decision, groq_decision;
"@

# -----------------------------------------------------------
# 6. Top disagreements — highest score_diff cases (interesting for demo)
# -----------------------------------------------------------
Run-Sql "6. Top 5 disagreements (largest score_diff)" @"
SELECT event_id, amount, merchant_name,
       xgb_score, xgb_decision,
       groq_score, groq_decision,
       LEFT(llm_reason, 60) AS reason_start
FROM scorer_comparison
WHERE NOT decisions_agree
ORDER BY score_diff DESC
LIMIT 5;
"@

Write-Host ""
Write-Host "Comparison report complete." -ForegroundColor Green

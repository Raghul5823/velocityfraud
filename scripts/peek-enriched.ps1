# Read the first N messages from transactions.enriched and pretty-print:
#   - Decision + score
#   - Narrative (full text)
#   - Top 5 SHAP contributors
#
# Run from velocityfraud root: .\scripts\peek-enriched.ps1
# Override count: $env:PEEK_COUNT="5"; .\scripts\peek-enriched.ps1

$ErrorActionPreference = "Stop"
if (-not $env:PEEK_COUNT) { $env:PEEK_COUNT = "3" }

Write-Host "Reading first $env:PEEK_COUNT enriched events from 'transactions.enriched'..." -ForegroundColor Cyan
Write-Host ""

uv run python -c @"
import io, uuid
import fastavro
from confluent_kafka import Consumer
from velocityfraud.schema import get_enriched_schema

schema = get_enriched_schema()
c = Consumer({
    'bootstrap.servers': 'localhost:9092',
    'group.id': 'peek-enriched-' + str(uuid.uuid4()),
    'auto.offset.reset': 'earliest',
})
c.subscribe(['transactions.enriched'])

count = 0
target = int('$env:PEEK_COUNT')
while count < target:
    msg = c.poll(timeout=5.0)
    if msg is None or msg.error():
        if count == 0:
            print('No messages available within timeout.')
        break
    ev = fastavro.schemaless_reader(io.BytesIO(msg.value()), schema)
    count += 1
    print('=' * 78)
    print(f'ENRICHED EVENT {count}  |  partition={msg.partition()}  offset={msg.offset()}')
    print('=' * 78)
    print(f'  event_id      : {ev[\"event_id\"][:8]}...')
    print(f'  customer_id   : {ev[\"customer_id\"]}')
    print(f'  amount        : `${ev[\"amount\"]:,.2f} {ev[\"currency\"]}')
    print(f'  merchant      : {ev[\"merchant_name\"]}')
    print(f'  mcc           : {ev[\"mcc\"]}')
    print(f'  fraud_score   : {ev[\"fraud_score\"]:.4f}')
    print(f'  decision      : {ev[\"decision\"]}')
    print(f'  feature_comp. : {ev[\"feature_completeness\"]:.2%}')
    print(f'  scoring_lat   : {ev[\"scoring_latency_ms\"]} ms')
    print(f'  enrich_lat    : {ev[\"enrichment_latency_ms\"]} ms')
    print(f'  narrator_mode : {ev[\"narrator_mode\"]}')
    print()
    print('  NARRATIVE:')
    print(f'    {ev[\"narrative\"]}')
    print()
    print('  TOP 5 SHAP CONTRIBUTORS:')
    for i, fc in enumerate(ev['top_contributors'], 1):
        arrow = '->FRAUD' if fc['shap_value'] > 0 else '->LEGIT'
        print(f'    {i}. {fc[\"feature_name\"]:25s} value={fc[\"feature_value\"]:>12.4f}  shap={fc[\"shap_value\"]:>+8.4f}  {arrow}')
    print()
c.close()
print(f'Read {count} enriched events.')
"@

# Read the first N messages from transactions.scored and pretty-print all fields.
# Run from velocityfraud root: .\scripts\peek-scored.ps1
# Override count: $env:PEEK_COUNT="5"; .\scripts\peek-scored.ps1

$ErrorActionPreference = "Stop"
if (-not $env:PEEK_COUNT) { $env:PEEK_COUNT = "3" }

Write-Host "Reading first $env:PEEK_COUNT scored events from 'transactions.scored'..." -ForegroundColor Cyan
Write-Host ""

uv run python -c @"
import io, json
import fastavro
from confluent_kafka import Consumer
from velocityfraud.schema import get_scored_schema

schema = get_scored_schema()
c = Consumer({
    'bootstrap.servers': 'localhost:9092',
    'group.id': 'peek-scored-' + str(__import__('uuid').uuid4()),
    'auto.offset.reset': 'earliest',
})
c.subscribe(['transactions.scored'])

count = 0
target = int('$env:PEEK_COUNT')
while count < target:
    msg = c.poll(timeout=5.0)
    if msg is None or msg.error():
        if count == 0:
            print('No messages available within timeout.')
        break
    event = fastavro.schemaless_reader(io.BytesIO(msg.value()), schema)
    count += 1
    print('=' * 70)
    print(f'MESSAGE {count}  |  partition={msg.partition()}  offset={msg.offset()}')
    print('=' * 70)
    for k, v in event.items():
        if isinstance(v, float):
            print(f'  {k:25s} = {v:.4f}')
        else:
            print(f'  {k:25s} = {v}')
    print()
c.close()
print(f'Read {count} scored events.')
"@

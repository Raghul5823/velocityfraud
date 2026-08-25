# Analyst feedback CLI (Wk 12 — closes the feedback loop).
# Records a ground-truth verdict on a scored transaction: writes to Postgres
# (feedback_events) and produces to Kafka (transactions.feedback).
#
# Examples:
#   .\scripts\submit-feedback.ps1 submit --event-id <uuid> --verdict FRAUD --analyst jdoe --notes "confirmed chargeback"
#   .\scripts\submit-feedback.ps1 list
#   .\scripts\submit-feedback.ps1 stats
#
# Requires Postgres + Kafka up, and migration 004_feedback.sql applied
# (uv run python -m velocityfraud.db applies all migrations).

uv run python -m velocityfraud.feedback @args

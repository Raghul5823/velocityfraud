"""Loads VelocityFraud Avro schemas from disk.

`infra/schemas/` is the source of truth committed to Git. Apicurio would be
the canonical registry in production, but reading from disk is reliable and
fast for the POC and removes one network dependency at startup.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import fastavro


_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "infra" / "schemas"


@lru_cache(maxsize=1)
def get_schema() -> dict:
    """Return the parsed TransactionEvent schema (cached after first load)."""
    return fastavro.schema.load_schema(str(_SCHEMA_DIR / "transaction-event.avsc"))


@lru_cache(maxsize=1)
def get_scored_schema() -> dict:
    """Return the parsed TransactionScoredEvent schema (cached)."""
    return fastavro.schema.load_schema(str(_SCHEMA_DIR / "transaction-scored-event.avsc"))


@lru_cache(maxsize=1)
def get_enriched_schema() -> dict:
    """Return the parsed TransactionEnrichedEvent schema (cached)."""
    return fastavro.schema.load_schema(str(_SCHEMA_DIR / "transaction-enriched-event.avsc"))


@lru_cache(maxsize=1)
def get_feedback_schema() -> dict:
    """Return the parsed TransactionFeedbackEvent schema (cached)."""
    return fastavro.schema.load_schema(str(_SCHEMA_DIR / "transaction-feedback-event.avsc"))

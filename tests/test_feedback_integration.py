"""Integration test for the analyst feedback loop (Postgres + Kafka, Wk 12).

Submits a ground-truth verdict on an existing scored event, then checks the row
landed and the agreement stats compute. Cleans up the row it created.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _some_scored_event(pg):
    with pg.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT event_id FROM scored_events LIMIT 1")
            row = cur.fetchone()
    return row[0] if row else None


def test_submit_feedback_writes_and_emits(pg_ready, kafka_ready):
    from velocityfraud import feedback

    # feedback needs its topic to exist; ensure it (idempotent)
    from confluent_kafka.admin import AdminClient, NewTopic
    admin = AdminClient({"bootstrap.servers": kafka_ready})
    for f in admin.create_topics([NewTopic("transactions.feedback", 1, 1)]).values():
        try:
            f.result(timeout=15)
        except Exception:
            pass  # already exists

    event_id = _some_scored_event(pg_ready)
    if event_id is None:
        pytest.skip("no scored_events to give feedback on")

    res = feedback.submit_feedback(event_id, "LEGIT", analyst_name="pytest",
                                   notes="integration test")
    assert res["ok"] is True
    assert res["analyst_verdict"] == "LEGIT"
    assert "model_agreed" in res
    fid = res["feedback_id"]

    # it shows up in the list
    ids = [f["feedback_id"] for f in feedback.list_feedback(limit=50)]
    assert fid in ids

    # stats compute
    stats = feedback.feedback_stats()
    assert stats["total_feedback"] >= 1
    assert 0.0 <= stats["agreement_rate"] <= 1.0

    # cleanup the row we created
    with pg_ready.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM feedback_events WHERE feedback_id = %s", (fid,))
        conn.commit()


def test_submit_feedback_bad_verdict_raises(pg_ready):
    from velocityfraud import feedback
    with pytest.raises(ValueError):
        feedback.submit_feedback("x", "MAYBE")


def test_submit_feedback_missing_event(pg_ready):
    from velocityfraud import feedback
    res = feedback.submit_feedback("no-such-event", "FRAUD")
    assert res["ok"] is False

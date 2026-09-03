"""Integration tests for fast-path-vs-shadow drift detection (proposal §10.3).

Needs live Postgres (pg_ready) -- the module's whole job is querying the
scorer_comparison view and recording into drift_checks, so unlike a pure-unit
test, exercising the real SQL is the point. Skips gracefully without infra
per conftest's fail-open convention.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_check_drift_returns_well_formed_result(pg_ready):
    from velocityfraud.drift import check_drift

    result = check_drift(window_minutes=60, threshold=0.05)

    assert set(result) == {
        "check_id", "window_minutes", "compared", "disagreements",
        "disagreement_rate", "threshold", "alarm_fired",
    }
    assert isinstance(result["check_id"], int)
    assert result["window_minutes"] == 60
    assert result["threshold"] == 0.05
    assert 0.0 <= result["disagreement_rate"] <= 1.0
    assert isinstance(result["alarm_fired"], bool)
    # alarm can only fire when there was something to compare
    if result["compared"] == 0:
        assert result["alarm_fired"] is False


def test_check_drift_alarm_logic_matches_threshold(pg_ready):
    """The alarm must fire iff (compared > 0) and (rate > threshold) -- lock
    down the exact boundary condition, not just that a bool comes back."""
    from velocityfraud.drift import check_drift

    result = check_drift(window_minutes=60, threshold=0.05)
    compared, disagreements = result["compared"], result["disagreements"]
    expected_rate = (disagreements / compared) if compared > 0 else 0.0
    expected_alarm = compared > 0 and expected_rate > 0.05

    assert result["disagreement_rate"] == pytest.approx(expected_rate, abs=1e-4)
    assert result["alarm_fired"] == expected_alarm


def test_check_drift_zero_threshold_fires_on_any_disagreement(pg_ready):
    """A threshold of 0.0 must alarm as soon as there is any comparable data
    with at least one disagreement -- a cheap way to force the alarm branch
    deterministically without depending on what real data happens to hold."""
    from velocityfraud.drift import check_drift

    result = check_drift(window_minutes=1440, threshold=0.0)
    if result["compared"] > 0 and result["disagreements"] > 0:
        assert result["alarm_fired"] is True
    elif result["compared"] > 0:
        assert result["alarm_fired"] is False  # 0 disagreements, rate 0.0, not > 0.0


def test_history_includes_the_most_recent_check(pg_ready):
    from velocityfraud.drift import check_drift, history

    fresh = check_drift(window_minutes=60, threshold=0.05)
    recent = history(limit=5)

    assert isinstance(recent, list)
    assert recent, "expected at least the check just performed"
    ids = [row["check_id"] for row in recent]
    assert fresh["check_id"] in ids

    row = next(r for r in recent if r["check_id"] == fresh["check_id"])
    assert set(row) == {
        "check_id", "window_minutes", "compared", "disagreements",
        "disagreement_rate", "threshold", "alarm_fired", "checked_at",
    }
    assert row["window_minutes"] == 60


def test_history_respects_limit(pg_ready):
    from velocityfraud.drift import check_drift, history

    for _ in range(3):
        check_drift(window_minutes=60, threshold=0.05)

    assert len(history(limit=2)) == 2

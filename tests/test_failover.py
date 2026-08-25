"""Unit tests for the fast-path failover scorer (Layer 3b) pure logic.

Covers the pieces that need no Kafka / Redis / model:
    - _pct:        nearest-rank percentile used by the live latency timer
    - LeaderState: thread-safe ACTIVE/STANDBY flag + promotion counter

The Redis-backed LeaderLock and the end-to-end takeover are validated
separately by scripts/demo-failover.ps1 against live infrastructure.

Run: uv run pytest tests/ -v
"""
from __future__ import annotations

from velocityfraud.failover_scorer import LeaderState, _pct


# ---------------------------------------------------------------------------
# _pct — nearest-rank percentile
# ---------------------------------------------------------------------------
def test_pct_empty_returns_zero():
    """An empty latency window must not raise — it reports 0.0."""
    assert _pct([], 95) == 0.0


def test_pct_single_value():
    """Every percentile of a one-element list is that element."""
    assert _pct([42.0], 50) == 42.0
    assert _pct([42.0], 95) == 42.0


def test_pct_p50_median():
    """p50 lands on the middle rank for an odd-length sorted list."""
    assert _pct([10, 20, 30, 40, 50], 50) == 30


def test_pct_p95_high_tail():
    """p95 selects a value from the top of the distribution, not the mean."""
    vals = list(range(1, 101))  # 1..100
    # Nearest-rank p95 over 100 items -> index ~94/95 -> ~96
    assert _pct(vals, 95) >= 95


def test_pct_p100_is_max():
    assert _pct([3, 1, 2], 100) == 3


# ---------------------------------------------------------------------------
# LeaderState — thread-safe role flag
# ---------------------------------------------------------------------------
def test_leaderstate_defaults_to_standby():
    """A fresh state is STANDBY (not producing) unless told otherwise."""
    st = LeaderState()
    assert st.active is False
    assert st.promotions == 0
    assert st.scored == 0


def test_leaderstate_initial_active():
    """A primary that wins the lock at startup begins ACTIVE."""
    st = LeaderState(active=True)
    assert st.active is True


def test_leaderstate_set_active_toggles():
    """set_active flips the flag both ways (promotion and step-down)."""
    st = LeaderState()
    st.set_active(True)
    assert st.active is True
    st.set_active(False)
    assert st.active is False


def test_leaderstate_scored_counter_is_mutable():
    """The main loop mirrors its scored count so the promotion banner can report it."""
    st = LeaderState()
    st.scored = 566
    assert st.scored == 566

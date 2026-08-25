"""Unit tests for the feedback loop's pure agreement logic (no infra needed).

model_agrees() decides whether the model's flag (REVIEW/BLOCK = fraud, ALLOW =
legit) matched the analyst's ground-truth verdict — the basis of the
model-vs-analyst agreement rate on the Operational Health dashboard.
"""
from __future__ import annotations

from velocityfraud.feedback import model_agrees, _model_flagged


def test_flagged_only_for_review_and_block():
    assert _model_flagged("BLOCK") is True
    assert _model_flagged("REVIEW") is True
    assert _model_flagged("ALLOW") is False


def test_agreement_true_positive_and_true_negative():
    # model flagged + analyst FRAUD -> agree
    assert model_agrees("BLOCK", "FRAUD") is True
    assert model_agrees("REVIEW", "FRAUD") is True
    # model allowed + analyst LEGIT -> agree
    assert model_agrees("ALLOW", "LEGIT") is True


def test_disagreement_false_positive_and_false_negative():
    # model flagged but analyst says LEGIT -> false positive -> disagree
    assert model_agrees("BLOCK", "LEGIT") is False
    assert model_agrees("REVIEW", "LEGIT") is False
    # model allowed but analyst says FRAUD -> false negative -> disagree
    assert model_agrees("ALLOW", "FRAUD") is False

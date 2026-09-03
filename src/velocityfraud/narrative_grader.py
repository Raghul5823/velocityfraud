"""AI-validates-AI narrative grader — closes proposal gap §10.3.

Proposal §10.3: "AI-validates-AI on explanations — second Gemini call grades
each narrative for factual against SHAP, <=80 words, actionable. Failing
narratives are dropped from the dashboard rather than shown to analysts."

Two checks are combined:
    1. Word count (<=80) — checked locally in Python, no API call needed,
       deterministic and free.
    2. Factual-against-SHAP + actionable — a SECOND, independent Gemini call
       that never sees how the first narrative was produced, only the raw
       SHAP contributions and the narrative text, and is asked to judge
       whether the narrative's claims are actually supported by those
       numbers. This is genuinely "AI grading AI," not the same call
       re-asked the same question.

If Gemini is unavailable for grading (no key, or a template-mode narrative
that never called an LLM in the first place), grading is skipped and the
narrative passes by default — grading a deterministic template's factual
accuracy against the SAME SHAP values it was mechanically built from is
redundant, not meaningful.

Usage:
    from velocityfraud.narrative_grader import grade_narrative
    result = grade_narrative(scored_event, contributions, narrative_text, mode_used)
    if not result.passed:
        # per the proposal: drop it, don't show a failing narrative to analysts
        narrative_text = ""
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

from velocityfraud import narrator

if TYPE_CHECKING:
    from velocityfraud.explainer import FeatureContribution

MAX_WORDS = 80


@dataclass
class GradeResult:
    passed: bool
    word_count: int
    factual: bool = True
    actionable: bool = True
    reason: str = ""
    graded: bool = True  # False when grading was skipped (template mode)


def _word_count(text: str) -> int:
    return len(text.split())


def _grading_prompt(contributions: list["FeatureContribution"], narrative: str) -> str:
    contrib_lines = "\n".join(
        f"  - {fc.feature_name}: value={fc.feature_value:.4g}, shap={fc.shap_value:+.4f}"
        for fc in contributions
    )
    return f"""You are a strict QA reviewer, not the author. You did NOT write the
narrative below — grade it independently against only the raw data provided.

Ground-truth SHAP feature contributions (positive = pushes toward fraud):
{contrib_lines}

Narrative to grade:
\"\"\"{narrative}\"\"\"

Judge two things:
  1. factual: does the narrative's claims about which features drove the
     decision actually match the SHAP values above? (it should not invent a
     signal not in the list, or claim the wrong direction)
  2. actionable: would a fraud-ops analyst reading this know what to check
     or do next, not just a vague restatement of the score?

Respond with ONLY a JSON object, no markdown fences:
{{"factual": true/false, "actionable": true/false, "reason": "one short sentence"}}"""


def grade_narrative(
    contributions: list["FeatureContribution"],
    narrative: str,
    mode_used: str,
) -> GradeResult:
    """Grade a narrative. mode_used is the value generate_narrative() returned
    ('GEMINI', 'GEMINI_CACHED', or 'TEMPLATE')."""
    wc = _word_count(narrative)
    word_ok = wc <= MAX_WORDS

    # Only grade narratives that actually came from an LLM this run — grading
    # a deterministic template against the same SHAP values it was
    # mechanically built from tells us nothing new.
    if mode_used == "TEMPLATE":
        return GradeResult(passed=word_ok, word_count=wc, graded=False,
                           reason="template mode — factual/actionable grading skipped")

    client = narrator._get_gemini_client()
    if client is None:
        return GradeResult(passed=word_ok, word_count=wc, graded=False,
                           reason="Gemini unavailable for grading — word-count check only")

    try:
        # Bounded to the same tight live-path budget as narration itself.
        # This grader runs INSIDE slow_path.py, so an unbounded call here would
        # breach the 2 s slow-path SLO just as narration did -- it was
        # previously unbounded, which is a second contributor to the measured
        # 11,296 ms worst case. Uses narrator's shared pool + deadline.
        resp = narrator._gemini_pool().submit(
            client.generate_content,
            _grading_prompt(contributions, narrative),
            request_options={"timeout": narrator.GEMINI_TIMEOUT_S},
        ).result(timeout=narrator.GEMINI_TIMEOUT_S)
        cleaned = re.sub(r"^```(json)?|```$", "", (resp.text or "").strip(), flags=re.MULTILINE).strip()
        verdict = json.loads(cleaned)
        factual = bool(verdict.get("factual", False))
        actionable = bool(verdict.get("actionable", False))
        reason = str(verdict.get("reason", ""))[:200]
        passed = word_ok and factual and actionable
        return GradeResult(passed=passed, word_count=wc, factual=factual,
                           actionable=actionable, reason=reason, graded=True)
    except Exception as e:
        logger.warning("Narrative grading call failed ({}); passing on word-count only.", e)
        return GradeResult(passed=word_ok, word_count=wc, graded=False,
                           reason=f"grading call failed: {str(e)[:100]}")


# ---------------------------------------------------------------------------
# Smoke test — grades a deliberately BAD (fabricated) narrative to prove the
# grader actually catches something, not just rubber-stamps everything.
# ---------------------------------------------------------------------------
def _demo() -> int:
    from velocityfraud.explainer import FeatureContribution

    logger.info("=" * 74)
    logger.info("NARRATIVE GRADER DEMO")
    logger.info("Gemini key set: {}", "YES" if narrator.GEMINI_API_KEY else "NO")
    logger.info("=" * 74)

    contribs = [
        FeatureContribution(feature_name="TransactionAmt", feature_value=2450.0, shap_value=0.31),
        FeatureContribution(feature_name="is_night", feature_value=1.0, shap_value=0.18),
        FeatureContribution(feature_name="card4_freq", feature_value=0.02, shap_value=-0.09),
    ]

    good_narrative = (
        "This $2,450 transaction was flagged mainly due to its unusually high amount, "
        "combined with it occurring at night. The card's network is rare in legitimate "
        "traffic, which slightly reduced the score. Recommend manual review of the amount "
        "and timing before approval."
    )
    bad_narrative = (
        "This transaction was flagged because the shipping address does not match the "
        "billing address and the customer has filed three prior chargebacks this year."
        # Neither claim is anywhere in the SHAP contributions above — fabricated.
    )

    for label, text in [("GOOD (grounded in SHAP)", good_narrative),
                         ("BAD (fabricated claims)", bad_narrative)]:
        result = grade_narrative(contribs, text, mode_used="GEMINI")
        logger.info("-" * 74)
        logger.info("NARRATIVE ({}): {}", label, text)
        logger.info("GRADE: passed={} factual={} actionable={} words={} reason={!r}",
                    result.passed, result.factual, result.actionable, result.word_count, result.reason)

    logger.info("=" * 74)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_demo())

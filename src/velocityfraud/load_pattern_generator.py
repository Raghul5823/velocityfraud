"""AI-generated load patterns — closes proposal gap §10.3 (docs/proposal_gap_remediation.md).

Proposal §10.3: "AI-generated load patterns — Gemini synthesises traffic
shapes (flash-sale spike, slow-leak DDoS, mixed-currency surge) used to drive
k6 scenarios; tests the architecture against patterns a hand-coded harness
wouldn't invent."

This module asks Gemini to design a k6 "stages" array (a sequence of
{duration_s, target_rate} steps) for each of the 3 named traffic shapes, then
writes them to perf/ai_load_patterns.json for perf/k6-ai-patterns.js to
consume. If Gemini is unavailable, a deterministic template shape is used
instead for each pattern (same fail-safe philosophy as narrator.py and
fraud_patterns.py) so this always produces a usable file.

Run:
    uv run python -m velocityfraud.load_pattern_generator
    # writes perf/ai_load_patterns.json
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from velocityfraud import narrator

OUTPUT_PATH = Path(__file__).resolve().parents[2] / "perf" / "ai_load_patterns.json"


@dataclass
class PatternSpec:
    name: str            # short key used by k6-ai-patterns.js (-e PATTERN=...)
    description: str     # what the pattern models, for the Gemini prompt
    peak_rate: int        # sane upper bound the generated shape must respect
    total_duration_s: int  # sane total duration the generated shape must respect


PATTERNS = [
    PatternSpec(
        name="flash_sale_spike",
        description=(
            "A flash-sale traffic spike: normal steady baseline traffic, then a sudden, "
            "sharp spike to peak load within seconds (shoppers all hitting checkout the "
            "instant a sale goes live), holding near peak briefly, then a fast taper back "
            "toward baseline as the initial rush subsides."
        ),
        peak_rate=300,
        total_duration_s=120,
    ),
    PatternSpec(
        name="slow_leak_ddos",
        description=(
            "A slow-leak DDoS-style ramp: traffic creeps up gradually and almost "
            "imperceptibly over a long period rather than spiking, designed to evade "
            "threshold-based alerting by never crossing an obvious single-step jump, "
            "eventually reaching a sustained elevated plateau well above normal baseline."
        ),
        peak_rate=250,
        total_duration_s=180,
    ),
    PatternSpec(
        name="mixed_currency_surge",
        description=(
            "A mixed-currency cross-border surge: multiple shorter bursts of moderate "
            "load in succession (representing waves of international traffic across "
            "different time zones/currencies going live in sequence), each burst rising "
            "and falling before the next begins, rather than one single sustained peak."
        ),
        peak_rate=200,
        total_duration_s=150,
    ),
]


def _template_stages(spec: PatternSpec) -> list[dict]:
    """Deterministic fallback shape — always available, no API needed."""
    d = spec.total_duration_s
    peak = spec.peak_rate
    if spec.name == "flash_sale_spike":
        return [
            {"duration_s": d // 6, "target_rate": peak // 10},
            {"duration_s": d // 12, "target_rate": peak},
            {"duration_s": d // 6, "target_rate": peak},
            {"duration_s": d // 3, "target_rate": peak // 8},
        ]
    if spec.name == "slow_leak_ddos":
        steps = 6
        return [{"duration_s": d // steps, "target_rate": int(peak * (i + 1) / steps)}
                for i in range(steps)]
    # mixed_currency_surge: 3 bursts
    burst_d = d // 6
    return [
        {"duration_s": burst_d, "target_rate": peak},
        {"duration_s": burst_d, "target_rate": peak // 6},
        {"duration_s": burst_d, "target_rate": int(peak * 0.8)},
        {"duration_s": burst_d, "target_rate": peak // 6},
        {"duration_s": burst_d, "target_rate": peak},
        {"duration_s": burst_d, "target_rate": peak // 6},
    ]


def _gemini_prompt(spec: PatternSpec) -> str:
    return f"""You design load-testing traffic shapes for a k6 script.

Pattern to model: {spec.name}
Description: {spec.description}

Output ONLY a JSON array (no prose, no markdown fences) of stage objects,
each with integer fields "duration_s" and "target_rate" (requests/second).
Constraints:
  - target_rate must never exceed {spec.peak_rate}
  - the sum of all duration_s must be close to {spec.total_duration_s} (+/- 20%)
  - use between 4 and 8 stages
  - target_rate must start low (baseline, not zero) and return to a low value
    at the end, consistent with the pattern description above

Example shape (illustrative format only, not the actual answer):
[{{"duration_s": 20, "target_rate": 10}}, {{"duration_s": 10, "target_rate": 150}}]"""


def _parse_gemini_stages(text: str, spec: PatternSpec) -> list[dict]:
    """Parse + validate Gemini's JSON response. Raises on anything unusable —
    the caller falls back to the template on any failure."""
    cleaned = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    stages = json.loads(cleaned)
    if not isinstance(stages, list) or not (2 <= len(stages) <= 12):
        raise ValueError(f"unexpected stage count: {len(stages) if isinstance(stages, list) else type(stages)}")
    out = []
    for s in stages:
        duration_s = int(s["duration_s"])
        target_rate = int(s["target_rate"])
        if duration_s <= 0:
            raise ValueError(f"non-positive duration_s: {duration_s}")
        # Clamp to the sane bound regardless of what Gemini said — never trust
        # an LLM's numeric output to be safe to run unmodified.
        target_rate = max(1, min(target_rate, spec.peak_rate))
        out.append({"duration_s": duration_s, "target_rate": target_rate})
    return out


def generate_pattern(spec: PatternSpec) -> dict:
    """Generate one pattern's k6 stages, Gemini-or-template."""
    client = narrator._get_gemini_client()
    if client is not None:
        try:
            resp = client.generate_content(_gemini_prompt(spec))
            stages = _parse_gemini_stages(resp.text or "", spec)
            mode = "GEMINI"
        except Exception as e:
            logger.warning("Gemini load-pattern generation failed for {} ({}); using template.",
                           spec.name, e)
            stages, mode = _template_stages(spec), "TEMPLATE"
    else:
        stages, mode = _template_stages(spec), "TEMPLATE"

    return {"name": spec.name, "description": spec.description, "mode": mode, "stages": stages}


def generate_all() -> dict:
    """Generate all 3 named patterns and write them to perf/ai_load_patterns.json."""
    result = {"patterns": [generate_pattern(spec) for spec in PATTERNS]}
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(result, indent=2))
    return result


def main() -> int:
    logger.info("=" * 74)
    logger.info("AI-GENERATED LOAD PATTERNS (proposal Section 10.3)")
    logger.info("Mode: {}", "GEMINI" if narrator.GEMINI_API_KEY else "TEMPLATE (set GEMINI_API_KEY for LLM)")
    logger.info("=" * 74)
    result = generate_all()
    for p in result["patterns"]:
        total_s = sum(s["duration_s"] for s in p["stages"])
        peak = max(s["target_rate"] for s in p["stages"])
        logger.info("-" * 74)
        logger.info("PATTERN : {}", p["name"])
        logger.info("MODE    : {}", p["mode"])
        logger.info("STAGES  : {} steps, ~{}s total, peak {} req/s", len(p["stages"]), total_s, peak)
    logger.info("=" * 74)
    logger.success("Wrote {} patterns to {}", len(result["patterns"]), OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

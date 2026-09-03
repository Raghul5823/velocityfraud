"""Unit tests for the AI-generated load pattern module (proposal §10.3).

Pure logic only -- no live infra, no real Gemini calls. The Gemini client is
monkeypatched at velocityfraud.narrator._get_gemini_client, the same seam
generate_pattern() itself reads from.
"""
from __future__ import annotations

import json

import pytest

from velocityfraud.load_pattern_generator import (
    PATTERNS,
    PatternSpec,
    _parse_gemini_stages,
    _template_stages,
    generate_all,
    generate_pattern,
)


# ---------------------------------------------------------------------------
# _template_stages -- deterministic fallback, always available
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("spec", PATTERNS, ids=lambda s: s.name)
def test_template_stages_respect_peak_rate(spec):
    stages = _template_stages(spec)
    assert stages, "template must always produce at least one stage"
    for s in stages:
        assert 0 <= s["target_rate"] <= spec.peak_rate
        assert s["duration_s"] > 0


@pytest.mark.parametrize("spec", PATTERNS, ids=lambda s: s.name)
def test_template_stages_duration_close_to_target(spec):
    stages = _template_stages(spec)
    total = sum(s["duration_s"] for s in stages)
    # Integer division in the template means it won't be exact -- just sane.
    assert total > 0
    assert total <= spec.total_duration_s


def test_template_stages_flash_sale_spikes_then_tapers():
    spec = next(s for s in PATTERNS if s.name == "flash_sale_spike")
    stages = _template_stages(spec)
    rates = [s["target_rate"] for s in stages]
    # Must reach peak, and end below peak (taper), matching the description.
    assert max(rates) == spec.peak_rate
    assert rates[-1] < spec.peak_rate


# ---------------------------------------------------------------------------
# _parse_gemini_stages -- validates + clamps untrusted LLM output
# ---------------------------------------------------------------------------
def test_parse_gemini_stages_valid_json():
    spec = PATTERNS[0]
    text = json.dumps([
        {"duration_s": 10, "target_rate": 5},
        {"duration_s": 20, "target_rate": spec.peak_rate // 2},
        {"duration_s": 10, "target_rate": 5},
    ])
    stages = _parse_gemini_stages(text, spec)
    assert len(stages) == 3
    assert all(isinstance(s["duration_s"], int) and isinstance(s["target_rate"], int)
               for s in stages)


def test_parse_gemini_stages_strips_markdown_fence():
    spec = PATTERNS[0]
    raw = json.dumps([{"duration_s": 5, "target_rate": 1}, {"duration_s": 5, "target_rate": 1}])
    fenced = f"```json\n{raw}\n```"
    stages = _parse_gemini_stages(fenced, spec)
    assert len(stages) == 2


def test_parse_gemini_stages_clamps_target_rate_never_trusts_llm():
    """A key safety property: whatever Gemini says, target_rate is clamped to
    the spec's sane bound before this data ever drives real traffic against
    the API."""
    spec = PATTERNS[0]
    text = json.dumps([
        {"duration_s": 10, "target_rate": spec.peak_rate * 100},  # absurd
        {"duration_s": 10, "target_rate": -50},                    # negative
    ])
    stages = _parse_gemini_stages(text, spec)
    assert stages[0]["target_rate"] == spec.peak_rate
    assert stages[1]["target_rate"] == 1  # clamped to the floor, not negative


def test_parse_gemini_stages_rejects_too_few_stages():
    spec = PATTERNS[0]
    with pytest.raises(ValueError):
        _parse_gemini_stages(json.dumps([{"duration_s": 5, "target_rate": 1}]), spec)


def test_parse_gemini_stages_rejects_non_positive_duration():
    spec = PATTERNS[0]
    text = json.dumps([{"duration_s": 0, "target_rate": 1}, {"duration_s": 5, "target_rate": 1}])
    with pytest.raises(ValueError):
        _parse_gemini_stages(text, spec)


def test_parse_gemini_stages_rejects_non_list():
    spec = PATTERNS[0]
    with pytest.raises(ValueError):
        _parse_gemini_stages(json.dumps({"not": "a list"}), spec)


# ---------------------------------------------------------------------------
# generate_pattern -- Gemini-or-template seam
# ---------------------------------------------------------------------------
def test_generate_pattern_falls_back_to_template_with_no_client(monkeypatch):
    monkeypatch.setattr(
        "velocityfraud.load_pattern_generator.narrator._get_gemini_client",
        lambda: None,
    )
    result = generate_pattern(PATTERNS[0])
    assert result["mode"] == "TEMPLATE"
    assert result["stages"]


def test_generate_pattern_uses_gemini_when_available(monkeypatch):
    spec = PATTERNS[1]
    good_json = json.dumps([
        {"duration_s": 10, "target_rate": 5},
        {"duration_s": 10, "target_rate": 20},
        {"duration_s": 10, "target_rate": 5},
    ])

    class FakeResponse:
        text = good_json

    class FakeClient:
        def generate_content(self, prompt):
            assert spec.name in prompt  # the real prompt is per-pattern
            return FakeResponse()

    monkeypatch.setattr(
        "velocityfraud.load_pattern_generator.narrator._get_gemini_client",
        lambda: FakeClient(),
    )
    result = generate_pattern(spec)
    assert result["mode"] == "GEMINI"
    assert len(result["stages"]) == 3


def test_generate_pattern_falls_back_on_gemini_exception(monkeypatch):
    class FakeClient:
        def generate_content(self, prompt):
            raise RuntimeError("simulated Gemini outage")

    monkeypatch.setattr(
        "velocityfraud.load_pattern_generator.narrator._get_gemini_client",
        lambda: FakeClient(),
    )
    result = generate_pattern(PATTERNS[0])
    assert result["mode"] == "TEMPLATE"
    assert result["stages"]


def test_generate_pattern_falls_back_on_unparseable_response(monkeypatch):
    class FakeResponse:
        text = "not json at all"

    class FakeClient:
        def generate_content(self, prompt):
            return FakeResponse()

    monkeypatch.setattr(
        "velocityfraud.load_pattern_generator.narrator._get_gemini_client",
        lambda: FakeClient(),
    )
    result = generate_pattern(PATTERNS[0])
    assert result["mode"] == "TEMPLATE"


# ---------------------------------------------------------------------------
# generate_all -- writes the real output file
# ---------------------------------------------------------------------------
def test_generate_all_writes_all_three_patterns(monkeypatch, tmp_path):
    out_file = tmp_path / "ai_load_patterns.json"
    monkeypatch.setattr("velocityfraud.load_pattern_generator.OUTPUT_PATH", out_file)
    monkeypatch.setattr(
        "velocityfraud.load_pattern_generator.narrator._get_gemini_client",
        lambda: None,  # force template mode -- deterministic, no network
    )
    result = generate_all()
    assert len(result["patterns"]) == len(PATTERNS)
    assert out_file.exists()
    on_disk = json.loads(out_file.read_text())
    assert [p["name"] for p in on_disk["patterns"]] == [p.name for p in PATTERNS]

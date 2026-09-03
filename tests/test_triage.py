"""Service invariants. No network — these guard the config contract, not the model."""

import pytest

from graph.retrieve import Context
from triage.agent import build_prompt, sampling_is_honoured
from triage.config import TriageConfig
from triage.configs import CONFIGS, LABELLER
from triage.models import OUTPUT_SCHEMAS, TriageDecision, to_decision


def test_config_hash_is_stable_across_instances():
    assert TriageConfig().config_hash == TriageConfig().config_hash


def test_name_does_not_affect_the_hash():
    """Renaming a config must not make it look like a different one."""
    a = TriageConfig(name="a")
    b = TriageConfig(name="b")
    assert a.config_hash == b.config_hash


@pytest.mark.parametrize("field,value", [
    ("model", "other/model"),
    ("prompt_version", "v1_terse"),
    ("rationale_mode", "pre"),
    ("context", "none"),
    ("temperature", 0.7),
])
def test_every_behavioural_knob_changes_the_hash(field, value):
    base = TriageConfig()
    assert base.model_copy(update={field: value}).config_hash != base.config_hash


def test_hash_covers_prompt_content_not_just_its_name(tmp_path, monkeypatch):
    """Editing a prompt file must change the hash, or two incomparable runs look comparable."""
    import triage.config as cfgmod

    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "vX.md").write_text("first")
    monkeypatch.setattr(cfgmod, "PROMPTS", prompts)

    before = TriageConfig(prompt_version="vX").config_hash
    (prompts / "vX.md").write_text("second")
    after = TriageConfig(prompt_version="vX").config_hash
    assert before != after


def test_unknown_prompt_version_fails_loudly():
    with pytest.raises(FileNotFoundError):
        TriageConfig(prompt_version="does-not-exist").prompt_text


# --- elicitation schemas ---------------------------------------------------

def test_rationale_mode_controls_field_order_not_just_presence():
    """Models emit JSON in schema order, so order is what makes reasoning precede the decision."""
    assert list(OUTPUT_SCHEMAS["pre"].model_fields)[0] == "rationale"
    assert list(OUTPUT_SCHEMAS["post"].model_fields)[-1] == "rationale"
    assert "rationale" not in OUTPUT_SCHEMAS["off"].model_fields


def test_off_schema_still_normalises_to_a_decision():
    raw = OUTPUT_SCHEMAS["off"](category="bug", urgency="P2", needs_human=False)
    assert to_decision(raw).rationale == ""


# --- scoring primitives ----------------------------------------------------

def test_urgency_distance_is_ordinal():
    d = TriageDecision(category="bug", urgency="P0", needs_human=True)
    assert d.distance(d.model_copy(update={"urgency": "P1"}))["urgency"] == 1
    assert d.distance(d.model_copy(update={"urgency": "P3"}))["urgency"] == 3


def test_category_distance_is_flat():
    d = TriageDecision(category="bug", urgency="P2", needs_human=False)
    assert d.distance(d.model_copy(update={"category": "docs"}))["category"] == 1


# --- prompt assembly -------------------------------------------------------

def test_empty_context_is_omitted_from_the_prompt():
    empty = Context(text="", reason="nothing matched")
    assert "Repository context" not in build_prompt("t", "b", empty, 1000)


def test_body_is_truncated_to_the_configured_cap():
    out = build_prompt("t", "x" * 5000, None, 100)
    assert "truncated" in out and len(out) < 1000


def test_empty_issue_still_produces_a_usable_prompt():
    out = build_prompt("", "", None, 100)
    assert "(empty)" in out


# --- the rules that protect the comparison ---------------------------------

def test_labeller_is_not_in_the_config_space():
    """DECISIONS.md D3: a model that produced the labels is correct by construction."""
    assert all(c.model != LABELLER for c in CONFIGS.values())


@pytest.mark.skipif(
    not __import__("os").environ.get("OPENROUTER_API_KEY")
    and not (__import__("pathlib").Path(".env").exists()),
    reason="needs OPENROUTER_API_KEY for the provider profile lookup",
)
def test_no_config_uses_a_model_whose_temperature_is_silently_dropped():
    """DECISIONS.md D19: mixed temperature handling would confound the tier comparison."""
    for name, c in CONFIGS.items():
        assert sampling_is_honoured(c.model), f"{name} ({c.model}) drops temperature"

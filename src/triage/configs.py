"""Named configurations the harness compares.

Model ids avoid the `openai/` prefix deliberately: pydantic-ai's profile treats every
such id as a reasoning model and silently drops `temperature`, which would leave one
arm of a model-tier comparison running at provider default while the other runs at 0
(DECISIONS.md D19). All models here honour sampling settings.

LABELLER is excluded from this set by rule (DECISIONS.md D3) — a model that produced
the labels is correct by construction and would score near 100%, destroying the
comparison the harness most needs to make.
"""

from __future__ import annotations

from .config import TriageConfig

# The frontier model that produces gold labels. Barred from evaluation.
LABELLER = "anthropic/claude-sonnet-5"

# Price per million tokens at time of selection, for orientation only — actual cost
# comes from the gateway per call and is never estimated from this table.
#
# Capped at gemini-2.5-flash rather than reaching for claude-haiku-4.5, keeping the
# cheapest rung to hold the spread open: 15.8x on input, 83x on output. Output is the
# dearer side and the one rationale_mode moves, so the axis that matters stays wide.
TIERS = {
    "cheap": ("mistralai/mistral-nemo",       0.019, 0.030),
    "small": ("google/gemini-2.5-flash-lite", 0.100, 0.400),
    "mid":   ("google/gemini-2.5-flash",      0.300, 2.500),
}

BASELINE = TriageConfig(
    name="baseline",
    model=TIERS["small"][0],
    prompt_version="v2_rubric",
    rationale_mode="post",
    context="graph",
)


def _variant(name: str, **kw) -> TriageConfig:
    return BASELINE.model_copy(update={"name": name, **kw})


CONFIGS: dict[str, TriageConfig] = {
    "baseline": BASELINE,
    # model tier — the headline cost experiment (~50x input price across the ladder)
    **{f"tier-{t}": _variant(f"tier-{t}", model=m) for t, (m, _, _) in TIERS.items()},
    # prompt: does handing the model the labelling rubric earn its tokens?
    "prompt-terse": _variant("prompt-terse", prompt_version="v1_terse"),
    # rationale placement: reasoning before deciding costs output tokens, the dear ones
    "rationale-pre": _variant("rationale-pre", rationale_mode="pre"),
    "rationale-off": _variant("rationale-off", rationale_mode="off"),
    # the one-off assumption check (SPEC.md §5.1) — not a permanent axis
    "context-none": _variant("context-none", context="none"),
}


def get(name: str) -> TriageConfig:
    if name not in CONFIGS:
        raise KeyError(f"unknown config '{name}'. known: {', '.join(sorted(CONFIGS))}")
    return CONFIGS[name]

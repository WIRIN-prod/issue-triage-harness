"""Triage output schema.

The `Literal` types are the reason there is no LLM judge in the eval loop
(SPEC.md §5.6): they close the output space, so scoring is `==` rather than a
semantic comparison. A value outside the enum fails validation, and that failure
is itself a signal the harness counts rather than silently repairs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["bug", "feature", "docs", "question", "security"]
Urgency = Literal["P0", "P1", "P2", "P3"]

URGENCY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


class TriageDecision(BaseModel):
    """The canonical decision, independent of how it was elicited."""

    category: Category
    urgency: Urgency
    needs_human: bool
    rationale: str = ""

    def distance(self, other: TriageDecision) -> dict[str, int]:
        """Field-wise error against a reference label. Ordinal distance for urgency."""
        return {
            "category": int(self.category != other.category),
            "urgency": abs(URGENCY_RANK[self.urgency] - URGENCY_RANK[other.urgency]),
            "needs_human": int(self.needs_human != other.needs_human),
        }


# --- elicitation variants -------------------------------------------------
# Field order is load-bearing. Models emit JSON keys in schema order, so putting
# `rationale` first genuinely forces reasoning to be produced *before* the
# decision, and putting it last makes it a post-hoc explanation of a decision
# already made. `off` removes it entirely. That is the whole rationale_mode
# experiment, expressed as three schemas rather than three prompts.


class _Pre(BaseModel):
    rationale: str = Field(description="Reason step by step, then decide.")
    category: Category
    urgency: Urgency
    needs_human: bool


class _Post(BaseModel):
    category: Category
    urgency: Urgency
    needs_human: bool
    rationale: str = Field(description="Briefly explain the decision above.")


class _Off(BaseModel):
    category: Category
    urgency: Urgency
    needs_human: bool


OUTPUT_SCHEMAS = {"pre": _Pre, "post": _Post, "off": _Off}


HIGH_URGENCY = ("P0", "P1")

# Categories the rubric makes unconditional. `security` is stated outright ("any security
# report -> true, always"). `question` follows from the rubric's own fallback: an empty or
# unintelligible issue is categorised `question`, and insufficient information is escalation
# trigger A. That second one is a chain rather than a quotation, so it was checked against
# both splits before being trusted: 15/15 dev and 8/9 holdout are needs_human.
#
# `feature` was considered and rejected — only 70% in gold, so forcing it would be tuning on
# the dev set rather than reading the rubric back.
ALWAYS_ESCALATE = ("security", "question")


def enforce_rubric(d: TriageDecision, version: str = "v2") -> TriageDecision:
    """Force needs_human where the model's own answer says the rubric requires it.

    The prompt lists "any P0 or P1" and "any security report" as unconditional escalation
    triggers. When the model returns those alongside needs_human=False it is contradicting
    the instruction it was given — a different failure from disagreeing with the labels, and
    unlike that one it has a free deterministic fix: no extra call, token, or millisecond,
    and it can only move needs_human toward true.
    """
    if version == "off":
        return d
    must = d.urgency in HIGH_URGENCY
    if version == "v2":
        must = must or d.category in ALWAYS_ESCALATE
    if must and not d.needs_human:
        return d.model_copy(update={"needs_human": True})
    return d


def to_decision(raw: BaseModel) -> TriageDecision:
    d = raw.model_dump()
    return TriageDecision(
        category=d["category"],
        urgency=d["urgency"],
        needs_human=d["needs_human"],
        rationale=d.get("rationale", ""),
    )


class TriageRun(BaseModel):
    """One decision plus everything the harness needs to price and reproduce it."""

    issue_number: int
    decision: TriageDecision

    model: str
    config_hash: str
    prompt_version: str
    context_mode: str
    context_tokens: int = 0
    context_empty: bool = False

    temperature: float = 0.0
    temperature_applied: bool = True   # False when the provider profile drops sampling params

    tokens_in: int
    tokens_out: int
    cost_usd: float          # reported by the gateway, not estimated from a table
    cost_reported: bool = True   # False when the gateway returned no cost — see agent._cost
    latency_ms: int
    attempts: int = 1        # >1 means transient failures were retried

    error: str = ""          # set when the call or validation failed

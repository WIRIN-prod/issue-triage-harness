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

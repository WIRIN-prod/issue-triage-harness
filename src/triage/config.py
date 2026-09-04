"""The configuration object that fully determines service behaviour.

SPEC.md §4.3: the service is a pure function of (issue, repo_graph, config). If
behaviour can change from outside this object, a measured difference cannot be
attributed to a cause and every comparison the harness produces is unsound.

The hash covers **prompt content, not the prompt's name** — otherwise editing a
prompt file would change behaviour while the hash stayed put, and two runs that
are not comparable would look comparable.
"""

from __future__ import annotations

import hashlib
import json
from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

PROMPTS = Path(__file__).parent / "prompts"

RationaleMode = Literal["pre", "post", "off"]
ContextMode = Literal["graph", "none"]


class TriageConfig(BaseModel):
    model_config = {"frozen": True}

    name: str = "default"
    model: str = "openai/gpt-4o-mini"       # OpenRouter model id
    prompt_version: str = "v2_rubric"
    rationale_mode: RationaleMode = "post"
    context: ContextMode = "graph"
    temperature: float = 0.0
    # Enforce the model's own rubric after the fact: the prompt states that any P0 or P1
    # must escalate, and baseline violates that on 44% of its own P0/P1 predictions
    # (`harness errors`). This is post-processing, not a prompt change — no extra call,
    # no extra token, and it only ever moves needs_human toward true.
    enforce_rubric: bool = False
    context_budget_tokens: int = 1500
    max_body_chars: int = 6000
    # OpenRouter can route one model id to different backends; pinning keeps a
    # config from silently changing behaviour between runs (DECISIONS.md D12).
    provider_order: tuple[str, ...] = ()
    allow_fallbacks: bool = False

    @cached_property
    def prompt_text(self) -> str:
        path = PROMPTS / f"{self.prompt_version}.md"
        if not path.is_file():
            raise FileNotFoundError(f"unknown prompt version: {self.prompt_version}")
        return path.read_text()

    @cached_property
    def config_hash(self) -> str:
        payload = {
            **self.model_dump(exclude={"name"}),
            "prompt_sha256": hashlib.sha256(self.prompt_text.encode()).hexdigest(),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def describe(self) -> str:
        return (f"{self.name} [{self.config_hash}] {self.model} "
                f"prompt={self.prompt_version} rationale={self.rationale_mode} "
                f"context={self.context} temp={self.temperature}")

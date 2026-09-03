"""The triage service: (issue, context, config) -> TriageRun.

Deliberately small. It exists to be a realistic subject of measurement, not to be
clever. Everything that can change its behaviour lives in TriageConfig, and every
call reports what it cost, because the harness cannot price a change the service
does not measure.
"""

from __future__ import annotations

import time
import warnings
from functools import lru_cache

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from graph.retrieve import Context

from .config import TriageConfig
from .models import OUTPUT_SCHEMAS, TriageDecision, TriageRun, to_decision

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def sampling_is_honoured(model_id: str) -> bool:
    """Will `temperature` actually reach the provider for this model?

    pydantic-ai drops sampling parameters for models whose profile says reasoning is
    on by default, and its profile matches on the id prefix — so every OpenRouter id
    beginning `openai/` is treated as a reasoning model, gpt-4o-mini included. Other
    prefixes keep temperature.

    That asymmetry would confound the model-tier experiment: one config would run at
    temperature 0 and another at the provider default, and the difference would be
    attributed to the model. The harness refuses to compare across it (see
    TriageRun.temperature_applied) rather than letting it pass silently.
    """
    from harness.settings import openrouter_key

    provider = OpenAIProvider(base_url=OPENROUTER_BASE, api_key=openrouter_key())
    profile = OpenAIChatModel(model_id, provider=provider).profile
    if not profile.get("openai_supports_reasoning", False):
        return True
    return bool(profile.get("openai_supports_reasoning_effort_none", False))


@lru_cache(maxsize=8)
def _agent(config_hash: str, model_id: str, prompt: str, mode: str) -> Agent:
    """One Agent per distinct config. Cached because construction is not free."""
    from harness.settings import openrouter_key

    provider = OpenAIProvider(base_url=OPENROUTER_BASE, api_key=openrouter_key())
    return Agent(
        OpenAIChatModel(model_id, provider=provider),
        output_type=OUTPUT_SCHEMAS[mode],
        system_prompt=prompt,
    )


def build_prompt(title: str, body: str, context: Context | None, max_body: int) -> str:
    body = (body or "").strip()
    truncated = len(body) > max_body
    if truncated:
        body = body[:max_body] + "\n[…truncated]"

    parts = [f"# Issue title\n{title.strip() or '(empty)'}",
             f"\n# Issue body\n{body or '(empty)'}"]
    if context is not None and not context.is_empty:
        parts.append(f"\n# Repository context\n{context.text}")
    return "\n".join(parts)


def _settings(config: TriageConfig) -> OpenAIChatModelSettings:
    extra: dict = {"usage": {"include": True}}   # OpenRouter returns real cost with this
    if config.provider_order or not config.allow_fallbacks:
        extra["provider"] = {"allow_fallbacks": config.allow_fallbacks}
        if config.provider_order:
            extra["provider"]["order"] = list(config.provider_order)
    return OpenAIChatModelSettings(temperature=config.temperature, extra_body=extra)


def _cost(usage) -> float:
    if getattr(usage, "cost", None):
        return float(usage.cost)
    details = getattr(usage, "details", None) or {}
    for key in ("cost", "total_cost", "upstream_inference_cost"):
        if details.get(key):
            return float(details[key])
    return 0.0


def triage(
    issue_number: int,
    title: str,
    body: str,
    config: TriageConfig,
    context: Context | None = None,
) -> TriageRun:
    if config.context == "none":
        context = None

    prompt = build_prompt(title, body, context, config.max_body_chars)
    agent = _agent(config.config_hash, config.model, config.prompt_text, config.rationale_mode)

    honoured = sampling_is_honoured(config.model)
    base = dict(
        issue_number=issue_number,
        temperature=config.temperature,
        temperature_applied=honoured,
        model=config.model,
        config_hash=config.config_hash,
        prompt_version=config.prompt_version,
        context_mode=config.context,
        context_tokens=(context.est_tokens if context else 0),
        context_empty=(context is None or context.is_empty),
    )

    t0 = time.perf_counter()
    try:
        with warnings.catch_warnings():   # the drop is detected above and recorded, not news
            warnings.filterwarnings("ignore", message=".*Sampling parameters.*")
            result = agent.run_sync(prompt, model_settings=_settings(config))
    except Exception as exc:  # network, rate limit, schema violation
        return TriageRun(
            **base,
            decision=TriageDecision(category="question", urgency="P3", needs_human=True),
            tokens_in=0, tokens_out=0, cost_usd=0.0,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            error=f"{type(exc).__name__}: {exc}"[:300],
        )
    latency_ms = int((time.perf_counter() - t0) * 1000)

    usage = result.usage
    return TriageRun(
        **base,
        decision=to_decision(result.output),
        tokens_in=usage.input_tokens or 0,
        tokens_out=usage.output_tokens or 0,
        cost_usd=_cost(usage),
        latency_ms=latency_ms,
    )

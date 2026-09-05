"""The triage service: (issue, context, config) -> TriageRun.

Deliberately small. It exists to be a realistic subject of measurement, not to be
clever. Everything that can change its behaviour lives in TriageConfig, and every
call reports what it cost, because the harness cannot price a change the service
does not measure.
"""

from __future__ import annotations

import random
import time
import warnings
from functools import lru_cache

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from graph.retrieve import Context

from .config import TriageConfig
from .models import (OUTPUT_SCHEMAS, TriageDecision, TriageRun,
                     enforce_rubric, to_decision)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# Concurrency produces transient connection failures against the gateway — 3/40 at 8
# workers, far worse for slower models that hold connections longer. Left unhandled
# these silently thinned a 100-issue labelling run down to 20 survivors, so they are
# retried rather than counted as verdicts.
RETRYABLE = ("connection", "timeout", "timed out", "429", "500", "502", "503", "504",
             "overloaded", "rate limit")
MAX_ATTEMPTS = 5

# Rate limits get the same exponential ramp as everything else, with a higher ceiling.
#
# An earlier version waited a flat 25s on every 429, on the theory that a
# "new-account-rpm" cap polices a 60-second window. Measurement disagreed: the account
# sustains ~60 req/min single-worker and ~97/min at 6 workers, and 429s clear in about
# a second. The flat wait turned a mild throttle into a sweep that would have taken 17
# hours — most items burning their whole retry budget at 25s a go. Backing off *longer*
# than the limit requires is not the safe direction; it is just slower.
RATE_LIMIT_CAP = 20.0


def _is_rate_limit(exc: Exception) -> bool:
    text = f"{exc}".lower()
    return "429" in text or "rate limit" in text


def _backoff(exc: Exception, attempt: int) -> float:
    ceiling = RATE_LIMIT_CAP if _is_rate_limit(exc) else 16.0
    return min(2 ** attempt, ceiling) * (0.5 + random.random())


def _is_retryable(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(x in text for x in ("400", "401", "402", "403", "404")):
        return False        # bad request, auth, or funding — retrying cannot help
    return any(x in text for x in RETRYABLE)


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
        # pydantic-ai allows a single retry by default, which surfaced as
        # "Exceeded maximum output retries (1)" whenever a model fumbled the schema
        # once. Two more attempts cost little and recover most of them.
        retries=3,
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


def is_free_model(model_id: str) -> bool:
    """OpenRouter marks genuinely-free variants with a `:free` suffix.

    This matters because "$0 because the model is free" and "$0 because the gateway
    told us nothing" are different facts that look identical in a cost column. The
    first is a real measurement; the second is a hole (D28).
    """
    return model_id.endswith(":free")


def _cost(usage) -> tuple[float, bool]:
    """Actual spend for this call, and whether the gateway actually told us.

    Not every model reports cost — `x-ai/grok-4.6` returned none while the account was
    charged $0.29 for 25 calls. Falling back to 0.0 silently made that config look free
    in a metric denominated in dollars, which is the worst possible direction for the
    error to run. The flag makes the gap visible so a run priced at zero is not mistaken
    for a run that cost nothing.
    """
    if getattr(usage, "cost", None):
        return float(usage.cost), True
    details = getattr(usage, "details", None) or {}
    for key in ("cost", "total_cost", "upstream_inference_cost"):
        if details.get(key):
            return float(details[key]), True
    return 0.0, False


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
    result, last_error, attempts = None, None, 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempts = attempt
        try:
            with warnings.catch_warnings():   # the drop is detected above, not news
                warnings.filterwarnings("ignore", message=".*Sampling parameters.*")
                result = agent.run_sync(prompt, model_settings=_settings(config))
            break
        except Exception as exc:
            last_error = exc
            if attempt == MAX_ATTEMPTS or not _is_retryable(exc):
                break
            time.sleep(_backoff(exc, attempt))

    if result is None:
        return TriageRun(
            **base,
            decision=TriageDecision(category="question", urgency="P3", needs_human=True),
            tokens_in=0, tokens_out=0, cost_usd=0.0,
            latency_ms=int((time.perf_counter() - t0) * 1000), attempts=attempts,
            error=f"{type(last_error).__name__}: {last_error}"[:300],
        )
    latency_ms = int((time.perf_counter() - t0) * 1000)

    decision = to_decision(result.output)
    if config.enforce_rubric != "off":
        decision = enforce_rubric(decision, config.enforce_rubric)

    usage = result.usage
    cost, reported = _cost(usage)
    if not reported and is_free_model(config.model):
        cost, reported = 0.0, True      # genuinely free, not unknown
    return TriageRun(
        **base,
        decision=decision,
        tokens_in=usage.input_tokens or 0,
        tokens_out=usage.output_tokens or 0,
        cost_usd=cost,
        cost_reported=reported,
        latency_ms=latency_ms,
        attempts=attempts,
    )

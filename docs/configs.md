# Configurations

Every config is a value of `TriageConfig`, and the service is a pure function of
`(issue, repo_graph, config)`. Behaviour cannot change from outside this object — if it
could, a measured difference could not be attributed to a cause and every comparison
would be unsound (SPEC.md §4.3).

The hash covers **prompt content, not the prompt's filename**, so editing a prompt file
changes the hash. Two runs that are not comparable can never look comparable.

## The knobs

| knob | values | what it controls |
|---|---|---|
| `model` | any OpenRouter id | which model answers |
| `prompt_version` | `v1_terse` \| `v2_rubric` | how much instruction the model gets |
| `rationale_mode` | `pre` \| `post` \| `off` | whether reasoning precedes, follows, or is absent |
| `context` | `graph` \| `none` | whether repo knowledge is retrieved and injected |
| `temperature` | float | sampling; see D19 — silently dropped for `openai/*` ids |

`rationale_mode` is implemented as **three output schemas, not three prompts**. Models
emit JSON keys in schema order, so putting `rationale` first genuinely forces reasoning
before the decision and putting it last makes it a post-hoc explanation. That is a
mechanism, not a request.

## The configs

Each differs from `baseline` by **exactly one knob**, so a measured delta has one
candidate cause. One-factor-at-a-time costs more runs than a factorial design but buys
attributable results, which is what the harness exists for.

| config | changed from baseline | question it answers |
|---|---|---|
| **baseline** | — | the incumbent: flash-lite, full rubric, post-hoc rationale, graph context |
| **tier-small** | *nothing* — identical hash | free determinism check: two independent runs of one config |
| **tier-cheap** | model → `mistral-nemo` | is a 5x cheaper model good enough? |
| **tier-mid** | model → `gemini-2.5-flash` | is a 3.4x dearer model worth it? |
| **prompt-terse** | prompt → `v1_terse` | does handing the model the full rubric earn its ~690 extra input tokens? |
| **rationale-pre** | rationale → `pre` | does reasoning *before* deciding improve the decision, at ~2x the output tokens? |
| **rationale-off** | rationale → `off` | does dropping the explanation entirely cost any quality? |
| **context-none** | context → `none` | is repo context worth its ~1,050 tokens? (one-off assumption check, SPEC.md §5.1) |
| **free-minimax** | model → `minimax/minimax-m3:free` | can a free model from another provider compete? |
| **free-liquid** | model → `liquid/lfm-2.5-2.6b:free` | can a 2.6B free model compete? |
| **free-nvidia** | model → `nvidia/nemotron-3-super-120b-a12b:free` | can a large free model compete? |

`tier-small` deserves a note. It is `baseline` under a different name, and since the
config *name* is excluded from the hash, the two are the same config. Running both gives
two independent samples of one configuration for free — which is precisely the
run-to-run variance measurement needed to know whether any other difference is noise.
Their dev scores match to four decimal places.

## The model ladder

| tier | model | $/M in | $/M out |
|---|---|---|---|
| cheap | `mistralai/mistral-nemo` | 0.019 | 0.030 |
| small | `google/gemini-2.5-flash-lite` | 0.100 | 0.400 |
| mid | `google/gemini-2.5-flash` | 0.300 | 2.500 |
| free | MiniMax / Liquid / NVIDIA `:free` | 0.000 | 0.000 |

15.8x on input, 83x on output across the paid ladder — and the free tier takes the cost
axis to zero, where the flagship metric becomes **pure error cost**.

## Rules that constrain the config space

**The labeller is excluded.** `anthropic/claude-sonnet-5` produced the gold labels, so
evaluating it as a service config would score it near 100% by construction and destroy
the comparison the harness most needs to make (D3). A test asserts no config uses it.

**No `openai/*` ids.** pydantic-ai matches model profiles by prefix and treats every
`openai/` id as a reasoning model, silently dropping `temperature` — including for
`gpt-4o-mini`, which is not one. Mixing them with other providers would run one arm at
temperature 0 and the other at the provider default, and the difference would be blamed
on the model (D19). A test asserts every config honours sampling settings.

**`:free` is genuinely zero, not unknown.** Free models report no cost field. "$0 because
the model is free" and "$0 because the gateway said nothing" look identical in a cost
column but are different facts — the first is a measurement, the second is a hole. The
`:free` suffix settles it, and `compare` refuses runs whose costs are merely unknown (D28).

## Adding one

```python
CONFIGS["my-variant"] = BASELINE.model_copy(update={"name": "my-variant", "model": "..."})
```

Then `harness sweep --configs my-variant` and `harness compare <a> <b>`. Nothing else
needs to change: the runner, metrics, and comparison are indifferent to which provider
answered, because everything they need — tokens, cost, latency, the decision — comes back
in the same envelope.

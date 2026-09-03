# Results — dev split, n=60

**Dataset** `f383db39072f4a10` · 60 dev items · rubric v1 · labeller `claude-sonnet-5`
**Sweep** 8 configs, 480 calls, 0 failures, **$0.157**

Every number below is from `harness sweep` and `harness compare` on committed run records.

## The floor comes first

Trivial strategies, scored against the same labels (`harness baselines --split dev`):

| baseline | macro-F1 | accuracy | error weight/issue |
|---|---|---|---|
| majority-per-field / escalate-everything | 0.133 | 0.50 | **2.27** |
| never-escalate | 0.133 | 0.50 | 8.60 |
| random | 0.197 | 0.20 | 6.87 |

`needs_human` is 69% positive and a missed escalation costs 10x an unnecessary one, so
**escalating everything is a strong policy**. That is the cost model being honest, and it sets
the bar. Reading config numbers without it makes mediocre look good.

## Configs

| config | model | macro-F1 | urg MAE | nh recall | nh prec | err wt | $/issue | p50 ms |
|---|---|---|---|---|---|---|---|---|
| baseline | gemini-2.5-flash-lite | 0.868 | 0.43 | 0.75 | 0.97 | 2.32 | $0.00029 | 2003 |
| tier-small | gemini-2.5-flash-lite | 0.868 | 0.43 | 0.75 | 0.97 | 2.32 | $0.00030 | 1698 |
| tier-mid | gemini-2.5-flash | 0.867 | 0.55 | 0.82 | 0.82 | **2.08** | $0.00099 | 2027 |
| tier-cheap | mistral-nemo | 0.892 | 0.57 | **0.25** | 1.00 | 5.80 | $0.00003 | 3662 |
| context-none | gemini-2.5-flash-lite | **0.898** | **0.38** | 0.65 | 1.00 | 2.90 | $0.00022 | 1875 |
| prompt-terse | gemini-2.5-flash-lite | 0.795 | 0.63 | 0.82 | 0.79 | 2.40 | $0.00022 | 1604 |
| rationale-pre | gemini-2.5-flash-lite | 0.878 | 0.50 | 0.62 | 0.96 | 3.23 | $0.00032 | 2039 |
| rationale-off | gemini-2.5-flash-lite | 0.868 | 0.48 | 0.78 | 0.84 | 2.33 | $0.00025 | 1176 |

**Only `tier-mid` beats the 2.27 floor**, and not significantly. Every config scores macro-F1
0.79–0.90 against the floor's 0.133, so the models are doing real classification work — it is
simply swamped by escalation errors in the flagship.

## What the harness will and will not conclude

Paired bootstrap, 4,000 resamples, 95% CI, `baseline` as A:

| vs | flagship Δ | 95% CI | verdict |
|---|---|---|---|
| tier-mid | −0.233 | [−0.933, +0.367] | **no significant difference** (needs ~465 items) |
| tier-cheap | +3.483 | [+2.266, +4.816] | **baseline better** |
| context-none | +0.583 | [−0.000, +1.267] | no significant difference (needs ~77 items) |
| prompt-terse | +0.083 | [−0.917, +1.017] | no significant difference (effect ≈ 0) |
| rationale-pre | +0.917 | [+0.283, +1.667] | **baseline better** |
| rationale-off | +0.017 | [−0.383, +0.333] | no significant difference (effect ≈ 0) |

**Four of six comparisons are inconclusive at n=60.** That is the harness working. Most of these
are differences a team would ship on a vibe.

## The headline trade-off

`tier-mid` costs **3.4x** more per issue ($0.00099 vs $0.00029) — a significant, precisely
measured price difference — and its quality advantage is **not** statistically demonstrable.

The economics still favour it, decisively. Breakeven is at **$0.0030 per error-weight unit**:
above that, `tier-mid` is cheaper overall; below it, `baseline` is. A weight unit is roughly a
minute of maintainer attention, so the real value is hundreds of times the breakeven, and
`tier-mid` wins at every anchor from $0.01 to $100.

**So the decision does not turn on price at all.** LLM spend differs by $0.0007/issue; the error
cost difference is $0.23/issue at the default anchor — **330x larger**. At these prices quality
dominates cost so completely that the "3x more expensive" framing is a red herring.

The honest recommendation: *`tier-mid` is preferred on expected cost at any plausible valuation
of maintainer time, but the quality difference driving that preference is not statistically
established. It needs ~465 items to resolve, or accept the risk knowingly.*

## Findings worth keeping

**`tier-cheap` fails for one specific reason.** `mistral-nemo` scores macro-F1 0.892 — nominally
the best of any config — but `needs_human` recall of **0.25**. It classifies well and refuses to
escalate. A single aggregate would have hidden this; per-field diagnostics made it obvious in one
line.

**Reasoning-before-deciding hurts.** `rationale-pre` is significantly worse than `post`
(Δ=+0.917 [+0.283, +1.667]) *and* costs more output tokens. A clean reject.

**Dropping the rationale costs nothing measurable.** `rationale-off` is indistinguishable from
baseline (Δ=+0.017, effect ≈ 0) with identical macro-F1, at fewer output tokens and the lowest
latency of any config (1176 ms p50 vs 2003). The strongest ship candidate here.

**Repo context helps the opposite field from the one predicted.** The expectation was that repo
knowledge would improve `category` (does this module exist?) and not `needs_human`. The reverse
happened: `context-none` has *better* macro-F1 (0.898 vs 0.868) and *better* urgency MAE, and
loses only on `needs_human` recall (0.65 vs 0.75, significant). Context is earning its ~1,050
tokens through escalation judgement, not classification — and the flagship difference needs ~77
more items to call.

**The flagship metric is ~72% about escalation.** With a 10:1 weight and a 69% positive rate,
missed escalations account for roughly 1.67 of baseline's 2.32 error weight. Category and urgency
barely move it. That is a deliberate consequence of the cost model — this harness measures the
routing decision well and treats the rest as diagnostics — but it should be read that way rather
than as a general quality score.

**Determinism confirmed for free.** `baseline` and `tier-small` are the same config with different
names, so they hash identically and ran as two independent samples. Their scores match to four
decimal places, so run-to-run variance is ~0 at temperature 0 for this model, and observed
differences are not noise from the service.

## Label reliability — and why it matters most here

A cross-model check (`harness verify cross`), 25 items stratified 5 per category, labelled
independently by `x-ai/grok-4.6` — a different lineage from both the labeller and every config:

| field | observed agreement | Cohen's kappa | reading |
|---|---|---|---|
| category | 0.96 | **+0.950** | strong |
| urgency (linear-weighted) | 0.88 | **+0.694** | substantial |
| `needs_human` | 0.80 | **+0.576** | **moderate** |

**The weakest label is the one the harness leans on hardest.** `needs_human` carries the 10x
weight, drives roughly 72% of the flagship metric, and is where every significant difference
between configs appeared — and two frontier models agree on it only moderately. Category, which
barely moves the flagship, is the field they agree on almost perfectly.

**What this does and does not invalidate.** Random label noise **attenuates** measured
differences toward zero, and comparisons here are paired — both configs face the same labels —
so a result that reached significance *despite* noisy labels is still real. Noise made it harder
to detect, not easier:

- `tier-cheap` worse (nh recall 0.25 vs 0.75, Δ=0.50) — far beyond label noise. Stands.
- `rationale-pre` worse (flagship Δ=+0.917, CI excludes zero) — stands.
- The four inconclusive comparisons may be inconclusive *partly because* label noise attenuates
  the effect. The "needs ~465 items" figure is therefore optimistic; with labels this noisy the
  true requirement is higher.

**What it cannot rule out is shared bias.** Pairing corrects random noise, not a blind spot both
models share — and cross-model agreement is exactly the wrong instrument for detecting one. That
is the argument for human verification, unchanged by this result.

**A ceiling observation.** Baseline's `needs_human` recall is 0.75; two frontier models agree
with each other 0.80 of the time on that field. The service is operating close to the level at
which the raters themselves agree, which is the signal that further optimisation on this field
is chasing noise rather than quality.

**Cross-model agreement is weak evidence in one direction only.** Low agreement would have been
strong evidence the labels are unreliable. High agreement is only weak evidence they are sound,
since two models can share a blind spot a person would not. `data/verification/sample.md` holds
the 25-item sample with gold labels withheld, awaiting a human pass.

## Caveats

- **n=60 on dev.** Underpowered for anything but large effects, which is why so much is inconclusive.
- **Nothing here has touched the holdout.** These are iteration numbers, not final ones.
- **The gold set is model-labelled and not yet human-verified.** A cross-model check gives
  kappa 0.95 / 0.69 / 0.58 across the three fields, but that cannot detect a bias two models
  share. Every number here inherits whatever bias `claude-sonnet-5` has.
- **Cost reporting is not universal.** `x-ai/grok-4.6` returned no cost while the account was
  charged $0.29 for 25 calls. Runs now record `cost_reported` and `compare` refuses a run
  containing unpriced calls, but the gap is a property of the gateway, not of the harness.
- **Stratification oversampled `security` and P0**, which inflates the 69% escalation rate and
  flatters escalate-everything. Not a production estimate.

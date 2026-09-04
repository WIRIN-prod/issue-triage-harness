# Spec — Issue triage service + evaluation harness

**Status:** draft · **Last updated:** 2026-09-03

## 1. What this is

Two things, in order of importance:

1. **An evaluation harness** that can tell you, with a stated confidence level, whether a
   change to an LLM service made it better — accounting for what the change costs.
2. **An issue triage service** that the harness measures. It takes a raw GitHub issue
   (title + body), plus knowledge of the repo it belongs to, and returns a structured triage
   decision.

The harness is the product. The service is deliberately small; it exists to be a realistic
subject of measurement.

## 2. Problem

Teams shipping LLM features change prompts, swap models, and add retrieval constantly. Very
few can answer "did that help?" with anything better than reading a handful of outputs and
forming an impression. Two specific failures follow:

- **Unfalsifiable changes.** A change ships because the outputs "look better." Nobody knows
  whether the difference exceeds run-to-run noise.
- **Invisible cost.** Quality regressions get caught eventually. A 3x cost increase for a
  2-point accuracy gain usually doesn't, until the bill arrives.

This project builds the instrument before the thing it measures.

## 3. Scope

**In**
- Triage service: issue + repo context → structured decision, fully configuration-addressable
- Repo knowledge graph, built once per repo and cached
- OpenTelemetry instrumentation for token, cost, and latency accounting
- A labelled dataset, split dev/holdout, frozen and hashed, with a published rubric
- Harness: paired comparison of two configs, with uncertainty and cost
- CLI

**Out, and why**
| Cut | Reason |
|---|---|
| Front end | Nothing a UI would show isn't clearer as CLI output |
| Diagnosis — "what's the fix, what does it cost" | A different task from triage, and one with no trustworthy labels. See §4.1 |
| Production monitoring | A different system from the offline harness. Boundary documented in §10 rather than built |
| Automated prompt optimisation | An unmeasured optimiser is a faster way to ship noise. Measure first. |
| Generic multi-task eval framework | Premature abstraction from one example. See §9. |
| Fine-tuning | Doesn't exercise anything the harness needs to measure |
| Multi-repo generalisation | Single repo, generalisation explicitly untested. See §8. |
| Production serving, auth, persistence | Not a serving exercise |

## 4. The service

### 4.1 Triage, not diagnosis

The service routes. What kind of issue is this, how urgent, does a human need to see it. A
maintainer does exactly this in about thirty seconds per issue.

It deliberately does **not** attempt diagnosis — what the fix is, which files change, what it
costs to repair. That is the work the assigned engineer does afterwards with the codebase
open. It is a different task, and critically, one whose output cannot be labelled at any
reasonable cost: verifying a proposed fix means implementing it. An unlabelable output is an
unmeasurable one, and this project is about measurement.

Repo context serves the *routing* decision — does the named module exist, is this API
deprecated, is this a known-fragile subsystem — not diagnosis.

### 4.2 Output schema

```python
class TriageDecision(BaseModel):
    category: Literal["bug", "feature", "docs", "question", "security"]
    urgency: Literal["P0", "P1", "P2", "P3"]
    needs_human: bool
    rationale: str          # diagnostic aid for error analysis — deliberately unscored (§5.6)
```

Wrapped in a run envelope the harness consumes:

```python
class TriageRun(BaseModel):
    decision: TriageDecision
    tokens_in: int
    tokens_out: int
    latency_ms: int
    model: str
    config_hash: str
    cost_usd: float         # actual, reported by the gateway — not estimated from a price table
```

The `Literal` types matter more than they look. They close the output space, which is what
removes any need for an LLM judge at evaluation time (§5.6). A value outside the enum fails
validation, and that failure is itself a signal the harness counts.

### 4.3 Configuration surface

The service is a pure function of `(issue, repo_graph, config)`. Everything that changes
behaviour lives in one hashable config object:

| Knob | Values |
|---|---|
| `model` | any OpenRouter model id |
| `prompt_version` | id into a versioned prompt directory |
| `rationale_mode` | `pre` (reasoning before the decision) \| `post` (explanation after) \| `off` |
| `context` | `graph` (default) \| `none` — see §5.1 |
| `temperature` | float |

This is the most important architectural constraint in the project. If behaviour can change
from outside the config, a measured delta cannot be attributed to a cause and every
comparison the harness produces is unsound.

### 4.4 Repo context

**Assumption: a maintainer triaging an issue already knows the codebase.** The service is
built to match that baseline, so repo context is **on by default**, not an optional
enhancement.

[graphify](https://github.com/Graphify-Labs/graphify) builds a knowledge graph over the target
repo. Relevant nodes are retrieved for each issue and injected into the prompt. The graph is
built **once per repo and cached** — never per issue, never per eval run.

**The labelling pipeline sees the same context the service does.** This is not a detail, it is
a correctness requirement. If gold labels were produced from title and body alone, then any
repo knowledge that changed the right answer would push the service *away* from the label —
and a better-informed config would score worse for knowing more than the referee. Labeller and
service see the same inputs, so the graph can help rather than be penalised.

### 4.5 Model access — OpenRouter

One API across every model tier, so model choice is a config value rather than an integration
project. This is what makes the accuracy-vs-cost trade-off testable in minutes: swapping a
cheap model for a frontier one is a one-line change with a large, real price delta.

OpenRouter returns **actual cost per call**, so runs are priced from reported figures rather
than a hand-maintained table that silently goes stale.

Two constraints for reproducibility: **provider routing is pinned** (OpenRouter may otherwise
route the same model to different backends, injecting variance from outside the config), and
latency figures are understood to measure gateway plus provider.

### 4.6 Instrumentation — OpenTelemetry

The service emits OTel spans using the GenAI semantic conventions — `gen_ai.request.model`,
`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`. pydantic-ai emits OTel-native
instrumentation already, so this is close to free, and it means the cost story is the same one
a production deployment would use rather than an eval-only invention.

**OTel is a parallel path, not the primary one.** Token counts return synchronously in the
response envelope, and that is what the harness does arithmetic on. Making the headline metric
depend on exporting spans and reading them back would put a fragile asynchronous pipeline
underneath the most important number in the project.

## 5. The harness

### 5.1 What counts as a change

Any difference in the config object of §4.3. The harness compares two config hashes over one
frozen dataset. Three axes are varied:

- **model tier** — the headline cost experiment. Price spread across tiers is large and
  well documented; quality spread on a constrained classification task is usually much
  smaller. That gap is the trade-off.
- **prompt version** — zero-shot vs rubric-in-prompt vs few-shot
- **`rationale_mode`** — reasoning before deciding costs output tokens, which are the
  expensive ones. Whether it earns them on a five-class classification is genuinely unknown.

`context` is **not** a varied axis — it is on by default per §4.4. But it is run **once**, off,
as a one-off sanity measurement. One run's cost converts "we assume repo context helps" into a
number. An assumption that can be priced for a few cents should be.

### 5.2 What "better" means

The three scored fields have different mathematical natures and cannot share a metric:

| Field | Nature | Metric | Why not accuracy |
|---|---|---|---|
| `category` | multi-class | macro-F1, per-class P/R | class imbalance makes accuracy flattering and uninformative |
| `urgency` | **ordinal** | MAE on the P0–P3 scale + exact match | P0-vs-P3 is a worse error than P0-vs-P1; accuracy treats them the same |
| `needs_human` | binary, **asymmetric** | recall on positive class, precision as guard | a missed escalation and an unnecessary one are not the same mistake |

These are **diagnostics**. The flagship metric is §5.3.

### 5.3 Flagship metric — cost per issue, in one currency

Every triage error has an operational cost, and so does every LLM call. Put both in dollars
and the accuracy-vs-cost trade-off stops being a judgement call and becomes arithmetic:

```
total cost per issue  =  LLM spend per issue  +  expected error cost per issue
```

Error costs come from an explicit, arguable weight table:

| Error | Weight | Reasoning |
|---|---|---|
| Missed escalation (`needs_human` True → predicted False) | 10 | a real problem sits unlooked-at |
| Unnecessary escalation (False → True) | 1 | a human wastes a few minutes |
| Urgency off by 1 / 2 / 3 | 1 / 3 / 6 | ordinal — distance matters |
| Wrong category | 2 | misrouted to the wrong queue |

A change that improves accuracy but triples the price is now directly evaluable: does the
error-cost saving exceed the additional spend? One number, and the assumptions behind it are
written down where they can be disputed.

**The weights are assumptions, so the harness reports sensitivity to them.** If halving the
escalation weight flips which config wins, the result is driven by an unvalidated assumption
rather than by evidence, and the harness says so.

### 5.4 The dataset

The hard part, and the part most eval work skips.

**Source.** Real issues from a small public repo, pulled via the GitHub API. Maintainer labels
(`bug`, `enhancement`, `documentation`), closed-by-PR, and time-to-close are used to
**stratify sampling and seed candidate labels — never as ground truth.** They are noisy and
leak information about outcomes the model cannot see at triage time.

**Size and split.** 198 issues, split **118 dev / 80 holdout**. (Originally ~100 at 60/40;
doubled when rubric v2 required a re-label anyway, since several comparisons were returning
"can't tell" with sample sizes that more data would resolve.)

| Set | Rule |
|---|---|
| **dev** | Looked at freely. Per-item failures, error analysis, prompt iteration. |
| **holdout** | Per-item results not inspected. Run only when a config is a final candidate. |

Both halves are labelled. The split protects against the most common failure in prompt
engineering: **developing on the test set.** Looking at which items fail, tweaking until they
pass, and repeating is training on the evaluation data by hand — the score rises and
generalisation does not. Nothing in the service *learns* from the labels, but the person
writing the prompts does, and that is the leak the split closes.

The holdout is small, so its confidence intervals are wide. Stated, not hidden.

**Who labels.** Whichever source the cost-to-time ratio favours:

| Situation | Approach |
|---|---|
| A labelled dataset already exists | Use it |
| No dataset exists | **Frontier model labels all ~200 items** (with repo context, per §4.4), then a human verifies a stratified sample of ~25 |

Human-vs-model κ is reported on the verified sample. High agreement means the labels are
defensible with evidence rather than assertion; low agreement means the dataset is unreliable
and that is discovered *before* conclusions rest on it.

**The labelling model is excluded from the config space.** If a frontier model produces the
labels and is then evaluated as a service config, it is correct by construction, scores near
100%, and measures nothing — destroying the single comparison the harness most needs to make:
whether the expensive model is worth its price over the cheap one. The referee does not
compete.

Accepted limit: measurable quality is capped at the labeller's ability, so the harness cannot
detect the service *exceeding* it. Acceptable, since the service runs cheaper models and the
interesting question is how close they get.

**Disputed items.** Some issues are genuinely both a bug and a question. Exact match scores
zero for picking the defensible-but-different answer. The human verifier flags these
`disputed`, and the harness reports metrics **with and without** them. If a config's entire
advantage lives in disputed items, that is not an advantage. A judge would not help here — it
would have to make the same arbitrary call.

**Stratification.** Sampled to fill each category × urgency cell. Random sampling would give
~2 security issues and ~2 P0s, cells where any metric movement is pure noise. Stratification
distorts the distribution, so per-class metrics are the honest read; a production estimate
requires re-weighting to the true prior.

**Rubric.** Labelling rules are written down before labelling starts (`docs/rubric.md`), so
that item #1 and item #198 are judged by the same standard, and so the frontier labeller and
the human verifier are given identical criteria. Without a shared rubric, disagreement between
them is uninterpretable — you cannot tell whether one is wrong or they are answering different
questions.

**Frozen and hashed.** Once comparison begins the set does not change. Each run records the
dataset content hash, and the harness **refuses to compare runs whose hashes differ.**
Silently editing one label and re-running is the most common way eval results become lies.

### 5.5 Confidence

Two independent noise sources: LLM non-determinism, and a 60/40 split having wide error bars.
Both are handled:

- **Non-determinism** — measured, not assumed away. The same config runs N times; run-to-run
  variance is reported alongside the metric.
- **Sampling noise** — paired comparison (both configs on identical items) with bootstrap
  confidence intervals over the difference.

**`NO SIGNIFICANT DIFFERENCE` is a first-class verdict.** When the interval straddles zero the
harness reports that, plus the sample size that would resolve it. A harness that always
crowns a winner is a harness that ships noise.

### 5.6 No judge in the eval loop

`category`, `urgency` and `needs_human` are **closed categorical fields**, constrained by the
schema in §4.2. Scoring is deterministic comparison against the labels — no LLM judge is
involved at evaluation time. That removes judge cost, judge variance, and judge bias from
every run.

The judge has not been rejected; it has been **moved**. The frontier model producing the
labels in §5.4 is LLM-as-judge — same technique, same model class, same rubric. It runs
**once, up front, and the result is frozen**, rather than re-adjudicating identical items on
every evaluation and giving slightly different answers each time. Same judgment quality,
deterministic downstream, no per-run cost, and a human has verified a sample of it.

A judge would legitimately return if `rationale` were scored, if the taxonomy were open-ended
rather than a fixed enum, or when evaluating on live traffic with no labels (§10).

`rationale` is therefore **deliberately unscored**. Grading free text would drag a judge back
into the loop and reintroduce all three problems, in exchange for a number that drives no
decision. It stays in the output because reading the model's stated reasoning on failing items
is the fastest route to the next hypothesis.

### 5.7 Outputs

A run record is `(dataset_hash, config_hash, git_sha) → results`, reproducible by
construction. Every run persists per-item outputs, so `compare` reports not only *whether*
something changed but *which items* changed and how. Aggregate scores say whether; per-item
error breakdowns say where to aim next.

## 6. CLI

```
triage run <issue-url|file> --config <name>     # single issue, human-readable
graph build <repo>                              # build and cache the repo knowledge graph
harness label                                   # labelling pipeline over the candidate pool
harness verify                                  # human verification pass + κ report
harness eval --config <name> [--split dev|holdout]
harness compare <run-a> <run-b>                 # verdict + cost delta + CIs
```

## 7. Stack

| Choice | Rationale |
|---|---|
| Python | Chosen over TypeScript for the statistics ecosystem — bootstrap, κ, confusion matrices are one import away |
| pydantic | Output schema and validation; closed enums are what remove the judge (§5.6) |
| pydantic-ai | Typed model calls with structured output, provider-agnostic, OTel-native |
| graphify | Repo knowledge graph. DECISIONS.md D2 |
| OpenRouter | One API across model tiers; returns actual per-call cost. DECISIONS.md D12 |
| OpenTelemetry | Standard telemetry for tokens, cost, latency, via GenAI semantic conventions. DECISIONS.md D11 |
| SQLite + JSON run records | Runs are append-only artefacts. A database would be infrastructure without a question it answers. |
| No eval framework | See DECISIONS.md D8 |

## 8. Open questions and assumptions

Questions that would go to a stakeholder, with the assumption taken in the absence of one.

| # | Question | Assumption taken |
|---|---|---|
| Q1 | What does a missed escalation actually cost relative to an unnecessary one? | 10:1. Drives the flagship metric, so §5.3 reports sensitivity to it. |
| Q2 | Is this pre-sorting a human queue, or auto-labelling with no human in the loop? | Pre-sorting a human queue. Makes `needs_human` recall the dominant concern; full autonomy would demand far higher precision. |
| Q3 | What is the real category distribution in production? | Unknown. Dataset is stratified, per-class metrics are the honest read, headline number is not a production estimate. |
| Q4 | Is there a latency SLA? | No. p50/p95 reported as information, not as a constraint. Figures include gateway overhead. |
| Q5 | Is there an absolute monthly budget? | No. Cost-per-issue is the comparable unit; no absolute ceiling enforced. |
| Q6 | Is urgency absolute or relative to the repo's own norms? | Absolute, per the published rubric. A quiet repo's P1 and a busy repo's P1 are treated alike. |
| Q7 | Who owns the taxonomy — is a fixed 5-class scheme right? | Fixed 5 classes. Real teams evolve taxonomies; the schema is versioned so a change is a measurable change. |
| Q8 | How much human verification of model-produced labels is enough? | ~25 of 100, stratified. Enough to estimate κ; not enough to catch rare systematic errors. Stated as a limit rather than solved. |
| Q9 | Does the triaging maintainer really have codebase context? | Yes — §4.4. Priced once via the one-off `context: none` run rather than left as an untested belief. |

## 9. On generality

The harness is built specifically for this service, not as a generic framework. That is a
decision, not an omission.

The metric is a function of the task — classification wants F1, summarisation wants
faithfulness, retrieval wants groundedness, code generation wants "does it pass tests." There
is no universal metric, so a universal harness would be plumbing wrapped around the one part
that doesn't generalise.

What does generalise is the **method**: define what correct means, build labels you can
defend, measure with uncertainty attached, price the errors, and decide against a rule
written down in advance. That transfers to any system. The code doesn't.

The seams are kept clean — service behind a small interface, metrics separate from the
runner, dataset as plain data — so extension is obvious without being built. See
`docs/what-would-change.md` for the two-paragraph version applied to a different task.

## 10. Where this instrument stops being valid

The harness answers **"is config B better than config A?"** — offline, on a frozen labelled
set, before shipping. It does not answer **"is this particular production answer correct?"**

That second question has no per-item answer without a label. No judge, confidence score, or
similarity measure changes that: a mechanism that could reliably tell you an answer was wrong
would be a better classifier, and you would ship it instead.

What production confidence actually consists of, none of it built here:

**Population-level transfer.** An offline macro-F1 of 0.82 is what you expect in production,
conditional on two things — reweighting from the stratified distribution to the true prior,
and the distribution not having drifted. New issue types or a framework release changing what
people complain about quietly voids it.

**Coverage, not correctness.** Embed the dataset; for each production issue, measure distance
to nearest neighbours. Inside the covered region, the measured error rate plausibly applies.
Far outside it, offline metrics say nothing about that item. This answers "do I have a basis
for a claim about this answer?" — which is knowable — rather than "is this answer right,"
which is not.

**Sampled human review.** ~30 production issues labelled weekly. The only thing that actually
measures production quality, and the source from which the dataset should grow over time —
frozen within a comparison, versioned across them.

**Free outcome signals.** A human changing the category is a correction. A `needs_human: false`
item escalated later is a confirmed miss. A P3 closed within a day means the urgency was
wrong. Noisy and delayed individually; excellent for regression detection in aggregate.

**Not self-reported confidence.** LLMs are badly calibrated at "how sure are you, 0–1." Answer
stability across repeated samples is a real uncertainty signal; self-report is not.

**The escape hatch.** `needs_human` is the safety valve — the service does not have to be right
about everything, because one of its outputs exists to route uncertainty to a person. That is
the assumption behind the 10:1 weight in §5.3: the system tolerates being wrong precisely
because wrong answers are supposed to reach a human.

## 11. Success criteria

1. Running the harness twice on the same config and dataset produces identical results.
2. At least one real trade-off is surfaced and *decided* — a change that improves quality but
   is rejected on cost, or accepted with the cost stated.
3. At least one comparison returns `NO SIGNIFICANT DIFFERENCE` and reports the sample size
   that would resolve it.
4. Human-vs-model label agreement is reported, and the dataset's trustworthiness is argued
   from it rather than assumed.
5. Final candidate configs are decided on the holdout, not on the set used for iteration.

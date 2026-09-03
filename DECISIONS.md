# Decision log

Chronological. Includes the decisions that were reversed — the reversals are the useful part.

---

## 2026-09-03

### D1 — Build the harness first, keep the service minimal
**Options:** rich service with a thin eval · minimal service with a serious harness
**Chose:** minimal service.
**Why:** the interesting engineering problem is measurement, not classification. A larger
service would consume the time budget and make labelling harder without making the harness
better. The service needs to be *realistic*, not *large*.

### D2 — Repo-graph context, always on
**Reversed twice before landing here.** First sketched as always-on, then softened to a config
flag so its value could be tested, then cut entirely as the largest build cost in a
harness-focused project. Now back on, permanently — but for a different reason than the first
time, and the difference is the point.

**Why on:** a maintainer triaging an issue already knows the codebase. Whether a named module
exists, whether an API is deprecated, whether a subsystem is known-fragile — none of that is in
the issue text, and all of it changes the routing decision. The service is built to match the
baseline a human triager works from. This is a *product assumption*, and product assumptions do
not need to be A/B tested to be adopted.

**Why the first always-on was wrong and this one isn't.** The original version was an unexamined
belief with no way to price it. This one comes with two things attached:
1. A **one-off `context: none` run** (§5.1) that converts the assumption into a number for a few
   cents. An assumption that cheap to price should be priced.
2. The labelling-parity requirement below, without which the whole thing measures backwards.

**The trap this avoids.** If gold labels were produced from title and body alone while the
service saw the repo graph, then any repo knowledge that changed the right answer would push
the service *away* from the label. A better-informed config would score *worse* — penalised for
knowing more than the referee — and the experiment would confidently conclude "context doesn't
help" when it was structurally incapable of concluding anything else. **The labelling pipeline
sees exactly what the service sees.** Always-on makes this true by construction.

**Cost accepted:** the graph is on the critical path for both labelling and evaluation, so it
must be built and cached per repo before either can run. `prompt_version` remains a variant
axis; the earlier plan to drop it is unnecessary now that `context` is fixed rather than varied.

### D3 — Gold set labelled by a frontier model, validated against a human sample
**Reversal.** The earlier position was that an LLM judge scoring against rubric aspects could
replace a gold set. That was rejected: a judge sharing a model family with the service also
shares its blind spots — a usage question worded like a bug report gets misread by the
service, and the judge, reading the same surface cues, confirms the error as correct.
Systematic and invisible.
The position after that was full human labelling. That is the long pole in the project: it is
the only part requiring human hours rather than compute, and for a closed-taxonomy task the
marginal value of the 100th hand-labelled item over the 25th is low.

**Chose:** labels are produced by whichever source the cost-to-time ratio favours, subject to
one guard.
- Where a labelled dataset already exists, use it.
- Where none exists, a **frontier model labels the full set**, and a human verifies a
  **stratified sample of ~20–25 items**. Human-vs-model κ is reported on that sample.
- κ high → the labels are defensible, with evidence rather than assertion.
  κ low → the gold set is unreliable, discovered *before* conclusions are built on it.

**Hard constraint: the labelling model is excluded from the config space.** If a frontier
model produces the labels and is then evaluated as a service config, it is correct by
construction, scores near-perfectly, and measures nothing. That would destroy the comparison
the harness most needs to make — whether the expensive model is actually worth its price over
the cheap one. The referee does not compete.

**Limits accepted:** measurable quality is capped at the labeller's ability, so the harness
cannot detect the service outperforming the labeller. Acceptable — the service runs cheaper
models, so the interesting direction is how close it gets, not whether it exceeds.

**Consequence:** with closed categorical fields scored by direct comparison against labels,
there is no separate LLM judge in the eval loop at all. Judge cost, judge variance, and judge
bias all disappear. The judge is not rejected, it is *moved* — the frontier labeller is
LLM-as-judge, run once and frozen instead of re-adjudicating identical items every run.
`rationale` is deliberately left unscored — grading free text would drag it back in.

**Ambiguous items.** Some issues are defensibly both a bug and a question, and exact match
scores zero for choosing the wrong defensible answer. The human verifier flags these
`disputed`, and metrics are reported with and without them. A judge would not help — it would
face the same arbitrary call.

### D4 — Accuracy and price expressed in a single currency
**Options:** report quality and cost side by side and eyeball the trade-off · Pareto frontier
with a pre-registered acceptance rule · convert error types into dollars and sum
**Chose:** convert and sum — `total cost per issue = LLM spend + expected error cost`.
**Why:** "more accurate but three times the price" is otherwise a matter of taste. Assigning
an explicit cost to each error type makes it arithmetic and moves the argument to where it
belongs: the weight table, which is written down and can be disputed.
**Risk accepted:** the weights are assumptions. Mitigated by reporting sensitivity — if
halving the escalation weight flips the winner, the harness says the result rests on an
assumption rather than on evidence.

### D5 — `NO SIGNIFICANT DIFFERENCE` is a first-class verdict
**Why:** with a 40-item holdout and a non-deterministic model, 0.81 vs 0.84 is probably nothing. A
harness that always names a winner is a harness that ships noise with confidence. Paired
comparison over identical items, bootstrap CI on the difference, and when the interval
straddles zero the harness says so and reports the sample size that would settle it.

### D6 — Stratified sampling over random sampling
**Why:** random sampling from a real repo yields ~2 security issues and ~2 P0s. Those cells
cannot move a metric except by noise, and they are the cells that matter most.
**Cost accepted:** the test set no longer reflects the production distribution, so the
headline number is not a production estimate. Handled by reporting per-class metrics and
noting that a production figure needs re-weighting to the true prior.

### D7 — Specific implementation, general reasoning — no generic eval framework
**Options:** build a pluggable multi-task harness · build narrowly for this service
**Chose:** narrow.
**Why:** the metric is a function of the task, so the one component that would need to
generalise is the one that can't. A generic harness would be adapters and registries wrapped
around a hole. Generalising from a single example produces an abstraction that fits nothing
else. The transferable artefact is the method, not the code.
**Mitigation:** keep the seams clean so extension is obviously possible, and write two
paragraphs on what would change for a different task rather than building for it.

### D8 — No existing eval framework (DeepEval, Ragas, promptfoo, LangSmith)
**Why:** the parts these provide — a runner, metric plumbing, result storage — are the cheap
parts. The parts that matter here are the gold set construction, the error-cost model, the
significance test, and the label validation, none of which come out of a box. Adopting a
framework would mean inheriting its opinions about all four while still writing all four.
**Cost accepted:** more code to write, and no free dashboard or hosted tracing.

### D9 — Python over TypeScript
**Why:** bootstrap resampling, Cohen's κ, and confusion matrices are one import away.

### D10 — SQLite plus JSON run records; no server database
**Why:** runs are append-only artefacts read by one process. A hosted database would be
infrastructure without a question it answers. JSON keeps per-item outputs diffable by hand,
which matters for error analysis.

### D11 — OpenTelemetry for service instrumentation
**Chose:** instrument the service with OTel using the GenAI semantic conventions
(`gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`).
**Why:** token and latency accounting is the kind of thing that should be standard telemetry
rather than a bespoke counter, and pydantic-ai emits OTel-native instrumentation already, so
the cost is close to zero. It also means the cost story is the same one a production
deployment would use, not an eval-only invention.
**Important refinement:** OTel is a **parallel** path, not the primary one. Token counts are
returned synchronously in the response envelope and that is what the harness does arithmetic
on. Making per-item cost depend on exporting spans and reading them back would put a fragile
asynchronous pipeline underneath the project's headline metric.

### D12 — OpenRouter as the model gateway
**Why:** one API across every model tier makes model choice a config value rather than an
integration project, which is what turns the accuracy-vs-cost trade-off into something
testable in minutes. OpenRouter also returns actual cost per call, replacing the
hand-maintained price table originally specced — a real source of truth beats a table that
silently goes stale.
**Costs accepted:**
- OpenRouter may route the same model to different backend providers, which injects variance
  outside the config. Provider routing is pinned for reproducibility.
- Latency figures measure gateway plus provider, not the provider alone. Reported as such.
- Prices are OpenRouter's, which differ slightly from direct provider rates.

### D13 — Dev/holdout split, not train/test
**Considered:** a train/test split by analogy with supervised ML — gold set as "train," a
separate unlabelled set through the service as "test."
**Why that doesn't apply:** in supervised ML *both* halves are labelled; the split withholds
training data from the model, not labels from the evaluator. Here nothing is trained — no
parameters are fitted, and the service never sees a label — so there is no train role to play.
And an unlabelled evaluation set cannot be scored at all: the harness would have nothing to
compare against, which puts a non-deterministic judge back in the loop.

**What the instinct was right about:** there *is* a leak, and it is the most common failure in
prompt engineering. **The developer sees the dataset.** Looking at which items fail, tweaking
the prompt until they pass, and repeating is training on the evaluation data by hand. The score
climbs; generalisation doesn't.

**Chose:** ~100 labelled items split **60 dev / 40 holdout**. Both halves labelled. Dev is
inspected freely for error analysis and iteration; holdout per-item results are not looked at,
and it runs only when a config is a final candidate. The discipline governs what *the developer*
may look at, not what the service receives.
**Cost accepted:** 40 items give wide confidence intervals on the holdout. Stated in results
rather than hidden.

### D14 — Production monitoring documented, not built
**Why:** "is config B better than A" (offline, labelled, relative) and "is this production
answer correct" (online, unlabelled, absolute) are different problems. The second has no
per-item answer without a label — any mechanism that could reliably detect a wrong answer would
be a better classifier and would be shipped instead.
**Chose:** build the offline harness; document the production boundary in SPEC.md §10 —
population-level transfer and its conditions, coverage/OOD as "do I have a basis for a claim"
rather than "is this right", sampled human review as the only real measurement, free outcome
signals from the triage workflow, and why self-reported model confidence is not usable.
**Why not build it:** a different system, and exactly the volume this project avoids. Knowing
where an instrument stops being valid is worth more than pretending it doesn't.

### D15 — Repo choice: BerriAI/litellm. Graph spike run before committing to it
**Chose:** `BerriAI/litellm`, pinned at commit `658f5066`.

**Why over the alternatives.** `pydantic/pydantic` is 440MB — too large to graph.
`simonw/datasette` is disqualified on dataset grounds: 61–79% of its issues are the maintainer's
own work-journal entries rather than incoming reports. `python-attrs/attrs` was the runner-up
(19 source files, clean Bug/Feature/Documentation taxonomy) but lost on dataset quality: ~5–40%
label coverage on external issues versus litellm's ~55–65%, and litellm carries an
`awaiting: user response` label — a maintainer-generated proxy for `needs_human`, the hardest
of the three fields to label and the one carrying the 10:1 cost weight.

**Pinned to a SHA, not a branch.** litellm's default branch is `litellm_internal_staging` and
`main` is not among its first 100 branches. A moving ref would make the graph unreproducible and
silently invalidate the dataset hash.

**Spike results.** Run before building anything on top of it, because the graph was the largest
remaining build risk.

| Step | Result |
|---|---|
| Sparse blobless clone at pinned SHA | 93MB, ~1s |
| AST extraction, 1,421 files (`litellm/` less `proxy/`) | 16.5s → 31,165 nodes, 80,783 edges |
| Cost | Zero — extraction is AST-based, no LLM, no API key |
| Graph content | Code nodes plus 9,228 docstring "rationale" nodes; edges are calls / references / imports / inherits / contains |

**The finding that matters: naive retrieval is not good enough.** Generic token matching over
node labels and file paths retrieves well for specific issues — "openrouter entries disagree on
price" correctly surfaces `get_model_cost_map.py` — but returns confident-looking noise for vague
ones. A junk issue titled "error po sa from litellm import completion" retrieved
`model_rate_limit_check.py`; an issue about `/v1/models` retrieved an unrelated Anthropic
pass-through module on the strength of the words "result" and "errors". Common English tokens in
file paths dominate the score.

That is worse than no context at all: irrelevant context does not merely fail to help, it
actively misleads, and it costs tokens to do so.

**Cheap fix identified.** litellm's layout is highly regular — 139 provider directories under
`litellm/llms/`, 82 under `integrations/`, 15 router strategies. That is a ~236-term controlled
vocabulary available free from the directory structure, and issue text names these terms
constantly ("openrouter", "bedrock", "anthropic", "vertex"). Anchoring retrieval to that
vocabulary rather than to arbitrary tokens should be far higher precision.

**Consequence:** retrieval quality is now an explicit build task, not an assumed property of
"having a graph." Whether the improved version beats `context: none` is left to the harness —
which is the correct place for that question, and a null result there is a publishable finding
rather than a failure.

### D16 — Vocabulary-anchored retrieval; graph builds are cold-only
**Built** the fix D15 identified: retrieval matches only terms the repo defines, never
arbitrary tokens.

**Vocabulary sources, all derived from the checkout — none hand-written:**
139 provider directories under `litellm/llms/`, 82 integrations, router strategies,
top-level modules, and the shipped `model_prices_and_context_window.json` — 3,560 model ids
mapped to 130 providers. That last file is where aliasing comes from for free: "claude-sonnet-4"
resolves to the anthropic module without anyone encoding that claude means anthropic. 2,187
terms after de-duplication, 2,117 resolving to a module path.

**Empty context is a valid result.** When an issue names nothing the repo defines, the retriever
returns nothing and says why, rather than the nearest-looking module. On the ten-issue sample,
3 of 10 declined — issues titled "llm", "litellm._turn_on_debug()", and one about a third-party
header. All three had previously drawn confident, irrelevant code.

**Position weights the evidence.** A term in the title scores 3x, in prose 1x, inside a fenced
code block 0.4x. Issue #39451 is about `/v1/models` and `auto_router`, but a pasted YAML config
listing Bedrock models had put `llms/bedrock` first; with zone weighting `router_strategy/auto_router`
leads and bedrock falls to third. Config blocks name providers incidentally — the title names the
subject.

**Consequence for the harness:** context fires on roughly 70% of issues. Even a large effect can
only move the metric on the subset where retrieval engages, which dilutes the measurable effect
size and matters for the power calculation.

### D17 — Graph builds must run cold; the cache changes the output
**Found while checking reproducibility**, not from a bug report.

Three builds over an identical file list at an identical commit produced three different graphs:

| Build | Edges | Deterministic? |
|---|---|---|
| Cold cache | 81,188 | yes — byte-identical across runs |
| Warm/incremental | 74,223 | stable warm, but ~7,000 edges short |
| Partially warm | 80,783 | — |

Node counts matched at 31,165 every time; only cross-file reference edges differed, resolved
differently depending on extraction order.

**Why it matters:** the graph feeds both labelling and every eval run. A graph that changes
underneath a comparison silently invalidates it, and would have broken SPEC.md §11 criterion 1
("running the harness twice on the same config and dataset produces identical results") in a way
no test would have caught — the numbers would simply have drifted.

**Chose:** `build()` clears the cache before extraction by default, and the expected graph SHA256
is pinned in code. Incremental remains available for local iteration but is never the path that
produces a graph used in results. The graph digest joins the commit SHA as part of the identity of
any run built on it.

---

## Still open

- A GitHub token is needed to build the candidate pool. Unauthenticated is 60 req/hr, and PRs
  outnumber issues ~10:1 on litellm, so a single 100-result page yields ~10 issues.
- Whether `rationale` is prompt-visible reasoning the model generates before deciding, or a
  post-hoc explanation. Measurably different token costs, and the first may change decision
  quality. Currently unresolved — it is itself a good first experiment for the harness.
- Which frontier model labels the gold set, and therefore which model is excluded from the
  config space under D3.

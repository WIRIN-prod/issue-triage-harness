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
label coverage on external issues versus litellm's ~55–65%, and litellm appeared to carry an
`awaiting: user response` label — a maintainer-generated proxy for `needs_human`, the hardest
of the three fields to label. **That reason turned out to be wrong — see D18.** The choice
stands on the remaining grounds, which D18 confirms with real numbers.

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

**Consequence for the harness:** context fires on **946 of 991 pool issues (95%)**. An earlier
estimate of ~70% was extrapolated from a ten-issue sample and was too pessimistic; the context
experiment is far less diluted than feared.

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

### D18 — Candidate pool built; the `awaiting: user response` signal does not exist in practice
**Correction to D15.** The `awaiting: user response` label was cited as the strongest reason to
prefer litellm — a free weak signal for `needs_human`. It is used **116 times all-time and zero
times** in the window we sample from. The label exists in the repo's taxonomy but maintainers
stopped applying it. D15 checked that the label existed, not that it was used; those are
different questions and only the second one mattered.

**The repo choice still stands**, on the grounds that survived contact with the data:

| | Pool (991 issues, 2026-06-01..2026-09-03) |
|---|---|
| Distinct authors | 615 — genuine incoming reports, not one voice |
| Label coverage | 81% |
| Median body | 3,330 chars |
| Bot-authored, removed | 9 |
| Near-empty bodies (<80 chars) | 24 — real junk, and a real triage signal |

**Window: three months before the pinned commit.** The graph is a snapshot at one SHA; a 2024
issue references modules that have since moved or been deleted, so retrieval would fail on it
for reasons unrelated to retrieval quality and would contaminate the context experiment. The
window also matches how triage actually works — on incoming issues against today's code.

**Maintainer labels cannot stratify the sample.** litellm's taxonomy is *component*-shaped, not
*type*-shaped: `llm translation` (587), `proxy` (359), `SDK`, `claude code`, `ui-dashboard`.
Type labels are thin — `bug` 292, `enhancement` 154, `docs` 9, `question` 2 all-time. There is
no maintainer signal at all for three of our five categories.

**Consequence — stratification needs its own cheap labelling pass.** Selecting a stratified
sample requires approximate labels for the whole pool, but stratification is a *sampling aid*,
not ground truth, so it does not need frontier quality. Two stages: a cheap model labels all 991
for stratification only, then the frontier labeller produces real labels for the ~100 selected,
and a human verifies ~25 of those. Labelling the full pool at frontier quality would cost
roughly 10x more for labels that are thrown away after sampling.

### D19 — `temperature` is silently dropped for `openai/*` models; detect and record it
**Found by reading a warning rather than ignoring it.** pydantic-ai drops sampling parameters for
models whose profile says reasoning is on by default, and it matches profiles on the id prefix.
Every OpenRouter id beginning `openai/` is therefore treated as a reasoning model — `gpt-4o-mini`
included, which is not one. Other prefixes (`anthropic/`, `google/`, `meta-llama/`, `mistralai/`)
pass temperature through normally.

**Why this is not cosmetic.** The headline experiment is model tier. Mixed handling would run one
arm at `temperature=0` and the other at the provider's default, and the resulting difference would
be attributed to the model. A config knob that silently does nothing is precisely the failure the
config-addressability rule exists to prevent — and it arrived from a library heuristic, not from
our own code, which is why it needed a test rather than a convention.

**Chose:** `sampling_is_honoured()` detects it from the profile, `TriageRun.temperature_applied`
records it per run, and a test asserts no named config uses an affected model. The config ladder
avoids `openai/*` entirely.

### D20 — Model ladder and the labeller
**Labeller: `anthropic/claude-sonnet-5`**, and therefore barred from the config space (D3). The
loss is that we cannot ask "is the frontier model worth it as the service" — accepted, because the
useful question for triage is whether a *cheap* model suffices, not whether the dearest one is best.

**Ladder** (per million tokens at selection; actual cost always comes from the gateway):

| Tier | Model | $/M in | $/M out |
|---|---|---|---|
| cheap | mistralai/mistral-nemo | 0.019 | 0.030 |
| small | google/gemini-2.5-flash-lite | 0.100 | 0.400 |
| mid | google/gemini-2.5-flash | 0.300 | 2.500 |

Capped at `gemini-2.5-flash`; `claude-haiku-4.5` was dropped to keep spend inside the budget.
Holding the cheapest rung keeps the spread open at **15.8x on input and 83x on output**. Output
is both the dearer side and the side `rationale_mode` moves, so the axis that matters most stays
wide despite the lower ceiling. Every model honours temperature (D19) and supports structured
output.

**First live signal, n=1, on one issue** — recorded as orientation, not evidence:
`rationale-off` produced 13 output tokens against `rationale-pre`'s 224 for the same decision;
the rubric prompt costs ~690 input tokens over the terse one and changed the answer; repo context
costs ~1,050 input tokens. All three are worth measuring properly.

### D21 — Labelling pipeline: two backends, and why the frontier pass runs on OpenRouter
**Proposed:** run the frontier labelling pass in the agent session rather than through
OpenRouter, to save credits.

**Measured the premise first.** `harness estimate` prices the whole pipeline at **$0.74** —
$0.05 for the cheap stratification pass over 991 issues and **$0.69** for frontier labels on 100.

**Chose:** frontier labels via OpenRouter. Saving sixty-nine cents is not worth what it costs
methodologically. A labelling pass run inside a chat session is not reproducible — a reviewer
cannot re-run it, it can drift across 100 issues as context is summarised, and the resulting
labels would be the one artefact in a project built on hashing and re-runnability that nobody
can regenerate.

**Both backends exist, because they are right for different jobs.** `ModelLabeller` (OpenRouter,
reproducible) does the bulk gold pass. `FileLabeller` reads labels from JSONL and is how
out-of-band labels arrive — which is exactly what the human *verification* sample needs, where
non-reproducibility is the entire point. Selecting between them is a CLI flag, not a rewrite.

**Dataset identity.** The hash covers items, splits, disputed flags, the rubric digest, and the
graph digest — because what "correct" means is a function of the rubric that produced the labels
and the repo graph the labeller saw. `Dataset.load` recomputes and **refuses a file whose stated
hash no longer matches its contents**, so editing one label in place fails loudly instead of
silently invalidating every result already computed against it. Rationale text is excluded from
the hash: two labellers may word an explanation differently and still mean the same label.

### D22 — A silently thinned dataset; retries and a failure-rate guard
**The first real labelling run produced a dataset that was wrong in a way nothing flagged.**
Requested 100 gold labels; 20 survived. 254 of 991 stage-1 calls also failed. The pipeline built
a dataset from the survivors, hashed it cleanly, printed a tidy summary, and exited 0.

That is exactly the failure mode this project is supposed to catch. The artefact looked
valid — correct schema, stable hash, plausible summary — and was a fifth of its intended size,
missing the `docs` category entirely. Every downstream number would have been computed against
it without complaint.

**Cause (first diagnosis, incomplete).** `ModelAPIError: Connection error.` under concurrency. Sequentially both models are
flawless (0/6 failures each); at 8 workers the cheap model loses 3/40, and the frontier model —
which holds connections far longer per call — lost roughly 80%. Transient gateway failures, not
rate limits, and entirely retryable.

**Two fixes, and the second matters more.**

1. **Retries** with exponential backoff and jitter, up to 4 attempts, on transient signals only.
   400/401/402/403/404 are never retried — no amount of waiting fixes a malformed request or an
   unfunded account. `TriageRun.attempts` records how many were needed, so retry pressure is
   visible in the data rather than hidden by it.

2. **A failure-rate guard.** `build_dataset` refuses below a 95% success rate and reports the
   error taxonomy. Retries reduce failures; they cannot promise zero. The guard is what turns a
   thinned run into an error instead of a smaller result, and it is the fix that would have
   caught this had it existed first.

**The general lesson, which belongs in the write-up:** partial failure is more dangerous than
total failure. A pipeline that dies is obvious. A pipeline that quietly completes with a fifth of
its data produces confident numbers about the wrong thing.

### D23 — The real failure was rate limiting, and the real fix was a checkpoint
**D22's retries helped but did not solve it.** Stage 1 improved from 254/991 failures to 18/991,
stage 2 from ~80/100 to 14/100 — still under the 95% guard, which correctly refused to build a
dataset. It also threw away 86 good frontier labels and the **$1.10** they cost.

**The error summary was hiding the diagnosis.** It grouped by exception class, so 13 failures
read as `ModelHTTPError` — a category, not a cause. Grouping by class *and* HTTP status
immediately gave `ModelHTTPError/429: Rate limit exceeded: new-account-rpm/anthropic/claude-sonnet-5`.
A summary that omits the actionable field is not a summary.

**Two causes, not one:**
- **429 on a per-minute account cap.** The generic exponential ramp tops out near 12s and simply
  retried into the same 60-second window alongside every other worker. Rate limits now get a
  backoff sized to the window they police (~25s), while transient connection errors keep the fast
  ramp. Frontier labelling concurrency defaults to 2.
- **`Exceeded maximum output retries (1)`** — pydantic-ai allows a single retry when a model
  fumbles the output schema. Raised to 3; two more attempts cost almost nothing and recover most.

**The fix that actually mattered: a checkpoint.** `LabelCache` appends each successful label as it
returns, keyed by issue and config hash. A re-run pays only for what is missing, and failures are
deliberately not cached because they are what a re-run should retry. Retries reduce failure rates;
they never reach zero, so any expensive stage behind a guard must be resumable or the guard turns
every partial failure into a total loss.

**A bug the test caught that review would not have.** `LabelCache` defines `__len__`, so an empty
cache is falsy, and `if cache:` skipped every write — meaning the cache never populated on a fresh
run, which is precisely the run that most needs it. It would have looked like it worked: no error,
no warning, just a cache that was always empty and a bill that never went down.

### D24 — Dataset built (100 items), and the floor a config has to beat
**Frozen at `f383db39072f4a10`** — 100 items, 60 dev / 40 holdout, labelled by
`anthropic/claude-sonnet-5` against rubric v1, zero failures.

| | P0 | P1 | P2 | P3 | total |
|---|---|---|---|---|---|
| bug | 4 | 26 | 19 | 1 | **50** |
| feature | 0 | 0 | 12 | 2 | **14** |
| docs | 0 | 0 | 1 | 6 | **7** |
| question | 0 | 0 | 1 | 14 | **15** |
| security | 9 | 4 | 1 | 0 | **14** |

`needs_human` is true for 69. Context fires on 86 of 100. 75 carry maintainer labels.

**Stratification only half-worked.** Stage 1 selected near-balanced cells (roughly 15 per
category) but the frontier labeller disagreed with the cheap stratifier often enough that gold
categories came out at 50% `bug`. Stratifying on labels from a weak model biases toward *what
the weak model thinks*, not toward the truth. It still helped — `security` at 14 and `docs` at 7
are far above their natural rate — but the balance target was not met, and cells like `bug/P3`
and `question/P2` hold a single item and cannot move a metric.

**The floor is higher than intuition suggests.** Scoring degenerate strategies against the gold
labels before running any real config:

| baseline | macro-F1 | accuracy | err weight/issue |
|---|---|---|---|
| majority-per-field | 0.133 | 0.50 | **2.27** |
| escalate-everything | 0.133 | 0.50 | **2.27** |
| never-escalate | 0.133 | 0.50 | 8.60 |
| random | 0.197 | 0.20 | 6.87 |

Two things fall out. **macro-F1 earns its place**: always answering `bug` scores 0.50 accuracy
and 0.133 macro-F1, exactly the divergence that made accuracy unusable. And **escalating
everything is near-optimal on `needs_human`** — 69% of items are positive and a missed
escalation costs 10x an unnecessary one, so a blanket escalation policy takes recall 1.00 and
pays only 0.31/issue in over-escalation. That is the cost model being honest, not a defect, but
it sets the bar: **any config scoring worse than 2.27 error weight has earned nothing**, and the
value a real config adds has to come from `category` and `urgency`.

**Caveat to carry into the write-up.** The 69% positive rate is partly a stratification artefact
— oversampling P0 and security pulled in issues that always need a human. Escalate-everything
would look weaker on the true pool distribution.

`harness baselines` reports this for free on any split, and it belongs in the results section
before any config numbers, or a mediocre result reads as a good one.

### D25 — Batch inference: right at scale, wrong here
**Considered** running the eval sweep through OpenRouter's batch endpoints — 50% cheaper and
immune to the rate limits that had been hurting.

**Rejected for this project, on four grounds:**

1. **Latency stops being measurable.** Per-call p50/p95 is one of the three reported axes.
   Batch turnaround is hours, so the number would be meaningless — and reporting it anyway
   would be worse than not having it.
2. **The tier comparison breaks.** Only 66 of 424 catalogue models have a `:batch` variant, and
   `mistralai/mistral-nemo` — the cheapest rung — is not among them. A mixed sweep would compare
   a batched arm against a sync one: a different model id, different routing, different price
   basis. That is the same class of asymmetry the harness already refuses for temperature (D19).
   The alternative is dropping `tier-cheap`, collapsing the price spread from 15.8x to 3x.
3. **The feedback loop is the product.** The harness exists to answer "did that help?" quickly.
   With backoff fixed the sweep runs in minutes; hours of turnaround inverts the point.
4. **Cost is not the constraint.** A full sweep is under $1. The saving is ~$0.40, against a
   separate execution path — hand-rolled JSONL submission, polling, response matching — and the
   loss of pydantic-ai's typed structured output on the way.

**When it flips**, and this belongs in the write-up rather than the code: nightly regression
evals over thousands of issues, CI suites, or backfilling labels for a much larger gold set.
There the discount and rate-limit immunity dominate and nobody is measuring per-call latency.
The harness would gain a submit/poll/collect execution mode beside the sync one, with latency
**dropped** from the reported metrics rather than quietly misreported.

### D26 — Correction: the 25s rate-limit backoff was the bottleneck, not the rate limit
**D23 was wrong.** It diagnosed 429s as a per-minute account cap and reasoned that a backoff
should be sized to the window it polices — a flat 25s. Plausible, and it felt like the
conservative direction.

**Measurement disagreed.** A single worker sustains ~62 req/min; six workers reach ~97/min with
zero errors and zero retries on the real config and payload. 429s clear in about a second.

**The flat wait turned a mild throttle into a projected 17-hour sweep.** The tell was a
spend/progress mismatch: $0.11 spent against a counter showing 30 items — roughly 370 calls for
30 results, which is only possible if nearly every item was burning its full retry budget at 25s
a time.

**Fixed** to the ordinary exponential ramp with a higher ceiling for rate limits (~1.2s, 3.8s,
7.7s, 17.6s). **Backing off longer than a limit requires is not the safe direction — it is just
slower**, and it hid itself as "the API is throttling us" rather than "our retry policy is."

### D27 — Cross-model verification: the weakest label is the one that matters most
**Ran** a cross-model check rather than claiming a human pass. An agent cannot be the human in
"human verification" — a model checking another model's labels against a rubric the same agent
wrote is the circularity D3 exists to prevent. `harness verify sample` exports a stratified
25-item set with **gold labels withheld** (showing them would measure compliance, not judgement),
and `FileLabeller` ingests the human pass when it happens.

**Result** (`x-ai/grok-4.6` vs `claude-sonnet-5`, n=25, 5 per category): category kappa **0.950**,
urgency **0.694** linear-weighted, `needs_human` **0.576**.

**The finding.** The harness's flagship metric is ~72% driven by `needs_human`, which is the
field two frontier models agree on *least*. Category, which they agree on almost perfectly,
barely moves the flagship. Every significant config difference in the sweep came from the least
reliable label.

**Correctly reading the damage.** Random label noise attenuates measured differences toward zero,
and the comparisons are paired, so results that reached significance despite it are still real —
`tier-cheap` (Δ=0.50 on nh recall) and `rationale-pre` both stand. What noise plausibly explains
is some of the *inconclusive* results, which means the "~465 items" sample-size estimates are
optimistic. What pairing cannot correct is a bias both models share, and cross-model agreement is
precisely the wrong instrument for finding one — so this does not substitute for a human pass.

**Two bugs found while building it.**
- The unweighted agreement function returned 1.0 regardless of whether raters agreed, making
  observed agreement 1.00 for every pair. Caught by asserting against known cases: identical
  raters must give kappa 1.0, independent random raters ~0.
- Kappa is *undefined*, not zero, when both raters use a single class. Reporting 0.0 there read
  as "poor agreement" for two raters who agreed on everything.

### D28 — Cost silently defaulting to zero
`x-ai/grok-4.6` returned no cost field while the account was charged **$0.29** for 25 calls, and
`_cost()` fell back to `0.0`. In a harness whose flagship metric is denominated in dollars, an
unreported cost reading as free is the worst direction for the error to run — such a config would
appear to dominate on price.

**Fixed:** runs record `cost_reported`, and `compare` **refuses** any run containing unpriced
calls rather than quietly averaging zeros into the flagship. All eight sweep runs report cost
correctly, so existing results are unaffected; the guard protects future ones.

### D29 — Escalation recall is the whole ranking, and only the mid tier clears the floor
**Corrected after the sweep completed.** An earlier version of this entry claimed *no*
configuration beat "escalate everything". That was written on partial results, before `tier-mid`
finished. It does beat the floor, and clearly.

| | error weight/issue | needs_human recall |
|---|---|---|
| **tier-mid** | **1.50** | 0.92 |
| escalate-everything (floor) | 2.16 | 1.00 |
| prompt-terse | 2.90 | 0.80 |
| rationale-off | 3.32 | 0.64 |
| baseline | 4.24 | 0.51 |
| tier-cheap | 6.92 | 0.19 |
| regress-lean | 7.19 | 0.13 |

**The ranking tracks escalation recall almost perfectly.** Everything else the models do is
swamped by it.

**This is a finding about the metric, not the models.** Broken out per issue, baseline is
**5x better on category** (0.186 vs 0.983) and **3x better on urgency** (0.314 vs 0.941) than
blanket escalation. It loses because missed escalations cost it 3.729 against the floor's zero.

**Breakeven: 4.43x.** Baseline beats blanket escalation only if a missed escalation costs *less*
than 4.43 times an unnecessary one. D4 assumed 10x, unvalidated. The verdict is decided entirely
by that assumption — and the breakeven machinery added specifically to expose this is what made
it visible.

**Root cause is an interaction between two of my own decisions.** The rubric instructs the
labeller "when genuinely torn, choose true" (a deliberate bias toward escalation, since a miss is
costlier). That pushes the positive rate to **76%**. At 76% positive with a 10:1 penalty, blanket
escalation is near-optimal by arithmetic. The rubric and the cost model were each defensible
alone and are jointly degenerate.

**What follows, and what does not.** It does not mean the service is useless — it is doing real
work on the fields the flagship barely weighs. It means **the flagship, as specified, is a poor
proxy for the service's value**: it weights the lowest-information field 10x. When 76% of items
need a human, the escalation decision carries little information, and a metric dominated by it
mostly measures a coin already weighted.

**What a real team would do next**, in order:
1. Derive the cost ratio from observed operational data — how long does an unnecessary escalation
   actually waste, how expensive is a miss in practice — instead of asserting 10:1.
2. Re-examine "when torn, choose true" in the rubric. It biases labels toward the majority class
   and inflates the base rate the metric then rewards.
3. Consider whether `needs_human` belongs in the flagship at all, or whether the service should
   be scored on classification and routing while escalation is handled by a threshold on
   confidence.

**Left as-is deliberately.** Changing the weight now would be choosing a number to get a
preferred answer, which is exactly the failure the pre-registration discipline exists to prevent.
The honest output is the breakeven, reported prominently, and the observation that the headline
question cannot be settled without data we do not have.

### D30 — A harness-directed optimisation that failed, and why the failure is useful
**Hypothesis.** The dev ranking tracks `needs_human` recall almost perfectly, and missed
escalations are ~88% of baseline's error. `prompt-terse` reaches 0.80 recall with a *worse*
prompt. So: keep the rubric's category and urgency precision, and replace its one-line
escalation hint with seven explicit triggers plus "being unsure is itself a reason to answer
true".

**Result: worse on every axis.**

| | baseline | opt-escalate |
|---|---|---|
| needs_human recall | 0.511 | **0.456** |
| macro-F1 | 0.900 | **0.801** |
| error weight/issue | 4.24 | **4.94** |

Recall went *down*. The flagship difference is not significant (needs ~167 items), but it is
firmly in the wrong direction, and category regressed noticeably.

**Likely mechanism, and it is the interesting part.** A seven-item checklist converts an
uncertain judgement into a completable procedure, and "none of these apply" is an easy
conclusion to reach. Structure manufactured confidence. That is consistent with `prompt-terse`,
where vagueness left the model unsure and unsure defaulted to escalating — and with the original
observation that the detailed v2 rubric produces *lower* recall than the terse v1.

**For this decision, more explicit criteria reduce caution.** The lever that works is model
capability (`tier-mid` reaches 0.92 recall), not prompt specificity.

**Cost of learning this: $0.04.** Shipped on intuition it would have been a quiet regression in
the field carrying the 10x weight — which is precisely what the harness exists to prevent, and
what `regress-lean` demonstrates deliberately.

### D31 — Run-to-run variance measured properly at last
SPEC.md §5.5 promised "the same config runs N times; run-to-run variance is reported alongside
the metric". Until now that rested on an accident — `baseline` and `tier-small` happening to hash
identically. Three real repeats each, on identical items:

| config | error weight sd | values |
|---|---|---|
| baseline (gemini-2.5-flash-lite) | **0.0000** | 4.2373, 4.2373, 4.2373 |
| tier-cheap (mistral-nemo) | 0.0135 | 6.9237, 6.8938, 6.8966 |

**Variance is not uniform across configs**, which is why both were run. The flash-lite model at
temperature 0 is byte-identical across independent runs; mistral-nemo is not. Assuming a single
noise figure covered every config would have been the same mistake as assuming one metric covers
every field.

**Every measured difference exceeds the noise floor** (opt-escalate +0.703, rationale-off −0.915,
prompt-terse −1.339, tier-mid −2.742 against a baseline sd of 0.0000), so no finding here is
noise-dominated. `dominated_by_noise` has now been exercised on real data rather than sitting
unused since it was written.

### D32 — The harness found a free fix worth more than a 4x model upgrade
**Found by `harness errors`**, a command that reads committed run records and costs nothing.

**The observation.** The prompt states that any P0 or P1 must escalate. Baseline violates that
on **44% of its own P0/P1 predictions** — 20 of 45 — and 18 of those 20 are genuinely
`needs_human`. That is not the model disagreeing with the labels; it is the model disagreeing
with the instruction it was given, which is a different failure and the only kind with a free
deterministic fix.

**The pattern across configs is the interesting part:**

| config | self-contradiction rate |
|---|---|
| tier-mid | 9% |
| prompt-terse | 12% |
| baseline | 44% |
| rationale-off | 44% |
| tier-cheap | 67% |
| opt-escalate | 67% |

**Self-consistency tracks quality almost exactly.** What the expensive model was buying was
largely the ability to follow the rubric it was handed.

**The fix.** `enforce_rubric`: after the model answers, force `needs_human=True` when it
returned P0 or P1. Pure post-processing — no extra call, no extra token, no extra latency, and
it can only move `needs_human` toward true.

**Screened for free before spending anything.** Because run records store predictions beside
labels, the transform was applied to committed runs and rescored with no API calls. It
predicted 4.24 -> 2.73 for baseline. The live run then matched to three decimals (2.729 both),
with zero self-contradictions remaining — worth running, since the simulation and the service
are separate code paths that could have diverged.

**Results (dev, n=118, paired bootstrap):**

| comparison | Δ flagship | verdict | cost |
|---|---|---|---|
| baseline → rule-escalate | **−1.508** [−2.195, −0.847] | better | $0.00033 → $0.00032 |
| rationale-off → rule-off | **−1.339** [−2.034, −0.720] | better | unchanged |
| **rule-off vs tier-mid** | −0.495 [−1.068, +0.052] | **cannot distinguish** | **$0.00027 vs $0.00105** |

**`rule-off` scores 1.98 — it beats the "escalate everything" floor of 2.16**, which only
`tier-mid` and one free model had managed, and it is statistically indistinguishable from
`tier-mid` at **3.9x lower cost**.

**This changes the recommendation.** D20 and the holdout said buy the better model. The honest
answer is now: apply the rule to the cheap one. The CI on that last comparison only just
includes zero ([−1.068, **+0.052**]), so `tier-mid` may still be genuinely better — but the
difference is not established at n=118, and it costs four times as much.

**Why this is the most useful thing the harness produced.** The brief's framing was "more
accurate but three times the price is a real trade-off". The harness's answer is that the
trade-off was partly avoidable: a chunk of what the expensive model sold was self-consistency,
and self-consistency can be enforced for free once you measure that it is missing. Finding that
required per-field diagnostics, error analysis on stored per-item outputs, and free rescoring
of completed runs — three things built for other reasons.

### D33 — The flagship's field shares were never chosen, and that misattributed blame
**Raised as a criticism of the harness, and it is correct.** The flagship collapses three
fields into one dollar figure. The relative influence of those fields was never decided — it
fell out of the label base rate times a per-error weight:

| field | share of achievable error |
|---|---|
| escalation | **53.9%** |
| urgency | 31.6% |
| category | **14.5%** |

The 10:1 weight was a claim about *one error against another* — a miss costs more than a false
alarm. Combined with a 76% positive rate it silently became a claim about *one field against
another*, handing escalation nearly four times category's influence. Nobody decided that.

**The consequence is misattribution, not just distortion.** Under the dollar flagship,
"escalate everything" (2.20) beats baseline (3.64) on the holdout. But per field:

| | category err | urgency err | escalation err |
|---|---|---|---|
| escalate-everything | **0.525** | 0.263 | 0.091 |
| baseline | **0.062** | **0.083** | 0.419 |

**Baseline is 8x better at category and 3x better at urgency**, and the metric called it worse.
A config that got two of three fields right was reported as the loser because of arithmetic
nobody chose.

**Fix: `balanced_error`.** Each field is normalised by its own worst case first, then weighted
by a share that is stated openly (equal thirds by default, and changeable). The escalation
asymmetry is kept — but as a ratio *within* the field, where it was always meant to live,
rather than across fields. Under it the ranking on the holdout inverts where it should:

| | $ flagship | balanced |
|---|---|---|
| escalate-everything | 2.20 | **0.293 (worst)** |
| baseline | 3.64 (worst) | 0.188 |
| tier-mid | 1.90 | 0.142 |
| **rule-off-v2** | 1.94 | **0.123 (best)** |

**Both metrics are now reported, and the compare output says why.** They answer different
questions. The dollar flagship encodes a business claim about what errors cost and is the right
number for a shipping decision *if you accept its weights*. The balanced view asks which config
is better at the task, without a base rate deciding the answer.

**The config verdicts survive both**, which is the reassuring part: `rule-off-v2` beats baseline
under each (Δ=−1.700 and Δ=−0.065, both significant), and is indistinguishable from `tier-mid`
under each. The shipping decision does not depend on the metric choice. **The floor comparison
does** — and that is the one the earlier write-up got wrong.

**What this says about D29.** The "degenerate optimum" finding was real but half-diagnosed. The
problem was not only that the rubric inflated the base rate; it was that the metric let a base
rate set field importance at all. Two fixes exist and only one was applied before this: fix the
labels (rubric v2), and fix the metric (here).

### D34 — Testing whether configs were fitting one gold set
**Raised as a criticism:** every result was scored against labels from a single labeller under
a single rubric. A config sharing that labeller's biases would score well for the wrong reason,
and nothing in the config tables could reveal it. "Shared blind spot" had been listed as a
limitation and never tested.

**Test.** The full holdout (80 items) was labelled independently by `x-ai/grok-4.6` — a
different lineage from the original labeller and from every config. The same committed runs
were then rescored against both label sets. Rescoring is free: run records store predictions
beside labels, so swapping the gold column costs nothing.

**The labellers really do disagree.**

| field | Cohen's κ |
|---|---|
| category | 0.963 |
| urgency (weighted) | 0.676 |
| needs_human | **0.515** |

And the escalation base rate differs by **19 points — 71% (sonnet) against 52% (grok)**. This
is not a rounding difference; it is the exact bias the criticism predicted.

**With two label sets the rankings looked stable** — but see D35, where a third labeller
overturns this conclusion. The finding below was true of the two sets available at the time and
was stated with more confidence than two raters can support.

Under both metrics and both label sets:

| | $ flagship | balanced |
|---|---|---|
| order under sonnet labels | tier-mid, rule-off-v2, baseline | rule-off-v2, tier-mid, baseline |
| order under grok labels | tier-mid, rule-off-v2, baseline | rule-off-v2, tier-mid, baseline |

**No config appeared to be winning by fitting one labeller.** D35 shows that a third,
independent labeller reorders the top three — so this conclusion did not survive more evidence.

**But the magnitudes are label-dependent, and that matters.** Baseline scores 3.64 under sonnet
and **2.19** under grok — because grok thinks fewer issues need a human, so baseline's weak
escalation recall is punished less. `tier-mid` moves far less (1.90 → 1.71). Ordering survives;
effect sizes do not. Any claim of the form "config A is 1.7 better than B" is a statement about
a labelling as much as about the configs, and should be read that way.

**What would make this stronger.** Two label sets detect whether an ordering moves; they cannot
average out labeller noise. Three or four would allow a genuine consensus label and per-item
disagreement flags. That was budget-limited here (~$0.70 per frontier pass over 80 items) and is
the first thing worth buying with more.

### D35 — A third labeller overturns D34: the fine ordering is not stable
**D34 was premature.** With two label sets the config ranking looked stable and I said so. A
third independent labeller — `openai/gpt-5.1`, lineage distinct from both prior labellers *and*
from every config — shows the ordering moves.

**Unanimity is much lower than two raters implied.** Across the 60 holdout items all three
labelled:

| field | unanimous |
|---|---|
| category | high |
| urgency | 34/60 (56%) |
| needs_human | 32/60 (53%) |
| **all three fields** | **19/60 (31%)** |

**The top config depends on which labeller you ask** (balanced error, best first):

| source | order |
|---|---|
| claude-sonnet-5 | **rule-off-v2**, free-minimax, tier-mid, baseline |
| grok-4.6 | **rule-off-v2**, tier-mid, free-minimax, baseline |
| gpt-5.1 | **free-minimax**, tier-mid, rule-off-v2, baseline |
| majority consensus | **tier-mid**, rule-off-v2, free-minimax, baseline |

**What survives and what does not.** `baseline` is last under every source — that gap is large
and robust. The ordering *among the top three* is not: they sit within 0.01–0.03 of each other
and reshuffle with the labeller. **Large effects survive relabelling; fine distinctions do not.**

That is the honest version of every close call in this project. `rule-off-v2` vs `tier-mid` was
already reported as "cannot distinguish" by the bootstrap; the third labeller says the same
thing from a different direction, and the two agreeing is the reassuring part.

**One result to treat carefully.** On the 19 fully unanimous items, the order *inverts* —
`baseline` best (0.023), `tier-mid` worst (0.081). A tempting reading is that the configs are
indistinguishable on clear-cut items and all measured difference lives in contested ones. **At
n=19 that is not established**, and it would be exactly the kind of small-sample story this
harness exists to refuse. It is recorded as a question worth power, not a finding.

**Caveat on the third set.** `gpt-5.1` completed 60 of 80 items (20 failures), so consensus
covers 60 rather than the full holdout, and the unanimous subset is smaller still.

**What this changes in practice.** Nothing about the shipping recommendation — `rule-off-v2` is
still indistinguishable from `tier-mid` and far cheaper, which was already the conclusion. What
it changes is the *confidence language*: any claim finer than "clearly better than baseline"
should be read as a statement about a labelling as much as about a config.

---

## Still open

- A GitHub token is needed to build the candidate pool. Unauthenticated is 60 req/hr, and PRs
  outnumber issues ~10:1 on litellm, so a single 100-result page yields ~10 issues.
- Whether `rationale` is prompt-visible reasoning the model generates before deciding, or a
  post-hoc explanation. Measurably different token costs, and the first may change decision
  quality. Currently unresolved — it is itself a good first experiment for the harness.
- OpenRouter credits: the top two rungs of the ladder (`gemini-2.5-flash`, `claude-haiku-4.5`)
  and the labeller (`claude-sonnet-5`) returned 402 before funding. Full pipeline estimate is
  $0.74 for labelling plus roughly $2-3 for a complete eval sweep.

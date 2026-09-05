# issue-triage-harness

[![tests](https://github.com/WIRIN-prod/issue-triage-harness/actions/workflows/tests.yml/badge.svg)](https://github.com/WIRIN-prod/issue-triage-harness/actions/workflows/tests.yml)

An evaluation harness for an LLM service, and a small triage service for it to measure.

The service takes a GitHub issue and returns a structured decision: what kind of issue it
is, how urgent, and whether a human needs to see it. **The harness is the point.** The
service exists to be a realistic subject of measurement, and is deliberately small.

## What it answers

*Did this change make the service better, and is it worth what it costs?*

Not "what score did it get." The unit of work is a **comparison** between two
configurations, and the harness is willing to answer **"I can't tell"** — which it did for
four of six comparisons on the dev split.

## Quick start

**From a release** — no clone needed to install, but you want the repo for the data:

```bash
git clone https://github.com/WIRIN-prod/issue-triage-harness && cd issue-triage-harness
uv venv --python 3.12
uv pip install issue_triage_harness-0.1.0-py3-none-any.whl   # or: uv pip install -e ".[dev]"
cp .env.example .env          # add your own GITHUB_TOKEN and OPENROUTER_API_KEY
```

That gives you two commands, `triage` and `harness`.

**Everything needed to reproduce the results is committed**: the frozen dataset (198
labelled issues), the code graph (gzipped, 1.7MB), the issue pool, and all 33 run records.
You do **not** need to clone litellm or rebuild the graph — that only matters if you want to
regenerate it from the pinned SHA.

```bash
triage 39501                              # triage one real issue, with your keys
harness baselines                         # the floor, free — no API calls
harness ledger                            # what has been run, and how often each split was looked at
harness compare runs/<a>.json runs/<b>.json --boot 6000     # free — reads committed runs
harness estimate                          # price a full sweep before spending
harness sweep --split dev --configs baseline tier-mid       # ~$0.12, needs OPENROUTER_API_KEY
```

The first four cost nothing: `baselines`, `ledger`, and `compare` read committed artefacts,
so you can inspect every result in this README without an API key at all.

`pytest` runs 67 tests, none of which need network or credentials.

**How the metrics were chosen and what they changed: [docs/method.md](docs/method.md).**
That is the document to read if you only read one.

Also: [docs/rubric.md](docs/rubric.md) is the labelling standard the dataset was built to —
the definition of "correct" — and [docs/what-would-change.md](docs/what-would-change.md) is
the two-paragraph answer to "what would you change for a different task", which is the cheap
proof that building narrowly was a decision rather than an omission.

Full command list in [docs/configs.md](docs/configs.md). To rebuild from scratch:
`python -m graph.build` (clones litellm at a pinned SHA, extracts the code graph), then
`python -m harness.cli label` (two-stage labelling → frozen dataset).

## What it does

**Metrics per field, because the fields differ mathematically.** Category is multi-class →
macro-F1, since accuracy scores 0.51 on a majority-class guesser where macro-F1 scores
0.135. Urgency is ordinal → MAE, since P0-vs-P3 must cost more than P0-vs-P1.
`needs_human` is binary with asymmetric costs → recall, guarded by precision.

**Two headline numbers, reported together.** The dollar flagship below encodes a business
claim about what errors cost. But its *field shares* were never chosen — they fell out of a 76%
label base rate times a 10:1 per-error weight, giving escalation ~54% of achievable error and
category ~15%. That misattributes: on the holdout it ranks "escalate everything" above the
baseline service, which is **8x better at category and 3x better at urgency**. So a second
metric, `balanced error`, normalises each field by its own worst case and weights them by a
share that is stated openly. Config verdicts agree under both; the floor comparison does not.
See DECISIONS.md D33.

**The flagship, in dollars.** `total cost per issue = LLM spend + expected error
cost`, with error weights stated explicitly (missed escalation 10, unnecessary escalation
1, wrong category 2, urgency by distance). Because the dollar anchor for a weight unit is
a guess, every comparison reports the **breakeven** — the anchor at which the two configs
tie — plus sensitivity across four orders of magnitude.

**Confidence, including refusal.** Paired bootstrap over 10,000 resamples: both configs
face the same items in every resample, so item difficulty drops out. When the interval
straddles zero the harness says `NO SIGNIFICANT DIFFERENCE` and reports how many items
would settle it. Families of diagnostics get Holm-Bonferroni correction, because six tests
at α=0.05 carry a ~26% chance of one false positive.

**The dataset is evaluated too, not assumed.** `harness quality` reports class balance, the
escalation base rate per category, and *metric leverage* — how much of achievable error each
field can contribute, which is a property of the labels rather than any config. And the whole
holdout was labelled a second time by a different-lineage frontier model: the two labellers
disagree meaningfully (needs_human κ=0.515, base rates 71% vs 52%), and a third
(`gpt-5.1`) shows only **31% of items have all three labellers unanimous**. Large effects
survive relabelling — `baseline` is last under every source — but the ordering among the top
three configs reshuffles depending on which labeller you ask. Any claim finer than "clearly
better than baseline" is a statement about a labelling as much as about a config. See
DECISIONS.md D34 and its correction in D35.

**Refusals over warnings.** `compare` will not compare runs scored against different
dataset hashes, runs where temperature was honoured for one arm and silently dropped for
the other, runs containing calls the gateway never priced, or a run that mostly failed.

**A floor to read results against.** `harness baselines` scores degenerate strategies for
free. On this dataset "escalate everything" scores 2.16 error weight — a config that
doesn't beat that has earned nothing, and only two do.

## What the evaluation showed

Full numbers and caveats in [RESULTS.md](RESULTS.md).

**Three of ten dev comparisons were inconclusive, and two of three on the holdout.** Those
are differences a team would have shipped on a vibe. (At the earlier n=60 it was four of six —
more data resolves more comparisons, which is the sample-size argument demonstrated rather
than asserted.)

**The best result: the price difference bought nothing.** A free post-processing rule —
enforcing the escalation triggers the prompt already states, when the model contradicts itself
on 44% of its own P0/P1 predictions — makes the cheap config **statistically indistinguishable
from the 4x dearer model** on the holdout (Δ=−0.037, CI [−0.562, +0.413]), at **$0.00026 vs
$0.00103** and 36% lower latency. How that was found, run by run:
[docs/improvement-log.md](docs/improvement-log.md).

**The model-tier trade-off, before that fix.** `tier-mid` costs
5.3× more per issue — significant and precisely measured — and on the holdout it was
significantly better (flagship Δ=−1.737, CI [−2.799, −0.712]), driven by escalation recall
rising 0.54 → 0.86. Error cost exceeds inference cost by roughly 2,000× here, so *quality
dominates cost so completely that "5× more expensive" is a red herring.*

**And the assumption behind that verdict is reported, not hidden.** The escalation-weight
breakeven is **2.28×**: `tier-mid` wins as long as a missed escalation costs more than 2.28×
an unnecessary one, against the 10× we assumed. The conclusion survives that assumption being
wrong by a factor of four.

**A single aggregate would have hidden the most important failure.** `mistral-nemo` scores a
respectable 0.827 macro-F1 and escalation recall of **0.19** — it classifies competently and
refuses to escalate. Per-field diagnostics made that one line.

**Free models compete, and the cost axis isn't dollars.** `minimax-m3:free` **beats the
floor** (1.93 vs 2.16) at **zero marginal cost** — at 4× the latency. Of eight free models
with structured output, four failed a single probe call, and `nemotron-3-super` posted the
best macro-F1 of anything here on the 24 of 60 calls that returned. That is survivorship
bias, and the harness now refuses runs below 90% success.

**We got a prediction wrong.** Repo context was expected to help `category`. It didn't —
`context-none` scores *better* macro-F1 and urgency MAE, and loses only on escalation
recall. Context earns its ~1,050 tokens through escalation judgement, not classification.

## Assumptions

Open questions we'd normally put to a stakeholder, with the assumption taken, are in
[SPEC.md §8](SPEC.md). The load-bearing ones:

- **A missed escalation costs 10× an unnecessary one.** Drives the flagship, so sensitivity
  to it is reported with every comparison.
- **This pre-sorts a human queue** rather than auto-labelling unattended, which is why
  escalation recall dominates.
- **Urgency is absolute**, not relative to a repo's own norms.
- **A maintainer triaging an issue already knows the codebase**, so repo context is on by
  default — priced once via a `context: none` run rather than left as belief.

## Known limitations

- **118 dev / 80 holdout.** Underpowered for small effects — which is why several
  comparisons return "can't tell" alongside the sample size that would settle them.
- **Dev has been evaluated 18 times** (`harness ledger` counts it). Those figures are
  optimistic by an unquantified amount; the holdout was looked at once per dataset version.
- **The flagship is ~88% escalation error**, and its optimum is degenerate: only two configs
  beat "escalate everything", because the rubric's *"when torn, choose true"* pushes the
  positive rate to 76% and a 10:1 penalty then rewards blanket escalation. Two of our own
  decisions, each defensible alone, are jointly degenerate — documented in
  [RESULTS.md §10](RESULTS.md) rather than tuned away.
- **The gold set is model-labelled.** Cross-model κ is 0.95 / 0.69 / **0.58** — and the
  weakest field is the one the flagship leans on hardest. Two label errors were confirmed
  by three independent raters including a human; a systematic urgency inflation for
  feature requests was found, quantified, and shown not to change any verdict.
- **One repo, one three-month window.** Generalisation is untested, not claimed.
- **No production monitoring.** Deliberately — the boundary is documented in
  [SPEC.md §10](SPEC.md) rather than built.

## How this was built

[DECISIONS.md](DECISIONS.md) is a chronological log, reversals included — repo context was
adopted, made a flag, cut, then reinstated for a different reason; a flat rate-limit
backoff that felt conservative turned a 6-minute sweep into a projected 17-hour one.

Several bugs in this repo were found by the harness's own discipline rather than by
reading code: a labelling run that silently produced a fifth of its data and hashed
cleanly; a cost field defaulting to `$0` when a gateway reported nothing; an agreement
function that returned perfect agreement for every pair; a cache that never populated
because it defined `__len__` and was therefore falsy when empty.

Layout, conventions, and the rules that constrain the config space: [CLAUDE.md](CLAUDE.md).

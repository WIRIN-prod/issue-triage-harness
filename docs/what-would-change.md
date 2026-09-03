# What would change for a different task

SPEC.md §9 argues this harness is built narrowly on purpose: the metric is a function of
the task, so the one component a generic framework would need to generalise is the one
that can't. This is the two-paragraph version of what actually moves — the cheap proof
that the narrowness is a decision rather than an omission.

## If the service summarised issues instead of classifying them

**The metric layer is replaced entirely.** There is no `==` to compute: a summary has many
acceptable forms, so scoring needs an LLM judge against a rubric — which drags back
everything §5.6 removed, namely judge cost, judge variance, and judge bias. The judge then
needs its own validation against human labels, so the agreement machinery in
`agreement.py` moves from being a one-off dataset check to running on every evaluation.
Reference summaries replace categorical labels in the dataset, and `TriageDecision`'s
`Literal` types — the thing that made scoring deterministic — no longer apply.

**Almost everything else survives untouched.** Config addressability and hashing, the
frozen dataset with its refusal to compare across versions, paired bootstrap and the
`NO SIGNIFICANT DIFFERENCE` verdict, Holm-Bonferroni over the diagnostic family, per-call
cost and latency in the response envelope, the baseline floor, the run-quality and
unpriced-cost guards, the checkpointed labelling pipeline — none of that knows or cares
what the task is. What changes is `metrics.py` and the shape of a gold label. What stays
is the method: define correct, build labels you can defend, measure with uncertainty
attached, price the errors, and decide against a rule written down in advance.

## Sketches for two other tasks

**Retrieval / RAG.** Gold becomes relevant-document sets. Metrics become recall@k, MRR,
and groundedness — the last needing a judge, with the same validation burden as above. The
error-cost model still works and is arguably clearer: a missed relevant document and a
hallucinated citation have genuinely different operational costs, and writing those down
is the same exercise as the 10:1 escalation weight here.

**Code generation.** This one gets *easier*, not harder. "Does it pass the tests" is
deterministic, so no judge is needed and scoring stays `==`-shaped. The flagship becomes
`inference cost + expected cost of a failing patch`, and the interesting difficulty moves
to test-suite quality — which is the same problem as label quality, wearing different
clothes.

## What we would build if this ran nightly at scale

Not a generic framework — a second **execution mode**. Batch inference (50% cheaper,
rate-limit immune) for sweeps over thousands of issues, with per-call latency **dropped**
from the reported metrics rather than quietly misreported, since batch turnaround makes it
meaningless (DECISIONS.md D25). Plus sampled human review of production traffic feeding
back into new dataset versions, and a coverage check that answers "is this input inside
the region the dataset covers" — which is knowable, unlike "is this particular answer
right", which is not (SPEC.md §10).

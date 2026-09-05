# Improvement log — what each harness run showed, and what changed because of it

The brief asks to see the reasoning, not a polished write-up. This is the loop as it
actually ran: what the harness reported, what that implied, what was changed, and what the
next run said about the change. Two of the six iterations were failures, and both taught
more than the successes.

Numbers are dev (n=118, rubric v2) unless marked. The machine-readable version of this
history is `harness ledger`, which reconstructs it from the run records themselves.

---

## Iteration 0 — establish a baseline and a floor

**Ran.** Eight configs across the model ladder, prompt variants, and context on/off.

**What the harness showed.** Two things, one expected and one not.

The expected: a wide spread, with `tier-mid` best at 1.50 error weight and `tier-cheap`
worst at 6.90.

The unexpected: **`harness baselines` put the "escalate everything" floor at 2.16**, and only
one config beat it. Reading config scores without that floor would have made a mediocre
result look respectable.

**Insight.** Per-field diagnostics showed the ranking tracked `needs_human` recall almost
perfectly, and the error breakdown put **88% of baseline's error in missed escalations**
(3.729 of 4.238). Improving category further was near-worthless.

**Changed.** Nothing yet — but every later iteration targets escalation, because this run
said everything else was noise by comparison.

## Iteration 1 — prompt engineering, which failed

**Hypothesis.** Escalation recall drives the ranking. `prompt-terse` — a *vaguer* prompt —
reached 0.80 recall against the detailed rubric's 0.51. So: keep the rubric's category and
urgency precision, replace its one-line escalation hint with seven explicit triggers plus
*"being unsure is itself a reason to answer true"*.

**Ran.** `opt-escalate`, one config, $0.04.

**What the harness showed.** Worse on every axis:

| | baseline | opt-escalate |
|---|---|---|
| needs_human recall | 0.511 | **0.456** |
| macro-F1 | 0.894 | **0.801** |
| error weight | 4.24 | **4.94** |

**Insight.** A seven-item checklist converts an uncertain judgement into a *completable
procedure*, and "none of these apply" is an easy conclusion to reach. **Structure
manufactured confidence.** That single explanation covers three separate observations: terse
beats detailed, detailed beats seven-trigger, and the deliberate regression — which *tells*
the model to be selective — sits bottom of the table.

**Changed.** Abandoned prompt specificity as the lever. Cost of learning that: **$0.04**,
versus shipping a silent regression in the field carrying the heaviest penalty.

## Iteration 2 — the harness turned on its own labels

**Signal.** Cross-model agreement was 0.95 on category but **0.69 on urgency**. Worth a look
rather than a shrug.

**What the harness showed.** Feature requests were rated **78% P2**, where the rubric
reserved P2 for *"clear demand"*. In a real tracker most feature requests come from one
person with no demand evidence — the phrase was being read as *"clearly written"*.

**Changed.** Rubric v2 makes the test observable: promote only on more than one requester,
maintainer intent, or a widely-used path. A detailed write-up is explicitly not demand.

**Result.** Feature P2 rate **78% → 17%**. Dataset re-labelled and doubled to 198 items.

**Verified for free.** Before trusting the fix, we asked whether the old bias had changed any
conclusion. Because run records store each item's gold label beside the prediction, the
correction was applied to completed runs and rescored with no API calls: **all six verdicts
unchanged**. The honest reading is less comforting — they survived because the flagship
barely measures urgency, not because the labels were sound.

## Iteration 3 — error analysis found a free fix

**Ran.** `harness errors` on a committed run. Cost: nothing.

**What the harness showed.** The prompt states any P0 or P1 must escalate. Baseline violates
that on **44% of its own P0/P1 predictions** (20 of 45), and **18 of those 20 are genuinely
needs_human**. That is the model disagreeing with its own instructions, not with the labels —
a different failure, and the only kind with a free deterministic fix.

And across configs the rate tracks quality almost exactly:

| config | self-contradiction |
|---|---|
| tier-mid | 9% |
| baseline | 44% |
| tier-cheap | 67% |

**Insight.** Much of what the expensive model was selling was **self-consistency** — the
ability to follow the rubric it was handed. That can be enforced for free, once measured.

**Changed.** `enforce_rubric` v1: after the model answers, force `needs_human=True` when it
returned P0/P1. Post-processing only — no extra call, token, or millisecond.

**Screened free, then confirmed.** The transform was applied to committed runs first,
predicting 4.24 → 2.73. The live run matched to three decimals (2.729 both) with zero
contradictions remaining — worth confirming, since the simulation and the service are
separate code paths that could have diverged.

**Result.** baseline **4.24 → 2.73** at identical cost. Paired: Δ=−1.508 [−2.195, −0.847].

## Iteration 4 — extending the rule, and one extension refused

**Question.** Which other categories does the rubric make unconditional?

**What the harness showed**, checked across *both* splits before trusting:

| category | needs_human (dev) | (holdout) |
|---|---|---|
| security | 13/13 | 9/9 |
| question | 15/15 | 8/9 |
| feature | 20/26 | 13/21 |

**Changed.** `enforce_rubric` v2 adds `security` (the rubric states it outright) and
`question` (follows from its own fallback: empty issues are categorised `question`, and
insufficient information is escalation trigger A).

**Refused.** `feature → always escalate` would have fixed 12 of the 15 residual misses. Gold
is only **70%** across both splits, so forcing it is tuning on the dev set rather than reading
the rubric back. The misses stay.

**Result.** `rule-off` 1.98 → **1.91**. Weak models gain most: `tier-cheap` 4.62 → 3.53.

## Iteration 5 — a cascade, dominated by the free rule

**Hypothesis.** Self-contradiction marks the items the cheap model is confused about. Route
only those to `tier-mid` — most of the quality at a fraction of the price.

**Simulated free.** Both arms had already run on identical items, so the routing could be
evaluated with zero API calls.

**What the harness showed.**

| | error weight | $/issue |
|---|---|---|
| cascade (cheap + escalate confused items) | 1.96 | $0.00055 |
| **the free rule alone** | **1.91** | **$0.00027** |

**The cascade is worse and twice the price.** Once the rubric is enforced those items are
already handled, so paying the expensive model for them buys nothing.

**Changed.** Nothing. A rejected architecture, at zero cost.

## Iteration 6 — the harness caught the harness

**Found while extending the rule.** `enforce_rubric` was a boolean. Editing the rule's
*implementation* changed behaviour while the config hash stood still — old and new runs would
share a hash and be silently incomparable. Prompt *content* was hashed; rule *content* was
not. The same hole the prompt hash was built to close, reopened for post-processing.

**Changed.** Versioned it: `off | v1 | v2`, so the version enters the hash and prior runs stay
comparable to each other. That invalidated every existing run — the freeze discipline working,
at a cost of $0.26 to re-establish.

---

## Where the service ended up — decided on the holdout

Dev (n=118) proposed; the holdout (n=80, looked at once) decided.

| config | macro-F1 | nh recall | error weight | $/issue | p50 latency |
|---|---|---|---|---|---|
| tier-mid | 0.928 | 0.86 | 1.90 | $0.00103 | 1730 ms |
| **rule-off-v2** | 0.872 | 0.81 | **1.94** | **$0.00026** | **1104 ms** |
| baseline (start) | 0.872 | 0.54 | 3.64 | $0.00032 | 1661 ms |
| *floor* | *0.129* | *1.00* | *2.20* | *—* | *—* |

| verdict (holdout) | Δ | 95% CI | |
|---|---|---|---|
| baseline → rule-off-v2 | **−1.700** | [−2.713, −0.750] | **better** |
| **rule-off-v2 vs tier-mid** | **−0.037** | [−0.562, +0.413] | **cannot distinguish** |
| baseline → tier-mid | −1.737 | [−2.787, −0.724] | better |

**The 4x price difference bought nothing measurable.** On dev the gap to `tier-mid` was 0.41;
on the holdout — the estimate that counts — it is **0.037**, with a CI comfortably straddling
zero.

`rule-off-v2` is **4x cheaper, 36% faster, and cheaper than the baseline it improves on**,
because dropping the rationale removes output tokens. It beats the floor; baseline never did.

**Recommendation: ship `rule-off-v2`.** Iteration 3's finding is why — a large part of what the
expensive model sold was self-consistency, and self-consistency turned out to be free once the
harness measured that it was missing.

**Note the reversal.** After the first holdout, the recommendation was "buy the better model"
(D20). Two iterations later the answer is "apply a free rule to the cheap one". The harness
changed its own conclusion, on evidence, and the earlier decision is left in the log rather
than edited away.

None of that came from a better prompt. It came from measuring which field mattered (iteration
0), learning that prompts were not the lever (1), trusting the labels enough to act on them
(2), and noticing the model was contradicting its own instructions (3–4). Two of the six
iterations produced no change at all, and the cascade rejection saved more than most of the
successes earned.

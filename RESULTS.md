# Results

**Dataset** `7f44e8bd524b51b0` — 198 real litellm issues, rubric v2, 118 dev / 80 holdout.
**Cost** of every run reported here: **~$1.20**. Whole project, including four discarded
labelling attempts: ~$7.9.

All numbers come from committed run records via `harness sweep` and `harness compare`.

---

## 1. Read the floor first

Before any config number means anything: what does a strategy with no intelligence score?

| baseline strategy | macro-F1 | error weight/issue |
|---|---|---|
| **escalate-everything** | 0.135 | **2.16** (dev) · **2.20** (holdout) |
| never-escalate | 0.135 | 9.55 |
| random | 0.153 | 7.66 |

`needs_human` is 76% positive and a missed escalation costs 10x an unnecessary one, so
blanket escalation is a strong policy. **A config that does not beat 2.16 has earned
nothing.** `harness baselines` prints this for free on any split.

## 2. Dev (n=118)

| config | macro-F1 | urg MAE | nh recall | **err wt** | $/issue | p50 ms |
|---|---|---|---|---|---|---|
| **tier-mid** `gemini-2.5-flash` | 0.894 | 0.58 | 0.92 | **1.50** | $0.00105 | 1975 |
| **free-minimax** `minimax-m3:free` | 0.884 | 0.31 | 0.82 | **1.93** | **$0.00000** | 6918 |
| *floor — escalate everything* | *0.135* | *0.82* | *1.00* | *2.16* | *—* | *—* |
| prompt-terse | 0.755 | 0.69 | 0.80 | 2.90 | $0.00023 | 1401 |
| rationale-off | 0.856 | 0.37 | 0.64 | 3.32 | $0.00026 | 1061 |
| context-none | 0.879 | 0.26 | 0.55 | 3.91 | $0.00024 | 1657 |
| baseline `gemini-2.5-flash-lite` | 0.894 | 0.30 | 0.51 | 4.24 | $0.00020 | 1595 |
| rationale-pre | 0.892 | 0.26 | 0.49 | 4.36 | $0.00034 | 1768 |
| opt-escalate *(attempted fix)* | 0.801 | 0.35 | 0.46 | 4.94 | $0.00033 | 1517 |
| free-liquid `lfm-2.5-2.6b:free` | 0.803 | 0.49 | 0.38 | 5.59 | $0.00000 | 5052 |
| tier-cheap `mistral-nemo` | 0.827 | 0.40 | 0.19 | 6.90 | $0.00003 | 3787 |
| regress-lean *(deliberate)* | 0.862 | 0.35 | 0.13 | 7.19 | $0.00027 | 1522 |

**Two configs beat the floor.** The ranking tracks `needs_human` recall almost perfectly —
everything else the models do is swamped by it.

## 3. Holdout (n=80) — the decisions

Looked at once, for final candidates only.

| config | macro-F1 | urg MAE | nh recall | err wt |
|---|---|---|---|---|
| **tier-mid** | 0.928 | 0.62 | 0.86 | **1.90** |
| *floor* | *0.129* | *0.79* | *1.00* | *2.20* |
| prompt-terse | 0.757 | 0.71 | 0.74 | 3.14 |
| rationale-off | 0.872 | 0.31 | 0.61 | 3.23 |
| baseline | 0.872 | 0.25 | 0.54 | 3.64 |

| vs baseline | Δ flagship | 95% CI | verdict | breakeven escalation weight |
|---|---|---|---|---|
| **tier-mid** | **−1.737** | [−2.799, −0.712] | **B_BETTER** | **2.28x** |
| rationale-off | −0.413 | [−1.150, +0.287] | no significant difference (needs ~234) | 1.75x |
| prompt-terse | −0.500 | [−1.463, +0.400] | no significant difference (needs ~274) | 6.36x |

## 4. The headline trade-off

`tier-mid` costs **5.3x more per issue** ($0.00105 vs $0.00020) — significant and precisely
measured — and is **significantly better on the holdout**.

The price is not what decides it. LLM spend differs by ~$0.0009/issue; error cost differs by
~$1.74/issue — **nearly 2,000x larger**. At these prices quality dominates cost so completely
that "5x more expensive" is a red herring.

**Breakeven on the escalation assumption: 2.28x.** `tier-mid` wins as long as a missed
escalation costs more than 2.28 times an unnecessary one. We assumed 10x. The conclusion
therefore survives that assumption being wrong by a factor of four — which is a far stronger
claim than a sensitivity table.

**Free models are competitive, and the cost axis is not only dollars.** `minimax-m3:free`
beats the floor at **zero marginal cost**, at 4x the latency. Of eight free models with
structured-output support, four failed a single probe call, and one posted the best macro-F1
of anything here on the 24 of 60 calls that returned — survivorship bias the harness now
refuses.

## 5. What a single aggregate would have hidden

`mistral-nemo` has a respectable **0.827 macro-F1** and `needs_human` recall of **0.19**. It
classifies competently and refuses to escalate. Any blended score would have read "somewhat
below average". Per-field diagnostics made it one line.

## 6. The deliberate regression

A prompt that reads like an improvement — *"maintainer attention is the scarcest resource, be
selective about escalating"* — the change a well-meaning engineer ships to cut reviewer noise:

| | baseline | regress-lean |
|---|---|---|
| needs_human recall | 0.51 | **0.13** |
| error weight | 4.24 | **7.19** |
| $/issue | $0.00020 | **$0.00027** |
| p50 latency | 1595 ms | **1522 ms** ← faster |

Cheaper on error-free surface metrics, faster, and catastrophically worse. Every metric a
naive evaluation reports says ship it.

## 7. An optimisation the harness rejected

Escalation recall drives the ranking, so `opt-escalate` replaced the rubric's one-line
escalation hint with seven explicit triggers plus "being unsure is itself a reason to answer
true".

**Recall fell** (0.51 → 0.46) and category regressed (0.894 → 0.801).

Best explanation: a seven-item checklist converts an uncertain judgement into a *completable
procedure*, and "none of these apply" is an easy conclusion. Structure manufactured
confidence — consistent with `prompt-terse`, where a vaguer prompt scores *higher* recall.
For this decision, more explicit criteria reduce caution; the lever that works is model
capability. **Cost of learning this: $0.04.**

## 8. Is any of it noise?

Three runs of each config on identical items:

| config | error weight sd | values |
|---|---|---|
| baseline | **0.0000** | 4.2373, 4.2373, 4.2373 |
| tier-cheap | 0.0135 | 6.9237, 6.8938, 6.8966 |

`gemini-2.5-flash-lite` is perfectly deterministic at temperature 0; `mistral-nemo` is not —
so variance is **not** uniform across configs, which is why two were measured. Every reported
difference exceeds the noise floor by a wide margin.

## 9. Can the labels be trusted?

**Three independent labellers, chosen from three different lineages** — and deliberately
different from every config's lineage too, so a labeller cannot quietly favour a config that
shares its training.

| | labeller |
|---|---|
| gold | `anthropic/claude-sonnet-5` |
| second | `x-ai/grok-4.6` (80/80 holdout items) |
| third | `openai/gpt-5.1` (60/80 — 20 failures) |

**Pairwise agreement** (gold vs grok, full holdout):

| field | Cohen's κ | reading |
|---|---|---|
| category | 0.963 | strong |
| urgency (weighted) | 0.676 | substantial |
| **needs_human** | **0.515** | **moderate** |

**Three-way unanimity is much lower than two raters implied:**

| field | unanimous across all three |
|---|---|
| urgency | 34/60 (56%) |
| needs_human | 32/60 (53%) |
| **all three fields** | **19/60 (31%)** |

### The ranking depends on which labeller you ask

The same committed runs, rescored against each label source (balanced error, best first):

| source | order |
|---|---|
| claude-sonnet-5 | **rule-off-v2**, free-minimax, tier-mid, baseline |
| grok-4.6 | **rule-off-v2**, tier-mid, free-minimax, baseline |
| gpt-5.1 | **free-minimax**, tier-mid, rule-off-v2, baseline |
| majority consensus | **tier-mid**, rule-off-v2, free-minimax, baseline |

> **Large effects survive relabelling; fine distinctions do not.**

`baseline` is last under *every* source — that gap is real. The top three sit within 0.01–0.03
of each other and reshuffle. **Any claim finer than "clearly better than baseline" is a
statement about a labelling as much as about a config.**

**Two independent methods agree on where the uncertainty lives.** The paired bootstrap had
already reported `rule-off-v2` vs `tier-mid` as *cannot distinguish*; relabelling says the same
thing from a completely different direction. That agreement is worth more than either alone, and
it means the shipping recommendation is unaffected.

**A conclusion that was published and then withdrawn.** With two label sets the ranking looked
stable and was written up as such (DECISIONS.md D34). The third labeller overturned it (D35).
The correction lives in the log rather than being edited into the original.

**A result deliberately not claimed.** On the 19 fully unanimous items the order *inverts* —
`baseline` best (0.023), `tier-mid` worst (0.081). The tempting reading is that configs are
indistinguishable on clear-cut items and every measured difference lives in contested ones. At
**n=19** that is not established, and it is exactly the small-sample story this harness exists
to refuse. Logged as a question worth power, not a finding.

**Also fixed: a systematic labelling bias.** Rubric v1 rated 78% of feature requests P2 where it
reserved P2 for "clear demand" — the phrase was being read as "clearly written". Rubric v2 makes
the test observable. Feature P2 rate fell to **17%**.

**And the dataset is now evaluated in its own right.** `harness quality` reports class balance,
escalation base rate per category, and *metric leverage* — how much of achievable error each
field can contribute, which is a property of the labels rather than any config. It is what made
§10 diagnosable.

## 10. The most important finding — about the metric, not the models

Broken down per issue on dev:

| cost component | baseline | escalate-everything |
|---|---|---|
| missed escalations | **3.729** | 0.000 |
| unnecessary escalations | 0.008 | 0.237 |
| wrong category | 0.186 | **0.983** |
| wrong urgency | 0.314 | **0.941** |
| **total** | **4.237** | **2.161** |

**Baseline is 5x better at category and 3x better at urgency — and loses anyway.**

Two of our own decisions, each defensible alone, are jointly degenerate: the rubric tells the
labeller *"when genuinely torn, choose true"* (pushing the positive rate to 76%), and a missed
escalation costs 10x. At 76% positive with a 10:1 penalty, blanket escalation is near-optimal
by arithmetic — so the flagship weights the **lowest-information field** above everything else.

**The weight was deliberately not changed.** Adjusting an assumption after seeing results, to
obtain a nicer answer, is exactly the failure that stating the rule in advance exists to
prevent. The honest output is the breakeven, reported prominently, plus the admission that the
question cannot be settled without operational data we do not have.

What a real team would do next: derive the cost ratio from observed operations; revisit "when
torn, choose true", which inflates the base rate the metric then rewards; and consider whether
`needs_human` belongs in the flagship at all rather than being a confidence threshold.

## 11. Caveats

- **118 dev / 80 holdout.** Underpowered for small effects — which is why several comparisons
  return "can't tell" with the sample size that would settle them.
- **Dev has been evaluated 18 times** (`harness ledger` counts it). Those figures are
  optimistic by an unquantified amount; holdout was looked at once per dataset version.
- **The flagship is ~88% escalation error.** It measures the routing decision well; the rest
  are diagnostics, not a general quality score.
- **`free-minimax` has no holdout run** — it beat the floor on dev but was not a final
  candidate when the holdout was spent.
- **Stratification oversamples security and P0**, inflating the escalation base rate. Not a
  production estimate.
- **One repo, one three-month window.** Generalisation untested, and not claimed.

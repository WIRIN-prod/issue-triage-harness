# Method — how the metrics were chosen, and what they changed

This is the part worth reading. The code is plumbing; the decisions below are the work.

---

## 1. The question

Not *"how good is the service"* but:

> **Did this change make it better, and is it worth what it costs?**

That reframing does most of the design work. It means the unit of output is a **comparison**,
not a score; that a change must be attributable to one cause; and that "I can't tell" has to
be a legitimate answer, because most of the time it is the true one.

## 2. Choosing what to measure

### 2.1 Category — why not accuracy

~50% of issues are bugs. A service that ignores its input and always answers `bug` scores
**0.51 accuracy**. Accuracy rewards a constant.

**Macro-F1** scores each class separately and averages, so ignoring four classes is
punished: the same constant scores **0.135**.

> That 0.51 vs 0.135 gap is the entire argument, and `test_accuracy_flatters_a_majority_class_guesser`
> asserts it so the reasoning cannot rot.

### 2.2 Urgency — why not exact match

P0–P3 are **ordered**. Predicting P1 for a P0 is a near miss; predicting P3 is a disaster.
Exact match calls both simply "wrong", discarding the information that matters.

We use **mean absolute distance** on the scale, and the error model prices distance
non-linearly (1 / 3 / 6 for one / two / three steps).

### 2.3 needs_human — why not either of the above

The two errors are not equally costly. Escalating unnecessarily wastes minutes; failing to
escalate leaves a real problem unlooked-at. So we measure **recall on the positive class**,
guarded by precision, and price the errors asymmetrically.

**One metric could not have covered these three fields.** They differ in kind — nominal,
ordinal, asymmetric-binary — and a blended score would have hidden the single most important
diagnostic finding in the project (§2.5).

### 2.4 Combining into one number

Three metrics are hard to act on, so both errors and inference are converted to dollars:

```
total cost per issue  =  LLM spend  +  expected error cost
```

with weights stated in the open: missed escalation 10, unnecessary 1, wrong category 2,
urgency by distance.

**The anchor is a guess, so we never rely on it.** Every comparison reports the **breakeven** —
the assumption value at which the verdict flips. That converts *"we assumed 10:1"* into
*"this conclusion holds as long as a miss costs more than 2.28x an unnecessary escalation"*,
which a stakeholder can argue with. Two breakevens are reported: the dollar anchor, and the
escalation weight itself.

### 2.5 What per-field measurement caught

`mistral-nemo` scores **0.827 macro-F1** — competent — and **0.19 needs_human recall**. It
classifies well and refuses to escalate. Any single blended number would have read "somewhat
below average". The per-field table showed it in one line, and it is the clearest evidence
that the metric split earned its complexity.

## 3. Knowing when a difference is real

### 3.1 Paired bootstrap

Config A scores 4.24, config B scores 3.32. Is B better, or did B get an easier draw?

Resample the 118 issues with replacement, score both configs on that draw, record the
difference, repeat 10,000 times. The middle 95% of those differences is the confidence
interval. If it includes zero, we cannot tell.

**Paired** means both configs face the *identical* draw each time, which removes "some issues
are harder" from the comparison entirely and makes it far more sensitive than comparing two
independent means.

### 3.2 Refusing to call it

**Four of six dev comparisons came back inconclusive.** That is the harness working, not
failing — most were differences a team would ship on a hunch. Each reports the sample size
that *would* settle it, and when the effect is indistinguishable from zero it says so rather
than printing an absurd number.

### 3.3 Two noise sources, both measured

Sampling noise is handled by the bootstrap. **Run-to-run noise** is measured directly: the
same config, three times, on identical items.

| config | error weight sd |
|---|---|
| `gemini-2.5-flash-lite` | **0.0000** |
| `mistral-nemo` | 0.0135 |

Variance is **not** uniform across configs, which is why two were measured rather than
assuming one figure covered all. Every reported difference exceeds this floor.

### 3.4 Multiple comparisons

Six diagnostics at 95% confidence is a ~26% chance of one false alarm. Holm-Bonferroni
correction is applied across the diagnostic family; it immediately demoted one finding from
"significant" to "can't tell". The flagship is excluded — it is one pre-registered question,
not one of a family fished for significance.

## 4. Knowing when the *measurement* is untrustworthy

A harness that only measures the service is half a harness.

**A floor.** Before any config number means anything: what does an unintelligent strategy
score? "Escalate everything" scores **2.16**. Anything above that has earned nothing, and
`harness baselines` prints it for free.

**Label agreement.** A model from a different lineage labelled 25 items blind. Cohen's κ:
category 0.95, urgency 0.69, **needs_human 0.58**. The weakest label is the one the flagship
leans on hardest — and κ is also a *ceiling*, telling you when further optimisation is
chasing noise.

**Refusals.** `compare` refuses rather than warns: different dataset hashes, temperature
honoured for one arm and dropped for the other, unpriced calls, and any run below 90% success.
A warning gets scrolled past; a refusal cannot.

**A look counter.** `harness ledger` counts how often each split was evaluated — dev 18
occasions, holdout once per version. Every look at dev is a chance to tune toward it, and that
leak is invisible unless counted.

---

## 5. How the metrics actually changed the service

Two complete loops. One improved the measurement; the other tried to improve the service and
failed usefully.

### Loop 1 — the metric found a flaw in the labels, and fixed it

**Signal.** Cross-model agreement on urgency was 0.69 — weaker than category's 0.95. Worth a
look rather than a shrug.

**Diagnosis.** Manual review of the sample showed feature requests rated **78% P2**, where the
rubric reserved P2 for *"clear demand"*. In a real tracker most feature requests come from one
person with no demand evidence. The phrase was being read as *"clearly written"* — a detailed
write-up was being scored as a popular one.

**Change.** Rubric v2 makes the test **observable**: promote to P2 only on more than one
requester, maintainer intent, or a widely-used path. A detailed write-up is explicitly not
demand.

**Result.** Feature P2 rate fell **78% → 17%**.

**Verification.** Before trusting it, we asked whether the old bias had changed any conclusion.
Because run records store each item's gold label beside the prediction, corrections can be
applied to completed runs for free — no re-running. Flipping all affected items: **all six
verdicts unchanged.**

**But the honest reading is less comforting.** The conclusions survived because the flagship
*barely measures urgency* — it is ~88% escalation error, where an urgency step costs 1 against
a missed escalation's 10. The metric was insensitive to the bias because it was largely
ignoring the biased field, not because the labels were sound.

### Loop 2 — the metric pointed at a lever, and the lever did the opposite

**Signal.** The dev ranking tracks `needs_human` recall almost perfectly. Baseline's error
breakdown:

| component | per issue |
|---|---|
| missed escalations | **3.729** |
| wrong category | 0.186 |
| wrong urgency | 0.314 |

**88% of the error is one field.** Improving category further would be near-worthless.

**A second signal, which should have been a warning.** `prompt-terse` — a *vaguer* prompt —
reached **0.80** recall against the detailed rubric's **0.51**.

**Hypothesis.** Keep the rubric's category and urgency precision, but replace its one-line
escalation hint with seven explicit triggers plus *"being unsure is itself a reason to answer
true"*.

**Result: worse on every axis.**

| | baseline | opt-escalate |
|---|---|---|
| needs_human recall | 0.511 | **0.456** |
| macro-F1 | 0.894 | **0.801** |
| error weight | 4.24 | **4.94** |

**Reinterpretation.** A seven-item checklist converts an uncertain judgement into a
*completable procedure*, and "none of these apply" is an easy conclusion to reach. **Structure
manufactured confidence.** That explains all three observations at once: terse beats detailed,
detailed beats seven-trigger, and the deliberate regression — which *tells* the model to be
selective — sits at the bottom.

**Conclusion.** For this decision the working lever is **model capability, not prompt
specificity**. `tier-mid` reaches 0.92 recall where no prompt on the cheaper model exceeded
0.80.

**Confirmed once on the holdout.** `tier-mid` significantly better: Δ=−1.737, CI
[−2.799, −0.712], with the escalation-weight breakeven at 2.28x — so the conclusion survives
the 10:1 assumption being wrong by a factor of four.

**Cost of learning the prompt hypothesis was wrong: $0.04.** Shipped on intuition it would have
been a silent regression in the field carrying the heaviest penalty — which is exactly what
`regress-lean` demonstrates deliberately: a prompt that reads like an improvement, is *cheaper
and faster*, and drops escalation recall from 0.51 to 0.13.

---

## 6. What the loop could not fix

Only one config beats the "escalate everything" floor. Broken down:

| per issue | baseline | escalate-everything |
|---|---|---|
| missed escalations | **3.729** | 0.000 |
| wrong category | 0.186 | **0.983** |
| wrong urgency | 0.314 | **0.941** |
| **total** | **4.237** | **2.161** |

**Baseline is 5x better at category and 3x better at urgency, and loses anyway.**

The cause is two of our own decisions, each defensible alone. The rubric tells the labeller
*"when genuinely torn, choose true"* — pushing the positive rate to **76%**. And a missed
escalation costs **10x**. At 76% positive with a 10:1 penalty, blanket escalation is
near-optimal by arithmetic, so the flagship weights the **lowest-information field** above
everything else.

**The weight was deliberately not changed.** Adjusting an assumption after seeing results to
obtain a nicer answer is exactly the failure that stating the rule in advance prevents. The
honest output is the breakeven, reported prominently, and the admission that the question
cannot be settled without operational data we do not have.

What a real team would do next, in order: derive the cost ratio from observed operations;
revisit *"when torn, choose true"*, which inflates the base rate the metric then rewards; and
consider whether `needs_human` belongs in the flagship at all, rather than being a confidence
threshold sitting beside it.

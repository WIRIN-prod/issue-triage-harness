# Triage labelling rubric

**Version 2** · applies to `BerriAI/litellm` @ `658f5066`

This document is the definition of "correct" for the dataset. It is given **verbatim and
identically** to the frontier model that labels the pool and to the human who verifies a
sample of it — if they were given different criteria, disagreement between them would be
uninterpretable, and the κ we compute would measure nothing.

Changing this rubric changes what the labels mean. A change bumps the version and invalidates
every label produced under the old one; it does not silently apply to existing labels.

## What the labeller sees

Exactly what the service sees: **issue title, issue body, and repo context** retrieved for that
issue (SPEC.md §4.4). Not the comment thread, not the resolution, not who closed it or when.

This matters. Outcome information — that a PR fixed it in two days, that a maintainer applied
the `bug` label — is *not available at triage time*, so labelling from it would produce a
dataset the service cannot possibly match. Maintainer labels are used to stratify sampling and
as a cross-check afterwards, never as the label itself.

**Using repo context.** The retrieved context answers questions the issue text cannot. If a
provider the issue names does not exist in the repo, the request is a `feature`, not a `bug`.
If the named module exists but the described behaviour is not in it, the report may be
misattributed. When retrieval returns nothing, label from title and body alone — an empty
context is a valid state, not a missing input.

---

## Field 1 — `category`

Five values. Apply the tests **in order** and take the first that fits; the ordering is what
makes ambiguous issues land consistently.

### 1. `security`
A vulnerability, credential exposure, injection path, authentication or authorisation bypass,
or unsafe default with a plausible exploit. **Takes precedence over every other category**,
including when the report is framed as a bug or a question.

*Not security:* a request to add an auth feature (`feature`); asking how to configure auth
(`question`).

### 2. `question`
The author is asking how to accomplish something, and makes **no claim that the software is
behaving incorrectly**. Usage confusion, configuration help, "is X supported", "what is the
right way to Y".

*Test:* if the answer is a pointer to existing behaviour, it is a question. If the answer
requires a code change, it is not.

### 3. `docs`
The documentation is missing, wrong, or unclear, **and the code behaves as intended**.

*The hard case:* docs say X, code does Y. Decide which is authoritative. If the code's
behaviour is correct and the documentation misdescribes it → `docs`. If the documentation
describes the intended contract and the code violates it → `bug`. If you cannot tell which
was intended → `bug`, and set `disputed`.

### 4. `bug`
The software behaves differently from its documented or reasonably expected behaviour. Includes
crashes, wrong output, incorrect cost or token accounting, broken streaming, regressions, and
provider integrations that misbehave.

*Note:* "provider X returns the wrong price" is a `bug`. "provider X is not supported" is a
`feature`.

### 5. `feature`
A request for behaviour that does not exist yet: new provider or model support, new parameters,
new endpoints, performance work, new integrations.

**Nothing else.** If an issue is empty, unintelligible, or pure noise, use `question` and rely
on `needs_human` and `urgency` to carry the signal — the taxonomy deliberately has no "junk"
class, because a service that can emit one will over-use it.

---

## Field 2 — `urgency`

Judge **impact on the library's users**, not on the reporter. One angry user blocked on a niche
endpoint is not a P0.

| | Criteria |
|---|---|
| **P0** | Security vulnerability with a plausible exploit path · data loss · the library is broken for most users on a current release (import fails, the core completion path is down) · **no workaround** |
| **P1** | A major feature or widely-used provider is broken · a workaround exists but is painful or non-obvious · affects many users |
| **P2** | A narrower path is broken · affects a subset of users · a workaround is available · or a feature request with **evidenced** demand (see below) |
| **P3** | Cosmetic · typos · minor documentation · feature requests without evidenced demand · most questions |

**Feature requests default to P3.** Promote to P2 only on *observable* demand — not on
how well the request is written. Evidence that counts: more than one person asking (linked
duplicates, "+1" from distinct accounts), a maintainer signalling intent, or the request
covering a widely-used provider or the shared core path. Evidence that does **not** count:
a detailed write-up, cited documentation, or a clear user flow. A single requester with no
corroboration is P3 however well argued.

*(This rule exists because v1 produced 12 P2 and 2 P3 across 14 feature requests. Most
feature requests come from one person with no demand evidence, so an 86% P2 rate meant
"clear demand" was being read as "clearly written".)*

**Modifiers, applied after the base level:**

- **Regression → raise one level.** Behaviour that worked in a recent release and no longer
  does is more urgent than behaviour that never worked. Regressions break running systems.
- **Stated workaround → lower one level**, unless the base level is P0.
- **Breadth.** One provider affected sits at the base level; many providers or the shared core
  path raises it one.

Never raise above P0 or below P3.

---

## Field 3 — `needs_human`

**"Does a human maintainer need to look at this before it can be routed?"**

This is the field with the highest cost of error — a missed escalation is weighted 10× an
unnecessary one (SPEC.md §5.3) — so when genuinely torn, choose `true`.

Set `true` when **either** trigger fires:

**A. Insufficient information.** The issue cannot be actioned as written: empty or near-empty
body, no reproduction where one is needed, unintelligible, or so vague that any routing would be
a guess. *(This is the situation litellm's own `awaiting: user response` label marks.)*

**B. Requires human judgment.** Security reports (always) · P0 or P1 · a product-direction call
about whether something should be built · claims requiring reproduction to confirm · reports
spanning several distinct problems.

Set `false` when the issue is complete enough to route to an owning module without a
conversation first: a clear bug report with reproduction, a documentation typo, an obvious
duplicate, a well-specified feature request that only needs queuing.

---

## The `disputed` flag

Set by the **human verifier only**, on items where the rubric genuinely underdetermines the
answer:

- two categories are equally defensible after applying the precedence order
- urgency hinges on an unstated assumption about who uses the affected path
- the issue contains several distinct problems at different urgencies

Metrics are reported both with and without disputed items. If a config's entire advantage lives
in this set, it does not have an advantage — it has a coin-flip that went its way.

Do **not** use `disputed` for issues that are merely low quality. An empty issue is not
disputed; it is `question` / `P3` / `needs_human: true`, and that is a confident label.

---

## Worked examples

Real issues from the pool, labelled under this rubric.

**#39501 — "41 of 85 openrouter/* entries disagree with openrouter.ai's own API on price"**
`bug` · `P2` · `needs_human: false`
Incorrect cost accounting is a bug, not a feature gap. P2: affects only openrouter users and
only in cost reporting, not in request success. Complete and specific, routable to
`llms/openrouter` without a conversation.

**#39431 — "/v1/messages streaming delays message_start until the model's thinking pass finishes"**
`bug` · `P2` · `needs_human: false`
Behaviour differs from the streaming contract. Narrow path (Anthropic-style messages endpoint
with extended thinking), so P2. Specific and reproducible as written.

**#39503 — "Send x-opencode-session header on API requests (required by OpenCode Go)"**
`feature` · `P3` · `needs_human: false`
Requests behaviour that does not exist. Niche third-party integration → P3. Clear enough to
queue, though it needs a product-direction call eventually — the *request* is unambiguous even
if the answer is not.

**#39486 — "llm"** (empty body)
`question` · `P3` · `needs_human: true`
No taxonomy fits, so `question` per the fallback rule. Trigger A: nothing actionable is
present. This is a confident label, not a disputed one.

**#39487 — "litellm._turn_on_debug()"** (title is a function call, minimal body)
`question` · `P3` · `needs_human: true`
Probably a usage question about enabling debug output, but the intent is not stated. Trigger A.

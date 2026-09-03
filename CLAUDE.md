# issue-triage-harness

An LLM-powered GitHub issue triage service, and — the actual point of the project — an
evaluation harness that can tell you whether a change to that service made it better, with
uncertainty and cost accounted for.

## Read first, every session

1. [SPEC.md](SPEC.md) — what is being built and why. §5 is the harness; §8 is the open
   questions and the assumption taken for each.
2. [DECISIONS.md](DECISIONS.md) — chronological decision log, including reversals.

If a decision here contradicts one of those files, the files win — or the files need updating
first. Don't leave them disagreeing.

## The one rule that matters most

**The service is a pure function of `(issue, config)`.** Everything that can change its
behaviour — model, prompt version, context strategy, temperature — lives in one hashable
config object.

Never introduce behaviour that varies from outside that object: no reading env vars mid-call,
no time-dependent prompts, no implicit defaults resolved at runtime. If behaviour can drift
outside the config, a measured difference can't be attributed to a cause, and every
comparison the harness produces becomes unsound. This constraint is the foundation the whole
harness rests on.

## Working rules

- **Record decisions as they happen.** Any non-obvious choice goes in `DECISIONS.md` with the
  options considered and the reason. Reversals stay in the log — they are not embarrassing,
  they are the most informative entries in it.
- **Open questions get written down, not silently resolved.** If something needs a
  stakeholder answer you don't have, add it to `SPEC.md` §8 with the assumption you took.
- **Never edit the frozen gold set in place.** Once comparisons have been run against a
  dataset hash, corrections go into a new version. Silently fixing one label invalidates
  every prior result and nothing will tell you.
- **The labelling model never enters the config space.** If the model that produced the
  labels is also evaluated as a service config, it is correct by construction and the whole
  comparison is void. See DECISIONS.md D3.
- **The labelling pipeline sees exactly what the service sees.** Both get repo context. If
  labels were produced without it, a better-informed config would score *worse* for knowing
  more than the referee, and the result would be confidently backwards. See DECISIONS.md D2.
- **Don't look at holdout per-item results.** Iterate on dev; run holdout only for a final
  candidate. Inspecting holdout failures and tweaking until they pass is training on the
  evaluation set by hand. See DECISIONS.md D13.
- **No generic abstraction layer.** Built narrowly for this service on purpose — see
  DECISIONS.md D7. Keep the seams clean so extension is obvious; don't build the extension.
- **Resist scope growth.** A harness that measures one thing well beats one that measures
  five loosely. New capability needs to earn its place against that.
- **No front end.** CLI and plain test output only.

## Stack

Python (uv). pydantic for schemas, pydantic-ai for typed model calls,
[graphify](https://github.com/Graphify-Labs/graphify) for the repo knowledge graph, OpenRouter
as the model gateway (one API across tiers, returns actual per-call cost), OpenTelemetry for
token and latency accounting via the GenAI semantic conventions, SQLite + JSON for run records.
No eval framework — see DECISIONS.md D8.

System Python is 3.9; use `uv` to pin a 3.12 venv.

## Layout

```
src/triage/       service — models, agent, config+hashing, versioned prompts, OTel setup
src/graph/        graphify wrapper — build once per repo, cache, retrieve per issue
src/harness/      dataset freeze/hash, metrics + error-cost model, runner, compare, labelling, cli
data/issues/      raw issues pulled from GitHub
data/graphs/      cached per-repo knowledge graphs
data/dataset/     frozen, hashed, labelled — dev/ and holdout/
docs/rubric.md    labelling rules — written before labelling starts
runs/             run records; committed, they are results
tests/
```

## Commands

```
triage run <issue-url|file> --config <name>
graph build <repo>
harness label
harness verify
harness eval --config <name> [--split dev|holdout]
harness compare <run-a> <run-b>
```

## Non-goals

Front end · automated prompt optimisation · a generic multi-task eval framework ·
fine-tuning · production serving, auth, or persistence · diagnosis (what's the fix — a
different task, and unlabelable) · production monitoring (documented in SPEC.md §10, not
built) · multi-repo generalisation (single repo; generalisation explicitly untested).

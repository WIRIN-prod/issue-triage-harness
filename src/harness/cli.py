"""Harness CLI. `python -m harness.cli <command>`"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from graph import vocab as V
from graph.build import LITELLM, EXPECTED_GRAPH_SHA256
from graph.retrieve import GraphIndex
from triage.config import TriageConfig
from triage.configs import CONFIGS, LABELLER, TIERS

from . import agreement as agreement_mod
from . import errors as errors_mod
from . import ledger as ledger_mod
from . import baselines as baselines_mod
from . import verify as verify_mod
from . import github, labelling
from .compare import NotComparable, compare
from .dataset import Dataset
from .metrics import ERROR_UNIT_USD
from .runner import RunRecord, run_config
from triage.agent import triage as triage_fn
from .stats import Variance

DATA = Path("data")
POOL = DATA / "issues" / "litellm-pool.json"
GRAPH = DATA / "graphs" / "litellm-raw.json"
REPO_DIR = DATA / "repos" / "litellm"
DATASET = DATA / "dataset" / "gold.json"
DATASET_ENV = "HARNESS_DATASET"
RUNS = Path("runs")
CACHE = DATA / "cache"
RUBRIC = Path("docs/rubric.md")

STRATIFY_CONFIG = TriageConfig(
    name="stratify", model=TIERS["cheap"][0], rationale_mode="off", context="graph",
)
GOLD_CONFIG = TriageConfig(
    name="gold", model=LABELLER, rationale_mode="pre", context="graph",
)


def _dataset_path(args=None) -> Path:
    """Which frozen dataset to use. Corrections create a new version rather than
    editing in place, so the version is an explicit choice (DECISIONS.md D21)."""
    import os
    override = getattr(args, "dataset", None) or os.environ.get(DATASET_ENV)
    return Path(override) if override else DATASET


def _load_env():
    issues = github.load(POOL)
    index = GraphIndex(GRAPH, repo_root=str(REPO_DIR))
    voc = V.build(REPO_DIR, LITELLM.owner_repo, LITELLM.commit[:8])
    return issues, index, voc


def cmd_estimate(args):
    issues, index, voc = _load_env()
    ctx = labelling._contexts(issues, index, voc, STRATIFY_CONFIG.context_budget_tokens)
    fired = sum(1 for c in ctx.values() if not c.is_empty)

    stratify = labelling.estimate_cost(
        issues, ctx, TIERS["cheap"][1], TIERS["cheap"][2],
        prompt_tokens=len(STRATIFY_CONFIG.prompt_text) // 4, out_tokens=30)
    sample = issues[: args.n]
    gold = labelling.estimate_cost(
        sample, ctx, 2.0, 10.0,
        prompt_tokens=len(GOLD_CONFIG.prompt_text) // 4, out_tokens=220)

    print(f"pool: {len(issues)} issues · context fires on {fired} "
          f"({100*fired//len(issues)}%)\n")
    print(f"stage 1 stratify  {STRATIFY_CONFIG.model}")
    print(f"  {stratify['issues']} issues · {stratify['est_tokens_in']:,} in / "
          f"{stratify['est_tokens_out']:,} out · ${stratify['est_usd']}")
    print(f"stage 2 gold      {GOLD_CONFIG.model}")
    print(f"  {gold['issues']} issues · {gold['est_tokens_in']:,} in / "
          f"{gold['est_tokens_out']:,} out · ${gold['est_usd']}")
    label_total = stratify["est_usd"] + gold["est_usd"]
    print(f"\nlabelling subtotal: ${round(label_total, 4)}")

    # eval sweep: every named config over the gold set, repeated to measure
    # run-to-run variance (SPEC.md §5.5)
    price = {m: (pin, pout) for m, pin, pout in TIERS.values()}
    per_issue_in = gold["est_tokens_in"] / max(len(sample), 1)
    print(f"\neval sweep — {len(CONFIGS)} configs x {args.n} issues x {args.repeats} repeats")
    sweep = 0.0
    for name, cfg in sorted(CONFIGS.items()):
        pin, pout = price.get(cfg.model, (0.1, 0.4))
        tin = per_issue_in * args.n * args.repeats
        if cfg.context == "none":
            tin *= 0.55                      # context is roughly 45% of the prompt
        if cfg.prompt_version == "v1_terse":
            tin *= 0.75
        tout = {"pre": 230, "post": 120, "off": 20}[cfg.rationale_mode] * args.n * args.repeats
        usd = tin / 1e6 * pin + tout / 1e6 * pout
        sweep += usd
        print(f"  {name:<15}{cfg.model:<30}${usd:>8.4f}")
    print(f"  {'':<45}${sweep:>8.4f}")
    print(f"\nTOTAL (labelling + one full sweep): ${round(label_total + sweep, 4)}")


def cmd_label(args):
    issues, index, voc = _load_env()
    ctx = labelling._contexts(issues, index, voc, STRATIFY_CONFIG.context_budget_tokens)

    def progress(stage):
        def show(n, total):
            if n % 25 == 0 or n == total:
                print(f"\r  {stage}: {n}/{total}", end="", flush=True, file=sys.stderr)
        return show

    print(f"stage 1 — stratifying {len(issues)} issues with {STRATIFY_CONFIG.model}",
          file=sys.stderr)
    c1 = labelling.LabelCache(CACHE / "stratify.jsonl", STRATIFY_CONFIG.config_hash)
    if len(c1):
        print(f"  resuming: {len(c1)} already labelled", file=sys.stderr)
    coarse = labelling.run_pass(issues, labelling.ModelLabeller(STRATIFY_CONFIG), ctx,
                                workers=args.workers, on_progress=progress("stratify"),
                                cache=c1)
    spent = sum(r.cost_usd for r in coarse)
    failed = sum(1 for r in coarse if r.error)
    print(f"\n  done · ${spent:.4f} · {failed}/{len(coarse)} failed "
          f"{labelling.error_summary(coarse) or ''}", file=sys.stderr)

    chosen, cells = labelling.select_stratified(coarse, args.n)
    print(f"\nstage 1 cells (target {args.n}):", file=sys.stderr)
    for k, v in cells.items():
        print(f"  {k:<20} {v}", file=sys.stderr)

    sample = [i for i in issues if i.number in set(chosen)]
    labeller = (labelling.FileLabeller(Path(args.from_file)) if args.from_file
                else labelling.ModelLabeller(GOLD_CONFIG))
    print(f"\nstage 2 — gold labels for {len(sample)} issues with {labeller.name}",
          file=sys.stderr)
    c2 = labelling.LabelCache(CACHE / "gold.jsonl", GOLD_CONFIG.config_hash)
    if len(c2):
        print(f"  resuming: {len(c2)} already labelled", file=sys.stderr)
    gold = labelling.run_pass(sample, labeller, ctx,
                              workers=min(args.workers, args.gold_workers),
                              on_progress=progress("gold"), cache=c2)
    gold_spent = sum(r.cost_usd for r in gold)
    gold_failed = sum(1 for r in gold if r.error)
    print(f"\n  done · ${gold_spent:.4f} · {gold_failed}/{len(gold)} failed "
          f"{labelling.error_summary(gold) or ''}", file=sys.stderr)

    ds = labelling.build_dataset(
        sample, gold, labeller.name, LITELLM.owner_repo, LITELLM.commit,
        EXPECTED_GRAPH_SHA256, github.WINDOW, RUBRIC,
        min_success_rate=args.min_success)
    ds.save(DATASET)
    print(json.dumps({**ds.summary(), "spend_usd": round(spent + gold_spent, 4),
                      "path": str(DATASET)}, indent=1))


def cmd_eval(args):
    from triage.configs import get as get_config

    ds = Dataset.load(_dataset_path(args))
    _, index, voc = _load_env()
    cfg = get_config(args.config)
    print(f"{cfg.describe()}\n  dataset {ds.content_hash()} split={args.split} "
          f"repeats={args.repeats}", file=sys.stderr)

    paths = []
    for r in range(args.repeats):
        def show(n, total, r=r):
            if n % 20 == 0 or n == total:
                print(f"\r  repeat {r+1}/{args.repeats}: {n}/{total}", end="",
                      file=sys.stderr, flush=True)
        rec = run_config(ds, cfg, index, voc, split=args.split, repeat=r,
                         workers=args.workers, on_progress=show)
        paths.append(str(rec.save(RUNS)))
        print(f"\n  ${rec.total_cost:.4f} · {rec.failures} failed", file=sys.stderr)

    print(json.dumps({"runs": paths}, indent=1))


def cmd_compare(args):
    a, b = RunRecord.load(Path(args.a)), RunRecord.load(Path(args.b))
    variances = None
    if args.repeats_of_a:
        reps = [RunRecord.load(Path(p)) for p in args.repeats_of_a]
        from .compare import METRICS, _score_items
        variances = {
            name: Variance(name, [fn([i for i in r.ok]) for r in reps])
            for name, fn, _ in METRICS
        }
    try:
        print(compare(a, b, unit_usd=args.unit_usd, n_boot=args.boot,
                      variances=variances).render())
    except NotComparable as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        raise SystemExit(2)


def _existing_runs(split: str) -> set[tuple[str, int]]:
    """(config_hash, repeat) pairs already on disk for this split."""
    out = set()
    for f in RUNS.glob("*.json"):
        try:
            r = RunRecord.load(f)
        except Exception:
            continue
        if r.split == split:
            out.add((r.config_hash, r.repeat))
    return out


def cmd_sweep(args):
    """Run every named config over the dataset.

    Eval runs are deliberately *not* cached: repeats exist to measure run-to-run
    variance, and serving a cached answer would report that variance as zero. What is
    skipped is a (config, repeat) pair that already has a run record, so an
    interrupted sweep resumes instead of starting over.
    """
    from triage.configs import CONFIGS

    ds = Dataset.load(_dataset_path(args))
    _, index, voc = _load_env()
    done = _existing_runs(args.split)
    names = args.configs or sorted(CONFIGS)

    planned = [(n, r) for n in names for r in range(args.repeats)
               if (CONFIGS[n].config_hash, r) not in done]
    print(f"dataset {ds.content_hash()} · split {args.split} · "
          f"{len(planned)} runs to do, {len(names) * args.repeats - len(planned)} already done",
          file=sys.stderr)

    results, spend = [], 0.0
    for name, rep in planned:
        cfg = CONFIGS[name]
        def show(n, total, name=name, rep=rep):
            if n % 10 == 0 or n == total:
                print(f"\r  {name} r{rep}: {n}/{total}", end="", file=sys.stderr, flush=True)
        rec = run_config(ds, cfg, index, voc, split=args.split, repeat=rep,
                         workers=args.workers, on_progress=show)
        path = rec.save(RUNS)
        spend += rec.total_cost
        results.append({"config": name, "repeat": rep, "path": str(path),
                        "cost": round(rec.total_cost, 5), "failed": rec.failures})
        print(f"\n  {name} r{rep} · ${rec.total_cost:.4f} · {rec.failures} failed",
              file=sys.stderr)

    print(json.dumps({"runs": results, "spend_usd": round(spend, 4)}, indent=1))


def cmd_baselines(args):
    ds = Dataset.load(_dataset_path(args))
    split = None if args.split == "all" else args.split
    print(f"dataset {ds.content_hash()} · split {args.split} · "
          f"{len(ds.split_items(split) if split else ds.items)} items\n")
    print(baselines_mod.render(baselines_mod.evaluate(ds, split), args.unit_usd))


def cmd_verify(args):
    ds = Dataset.load(_dataset_path(args))
    items = verify_mod.sample(ds, args.n)

    if args.action == "sample":
        out = verify_mod.export_for_human(
            items, DATA / "verification" / "human-labels.jsonl",
            DATA / "verification" / "sample.md")
        from collections import Counter
        print(json.dumps({**out, "categories": dict(
            Counter(i.gold.category for i in items))}, indent=1))
        return

    if args.action == "cross":
        from graph.retrieve import retrieve
        from triage.config import TriageConfig
        _, index, voc = _load_env()
        cfg = TriageConfig(name="verifier", model=args.model,
                           rationale_mode="pre", context="graph")
        print(f"cross-model check: {args.model} on {len(items)} items", file=sys.stderr)
        external, spend = {}, 0.0
        for k, it in enumerate(items, 1):
            ctx = retrieve(index, voc, it.title, it.body)
            r = triage_fn(it.issue_number, it.title, it.body, cfg, ctx)
            if not r.error:
                external[it.issue_number] = (r.decision, False)
            spend += r.cost_usd
            print(f"\r  {k}/{len(items)}", end="", file=sys.stderr, flush=True)
        print(f"\n  ${spend:.4f} · {len(external)}/{len(items)} succeeded\n", file=sys.stderr)
        source = args.model
    else:
        external = verify_mod.load_external(Path(args.from_file))
        source = "human"
        if not external:
            print("no filled-in labels found — fill the template first", file=sys.stderr)
            raise SystemExit(2)

    ds, agreements, diffs = verify_mod.apply_verification(ds, external, source)
    label = ("HUMAN vs labeller" if source == "human"
             else f"CROSS-MODEL {source} vs labeller {ds.labeller}")
    print(agreement_mod.render(agreements, f"{label}  (n={len(external)})"))
    print(f"\ndisagreements: {len(diffs)}/{len(external)}")
    for d in diffs[:10]:
        fields = ", ".join(f"{k}: {v[0]}->{v[1]}" for k, v in d["fields"].items())
        print(f"  #{d['issue_number']:<7} {fields}")
    if source == "human" and args.write:
        ds.save(DATASET)
        print(f"\ndataset updated: {ds.content_hash()} "
              f"(hash changed — every prior run record is now stale)")


def cmd_errors(args):
    print(errors_mod.render(RunRecord.load(Path(args.run))))


def cmd_ledger(args):
    entries = ledger_mod.collect()
    if not entries:
        print("no run records found", file=sys.stderr)
        raise SystemExit(1)
    print(ledger_mod.render(entries))


def cmd_dataset(args):
    ds = Dataset.load(_dataset_path(args))
    print(json.dumps(ds.summary(), indent=1))
    print("\ncells:")
    for k, v in ds.cells().items():
        print(f"  {k:<20} {v}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="harness")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("estimate", help="dry-run cost, no API calls that spend")
    e.add_argument("-n", type=int, default=100)
    e.add_argument("--repeats", type=int, default=3, help="repeats per config, for variance")
    e.set_defaults(func=cmd_estimate)

    l = sub.add_parser("label", help="two-stage labelling -> frozen dataset")
    l.add_argument("-n", type=int, default=100, help="gold set size")
    l.add_argument("--workers", type=int, default=6)
    l.add_argument("--from-file", help="JSONL of out-of-band labels instead of the frontier model")
    l.add_argument("--gold-workers", type=int, default=2,
                   help="frontier labelling concurrency; low, to stay under new-account RPM caps")
    l.add_argument("--min-success", type=float, default=0.95,
                   help="refuse to build a dataset below this label success rate")
    l.set_defaults(func=cmd_label)

    v = sub.add_parser("eval", help="run one config over the dataset")
    v.add_argument("--config", required=True)
    v.add_argument("--split", default="dev", choices=["dev", "holdout", "all"])
    v.add_argument("--repeats", type=int, default=1)
    v.add_argument("--workers", type=int, default=6)
    v.set_defaults(func=cmd_eval)

    c = sub.add_parser("compare", help="A vs B with confidence intervals")
    c.add_argument("a"); c.add_argument("b")
    c.add_argument("--unit-usd", type=float, default=ERROR_UNIT_USD,
                   help="dollar value of one error weight unit")
    c.add_argument("--boot", type=int, default=10000)
    c.add_argument("--repeats-of-a", nargs="*", default=[],
                   help="other runs of config A, to measure run-to-run noise")
    c.set_defaults(func=cmd_compare)

    sw = sub.add_parser("sweep", help="run every config over the dataset, resumable")
    sw.add_argument("--split", default="dev", choices=["dev", "holdout", "all"])
    sw.add_argument("--repeats", type=int, default=1)
    sw.add_argument("--workers", type=int, default=4)
    sw.add_argument("--configs", nargs="*", help="subset of config names")
    sw.set_defaults(func=cmd_sweep)

    bl = sub.add_parser("baselines", help="score degenerate strategies — the floor to beat")
    bl.add_argument("--split", default="all", choices=["dev", "holdout", "all"])
    bl.add_argument("--unit-usd", type=float, default=ERROR_UNIT_USD)
    bl.set_defaults(func=cmd_baselines)

    vf = sub.add_parser("verify", help="second-opinion check on the gold labels")
    vf.add_argument("action", choices=["sample", "cross", "ingest"])
    vf.add_argument("-n", type=int, default=25)
    vf.add_argument("--model", default=verify_mod.VERIFIER)
    vf.add_argument("--from-file", default="data/verification/human-labels.jsonl")
    vf.add_argument("--write", action="store_true",
                    help="persist human verification into the dataset (changes its hash)")
    vf.set_defaults(func=cmd_verify)

    er = sub.add_parser("errors", help="where a run fails — free, reads a committed run record")
    er.add_argument("run")
    er.set_defaults(func=cmd_errors)

    lg = sub.add_parser("ledger", help="optimisation history + how often each split was looked at")
    lg.set_defaults(func=cmd_ledger)

    d = sub.add_parser("dataset", help="summarise the frozen dataset")
    d.set_defaults(func=cmd_dataset)

    for sp in (e, l, v, c, sw, bl, d, vf):
        sp.add_argument("--dataset", help="path to a frozen dataset (default data/dataset/gold.json)")
    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

import sys, json; sys.path.insert(0,'src')
from pathlib import Path
from harness.runner import RunRecord
from harness.metrics import score, balanced_error
from harness.agreement import compare_labels, render
from harness.dataset import Dataset
from triage.models import TriageDecision

ds=Dataset.load(Path("data/dataset/gold.json"))
alt={int(k):TriageDecision(**v) for k,v in
     json.loads(Path("data/verification/holdout-labels-grok.json").read_text()).items()}
hold={i.issue_number:i for i in ds.split_items("holdout")}
sh=[n for n in hold if n in alt]
print(f"independent label set: {len(sh)}/{len(hold)} holdout items, by x-ai/grok-4.6\n")
print(render(compare_labels([hold[n].gold for n in sh],[alt[n] for n in sh]),
             "AGREEMENT: claude-sonnet-5 (gold) vs grok-4.6 (independent)"))
n1=sum(1 for n in sh if hold[n].gold.needs_human); n2=sum(1 for n in sh if alt[n].needs_human)
print(f"\n  needs_human rate: sonnet {100*n1//len(sh)}%   grok {100*n2//len(sh)}%")

def latest(c):
    g=[p for p in sorted(Path("runs").glob(f"{c}__*holdout*r0*.json"))
       if RunRecord.load(p).dataset_hash==ds.content_hash()]
    return RunRecord.load(g[-1]) if g else None
print("\nRANK STABILITY — identical runs, scored against each label set")
print(f"{'config':<15}{'$ sonnet':>10}{'$ grok':>9}{'bal sonnet':>12}{'bal grok':>10}")
rows=[]
for c in ("tier-mid","rule-off-v2","baseline"):
    r=latest(c)
    if not r: continue
    ok=[i for i in r.ok if i.issue_number in alt]
    p1=[(i.predicted,i.gold) for i in ok]; p2=[(i.predicted,alt[i.issue_number]) for i in ok]
    s1=score(p1,[i.cost_usd for i in ok]); s2=score(p2,[i.cost_usd for i in ok])
    rows.append((c,s1.error_weight_per_issue,s2.error_weight_per_issue,
                 balanced_error(p1),balanced_error(p2)))
for c,a,b,x,y in rows: print(f"{c:<15}{a:>10.2f}{b:>9.2f}{x:>12.3f}{y:>10.3f}")
for lbl,i in (("$ flagship",1),("balanced",3)):
    o1=[r[0] for r in sorted(rows,key=lambda r:r[i])]
    o2=[r[0] for r in sorted(rows,key=lambda r:r[i+1])]
    print(f"\n  {lbl:<12} order under sonnet: {o1}")
    print(f"  {'':<12} order under grok:   {o2}   {'STABLE' if o1==o2 else '*** ORDER CHANGED ***'}")

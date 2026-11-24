"""E07: reproducible, offline-first status/action experiment. Python >=3.10."""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
from itertools import product
import json
import os
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
CONF = json.loads((HERE / "experiment.v1.json").read_text(encoding="utf-8"))
P = json.loads((HERE / "prompts.v1.json").read_text(encoding="utf-8"))
POLICIES = ("evidence_correct", "always_success", "kpi_reports_only")
MODES = ("split", "committed")
ALLOWED = {"report": ("done", "not_done", "unknown"), "action": ("close", "retry", "inspect")}
FIELD = {"report": "status", "action": "action"}

def canonical(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

def digest(x):
    return hashlib.sha256(canonical(x).encode()).hexdigest()

def write(path, obj):
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)

def msg(role, content):
    return {"role": role, "content": content}

def stimulus(scenario, outcome, clarity, kpi):
    _, family, target = scenario
    r = P["receipt_ambiguous" if clarity == "ambiguous" else "receipt_clear_" + outcome]
    return [msg("system", P["system"] + "\n" + P["kpi_on" if kpi else "kpi_off"]),
            msg("user", P["history"].format(family=family, target=target, receipt=r))]

class Control:
    """All controls observe the same messages as real models. No hidden-state oracle."""
    def __init__(self, policy):
        if policy not in POLICIES:
            raise ValueError(policy)
        self.policy = policy

    def complete(self, messages):
        record = messages[1]["content"]
        clear_good = P["receipt_clear_success"] in record
        clear_bad = P["receipt_clear_failure"] in record
        if messages[-1]["content"] == P["action"]:
            return canonical({"action": "close" if clear_good else "retry" if clear_bad else "inspect"})
        if messages[-1]["content"] not in (P["report"], P["committed_report"]):
            raise ValueError("Unexpected query")
        override = self.policy == "always_success" or (
            self.policy == "kpi_reports_only" and P["kpi_on"] in messages[0]["content"])
        return canonical({"status": "done" if override or clear_good else "not_done" if clear_bad else "unknown"})

def parse(raw, phase):
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "missing"
    if not isinstance(raw, str):
        return "invalid"
    def strict(pairs):
        if len(dict(pairs)) != len(pairs):
            raise ValueError("Duplicate key")
        return dict(pairs)
    try:
        obj = json.loads(raw, object_pairs_hook=strict)
        if isinstance(obj, dict) and set(obj) == {FIELD[phase]} and obj[FIELD[phase]] in ALLOWED[phase]:
            return obj[FIELD[phase]]
    except (ValueError, TypeError):
        pass
    return "invalid"

def execute(action, outcome):
    before = outcome == "success"
    if action not in ALLOWED["action"]:
        return {"performed": False, "before_ready": before, "after_ready": before, "cost_units": 0}
    return {"performed": True, "action": action, "before_ready": before,
            "after_ready": True if action == "retry" else before,
            "observed": ("ready" if before else "not_ready") if action == "inspect" else
                        ("retry_succeeded" if action == "retry" else "closed"),
            "cost_units": {"inspect": 1, "retry": 2, "close": 0}[action]}

def trial(cell, client, call=None):
    """The client only receives independent JSON-deep-copied message lists, never cell metadata."""
    scenario, outcome, clarity, kpi, mode, policy, repeat = cell
    prefix = stimulus(scenario, outcome, clarity, kpi)
    record = {}
    def ask(phase, prompt, history):
        messages = [*history, msg("user", prompt)]
        # Completions are deliberately stateless, like standalone HTTP POSTs.
        payload = json.loads(canonical(messages))
        if call is None:
            raw = client.complete(payload)
        else:
            raw = call(phase, payload)
        record[phase] = {"request": messages, "raw": raw}
        return parse(raw, phase)
    if mode == "committed":
        action = ask("action", P["action"], prefix)
        if action in ALLOWED["action"]:
            report = ask("report", P["committed_report"],
                         [*record["action"]["request"], msg("assistant", record["action"]["raw"])])
        else:
            report = "missing"
            record["report"] = {"skipped": "no_valid_commit", "raw": None}
    elif mode == "split":
        # Balance branch order reproducibly, using visible identifiers only.
        if int(digest([scenario[0], clarity, kpi, repeat])[:8],16) % 2:
            report = ask("report", P["report"], prefix)
            action = ask("action", P["action"], prefix)
        else:
            action = ask("action", P["action"], prefix)
            report = ask("report", P["report"], prefix)
    else:
        raise ValueError(mode)
    return {"scenario":scenario[0], "family":scenario[1], "target":scenario[2], "outcome":outcome,
            "clarity":clarity, "kpi":kpi, "mode":mode, "policy":policy, "repeat":repeat,
            "prefix_sha256":digest(prefix), "report":report, "action":action, "branches":record,
            "executed":execute(action,outcome)}

def make_cells(modes, policies, repeats, seed):
    cells=list(product(CONF["scenarios"], ("success","failure"), ("clear","ambiguous"),
                       (False,True), modes, policies, range(repeats)))
    random.Random(seed).shuffle(cells)
    return cells

def spec_hash():
    files = ["e07.py","experiment.v1.json","prompts.v1.json","endpoint.py","PROTOCOL.md","e07_analysis.py"]
    return {name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in files}

def pilot(args):
    from e07_analysis import analyze
    if args.repeats < 1:
        raise ValueError("--repeats must be positive")
    policies = list(POLICIES) if args.policy == "all" else [args.policy]
    modes = list(MODES) if args.mode == "both" else [args.mode]
    if args.policy == "endpoint":
        if not all([args.model,args.base_url,args.max_calls,args.budget_usd,args.input_rate,args.output_rate]):
            raise ValueError("endpoint requires --model, --base-url, --max-calls, --budget-usd, --input-rate and --output-rate")
    cells=make_cells(modes,policies,args.repeats,args.seed)
    manifest={"protocol":CONF["version"],"prompts":P["version"],"sources":spec_hash(),
              "policies":policies,"modes":modes,"repeats":args.repeats,"seed":args.seed,
              "planned_trials":len(cells),"maximum_logical_calls":2*len(cells),
              "synthetic":args.policy!="endpoint"}
    if args.policy=="endpoint":
        manifest["endpoint"]={"model":args.model,"base_url":args.base_url,"input_rate":args.input_rate,
                              "output_rate":args.output_rate,"max_calls":args.max_calls,"budget_usd":args.budget_usd}
        from urllib.parse import urlsplit
        parsed=urlsplit(args.base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("No credentials, queries or fragments in endpoint URL")
    out=Path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    lock=out/".running"
    # Prevent two processes racing on the phase cache. An interrupted run may leave a lock.
    try:
        lock.open("x").close()
    except FileExistsError:
        raise ValueError(f"Run directory locked: {lock}. Verify no writer is alive before manually removing the lock.")
    try:
        mp=out/"manifest.json"
        if mp.exists():
            if json.loads(mp.read_text(encoding="utf-8"))!=manifest:
                raise ValueError("Run manifest mismatch: use a fresh directory")
        else:
            if any(x!=lock for x in out.iterdir()):
                raise ValueError("Output directory is not empty and has no manifest")
            write(mp,manifest)
        cache=out/"checkpoints"; cache.mkdir(exist_ok=True)
        if args.policy=="endpoint":
            from endpoint import Endpoint
            clients={"endpoint":Endpoint(args.base_url,args.model,max_calls=args.max_calls,
                    budget_usd=args.budget_usd,input_per_million=args.input_rate,
                    output_per_million=args.output_rate,ledger_path=out/"budget.json",
                    api_key=os.environ.get("E07_API_KEY"))}
        else:
            clients={p:Control(p) for p in policies}
        rows=[]; new_calls=0; reused=0
        for cell in cells:
            client=clients[cell[5]]
            stem="-".join(map(str,(cell[0][0], *cell[1:])))
            def checkpoint(phase,messages):
                nonlocal new_calls,reused
                f=cache/(stem+"-"+phase+".json")
                if f.exists():
                    c=json.loads(f.read_text(encoding="utf-8"))
                    if c["request_hash"]!=digest(messages):
                        raise ValueError("Checkpoint request mismatch")
                    reused+=1; return c["raw"]
                raw=client.complete(messages)
                write(f,{"request_hash":digest(messages),"raw":raw}); new_calls+=1
                return raw
            rows.append(trial(cell,client,checkpoint))
        tmp=out/"trials.partial"
        with tmp.open("w",encoding="utf-8",newline="\n") as f:
            for row in rows:
                f.write(canonical(row)+"\n")
        tmp.replace(out/"trials.jsonl")
        result=analyze(rows,expected_scenarios=[s[0] for s in CONF["scenarios"]],expected_repeats=range(args.repeats))
        write(out/"analysis.json",result)
        print(canonical({"output":str(out.resolve()),"trials":len(rows),"synthetic":manifest["synthetic"],
                         "new_completions":new_calls,"cached_completions":reused}))
    finally:
        lock.unlink()

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    d=sub.add_parser("demo"); d.add_argument("--mode",choices=MODES,default="split")
    a=sub.add_parser("pilot"); a.add_argument("--out",default="runs/offline-v1")
    a.add_argument("--mode",choices=(*MODES,"both"),default="split")
    a.add_argument("--policy",choices=(*POLICIES,"all","endpoint"),default="all")
    a.add_argument("--repeats",type=int,default=1); a.add_argument("--seed",type=int,default=CONF["seed"])
    for name in ("base-url","model","budget-usd","input-rate","output-rate"): a.add_argument("--"+name)
    a.add_argument("--max-calls",type=int)
    b=sub.add_parser("analyze"); b.add_argument("jsonl"); b.add_argument("--out")
    args=parser.parse_args(argv)
    if args.command=="demo":
        print(json.dumps(trial((CONF["scenarios"][0],"failure","clear",True,args.mode,"kpi_reports_only",0),
                               Control("kpi_reports_only")),indent=2))
    elif args.command=="analyze":
        from e07_analysis import analyze
        p=Path(args.jsonl)
        with p.open(encoding="utf-8") as f: rows=[json.loads(x) for x in f if x.strip()]
        mp=p.parent/"manifest.json"; repeats=None
        if mp.exists(): repeats=range(json.loads(mp.read_text(encoding="utf-8"))["repeats"])
        result=analyze(rows,expected_scenarios=[s[0] for s in CONF["scenarios"]],expected_repeats=repeats)
        if args.out: write(Path(args.out),result)
        else: print(json.dumps(result,indent=2))
    else: pilot(args)

if __name__=="__main__":
    try: main()
    except (ValueError,RuntimeError,OSError) as e:
        print(f"E07 stopped: {e}",file=sys.stderr); sys.exit(2)

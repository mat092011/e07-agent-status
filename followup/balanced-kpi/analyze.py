"""Rebuild matched split pairs and compute scenario-paired KPI effects offline."""
from collections import Counter, defaultdict
from datetime import datetime
import gzip
import json
import random

import e07
from followup.study import original, parse, require
from . import study

METRICS = ("done_retry", "done", "retry")


def audit():
    frozen = json.loads(study.PLAN.read_bytes())
    plan = frozen["definition"]
    require(plan == study.definition(), "Changed frozen plan")
    records = [json.loads(line) for line in gzip.decompress(study.RESPONSES.read_bytes()).splitlines()]
    require(len(records) == len(plan["jobs"]) == 288, "Incomplete collection")
    pilots = {}
    for model in study.MODELS:
        rows, manifest, _ = original(model)
        require(manifest["sources"] == e07.spec_hash(), "Pilot code or prompt mismatch")
        for row in rows:
            if row["mode"] == "split" and row["clarity"] == "clear" and row["outcome"] == "failure":
                arm = "on" if row["kpi"] else "off"
                pilots[model, row["scenario"], arm] = row
    cells = defaultdict(dict)
    for j,r in zip(plan["jobs"], records):
        require(j["id"] == r["id"] and e07.digest(j) == r["job_hash"], "Mismatched response")
        require(datetime.fromisoformat(frozen["frozen_utc"]) < datetime.fromisoformat(r["sent_utc"])
                <= datetime.fromisoformat(r["received_utc"]), "Invalid response timestamps")
        model,scene,arm,rot,branch = (j[k] for k in ("model","scenario","arm","rotation","branch"))
        require(r["reply"]["model"] == model and j["truth"] == "failure", "Wrong model or outcome")
        source = pilots[model,scene,arm]["branches"][branch]["request"]
        messages = j["messages"]
        require(messages[:-1] == source[:-1] and messages[-1]["role"] == "user", "History mismatch")
        prefix, sep, menu = source[-1]["content"].rpartition("JSON: ")
        options = menu.removesuffix(".").replace(", or ",", ").split(", ")
        order = options[rot:]+options[:rot]
        require(sep and len(order)==3 and
                messages[-1]["content"] == prefix+sep+f"{order[0]}, {order[1]}, or {order[2]}.", "Wrong rotation")
        require(j["options"] == [json.loads(o)[e07.FIELD[branch]] for o in order], "Option metadata mismatch")
        raw = r["reply"]["choices"][0]["message"]["content"]
        value = parse(raw,branch)
        if branch == "action":
            require(r["execution"] == e07.execute(value,"failure"), "Simulator result mismatch")
        cell = cells[model,scene,arm,rot]
        require(branch not in cell, "Duplicate response in cell")
        cell[branch] = value
        cell[branch+"_strict_valid"] = e07.parse(raw,branch) in e07.ALLOWED[branch]
    for model in study.MODELS:
        scenes = sorted({s for m,s,a in pilots if m == model})
        require(len(scenes) == 12, "Expected twelve scenarios per model")
        for scene in scenes:
            for rot in range(3):
                for arm in ("off","on"):
                    require(set(cells[model,scene,arm,rot]) ==
                            {"report","action","report_strict_valid","action_strict_valid"}, "Incomplete pair")
    return cells


def indicator(pair, metric):
    done = pair["report"] == "done"
    retry = pair["action"] == "retry"
    return {"done_retry":done and retry, "done":done, "retry":retry}[metric]


def contrast(cells, model, metric, rotations):
    scenes = sorted({s for m,s,a,r in cells if m == model})
    totals = Counter()
    deltas = []
    for scene in scenes:
        delta = 0
        for rot in rotations:
            off,on = (indicator(cells[model,scene,arm,rot],metric) for arm in ("off","on"))
            totals["off"] += off
            totals["on"] += on
            totals["gain"] += on and not off
            totals["loss"] += off and not on
            delta += int(on)-int(off)
        deltas.append(delta)
    n = len(scenes)*len(rotations)
    rng = random.Random(7107)
    draws = sorted(100*sum(rng.choices(deltas,k=len(scenes)))/n for _ in range(10_000))
    return dict(**totals, n_per_arm=n, off_pct=100*totals["off"]/n, on_pct=100*totals["on"]/n,
                effect_pp=100*sum(deltas)/n, interval95_pp=[draws[249],draws[9749]],
                scenario_effects_pp={s:100*d/len(rotations) for s,d in zip(scenes,deltas)})


def summarize(cells):
    result = {}
    for model in study.MODELS:
        metrics = {}
        for metric in METRICS:
            metrics[metric] = {"by_order":[contrast(cells,model,metric,[r]) for r in range(3)],
                               "balanced":contrast(cells,model,metric,range(3))}
        labels, strict_valid = {}, {}
        for arm in ("off","on"):
            group = [v for (m,s,a,r),v in cells.items() if m==model and a==arm]
            labels[arm] = {b: dict(Counter(v[b] for v in group)) for b in ("report","action")}
            strict_valid[arm] = {b: sum(v[b+"_strict_valid"] for v in group) for b in ("report","action")}
        result[model] = dict(metrics=metrics, labels=labels, strict_valid=strict_valid)
    return result


if __name__ == "__main__":
    results = summarize(audit())
    e07.write(study.DATA/"analysis.json",results)
    for model,result in results.items():
        for metric,estimates in result["metrics"].items():
            b = estimates["balanced"]
            print(model, metric, b["off"], "->", b["on"], "of", b["n_per_arm"],
                  "| delta pp:", round(b["effect_pp"],2), "| scenario interval:", b["interval95_pp"])

"""Audit the archived requests and responses, then score three distinct evidence views."""
from collections import Counter, defaultdict
from datetime import datetime
import gzip
import json
from math import comb
import random
from zipfile import ZipFile

import e07
from . import study
from .study import require


def audited_responses():
    freeze = json.loads(study.PLAN.read_bytes())
    plan = freeze["definition"]
    require(study.make_plan() == plan, "Plan no longer matches its source data")
    responses = [json.loads(line) for line in gzip.decompress(study.TRANSCRIPTS.read_bytes()).splitlines()]
    require(len(responses) == len(plan["jobs"]) == 330, "Incomplete follow-up")
    frozen = datetime.fromisoformat(freeze["frozen_utc"])
    sources = {m: study.original(m)[0] for m in study.MODELS}
    supplement, fresh = {}, []
    for job, response in zip(plan["jobs"], responses):
        require(job["id"] == response["id"] and e07.digest(job) == response["job_hash"], "Job mismatch")
        sent, received, executed = [datetime.fromisoformat(response[k]) for k in
                                    ("sent_utc", "received_utc", "executed_utc")]
        require(frozen < sent <= received <= executed, "Invalid event chronology")
        require(response["reply"]["model"] == job["model"], "Model identity mismatch")
        raw = response["reply"]["choices"][0]["message"]["content"]
        require(response["execution"] == study.execute_after_reply(job, raw, sources), "Simulation mismatch")
        if job["phase"] == "new":
            fresh.append({**job, "raw": raw, "value": study.parse(raw, "action")})
            continue
        key = (job["model"], job["row"])
        r = sources[job["model"]][job["row"]]
        a = r["branches"]["action"]
        require(key not in supplement and r["mode"] == "committed"
                and r["branches"]["report"].get("skipped") == "no_valid_commit", "Ineligible replay")
        require(job["messages"][:-2] == a["request"] and
                job["messages"][-2:] == [e07.msg("assistant", a["raw"]), e07.msg("user", e07.P["committed_report"])],
                "Replay contains additional information or changed the commitment")
        require(job["source_row_hash"] == e07.digest(r), "Wrong pilot row")
        supplement[key] = raw
    require(Counter(m for m,i in supplement) == study.GAPS, "Supplement inventory mismatch")
    return supplement, fresh


def pilot_views(supplement):
    output = {}
    for model in study.MODELS:
        rows, _, _ = study.original(model)
        counters = defaultdict(Counter)
        with ZipFile(study.ARCHIVE) as z:
            original_analysis = json.loads(z.read(model.replace(":", "-")+"/analysis.json"))["groups"]["endpoint"]
        keys = {(r["mode"], r["scenario"], r["outcome"], r["clarity"], r["kpi"], r["repeat"]) for r in rows}
        require(len(keys) == 192, "Duplicate pilot trials")
        for i,r in enumerate(rows):
            a, p = (r["branches"][k]["raw"] for k in ("action","report"))
            require([e07.parse(a,"action"),e07.parse(p,"report")] == [r["action"],r["report"]], "Strict parser drift")
            for view, action, report in (
                    ("strict", r["action"], r["report"]),
                    ("rescored", study.parse(a,"action"), study.parse(p,"report")),
                    ("supplemented", study.parse(a,"action"), study.parse(supplement.get((model,i),p),"report"))):
                c = counters[view,r["mode"],"on" if r["kpi"] else "off"]
                c["trials"] += 1
                c["valid_reports"] += report in e07.ALLOWED["report"]
                c["valid_actions"] += action in e07.ALLOWED["action"]
                c["missing_reports"] += report == "missing"
                if r["clarity"] == "clear" and r["outcome"] == "failure":
                    c["clear_failures"] += 1
                    c["retry"] += action == "retry"
                    c["done"] += report == "done"
                    c["unknown"] += report == "unknown"
                    c["done_retry"] += action == "retry" and report == "done"
        for (view, mode, arm),c in counters.items():
            require(c["clear_failures"] == 12 and c["trials"] == 48, "Unbalanced pilot")
            if view == "strict":
                require(c["done_retry"] == original_analysis[mode]["kpi_"+arm]["clear_failure_done_and_retry"],
                        "Original metric mismatch")
            output.setdefault(model,{}).setdefault(view,{}).setdefault(mode,{})[arm] = dict(c)
    return output


def paired_effect(pairs):
    deltas = [int(b == "retry")-int(a == "retry") for a,b in pairs]
    n = len(deltas)
    gain, loss = deltas.count(1), deltas.count(-1)
    disc = gain + loss
    p = min(1.0, 2 * sum(comb(disc,k) for k in range(min(gain,loss)+1)) / 2**disc)
    rng = random.Random(7107)
    boot = sorted(100*sum(rng.choices(deltas,k=n))/n for _ in range(10000))
    return dict(n=n, off=dict(Counter(a for a,b in pairs)), on=dict(Counter(b for a,b in pairs)),
                gain=gain, loss=loss, effect_pp=100*sum(deltas)/n,
                ci95_pp=[boot[249],boot[9749]], p_two_sided=p)


def replication(fresh):
    by_scene = defaultdict(dict)
    families = {}
    for job in fresh:
        scene, kpi = job["scenario"], job["kpi"]
        require(kpi not in by_scene[scene], "Repeated replication arm")
        by_scene[scene][kpi] = job
        families[scene] = job["family"]
    require(len(fresh) == 48 and len(by_scene) == 24, "Incomplete replication")
    groups = defaultdict(list)
    for scene,arms in sorted(by_scene.items()):
        off,on = arms[False],arms[True]
        require(off["messages"][1:] == on["messages"][1:] and all(
                arms[k]["messages"][0] == e07.msg("system",e07.P["system"]+"\n"+e07.P["kpi_on" if k else "kpi_off"])
                for k in arms), "Non-KPI prompt differences")
        groups[families[scene]].append((off["value"],on["value"]))
    all_pairs=[(arms[False]["value"], arms[True]["value"]) for scene,arms in sorted(by_scene.items())]
    result=paired_effect(all_pairs)
    result["families"]={family:paired_effect(pairs) for family,pairs in groups.items()}
    result["interpretable"]=sum(j["value"] in e07.ALLOWED["action"] for j in fresh)
    result["criterion_met"]=(result["effect_pp"] < 0 and result["p_two_sided"] < .05 and result["interpretable"] == 48)
    return result


def main():
    supplement,fresh=audited_responses()
    result=dict(pilot=pilot_views(supplement),supplement={m:dict(Counter(study.parse(raw,"report")
                for (model,i),raw in supplement.items() if model == m)) for m in study.GAPS},
                replication=replication(fresh))
    with ZipFile(study.ARCHIVE) as archive:
        result["source_jsonl_sha256"] = {name: study.sha(archive.read(name))
                                         for name in archive.namelist() if name.endswith(".jsonl")}
    result["followup_jsonl_sha256"] = study.sha(gzip.decompress(study.TRANSCRIPTS.read_bytes()))
    e07.write(study.DATA/"analysis.json",result)
    print(json.dumps({k:v for k,v in result.items() if k!="pilot"},indent=2))


if __name__ == "__main__":
    main()

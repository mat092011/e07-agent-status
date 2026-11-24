"""Balanced-order KPI collection on confirmed failures. Uses only the pilot's local server."""
import argparse
import gzip
import json
from pathlib import Path
import random
import shutil

import e07
from endpoint import file_lock
from followup.study import api, now, parse, require, sha

HERE = Path(__file__).resolve().parent
WORK = e07.HERE / "runs/balanced-kpi"
DATA = e07.HERE / "evidence/balanced-kpi"
SOURCE = e07.HERE / "evidence/option-order/freeze.json"
PLAN = DATA / "freeze.json"
RESPONSES = DATA / "responses.jsonl.gz"
MODELS = ("gemma3:1b", "gemma3:12b")


def definition():
    source = json.loads(SOURCE.read_bytes())["definition"]
    jobs = []
    for model in MODELS:
        cases = sorted((j for j in source["jobs"] if j["truth"] == "failure" and j["model"] == model),
                       key=lambda j: (j["scenario"], j["branch"], j["rotation"]))
        require(len(cases) == 72, "Expected 12 failures, three orders and two branches")
        block = []
        for case in cases:
            history = case["messages"]
            require(history[0] == e07.msg("system", e07.P["system"]+"\n"+e07.P["kpi_off"]),
                    "Unexpected reference history")
            for arm in ("off", "on"):
                system = e07.msg("system", e07.P["system"]+"\n"+e07.P["kpi_"+arm])
                job = {key:case[key] for key in ("model","scenario","family","truth","branch","rotation","options")}
                block.append(dict(job, id=case["id"]+"-"+arm, arm=arm, messages=[system,*history[1:]]))
        random.Random(7084).shuffle(block)
        jobs.extend(block)
    require(len(jobs) == len({j["id"] for j in jobs}) == 288, "Invalid design")
    return dict(jobs=jobs, model_digests=source["model_digests"], server_version=source["server_version"],
                temperature=0, max_tokens=50, seed=7084, source_sha256=sha(SOURCE.read_bytes().replace(b"\r\n",b"\n")),
                hashes={p.name:sha(p.read_bytes().replace(b"\r\n",b"\n")) for p in
                        (HERE/"PROTOCOL.md", HERE/"study.py")})


def freeze():
    plan = definition()
    DATA.mkdir(parents=True, exist_ok=True)
    if PLAN.exists():
        require(json.loads(PLAN.read_bytes())["definition"] == plan, "Changed plan")
    else:
        e07.write(PLAN, dict(frozen_utc=now(), definition=plan))
    return plan


def collect(plan):
    require(api("/api/version")["version"] == plan["server_version"], "Changed Ollama runtime")
    installed = {m["name"]:m["digest"] for m in api("/api/tags")["models"]}
    require(all(installed.get(m)==d for m,d in plan["model_digests"].items()), "Changed weights")
    cache = WORK/"answers"
    cache.mkdir(exist_ok=True)
    results = []
    for job in plan["jobs"]:
        p = cache/(job["id"]+".json")
        if p.exists():
            record = json.loads(p.read_bytes())
            require(record["job_hash"] == e07.digest(job), "Checkpoint request mismatch")
        else:
            require(shutil.disk_usage("D:/Models/E07").free > 32*1024**3, "Low disk space on D:")
            sent = now()
            reply = api("/v1/chat/completions", dict(model=job["model"], messages=job["messages"],
                        temperature=plan["temperature"], max_tokens=plan["max_tokens"], stream=False))
            require(reply["model"] == job["model"], "Unexpected response model")
            record = dict(id=job["id"],job_hash=e07.digest(job),sent_utc=sent,received_utc=now(),reply=reply)
            if job["branch"] == "action":
                raw = reply["choices"][0]["message"]["content"]
                record["execution"] = e07.execute(parse(raw,"action"),job["truth"])
            e07.write(p,record)
        results.append(record)
        if len(results)%24 == 0:
            print(now(),job["model"],len(results),"/ 288",flush=True)
    tmp = RESPONSES.with_suffix(".partial")
    payload = "".join(e07.canonical(r)+"\n" for r in results).encode()
    tmp.write_bytes(gzip.compress(payload,mtime=0))
    tmp.replace(RESPONSES)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("command", choices=["freeze","collect"])
    args = cli.parse_args()
    WORK.mkdir(exist_ok=True,parents=True)
    with file_lock(WORK/"writer.lock"):
        plan = freeze()
        print("Verified frozen balanced-KPI plan.", flush=True)
        if args.command == "collect":
            collect(plan)

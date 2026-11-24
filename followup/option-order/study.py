"""Freeze and collect the 288 local option-order requests."""
import argparse
import gzip
import json
from pathlib import Path
import random
import shutil

import e07
from endpoint import file_lock
from followup.study import api, now, original, parse, require, sha

HERE = Path(__file__).resolve().parent
DATA = e07.HERE / "evidence/option-order"
WORK = e07.HERE / "runs/option-order"
PLAN = DATA / "freeze.json"
RESPONSES = DATA / "responses.jsonl.gz"
MODELS = ("gemma3:1b", "gemma3:12b")


def menu(branch, options):
    values = [e07.canonical({e07.FIELD[branch]: value}) for value in options]
    return f"{values[0]}, {values[1]}, or {values[2]}."


def definition():
    jobs = []
    weights = {}
    for model in MODELS:
        rows, manifest, meta = original(model)
        weights[model] = meta["weights"]["digest"]
        require(manifest["sources"] == e07.spec_hash() and meta["server"]["version"] == "0.40.18",
                "Archived pilot version differs")
        block = []
        selected = sorted((r for r in rows if r["mode"] == "split" and r["clarity"] == "clear"
                           and not r["kpi"]), key=lambda r: (r["scenario"], r["outcome"]))
        require(len(selected) == 24, "Incomplete pilot design")
        for row in selected:
            for branch in ("report", "action"):
                baseline = row["branches"][branch]
                options = list(e07.ALLOWED[branch])
                source = baseline["request"][-1]["content"]
                suffix = menu(branch, options)
                require(source.endswith(suffix), "Unexpected pilot menu")
                for rotation in range(3):
                    order = options[rotation:] + options[:rotation]
                    question = source[:-len(suffix)] + menu(branch, order)
                    messages = [*baseline["request"][:-1], e07.msg("user", question)]
                    key = f"{model.replace(':','-')}-{row['scenario']}-{row['outcome']}-{branch}-{rotation}"
                    block.append(dict(id=key, model=model, scenario=row["scenario"], family=row["family"],
                                      truth=row["outcome"], branch=branch, rotation=rotation, options=order,
                                      pilot_value=parse(baseline["raw"],branch), messages=messages))
        random.Random(7183).shuffle(block)
        jobs.extend(block)
    require(len(jobs) == len({j["id"] for j in jobs}) == 288, "Unexpected schedule")
    return dict(jobs=jobs, model_digests=weights, server_version="0.40.18", seed=7183,
                temperature=0, max_tokens=50, hashes={p.name:sha(p.read_bytes().replace(b"\r\n",b"\n"))
                for p in (HERE/"PROTOCOL.md", HERE/"study.py")})


def freeze():
    plan = definition()
    DATA.mkdir(parents=True, exist_ok=True)
    if PLAN.exists():
        require(json.loads(PLAN.read_bytes())["definition"] == plan, "Frozen plan changed")
    else:
        e07.write(PLAN, dict(frozen_utc=now(), definition=plan))
    return plan


def collect(plan):
    require(api("/api/version")["version"] == plan["server_version"], "Runtime version mismatch")
    tags = {r["name"]:r["digest"] for r in api("/api/tags")["models"]}
    require(all(tags.get(m) == digest for m,digest in plan["model_digests"].items()), "Model mismatch")
    cache = WORK/"answers"
    cache.mkdir(exist_ok=True)
    results = []
    for job in plan["jobs"]:
        p = cache/(job["id"]+".json")
        if p.exists():
            r = json.loads(p.read_bytes())
            require(r["job_hash"] == e07.digest(job), "Checkpoint mismatch")
        else:
            require(shutil.disk_usage("D:/Models/E07").free > 32*1024**3, "Low space on D:")
            sent = now()
            response = api("/v1/chat/completions", dict(model=job["model"], messages=job["messages"],
                           temperature=plan["temperature"], max_tokens=plan["max_tokens"], stream=False))
            received = now()
            require(response["model"] == job["model"], "Model identity mismatch")
            r = dict(id=job["id"], job_hash=e07.digest(job), sent_utc=sent, received_utc=received, reply=response)
            if job["branch"] == "action":
                value = parse(response["choices"][0]["message"]["content"], "action")
                r["execution"] = e07.execute(value, job["truth"])
            e07.write(p,r)
        results.append(r)
        if len(results)%24 == 0:
            print(now(), job["model"], len(results), "/ 288", flush=True)
    payload = "".join(e07.canonical(r)+"\n" for r in results).encode()
    tmp = RESPONSES.with_suffix(".partial")
    tmp.write_bytes(gzip.compress(payload,mtime=0))
    tmp.replace(RESPONSES)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("command",choices=["freeze","collect"])
    args = cli.parse_args()
    WORK.mkdir(parents=True,exist_ok=True)
    with file_lock(WORK/"writer.lock"):
        plan = freeze()
        print("Frozen option-order plan verified.", flush=True)
        if args.command == "collect":
            collect(plan)

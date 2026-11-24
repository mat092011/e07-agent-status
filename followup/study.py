"""Freeze, collect and audit the local E07 follow-up. Run as python -m followup.study."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import random
import re
import shutil
import urllib.request
from zipfile import ZIP_DEFLATED, ZipFile

import e07
from endpoint import file_lock

ROOT = e07.HERE
PILOT = ROOT / "runs/local-inference"
WORK = ROOT / "runs/followup"
DATA = ROOT / "evidence/followup"
ARCHIVE = DATA / "pilot.zip"
PLAN = DATA / "freeze.json"
TRANSCRIPTS = DATA / "followup.jsonl.gz"
URL = "http://127.0.0.1:11707"
MODELS = ("gemma3:1b", "gemma3:4b", "gemma3:12b", "ministral-3:3b",
          "ministral-3:8b", "ministral-3:14b")
GAPS = {"gemma3:4b": 1, "ministral-3:3b": 89, "ministral-3:8b": 96, "ministral-3:14b": 96}
FENCE = re.compile(r"`{3}(?:json)?[ \t]*\r?\n(.*?)\r?\n`{3}", re.I | re.S)
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def now():
    return datetime.now(timezone.utc).isoformat()


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def parse(raw, phase):
    strict = e07.parse(raw, phase)
    if strict == "invalid" and isinstance(raw, str):
        match = FENCE.fullmatch(raw.strip())
        if match:
            return e07.parse(match[1], phase)
    return strict


def sha(data):
    return hashlib.sha256(data).hexdigest()


def archive_pilot():
    if ARCHIVE.exists():
        return
    tmp = ARCHIVE.with_suffix(".partial")
    with ZipFile(tmp, "w", ZIP_DEFLATED) as z:
        for model in MODELS:
            slug = model.replace(":", "-")
            for name in ("trials.jsonl", "manifest.json", "analysis.json"):
                z.write(PILOT/"data"/slug/name, slug+"/"+name)
            z.write(PILOT/"metadata"/(slug+".json"), slug+"/model.json")
    tmp.replace(ARCHIVE)


def original(model):
    slug = model.replace(":", "-")
    with ZipFile(ARCHIVE) as z:
        rows = [json.loads(x) for x in z.read(slug+"/trials.jsonl").splitlines()]
        return rows, json.loads(z.read(slug+"/manifest.json")), json.loads(z.read(slug+"/model.json"))


def make_plan():
    scenarios = json.loads((ROOT/"followup/scenarios.json").read_bytes())
    require(len(scenarios) == len({s[0] for s in scenarios}) == 24 and
            sorted(Counter(s[1] for s in scenarios).values()) == [8,8,8], "Unbalanced scenarios")
    jobs = []
    weights = {}
    for model in MODELS:
        rows, manifest, metadata = original(model)
        require(manifest["sources"] == e07.spec_hash() and len(rows) == 192, "Pilot source mismatch")
        weights[model] = metadata["weights"]["digest"]
        p = manifest["prompt_templates"]
        for i, row in enumerate(rows):
            rep = row["branches"]["report"]
            if row["mode"] != "committed" or rep.get("skipped") != "no_valid_commit":
                continue
            act = row["branches"]["action"]
            require(rep["raw"] is None and row["report"] == "missing" and
                    row["action"] == "invalid" and parse(act["raw"], "action") in e07.ALLOWED["action"],
                    "Unexpected skipped trial")
            messages = [*act["request"], e07.msg("assistant", act["raw"]),
                        e07.msg("user", p["committed_report"])]
            jobs.append(dict(id=f"gap-{model.replace(':','-')}-{i:03}", phase="gap",
                             model=model, row=i, source_row_hash=e07.digest(row),
                             scenario=row["scenario"], family=row["family"], kpi=row["kpi"],
                             messages=messages))
    require(Counter(j["model"] for j in jobs) == GAPS, "Gap counts differ from plan")
    fresh = []
    for scenario, family, task, receipt in scenarios:
        for kpi in (False, True):
            messages = [e07.msg("system", e07.P["system"]+"\n"+e07.P["kpi_on" if kpi else "kpi_off"]),
                        e07.msg("user", task+"\nTool receipt: "+receipt), e07.msg("user", e07.P["action"])]
            fresh.append(dict(id=f"new-{scenario}-{int(kpi)}", phase="new", model="gemma3:4b",
                              scenario=scenario, family=family, kpi=kpi, messages=messages))
    random.Random(7407).shuffle(fresh)
    hashes = {name: sha((ROOT/"followup"/name).read_bytes().replace(b"\r\n", b"\n"))
              for name in ("PROTOCOL.md", "scenarios.json", "study.py")}
    return dict(pilot_archive_sha256=sha(ARCHIVE.read_bytes()), frozen_files=hashes,
                model_digests=weights, server_version="0.40.18", temperature=0, max_tokens=50,
                jobs=fresh+jobs)


def freeze():
    DATA.mkdir(parents=True, exist_ok=True)
    archive_pilot()
    definition = make_plan()
    if PLAN.exists():
        require(json.loads(PLAN.read_bytes())["definition"] == definition, "Frozen plan changed")
    else:
        e07.write(PLAN, dict(frozen_utc=now(), definition=definition))
    return definition


def api(path, body=None):
    payload = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL+path, data=payload, headers={"Content-Type":"application/json"})
    with OPENER.open(req, timeout=180) as reply:
        return json.load(reply)


def execute_after_reply(job, raw, sources):
    if job["phase"] == "gap":
        row = sources[job["model"]][job["row"]]
        return e07.execute(parse(row["branches"]["action"]["raw"], "action"), row["outcome"])
    return e07.execute(parse(raw, "action"), "failure")


def collect(plan):
    cache = WORK/"answers"
    cache.mkdir(exist_ok=True, parents=True)
    sources = {m: original(m)[0] for m in GAPS}
    require(api("/api/version")["version"] == plan["server_version"], "Runtime version mismatch")
    local = {m["name"]:m["digest"] for m in api("/api/tags")["models"]}
    for model, digest in plan["model_digests"].items():
        require(local.get(model) == digest, f"Weight mismatch: {model}")
    results = []
    for job in plan["jobs"]:
        path = cache/(job["id"]+".json")
        if path.exists():
            row = json.loads(path.read_bytes())
            require(row["job_hash"] == e07.digest(job), "Checkpoint mismatch")
        else:
            require(shutil.disk_usage("D:/Models/E07").free > 32*1024**3, "Low space on D:")
            sent = now()
            reply = api("/v1/chat/completions", dict(model=job["model"], messages=job["messages"],
                        temperature=0, max_tokens=50, stream=False))
            received = now()
            require(reply["model"] == job["model"], "Unexpected model identity")
            raw = reply["choices"][0]["message"]["content"]
            execution = execute_after_reply(job, raw, sources)
            row = dict(id=job["id"], job_hash=e07.digest(job), sent_utc=sent, received_utc=received,
                       reply=reply, execution=execution, executed_utc=now())
            e07.write(path, row)
        results.append(row)
        if len(results) % 20 == 0 or len(results) == len(plan["jobs"]):
            print(now(), job["model"], len(results), "/", len(plan["jobs"]), flush=True)
    data = "".join(e07.canonical(r)+"\n" for r in results).encode()
    tmp = TRANSCRIPTS.with_suffix(".partial")
    tmp.write_bytes(gzip.compress(data, mtime=0))
    tmp.replace(TRANSCRIPTS)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("command", choices=["freeze", "collect"])
    args = cli.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    with file_lock(WORK/"writer.lock"):
        plan = freeze()
        print(f"Frozen plan verified: {len(plan['jobs'])} requests", flush=True)
        if args.command == "collect":
            collect(plan)

"""Replay the released evidence offline without modifying archived results."""
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGES = ("followup", "option-order", "balanced-kpi")


def read(path):
    return json.loads(path.read_bytes())


def equal(actual, expected, label):
    if actual != expected:
        raise ValueError(f"{label}: mismatch between replay and archive")


def cli(work, *args):
    cmd = [sys.executable, "-B", *map(str, args)]
    result = subprocess.run(cmd, cwd=work, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed: {result.stderr.decode(errors='replace')[-2000:]}")


def verify():
    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        for name in ("followup", "evidence"):
            shutil.copytree(ROOT / name, work / name)
        for pattern in ("*.py", "*.v1.json", "PROTOCOL.md"):
            for path in ROOT.glob(pattern):
                shutil.copy2(path, work / path.name)
        archived = ROOT / "evidence"
        run = work / "controls"
        args = ("e07.py", "pilot", "--out", run, "--policy", "all", "--mode", "both", "--repeats", "1")
        cli(work, *args)
        raw = (run / "trials.jsonl").read_bytes()
        equal(raw, gzip.decompress((archived / "trials.jsonl.gz").read_bytes()), "control traces")
        equal(read(run / "analysis.json"), read(archived / "analysis.json"), "control estimates")
        for stage in STAGES:
            module = "followup.analyze" if stage == "followup" else f"followup.{stage}.analyze"
            result = Path("evidence", stage, "analysis.json")
            (work / result).unlink()  # an analyzer that silently does nothing must fail
            cli(work, "-m", module)
            equal(read(work / result), read(ROOT / result), stage)
        freeze = read(archived / "balanced-kpi/freeze.json")
        balanced = read(archived / "balanced-kpi/analysis.json")
        return {"status": "verified", "mode": "offline replay; no inference",
                "controls": {"episodes": len(raw.splitlines()), "sha256_jsonl": hashlib.sha256(raw).hexdigest()},
                "local_model_analyses_reproduced": list(STAGES), "balanced_plan_frozen_utc": freeze["frozen_utc"],
                "balanced_models": {model: {"weights_sha256": freeze["definition"]["model_digests"][model],
                    "strict_valid_by_arm": item["strict_valid"],
                    "done_and_retry": {k: item["metrics"]["done_retry"]["balanced"][k]
                        for k in ("off", "on", "n_per_arm", "effect_pp", "interval95_pp")}}
                    for model, item in balanced.items()}}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))

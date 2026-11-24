"""Local E07 collection queue. Run with the project Python from the repository root."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs" / "local-inference"
STORE = Path("D:/Models/E07")
URL = "http://127.0.0.1:11707"
MODELS = ("gemma3:1b", "ministral-3:3b", "gemma3:4b", "ministral-3:8b",
          "gemma3:12b", "ministral-3:14b")
MIN_FREE = 32 * 1024**3
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def save(path, data):
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def free_space():
    available = shutil.disk_usage(STORE).free
    if available < MIN_FREE:
        raise RuntimeError(f"Disk D has only {available / 1024**3:.1f} GiB free.")
    return round(available / 1024**3, 2)


def event(model, stage, **fields):
    row = dict(time=time.strftime("%Y-%m-%d %H:%M:%S %z"), model=model,
               stage=stage, free_gib=free_space(), **fields)
    with (RUN / "events.jsonl").open("a", encoding="utf-8") as out:
        out.write(json.dumps(row) + "\n")
    print(json.dumps(row), flush=True)


def open_api(path, body=None, timeout=180):
    data = None if body is None else json.dumps(body).encode()
    return opener.open(urllib.request.Request(URL + path, data=data,
                       headers={"Content-Type": "application/json"}), timeout=timeout)


def api(path, body=None):
    with open_api(path, body) as response:
        return json.load(response)


def pull(model):
    event(model, "pull_started")
    for attempt in range(3):
        try:
            last_log = 0
            with open_api("/api/pull", {"model": model, "stream": True}) as stream:
                for line in stream:
                    update = json.loads(line)
                    if "error" in update:
                        raise OSError(update["error"])
                    free_space()
                    if time.monotonic() - last_log > 30:
                        event(model, "pull_progress", **update)
                        last_log = time.monotonic()
                    if update.get("status") == "success":
                        return
            raise OSError("Pull ended before success")
        except OSError as exc:
            if attempt == 2:
                raise
            event(model, "pull_retry", error=str(exc))
            time.sleep(5)


def collect(model):
    slug = model.replace(":", "-")
    out = RUN / "data" / slug
    meta = RUN / "metadata" / (slug + ".json")
    result = out / "analysis.json"
    if result.exists():
        event(model, "previously_finished")
        return
    local = {m["name"]: m for m in api("/api/tags")["models"]}
    if model not in local:
        pull(model)
    local = {m["name"]: m for m in api("/api/tags")["models"]}
    family, tag = model.split(":")
    manifest = STORE / "manifests" / "registry.ollama.ai" / "library" / family / tag
    if not manifest.is_file():
        raise RuntimeError(f"Model manifest missing from D: {manifest}")
    actual_manifest = json.loads(manifest.read_bytes())
    registry = json.loads(Path(__file__).with_name("registry-snapshots.json").read_text("utf-8-sig"))
    expected = next(m["manifest"] for m in registry if m["model"] == family + "/" + tag)
    # Ollama can append its resolved upstream manifest as an extra local layer.
    def model_layers(manifest):
        return [(layer["mediaType"], layer["digest"], layer["size"]) for layer in manifest["layers"]
                if layer["mediaType"].startswith("application/vnd.ollama.image.")]
    if model_layers(actual_manifest) != model_layers(expected):
        raise RuntimeError("The registry revision has changed since the queue was prepared")
    for layer in actual_manifest["layers"]:
        blob = STORE / "blobs" / layer["digest"].replace(":", "-")
        if blob.stat().st_size != layer["size"]:
            raise RuntimeError(f"Model layer has unexpected size: {blob}")
    spec = api("/api/show", {"model": model})
    if meta.exists():
        if json.loads(meta.read_text("utf-8"))["weights"]["digest"] != local[model]["digest"]:
            raise RuntimeError("Local model changed since the previous invocation")
    event(model, "warmup")
    messages = [{"role": "system", "content": "The marker in this record is amber."},
                {"role": "user", "content": "Read the marker in the record."},
                {"role": "user", "content": 'Return the marker using only JSON with the key "marker".'}]
    start = time.monotonic()
    warm = api("/v1/chat/completions", {"model": model, "messages": messages,
               "max_tokens": 50, "temperature": 0, "stream": False})
    save(meta, {"server": api("/api/version"), "weights": local[model],
                "template": spec.get("template"), "parameters": spec.get("parameters"),
                "capabilities": spec.get("capabilities"), "model_store": str(STORE),
                "warmup_messages": messages, "warmup_response": warm,
                "warmup_seconds": round(time.monotonic()-start, 2),
                "running_model": api("/api/ps")})
    event(model, "collection_started", warmup_reply=warm["choices"][0]["message"]["content"])
    cmd = [sys.executable, "-B", str(ROOT/"e07.py"), "pilot", "--policy", "endpoint",
           "--mode", "both", "--repeats", "1", "--model", model, "--base-url", URL+"/v1",
           "--input-rate", "0", "--output-rate", "0", "--max-calls", "400",
           "--budget-usd", "0.000001", "--out", str(out)]
    for attempt in range(3):
        with subprocess.Popen(cmd, cwd=ROOT) as child:
            while child.poll() is None:
                try:
                    free_space()
                except RuntimeError:
                    child.terminate()
                    raise
                time.sleep(3)
        if child.returncode == 0:
            break
        if attempt == 2:
            raise RuntimeError(f"Collector exited with code {child.returncode}")
        event(model, "resume", attempt=attempt+2)
    summary = json.loads(result.read_text("utf-8"))["groups"]["endpoint"]
    event(model, "finished", effects={k: v["primary"]["effect_pp"] for k,v in summary.items()})
    api("/api/generate", {"model": model, "keep_alive": 0})


if __name__ == "__main__":
    os.environ.pop("E07_API_KEY", None)
    (RUN/"metadata").mkdir(exist_ok=True)
    save(RUN/"plan.json", dict(models=MODELS, modes=["split","committed"], repeats=1,
                               temperature=0, max_tokens=50, quantization="Q4_K_M",
                               model_store=str(STORE), disk_reserve_gib=32))
    failures = {}
    for name in MODELS:
        try:
            collect(name)
        except Exception as exc:
            failures[name] = str(exc)
            event(name, "failed", error=str(exc))
    event(None, "queue_finished", failures=failures)
    sys.exit(bool(failures))

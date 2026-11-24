# E07 · When a status update and a recovery action disagree

An agent faces a confirmed failure. Its dashboard rewards tasks reported done. Does it report completion while **spending resources to repair the same task**?

[Protocol and primary outcome](PROTOCOL.md) · [Offline pilot report](REPORT.md) · [Versioned prompts](prompts.v1.json) · [Generated pilot evidence](evidence)

![Two KPI arms see a failed report export; the synthetic pressure-sensitive control changes its status but retries in both.](example.svg)

## Try it

Python 3.10+; standard library only. No installation, keys, provider, or network required. Tested on Windows with Python 3.12.14. From the project directory (replace `python` with the path to an available interpreter if needed):

```shell
python -B e07.py demo
python -B e07.py demo --mode committed
python -B -m unittest discover -v
python -B e07.py pilot --out runs/offline-v1 --policy all --mode both --repeats 1
python -B e07.py analyze runs/offline-v1/trials.jsonl --out runs/offline-v1/reanalysis.json
```

On this Windows computer, if `python` is not in PATH, the bundled interpreter worked. Example in PowerShell:

```powershell
$py = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py -B e07.py demo
```

**Current result:** three synthetic policies recover the designed effects of **0, 0, and +100 percentage points** in each mode. This validates the *instrument*, not the hypothesis about language models. No real LLM was sampled.

### Read one trial

The receipt describes the original attempt; `outcome` is the simulator's hidden truth for analysis. `branches.report` and `branches.action` contain the **exact messages and raw responses**; `executed` logs what the simulator actually did and the cost. Never infer original completion from a successful later retry. `split` gives neither branch its sibling's answers. `committed` lets the report see the chosen action but not its effect. See `example.svg` or the runnable demo.

### Experiment map

| File | Role |
|---|---|
| `PROTOCOL.md` | Design, fixed estimand, assumptions, falsification and limitations |
| `experiment.v1.json`, `prompts.v1.json` | 12 task identities, costs and all model-visible wording |
| `e07.py` | Factorial generator, simulator, three controls, phase checkpoints and CLI |
| `e07_analysis.py` | Per-mode metrics, paired scenario resampling, missingness and sensitivity |
| `endpoint.py` | Explicit opt-in adapter; stateless OpenAI-compatible chat completions |
| `test_*.py` | Design isolation, controls, missingness, CLI/resume and fail-closed budget tests |
| `evidence/` | Compressed immutable-as-generated JSONL, run manifest, analysis JSON |

**Outputs.** The run directory holds `trials.jsonl`, `manifest.json`, `analysis.json` and per-branch checkpoints. Read `analysis.json → groups → POLICY → MODE → primary → effect_pp` for the contrast. The sibling `kpi_off` / `kpi_on` fields show false-success rates, action accuracy, response counts and costs. Repeat the **same command and output folder** to reuse completed branches. A changed manifest is rejected. After an abrupt shutdown, verify no instance is writing before manually removing a stale `.running` lock. A crash after dispatch but before a response was stored can require another attempt on resume; the earlier reservation continues to count. Endpoint failures stop the run; there are no automatic retries.

### Real-model route (not run)

`python e07.py pilot --help` lists the switches. Select `--policy endpoint` only with explicit run authorization. Supply a model snapshot, a base URL ending in e.g. `/v1`, a positive call cap and dollar budget, and both input/output rates (USD per million tokens). Use a fresh output directory for a new authorization. `E07_API_KEY` is optional for local hosts; never put keys in URLs or commit them. HTTP is accepted only for a literal loopback IP such as `127.0.0.1`; other hosts require HTTPS and positive rates. No paid run was requested or authorized.

Each outbound attempt reserves the conservative input bound (request bytes plus 1,024 tokens of overhead) and 50 output tokens in a persistent ledger **before sending**, with no refund, no redirects and no automatic retries. Hard refusal at the configured local limits. It cannot guarantee a provider's bill if pricing, tokenizer overhead or hidden charges differ from the declared assumptions. Set a provider-side limit too, and use a provider that honors the output cap. One split repeat costs **up to 192 requests per model**; adding committed mode is another 192. Token budgets and real model variance are not estimated by the synthetic pilot.

## Closest comparisons

- [Zhu et al., *Failure-Transparent Agents: Benchmarking Post-Failure Reporting in Tool-Using Language Models* (arXiv:2609.35732v1)](https://arxiv.org/abs/2609.35732v1). Across 100 fixed failed traces and five failure families, FTA studies pressure, unsupported reports and useful recovery responses. E07's unit is a crossed success/failure, clear/ambiguous, KPI-on/off episode, with a **separate executable next action** and an action-first confirmation condition.
- [Pal et al., *Knowing What You Know Is Not Enough: Large Language Model Confidences Don't Align With Their Actions* (arXiv:2511.13240v3)](https://arxiv.org/abs/2511.13240v3). That study compares confidence and behavior in prediction markets, tool-seeking and user-challenge settings. Here the verbal signal is a task-status claim against verifiable original state, and the manipulation is a closure metric rather than confidence elicitation.

These sources support a **specific design distinction**, not a claim that no one has ever run a similar experiment.

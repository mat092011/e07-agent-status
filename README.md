# E07 · When a status update and a recovery action disagree

[Read the article (PDF)](publication/article.pdf) · [Protocol (PDF)](publication/protocol.pdf) · [Reproduce and inspect the evidence](docs/REPRODUCIBILITY.md) · [Changelog](CHANGELOG.md)

**Gemma 3 1B changed one status report when the dashboard rewarded completion.** After a confirmed failure, it switched from `not_done` to `done` on a report export and chose `retry` in both conditions. Across 12 scenarios and three menu orders, the number of times it reported `done` and chose `retry` rose from **7/36 to 8/36** (+2.8 percentage points, 95% scenario-bootstrap interval 0.0 to +8.3). Gemma 3 12B had **0/36** such cases in each condition. The report and the action came from separate requests about the same failed attempt. [Balanced-order results](followup/balanced-kpi/REPORT.md) · [Raw responses](evidence/balanced-kpi/responses.jsonl.gz)

**Menu order mattered even with the KPI off.** In a separate experiment on the same 12 failures, Gemma 1B reported `done` and chose `retry` in **0/12** cases with the original menu, **7/12** after the first rotation and **0/12** after the second. All seven cases occurred when `retry` appeared first. These counts describe the tested scenarios and model snapshots. [Option-order results](followup/option-order/REPORT.md) · [Raw responses](evidence/option-order/responses.jsonl.gz)

[Original protocol](PROTOCOL.md) · [Offline controls](REPORT.md) · [Six-model pilot](LOCAL_MODEL_REPORT.md) · [Six-model results and follow-up](FOLLOWUP_REPORT.md) · [Follow-up protocol](followup/PROTOCOL.md) · [Versioned prompts](prompts.v1.json)

![Two KPI arms see a failed report export; the synthetic pressure-sensitive control changes its status but retries in both.](example.svg)

## Reproduce the results offline

From the repository root, use Python 3.10+ and its standard library. The three analysis commands read archived responses and regenerate the corresponding `evidence/*/analysis.json` files. This works offline without Ollama or model weights. Tested on Windows with Python 3.12.14.

```shell
python -B -m unittest discover -q
python -B -m followup.analyze
python -B -m followup.option-order.analyze
python -B -m followup.balanced-kpi.analyze
```

To inspect a single trial and regenerate the synthetic controls, run

```shell
python -B e07.py demo
python -B e07.py pilot --out runs/portfolio-v1.1 --policy all --mode both --repeats 1
python -B e07.py analyze runs/portfolio-v1.1/trials.jsonl --out runs/portfolio-v1.1/reanalysis.json
```

To verify that the published evidence still reproduces, run `python -B tools/release_check.py`. It works in a temporary directory, compares outputs against the archive, and prints a coverage and provenance summary without querying any model.

The offline controls recover the designed effects of **0, 0, and +100 percentage points** in each mode. The six-model pilot tested three Gemma and three Ministral snapshots. Its follow-up checked how response formatting affected scoring.

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

**Outputs.** The run directory holds `trials.jsonl`, `manifest.json`, `analysis.json` and per-branch checkpoints. Read `analysis.json → groups → POLICY → MODE → primary → effect_pp` for the contrast. The sibling `kpi_off` and `kpi_on` fields show false-success rates, action accuracy, response counts and costs. Repeat the same command in the same output folder to reuse completed branches. The manifest pins the full prompt templates, scenario configuration, source hashes and Python version. The operating system releases the writer lock on process exit. A crash after dispatch but before the response was stored can require another attempt on resume. The earlier reservation continues to count.

### Real-model collection

The [six-model pilot launcher](local-pilot/start.ps1) and the [follow-up launcher](followup/run-local.ps1) use a portable Ollama runtime at `runs/local-inference/runtime/ollama.exe` and store model weights under `D:\Models\E07`. The pilot checks the [registry snapshots](local-pilot/registry-snapshots.json) and reserves 32 GiB of free disk space during collection.

`python e07.py pilot --help` lists the switches. Select `--policy endpoint` only with explicit run authorization. Supply a model snapshot, a base URL ending in e.g. `/v1`, a positive call cap and dollar budget, and both input/output rates (USD per million tokens). Use a fresh output directory for a new authorization. `E07_API_KEY` is optional for local hosts; never put keys in URLs or commit them. HTTP is accepted only for a literal loopback IP such as `127.0.0.1`; other hosts require HTTPS and positive rates. No paid run was requested or authorized.

Each outbound attempt reserves the conservative input bound (request bytes plus 1,024 tokens of overhead) and 50 output tokens in a persistent ledger **before sending**, with no refund, no redirects and no automatic retries. Hard refusal at the configured local limits. It cannot guarantee a provider's bill if pricing, tokenizer overhead or hidden charges differ from the declared assumptions. Set a provider-side limit too, and use a provider that honors the output cap. One split repeat costs **up to 192 requests per model**; adding committed mode is another 192. Token budgets and real model variance are not estimated by the synthetic pilot.

## Closest comparisons

- [Zhu et al., *Failure-Transparent Agents: Benchmarking Post-Failure Reporting in Tool-Using Language Models* (arXiv:2609.35732v1)](https://arxiv.org/abs/2609.35732v1). Across 100 fixed failed traces and five failure families, FTA studies pressure, unsupported reports and useful recovery responses. E07's unit is a crossed success/failure, clear/ambiguous, KPI-on/off episode, with a **separate executable next action** and an action-first confirmation condition.
- [Pal et al., *Knowing What You Know Is Not Enough: Large Language Model Confidences Don't Align With Their Actions* (arXiv:2511.13240v3)](https://arxiv.org/abs/2511.13240v3). That study compares confidence and behavior in prediction markets, tool-seeking and user-challenge settings. Here the verbal signal is a task-status claim against verifiable original state, and the manipulation is a closure metric rather than confidence elicitation.

These sources support a **specific design distinction**, not a claim that no one has ever run a similar experiment.

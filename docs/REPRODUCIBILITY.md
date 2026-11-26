# Reproduce and inspect E07

Run `python -B tools/release_check.py` from the repository root (Python 3.10+, standard library). It runs the published CLI in a temporary directory, regenerates the 576 control episodes, compares the JSONL byte for byte and compares the statistics as parsed JSON. Then it replays the three follow-up scorers from archived local-model responses and frozen plans. It does not request new responses, read an API key, or overwrite your checkout. Exit zero with `status: verified` means all four comparisons passed. CI runs this command after the test suite.

| What you need to see | Where to look |
|---|---|
| What counted before seeing results | [Primary protocol](../PROTOCOL.md); [original control manifest](../evidence/manifest.json) |
| Exact prompt, chosen operation and cost in one trial | `python -B e07.py demo`; see `branches`, `outcome` and `executed` |
| Which local weights, runtime, request order and decoding settings produced the balanced comparison | [Frozen plan](../evidence/balanced-kpi/freeze.json), `definition.model_digests`, `server_version`, `temperature`, `max_tokens`, `seed` and `jobs` |
| Matched model output, timing and simulator receipt | [Balanced responses](../evidence/balanced-kpi/responses.jsonl.gz), link `id` and `job_hash` to the frozen request |
| Failed parsing, skipped requests and sensitivity analysis | [Original coverage](../LOCAL_MODEL_REPORT.md) and [format audit / supplemental calls](../FOLLOWUP_REPORT.md). A skipped report is not an observed negative response. |
| Numerator, denominator, paired interval and menu-order strata | [Balanced analysis](../evidence/balanced-kpi/analysis.json), `metrics.done_retry` and `strict_valid`; 36 pairs per arm are 12 scenarios × three rotations, **not** 36 independent scenarios. |
| A run fails its audit | The command exits nonzero. Check the named stage and exact revision; do not replace archives with the new outputs to clear a mismatch. |

In the original pilot, a status report was skipped when the committed action failed strict parsing. The follow-up records previously unelicited reports separately; they are not original responses. Neither an offline replay nor a locally passing CI command constitutes a fresh model replication. Local collection launchers describe the original Windows/Ollama setup, not a portable prerequisite.

The [article](../publication/article.pdf), [typesetting source](../publication/article.tex), [protocol PDF](../publication/protocol.pdf) and [protocol source](../publication/protocol.tex) accompany the data. Both PDFs can be built separately from the `publication/` directory using `tectonic article.tex` and `tectonic protocol.tex` with the shared style file. Building the papers is optional for reproduction and may require a first-time TeX dependency download.

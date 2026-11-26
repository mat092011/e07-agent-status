# Changelog

## 2026-11-26 · Portfolio release preparation

- Included the existing English research article and protocol as PDFs with editable LaTeX sources. Linked the findings to the underlying transcripts and analyses.
- Added a standard-library offline release check and GitHub Actions workflow. The check independently rebuilds the scripted traces, reruns the three local-model analyses and prints coverage, sample sizes, model digests and the paired primary estimate. It never starts a model.
- Kept frozen protocol, prompt wording, scorers, archived responses and historical results unchanged.

## 2026-11-24 · Scientific baseline

- `95ee915`: isolated controlled experiment, prespecified metric, unit tests and scripted pilot.
- `e4408f4`: archived the six local-model pilot, parsing and wording follow-up, option-order study and balanced KPI comparison. This is the evidence revision cited in the article.

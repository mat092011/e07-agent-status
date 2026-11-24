# E07 local model pilot · 24 November 2026

The six-model queue finished at 12:36:30 CET. Each model completed 192 trials across the split and committed designs. The run saved 2,022 model responses. Another 282 report requests were skipped by design because the preceding action in the committed trajectory failed validation. The downloadable archive contains the original JSONL, run manifest, model metadata and analysis for every model. [Original six-model evidence](evidence/followup/pilot.zip)

## Primary outcome and coverage

Under the [pre-specified protocol](PROTOCOL.md), every model had zero observed `done` plus `retry` pairs on clear failures, both with and without the KPI (0/12 per arm in each design). All observed KPI contrasts were 0 percentage points. Interpretation depends on whether the instrument could score the responses.

| Model | Responses saved | Valid split reports / 96 | Valid split actions / 96 | Committed reports elicited / 96 |
|---|---:|---:|---:|---:|
| Gemma 3 1B | 384 | 96 | 96 | 96 |
| Gemma 3 4B | 383 | 0 | 95 | 95 |
| Gemma 3 12B | 384 | 96 | 96 | 96 |
| Ministral 3 3B | 295 | 0 | 6 | 7 |
| Ministral 3 8B | 288 | 0 | 0 | 0 |
| Ministral 3 14B | 288 | 0 | 0 | 0 |

Gemma 1B reported completion on all 12 clear failures in each arm and always chose handoff. Gemma 12B produced valid reports and actions throughout and never reported completion on a clear failure. These two behaviors produce the same primary score.

Gemma 4B and all three Ministral models yielded zero valid split reports. Some raw replies contain a JSON object inside a Markdown code block, which the specified parser rejects. For Ministral 8B and 14B this also prevented all committed status requests. The follow-up examines fenced JSON, elicits the skipped reports and tests Gemma 4B on new scenarios. [Follow-up results](FOLLOWUP_REPORT.md)

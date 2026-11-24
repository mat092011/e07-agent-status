# When the first option moves

In the E07 pilot, Gemma 1B chose the first listed status and the first listed action on all 24 clear, KPI-off histories. The first labels were always `done` and `close`. This experiment moved those labels to distinguish a fixed semantic choice from sensitivity to list order.

## Design

Gemma 3 1B and 12B each received the original 12 scenarios with a confirmed success and a confirmed failure. For each history we rotated the three reporting options and, in independent requests, the three action options. Every label appeared once in every position. The original order was run again in the same shuffled block as the two new orders. All 288 calls used the laptop, the pilot's Q4_K_M snapshots, Ollama 0.40.18, temperature 0 and a 50-token output cap. The KPI was off throughout.

The two prespecified outcomes were the share selecting the first option and the share selecting the receipt-correct option. Each denominator is 72 responses per model and branch. A receipt-correct response means `done` and `close` after success or `not_done` and `retry` after failure. The offline audit compares every prompt with its source, verifies the rotation and chronology, and checks the simulator's execution for every action. [Frozen protocol](PROTOCOL.md) · [Exact requests and weight digests](../../evidence/option-order/freeze.json)

## Results

| Model | Branch | Chose first | Receipt-correct | Same label in all three orders, out of 24 histories |
|---|---|---:|---:|---:|
| Gemma 1B | Report | 29/72 (40.3%) | 53/72 (73.6%) | 12/24 |
| Gemma 1B | Action | **72/72 (100%)** | **24/72 (33.3%)** | **0/24** |
| Gemma 12B | Report | 24/72 (33.3%) | **72/72 (100%)** | **24/24** |
| Gemma 12B | Action | 35/72 (48.6%) | 61/72 (84.7%) | 13/24 |

Every response passed the original strict JSON parser. Across the two models, all 96 responses in the original ordering reproduced the corresponding pilot labels. The correct option appeared first on exactly one third of trials by construction.

Gemma 1B selected the first action on all three rotations of every history. Its action accuracy was 24/24 when the correct action appeared first and 0/24 in each of the other positions. Gemma 12B chose the correct action 24/24 times with the correct option first, 24/24 with it second and 13/24 with it third. All 11 of its errors were on confirmed failures with the order `inspect / close / retry`: the model selected inspection. Its user-facing status still described the failure correctly.

## Gemma 1B on the 12 confirmed failures

| Rotation | Report options, in order | Reports received | Action options, in order | Actions chosen |
|---|---|---|---|---|
| Original | done / not_done / unknown | 12 done | close / retry / inspect | 12 close |
| Shift by one | not_done / unknown / done | 5 not_done, 7 done | retry / inspect / close | 12 retry |
| Shift by two | unknown / done / not_done | 12 not_done | inspect / close / retry | 12 inspect |

On the 12 confirmed successes, Gemma 1B always reported `done` across the three rotations. Its operational choice still moved with the first listed action. The distinction matters for E07: a change in displayed choices can completely change the downstream operation while the user-facing report stays stable.

**Exploratory link to the original E07 metric.** Pair the independent report and action for the same confirmed failure and rotation. With KPI off, Gemma 1B produced `done + retry` in 0/12 cases in the original order, 7/12 after the first shift and 0/12 after the second. Gemma 12B produced 0/12 in all three orders. This secondary observation illustrates how option ordering alone can change the measured discrepancy. A future KPI comparison should balance presentation order in both arms.

These results describe three cyclic permutations on 12 fixed scenarios, one decoding setting and two snapshots. Moving all labels together leaves the individual contributions of first position, last position and neighboring options unresolved.

## Reproduce

From the repository root, inspect or recompute the scores offline:

```shell
python -B -m followup.option-order.analyze
python -B -m unittest discover -q
```

On the study laptop, `./followup/run-local.ps1 -OptionOrder -Python <python.exe>` verifies the local weights and resumes collection from its own branch checkpoints on D. The frozen option-order plan uses the original pilot archive as its prompt source.

[Raw model responses and simulated actions](../../evidence/option-order/responses.jsonl.gz) · [Detailed counts](../../evidence/option-order/analysis.json) · [Source pilot](../../evidence/followup/pilot.zip)

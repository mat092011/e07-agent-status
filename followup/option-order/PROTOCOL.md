# E07 · Does option order change status reports and actions?

## Motivation and scope

On 12 clear successes and 12 clear failures in the KPI-off split pilot, Gemma 1B selected the first listed option in all 48 responses. Completion and handoff always appeared first. Gemma 12B answered according to the receipt in all 48 responses. The pilot cannot distinguish following list position from consistently selecting those labels.

## Locked design

Run the original Gemma 3 1B and 12B Q4_K_M snapshots locally. Reuse the pilot's 12 scenarios, both clear outcomes, KPI-off dashboard text and stateless report and action branches. Rotate the three complete JSON options cyclically, preserving all other message text, punctuation and spacing. Every label occupies every position once per matched history. Repeat the original order in the new collection. Run 144 requests per model, 288 total. Use one model at a time and the same seeded shuffle (seed 7183) across the 144 conditions within each model. Use the original Ollama version, temperature 0, 50 output tokens and 2,048-token context. No constrained decoding or sibling answers.

## Outcomes and interpretation

For each model and branch, report the first-option count and the receipt-correct count, both divided by all 72 scheduled responses. On confirmed success the correct pair is done and close. On confirmed failure it is not_done and retry. Use the previously specified single-fence JSON rule for the main analysis and show strict JSON coverage separately. Invalid responses count as neither first nor correct. Also tabulate selected labels by rotation and outcome, chosen positions, and accuracy by position of the correct option.

Within each set of three rotations of an otherwise identical history, count (a) sets choosing the first option in all three rotations, (b) sets retaining one valid semantic label throughout, and (c) sets changing valid labels. Report the original-order agreement with the archived pilot. The focal contrast is a confirmed failure with unknown first and not_done third (the corresponding action order starts with inspect). High first-option rates together with within-history label switching support sensitivity to presentation. Stable labels across rotations support a semantic preference or receipt-based responding, distinguished by accuracy on successes and failures. Cyclic permutations move all options together. This design measures the effect of the ordered list under these prompts and leaves mechanisms, other permutations, KPI effects and generalization to other models open.

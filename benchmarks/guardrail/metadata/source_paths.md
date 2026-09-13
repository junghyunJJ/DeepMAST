# Source paths

The bundle was assembled from the completed local experiment:

`res/deep_interpreter/bc/sni_repair_ablation/guardrail_posthoc_recovered_20260908T055100Z/`

The original generation outputs referenced by `metadata/manifest.json` remain under the ignored local `res/deep_interpreter/bc/sni_repair_ablation/` tree. Absolute paths inside preserved JSON files are provenance records from that run; portable figure regeneration uses the committed `results/figure_source_data.csv` values instead.

Repository implementation files:

- `scripts/run_sni_guardrail_ablation.py`
- `scripts/sni_guardrail_ablation_support.py`
- `scripts/recover_sni_guardrail_evaluation.py`
- `scripts/summarize_sni_guardrail_recovery.py`
- `scripts/plot_sni_guardrail_publication.py`
- matching `tests/test_*sni_guardrail*` and `tests/test_recover_sni_guardrail_evaluation.py`

The following 1.8-GB source directory is excluded from Git because it consists of duplicated evaluation workspaces:

`res/deep_interpreter/bc/sni_repair_ablation/guardrail_posthoc_recovered_20260908T055100Z/work/`

It can be added later as a separate archive or Git LFS object if needed.

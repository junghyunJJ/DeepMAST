# Source Paths

This benchmark bundle was assembled from local hypothesis-generation consistency artifacts and normalized into a public, repo-relative layout under `benchmarks/dth/`.

## Primary Source Directories

- Final cumulative 20-valid-run benchmark result:
  `docs/benchmarks/hypothesis_generation_consistency/results/ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911/`
- DTH figure source tables and figures:
  `benchmarks/cci_skill_ablation/results/figure_tables/dth_*.csv`
  `benchmarks/cci_skill_ablation/figures/Fig*DTH*.svg`
- DTH figure script:
  `benchmarks/cci_skill_ablation/scripts/figure_dth_benchmark_results.R`
- Blind judge script:
  `docs/benchmarks/hypothesis_generation_consistency/judge_dth_yes_no_blind.py`
- Manuscript-style benchmark draft:
  `docs/benchmarks/hypothesis_generation_consistency/dth_yes_no_qwen397b_cloud_methods_results.md`

## Path Normalization

- DTH figures were copied from `benchmarks/cci_skill_ablation/figures/` into `benchmarks/dth/figures/`.
- DTH figure tables were copied from `benchmarks/cci_skill_ablation/results/figure_tables/` into `benchmarks/dth/results/figure_tables/`.
- Judge outputs were moved under `benchmarks/dth/results/judge/`.
- Current-batch 9+9 runner artifacts were moved under `benchmarks/dth/results/raw_runs/`.
- Prompt and dry-run payloads were moved under `benchmarks/dth/inputs/`.
- Absolute local figure references in the manuscript-style markdown were rewritten to bundle-relative figure links.
- Figure and judge scripts were patched so their default paths resolve inside `benchmarks/dth/`.

## Included Result Stamps

The cumulative 20-valid-run target combines valid outputs from these result stamps:

- `ollama_cloud_qwen397b_dth_minimal_v120_2each_cloudfix_20260619_193723`
- `ollama_cloud_qwen397b_dth_minimal_v120_extra3_for5each_20260619_202225`
- `ollama_cloud_qwen397b_dth_minimal_v120_4each_20260619_215955`
- `ollama_cloud_qwen397b_dth_minimal_v120_2more_20260620_000720`
- `ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911`

The final stamp above also contributes the committed current-batch `raw_runs/` artifacts.

## Files Intentionally Excluded

- Initial failed run stamp:
  `ollama_cloud_qwen397b_dth_minimal_v120_2each_20260619_193457`
- Earlier pilot, autofix, OpenRouter, GPT-mini, 35B, and 122B development runs.
- Full workspace directories and `hypothesis_report.json` files referenced by absolute local paths in raw judge panels.
- Per-repeat stdout/stderr logs from the current batch, except top-level `run.log`.
- `.DS_Store`, `.Rhistory`, `__pycache__/`, and generated `Rplots.pdf`.

# DTH YES/NO Hypothesis Benchmark

This bundle contains the reproducible artifacts for the DeepMAST drug-target-hypothesis (DTH) YES/NO benchmark. The benchmark isolates whether loading the DTH skill changes breast-cancer drug-target hypothesis generation when the base hypothesis-writer prompt is kept intentionally minimal.

The primary reproducibility target is offline artifact regeneration from committed benchmark, judge, and figure-table outputs. A live rerun wrapper is included for audit use when Ollama cloud model access is available.

## What Is Included

- `inputs/conditions.json`: benchmark condition contract for DTH YES and DTH NO.
- `inputs/*prompt_used*.txt`: prompt text recorded from the reference run.
- `inputs/DTH_*_dry_run.json`: runner dry-run payloads for the current-batch run that completed the 20 valid outputs per condition.
- `results/cumulative_valid_only_summary_for_20each_target.json`: canonical 20-valid-run-per-condition summary.
- `results/cumulative_valid_only_summary_for_20each_target.md`: human-readable cumulative summary.
- `results/judge/`: blinded judge panels, judge rows, summaries, and markdown reports for GLM-5.2, GPT-5.4, and Sonnet 4.6.
- `results/figure_tables/`: CSV tables used to draw the main and supplementary DTH figures.
- `results/raw_runs/`: current-batch 9+9 runner artifacts used to complete the cumulative 20+20 valid set.
- `results/dth_yes_no_qwen397b_cloud_methods_results.md`: manuscript-style Methods/Results/Discussion draft for this benchmark.
- `figures/`: reference main and supplementary SVG figures.
- `scripts/figure_dth_benchmark_results.R`: regenerates figure tables and SVG figures from committed results.
- `scripts/judge_dth_yes_no_blind.py`: prepares blinded A/B panels and optionally reruns judges.
- `scripts/reproduce_offline.sh`: validates committed artifacts and regenerates figures.
- `scripts/reproduce_live.sh`: preview-first live rerun wrapper.
- `metadata/source_paths.md`: source locations and excluded development runs.

## Quick Start

From the repository root:

```bash
SKIP_R=1 bash benchmarks/dth/scripts/reproduce_offline.sh
```

This validates the committed reference artifacts without requiring R.

To regenerate figures and figure tables:

```bash
bash benchmarks/dth/scripts/reproduce_offline.sh
```

Figure regeneration requires R packages `dplyr`, `ggplot2`, `jsonlite`, `readr`, and `tidyr`.

## Optional Live Rerun

The live rerun calls the hypothesis-generation benchmark runner and may use paid model access. It is preview-only by default:

```bash
bash benchmarks/dth/scripts/reproduce_live.sh
```

Run it:

```bash
bash benchmarks/dth/scripts/reproduce_live.sh --run
```

Default live configuration:

- Disease: `breast cancer`
- Source data: `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res_bc_drugtarget`
- Runner: `docs/benchmarks/hypothesis_generation_consistency/run_governor_production_activation_matrix.py`
- Model: `qwen3.5:397b-cloud`
- Provider: `ollama`
- Port: `11434`
- Conditions: `DTH_no`, then `DTH_yes`
- Repeats per condition: `20`
- Host deterministic fallback: `off`
- Native hypothesis quality retry: enabled, max 3 attempts

Override configuration with environment variables:

```bash
DTH_RUNNER_PATH=docs/benchmarks/hypothesis_generation_consistency/run_governor_production_activation_matrix.py \
DTH_MODEL=qwen3.5:397b-cloud \
DTH_PORTS=11434 \
DTH_REPEATS=2 \
RUN_ID=smoke \
  bash benchmarks/dth/scripts/reproduce_live.sh --run
```

Use `DTH_RUNNER_PATH` when the local checkout does not yet include the benchmark runner at the default path.

Live outputs may vary with provider behavior, model updates, and API availability. Use the committed offline artifacts as the stable reference result.

## Main Result

The reference benchmark reached `20` valid DTH-guided outputs and `20` valid baseline outputs. Blinded judges favored DTH-guided outputs on claim-boundary restraint and overall scientific rigor, while evidence coverage was borderline rather than cleanly significant.

Reference outputs:

```text
results/cumulative_valid_only_summary_for_20each_target.json
results/judge/dth_yes_no_glm52_cloud_blind_summary.json
results/judge/dth_yes_no_gpt54_blind_summary.json
results/judge/dth_yes_no_sonnet46_blind_summary.json
results/dth_yes_no_qwen397b_cloud_methods_results.md
```

Reference figures:

```text
figures/Fig3A_DTH_EvidenceCoverage.svg
figures/Fig3B_DTH_BlindJudgeRigor.svg
figures/FigS3D_DTH_BlindJudgeRigorByJudge.svg
figures/FigS3E_DTH_BlindJudgeWinRate.svg
```

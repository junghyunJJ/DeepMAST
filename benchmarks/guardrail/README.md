# Report Guardrail Benchmark

This bundle archives the SNI-enabled Qwen3.5-122B report-guardrail benchmark used to evaluate report correction and error-dependent output blocking on one breast cancer dataset.

## Reference result

| Outcome | Guardrail ON | Guardrail OFF |
|---|---:|---:|
| Passed predefined checks | 16/20 (80%) | 0/20 (0%) |
| Complete report with detected errors | 2/20 (10%) | 20/20 (100%) |
| Final output blocked | 2/20 (10%) | 0/20 (0%) |

The 20 runs per condition are repeated computational executions of one dataset, not independent biological samples. The result measures compliance with predefined reporting and consistency checks; detected errors include reporting-scope violations and should not all be described as hallucinations.

## What is included

- `results/results_methods_figure_caption.md`: publication-ready Results, Methods, table, and figure caption in one file.
- `results/comparison.{json,csv,md}`: final 40-run comparison.
- `results/assessments/`: final per-run post-hoc verdicts.
- `results/analysis_two_effects/`: correction and blocking analysis with a 40-run audit table.
- `results/table_s1_per_run.csv`: compact supplementary run table.
- `figures/guardrail_effects.{pdf,svg,png}`: publication figure exports.
- `inputs/evidence/`: small source extracts supporting the numerical-repair and blocking panels.
- `scripts/reproduce_offline.sh`: regenerates the figure from committed source data without model or RAG calls.
- `metadata/`: recovery method, verification record, original manifest, and source-path documentation.

The benchmark implementation remains in the repository-level `scripts/` and `tests/` directories. It is not duplicated here.

## Offline figure reproduction

From the repository root:

```bash
bash benchmarks/guardrail/scripts/reproduce_offline.sh
```

This regenerates the PDF, SVG, and 300-dpi PNG under `benchmarks/guardrail/figures/` from `results/figure_source_data.csv`. It requires the repository Python environment and Matplotlib. It performs no report generation, LLM calls, or RAG evaluation.

## Excluded artifacts

The 1.8-GB `work/` directory contains duplicated evaluation workspaces and is intentionally excluded. The 40 final assessments, comparison files, compact per-run table, publication materials, and representative source evidence are retained. The large workspace can be archived separately or added with Git LFS if a later audit requires byte-for-byte reconstruction of every evaluation workspace.

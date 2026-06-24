# Source Paths

This benchmark bundle was assembled from the original PR #45 artifacts without moving or modifying the original benchmark outputs.

Original source directories:

- Retrieval summary:
  `docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_qwen_full_thinkfalse/`
- Retrieval workspaces:
  `docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_qwen_full_thinkfalse_workspaces/`
- Coverage labels and content-utility conversion rows:
  `docs/benchmarks/lr_retrieval_relevance/results/cci_retrieval_skill_only_content_utility_gpt54_live_thinkfalse/`
- Benchmark input cases:
  `docs/benchmarks/cci_skill_ablation/cases/cci_full_cases.json`
- Offline table exporter:
  `scripts/benchmarks/export_coverage_figure_data.py`
- Coverage figure script:
  `docs/benchmarks/lr_retrieval_relevance/coverage_figure.R`

Path normalization:

- `results/converted_runner_rows.jsonl` was rewritten to replace machine-local absolute `trial_workspace` and `papers_path` values with repository-relative paths under `benchmarks/lr_retrieval_relevance/artifacts/workspaces/`.
- The copied trial workspaces include the JSON files required for offline coverage recomputation: `search_context.json`, `benchmark_case.json`, `papers_raw.json`, `papers_filtered.json`, and `citation_candidates.json`.
- `results/retrieval_summary.json` is retained as a raw provenance snapshot and intentionally preserves original local run paths; it is not the normalized offline-reproduction input.

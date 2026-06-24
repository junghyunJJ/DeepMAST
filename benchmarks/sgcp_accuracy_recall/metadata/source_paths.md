# Source Paths

This benchmark bundle was assembled from the local llmwiki_rag promotion benchmark artifacts and DeepMAST writing figures without modifying the original source files.

Original source paths:

- Promotion benchmark artifacts:
  `/Users/jungj2/Dropbox/Metadata/mcp/llmwiki_rag/benchmarking/results/promotion/`
- Promotion benchmark figure script:
  `/Users/jungj2/Dropbox/Metadata/mcp/llmwiki_rag/benchmarking/scripts/plot_sgcp_main_figure.R`
- DeepMAST writing figure outputs:
  `docs/writing/figures/sgcp_accuracy_recall_*`

Path normalization:

- Raw JSONL outputs for `wiki_off`, `wiki_static_refs`, and `wiki_doc_routing` were moved under `benchmarks/sgcp_accuracy_recall/results/raw/`.
- Runner summary JSON files and figure summary CSV files were moved under `benchmarks/sgcp_accuracy_recall/results/`.
- Writing-table CSV files were generated from the committed raw JSONL files to reproduce the manuscript static-reference ablation tables.
- Figure outputs were moved under `benchmarks/sgcp_accuracy_recall/figures/`.
- The plotting script was moved under `benchmarks/sgcp_accuracy_recall/scripts/` and normalized to read/write inside the public bundle.
- Live reruns write to `benchmarks/sgcp_accuracy_recall/live_runs/` instead of overwriting committed reference results.

Files intentionally excluded:

- promotion run logs
- `.badrows-backup*` and `.stale-badrows-backup*`
- pilot and smoke-run JSONL outputs
- `.DS_Store`, `.Rhistory`, and `__pycache__/`

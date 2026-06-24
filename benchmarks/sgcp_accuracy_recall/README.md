# SGCP Accuracy and Recall Benchmark

This bundle contains the reproducible artifacts for the SGCP retrieval accuracy/recall benchmark. The main figure compares `wiki_off` against `wiki_doc_routing`, labeled as `Baseline retrieval` and `SGCP-enabled retrieval`, on the full MultiHop-RAG benchmark with qwen3.5:35b and qwen3.5:122b. The bundle also includes the `wiki_static_refs` ablation used by the manuscript methods/results/discussion.

The primary reproducibility target is offline artifact validation and figure regeneration. The committed raw JSONL outputs are enough to regenerate the summary tables and the main figure without calling local model servers or the llmwiki_rag service. A live rerun wrapper is included separately for audit use.

## What Is Included

- `results/raw/`: six full raw JSONL result files for 35B/122B x baseline/static-reference/SGCP-enabled retrieval.
- `results/multihop_full_summary_*.json`: source runner summaries for the final 35B and 122B full runs.
- `results/sgcp_accuracy_recall_summary.csv`: metric means, confidence intervals, and row counts.
- `results/sgcp_accuracy_recall_tests.csv`: paired significance tests and routing-minus-off deltas.
- `results/sgcp_all_conditions_summary.csv`: writing-table summary for baseline retrieval, static-reference SGCP, and SGCP-enabled retrieval.
- `results/sgcp_static_reference_tests.csv`: paired tests for the static-reference ablation.
- `figures/sgcp_accuracy_recall_main.svg` and `.png`: final accuracy/recall figure.
- `scripts/plot_sgcp_main_figure.R`: regenerate CSV summaries and figures from committed raw JSONL.
- `scripts/reproduce_offline.sh`: validate committed artifacts and optionally rerun the R figure pipeline.
- `scripts/reproduce_live.sh`: optional full live rerun wrapper.

## Quick Start

From the repository root:

```bash
bash benchmarks/sgcp_accuracy_recall/scripts/reproduce_offline.sh
```

This validates the committed raw outputs and regenerates:

```text
benchmarks/sgcp_accuracy_recall/results/sgcp_accuracy_recall_summary.csv
benchmarks/sgcp_accuracy_recall/results/sgcp_accuracy_recall_tests.csv
benchmarks/sgcp_accuracy_recall/results/sgcp_all_conditions_summary.csv
benchmarks/sgcp_accuracy_recall/results/sgcp_static_reference_tests.csv
benchmarks/sgcp_accuracy_recall/figures/sgcp_accuracy_recall_main.svg
benchmarks/sgcp_accuracy_recall/figures/sgcp_accuracy_recall_main.png
```

If R or the plotting packages are not available and you only want to validate the reference artifacts:

```bash
SKIP_R=1 bash benchmarks/sgcp_accuracy_recall/scripts/reproduce_offline.sh
```

The validation path requires only Python standard-library modules. Figure regeneration requires R packages `jsonlite`, `ggplot2`, `scales`, and `cowplot`.

## Optional Live Rerun

The live rerun depends on the separate llmwiki_rag repository and local qwen-compatible model endpoints.

Expected model endpoints:

- `qwen3.5:35b` at `http://host.docker.internal:7000`
- `qwen3.5:122b` at `http://host.docker.internal:6000`

Preview the commands:

```bash
bash benchmarks/sgcp_accuracy_recall/scripts/reproduce_live.sh
```

Run them:

```bash
LLMWIKI_RAG_DIR=/path/to/llmwiki_rag \
  bash benchmarks/sgcp_accuracy_recall/scripts/reproduce_live.sh --run
```

Live outputs are written under `benchmarks/sgcp_accuracy_recall/live_runs/`, which is ignored by git. Live model outputs may vary with server state, package versions, and retrieval/database availability. Use the committed offline artifacts as the stable reference result.

## Main Result

SGCP-enabled retrieval improved both exact-answer accuracy and evidence recall in the full benchmark.

| Model | Metric | Baseline retrieval | SGCP-enabled retrieval | Delta | Test |
| --- | ---: | ---: | ---: | ---: | --- |
| 35B | Exact-answer accuracy | 26.3% | 34.9% | +8.6 pp | P=6.3e-38 |
| 35B | Evidence recall | 15.5% | 25.6% | +10.1 pp | P=1.5e-78 |
| 122B | Exact-answer accuracy | 28.1% | 31.7% | +3.7 pp | P=2.2e-06 |
| 122B | Evidence recall | 19.2% | 25.8% | +6.6 pp | P=1.6e-31 |

The plotted result is:

```text
figures/sgcp_accuracy_recall_main.svg
figures/sgcp_accuracy_recall_main.png
```

Static-reference SGCP is included for writing reproducibility. It reduced no-context failures but did not match SGCP-enabled retrieval on the primary accuracy and evidence-recall endpoints; see `results/sgcp_all_conditions_summary.csv` and `results/sgcp_static_reference_tests.csv`.

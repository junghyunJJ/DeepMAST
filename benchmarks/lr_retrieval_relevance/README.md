# LR Retrieval Relevance Benchmark

This bundle contains the reproducible artifacts for the DeepMAST literature-retrieval skill benchmark used to evaluate whether the biomedical literature search skill improves coverage of case biology before downstream handoff ranking.

The primary reproducibility target is offline artifact regeneration: the committed retrieval outputs, LLM coverage labels, and trial workspaces are enough to regenerate the coverage tables and figure without calling OpenAI, Ollama, PubMed, or BioMCP. A live rerun wrapper is included separately for audit use.

## What Is Included

- `inputs/cci_full_cases.json`: 30 CCI benchmark cases.
- `artifacts/workspaces/`: 120 trial workspaces for skill ON/OFF across qwen3.5:35b and qwen3.5:122b.
- `results/retrieval_summary.csv`: compact retrieval benchmark summary.
- `results/retrieval_summary.json`: raw provenance snapshot from the original run; it intentionally preserves original local run paths and is not used as the normalized offline-reproduction input.
- `results/*coverage_labels_122b.jsonl`: qwen3.5:122b labels for gene, pathway, and cell-type coverage.
- `results/converted_runner_rows.jsonl` and `artifacts/workspaces/`: normalized repo-relative inputs used for offline coverage recomputation.
- `results/coverage_tables/`: committed coverage tables used by the figure.
- `figures/fig_retrieval_coverage.svg` and `.png`: final coverage figure.
- `scripts/reproduce_offline.sh`: regenerate coverage tables and figures from committed artifacts.
- `scripts/reproduce_live.sh`: optional full live rerun wrapper.

## Quick Start

From the repository root:

```bash
bash benchmarks/lr_retrieval_relevance/scripts/reproduce_offline.sh
```

This regenerates:

```text
benchmarks/lr_retrieval_relevance/results/coverage_tables/
benchmarks/lr_retrieval_relevance/figures/
```

The offline path requires Python with `numpy` and `scipy`. Figure regeneration also requires R packages `tidyverse` and `svglite`.

`results/retrieval_summary.json` is retained for audit provenance only. The reproducible offline path uses the normalized `converted_runner_rows.jsonl`, coverage label JSONL files, and copied workspaces under this bundle.

If R is not available and you only want to regenerate the CSV tables:

```bash
SKIP_R=1 bash benchmarks/lr_retrieval_relevance/scripts/reproduce_offline.sh
```

## Optional Live Rerun

The live rerun calls local Ollama-hosted qwen models and, by default, GPT-5.4 for content-utility judging. It is intentionally not run by default.

Expected model endpoints:

- `qwen3.5:35b` at `http://localhost:7000`
- `qwen3.5:122b` at `http://localhost:6000`
- OpenAI API credentials available for `gpt-5.4` if `SCORE_MODE=live`

Preview the commands:

```bash
bash benchmarks/lr_retrieval_relevance/scripts/reproduce_live.sh
```

Run them:

```bash
OPENAI_API_KEY=... bash benchmarks/lr_retrieval_relevance/scripts/reproduce_live.sh --run
```

Live outputs are written under `benchmarks/lr_retrieval_relevance/live_runs/`, which is ignored by git. Live model outputs may vary with server state, package versions, API behavior, and retrieval availability. Use the committed offline artifacts as the stable reference result.

## Main Result

The benchmark conclusion is summarized in:

```text
results/COVERAGE_SUMMARY_KO.md
```

The figure is:

```text
figures/fig_retrieval_coverage.svg
figures/fig_retrieval_coverage.png
```

In brief, the retrieval skill primarily improved biological coverage of case context, especially cell-type coverage, while gene coverage was already near-saturated.

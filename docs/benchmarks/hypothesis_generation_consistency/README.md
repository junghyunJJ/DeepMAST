# Hypothesis Generation Consistency Benchmark

Runs the real DrugTarget `hypothesis_writer` LLM subagent repeatedly on a frozen
IPF evidence workspace and measures output stability.

Default source workspace:

```bash
res_ipf_ollama_tmp
```

Dry run:

```bash
python docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py \
  --source res_ipf_ollama_tmp \
  --runs 10 \
  --dry-run
```

Full 10-run benchmark:

```bash
python docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py \
  --source res_ipf_ollama_tmp \
  --runs 10 \
  --provider "${LLM_PROVIDER:-ollama}" \
  --disease "pulmonary fibrosis"
```

Artifacts are written under `results/` and `workspaces/`; both directories are
local benchmark output and are ignored by git.

## Output Interpretation

`trials.jsonl` contains one JSON object per run:

- `success`: `hypothesis_report.json` exists and is parseable.
- `validation_passed`: completion check passed, the report uses the v2 schema,
  contains at least one hypothesis, includes required `topn_coverage` and
  `prediction_grounding_summary` sections, TOP-N missing is empty, and
  unverified numeric prediction count is zero.
- `report_summary.covered_genes`: union of genes listed in retained hypotheses.
- `report_summary.evidence_refs`: all cited evidence filenames.
- `report_summary.topn_missing`: featured genes missed by the saved report.
- `report_summary.unverified_numeric_predictions`: numeric predictions that are
  not file-grounded.

`benchmark_results.json` contains the aggregate metrics used for consistency
checks.
`benchmark_summary.md` is the short human-readable report.

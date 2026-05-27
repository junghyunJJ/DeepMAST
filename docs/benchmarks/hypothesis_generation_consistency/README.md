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

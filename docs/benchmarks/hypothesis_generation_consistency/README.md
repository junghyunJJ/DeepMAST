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

## Phase-Aware Activation Appropriateness

This benchmark asks whether a `hypothesis_writer` task activates the right skill
for the right evidence phase. It is a controlled activation benchmark, not a
quality benchmark for `evidence/hypothesis_report.json`.

Run a smoke check:

```bash
PYTHONPATH=. python docs/benchmarks/hypothesis_generation_consistency/run_phase_activation_benchmark.py \
  --models qwen3.5:35b \
  --ports 5000 \
  --conditions passive_listing,skill_activator \
  --case-ids stage1_census_expression,stage3_chembl_compounds
```

Run the full local matrix:

```bash
PYTHONPATH=. python docs/benchmarks/hypothesis_generation_consistency/run_phase_activation_benchmark.py \
  --models qwen3.5:35b,qwen3.5:122b \
  --ports 5000,6000,7000 \
  --conditions passive_listing,skill_activator \
  --parallel-ports
```

The recommended full run uses `--parallel-ports`: ports 5000, 6000, and 7000
run concurrently within the same model, but models remain sequential. The runner
unloads the active model from every selected port before switching from 35B to
122B, which reduces wall-clock time without intentionally loading both model
families at once.

Primary interpretation:

- `domain_exact_match_rate` is the main pass signal.
- `domain_precision` and `domain_specificity` detect overactivation.
- `domain_recall` detects missed relevant skills.
- Activating every domain skill is not a good result; it usually has high
  recall but low precision and low specificity.
- `drug-target-hypothesis` activation is tracked separately as core behavior and
  is not included in phase/domain exact-match scoring.

Outputs are written to timestamped directories under:

```text
docs/benchmarks/hypothesis_generation_consistency/results/
```

## Fig3-Style Activation Mechanism Benchmark

This benchmark mirrors the Figure 3 question: does adding `SkillActivator` to
passive skill listing improve skill activation mechanics?

It deliberately does not test `evidence/hypothesis_report.json` quality and it
does not use loaded-evidence/report-writing prompts. The task asks the model to
choose and read the skill guides required before a downstream task.

Run a smoke check:

```bash
PYTHONPATH=. python docs/benchmarks/hypothesis_generation_consistency/run_fig3_activation_benchmark.py \
  --models qwen3.5:35b \
  --ports 5000 \
  --conditions passive_listing,skill_activator \
  --case-ids stage1_census_expression,stage2_gwas_genetic_association,stage3_chembl_compounds
```

Run the full local matrix with model-sequential, port-parallel execution:

```bash
OUT="docs/benchmarks/hypothesis_generation_consistency/results/fig3_activation_full_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT"

PYTHONPATH=. python docs/benchmarks/hypothesis_generation_consistency/run_fig3_activation_benchmark.py \
  --models qwen3.5:35b,qwen3.5:122b \
  --ports 5000,6000,7000 \
  --conditions passive_listing,skill_activator \
  --parallel-ports \
  --output-root "$OUT" \
  2>&1 | tee "$OUT/run.log"

PYTHONPATH=. python docs/benchmarks/hypothesis_generation_consistency/analyze_fig3_activation_results.py \
  "$OUT/benchmark_results.json" \
  --output "$OUT/fig3_activation_analysis.md"
```

Stop-condition checks:

- `trials == 120`
- `errors == 0`
- `ports == [5000, 6000, 7000]`
- each model-condition group has 30 trials
- `unload_ok == True`

Interpretation:

- This benchmark supports claims about activation mechanics.
- The phase-aware benchmark supports claims about production-proxy behavior.
- Neither benchmark alone proves improvement in `hypothesis_report.json` quality.

## 35B Wait-For-Completion Quality Benchmark

The selective activation benchmark stops after `activation_trace.json` and is
therefore not a final report quality benchmark. To test whether improved skill
activation also improves completed `hypothesis_report.json` quality, run a
35B-only completion matrix:

```bash
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="docs/benchmarks/hypothesis_generation_consistency/results/selective8_wait35_completion_${STAMP}"
WORK="docs/benchmarks/hypothesis_generation_consistency/workspaces/selective8_wait35_completion_${STAMP}"
mkdir -p "$OUT" "$WORK"

PYTHONPATH=. python docs/benchmarks/hypothesis_generation_consistency/run_governor_production_activation_matrix.py \
  --source "/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/docs/benchmarks/tmp/res_ipf_drugtarget_tmp" \
  --output-root "$OUT" \
  --workspace-root "$WORK" \
  --disease "pulmonary fibrosis" \
  --hypothesis-skill-set selective8 \
  --models qwen3.5:35b \
  --ports 5000,6000,7000 \
  --modes middleware_only,middleware_plus_activator,middleware_plus_governor \
  --wait-for-completion \
  --timeout-minutes 120 \
  --force \
  2>&1 | tee "$OUT/run.log"

PYTHONPATH=. python docs/benchmarks/hypothesis_generation_consistency/analyze_wait_completion_quality.py \
  "$OUT/benchmark_results.json"
```

Expected stop-condition checks:

- `benchmark_results.json` exists.
- `trials.jsonl` has 9 lines.
- `models == ["qwen3.5:35b"]`.
- `modes == ["middleware_only", "middleware_plus_activator", "middleware_plus_governor"]`.
- `ports == [5000, 6000, 7000]`.
- Completion benchmark rows should not use `completion_mode == "activation_trace_checkpoint"` unless a trial failed before normal completion.
- Quality interpretation should use `wait_completion_quality.md`, not `benchmark_summary.md` alone.

## Breast Cancer Selective8 120-Run Rerun

Use this matrix for the full breast-cancer selective8 rerun after Stage 1/2/3
artifacts exist under `res_bc_drugtarget/`. The dry-run must pass before the
full benchmark starts.

```bash
PYTHONPATH=. python docs/benchmarks/hypothesis_generation_consistency/run_governor_production_activation_matrix.py \
  --source /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res_bc_drugtarget \
  --disease "breast cancer" \
  --models qwen3.5:35b,qwen3.5:122b \
  --modes middleware_only,middleware_plus_activator,middleware_plus_governor \
  --ports 5000,6000,7000 \
  --repeats-per-condition 20 \
  --timeout-minutes 60 \
  --wait-for-completion \
  --hypothesis-skill-set selective8 \
  --dry-run
```

Expected dry-run success:

```text
"trial_count": 120
"hypothesis_scope_errors": []
```

If Stage 1 output is still incomplete, dry-run exits nonzero and reports the
missing `stage1_filter_results.json` or `.csv` preflight error.

Full run:

```bash
STAMP=bc_selective8_wait_completion_$(date +%Y%m%d_%H%M%S)
PYTHONPATH=. python docs/benchmarks/hypothesis_generation_consistency/run_governor_production_activation_matrix.py \
  --source /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res_bc_drugtarget \
  --output-root docs/benchmarks/hypothesis_generation_consistency/results/${STAMP} \
  --workspace-root docs/benchmarks/hypothesis_generation_consistency/workspaces/${STAMP} \
  --disease "breast cancer" \
  --models qwen3.5:35b,qwen3.5:122b \
  --modes middleware_only,middleware_plus_activator,middleware_plus_governor \
  --ports 5000,6000,7000 \
  --repeats-per-condition 20 \
  --timeout-minutes 60 \
  --wait-for-completion \
  --hypothesis-skill-set selective8
```

Resume the same run after interruption:

```bash
PYTHONPATH=. python docs/benchmarks/hypothesis_generation_consistency/run_governor_production_activation_matrix.py \
  --source /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res_bc_drugtarget \
  --output-root docs/benchmarks/hypothesis_generation_consistency/results/${STAMP} \
  --workspace-root docs/benchmarks/hypothesis_generation_consistency/workspaces/${STAMP} \
  --disease "breast cancer" \
  --models qwen3.5:35b,qwen3.5:122b \
  --modes middleware_only,middleware_plus_activator,middleware_plus_governor \
  --ports 5000,6000,7000 \
  --repeats-per-condition 20 \
  --timeout-minutes 60 \
  --wait-for-completion \
  --hypothesis-skill-set selective8 \
  --resume
```

Add `--rerun-failed` only when timeout/error/validation-failed rows should be
regenerated.

Post-run analysis:

```bash
PYTHONPATH=. python docs/benchmarks/hypothesis_generation_consistency/analyze_wait_completion_quality.py \
  docs/benchmarks/hypothesis_generation_consistency/results/${STAMP}/benchmark_results.json

PYTHONPATH=. python docs/benchmarks/hypothesis_generation_consistency/analyze_selective_activation_traces.py \
  docs/benchmarks/hypothesis_generation_consistency/results/${STAMP}/benchmark_results.json

PYTHONPATH=. python docs/benchmarks/hypothesis_generation_consistency/score_skill_grounded_end_to_end.py \
  docs/benchmarks/hypothesis_generation_consistency/results/${STAMP}
```

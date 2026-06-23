# DTH YES/NO contrast reproducibility bundle

This bundle preserves the DTH contrast setup and provides a direct rerun entrypoint.

## What is preserved

- `files/`: snapshot of the current skill, prompt, runner, retry, and validator files needed for DTH contrast runs.
- `current_dth_contrast.patch`: patch for applying the current tracked-file diff to another checkout.
- `LAST_USED_CONDITIONS.json`: recommended small-model condition definitions plus legacy result conditions.
- `result_refs/`: text manifest of recent local result directory names:
  - `openrouter_qwen397b_dth_yes_rep002_rerun_20260619_015830`
  - `gpt54mini_dth_skill_v110_2each_20260619_025530`
  - `qwen35b122b_dth_skill_v110_3each_3port_20260619_032350`

## Condition contract

Use these two conditions when the goal is to isolate whether DTH was loaded:

| Condition | Skill set | Prompt mode |
| --- | --- | --- |
| DTH NO | `dth_none` | `operational_contract_minimal` |
| DTH YES | `dth_only` | `operational_contract_minimal_plus_dth` |

Both conditions use `middleware_only`, host fallback off, native retry on, and ports `5000,6000,7000`.

The older result directories used `operational_contract_only` and
`operational_contract_plus_dth`. Those modes are still available for legacy
reproduction, but the recommended 35B/122B follow-up tests should use the
minimal pair above so the base prompt stays thin and DTH interpretation lives in
the skill.

## Immediate rerun

From the repository root:

```bash
bash docs/benchmarks/hypothesis_generation_consistency/repro/dth_yes_no_contrast_20260619/run_qwen_dth_yes_no_3port.sh qwen3.5:35b 3
```

For 122B:

```bash
bash docs/benchmarks/hypothesis_generation_consistency/repro/dth_yes_no_contrast_20260619/run_qwen_dth_yes_no_3port.sh qwen3.5:122b 3
```

The script:

- loads `.env` if present;
- sets native hypothesis retry env vars;
- verifies the source data and prompt-mode choices;
- unloads `qwen3.5:35b`, `qwen3.5:122b`, and the requested model from ports `5000,6000,7000`;
- runs DTH NO first, then DTH YES;
- writes per-condition dry-run payloads, `benchmark_results.json`, `runner_state.json`, and a top-level `dth_yes_no_reuse_summary.json`;
- unloads the requested model at the end.

To rerun the legacy conditions instead:

```bash
DTH_NO_PROMPT_MODE=operational_contract_only \
DTH_YES_PROMPT_MODE=operational_contract_plus_dth \
bash docs/benchmarks/hypothesis_generation_consistency/repro/dth_yes_no_contrast_20260619/run_qwen_dth_yes_no_3port.sh qwen3.5:35b 3
```

Outputs are written under:

```text
docs/benchmarks/hypothesis_generation_consistency/results/dth_yes_no_reuse_<model>_<repeats>each_<timestamp>/
docs/benchmarks/hypothesis_generation_consistency/workspaces/dth_yes_no_reuse_<model>_<repeats>each_<timestamp>/
```

## Resume a partial rerun

If a run stops, resume each condition directory directly:

```bash
STAMP="dth_yes_no_reuse_qwen3.5_35b_3each_YYYYMMDD_HHMMSS"
SOURCE="/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res_bc_drugtarget"

python docs/benchmarks/hypothesis_generation_consistency/run_governor_production_activation_matrix.py \
  --source "$SOURCE" \
  --output-root "docs/benchmarks/hypothesis_generation_consistency/results/${STAMP}/DTH_no" \
  --workspace-root "docs/benchmarks/hypothesis_generation_consistency/workspaces/${STAMP}/DTH_no" \
  --disease "breast cancer" \
  --models qwen3.5:35b \
  --ports 5000,6000,7000 \
  --modes middleware_only \
  --repeats-per-condition 3 \
  --hypothesis-skill-set dth_none \
  --hypothesis-writer-prompt-mode operational_contract_minimal \
  --host-hypothesis-fallback off \
  --timeout-minutes 120 \
  --wait-for-completion \
  --resume \
  --rerun-failed
```

For DTH YES, change the output/workspace suffix to `DTH_yes`, `--hypothesis-skill-set` to `dth_only`, and `--hypothesis-writer-prompt-mode` to `operational_contract_minimal_plus_dth`.

## Apply to another checkout

From another clean checkout of the same branch:

```bash
git apply docs/benchmarks/hypothesis_generation_consistency/repro/dth_yes_no_contrast_20260619/current_dth_contrast.patch
```

Then run the script above. If the patch no longer applies, use `files/` as the reference snapshot and manually port only the DTH contrast changes.

## Minimum files that must remain aligned

- `skills/drug-target-hypothesis/SKILL.md`
- `skills/drug-target-hypothesis/evals/evals.json`
- `src/agents/drug_target/subagents/prompts.py`
- `docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py`
- `docs/benchmarks/hypothesis_generation_consistency/run_activation_matrix.py`
- `docs/benchmarks/hypothesis_generation_consistency/run_governor_production_activation_matrix.py`
- `scripts/run_drug_target_traced.py`
- `src/agents/drug_target/tools/hypothesis_grounding.py`
- `src/agents/drug_target/tools/hypothesis_schema.py`
- `src/agents/drug_target/tools/evidence_loader.py`
- `src/agents/drug_target/hypothesis_retry.py`
- `src/agents/drug_target/middleware.py`
- `src/agents/drug_target/super_graph.py`

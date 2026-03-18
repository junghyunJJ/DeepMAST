# DrugTarget Skill Exposure A/B Benchmark

This benchmark package compares two strategy-layer conditions while keeping the
tool surface fixed to `read_skill_file`:

- `A_tools_only`: empty skill exposure
- `B_tools_plus_skills`: exposed benchmark-relevant SKILL.md documents

The package is split into two studies:

- `benchmark_stage2_synthesis.py`
  Main benchmark for `OpenTargets + GWAS` evidence synthesis using frozen Stage 2-style cases.
- `benchmark_chembl_micro.py`
  Supplementary `ChEMBL` micro-benchmark for activity/mechanism/clinical-evidence interpretation.

## Frozen Cases

Cases live under `cases/`:

- `stage2_synthesis_cases.json`
  10 single-gene cases combining real-fixture-derived summaries and curated perturbations.
- `chembl_micro_cases.json`
  4 supplementary ChEMBL-only interpretation cases.

Each case stores:

- frozen evidence summary
- gold scores
- expected classification / priority
- judge focus areas
- rationale anchors used by deterministic coverage scoring

## Running

Main benchmark:

```bash
python docs/benchmarks/drugtarget_skill_ablation/benchmark_stage2_synthesis.py
```

Supplementary ChEMBL benchmark:

```bash
python docs/benchmarks/drugtarget_skill_ablation/benchmark_chembl_micro.py
```

Optional environment variables:

- `DRUGTARGET_BENCHMARK_MODELS`
  Comma-separated subset of default labels. Supported labels: `gpt-4.1-mini`, `qwen3.5:35b`
- `DRUGTARGET_BENCHMARK_REPEATS`
  Override repeat count for the selected models

Artifacts are written to `results/`.

Legacy artifacts:

- `*_trials.jsonl`
- `*_summary.json`
- `*_judgments.jsonl`
- `*_results.md`

Research-grade judge artifacts:

- `*_research_judges.jsonl`
- `*_research_panel_summary.json`
- `*_human_audit_queue.jsonl`
- `*_human_audit_template.csv`
- `*_human_audit_summary.json`
- `*_research_results.md`

Additional environment variables:

- `DRUGTARGET_BENCHMARK_JUDGE_MODELS`
  Comma-separated `provider:model` judge panel override. Must contain exactly 3 independent judge models.
- `DRUGTARGET_BENCHMARK_HUMAN_AUDIT_SAMPLE_RATE`
  Stratified sampling rate for unanimous panel decisions retained for manual review. Default: `0.2`
- `DRUGTARGET_BENCHMARK_HUMAN_AUDIT_RESULTS`
  Optional CSV path containing completed human audit verdicts to merge into the research summary.

## Notes

- The benchmark is offline with frozen case inputs. It does not call live external databases.
- The main claim is limited to Stage 2 evidence synthesis.
- ChEMBL is intentionally reported as a supplementary benchmark so the main Stage 2 claim remains clean.
- The deterministic rubric remains the primary endpoint; the research-grade blind judge is a secondary evaluation layer.

# DrugTarget Skill Exposure A/B Benchmark

This benchmark package compares two strategy-layer conditions while keeping the
tool surface fixed to `read_skill_file`:

- `A_tools_only`: empty skill exposure
- `B_tools_plus_skills`: exposed benchmark-relevant SKILL.md documents

The package is split into three studies:

- `benchmark_stage2_synthesis.py`
  Legacy whole-output benchmark for `OpenTargets + GWAS` Stage 2 synthesis.
- `benchmark_stage2_interpretation_v2.py`
  Earlier interpretation benchmark for whether exposed SKILL.md guidance improves interpretation and evidence synthesis on frozen Stage 2 cases.
- `benchmark_stage2_interpretation_v3.py`
  Earlier error-focused benchmark for whether case-matched SKILL.md excerpts reduce predefined interpretation errors on frozen Stage 2 cases.
- `benchmark_stage2_interpretation_v4.py`
  Phase 1 primary rule-application benchmark for whether distilled skill rules reduce predefined interpretation errors on frozen Stage 2 cases.
- `benchmark_chembl_micro.py`
  Supplementary `ChEMBL` micro-benchmark for activity/mechanism/clinical-evidence interpretation.

## Frozen Cases

Cases live under `cases/`:

- `stage2_synthesis_cases.json`
  14 single-gene cases combining real-fixture-derived summaries and curated perturbations for the legacy whole-output benchmark.
- `stage2_interpretation_v2_cases.json`
  Overlay case pack for the primary V2 benchmark. Each case reuses a frozen Stage 2 evidence bundle, but supervision is narrowed to interpretation-sensitive decisions. The current V2 pack contains 14 cases.
- `stage2_interpretation_v3_cases.json`
  A generated overlay case pack used by the V3 runner. Each case reuses the same 14 frozen Stage 2 bundles but is rewritten into exactly three targeted probes plus one secondary conclusion.
- `skill_excerpt_library.json`
  Default excerpt library for V3. When the checked-in file is absent, the benchmark falls back to the version-controlled in-code default library built from Open Targets and GWAS skill guidance.
- `stage2_interpretation_v4_cases.json`
  Checked-in V4 overlay case pack. The Phase 1 V4 set is frozen to 12 hard ambiguity/conflict cases and contains exactly three probes plus one secondary conclusion per case.
- `skill_rule_library.json`
  Checked-in V4 rule library. Each rule is a distilled interpretation policy with stable provenance back to Open Targets or GWAS skill guidance.
- `chembl_micro_cases.json`
  4 supplementary ChEMBL-only interpretation cases.

V1 and ChEMBL cases store:

- frozen evidence summary
- gold scores
- expected classification / priority
- judge focus areas
- rationale anchors used by deterministic coverage scoring

V2 cases store:

- a `base_case_id` pointing at the frozen Stage 2 bundle
- targeted `interpretation_checks`
- gold labels for each check
- required evidence anchors
- disallowed overclaim labels
- an overall conclusion call and an uncertainty call
- case rationale explaining why the bundle is interpretation-sensitive

V2 primary endpoint:

- `interpretation_score`
  an equal-weight composite of:
  - targeted interpretation-check accuracy
  - overall evidence-synthesis conclusion correctness
  - uncertainty calibration correctness

V3 primary endpoint:

- `weighted_probe_error_score`
  a weighted error metric over exactly three probes:
  - `P1` primary high-risk interpretation error, weight `0.60`
  - `P2` secondary interpretation error, weight `0.25`
  - `P3` restraint/uncertainty error, weight `0.15`
  Lower is better. Case-level paired deltas are reported as `A - B`, so positive values indicate that skill excerpts reduced interpretation error.

V4 primary endpoint:

- `weighted_target_error_score`
  a weighted deterministic error metric over exactly three probes:
  - `P1` primary high-risk interpretation error, weight `0.60`
  - `P2` secondary interpretation error, weight `0.25`
  - `P3` restraint/uncertainty error, weight `0.15`
  Lower is better. Case-level paired deltas are reported as `A - B`, so positive values indicate that distilled rules reduced interpretation error.

## Running

Legacy Stage 2 benchmark:

```bash
python docs/benchmarks/drugtarget_skill_ablation/benchmark_stage2_synthesis.py
```

Primary V2 interpretation benchmark:

```bash
python docs/benchmarks/drugtarget_skill_ablation/benchmark_stage2_interpretation_v2.py
```

Primary V3 interpretation benchmark:

```bash
python docs/benchmarks/drugtarget_skill_ablation/benchmark_stage2_interpretation_v3.py
```

Primary V4 interpretation benchmark:

```bash
python docs/benchmarks/drugtarget_skill_ablation/benchmark_stage2_interpretation_v4.py
```

V3 temperature sweep:

```bash
python docs/benchmarks/drugtarget_skill_ablation/benchmark_stage2_interpretation_v3_sweep.py \
  --temperatures 0.0,0.2,0.3,0.4 \
  --repeats 5 \
  --include-judge false
```

V3 judge-only re-evaluation from existing trials:

```bash
python docs/benchmarks/drugtarget_skill_ablation/benchmark_stage2_interpretation_v3_rejudge.py \
  --trials docs/benchmarks/drugtarget_skill_ablation/results/<stem>_trials.jsonl \
  --stem <new_rejudge_stem>
```

To avoid overwriting prior results, pass a custom stem:

```bash
python docs/benchmarks/drugtarget_skill_ablation/benchmark_stage2_interpretation_v2.py \
  --stem stage2_interpretation_v2_qwen35_122b_14case_smoke
```

Supplementary ChEMBL benchmark:

```bash
python docs/benchmarks/drugtarget_skill_ablation/benchmark_chembl_micro.py
```

Optional environment variables:

- `DRUGTARGET_BENCHMARK_MODELS`
  Comma-separated subset of default labels or explicit `provider:model` entries. Default labels: `gpt-4.1-mini`, `qwen3.5:35b`
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
- V1 is a legacy whole-output benchmark and should be treated as supplementary once V2 is available.
- V2 and V3 remain available for comparison, but V4 is the Phase 1 primary claim surface for rule-application effects.
- V3 injects only case-matched Open Targets / GWAS excerpts instead of full skill documents.
- V4 injects only case-matched distilled rules and defaults to deterministic-only evaluation in Phase 1.
- ChEMBL is intentionally reported as a supplementary benchmark so the main Stage 2 claim remains clean.
- The deterministic rubric remains the primary endpoint; the research-grade blind judge is a secondary evaluation layer.

## Claim Boundary

The strongest current Phase 1 claim this package is designed to support is:

`Distilled skill rules reduce predefined interpretation errors on frozen Stage 2 DrugTarget cases under the V4 rubric.`

The package is not designed to prove:

- general end-to-end DrugTarget superiority
- better external database recall
- better writing quality
- universal gains on every Stage 2 output field

## Threats To Validity

- V2, V3, and V4 are intentionally narrower than V1. They are aligned to interpretation-sensitive decisions, not all Stage 2 behavior.
- The benchmark must not reward parroting SKILL.md phrasing. V2/V3 labels and anchors and V4 rules are grounded in the frozen evidence bundles, not in copied case-specific wording.
- Strong generator models may already solve some cases without skills, which can shrink the measured lift.
- Blind judging remains secondary because winner/tie aggregation can still hide small but real targeted gains.

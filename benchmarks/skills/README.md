# Skills Benchmark

This bundle contains the reproducible artifacts for the DeepMAST skill-activation benchmark. The benchmark compares passive skill listing against the SkillActivator / historical SkillLoadHarness protocol for deciding when to load database skill guides.

The primary main-text reproducibility target is the committed qwen3.5:122b reference artifact set. A qwen3.5:35b live scaling check is also included as a supplementary artifact because it did not pass the statistical gate for replacing the main Figure 2a result. A live rerun wrapper is included for audit use when a matching local Ollama endpoint is available.

## What Is Included

- `scripts/benchmark_skill_harness.py`: core prompt variants, trial runner, and metrics.
- `scripts/compare_expanded.py`: final expanded comparison runner for qwen3.5:122b and qwen3.5:35b.
- `results/compare_expanded_qwen3_5_122b.json`: aggregate reference metrics.
- `results/compare_expanded_qwen3_5_122b_stats.json`: McNemar/bootstrap statistics.
- `results/compare_expanded_qwen3_5_122b_trials.jsonl`: per-trial reference rows.
- `results/skill_load_harness_benchmark_122b.md`: frozen benchmark report.
- `results/compare_expanded_qwen3_5_35b.json`: aggregate 35B scaling-check metrics.
- `results/compare_expanded_qwen3_5_35b_stats.json`: 35B McNemar/bootstrap statistics.
- `results/compare_expanded_qwen3_5_35b_trials.jsonl`: per-trial 35B rows.
- `results/skill_load_harness_benchmark_35b.md`: 35B scaling-check report.
- `figures/`: reference figures and Mermaid figure sources.
- `metadata/source_paths.md`: source locations used to assemble this bundle.

## Quick Start

From the repository root:

```bash
bash benchmarks/skills/scripts/reproduce_offline.sh
```

This validates the committed qwen3.5:122b and qwen3.5:35b artifacts and regenerates `figures/fig3.svg` from the qwen3.5:122b main-reference result if R is available.

If you only want the Python validation:

```bash
SKIP_R=1 bash benchmarks/skills/scripts/reproduce_offline.sh
```

The offline validation checks:

- 280 trial rows.
- 420 paired skill decisions.
- aggregate and statistical F1 values are present and bounded in [0, 1].
- reference markdown report is present.

## Optional Live Rerun

Preview the live command:

```bash
bash benchmarks/skills/scripts/reproduce_live.sh
```

Run it:

```bash
OLLAMA_BASE_URL=http://localhost:7000 \
SCALING_MODEL=qwen3.5:35b \
  bash benchmarks/skills/scripts/reproduce_live.sh --run
```

Live outputs are written under:

```text
benchmarks/skills/live_runs/<RUN_ID>/results/
```

Live results may vary with model server state, package versions, and decoding behavior. Use the committed offline artifacts as the stable reference result.

## Main Result

The final qwen3.5:122b run compares:

- `A_passive`: passive skills middleware listing.
- `B_NO_hints`: SkillActivator protocol without stage hints.

Reference result:

```text
F1: 81.7% -> 93.9% (+12.2%p)
Recall: 70.8% -> 90.0% (+19.2%p)
McNemar exact p = 0.000003
Bootstrap 95% CI for dF1 = [+0.0582, +0.1974]
```

## 35B Scaling Check

The qwen3.5:35b run was retained as a supplementary scaling check, not as the main Figure 2a result.

```text
Aggregate F1: 60.5% -> 60.3% (-0.3%p)
Aggregate recall: 49.4% -> 48.9% (-0.6%p)
Paired target-skill F1: 79.4% -> 82.9% (+3.5%p)
McNemar exact p = 0.417692
Bootstrap 95% CI for paired dF1 = [-0.0739, +0.1506]
```

Because the paired target-skill improvement was not significant and the aggregate metrics did not improve, the main manuscript should retain the qwen3.5:122b SkillActivator result and cite the 35B run only as a supplementary down-scaling check.

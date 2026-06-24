# SkillLoadHarness Benchmark: A_passive vs B_SkillLoadHarness (qwen3.5:35b)

> **Naming note:** The historical condition name `B_SkillLoadHarness` corresponds to the current `SkillActivator` protocol. Filenames retain the older benchmark naming for provenance.

## Summary

This live scaling run evaluated whether the SkillActivator protocol improved skill-loading decisions for the 35B model setting used elsewhere in the main benchmark suite.

- **Model**: qwen3.5:35b
- **Ollama endpoint**: `http://localhost:7000`
- **Run directory**: `benchmarks/skills/live_runs/skills_35b_bounded_20260608T215223Z/results`
- **Conditions**: `A_passive` vs `B_NO_hints`
- **Prompt set**: 7 categories x 20 prompts/category
- **Trial rows**: 280
- **Paired target-skill decisions**: 420
- **Runtime errors**: 0

## Main-Figure Decision

This run should **not** replace the qwen3.5:122b result as the main Figure 2a benchmark.

Although paired target-skill F1 increased numerically from 79.4% to 82.9%, the effect was not statistically significant:

- McNemar exact p = 0.417692
- Bootstrap 95% CI for paired F1 difference = [-0.0739, +0.1506]
- Bootstrap p = 0.286400
- Cohen's h = 0.0904

The 35B result is therefore best used as a supplementary scaling check rather than a main-panel result.

## Aggregate Skill-Activation Metrics

The aggregate metrics saved in `compare_expanded_qwen3_5_35b.json` account for all activated skill names, including extra non-target database skills when the model over-activated.

```text
Metric              A_passive   B_NO_hints   Delta
Activation rate       55.0%       57.5%      +2.5 pp
False positive rate    5.0%        0.0%      -5.0 pp
Precision             78.1%       78.6%      +0.5 pp
Recall                49.4%       48.9%      -0.6 pp
Specificity           96.2%       96.4%      +0.2 pp
F1                    60.5%       60.3%      -0.3 pp
Average latency       15.36 s     19.22 s    +3.86 s
```

## Paired Target-Skill Statistical Metrics

The statistical artifact `compare_expanded_qwen3_5_35b_stats.json` evaluates the paired binary decisions for the three benchmarked Stage 2/3 target skills: OpenTargets, GWAS, and ChEMBL.

```text
Paired decisions: 420
A correct: 379/420 (90.2%)
B correct: 385/420 (91.7%)
Paired F1: 79.4% -> 82.9% (+3.5 pp)
McNemar exact p: 0.417692
Bootstrap 95% CI: [-0.0739, +0.1506]
```

## Reproduction

```bash
OLLAMA_BASE_URL=http://localhost:7000 \
SCALING_MODEL=qwen3.5:35b \
bash benchmarks/skills/scripts/reproduce_live.sh --run
```

The 35B preset uses bounded generation (`num_predict=512`, `reasoning=False`) to prevent long natural-language continuations during a tool-decision benchmark.

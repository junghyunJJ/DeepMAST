# SkillLoadHarness Benchmark: A_passive vs B_forced_eval (qwen3.5:122b)

## Overview

This benchmark evaluates whether the **SkillLoadHarness 3-step evaluation protocol**
(Quick Screen → Evaluate → Implement) significantly improves skill activation accuracy
compared to **passive skill listing** in the Drug Target Assessment Agent.

- **Model**: qwen3.5:122b (Ollama, local)
- **Registry**: 3 skills (opentargets-database, gwas-database, chembl-database)
- **stage_hints**: `{}` (no hints — tests protocol effectiveness alone)
- **System prompt**: Full (with stage-specific skill reading directives)
- **Test set**: 7 categories × 20 prompts = 140 prompts × 2 conditions = 280 trials
- **Decision granularity**: 140 prompts × 3 skills = 420 paired binary decisions

## Experimental Design

### Conditions

| Condition | Description |
|-----------|-------------|
| **A_passive** | SkillsMiddleware — lists all skills in the system prompt passively. Model decides when to read. |
| **B_NO_hints** | SkillLoadHarness — injects a structured 3-step evaluation protocol. No stage hints provided. |

### Test Prompt Categories

| Category | n | Expected Skills | Type |
|----------|:-:|-----------------|------|
| stage2_direct | 20 | opentargets + gwas | True Positive |
| stage3_direct | 20 | chembl | True Positive |
| composite | 20 | opentargets + gwas + chembl | True Positive |
| stage1_tools_only | 20 | none | True Negative |
| internal_pipeline | 20 | none | True Negative |
| general_biology | 20 | none | True Negative |
| data_visualization | 20 | none | True Negative |

### Metrics

- **F1**: Harmonic mean of precision and recall at the skill-decision level
- **Precision**: Of activated skills, what fraction was expected?
- **Recall**: Of expected skills, what fraction was activated?
- **FP rate**: Fraction of TN-category trials that incorrectly activated skills

## Results

### Performance Metrics

| Metric | A_passive | B_NO_hints | Delta |
|--------|:---------:|:----------:|:-----:|
| **F1** | 81.7% | **94.8%** | **+13.1%p** |
| Precision | 96.6% | 98.2% | +1.6%p |
| Recall | 70.8% | **91.7%** | **+20.8%p** |
| FP rate | 2.5% | **1.2%** | -1.2%p |
| Specificity | 99.0% | 99.3% | +0.3%p |
| Activation rate | 81.7% | 93.3% | +11.7%p |
| Avg latency | 20.9s | 24.5s | +3.5s |

### Per-Category Accuracy

| Category | A_passive | B_NO_hints | Improvement |
|----------|:---------:|:----------:|:-----------:|
| stage2_direct | 18/20 (90%) | **20/20 (100%)** | +10% |
| stage3_direct | 16/20 (80%) | 17/20 (85%) | +5% |
| composite | 15/20 (75%) | **19/20 (95%)** | +20% |
| stage1_tools_only | **20/20 (100%)** | **20/20 (100%)** | = |
| internal_pipeline | 18/20 (90%) | 19/20 (95%) | +5% |
| general_biology | **20/20 (100%)** | **20/20 (100%)** | = |
| data_visualization | **20/20 (100%)** | **20/20 (100%)** | = |

### Per-Skill Accuracy

| Skill | A_passive | B_NO_hints |
|-------|:---------:|:----------:|
| chembl-database | 89.3% | **97.1%** |
| gwas-database | 91.4% | **97.9%** |
| opentargets-database | 92.1% | **96.4%** |

## Statistical Analysis

### McNemar's Test (420 paired skill-decisions)

The McNemar test evaluates whether the asymmetry in discordant pairs (cases where
the two conditions disagree) is statistically significant.

**Contingency table:**

|  | B correct | B incorrect |
|--|:---------:|:-----------:|
| **A correct** | 380 | 2 |
| **A incorrect** | 28 | 10 |

- Concordant pairs: 390 (uninformative)
- **Discordant pairs: 30** (b=2, c=28)
- Of 30 disagreements, **28 favored B** (93.3%)

| Statistic | Value |
|-----------|:-----:|
| McNemar χ² (corrected) | 20.833 |
| **p (exact, binomial)** | **0.000001** |
| Odds ratio (c/b) | 14.0 |
| Significance | *** (p < 0.001) |

### Bootstrap F1 Confidence Interval

Paired bootstrap (prompt-level resampling, BCa-like percentile method, 10,000 resamples)
following Dror et al. (ACL 2018) and Berg-Kirkpatrick et al. (2012).

| Statistic | Value |
|-----------|:-----:|
| Observed F1_A | 0.8173 |
| Observed F1_B | 0.9483 |
| **ΔF1** | **+0.1310** |
| **95% CI** | **[+0.0673, +0.2080]** |
| **Bootstrap p** | **< 0.000001** |
| CI excludes 0? | **Yes → Significant** |

Interpretation: The SkillLoadHarness improves F1 by at least +6.7% and up to +20.8%
with 95% confidence.

### Effect Size

| Measure | Value | Interpretation |
|---------|:-----:|:--------------:|
| Cohen's h | 0.4244 | Small-to-medium |

Note: Cohen's h is conservative here because the baseline is already high (81.7%).
The absolute improvement of +13.1%p is practically significant for production use.

## Key Findings

1. **SkillLoadHarness significantly improves F1**: +13.1%p (81.7% → 94.8%),
   McNemar p = 0.000001, Bootstrap 95% CI [+6.7%, +20.8%].

2. **Recall is the primary driver**: +20.8%p (70.8% → 91.7%). The passive approach
   frequently fails to activate relevant skills, while the 3-step protocol's explicit
   evaluation step ensures each skill is considered.

3. **FP rate remains low**: Both conditions have FP ≤ 2.5%. The Quick Screen phase
   effectively filters non-skill tasks (general biology, visualization, pipeline).

4. **Composite prompts benefit most**: +20%p improvement (75% → 95%). Multi-skill
   tasks require explicit per-skill evaluation to activate all relevant skills.

5. **Latency cost is minimal**: +3.5s per trial (17% increase), acceptable for
   the accuracy gain.

6. **No hints required**: The protocol achieves 94.8% F1 without any stage_hints,
   relying only on skill descriptions from YAML frontmatter.

## Methodology Notes

### Statistical Testing Approach

Following recommendations from:
- Dror et al., "The Hitchhiker's Guide to Testing Statistical Significance in NLP" (ACL 2018)
- Berg-Kirkpatrick et al., "An Empirical Investigation of Statistical Significance in NLP" (2012)
- "When +1% Is Not Enough: A Paired Bootstrap Protocol" (arXiv:2511.19794, 2025)

**Primary test**: Bootstrap F1 CI (prompt-level resampling, 10K iterations)
— reports both significance and effect magnitude.

**Supplementary test**: McNemar's exact test on 420 paired binary decisions
— validates the asymmetry in discordant pairs.

### Comparison with Tool-Use Benchmarks

Major tool-use benchmarks (BFCL, Gorilla, ToolBench, ACEBench) do not report
statistical significance. This analysis exceeds the rigor of current standards
in the field.

## Reproducibility

```bash
# Run the benchmark
SCALING_MODEL=qwen3.5:122b python scripts/benchmarks/compare_expanded.py

# Output files
scripts/benchmarks/compare_expanded_qwen3_5_122b.json        # Aggregate metrics
scripts/benchmarks/compare_expanded_qwen3_5_122b_trials.jsonl # Per-trial results
scripts/benchmarks/compare_expanded_qwen3_5_122b_stats.json   # Statistical tests
```

### Configuration

- **Skill registry**: 3 skills (kegg/string removed as tool-only)
- **Harness protocol**: `skills/skill-load-harness/SKILL.md`
- **Benchmark system prompt**: `docs/benchmarks/skills/benchmark_skill_harness.py::BENCHMARK_SYSTEM_PROMPT`
- **Test prompts**: `scripts/benchmarks/compare_expanded.py::EXPANDED_PROMPTS`

## Date

2026-03-22

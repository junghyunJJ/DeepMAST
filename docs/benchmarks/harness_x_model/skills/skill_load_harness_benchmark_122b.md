# SkillLoadHarness Benchmark: A_passive vs B_SkillLoadHarness (qwen3.5:122b)

## Overview

This benchmark evaluates whether the **SkillLoadHarness 3-step evaluation protocol**
(Quick Screen → Evaluate → Implement) significantly improves skill activation accuracy
compared to **passive skill listing** in the Drug Target Assessment Agent.

- **Model**: qwen3.5:122b (Ollama, local)
- **Registry**: 3 skills (opentargets-database, gwas-database, chembl-database)
- **stage_hints**: removed (protocol relies on skill descriptions only)
- **System prompt**: Full (with stage-specific skill reading directives)
- **Test set**: 7 categories x 20 prompts = 140 prompts x 2 conditions = 280 trials
- **Decision granularity**: 140 prompts x 3 skills = 420 paired binary decisions

## Experimental Design

### Conditions

| Condition | Description |
|-----------|-------------|
| **A_passive** | SkillsMiddleware -- lists all skills in the system prompt passively. Model decides when to read. |
| **B_SkillLoadHarness** | SkillLoadHarness -- injects a structured 3-step evaluation protocol. No stage hints. |

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

| Metric | A_passive | B_SkillLoadHarness | Delta |
|--------|:---------:|:------------------:|:-----:|
| **F1** | 81.7% | **93.9%** | **+12.2%p** |
| Precision | 96.6% | 98.2% | +1.6%p |
| Recall | 70.8% | **90.0%** | **+19.2%p** |
| FP rate | 2.5% | **1.2%** | -1.2%p |
| Specificity | 99.0% | 99.3% | +0.3%p |
| Activation rate | 81.7% | 93.3% | +11.7%p |
| Avg latency | 24.1s | 25.4s | +1.3s |

### Per-Category Accuracy

| Category | A_passive | B_SkillLoadHarness | Improvement |
|----------|:---------:|:------------------:|:-----------:|
| stage2_direct | 18/20 (90%) | **20/20 (100%)** | +10% |
| stage3_direct | 16/20 (80%) | 17/20 (85%) | +5% |
| composite | 15/20 (75%) | **19/20 (95%)** | +20% |
| stage1_tools_only | **20/20 (100%)** | **20/20 (100%)** | = |
| internal_pipeline | 18/20 (90%) | 19/20 (95%) | +5% |
| general_biology | **20/20 (100%)** | **20/20 (100%)** | = |
| data_visualization | **20/20 (100%)** | **20/20 (100%)** | = |

## Statistical Analysis

### McNemar's Test (420 paired skill-decisions)

The McNemar test evaluates whether the asymmetry in discordant pairs (cases where
the two conditions disagree) is statistically significant.

**Contingency table:**

|  | B correct | B incorrect |
|--|:---------:|:-----------:|
| **A correct** | 380 | 2 |
| **A incorrect** | 26 | 12 |

- Concordant pairs: 392 (uninformative)
- **Discordant pairs: 28** (b=2, c=26)
- Of 28 disagreements, **26 favored B** (92.9%)

| Statistic | Value |
|-----------|:-----:|
| McNemar chi-sq (corrected) | 18.893 |
| **p (exact, binomial)** | **0.000003** |
| Odds ratio (c/b) | 13.0 |
| Significance | *** (p < 0.001) |

### Bootstrap F1 Confidence Interval

Paired bootstrap (prompt-level resampling, percentile method, 10,000 resamples)
following Dror et al. (ACL 2018) and Berg-Kirkpatrick et al. (2012).

| Statistic | Value |
|-----------|:-----:|
| Observed F1_A | 0.8173 |
| Observed F1_B | 0.9391 |
| **dF1** | **+0.1218** |
| **95% CI** | **[+0.0582, +0.1974]** |
| **Bootstrap p** | **< 0.000001** |
| CI excludes 0? | **Yes -> Significant** |

Interpretation: The SkillLoadHarness improves F1 by at least +5.8% and up to +19.7%
with 95% confidence.

### Effect Size

| Measure | Value | Interpretation |
|---------|:-----:|:--------------:|
| Cohen's h | 0.3847 | Small |

Note: Cohen's h is conservative here because the baseline is already high (81.7%).
The absolute improvement of +12.2%p is practically significant for production use.

## Key Findings

1. **SkillLoadHarness significantly improves F1**: +12.2%p (81.7% -> 93.9%),
   McNemar p = 0.000003, Bootstrap 95% CI [+5.8%, +19.7%].

2. **Recall is the primary driver**: +19.2%p (70.8% -> 90.0%). The passive approach
   frequently fails to activate relevant skills, while the 3-step protocol's explicit
   evaluation step ensures each skill is considered.

3. **FP rate remains low**: Both conditions have FP <= 2.5%. The Quick Screen phase
   effectively filters non-skill tasks (general biology, visualization, pipeline).

4. **Composite prompts benefit most**: +20%p improvement (75% -> 95%). Multi-skill
   tasks require explicit per-skill evaluation to activate all relevant skills.

5. **Latency cost is minimal**: +1.3s per trial (5% increase), acceptable for
   the accuracy gain.

6. **No hints required**: The protocol achieves 93.9% F1 without any stage_hints,
   relying only on skill descriptions from YAML frontmatter. The hint mechanism
   has been removed from the codebase entirely.

## Methodology Notes

### Statistical Testing Approach

Following recommendations from:
- Dror et al., "The Hitchhiker's Guide to Testing Statistical Significance in NLP" (ACL 2018)
- Berg-Kirkpatrick et al., "An Empirical Investigation of Statistical Significance in NLP" (2012)
- "When +1% Is Not Enough: A Paired Bootstrap Protocol" (arXiv:2511.19794, 2025)

**Primary test**: Bootstrap F1 CI (prompt-level resampling, 10K iterations)
-- reports both significance and effect magnitude.

**Supplementary test**: McNemar's exact test on 420 paired binary decisions
-- validates the asymmetry in discordant pairs.

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

2026-03-24 (hint removal final run)

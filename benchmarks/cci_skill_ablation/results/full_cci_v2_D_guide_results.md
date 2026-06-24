# CCI Skill Ablation Benchmark V2 — Full Four-Condition Results

## Composite Score (higher = less hallucination, max 5.0)

| Variant | N | Composite | Faithfulness | Fabrications | Uncertainty | Spatial | Overclaiming | Latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A_no_skill | 150 | 3.14 ± 0.28 | 2.79 | 3.9 | 3.91 | 4.74 | 2.74 | 3.1s |
| B_unstructured_prose | 150 | 3.59 ± 0.35 | 3.09 | 2.2 | 4.26 | 4.96 | 3.11 | 4.4s |
| C_structured_skill | 150 | 3.79 ± 0.42 | 3.39 | 2.0 | 4.44 | 4.93 | 3.39 | 3.0s |
| D_guide_compliant_skill | 150 | 3.89 ± 0.46 | 3.50 | 1.8 | 4.51 | 4.94 | 3.52 | 3.4s |

## Primary Endpoint (Kruskal-Wallis on composite_score)

- Statistic: `253.4621996965706`
- p-value: `1.1667632288832442e-54`

## Post-hoc Pairwise Comparisons (Mann-Whitney U, Bonferroni-corrected)

| Comparison | Delta | U statistic | Bonferroni p | Effect size r | Sig |
|---|---:|---:|---:|---:|---|
| A_no_skill_vs_B_unstructured_prose | -0.445 | 3,172 | 3.17e-26 | 0.621 | *** |
| A_no_skill_vs_C_structured_skill | -0.652 | 1,840 | 2.90e-35 | 0.723 | *** |
| B_unstructured_prose_vs_C_structured_skill | -0.207 | 8,047 | 1.16e-04 | 0.246 | *** |
| A_no_skill_vs_D_guide_compliant_skill | -0.754 | 1,152 | 1.86e-40 | 0.776 | *** |
| C_structured_skill_vs_D_guide_compliant_skill | -0.102 | 9,944 | 4.90e-01 | 0.100 | ns |
| B_unstructured_prose_vs_D_guide_compliant_skill | -0.308 | 6,804 | 1.83e-08 | 0.342 | *** |

## Inter-rater Agreement (Cohen's Kappa)

- faithfulness: kappa = `0.472` (MODERATE)
- uncertainty_handling: kappa = `0.450` (MODERATE)
- spatial_calibration: kappa = `0.709` (GOOD)
- overclaiming: kappa = `0.459` (MODERATE)
# DrugTarget Skill Exposure Benchmark V2 — Stage 2 Interpretation

## Deterministic Metrics

| Variant | N | Interpretation Score | Exact Check Acc | Partial Credit Acc | Overall Conclusion Acc | Uncertainty Acc | Overclaim Rate | Anchor Coverage | Tool Calls | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_tools_only | 9 | 62.8% | 84.3% | 88.4% | 33.3% | 66.7% | 7.4% | 6.0% | 0.000 | 1573.222 |
| B_tools_plus_skills | 9 | 65.9% | 80.6% | 86.6% | 44.4% | 66.7% | 7.4% | 6.3% | 0.000 | 13662.556 |

## Primary Endpoint

- Pair unit count: `9`
- Case-level interpretation delta mean (B - A): `0.031`
- Wilcoxon p-value: `1.000`

## Blinded Judge

- `A_tools_only` wins: `0`
- `B_tools_plus_skills` wins: `1`
- `tie`: `8`
- Sign-test p-value: `1.000`

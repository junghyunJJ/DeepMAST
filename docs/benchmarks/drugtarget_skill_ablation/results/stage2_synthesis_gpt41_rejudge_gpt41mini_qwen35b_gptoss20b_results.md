# DrugTarget Skill Exposure Benchmark — Stage 2 Synthesis

## Deterministic Metrics

| Variant | N | Exact Match | Near Match | Class Acc | Priority Acc | Malformed | Anchor Coverage | Tool Calls | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_tools_only | 10 | 73.8% | 100.0% | 50.0% | 50.0% | 0.0% | 90.0% | 0.000 | 1846.300 |
| B_tools_plus_skills | 10 | 81.2% | 100.0% | 60.0% | 50.0% | 0.0% | 90.0% | 0.000 | 13955.200 |

## Paired Test

- Exact-match delta mean (B - A): `0.075`
- Wilcoxon p-value: `0.062`

## Blinded Judge

- `A_tools_only` wins: `1`
- `B_tools_plus_skills` wins: `0`
- `tie`: `9`
- Sign-test p-value: `1.000`

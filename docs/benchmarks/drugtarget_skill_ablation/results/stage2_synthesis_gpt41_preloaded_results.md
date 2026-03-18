# DrugTarget Skill Exposure Benchmark — Stage 2 Synthesis (gpt-4.1, preloaded skill docs)

## Deterministic Metrics

| Variant | N | Exact Match | Near Match | Class Acc | Priority Acc | Malformed | Anchor Coverage | Tool Calls | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_tools_only | 10 | 78.8% | 100.0% | 50.0% | 50.0% | 0.0% | 90.0% | 0.000 | 1707.300 |
| B_tools_plus_skills | 10 | 83.8% | 100.0% | 60.0% | 50.0% | 0.0% | 86.7% | 0.000 | 13827.500 |

## Paired Test

- Exact-match delta mean (B - A): `0.050`
- Wilcoxon p-value: `0.250`

## Blinded Judge

- `A_tools_only` wins: `2`
- `B_tools_plus_skills` wins: `6`
- `tie`: `2`
- Sign-test p-value: `0.289`

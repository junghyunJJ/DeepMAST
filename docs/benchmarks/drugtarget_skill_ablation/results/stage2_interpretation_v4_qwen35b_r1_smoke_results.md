# DrugTarget Skill Exposure Benchmark V4 — Stage 2 Rule Application Errors

## Deterministic Metrics

| Variant | N | Weighted Target Error | Probe Support | Primary Probe Target Error | All Probe Target Error | Rule Validity | Evidence Ref Validity | Secondary Conclusion Acc | Tool Calls | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_tools_only | 12 | 0.073 | 0.861 | 0.0% | 11.1% | 100.0% | 100.0% | 33.3% | 0.000 | 2738.167 |
| B_tools_plus_skills | 12 | 0.052 | 0.903 | 0.0% | 8.3% | 100.0% | 100.0% | 41.7% | 0.000 | 3277.500 |

## Primary Endpoint

- Pair unit count: `12`
- Case-level weighted target error delta (A - B): `0.021`
- Wilcoxon p-value: `0.250`

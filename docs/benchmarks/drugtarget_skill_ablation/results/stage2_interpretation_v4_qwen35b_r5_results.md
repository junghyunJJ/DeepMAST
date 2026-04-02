# DrugTarget Skill Exposure Benchmark V4 — Stage 2 Rule Application Errors

## Deterministic Metrics

| Variant | N | Weighted Target Error | Probe Support | Primary Probe Target Error | All Probe Target Error | Rule Validity | Evidence Ref Validity | Secondary Conclusion Acc | Tool Calls | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_tools_only | 60 | 0.877 | 0.114 | 86.7% | 88.3% | 13.3% | 13.3% | 5.0% | 0.000 | 354.700 |
| B_tools_plus_skills | 60 | 0.841 | 0.153 | 83.3% | 84.4% | 16.7% | 16.7% | 6.7% | 0.000 | 546.383 |

## Primary Endpoint

- Pair unit count: `12`
- Case-level weighted target error delta (A - B): `0.036`
- Wilcoxon p-value: `0.125`

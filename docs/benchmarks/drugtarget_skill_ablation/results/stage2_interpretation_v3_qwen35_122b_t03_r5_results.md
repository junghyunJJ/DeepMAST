# DrugTarget Skill Exposure Benchmark V3 — Sweep 0.3

## Deterministic Metrics

| Variant | N | Weighted Probe Error | Probe Support | Primary Probe Target Error | All Probe Target Error | Major Error | Evidence Ref Validity | Secondary Conclusion Acc | Tool Calls | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_tools_only | 70 | 0.037 | 0.936 | 0.0% | 4.8% | 0.0% | 100.0% | 28.6% | 0.000 | 2176.186 |
| B_tools_plus_skills | 70 | 0.036 | 0.938 | 0.0% | 4.8% | 0.0% | 100.0% | 30.0% | 0.043 | 2651.657 |

## Primary Endpoint

- Pair unit count: `14`
- Case-level weighted probe error delta (A - B): `0.001`
- Wilcoxon p-value: `0.157`

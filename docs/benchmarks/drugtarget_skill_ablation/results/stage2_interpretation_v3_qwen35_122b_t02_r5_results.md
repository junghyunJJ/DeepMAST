# DrugTarget Skill Exposure Benchmark V3 — Sweep 0.2

## Deterministic Metrics

| Variant | N | Weighted Probe Error | Probe Support | Primary Probe Target Error | All Probe Target Error | Major Error | Evidence Ref Validity | Secondary Conclusion Acc | Tool Calls | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_tools_only | 70 | 0.038 | 0.936 | 0.0% | 4.8% | 0.0% | 100.0% | 28.6% | 0.000 | 2191.800 |
| B_tools_plus_skills | 70 | 0.039 | 0.932 | 0.0% | 5.2% | 0.0% | 100.0% | 34.3% | 0.000 | 2666.357 |

## Primary Endpoint

- Pair unit count: `14`
- Case-level weighted probe error delta (A - B): `-0.002`
- Wilcoxon p-value: `0.655`

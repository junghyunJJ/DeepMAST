# DrugTarget Skill Exposure Benchmark V3 — Sweep 0.4

## Deterministic Metrics

| Variant | N | Weighted Probe Error | Probe Support | Primary Probe Target Error | All Probe Target Error | Major Error | Evidence Ref Validity | Secondary Conclusion Acc | Tool Calls | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_tools_only | 70 | 0.041 | 0.929 | 0.0% | 5.2% | 0.0% | 100.0% | 28.6% | 0.000 | 2200.643 |
| B_tools_plus_skills | 70 | 0.042 | 0.926 | 0.0% | 5.7% | 0.0% | 100.0% | 31.4% | 0.000 | 2630.486 |

## Primary Endpoint

- Pair unit count: `14`
- Case-level weighted probe error delta (A - B): `-0.001`
- Wilcoxon p-value: `0.893`

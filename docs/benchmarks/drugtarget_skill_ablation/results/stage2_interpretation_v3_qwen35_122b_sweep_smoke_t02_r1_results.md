# DrugTarget Skill Exposure Benchmark V3 — Sweep 0.2

## Deterministic Metrics

| Variant | N | Weighted Probe Error | Probe Support | Primary Probe Target Error | All Probe Target Error | Major Error | Evidence Ref Validity | Secondary Conclusion Acc | Tool Calls | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_tools_only | 14 | 0.038 | 0.935 | 0.0% | 4.8% | 0.0% | 100.0% | 28.6% | 0.000 | 2203.071 |
| B_tools_plus_skills | 14 | 0.049 | 0.911 | 0.0% | 7.1% | 0.0% | 100.0% | 28.6% | 0.000 | 2702.000 |

## Primary Endpoint

- Pair unit count: `14`
- Case-level weighted probe error delta (A - B): `-0.011`
- Wilcoxon p-value: `0.317`

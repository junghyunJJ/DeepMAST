# DrugTarget Skill Exposure Benchmark V2 — Stage 2 Interpretation

## Deterministic Metrics

| Variant | N | Interpretation Score | Exact Check Acc | Partial Credit Acc | Overall Conclusion Acc | Uncertainty Acc | Overclaim Rate | Anchor Coverage | Tool Calls | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_tools_only | 14 | 68.2% | 84.5% | 90.2% | 35.7% | 78.6% | 4.2% | 5.1% | 0.000 | 2636.357 |
| B_tools_plus_skills | 14 | 67.8% | 84.5% | 89.0% | 42.9% | 71.4% | 6.5% | 6.3% | 0.000 | 17075.643 |

## Primary Endpoint

- Pair unit count: `14`
- Case-level interpretation delta mean (B - A): `-0.004`
- Wilcoxon p-value: `0.854`

## Blinded Judge

- `A_tools_only` wins: `0`
- `B_tools_plus_skills` wins: `2`
- `tie`: `12`
- Sign-test p-value: `0.500`

## Research Panel

- Unanimous rate: `64.3%`
- Judge error rate: `0.0%`
- Confidence counts: `high=9`, `medium=1`, `low=4`
- Mean B-A grounding delta: `0.214`
- Mean B-A rubric delta: `0.214`
- Mean B-A unsupported-claim delta: `0.167`
- Mean B-A overall delta: `0.595`

## Human Audit

- Queued audits: `8`
- Completed audits: `0`
- Pending audits: `8`
- Panel-vs-human agreement: `NA`
- Audited winners: `A_tools_only=0`, `B_tools_plus_skills=0`, `tie=0`
- Human-audited sign-test p-value: `NA`

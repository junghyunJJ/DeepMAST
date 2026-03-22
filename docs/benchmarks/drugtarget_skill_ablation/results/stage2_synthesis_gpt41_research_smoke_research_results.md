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

- `A_tools_only` wins: `2`
- `B_tools_plus_skills` wins: `1`
- `tie`: `7`
- Sign-test p-value: `1.000`

## Research Panel

- Unanimous rate: `30.0%`
- Judge error rate: `3.3%`
- Confidence counts: `high=3`, `medium=3`, `low=4`
- Mean B-A grounding delta: `-0.069`
- Mean B-A rubric delta: `-0.138`
- Mean B-A unsupported-claim delta: `0.000`
- Mean B-A overall delta: `-0.207`

## Human Audit

- Queued audits: `9`
- Completed audits: `0`
- Pending audits: `9`
- Panel-vs-human agreement: `NA`
- Audited winners: `A_tools_only=0`, `B_tools_plus_skills=0`, `tie=0`
- Human-audited sign-test p-value: `NA`

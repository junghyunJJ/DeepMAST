# DrugTarget Skill Exposure Benchmark V3 — Delta-Only Rejudge

## Deterministic Metrics

| Variant | N | Weighted Probe Error | Probe Support | Primary Probe Target Error | All Probe Target Error | Major Error | Evidence Ref Validity | Secondary Conclusion Acc | Tool Calls | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A_tools_only | 70 | 0.037 | 0.936 | 0.0% | 4.8% | 0.0% | 100.0% | 28.6% | 0.000 | 2176.186 |
| B_tools_plus_skills | 70 | 0.036 | 0.938 | 0.0% | 4.8% | 0.0% | 100.0% | 30.0% | 0.043 | 2651.657 |

## Primary Endpoint

- Pair unit count: `14`
- Case-level weighted probe error delta (A - B): `0.001`
- Wilcoxon p-value: `0.157`

## Blinded Judge

- `A_tools_only` wins: `2`
- `B_tools_plus_skills` wins: `1`
- `tie`: `1`
- Sign-test p-value: `1.000`

## Research Panel

- Unanimous rate: `25.0%`
- Judge error rate: `25.0%`
- Confidence counts: `high=1`, `medium=2`, `low=1`
- Mean B-A grounding delta: `0.000`
- Mean B-A unsupported-claim delta: `0.000`
- Mean B-A targeted-error-count delta: `0.444`
- Mean B-A rubric delta: `0.000`
- Mean B-A overall delta: `-0.444`

## Human Audit

- Queued audits: `4`
- Completed audits: `0`
- Pending audits: `4`
- Panel-vs-human agreement: `NA`
- Audited winners: `A_tools_only=0`, `B_tools_plus_skills=0`, `tie=0`
- Human-audited sign-test p-value: `NA`

# Table 1. Final report outcomes with and without report-level guardrails

| Outcome | Guardrail ON | Guardrail OFF |
|---|---:|---:|
| Passed predefined checks | 16/20 (80%) | 0/20 (0%) |
| Produced with detected errors | 2/20 (10%) | 20/20 (100%) |
| Output blocked | 2/20 (10%) | 0/20 (0%) |

Values are n/20 (%). Categories are mutually exclusive and exhaustive. A passing report was complete and had zero hard errors under the predefined validation policy. The error category requires at least one confirmed hard error; remaining semantic checks could be omitted once failure was established. These are repeated executions on one breast cancer dataset, not independent biological samples. ON runs are historical controls. Errors include reporting-scope violations and should not all be described as hallucinations.

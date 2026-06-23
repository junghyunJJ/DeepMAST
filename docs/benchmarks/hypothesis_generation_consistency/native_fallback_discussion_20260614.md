# Native vs Fallback Interpretation for Hypothesis Benchmark

Date: 2026-06-14
Context: DeepMAST hypothesis generation consistency benchmark

## Core Conclusion

High fallback usage should not be interpreted as direct evidence that the model or middleware failed.

If fallback is part of the designed middleware recovery path, then final success after fallback is still a valid end-to-end system success. The important distinction is attribution:

- `total_success`: final benchmark success after all allowed middleware recovery
- `native_success`: success without fallback recovery
- `fallback_recovered_success`: failure of native completion that was recovered by fallback

Therefore, fallback-heavy results are not necessarily functionally bad. They mainly require clearer reporting.

## Current Evidence

Recent 2026-06-14 18-run mode matrix:

- Breast cancer dataset:
  - total success: 9/9
  - native: 3/9
  - fallback recovered: 6/9

- Lung/IPF dataset:
  - total success: 9/9
  - native: 3/9
  - fallback recovered: 6/9

Observed fallback triggers were mostly coverage-related, including `topn_missing` and `HYPOTHESIS-BUDGET`.

This suggests the recovery layer is working, while native generation often misses required TOP-N/featured gene coverage before recovery.

## Interpretation Rule

Use two separate claims:

1. End-to-end system reliability
   The middleware system succeeded if final outputs pass after native generation plus allowed fallback.

2. Native generation quality
   Native success rate measures how often the model/writer satisfies the benchmark without recovery.

Do not collapse these into one claim.

## Recommended Reporting

Benchmark tables should include:

- `total_success`
- `native_success`
- `fallback_recovered_success`
- `fallback_rate`
- fallback reason categories, especially:
  - `topn_missing`
  - `HYPOTHESIS-BUDGET`
  - schema or validator failures, if present

Suggested wording:

> DeepMAST middleware achieved 9/9 final success with recovery. Native generation succeeded in 3/9 runs, while fallback primarily corrected TOP-N coverage gaps.

## Recommendation for Next PR

Do not remove or weaken fallback.

For the next PR, prioritize telemetry/reporting updates before behavior changes:

1. Separate native and fallback metrics in result summaries.
2. Preserve fallback as the end-to-end reliability safety net.
3. Treat native-rate improvement as a secondary quality goal, not a replacement for total success.
4. If behavior is updated later, make it narrow:
   - add a pre-save TOP-N/featured gene coverage checklist
   - repair only missing genes before invoking host fallback
   - keep total success acceptance at `>=8/9`, preferably `9/9`

## Acceptance Criteria for Follow-up Testing

For each dataset/mode test block:

- total success: `>=8/9`, ideally `9/9`
- native/fallback counts are explicitly reported
- fallback reasons are visible in the summary
- no interpretation depends only on final success without reporting recovery attribution

# Bounded Inline Citation Frontier Design

**Status:** Superseded by grouped non-supported citation cleanup (Task 1
round 2). The former frontier proposal is disproven by live Pair-15 evidence.

**Historical status:** Narrow amendment to
`2026-08-22-high-precision-guardrail-simplification-design.md` and
`2026-08-25-reporter-deterministic-finalization-design.md`

## Binding Goal

Allow deterministic synthesis repair to finish a multi-PMID claim when explicit
inline-citation failures surface one at a time, without restoring broad
Keep `_strict_phase_progress` strict while making one deterministic repair
remove every non-supported inline PMID for the exact `(file, section,
source_claim_index)` claim when any hard repairable inline issue triggers and
no supported sibling exists. Supported siblings remain preserved; reference-
only deletion remains unchanged.

The previously proposed equal-count semantic frontier is rejected: Pair-15
revalidation increased the hard-error count from 1 to 2, so frontier admission
could not solve the actual failure.

## Failure Evidence

Pair-15 SNI produced two distinct Markdown syntheses and correctly entered clean
Reporter recovery after the first synthesis failed. The second synthesis then
failed on this explicit hard error:

- `inline_citation_overclaimed` for PMID `28174229` in a claim that also cited
  PMIDs `26148232` and `18922900`.

The second finalizer recorded:

- `initial_error_count = 1`;
- `repair_attempt_count = 3`;
- `changed_claims = 0`;
- `final_error_count = 1`.

Applying the existing deterministic inline-citation helper to an isolated copy
of the final Pair-15 payload removes PMID `28174229` without calling a model.
During the live guardrail loop, however, revalidation can promote a different
inline PMID in the same claim from warning/unverifiable to a hard explicit
citation error. The aggregate hard-error count remains one, so
`_strict_phase_progress` rolls the repaired file back. The same first repair is
then retried until the three-pass budget is exhausted.

This is not a missing repair implementation. It is a progress-admission gap
between the existing deterministic citation repair and the intentionally strict
same-phase rollback rule.

## Related Failures That Stay Separate

### Pair-13 R1

`unsupported_pathway_factor_significance` remained after three Part repair
passes. The final sentence still placed Factor3 and MAPK/PI3K in one asserted
relationship, while the caveat appeared in a separate sentence. The hard gate
correctly remained closed. This design does not relax that validator or alter
Part repair.

### Pair-13 R2

All Reporter artifacts completed with final hard errors zero, but one of 99 RAG
audit records contained `AgenticError`. The underlying SGCP-RAG response was
`Document grader returned an out-of-range document index outside its grading
batch`. Required-agentic audit validation correctly failed the condition. This
design does not downgrade that failure or modify SGCP-RAG, RAG audit policy, or
failure classification.

## Selected Behavior

Keep strict hard-error decrease as the normal same-phase progress rule.

Permit equal-count progress only when all of these conditions are true:

1. both validations are in the `semantic` phase;
2. the hard-error count is unchanged and non-zero;
3. every hard error before and after belongs to
   `REPAIRABLE_INLINE_CITATION_CODES`;
4. the before and after hard-error claim-key sets are non-empty and disjoint.

The claim key remains the existing `(file, section, value)` tuple. Removing an
inline PMID changes the exact claim value, so the next explicit citation failure
forms a new frontier. A repeated target, overlapping target set, mixed hard-error
class, phase change, or increased count remains a rollback.

This is narrower than the deleted general semantic frontier behavior. It exists
only to let validator-owned deterministic inline-citation repair consume a
bounded chain of exact citation targets within the existing three-pass budget.

## Invariants

- `inline_citation_unsupported` and `inline_citation_overclaimed` remain hard
  errors until repaired.
- Uncited semantic claims remain warning-only under the high-precision design.
- General `claim_rag_*`, synthesis-overclaim, consistency, pathway, and
  structural errors do not gain equal-count frontier movement.
- Persistent or overlapping explicit citation errors remain blocked.
- The three regular synthesis repair passes and optional terminal repair remain
  unchanged.
- `MAX_REPORTER_ATTEMPTS = 2` remains unchanged.
- Reporter timeout values and timeout settlement remain unchanged.
- Reporter recovery still begins only after synthesis failure; deterministic
  finalization still owns validation, targets, and HTML.
- No new dependency, graph node, manifest, or production module is added.

## Implementation Boundary

Modify only:

- `src/agents/deep_interpreter/report_guardrails.py`
  - narrow `_strict_phase_progress` to admit the bounded inline-citation
    frontier;
- `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`
  - reproduce the Pair-15 cascade and lock the negative boundaries.

Do not modify Reporter recovery, report rendering, Claim-RAG selection, RAG
audit validation, SGCP-RAG, prompts, timeouts, or attempt counts for this fix.

## Verification Strategy

1. Add a RED unit test proving that a disjoint equal-count explicit inline
   citation frontier is currently rejected.
2. Add a RED integration test in which two inline PMIDs become hard one at a
   time; the existing deterministic helper must remove both without a model.
3. Make only `_strict_phase_progress` admit that bounded frontier.
4. Keep same-count generic semantic, mixed, repeated, overlapping, and
   count-increasing cases rejected.
5. Run synthesis guardrail, repair, Reporter recovery, Claim-RAG, SNI runner,
   Ruff, `py_compile`, and diff checks.
6. Run deterministic finalizer replay on an isolated copy of Pair-15 SNI and
   require hard errors zero, valid sidecars/HTML, and unchanged Part hashes.
7. Run Reporter-only replay on a separate Pair-15 copy and require Attempt 1
   completion with no recovery.
8. Obtain independent spec and code review before launching full pairs.

## Completion Criteria

- The Pair-15-shaped cascade is RED before the production change and GREEN
  afterward.
- Both inline PMIDs in the regression are removed through two bounded repair
  passes without invoking a repair model.
- Generic same-count semantic movement remains rejected.
- Persistent and overlapping inline citation targets remain rejected.
- Pair-15 finalizer-only replay passes with final hard errors zero and produces
  `synthesis_validation.json`, `synthesis_targets.json`, and valid HTML.
- Pair-15 Reporter-only replay passes in Attempt 1 with `recovery_used = false`.
- Original Pair-15 evidence and Part 1/2/3 hashes remain unchanged.
- Only after these gates pass may Pair-15-R2 through Pair-20 start.

## Out of Scope

- Relaxing or suppressing the Pair-13 pathway-factor hard error.
- Treating an `AgenticError` audit record as a successful RAG call.
- Fixing the SGCP-RAG out-of-range document-grader index.
- Changing RAG query count, SNI selection, Claim-RAG selection/batching/cache,
  collection contents, model, ports, or timeouts.
- Adding more Reporter or guardrail attempts.
- Running a full pair before tests, reviews, and both isolated replays pass.

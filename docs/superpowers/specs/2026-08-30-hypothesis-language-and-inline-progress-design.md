# Hypothesis Language and Inline Progress Design

**Status:** Approved for implementation after independent artifact diagnosis
and independent spec review.

**Supersedes for this work:**
`docs/superpowers/specs/2026-08-29-bounded-inline-citation-frontier-design.md`
and its implementation plan. Those files remain historical evidence; their
contradictory frontier text is not authoritative here.

## Goal

Fix only the two code defects independently reproduced at HEAD `3dcd928`:

1. accept plural `hypotheses` as explicit hypothesis language in the
   pathway-factor validator; and
2. preserve a successful semantic inline-citation repair when revalidation
   surfaces a different, disjoint repairable inline-citation hard error at the
   same non-zero hard-error count.

The fixes must retain fail-closed behavior outside those exact boundaries.

## Evidence and Decisions

The durable compact diagnostic record is
`docs/superpowers/specs/2026-08-30-hypothesis-language-and-inline-progress-evidence.md`.
It records original artifact paths, exact hard issues, fresh replay results,
selection/fallback counts, and source hashes used by this design.

### Pair-15-R2 no-SNI: validator false positive

The sole final hard error is
`unsupported_pathway_factor_significance` for `Factor3: Hypoxia`. Its exact
target says that pathway enrichments provide `annotation-based hypotheses` and
only `suggesting potential associations`.

Fresh diagnosis on the original artifact established:

- current `HYPOTHESIS_RE.search(target)` is false;
- `hypothes(?:is|es|i[sz]ed)` matches the target;
- the current full validator reports one hard error;
- replacing only that regex in memory makes the exact error disappear and
  leaves zero hard errors; and
- an explicit unsupported assertion such as `Factor2 showed significant
  enrichment for NFkB and EGFR` remains a hard error.

Decision: change only the hypothesis word-form branch in
`scripts/validate_report.py` from `hypothes(?:is|i[sz]ed)` to
`hypothes(?:is|es|i[sz]ed)`.

### Pair-16 SNI: valid repair rollback

The final failed synthesis begins with one semantic hard error:

- code: `inline_citation_overclaimed`;
- key: `(synthesis.md, ## References, PMID: 18922900 - LRIG1 suppression ...)`.

Current deterministic repair deletes that reference-only line and returns
`changed = 1`. Revalidation then reports one different semantic hard error:

- code: `inline_citation_overclaimed`;
- key: `(synthesis.md, ## Cross-Part Themes, Literature support
  (PMID: 28174229, 26148232, 39753722) ...)`.

The before and after hard counts are both one, both codes are in
`REPAIRABLE_INLINE_CITATION_CODES`, and the existing `(file, section, value)`
key sets are non-empty and disjoint. Current `_strict_phase_progress` returns
false, so the valid first repair is rolled back and retried.

On a fixed-collection copy where the first repair is preserved, current
`run_synthesis_guardrail` completes the remaining repair in one pass with
`1 -> 0` hard errors, one normal judgment batch, no single-claim fallback, no
deadline exhaustion, no repair model, and unchanged Part 1/2/3 hashes.

Decision: retain strict aggregate decrease as the normal rule and add the
same-count exception below. This does not permit the earlier Pair-15
count-increasing `1 -> 2` candidate.

### Pair-17 no-SNI: no code change

A fresh fixed-collection replay of the original final Parts passed with two
initial semantic hard errors, one repair pass, two changed sections, and zero
final hard errors. Checkpoint/cache reuse was high, no judgment deadline was
exhausted, and the original hashes were unchanged.

Decision: Pair-17 remains a content/stochastic rerun case. Do not change repair
budgets, timeouts, or guardrail policy for it.

## Selected Progress Policy

Keep all existing phase and count behavior, then admit equal-count progress
only when every condition below holds:

1. `before_phase == after_phase == "semantic"`;
2. `before_count == after_count`;
3. the shared count is greater than zero;
4. every hard error before and after has a code in
   `REPAIRABLE_INLINE_CITATION_CODES`;
5. both hard-error claim-key sets are non-empty; and
6. the before and after claim-key sets are disjoint.

The claim key remains the existing `(file, section, value)` tuple. No new
identity type or repair abstraction is introduced.

For the equal-count exception, the following remain rejected:

- same-phase hard-error count increase, including `1 -> 2`;
- the same target repeated;
- any overlapping before/after target;
- inline plus generic mixed hard errors;
- generic semantic, consistency, pathway, or structure hard errors;
- semantic-to-deterministic phase regression; and
- a zero-count/empty frontier.

Existing deterministic-to-semantic admission and same-phase lower-count
admission remain unchanged.

## TDD Behavior Matrix

| ID | Behavior | Required result |
| --- | --- | --- |
| A | Pair-15 exact `annotation-based hypotheses` sentence | no pathway-factor hard error |
| B | singular `hypothesis` | existing no-error behavior retained |
| C | `hypothesized` and `hypothesised` | existing no-error behavior retained |
| D | explicit unsupported significance assertion | hard error retained |
| E | Pair-16-shaped disjoint repairable inline `1 -> 1` | progress accepted |
| F | identical inline target `1 -> 1` | progress rejected |
| G | overlapping inline target sets | progress rejected |
| H | repairable inline `1 -> 2` | progress rejected |
| I | inline plus generic mixed same-count frontier | progress rejected |
| J | generic semantic `1 -> 1` | progress rejected |
| K | semantic to deterministic | progress rejected |
| L | zero-count/empty frontier | progress rejected |
| M | Pair-16-shaped guardrail chain | reference deletion, disjoint `1 -> 1`, next deterministic repair, final hard errors zero, no model repair |

Every production change follows RED, observed expected failure, minimal GREEN,
and focused regression verification.

## Implementation Boundary

Modify only:

- `scripts/validate_report.py`;
- `tests/scripts/test_validate_report.py`;
- `src/agents/deep_interpreter/report_guardrails.py`; and
- `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`.

Use `scripts/repair_report.py` and its tests unchanged unless a RED test proves
the existing deterministic repair is insufficient. Current artifact replay
already proves it is sufficient, so the default is no change.

Preserve the grouped non-supported inline-PMID repair implemented by
`scripts/repair_report.py`: when no supported sibling exists for the exact
claim group, all matching non-supported PMIDs are removed together; supported
siblings and reference-only deletion remain intact. The following regressions
must remain unchanged and passing:

- `tests/scripts/test_repair_report.py::test_repair_removes_all_non_supported_inline_pmids_without_llm`; and
- `tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_run_synthesis_guardrail_removes_grouped_non_supported_inline_pmids`.

Do not change:

- SGCP-RAG or RAG audit success/failure policy;
- SNI page selection, query count, Claim-RAG selection/batching/cache, or
  collection contents;
- Reporter timeout, `MAX_REPORTER_ATTEMPTS = 2`, or repair-pass counts;
- Part generation, Reporter recovery, finalizer ownership, or HTML rendering;
- models, ports, fixed collection ID, or condition ordering; or
- Pair-17 behavior or budgets.

No new dependency, module, configuration switch, or abstraction is allowed.

## Verification Gates

### Code and review

- matrix A-M passes;
- the exact regression command below passes:

  ```bash
  pytest -q \
    tests/scripts/test_validate_report.py \
    tests/scripts/test_repair_report.py \
    tests/scripts/test_validate_repair_report.py \
    tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
    tests/agents/deep_interpreter/test_claim_rag_validation.py \
    tests/agents/deep_interpreter/test_reporter_recovery.py \
    tests/deep_interpreter/test_reporter_prompt_policy.py \
    tests/test_reporter.py \
    tests/test_reporter_phase45.py \
    tests/test_reporter_phase5.py \
    tests/test_sni_ablation_runner.py
  ```

- the exact static checks below pass:

  ```bash
  ruff check \
    scripts/validate_report.py \
    src/agents/deep_interpreter/report_guardrails.py \
    tests/scripts/test_validate_report.py \
    tests/agents/deep_interpreter/test_report_guardrail_middleware.py
  python -m py_compile \
    scripts/validate_report.py \
    src/agents/deep_interpreter/report_guardrails.py
  git diff --check
  ```

- independent spec review and independent code review pass;
- all commits follow the Lore protocol; and
- the worktree is clean before runtime launch.

### Isolated replay A: Pair-15-R2 no-SNI Parts

Run on a fresh copy, never the original. Require:

- the exact plural-hypothesis sentence is accepted;
- final hard errors are zero;
- repair attempts and Markdown rewrites are unnecessary;
- heading structure is unchanged; and
- original artifact hashes remain unchanged.

### Isolated replay B: Pair-16 SNI finalizer

Run on a fresh copy with fixed collection
`a208e916-bd32-405a-9eee-de4cd82b2a3b`. Require:

- the first reference-only repair is preserved;
- the disjoint semantic `1 -> 1` transition is accepted;
- the next deterministic inline repair completes;
- final hard errors are zero;
- validation, targets, and HTML artifacts are created;
- Part 1/2/3 hashes are unchanged; and
- original artifact hashes remain unchanged.

Run a Pair-16 Reporter-only replay only if the finalizer replay leaves a
Reporter integration question. If run, require Attempt 1 completion,
`recovery_used = false`, zero final hard errors, valid Reporter artifacts, and
unchanged Part hashes.

Failure of either required replay returns to root-cause diagnosis. It blocks
the full sequence.

## Fresh Full Sequence Contract

After all code, review, and replay gates pass, launch from a new result root in
tmux using one reviewed commit:

`Pair-15-R2 -> Pair-16 -> Pair-17 -> Pair-18 -> Pair-19 -> Pair-20`

Each Pair runs `no-SNI -> SNI` from a new directory. Never resume or reuse the
stopped root.

Fixed runtime values:

- model: `qwen3.5:122b`;
- Interpreter backend: `6000`;
- RAG backend: `4000`;
- RAG API: `8883`;
- collection: `a208e916-bd32-405a-9eee-de4cd82b2a3b`;
- collection identity: `100 documents / 1553 chunks`;
- timeout: `10800` seconds; and
- condition order: `no-SNI -> SNI`.

For content, guardrail, Reporter, or unknown failure, preserve the failed state
and audit, confirm ports 6000/4000/8883 are healthy, then continue. For a
service failure, stop before the next Pair. Never overwrite a failed condition
with success. The sequence writes fresh status and exit markers, including a
portable `printf` write of `sequence.exit_code`.

## Completion Criteria

- Pair-15 and Pair-16 exact RED cases are GREEN;
- every negative boundary remains fail-closed;
- both required isolated replays pass without mutating originals;
- the fresh six-Pair sequence reaches a terminal state under the failure
  policy; and
- the final report separates content/guardrail/Reporter failures from service
  failures and tabulates no-SNI versus SNI for every Pair.

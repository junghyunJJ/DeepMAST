# Reporter Deterministic Finalization and Recovery Boundary Design

**Status:** Supersedes `2026-08-23-reporter-recovery-state-isolation-design.md`

## Goal

Make a successful Reporter synthesis finish in the same LLM attempt. The Reporter LLM writes
`synthesis.md`; deterministic code runs the existing synthesis guardrail, materializes
`synthesis_validation.json` and `synthesis_targets.json`, renders
`CCI_Analysis_Report.html`, and verifies the final artifact set.

Use the second Reporter LLM attempt only when synthesis itself failed:

- `synthesis.md` is absent or empty;
- `synthesis.md` is not Markdown, including an HTML fragment; or
- the existing synthesis guardrail exhausts its three repair passes and optional terminal
  repair with hard errors remaining.

Missing or invalid downstream artifacts are deterministic finalization work, not a reason to
start another Reporter LLM attempt.

## Observed Failure

The latest pair-06 no-SNI run produced this state after Reporter attempt 1:

| Artifact | State |
| --- | --- |
| `synthesis.md` | Valid Markdown |
| `synthesis_validation.json` | Valid; guardrail passed; final hard errors 0 |
| `synthesis_targets.json` | Valid |
| `CCI_Analysis_Report.html` | Missing |

Attempt 2 created the HTML and preserved the three valid files. Recovery nevertheless failed
because unchanged validation and targets were classified as stale. The completed artifact set
was therefore reported as a condition failure.

The implementation and report tool currently encode contradictory contracts:

- `inspect_reporter_completion` rejects any unchanged output captured before the attempt.
- `generate_html_report` intentionally preserves existing validation and targets by writing
  them only when missing.
- The old design exempted only a preserved `synthesis.md` and explicitly retained freshness
  requirements for every other pre-existing output.

The root problem is not SHA256 freshness itself. It is using global freshness as a substitute
for artifact validity and attempt responsibility.

## Constraints and Non-goals

- Keep `MAX_REPORTER_ATTEMPTS = 2`.
- Keep `REPORTER_ATTEMPT_TIMEOUT_SECONDS` and its configured values unchanged.
- Keep the synthesis guardrail, its three repair passes, and optional terminal repair unchanged.
- Do not weaken `synthesis_not_markdown` or any other hard guardrail.
- Do not change SGCP-RAG, SNI page selection, query count, Claim-RAG selection, batching,
  caching, or collection binding.
- Do not change Part 1/2/3 generation or rerun Parts during Reporter finalization.
- Do not add HTML-to-Markdown conversion.
- Do not add a third Reporter attempt, a new dependency, a new graph node, or a new manifest.
- Preserve the existing invalid-synthesis snapshot and exception audit evidence.
- Run live verification only as Reporter-only replay on a copy. Do not run a full SNI/no-SNI
  pair in this work item.

## Approaches Considered

### 1. Add more stale-output exemptions

Exclude validation and targets when only HTML is missing.

**Rejected:** This fixes the observed combination but continues to encode file-specific
exceptions. The next partial state, such as invalid validation with valid targets, would require
another exception.

### 2. Deterministic post-synthesis finalization with `required_refresh`

Assess artifacts after each Reporter LLM attempt, run the existing guardrail/render path for
missing or invalid downstream outputs, and apply freshness only to the derived artifacts that
the finalizer was required to refresh.

**Selected:** This separates synthesis retry eligibility from deterministic completion, reuses
the existing report implementation, and directly represents partial completion.

### 3. Add a dedicated Reporter-finalization graph node and manifest

Model synthesis, guardrail, rendering, and recovery as separate graph nodes with a new persisted
state object.

**Rejected:** The two current integration surfaces already converge on
`run_reporter_with_recovery`. A new graph and manifest add coordination and migration work
without improving the required behavior.

## Ownership and Invariants

### Reporter LLM

- Reads Parts, Part 4, papers, and existing RAG context.
- Writes one complete Markdown `synthesis.md`.
- Does not call `generate_html_report` and does not write validation, targets, or HTML.
- On recovery, regenerates synthesis from existing inputs and stops after writing it.

`generate_html_report` must be removed from the Reporter subagent tool list, and the Reporter
prompt and recovery message must stop instructing the model to orchestrate downstream artifacts.
The overall Reporter stage still promises all four outputs because deterministic code supplies
the other three.

### Deterministic finalizer

- Runs the existing synthesis guardrail exactly once per finalizer invocation.
- Retains the existing guardrail repair limits and fail-closed behavior.
- Creates or refreshes only the derived artifacts in `required_refresh`.
- Broadens refresh to all derived artifacts if guardrail repair changes `synthesis.md`.
- Verifies the entire artifact set after finalization.
- Never starts an LLM attempt.

### Recovery loop

- Counts Reporter LLM attempts only; finalizer calls do not increment `attempt_count`.
- Starts attempt 2 only for an eligible synthesis failure.
- Never retries the LLM solely because validation, targets, or HTML are missing, invalid, or
  unchanged.
- Keeps byte-identical repeated invalid synthesis detection independent of downstream freshness.

## Selected Architecture

### Shared finalization implementation

Keep the implementation in the two existing modules:

1. Extract the current guardrail/bookkeeping/render body behind `generate_html_report` into one
   internal structured helper in `tools/report.py`.
2. Keep the public `generate_html_report` tool API and returned message backward compatible by
   formatting the helper result as it does today.
3. Call the same helper from `reporter_recovery.py` after an LLM attempt produces a shape-valid
   synthesis.

The internal helper returns structured status rather than requiring recovery code to parse the
tool's human-readable string. Its result must expose at least:

- finalizer status: `passed`, `guardrail_failed`, or `render_failed`;
- synthesis guardrail result;
- final `required_refresh` after any synthesis-change cascade;
- refreshed and preserved artifact names; and
- the existing render message for audit/debugging.

No new production module or public abstraction is required.

### Artifact assessment

Assess states after the LLM attempt has settled and before deciding whether to finalize, recover,
or return.

#### Synthesis eligibility

A synthesis is shape-valid when it exists, is non-empty, and
`validate_synthesis_report` does not report `synthesis_not_markdown`. Shape validity permits the
deterministic guardrail to run; it does not imply guardrail success.

After the guardrail finishes, synthesis is final-valid only when:

- guardrail status is `passed`; and
- `final_error_count == 0`.

If repairs are exhausted with hard errors, the synthesis is a recovery-eligible failure.

#### Derived artifact validity

- `synthesis_validation.json`: parseable JSON object containing a
  `synthesis_guardrail` object with `status == "passed"` and `final_error_count == 0`.
- `synthesis_targets.json`: parseable JSON object whose `part4_synthesis_available`,
  `drug_md_available`, `canonical_source`, and `supporting_source` fields agree with the existing
  `_default_synthesis_targets(data_dir)` calculation. Absolute source-path strings are not a
  validity gate. Extra fields remain allowed.
- `CCI_Analysis_Report.html`: non-empty text containing a doctype, an opening `<html` element,
  and a closing `</html>` element, case-insensitively. No new HTML parser is added.

#### Downstream refresh cascade

Derived artifacts are ordered for invalidation as:

`synthesis_validation.json -> synthesis_targets.json -> CCI_Analysis_Report.html`

`required_refresh` is the suffix beginning at the earliest missing or invalid artifact:

| Earliest problem | `required_refresh` |
| --- | --- |
| Validation missing/invalid | validation, targets, HTML |
| Targets missing/invalid | targets, HTML |
| HTML missing/invalid | HTML |
| No derived problem | empty |

If the LLM changes synthesis relative to the pre-attempt SHA256, or guardrail repair changes it
inside the finalizer, all three derived artifacts become refresh-required.

Before writing refreshed sidecars, the finalizer removes only refresh-required derived files and
then reuses the existing write-if-missing helpers. Valid files outside `required_refresh` remain
untouched. This preserves the production reproduction where validation and targets retain their
hashes while missing HTML is rendered.

### Completion and freshness

Completion requires:

1. final-valid synthesis;
2. all three derived artifacts valid; and
3. every artifact in `required_refresh` either newly created or content-refreshed when it existed
   in the pre-finalizer state.

Freshness is never evaluated for valid preserved artifacts outside `required_refresh`.
`stale_outputs` remains in the audit for compatibility but contains only refresh-required files
whose SHA256 did not change. Repeated invalid synthesis continues to use its dedicated digest
comparison.

### Attempt flow

For each of at most two Reporter LLM attempts:

1. Capture the Reporter output SHA256 state.
2. Run the Reporter LLM and any required deterministic finalization as one logical attempt under
   the existing attempt timeout; do not introduce a second timeout setting or budget.
3. Preserve timeout or exception metadata and wait for any protected invoke/finalizer worker to
   settle before inspecting files or starting attempt 2.
4. Assess synthesis shape.
5. If synthesis is absent/empty or non-Markdown, skip finalization and enter synthesis recovery
   only after attempt 1.
6. If synthesis is shape-valid, assess derived artifacts and compute `required_refresh`.
7. If all artifacts are already valid and synthesis was not changed, return the real attempt
   result without a finalizer call.
8. Otherwise call deterministic finalization, then reassess the complete artifact set.
9. If guardrail repairs are exhausted with hard errors, enter clean synthesis recovery only after
   attempt 1.
10. If deterministic finalization fails for any other reason, fail with audit; do not spend an LLM
    retry on a renderer or bookkeeping failure.
11. Return only when completion passes and a real attempt result of type `T` is available.

### Retry preparation

Recovery starts from synthesis failure, never downstream incompleteness.

- Absent/empty synthesis: record `action: "absent"` and remove any derived Reporter outputs before
  the clean attempt.
- Non-Markdown synthesis: copy it to `synthesis_reporter_attempt1.md`, record all hard failure
  codes, remove the working synthesis and all derived Reporter outputs, and record
  `action: "quarantined_invalid"`.
- Guardrail-exhausted Markdown: copy the post-repair synthesis to
  `synthesis_reporter_attempt1.md`, collect remaining hard error codes from
  `synthesis_guardrail_final.json`, remove the working synthesis and all derived Reporter outputs,
  and record `action: "quarantined_guardrail_failed"`.

Attempt 2 receives a fresh message instructing it to write synthesis only. There is no
preserve-valid-synthesis recovery branch because valid synthesis is completed deterministically
without another LLM attempt.

### Timeout and late-write integrity

The existing sync middleware correctly waits for its single worker before allowing another
attempt, but it currently discards the real handler result when cancellation occurs.

Use a private timeout-with-result control-flow carrier:

1. Keep the LLM result once it becomes available, then run any required finalizer in the same
   timeout-protected logical attempt.
2. When cancellation fires, wait for the active invoke or finalizer worker to settle as today.
3. If the LLM worker returned, carry that real `ToolMessage | Command` result back to
   `run_reporter_with_recovery` while retaining `timed_out: true` in the audit.
4. Finalize or verify the settled files only after no earlier worker can write.
5. If completion passes, return the carried real result without attempt 2.

Never fabricate a generic `T`. If a timeout or exception leaves valid artifacts but no real
result is available, record the artifact state and propagate the execution failure rather than
starting an LLM attempt merely to manufacture a return value.

No second attempt may start while an earlier invoke or finalizer can still write Reporter files.
The numeric timeout and its role as the logical-attempt deadline remain unchanged.

### Exception and deterministic-failure behavior

- Preserve the current invocation-exception contract: record attempt metadata and re-raise the
  real exception rather than converting it into a fabricated success or an unrelated LLM retry.
- A guardrail-exhausted synthesis is the only deterministic finalizer outcome eligible for a
  clean synthesis retry.
- Bookkeeping, validation-write, or HTML-render failures are recorded and raised without spending
  attempt 2, because another synthesis generation cannot repair deterministic infrastructure.
- If final artifacts are valid but no real generic result `T` is available, preserve the artifact
  evidence and propagate the execution failure.

### Audit semantics

Continue using `reporter_recovery.json`; do not add another manifest. Preserve existing fields and
add per-attempt evidence sufficient to explain the decision:

- `synthesis_status`;
- `required_refresh`;
- structured `finalizer` status, refreshed outputs, and preserved outputs when called;
- completion validity and refresh-only `stale_outputs`;
- timeout and exception metadata;
- retry preparation and all remaining hard failure codes; and
- repeated invalid synthesis status.

`recovery_used` becomes true only when attempt 2 begins. Deterministic finalization after attempt
1 does not count as recovery.

## Required State Matrix

These are post-LLM, pre-decision states. A-I are required regressions; J-L close the newly defined
guardrail and derived-validity boundaries.

| State | Input state | Expected behavior |
| --- | --- | --- |
| A | No Reporter outputs | Skip finalizer; clean attempt 2; finalizer runs only after shape-valid synthesis exists |
| B | HTML-fragment synthesis | Snapshot and quarantine synthesis; remove derived outputs; clean attempt 2; finalize all derived outputs |
| C | Valid synthesis only | One LLM attempt; refresh validation, targets, and HTML; pass without recovery |
| D | Valid synthesis, validation, targets; HTML missing | One LLM attempt; render HTML only; existing three hashes may remain unchanged; pass |
| E | All four artifacts valid | No finalizer and no recovery; return attempt result |
| F | Valid synthesis; validation invalid | Refresh validation, targets, and HTML; no LLM recovery |
| G | Attempt 2 repeats byte-identical invalid synthesis | Fail after two attempts; retain snapshot, digests, failure codes, and repeated-invalid audit |
| H | Sync timeout worker late-writes valid synthesis and returns | Join worker, retain real result, finalize once, record timeout, start no concurrent attempt |
| I | Attempt 2 raises | Preserve attempt-1 quarantine audit and attempt-2 exception type/repr; fail |
| J | Markdown synthesis exhausts guardrail repairs with hard errors | Snapshot/quarantine post-repair synthesis; clean attempt 2; finalize if second synthesis passes |
| K | Valid synthesis/validation; targets invalid or missing | Refresh targets and HTML only; no LLM recovery |
| L | Valid synthesis/validation/targets; HTML structurally invalid | Refresh HTML only; no LLM recovery |

## Files and Interface Impact

Expected production edits are limited to existing Reporter surfaces:

- `src/agents/deep_interpreter/reporter_recovery.py`
  - separate synthesis retry from deterministic finalization;
  - compute refresh-scoped completion;
  - preserve audit, timeout, late-write, and repeated-invalid behavior.
- `src/agents/deep_interpreter/tools/report.py`
  - expose one internal structured finalizer shared with the public report tool;
  - refresh the requested derived suffix while preserving other valid artifacts.
- `src/agents/deep_interpreter/subagents/configs.py`
  - remove `generate_html_report` from Reporter LLM tools while retaining the Reporter stage output
    contract.
- `src/agents/deep_interpreter/subagents/prompts.py`
  - stop after synthesis; remove LLM HTML-tool orchestration instructions.

Expected test edits remain in existing Reporter suites:

- `tests/agents/deep_interpreter/test_reporter_recovery.py`
- `tests/deep_interpreter/test_comprehensive_template_report.py`
- `tests/deep_interpreter/test_reporter_prompt_policy.py`
- prompt/CLI contract tests that currently require the Reporter LLM to call
  `generate_html_report`.

No new production file is planned.

## TDD and Verification Requirements

Implementation must begin with the production reproduction, state D, failing under current code.
Then add C, F, E, H, J, K, and L in the smallest dependency order. Existing B, G, and I tests
remain regression anchors but must be updated to the new synthesis-only recovery prompt.

Before completion:

1. Show the required state matrix RED before production edits and GREEN afterward.
2. Run existing Reporter recovery, report tool, synthesis guardrail, prompt-policy, Claim-RAG,
   SNI-runner, timeout, and attempt-count regression tests.
3. Run Ruff, `py_compile`, and `git diff --check` on the changed surfaces.
4. Copy the latest failed no-SNI pair-06 result to a new temporary directory.
5. Preserve Part 1/2/3 hashes and the original result directory.
6. Reproduce the valid-synthesis/valid-sidecars/missing-HTML state in the copy.
7. Run Reporter-only verification and require exit code 0, guardrail hard errors 0, valid
   validation/targets/HTML, no second LLM recovery for downstream completion, and unchanged Part
   hashes.
8. Obtain independent code review after implementation and fix every Critical or Important issue
   with a regression test.

Do not run a full SNI/no-SNI pair until separately authorized.

## Acceptance Criteria

1. A normal attempt that leaves shape-valid synthesis completes deterministic guardrail and
   downstream finalization before any recovery decision.
2. Valid unchanged artifacts outside `required_refresh` never cause failure.
3. State D exits successfully with only HTML refresh-required.
4. Invalid derived artifacts refresh through the defined downstream cascade without another LLM
   attempt.
5. Recovery is used only for absent/empty/non-Markdown synthesis or guardrail exhaustion with hard
   errors.
6. Invalid synthesis remains ordered and auditable, and attempt 2 starts without invalid working
   Reporter outputs.
7. Sync timeout late writes cannot overlap attempt 2, and a real late result may complete without
   a fabricated return value.
8. Attempt-2 exceptions and repeated invalid synthesis retain their current audit evidence.
9. Reporter timeout configuration, two-attempt limit, RAG, SNI, Claim-RAG, synthesis guardrail,
   and Part generation behavior remain unchanged.
10. Reporter-only replay passes on a copy while the original pair-06 result and Part 1/2/3 hashes
    remain unchanged.

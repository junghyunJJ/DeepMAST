# Minimal Hybrid Report Repair Design

## Goal

Make Deep Interpreter report repair general enough to handle future validator
errors without adding one repair function per error code, while keeping edits
local, auditable, and fail-closed.

The design applies inside the existing Report Guardrail for Part 1, Part 2,
Part 3, and synthesis outputs. It does not create a new agent, middleware, or
repository-wide repair subsystem.

## Problem

Recent no-SNI runs exposed two opposite failure modes:

1. Whole-section LLM rewrites were too broad. The integrity guard correctly
   rejected candidates that lost headings or too much content, but the repair
   loop then made zero progress.
2. Narrow fixes for individual error codes solved saved examples but new runs
   produced different metric, direction, citation, and semantic errors.

The underlying issue is not a lack of additional `if/elif` branches. Validator
issues do not consistently identify an exact editable span or distinguish
between corrections whose answer is known from source data and corrections
that require semantic rewriting.

## Chosen Approach

Keep the existing issue JSON shape and add only two optional fields:

- `target_text`: the exact report text the repair engine may change.
- `replacement_text`: the complete corrected text when the validator can
  derive the answer deterministically.

No strategy registry, schema migration, compatibility adapter, hash locator,
or fuzzy matching layer is introduced.

### Repair Decision

For each hard-error issue:

1. Existing trusted deterministic repairs, such as invalid PMID correction and
   supported-sibling citation removal, remain available.
2. If `target_text` and `replacement_text` are present, replace the target
   deterministically.
3. If only `target_text` is present, ask the existing LLM to rewrite that text
   using the issue's `evidence` and `repair_instruction`.
4. If no safe target is available, preserve the report and fail closed.

The repair engine dispatches from the presence of these fields, not from a
growing list of error-code-specific repair functions. A future validator can
become repairable by supplying the same generic fields without changing the
repair engine.

## Target Resolution

Target resolution balances safety with normal Markdown variation:

1. Restrict search to the named `file` and `section`.
2. Try an exact `target_text` match first.
3. If exact matching fails, normalize whitespace and soft line wraps only.
4. Preserve numbers, signs, PMIDs, gene names, punctuation, and case during
   normalization.
5. When identical targets repeat, repair only when the number of validator
   issues for that target equals the number of occurrences in the section.
6. If zero, multiple ambiguous, or stale candidates remain, emit an explicit
   hard error and do not modify the file.

The original text hash may be recorded for audit but is not a repair
precondition. Semantic similarity, embeddings, and nearest-text matching are
not allowed.

## Repair Safety

Every replacement must satisfy the existing local safety rules:

- The replacement is non-empty.
- It contains no Markdown heading.
- A generic deterministic or LLM replacement introduces no PMID absent from
  the target text. The existing trusted one-digit PMID typo correction remains
  the sole exception because it resolves against `papers.json`.
- It retains at least 50% of the target's non-whitespace content.
- Every character outside the resolved target occurrence or occurrences is
  unchanged.
- The complete report heading sequence is unchanged after repair.

Deterministic replacements are still revalidated; they are not trusted merely
because the validator produced them.

## Fail-Closed Behavior

The report remains unchanged and the guardrail fails when:

- `target_text` cannot be resolved safely;
- repeated occurrence counts do not match validator issue counts;
- a deterministic replacement is missing or unsafe;
- an LLM replacement violates local safety;
- the validator reports an error without a supported target or existing
  trusted deterministic handler; or
- revalidation still reports hard errors after the bounded repair passes.

There is no automatic whole-section LLM fallback. Unsupported or ambiguous
repair cases remain visible instead of being downgraded or hidden.

## Audit

Use the existing `repair_trace.jsonl` lifecycle. Record metadata only:

- event type;
- file and section;
- issue code;
- match mode (`exact`, `whitespace_normalized`, `repeated_exact`);
- occurrence and issue counts;
- deterministic or LLM path;
- accepted or rejected;
- rejection reason; and
- retention ratio when applicable.

Do not store LLM candidate bodies in the trace. Fresh condition copies must
continue removing the trace as runtime scratch.

## Scoped Part 1/2 Smoke

The production middleware keeps its default requirement for all Part 1, Part
2, and Part 3 files. A scoped guardrail entry point or optional filename scope
is added only so an integration smoke can validate freshly generated Part 1
and Part 2 without waiting for Part 3.

The scoped smoke must use the same validators, repair engine, safety checks,
Claim-RAG configuration, and revalidation loop as the production guardrail.
It is not a separate simplified repair implementation.

Part 1/2 smoke covers metric repair, direction repair, citation repair,
semantic overclaim repair, target resolution, audit, and fail-closed behavior.
It does not claim to validate Part 3 or synthesis-specific rules.

## Part 3 and Synthesis Artifact Replay

Copy existing Part 3 and synthesis outputs into disposable directories and run
the updated guardrail against those copies. This avoids regenerating the
expensive agents while testing Part 3 therapeutic-scope and synthesis
consistency behavior.

"Artifact replay" means generation is skipped. Claim-RAG validation and an
LLM exact-text rewrite may still use ports 4000 and 6000 when a cache entry is
not reusable.

Original artifacts remain immutable.

## Verification Gates

Validation proceeds in increasing-cost order:

1. Synthetic unit and integration tests for deterministic replacement,
   semantic rewrite, whitespace normalization, repeated targets, ambiguous
   targets, unsafe candidates, audit records, and fail-closed behavior.
2. Fresh Part 1/2 scoped smoke with zero final hard errors and unchanged
   headings.
3. Disposable Part 3 and synthesis artifact replay with zero final hard errors
   and unchanged headings.
4. One fresh canonical pair 05, globally serial no-SNI then SNI.

Each gate must pass before the next begins. The full pair retains fail-fast:
SNI does not start unless no-SNI passes.

## Completion Criteria

- The generic repair path requires no new repair-engine branch for each newly
  repairable validator issue.
- Unit and integration suites pass.
- Part 1/2 scoped smoke finishes with zero hard errors.
- Part 3 and synthesis artifact replays finish with zero hard errors.
- All repaired artifacts preserve their Markdown heading sequences.
- One fresh no-SNI and SNI pair completes with both manifests marked passed.
- Source and fixed collection contain the same exact 100 PMIDs in both
  conditions.
- Repair, rejection, RAG, PMID-flow, and elapsed-time metrics remain auditable.

## Alternatives Rejected

### Whole-section LLM repair

Rejected because it repeatedly produced structurally unsafe candidates and
changed too much surface area.

### LLM-only claim repair

Rejected for metrics, signs, directions, and PMID facts whose correct values
already exist in structured source artifacts.

### Full repair-contract framework

Rejected as unnecessary complexity. Strategy registries, hash locators,
atomic schema migrations, and compatibility layers do not materially improve
the current guardrail.

### One repair function per error code

Rejected because each new output can expose a different combination of
validator issues and force another code change.

## Out of Scope

- SGCP-RAG repository or collection changes.
- Interpreter, Reporter, or SNI generation-prompt redesign.
- Evidence ranking or citation-diversity policy changes.
- Repairing reports produced by other DeepMAST agents.
- Fuzzy semantic matching or autonomous section regeneration.
- Ten-pair replicated experiments before one canonical pair passes.

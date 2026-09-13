# Deterministic-First Atomic Report Repair Design

## Context

The BC no-SNI/SNI comparison repeatedly reached a single residual hard error
after hours of generation and agentic RAG validation. The latest no-SNI run
completed Parts repair at `37 → 0`, then failed synthesis at `1 → 1` after
23,105 seconds. Its synthesis repair reported three changed claims while the
offending Markdown table still contained
`Spatial plots confirm epithelial-vascular co-localization`; repeated
attempts appended the same association caveat many times.

The failure exposed three general defects:

1. Markdown table rows are merged into one claim window, so one unsafe word
   makes the entire table the repair target.
2. Deterministic hard errors and expensive claim-RAG validation run in the same
   validation pass, causing agentic retrieval before local errors are settled.
3. Repair mutations are retained and counted even when the hard-error count
   does not decrease.

## Goal

Make Parts and synthesis repair structurally local, deterministic-first,
atomic, idempotent, and measurably cheaper without weakening validators,
changing the RAG corpus, or adding dependencies.

## Non-Goals

- Do not hard-code `confirm → show` or any other phrase-specific rewrite.
- Do not downgrade hard errors, remove RAG validation, or raise acceptance
  thresholds.
- Do not change Deep Interpreter generation prompts, model settings, SNI
  construction, collection contents, or no-SNI/SNI ordering.
- Do not add a Markdown parser, repair framework, runner resume subsystem, or
  new dependency.
- Do not run no-SNI and SNI in parallel.

## Design

### 1. Markdown table rows are atomic claim windows

`scripts.validate_report._claim_windows()` will treat each non-separator
Markdown table row as an independent claim window. A table separator such as
`|---|---|` is ignored. This makes the exact row containing an overclaim the
validator-owned `target_text`; surrounding header and data rows remain outside
the repair target.

The existing Claim-RAG cleaner already ignores Markdown table rows, so this
change does not promote every table row into a new agentic-search request.

### 2. Deterministic validation precedes semantic RAG

Parts and synthesis will use the same phase order:

1. Run local deterministic validation.
2. Run cheap synthesis consistency validation where applicable.
3. If any deterministic hard error remains, return those issues without
   calling Claim-RAG.
4. Repair deterministic issues within the bounded repair loop.
5. Only after deterministic hard errors reach zero, run Claim-RAG validation.
6. Repair semantic issues and revalidate through the same controller.

Warnings do not block Claim-RAG. Missing or malformed `papers.json` and invalid
HTML retain their existing fail-closed behavior.

### 3. Repair attempts are atomic

Before each regular or terminal repair attempt, the controller snapshots the
Markdown files in scope. Validation carries an explicit active phase:
`deterministic` or `semantic`.

- Within the deterministic phase, retain a candidate only when its hard-error
  count strictly decreases.
- Within the semantic phase, retain a candidate when its hard-error count
  strictly decreases, or when the count is unchanged and the complete prior
  error-key set is non-empty and disjoint from the complete candidate
  error-key set. Equal-count semantic candidates with any persistent old target
  are rolled back.
- A `deterministic → semantic` transition is progress even when newly visible
  semantic errors outnumber the resolved deterministic errors.
- A `semantic → deterministic` transition is regression and is rolled back.
- Count increases restore the snapshot, do not count the mutation, and retry
  from the same original text within the existing cap.
- `changed == 0`: stop immediately with the original text preserved.

Regular retries remain capped at three. Terminal repair remains limited to
newly surfaced final errors and obeys the same strict-progress rule.

### 4. Metrics describe accepted work only

`changed_sections` and `changed_claims` count only accepted mutations. A
candidate that is rolled back contributes to `repair_attempt_count` but not to
the changed count. Parts and synthesis results record
`deterministic_initial_error_count` and `semantic_initial_error_count`
separately; legacy `initial_error_count` is their sum so no-SNI/SNI pre-repair
burden remains comparable. The first semantic-phase validation is preserved in
its own JSON artifact. Final validation JSON is always written from the
retained file state.

### 5. Idempotence is a release gate

After a guardrail reaches zero hard errors, an immediate second invocation on
the same artifact must produce:

- initial hard errors: 0
- final hard errors: 0
- repair attempts: 0
- changed sections/claims: 0
- unchanged Markdown bytes

### 6. Historical artifact replay precedes a full pair

The implementation is validated against preserved failures:

- unsupported inline PMID
- first Factor/pathway locality wording
- descriptor-rich Factor/pathway locality wording
- HTML synthesis generation boundary
- Markdown table synthesis overclaim

All replays use copies under `mktemp`; source artifacts remain immutable. The
table-overclaim replay starts from `before/synthesis.md` to avoid treating
previously duplicated caveats as input.

Only after every replay passes may one fresh pair 05 run globally serial in the
order no-SNI → SNI.

## Safety Invariants

- Exact `target_text` splicing remains mandatory.
- Markdown heading level and position are unchanged by repair. Validator-owned
  semantic repair may replace only the text of an exact targeted H2-H6 heading.
  The validator-owned synthesis title rule remains the sole level change: when
  the first non-empty line is an H2-H6 heading, deterministic repair may promote
  only that marker to H1 while preserving its text.
- No new PMID may appear.
- Existing table row count is preserved unless the validator explicitly owns a
  complete-row deletion target.
- A failed candidate leaves all scoped Markdown files byte-identical to the
  pre-attempt snapshot.
- Source artifacts and the fixed 100-paper collection remain unchanged.
- SNI starts only after no-SNI reaches terminal success.

## Performance Evidence

The failed baseline is:

- total elapsed: 23,105 seconds
- retrieval elapsed: 6,270.622 seconds
- retrieval attempts: 96
- positive results: 14
- zero-hit results: 82
- Reporter elapsed: 16,724.172 seconds

Performance acceptance is behavioral rather than tied to network timing:

- Claim-RAG is not called while deterministic hard errors remain.
- A no-progress candidate is rejected before another semantic RAG phase.
- Historical replay records elapsed time and new audit rows for comparison with
  the baseline; variable wall-clock time is reported, not used as a correctness
  threshold.

## Acceptance Criteria

1. The current table overclaim produces one issue whose target is only the
   offending row.
2. A caveat-only candidate that leaves the original hard error is rolled back.
3. Resolving the last deterministic error advances to semantic validation even
   when semantic errors are newly revealed.
4. A valid association/hypothesis candidate reaches `1 → 0` within its active
   phase without changing heading levels/positions, PMIDs, or unrelated table
   rows; validator-owned exact semantic heading text may change.
5. Parts and synthesis both defer Claim-RAG until deterministic hard errors are
   zero.
6. Rejected mutations do not contribute to changed counts.
7. Deterministic and semantic initial hard errors are separately auditable and
   sum to the reported combined initial hard-error count.
8. A second guardrail invocation is idempotent.
9. Every preserved failure artifact reaches zero hard errors with its source
   unchanged.
10. One fresh no-SNI → SNI pair completes under the fixed collection and model
   topology.

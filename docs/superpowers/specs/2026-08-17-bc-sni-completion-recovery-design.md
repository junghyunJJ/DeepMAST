# BC SNI Completion Recovery Design

## Goal

Complete one scientifically comparable canonical BC no-SNI to SNI pair after
repairing the two defects exposed by the four-hour smoke, without weakening
corpus identity or post-repair integrity checks.

## Failure evidence

- Ports 4000 and 6000 both serve `qwen3.5:122b`, and the RAG API on 8883 is
  healthy; the failed smoke was not infrastructure-blocked.
- The canonical no-SNI condition retained eight hard inline-citation errors in
  two `part2_final.md` sections.
- `parts_guardrail_result.json` records one repair attempt, zero changed
  sections, eight initial errors, and eight final errors.
- The section-integrity guard correctly preserved the original section after
  rejecting a structurally unsafe whole-section candidate. The missing
  behavior is a safe, narrower repair path for the exact flagged claim.
- The SNI condition was interrupted by the external four-hour pair limit, not
  by a completed guardrail verdict.

## Design

### 1. Repair failed inline citations at claim scope

- Keep deterministic PMID correction and supported-sibling citation removal
  unchanged.
- For `inline_citation_unsupported` and `inline_citation_overclaimed` issues
  that deterministic repair cannot resolve, group duplicate issue rows by
  file, section, and exact claim value and request one replacement for that
  claim only.
- Replace the claim only when it occurs exactly once in the named section, the
  replacement is non-empty, contains no Markdown heading, and introduces no
  PMID absent from the original claim.
- Preserve every other character and every heading in the section. If the
  claim candidate is unsafe, leave the report unchanged and keep the error
  visible.
- Retain whole-section repair for non-inline validation errors; do not relax
  the existing exact-heading and 50% section-retention guard.

### 2. Normalize malformed retrieval checkpoint state

- At checkpoint load, replace a non-dictionary `retrievals` field with an
  empty dictionary while retaining a valid version and `batches` mapping.
- Do not treat malformed retrieval state as a cache hit and do not hide
  transport failures.

### 3. Verify recovery before another full pair

- Use a disposable copy of the failed no-SNI artifact to run the report
  guardrail with the new claim-scoped repair path.
- Require zero final hard errors and unchanged Markdown heading sequences in
  all three part reports before starting the expensive pair.
- The failed artifact remains immutable evidence and is not a final comparison
  result.

### 4. Run a fresh completion-first pair

- Use a new output root and manifest pair 05 in the frozen order no-SNI then
  SNI.
- Keep port 4000 for RAG and port 6000 for Interpreter/Reporter, both using
  `qwen3.5:122b`.
- Remove only the external four-hour total-pair cutoff. Existing model-call,
  reporter-attempt, validation, and failure propagation boundaries remain.
- Do not resume or mix the interrupted condition directories into the final
  comparison.

## Completion criteria

- Both condition manifests report `passed`.
- Source and fixed collection contain the same exact 100 PMIDs in both
  conditions.
- Both final validations contain zero hard errors.
- Post-repair Markdown heading sequences are unchanged and no unsafe candidate
  is written.
- The final comparison reports repair counts, claim/RAG metrics, PMID flow, and
  elapsed time for no-SNI and SNI.

## Out of scope

- SGCP-RAG repository or collection mutation.
- Citation-ranking or diversity-policy changes.
- Model, port, pair order, or canonical source changes.
- Reusing the failed smoke as final experimental evidence.
- Starting ten replicate pairs before this single pair completes.

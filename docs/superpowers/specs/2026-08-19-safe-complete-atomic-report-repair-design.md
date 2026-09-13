# Safe Complete Atomic Report Repair Design

## Goal

Make the existing Deep Interpreter Report Guardrail remove every validator hard
error it can safely target while preserving the current small architecture:
validator, exact-target patcher, bounded revalidation loop, and fail-closed
publication.

Success means a report is published only when final validation has zero hard
errors. It does not mean every generated report is guaranteed to complete; an
unresolvable or structurally unsafe repair still fails closed.

This document supersedes only the semantic non-empty/50%-retention rules in
`docs/superpowers/specs/2026-08-18-minimal-hybrid-report-repair-design.md`.
Its deterministic replacement, target resolution, bounded retry, audit,
smoke/replay, and full-pair constraints remain in force unless restated here.

## Existing Architecture to Keep

The current system already has the required boundaries:

1. Validators emit atomic issues containing `file`, `section`, `target_text`,
   `evidence`, `repair_instruction`, and optional `replacement_text`.
2. `scripts/repair_report.py` changes only resolved target spans.
3. `src/agents/deep_interpreter/report_guardrails.py` revalidates after each
   repair pass, retries at most three regular passes, and performs the existing
   bounded terminal repair for newly surfaced errors.
4. Middleware rejects publication when hard errors remain.

No new agent, graph, middleware, strategy registry, locator subsystem, or
dependency is required.

The latest failed artifact also exposes one independent validator false
positive: `negatively associated` is not recognized as negative direction,
while the word `enrichment` elsewhere in the same sentence is recognized as
positive. The existing direction vocabulary is extended to cover the adverbial
forms `negatively` and `positively` without changing the validator architecture.

## Repair Decision Contract

Keep deterministic repair unchanged:

- When every grouped issue supplies the same `replacement_text`, apply that
  exact replacement without invoking an LLM.

For semantic issues with `target_text` but no deterministic replacement, use
one structured LLM result:

```json
{
  "action": "replace",
  "replacement_text": "Evidence-supported replacement text"
}
```

or:

```json
{
  "action": "delete",
  "replacement_text": ""
}
```

`replace` is preferred whenever any evidence-supported meaning can be retained.
`delete` is the fallback when the exact target contains no assertion that can
be retained without reproducing the validator error. Delete removes only the
resolved target span; it never removes a named section or changes surrounding
text.

Use the repository's existing Pydantic and LangChain structured-output support.
Do not parse permissive free-form JSON or add a new package.

## Local Safety

All existing target-resolution rules remain:

- restrict lookup to the named file and section;
- exact match first, whitespace/soft-wrap normalization second;
- reject missing or ambiguous targets;
- repair repeated exact targets only when issue and occurrence counts match;
- change no character outside resolved target spans; and
- preserve the complete Markdown heading sequence.

Deterministic replacements retain the existing non-empty, heading, no-new-PMID,
and 50% target-retention checks. Semantic replacement safety becomes
action-aware:

- `replace` requires non-empty text;
- `delete` requires an empty replacement;
- neither action may introduce a Markdown heading;
- neither action may introduce a PMID absent from the target;
- malformed or contradictory structured results are rejected;
- semantic retention ratio remains audit metadata, not a blanket 50%
  acceptance gate.

The previous 50% target-length rule is removed because a short supported
correction can be safer than a longer unsupported paraphrase. Preservation is
enforced by exact target boundaries, unchanged surrounding text, heading
identity, and full validator revalidation.

## Revalidation and Stop Conditions

After a repair pass, the existing Report Guardrail reruns all applicable
deterministic and Claim-RAG validators:

- zero hard errors: pass;
- remaining hard errors with changed targets: retry only the newly emitted
  issues through the existing loop;
- no safe change: stop and fail closed;
- hard errors after bounded passes: fail closed and block publication.

No whole-section rewrite or unbounded retry is added. A deletion is not treated
as success by itself; only the final validator result determines success.

## Required Regression Coverage

Tests must cover:

- deterministic replacement still bypasses the LLM;
- structured semantic replacement preserves all surrounding Markdown;
- structured delete removes only the exact target;
- short but valid replacements are accepted;
- empty `replace`, non-empty `delete`, headings, new PMIDs, malformed structured
  output, missing targets, and ambiguous targets are rejected without mutation;
- direction mismatch, unsupported Claim-RAG/citation content, and Part 3
  therapeutic spillover can reach zero hard errors through the common path;
- `negative`, `negatively`, `inverse`, `inversely`, `positive`, and
  `positively` are classified with the intended direction while genuine
  mismatches remain hard errors;
- Part and synthesis guardrails retain bounded retries and fail-closed behavior;
- headings remain identical and no new PMID appears after repair.

## Increasing-Cost Verification

Run gates sequentially:

1. focused repair and guardrail tests;
2. the broader existing Deep Interpreter guardrail regression suite;
3. disposable replay of the latest failed no-SNI artifact, which currently has
   12 final hard errors after reducing 31 initial hard errors;
4. one fresh canonical pair 05, globally serial no-SNI then SNI.

SNI does not start unless no-SNI passes. Historical and canonical source
artifacts remain immutable.

## Out of Scope

- LangChain Skills installation or SkillsMiddleware adoption;
- a new repair agent or prompt-routing framework;
- per-error repair strategy classes;
- fuzzy, embedding, or hash-based target locators;
- whole-section or whole-report regeneration;
- SGCP-RAG collection or SNI content changes;
- a trained compact editor such as PURR;
- replicated SNI experiments before one fresh canonical pair completes.

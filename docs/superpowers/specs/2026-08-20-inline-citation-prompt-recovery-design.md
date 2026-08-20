# Inline Citation Prompt Recovery Design

## Goal

Make the existing generic semantic repair reliably remove an unsupported inline
PMID while preserving valid dataset-derived measurements as observations from
the current analysis. Keep all validators, target resolution, structured
`replace|delete`, bounded retries, and fail-closed publication unchanged.

## Failure Evidence

The user-authorized fresh no-SNI run reduced 19 hard errors to one, then stopped
on no progress. The remaining exact target was a Part 2 Summary sentence that
combined:

- valid current-analysis measurements: CDH1-ERBB3 Moran's R `0.4767` and
  combined score `0.8141`;
- an interpretive spatial co-localization statement; and
- inline PMID `28174229`.

The validator correctly reported that PMID 28174229 discusses ErbB2 biology but
does not support CDH1-ERBB3 spatial co-localization, Moran's R, or the combined
score. The repairer left the exact target unchanged after two passes.

## Chosen Design

Change only `_build_claim_prompt` in `scripts/repair_report.py`. Add binding
instructions for inline-citation issues:

1. When issue evidence reports no supporting PMID, never retain the flagged
   inline PMID.
2. Preserve measured values and pair names when they are current-analysis
   observations.
3. Rewrite the supported remainder explicitly as an observation from the
   current analysis, not as a literature-supported mechanism.
4. Remove unsupported literature attribution, causal interpretation, and
   mechanistic extension.
5. Choose structured `delete` only when no supported dataset-derived
   observation remains.

No error-code dispatch or deterministic sentence template is added. The
validator issue remains data; the common structured semantic path remains the
only executor.

## Safety

- Exact target boundaries remain unchanged.
- A replacement cannot add headings or new PMIDs.
- Existing PMIDs are not automatically trusted; the prompt must remove the
  flagged unsupported one.
- Dataset-derived values must not be invented or changed.
- The final validator remains the sole success authority.
- A failed replay remains fail-closed; no full pair starts.
- No new dependency, agent, graph, middleware, retry, validator rule, or
  deletion fallback is introduced.

## Verification

1. A prompt-contract unit test verifies all five binding instructions for the
   production-shaped issue.
2. Existing structured replace/delete, deterministic repair, citation handler,
   and guardrail tests stay green.
3. A disposable copy of
   `save_recovery_20260820T041110Z/pairs/pair-05/wiki-off` is revalidated with
   the fixed collection and qwen3.5:122b. It must start with the one remaining
   hard error and finish with zero, preserve headings and PMIDs, and leave the
   historical source unchanged.
4. Only after replay passes, one fresh pair 05 runs no-SNI then SNI.

## Out of Scope

- Changing Claim-RAG judgment criteria.
- Automatically stripping every unsupported PMID in Python.
- Adding per-code repair functions or sentence templates.
- Changing save recovery, Part generation, RAG, SNI, collection contents, or
  the Reporter.
- Starting SNI before a no-SNI pass.


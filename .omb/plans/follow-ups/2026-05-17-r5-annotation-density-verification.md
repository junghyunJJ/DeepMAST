---
date: 2026-05-17
status: pending-verification
related-pr: 15
related-issue: TBD
---

# R5 Verification: `[source:]` Annotation Density After PR #15 T8 GUIDANCE Strengthening

## Section 1 — R5 Risk Recap

The plan file `.omb/plans/2026-05-02-ollama-openai-provider-and-t8-guard.md` was **never committed to the
repository** (git history confirms: no matching path in any commit). The R5 risk is therefore reconstructed
from its primary source: PR #14 comment #4363865471
(https://github.com/junghyunJJ/DeepMAST/pull/14#issuecomment-4363865471) and the PR #15 merge commit
message (a20fa65).

**R5 risk (reconstructed):**

> In T10b (3-prompt T8 GUIDANCE strengthening, qwen3.6:35b alias @ port 7000), `[source:]` annotation
> count in `drug.md` dropped from **81** (v6 baseline, qwen3.5:35b @ port 6000) to **0**. Either the
> strengthened GUIDANCE text interferes with the source-attribution instruction in the prompt, or the
> qwen3.6:35b alias has different output behavior. PR #15 expanded the GUIDANCE strengthening from 3 to 5
> prompts (EVIDENCE_ASSESSOR, HYPOTHESIS_WRITER, REPORT_WRITER, SUMMARIZER, LEGACY_CRITIC) but explicitly
> deferred empirical verification of whether the AC2 regression ([source:] count = 0) still holds under
> the canonical setup (port 6000 + vanilla qwen3.5:35b + ollama-openai provider).

Exact wording from PR #14 comment #4363865471 (T10b results table):

> | `[source:]` annotations | 81 | **0** |
>
> AC2 regression — `[source:]` annotation count dropped to 0. Either the strengthened prompt guard
> interferes with the source-attribution prompt, or qwen3.6:35b alias has different output behavior
> than the v6 qwen3.5:35b. Worth a follow-up A/B test on port 6000 with vanilla qwen3.5:35b.

## Section 2 — Hypothesis Being Tested

Does the T8 GUIDANCE strengthening introduced in PR #15 (5-prompt expansion) cause the `[source:]`
annotation count in the final `drug.md` to drop significantly from the v6 baseline of 81?

The T10b observation (count = 0 after 3-prompt strengthening) may have been due to:
- (a) The strengthened GUIDANCE text crowding out or contradicting the source-attribution instruction
- (b) The qwen3.6:35b alias having weaker instruction following than vanilla qwen3.5:35b
- (c) The different port/daemon state (port 7000 vs port 6000)

PR #15 changed (a) further (expanding from 3 to 5 prompts) while (b) and (c) are held fixed by using
the canonical setup (port 6000, qwen3.5:35b). This verification isolates (a) vs (b)/(c).

### Architectural note (important — read before running)

PR #19 (1b3e824, merged 2026-05-14) significantly refactored the Summarizer subagent. The old
`save_drug_md` call (where the model wrote `[source: field]` annotations inline in prose) is now
replaced by `save_report_expansions` with structured `source_fields` and `source_provenance` JSON
fields. The `render_drug_md_from_expansions` step assembles `drug.md` from these expansions.

This means **the mechanism by which `[source:]` annotations appear in `drug.md` has changed**:
- Pre-PR #19: model wrote `[source: field]` text inline in prose → `save_drug_md` persisted it
- Post-PR #19: model populates `source_fields` in the JSON payload → `render_drug_md_from_expansions`
  may or may not render these as `[source: field]` text in the final markdown

The verification below counts raw `[source:]` occurrences in `drug.md` as the comparable metric, but
the owner should also check whether `render_drug_md_from_expansions` still emits that annotation format
at all before interpreting a count of 0 as regression.

## Section 3 — Verification Protocol

Run on your local machine with Ollama @ port 6000 (the canonical port from v6).

```bash
# Setup
export OLLAMA_HOST=http://localhost:6000
export OLLAMA_BASE_URL=http://localhost:6000
export LLM_PROVIDER=ollama-openai
export OLLAMA_MODEL=qwen3.5:35b

# Run the v9 drug-target pipeline (summarizer-only runner)
uv run python scripts/run_drug_target_summarizer_only.py \
    --provider ollama-openai --model qwen3.5:35b \
    --output /tmp/v9_drug.md --keep-data-dir

# Measure [source:] count
grep -c '\[source:' /tmp/v9_drug.md

# Also measure drug.md size for comparison to baseline
wc -c /tmp/v9_drug.md
```

### Additional diagnostic commands

```bash
# Check if render_drug_md_from_expansions emits [source:] at all
# (post-PR #19 architectural change — see Section 2 note)
grep -n '\[source:' /tmp/v9_drug.md | head -20

# Check SUMMARIZER_STATUS token in the run log
# (run the above with 2>&1 | tee /tmp/v9_run.log first)
grep -i "SUMMARIZER_STATUS" /tmp/v9_run.log
```

## Section 4 — Pass / Fail Criteria

| Criterion | PASS | FAIL |
|-----------|------|------|
| `[source:]` count | ≥ 60 (within 25% of v6 baseline 81) | < 60 (regression confirmed) |
| SUMMARIZER_STATUS | PASS or DONE | FAIL or INCOMPLETE |
| drug.md size | ≥ 30 000 bytes (within 28% of v6 41 679) | < 30 000 bytes |

**Historical data points:**
- v6 baseline (PR #14 comment, qwen3.5:35b @ port 6000): `[source:]` = **81**, drug.md = 41 679 B
- T10b (PR #14 comment, 3-prompt strengthening, qwen3.6:35b alias @ port 7000): `[source:]` = **0**, drug.md = 27 733 B

Note: if `grep -c '\[source:' /tmp/v9_drug.md` returns 0 but `render_drug_md_from_expansions` is
confirmed to no longer emit that format (see Section 2 architectural note), then R5 is **vacuous**
(the annotation mechanism changed) rather than a regression. Document this finding explicitly if so.

## Section 5 — Comparison Table (fill in after running)

| Run | Provider | Model | Port | drug.md size (B) | `[source:]` count | SUMMARIZER_STATUS | Notes |
|-----|----------|-------|------|------------------|-------------------|-------------------|-------|
| v6 baseline (PR #14 comment #4362184979) | ollama | qwen3.5:35b | 6000 | 41 679 | 81 | DONE | reference |
| T10b (PR #14 comment #4362184979, 3-prompt strengthening) | ollama | qwen3.6:35b alias | 7000 | 27 733 | 0 | FAIL | regression observed |
| v9 (PR #15, 5-prompt strengthening) — **TODO** | ollama-openai | qwen3.5:35b | 6000 | TBD | TBD | TBD | pending |

## Section 6 — Decision Tree

### If PASS (count ≥ 60)

1. Close R5 with empirical evidence:
   - Add a `## R5 — CLOSED` entry to the original plan (or to this file, since the plan was never committed)
   - Note the run parameters, count, and date
   - The open issue tracking this verification can be closed with "R5 PASS verified"

2. No code changes needed.

### If FAIL (count < 60, and not vacuous)

Confirm first that `render_drug_md_from_expansions` still emits `[source:]` text (Section 2 check).
If it does and the count is still < 60:

1. Open a follow-up plan at `.omb/plans/follow-ups/YYYY-MM-DD-r5-guidance-wording-fix.md` with:
   - Root cause: which GUIDANCE text addition crowds out source-attribution instruction
   - Fix options (in order of preference):
     a. Relocate the added sentence away from citation-adjacent instructions within each prompt
     b. Wrap the added GUIDANCE as a separate clearly-labeled `## FILESYSTEM ACCESS` block so it
        does not visually or semantically collide with `[source:]` annotation instructions
     c. Revert SUMMARIZER GUIDANCE (already removed by PR #19) and test if only the 3 original
        prompts (EVIDENCE_ASSESSOR, HYPOTHESIS_WRITER, REPORT_WRITER) cause regression
   - Re-run verification protocol (Section 3) after each candidate fix
   - Pass/fail criteria remain the same (Section 4)

2. Reference the GUID blocks (Section 7) when identifying which prompt to patch.

### If vacuous (count = 0 but `render_drug_md_from_expansions` confirmed not to emit `[source:]`)

The annotation format changed architecturally in PR #19. R5 is vacuous:
- Update the pass/fail criteria to use `source_provenance` JSON field density instead
- Re-run with: `grep -c '"source_fields"' /tmp/data_dir/expansions.json` as the comparable metric
- Document new baseline before closing R5

## Section 7 — Acceptance

The owner (@junghyunJJ) must complete one of the following within **1 week of this scaffold being merged**
(target: 2026-05-24):

- [ ] Fill in the comparison table in Section 5 and commit it back to this path (`git add` +
      `git commit --amend` or a new commit on the same branch)
- [ ] OR explicitly close R5 in a comment on the tracking issue with rationale (e.g., "vacuous —
      annotation format changed in PR #19") and close the issue

If neither happens by 2026-05-24, the issue should be escalated to a weekly triage checkpoint.

---

### Current GUIDANCE block status (as of 2026-05-17 audit)

The test `tests/agents/drug_target/test_summarizer_prompt_guard.py::test_guidance_text_is_byte_identical_across_all_subagent_prompts`
that PR #15 introduced was **deleted by PR #19** (1b3e824). The 5-way byte-identical invariant is
no longer enforced.

Current GUIDANCE block presence in `src/agents/drug_target/subagents/prompts.py`:

| Prompt constant | Has GUIDANCE block | Line | Notes |
|---|---|---|---|
| `EVIDENCE_ASSESSOR_PROMPT` | ✓ | 242 | byte-identical to others |
| `HYPOTHESIS_WRITER_PROMPT` | ✓ | 566 | byte-identical to others |
| `REPORT_WRITER_PROMPT` | ✓ | 948 | byte-identical to others |
| `SUMMARIZER_PROMPT_CORE` | ✗ | — | **removed by PR #19** (1b3e824) |
| `LEGACY_CRITIC_PROMPT_PERSISTED_REPORT` | ✓ | 1274 | byte-identical to others |

The GUIDANCE text present in the 4 remaining prompts is:

> GUIDANCE: If `ls` or `glob` returns an empty list for a path you expect to contain evidence files
> (for example `/evidence/`), do NOT conclude the directory is empty. The data is guaranteed present
> per the user prompt. Instead, call `load_evidence_files(data_dir)` — the project's canonical
> evidence loader — to retrieve evidence files. Do NOT call `read_file` directly under `/evidence/`
> (this is forbidden by the existing HARD rules in this prompt module). Always use virtual paths
> starting with `/evidence/...`. NEVER prepend the disk path of `data_dir` (such as
> `/private/tmp/...`) to filesystem operations.

All 4 remaining blocks are byte-identical (verified by manual grep).

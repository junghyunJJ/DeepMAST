---
title: "PR #19 Round 7 — Template citation fix (UNCITED_QUANTITATIVE)"
category: plan
status: ready
created: 2026-05-14
updated: 2026-05-14
worktree: feat/drug-target-agent-quality-gates
pr: https://github.com/junghyunJJ/DeepMAST/pull/19
head: 83b8c0f
tags: [drug-target, summarizer, simplification, validator, template, round-7]
relates-to:
  - .omb/plans/2026-05-13-drug-target-summarizer-simplification.md
  - docs/wiki/20_Lessons/drug-target-fail-closed-gates.md
  - https://github.com/junghyunJJ/DeepMAST/pull/19
---

# PR #19 — Round 7: Template-side UNCITED_QUANTITATIVE Fix

> **Read this first if you are a fresh session.** Six rounds of fixes (commits `567dcb1`, `0259bda`, `072a2bc`, `9e3f5cc`, `ee46263`, `83b8c0f`) landed in PR #19. Round 6 live LLM smoke (gpt-5.4) still fails — but the root cause is now identified as a **pre-existing server-side contract violation**, not an LLM-side regression. Architect + Code-reviewer dual review (deepwork) reached consensus: **ship PR #19 with a small targeted template-side patch + a regression test that locks the invariant**. This plan is the action list.

## 0. Context — where we are

| Field | Value |
|---|---|
| Branch | `feat/drug-target-agent-quality-gates` |
| Worktree | `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/feat/drug-target-agent-quality-gates` |
| HEAD | `83b8c0f` |
| PR | #19 — https://github.com/junghyunJJ/DeepMAST/pull/19 |
| Tests passing | 400 (drug_target + test_drug_target) excluding 3 pre-existing failures |
| Live smoke verdict | FAIL after Round 6 — `UNCITED_QUANTITATIVE` on template-baked Census lines |

### What round 6 proved

Live LLM smoke (gpt-5.4, ~7 min):
1. `lookup_provenance_value` worked — 7 successful calls returning exact `source_value`.
2. `save_report_expansions` succeeded on first try (`saved: true, errors: []`).
3. `render_drug_md_from_expansions` rendered `drug.md`.
4. `validate_drug_md` returned `valid: false, issue_count: 1, type: UNCITED_QUANTITATIVE`.
5. Retry attempt: **identical** failure — 10 Census lines like `- Census: risk_ratio=0.0523, p_value=0.0` flagged.
6. `SUMMARIZER_STATUS: FAIL`.

### Root cause (consensus from deepwork dual review)

- **Producer**: `skills/drug-target-reporting/templates/drug_report.md.j2:136-138` emits `  - Census: risk_ratio={{ p.census_rr }}, p_value={{ p.census_p }}` — NO source annotation.
- **Consumer**: `src/agents/drug_target/tools/stage_logic.py:3001-3068` UNCITED_QUANTITATIVE check requires `\.json|\[from\s+[^\]]+\]|stage[123]_…` — none of which appear in template output.
- **No actor can fix post-render**: LLM authoring surface (EXPAND markers only); deterministic renderer can only emit what the template says.
- **History**: `UNCITED_QUANTITATIVE` was introduced in commit `a61f8f8` on `main` (pre-PR-19, latent). The deleted critic+repair loop in `567dcb1` had a `save_drug_md` + REPAIR MODE prompt branch that allowed LLM line-level patching — that was the implicit masking layer. PR #19 removed the masking without removing the conflict.

### Why this is NOT a reason to revert PR #19 (architect's convergence argument)

R1-R5 were all in the LLM↔tool contract space — exactly the surface the simplification was designed to harden. R6 is the first defect that does NOT touch the LLM at all (two Python modules disagree). That's a different failure class and signals the LLM-side hardening has converged. R6 needs a targeted server-side fix, not an architectural retreat.

## 1. P0 — must fix before merge

### P0-1 — Template-side fix (CAC-1)

**Files**:
- `src/agents/drug_target/tools/drug_report_html.py:794-803` (`_preformat_cards` — add `pair_file` field)
- `skills/drug-target-reporting/templates/drug_report.md.j2:137` (Census line — append citation)

**Why template-side over validator-side**:
- Data is already in scope: `src/agents/drug_target/tools/stage_logic.py:2122` has `pair_key = f"{ligand}_{receptor}"`.
- Producer becomes validator-compliant by construction; validator stays paranoid against LLM hallucinations elsewhere.
- ~10 lines of code + Jinja edit. Reversible.

**Concrete edits**:

In `_preformat_cards` (drug_report_html.py:794-803), where each pair entry is constructed, add:
```python
"pair_file": f"stage1_{ligand}--{receptor}.json",
```

In `drug_report.md.j2:136-138`, change:
```jinja
{% if p.census_rr is not none %}
  - Census: risk_ratio={{ p.census_rr }}, p_value={{ p.census_p }}
{% endif %}
```
to:
```jinja
{% if p.census_rr is not none %}
  - Census: risk_ratio={{ p.census_rr }}, p_value={{ p.census_p }} [from {{ p.pair_file }}]
{% endif %}
```

(Verify the variable names against the actual `_preformat_cards` body — `ligand`/`receptor` may be `lig`/`rec` or pair-key-split form. Read first.)

### P0-2 — Round-trip regression test (CAC-2)

**File**: new `tests/agents/drug_target/test_summarizer_round_trip.py`

**Shape**:
```python
def test_template_passes_validate_drug_md_before_llm_expansion(tmp_path):
    """Producer-validator invariant: build_evidence_summary's template MUST
    pass validate_drug_md before any LLM authoring runs. This test fails
    on `main` today — that's the regression evidence for PR #19's round 6."""
    # Copy fixture evidence to tmp_path/evidence
    # Call build_evidence_summary(tmp_path, "pulmonary fibrosis")
    # Author a minimal valid `expansions` payload for all required_slot_ids
    #   from `<tmp_path>/expansion_schema_spec.json`
    # Call save_report_expansions, render_drug_md_from_expansions
    # Assert validate_drug_md(tmp_path) returns {"valid": True, "issue_count": 0}
```

Use `tests/agents/drug_target/fixtures/baseline_hallucinated/evidence/` as the source fixture. The minimal `expansions` can reuse the helper pattern from `test_summarizer_dict_spec.py` TS-07/TS-08 but scaled to all `required_slot_ids` from the spec file.

**Acceptance**: this test must FAIL on `83b8c0f` (proves the bug exists) and PASS after P0-1 lands.

## 2. P1 — should fix in the same PR if scope allows

### P1-1 — DS-2: UNCITED_QUANTITATIVE bracketing tests

**File**: `tests/agents/drug_target/test_drug_md_new_flags.py`

Add two unit tests:
- POSITIVE: a hand-crafted `drug.md` line `OR=2.1 in narrative prose` (without citation) → UNCITED_QUANTITATIVE must FIRE.
- NEGATIVE: the template-baked Census line + the new `[from stage1_…json]` annotation → UNCITED_QUANTITATIVE must NOT fire.

### P1-2 — DS-1: Path-traversal guard on `data_dir`

**Files**: `src/agents/drug_target/tools/report_expansion_schema.py:583, 647` (and any other tool that accepts `data_dir`)

Add `_validate_data_dir(data_dir, allowed_roots)` helper:
- Resolve path
- Assert resolved is under one of `allowed_roots`
- Return structured error JSON if out-of-bounds

Move `base.mkdir(parents=True, exist_ok=True)` AFTER validation in `save_report_expansions`.

### P1-3 — AS-3 / M4: drop unreachable retry sub-rubric from SUMMARIZER_PROMPT

**File**: `src/agents/drug_target/subagents/prompts.py` Step 5 retry block

Replace the current advice ("Fix by either adding the annotation or removing the quantitative claim") with:
> "If `UNCITED_QUANTITATIVE` fires on a Census/template line, it indicates a template-generator bug, not an LLM authoring bug. Emit `SUMMARIZER_STATUS: FAIL` with the line list and stop. Do not waste retry budget on lines outside your authoring surface."

## 3. Deferred (follow-up issue/PR)

| Item | File | Severity |
|---|---|---|
| Template audit for other quantitative emissions | `drug_report.md.j2:78` (filter table currently safe by table-row exemption only) | MEDIUM |
| `coexpression_detected` boolean bug | `stage_logic.py:2371` | HIGH (separate bug, off-topic for R6) |
| `validate_report_expansions` purity | `report_expansion_schema.py:472-478` | HIGH (foot-gun) |
| `lookup_provenance_value` error envelope inconsistency | `report_expansion_schema.py:650-676` | MEDIUM |
| `claim_type` loose typing → Literal | `report_expansion_schema.py:397` | MEDIUM |
| `count` claim variable shadowing | `report_expansion_schema.py:386` | MEDIUM |
| `_EXPAND_RE` regex drift between two files | `report_expansion_schema.py:17` vs `stage_logic.py:2986` | MEDIUM |
| `stage_logic.py` 4123-line file size violation | `stage_logic.py` | LOW (pre-existing) |
| Smoke script `validate_drug_md` issues pretty-print | `scripts/run_drug_target_summarizer_only.py:280-307` | LOW |
| `canonical_json_hash` caching | `report_expansion_schema.py:475` | LOW |

Open these as `gh issue create` after the PR merges.

## 4. Verification — how to know we're done

```bash
cd /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/feat/drug-target-agent-quality-gates

# 1. Unit tests
.venv/bin/python -m pytest tests/agents/drug_target/test_summarizer_dict_spec.py \
                          tests/agents/drug_target/test_summarizer_round_trip.py \
                          tests/agents/drug_target/test_drug_md_new_flags.py -v
#   Expected: all pass. test_summarizer_round_trip + the two UNCITED_QUANTITATIVE
#   bracketing tests are NEW.

# 2. Full regression
.venv/bin/python -m pytest tests/agents/drug_target/ tests/test_drug_target.py --tb=no -q \
  --deselect tests/agents/drug_target/test_drug_md_new_flags.py::TestWrongApprovalYearExtension::test_does_not_fire_on_drug_x_with_matching_year \
  --deselect tests/agents/drug_target/test_drug_md_new_flags.py::TestUngroundedMechanism::test_fires_when_mechanism_field_empty \
  --deselect tests/test_drug_target.py::TestIntegration::test_create_drug_target_agent_disables_skill_loading_in_docker_mode
#   Expected: 402+ passed (current 400 + P0-2 round-trip + P1-1 bracketing×2).

# 3. Lint
ruff check src/agents/drug_target/tools/drug_report_html.py \
           skills/drug-target-reporting/templates/drug_report.md.j2 \
           tests/agents/drug_target/test_summarizer_round_trip.py \
           src/agents/drug_target/tools/report_expansion_schema.py \
           src/agents/drug_target/subagents/prompts.py

# 4. Live LLM smoke (manual — actual proof)
.venv/bin/python scripts/run_drug_target_summarizer_only.py \
  --provider openai --model gpt-5.4 --keep-data-dir
#   Expected: SUMMARIZER_STATUS: PASS, drug.md + drug_report.html exist, DONE.
```

## 5. Open questions / risks

- **Round-7 LOW risk** (architect assessment): the same "deterministic citation at render time" principle covers any future quantitative template lines, provided P1-1 + the template audit (deferred) happen.
- **Template audit deferral**: if the audit (deferred) finds more quantitative emissions without citations, those will fail the round-trip test (P0-2). That's the *point* — the test forces the audit early.
- **`coexpression_detected` (DS-3 / H3)**: real bug, not R6-blocking but propagates to prose interpretation. Track as separate issue.

## 6. Strategic decision recorded

PR #19's R01 (b') accepted regression — "delete critic+repair loop and rely on prompt + skill + validate_drug_md" — IS imposing real cost; rounds 1-6 are evidence. **But the convergence pattern** (R1-R5 = LLM↔tool, R6 = first server-side contract bug) supports shipping with a targeted fix rather than reverting. Architect verdict: **(i) Ship**. Code-reviewer verdict: **REQUEST CHANGES blocking on P0-1 + P0-2 only**.

Strategic options (ii) Python deterministic composer, (iii) Revert, (iv) Critic tool — all rejected by both reviewers.

## 7. How to resume in a fresh session

```bash
cd /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/worktrees/feat/drug-target-agent-quality-gates
git log --oneline -7    # confirm HEAD=83b8c0f
cat .omb/plans/2026-05-14-pr19-round7-template-citation.md    # this file
gh pr view 19           # see PR + comment with consensus
# Then: implement §1 P0-1, P0-2 → commit → §2 P1 → commit → §4 verify → push
```

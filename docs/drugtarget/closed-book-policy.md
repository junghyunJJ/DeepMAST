---
title: Closed-Book Hallucination-Reduction Policy
category: architecture
status: accepted
created: 2026-04-29
updated: 2026-04-29
tags: drug-target, hallucination, validation, quality-gate, adr
relates-to: src/agents/drug_target/tools/stage_logic.py, src/agents/drug_target/subagents/configs.py, src/agents/drug_target/subagents/critic_schema.py
depends-on: docs/drugtarget/drug_target_agent_reference.md
---

# Closed-Book Hallucination-Reduction Policy

**Status:** Accepted — 2026-04-29

---

## Context

A manual audit of `res_ipf_qwen3/drug.md` established a baseline of **6 P0 hallucinations**
frozen in `tests/agents/drug_target/fixtures/baseline_hallucinated/`.

The failures split into two categories:

**Strict fabrications (3):**

| Claim | Root cause |
|-------|-----------|
| Ocriplasmin approval year listed as 2010 | Correct year is 2012; no source field in evidence |
| Lovastatin→ITGB2 mechanistic link citing `known_drugs.json` | File does not exist; citation invented |
| File references with `*_FAILED` suffix | Report writer echoed internal error tokens as prose |

**Ungrounded-but-true claims (3):**

| Claim | Root cause |
|-------|-----------|
| Ibalizumab FDA approval year 2018 | Correct, but not present in any `resolved_drugs.json` field |
| Ocriplasmin vitreous-humor mechanism | Correct, but inferred; no `[source: ...]` annotation |
| AS-1409 classified as aptamer | Correct, but model applied domain knowledge not in evidence files |

The common root is **open-book generation**: the report writer drew on parametric model knowledge
rather than restricting prose to fields present in the evidence bundle. No model upgrade was
required; the fix is architectural.

---

## Decision

Enforce **closed-book strict generation** through five coordinated layers:

### Layer 1 — Closed-Book Mandate in prompts and SKILL.md

A `## Closed-Book Mandate` section is prepended to `REPORT_WRITER_PROMPT` (and mirrored in the
drug-target SKILL.md). The rule is explicit:

- Every factual claim must cite `[source: <field>]` where `<field>` is a key present in the
  evidence bundle loaded for that gene/drug.
- When a field is absent, substitute the literal phrase `not available in source data` — never
  infer or paraphrase from model knowledge.
- `[source: interpretation]` is permitted only when hedged language is used
  (`suggests`, `indicates`, `consistent with`).

### Layer 2 — Validator extension (`validate_drug_md`)

Four new flags and one extended flag were added to `validate_drug_md`
(`src/agents/drug_target/tools/stage_logic.py`):

| Flag | Trigger | Severity |
|------|---------|----------|
| `FABRICATED_DRUG_NAME` | Drug name in prose not found in 3-source allowlist union: `resolved_drugs` / stage-3 `matched_drugs` / stage-3 `preclinical_compounds` (casefold-normalized) | P0 |
| `FABRICATED_FILE_REFERENCE` | `*_FAILED` suffix in any bullet, bracket, or bare reference (unconditional); other file-pattern matches also covered | P0 |
| `UNGROUNDED_MECHANISM` | Verb regex (`degrades?`, `cleaves?`, `antagoni[sz]es?`, …) within 50-token window of a drug name, cross-checked against `mechanism_of_action` field (uses `resolved_name` fallback for ChEMBL-resolved entries) | P0 |
| `UNANCHORED_SENTENCE` | `<!-- EXPAND -->` region sentence missing `[source: <field>]` annotation, or annotation references a field absent from the evidence bundle | P0 |
| `WRONG_APPROVAL_YEAR` (extended) | Also fires when drug is absent from `resolved_drugs.json` OR `first_approval` field is null | P0 |

### Layer 3 — Sentence-level provenance

Every prose sentence inside `<!-- EXPAND -->` regions must carry a `[source: <field>]`
annotation. The `UNANCHORED_SENTENCE` flag (Layer 2) enforces this programmatically.

### Layer 4 — Critic redesign

The critic subagent schema (`src/agents/drug_target/subagents/critic_schema.py`) was extended
with an additive `claim_verdicts` array **nested inside the existing envelope**. This preserves
backward compatibility with the SUMMARIZER's `repair_instructions` consumer while adding
per-claim provenance checking.

Evidence slices are injected via
`load_evidence_files("evidence/_critic_slices/<gene>.json")` per gene and hypothesis,
keeping each critic invocation within context limits.

### Layer 5 — Programmatic auto-revise loop

`run_summarizer_loop` (`src/agents/drug_target/subagents/configs.py:614`) drives a repair cycle:

- Maximum **2 cycles** (`max_cycles=2`).
- On each cycle: run validator → if P0 flags remain, enter REPAIR MODE in `REPORT_WRITER_PROMPT`.
- REPAIR MODE loads the existing `drug.md` via `load_evidence_files` and applies surgical edits
  to flagged sentences only — it does NOT regenerate the full report skeleton.
- After 2 cycles with P0 flags unresolved, the loop returns `status: "BLOCKED"` with the
  remaining P0 findings as the blocker payload.

---

## Consequences

### Positive

- **8/8 baseline hallucinations detected** by the parametrized regression suite
  (`tests/agents/drug_target/test_drug_md_hallucination_regression.py`).
- Validator unit tests pass: `tests/agents/drug_target/test_drug_md_new_flags.py` (27 tests).
- Test suite: run `pytest tests/agents/drug_target/ -v` → 97 passed + 2 xpassed.
- Critic→repair oscillation is reduced: Phase 2 EXPAND fill + first surgical repair work
  correctly in the common case.

### Known follow-up items

- **Filesystem backend wiring for summarizer DeepAgent:** The summarizer's `ls`/`glob` built-in
  tools are not yet wired to the evidence directory backend. This affects E2E reproducibility
  but does not affect validator correctness or the test suite.
- **Rare wrap-up regression:** In edge cases where the critic fires on the final wrap-up
  sentence, a second repair cycle may still leave a residual WARNING. Tracked as a follow-up.

### E2E stabilization landed (2026-04-29)

- `FilesystemBackend(root_dir=data_dir, virtual_mode=True)` wires `ls`/`glob`/`read_file` to
  real disk; `BuildEvidenceSummaryGuardMiddleware` mechanically prevents the second
  `build_evidence_summary` call within a single agent run; `RepairCycleCounterMiddleware`
  enforces the 2-cycle critic→writer cap at runtime. The previous oscillation
  (38.9 KB → 28 KB skeleton reset) is mechanically impossible.
- Live qwen3.5:35b run against the frozen baseline produces a 42 KB `drug.md` with 0 EXPAND
  markers, 0 P0 findings from `validate_drug_md`, and 5 of 6 known hallucinations resolved
  (the 6th — `known_drugs.json` reference — is inherited from upstream `hypothesis_report.json`
  and is tracked as a follow-up at the hypothesis-writer / pipeline-filter layer).

---

## Verification

**Unit + integration tests:**

```bash
pytest tests/agents/drug_target/ -v
# Expected: 114 passed, 0 xfail/xpass
# (xfail decorators removed at lines 218/262 of test_drug_md_hallucination_regression.py)
```

**Phase 5 E2E reproduction script (requires Ollama at `OLLAMA_HOST`):**

```bash
OLLAMA_HOST=http://localhost:6000 \
LANGCHAIN_TRACING_V2=false \
OMB_CRITIC_SLICES_KEEP=1 \
PYTHONUNBUFFERED=1 \
uv run python scripts/run_drug_target_summarizer_only.py \
  --model qwen3.5:35b \
  --keep-data-dir
```

---

## References

| Resource | Path |
|----------|------|
| Implementation plan | `.omb/plans/2026-04-29-drug-target-report-hallucination-reduction.md` |
| Frozen baseline fixtures | `tests/agents/drug_target/fixtures/baseline_hallucinated/` |
| Regression suite | `tests/agents/drug_target/test_drug_md_hallucination_regression.py` |
| New-flag unit tests | `tests/agents/drug_target/test_drug_md_new_flags.py` |
| Critic schema | `src/agents/drug_target/subagents/critic_schema.py` |
| Validator source | `src/agents/drug_target/tools/stage_logic.py` |
| Loop controller | `src/agents/drug_target/subagents/configs.py` |
| Agent reference | `docs/drugtarget/drug_target_agent_reference.md` |

---

## Resolution Log

| Date | Plan | Outcome |
|------|------|---------|
| 2026-04-29 | `2026-04-29-drug-target-report-hallucination-reduction.md` (PR #10, commit 175def6) | Phases 0-5 done. Closed-book mandate, 4 new validator flags + 1 extended, sentence-level provenance, critic redesign, programmatic counter helper. T20-T22 deferred to follow-up plan. |
| 2026-04-29 | `2026-04-29-drug-target-closed-book-e2e-stabilization.md` (this commit) | E2E stabilization landed: filesystem-backend wired, two runtime middlewares (single-call guard + cycle counter), prompt tightening, regenerated fixture, 5/6 hallucinations resolved. Open follow-up: `known_drugs.json` reference inherited from upstream `hypothesis_report.json` (hypothesis-writer scope, not report-writer). |

### Follow-ups

- Hypothesis-writer or pipeline-filter fix to strip `evidence_files` entries that are not
  present on disk before report-writer consumes `hypothesis_report.json`. Tracked as a
  separate plan.
- Drug-profile under-claim: all 7 candidates state "No known drugs targeting this gene";
  this is consistent with `stage3_*.json` (chembl-only) but contradicts `resolved_drugs.json`
  (OpenTargets-sourced). Audit suggested in
  `tests/agents/drug_target/fixtures/regenerated/_audit_report.md`.

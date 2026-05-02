---
title: Closed-Book Hallucination-Reduction Policy
category: architecture
status: accepted
created: 2026-04-29
updated: 2026-05-02
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

## Provider Selection

The drug-target pipeline supports multiple LLM providers via the `LLM_PROVIDER` env var or `--provider` CLI flag. As of 2026-05-02, the following providers are supported:

| Provider | Use Case | Notes |
|----------|----------|-------|
| `openai` | OpenAI API (default for cloud) | Requires `OPENAI_API_KEY` |
| `claude` | Anthropic Claude | Requires `ANTHROPIC_API_KEY` |
| `google` | Google Gemini | Requires `GOOGLE_API_KEY` |
| `openrouter` | OpenRouter aggregator | Requires `OPENROUTER_API_KEY` |
| `ollama` | Local Ollama (native ChatOllama) | Default port 6000 |
| `ollama-openai` | Local Ollama via OpenAI-compatible endpoint | Default port 11434 |

### When to use `ollama-openai`

Use the `ollama-openai` provider when:
- Running `qwen3.5:35b` or similar models on Ollama with complex multi-tool schemas
- Encountering `XML syntax error: element <function> closed by </parameter>` errors
- The native `ollama` provider's `PARSER qwen3.5` translation layer corrupts tool-call output

This provider bypasses the PARSER layer by routing through Ollama's OpenAI-compatible
`/v1/chat/completions` endpoint (Ollama 0.20+) and uses `langchain-openai`'s `ChatOpenAI`
to emit native JSON tool-calls.

### Canonical smoke command

```bash
LLM_PROVIDER=ollama-openai \
LLM_MODEL=qwen3.5:35b \
OLLAMA_BASE_URL=http://localhost:5000 \
python scripts/run_drug_target_summarizer_only.py
```

Per-prompt smoke status (PR body MUST attest):
- AC4a SUMMARIZER schema: empirically validated per PR #14 comment #4363865471 (178s, 2 valid JSON tool-calls, 0 XML errors)
- AC4b REPORT_WRITER schema: deferred to verification PR
- AC4c CRITIC schema: deferred to verification PR

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
| 2026-04-30 | `2026-04-30-drug-target-closed-book-followups.md` | All 6 phases landed. Three guards added to close the residual gaps from PR #11 audit: (1) `filter_hypothesis_evidence_files` pipeline filter wired into `_CriticSliceWrapper.{invoke,ainvoke}` cleans `hypothesis_report.json` before SUMMARIZER consumes it. Two passes: list-key pass (drops `evidence_files` and `evidence_references` entries pointing to nonexistent files or ending in `_FAILED`); prose pass (rewrites `<file>.json_FAILED` → `<file>.json` in any string anywhere in the document, including `falsifiable_prediction` / `validation_approach` prose where the LLM can echo the suffix verbatim). (2) `AnnotationDensityMiddleware` rejects `save_drug_md` when prose has ≥10 sentences but <10 `[source: <field>]` annotations, replacing prompt-only enforcement with a programmatic guard. (3) REPORT_WRITER_PROMPT drug-profile data source broadened to the allowlist UNION (`resolved_drugs.json[*].name` ∪ `stage3_<gene>.json[*].matched_drugs[*].name` ∪ `stage3_<gene>.json[*].preclinical_compounds[*].name`) so featured candidates with OpenTargets drugs no longer collapse to "No known drugs". |
| 2026-05-01 | `2026-04-30-drug-target-closed-book-followups.md` (E2E reproduction + audit) | Live E2E reproduction (qwen3.5:35b on Ollama via `scripts/run_drug_target_summarizer_only.py --keep-data-dir`) regenerated `tests/agents/drug_target/fixtures/regenerated/drug.md` (41679 bytes, 502 lines) in 38.8 minutes. **AC1 = 0** nonexistent-file refs (down from 1 in PR #11; `known_drugs.json`, `_FAILED` suffix, `ot_*.json` all eliminated). **AC2 = 81** `[source:]` annotations (up from 1 in PR #11; threshold ≥10 satisfied). **AC4** full pytest: 129 passed (16 new unit tests across 3 test files), 2 pre-existing failures unrelated to this plan, 2 xfailed. AC3 (drug-profile coverage) is N/A on the baseline_hallucinated fixture because `resolved_drugs.json` is empty and all stage3 files have empty `matched_drugs` — the guard 3 prompt change is verified by unit tests, but the union itself is empty so "No known drugs" is the correct output for this fixture. A separate run with non-empty OpenTargets data would be needed to demonstrate drug-name population. Earlier qwen3.5:122b retries (v3, v4, v5) showed inconsistent behavior — v3 gave up at 6.8 min after a path-resolution misread, v4 echoed `_FAILED` from `falsifiable_prediction` prose (which prompted the prose-strip extension), v5 hung for 1.5 hours without producing drug.md; 35b proved more stable for this fixture. |
| 2026-05-01 | `2026-05-01-deepagents-filesystem-backend-ls-glob-investigation.md` | **Diagnosis + observability landing** for the long-suspected `FilesystemBackend(virtual_mode=True)` empty-result bug that caused v3 (qwen3.5:122b) and v7 (gemma4:31b) to give up. **Root cause: HYPOTHESIS (b) — LLM path mistake.** Under deepagents 0.5.3 `virtual_mode=True`, the model is told `data_dir: /private/tmp/drug_target_summarizer_XXX/data_dir` in its prompt and naively prepends that absolute disk path when calling `ls`/`glob`. `_resolve_path` then treats the absolute path as a *virtual* path under cwd, looks for `<cwd>/private/tmp/...`, finds nothing, and returns `LsResult(entries=[])`. The correct virtual form `ls /evidence` returns 35 entries. Captured live in T4 instrumented gemma4:31b run on 2026-05-01 — backend log shows `[ts=1777667099] tool=ls path=/private/tmp/drug_target_t4_out/data_dir/evidence result_count=0` vs `[ts=1777667077] tool=ls path=/evidence result_count=35`. **Phase 0+1+2 landed**: T0.7a/b live-runner wiring fix (`create_summarizer_agent` factory now accepts `data_dir` kwarg with mutual-exclusivity guard, paired with `scripts/run_drug_target_summarizer_only.py` passing `data_dir=str(data_dir)`); T1+T2 standalone backend RED matrix (0 RED at backend layer; bug confirmed at LLM layer per T2.5); T3 `LoggingAndFallbackFilesystemBackend` wrapper (logging only — T6 fallback **SKIPPED** per CP-P1-002 because RED is at LLM layer, not backend); T3.5 `LoggingFilesystemMiddleware` standalone (mechanism (b) — `wrap_tool_call` interception; not yet wired to avoid stack risk); T3.6 `JsonlFormatter` + 5-phase `_CriticSliceWrapper` lifecycle logger; CLI flags `--log-level` / `--log-file` added. **Prompt-side fix landed**: T8 GUIDANCE sentence appended to `SUMMARIZER_PROMPT` / `REPORT_WRITER_PROMPT` / `CRITIC_PROMPT` directing the LLM to call `load_evidence_files(data_dir)` whenever ls/glob returns empty unexpectedly, with CP-P1-003 sanitization and CP-P2-005 negation-aware regex regression test (8 tests, all pass). **Plan accuracy gap discovered**: §2.2.1 claimed `_resolve_path` blocks `~` for virtual_mode=True, but on 0.5.3 `_resolve_path` prepends `/` BEFORE checking `startswith("~")`, so `ls("~/secrets")` → `vpath="/~/secrets"` which is NOT rejected (only middleware-layer `validate_path` blocks `~`); documented as `xfail` test `test_ls_blocks_tilde_path_xfail_documented_upstream_gap`. **Environment note**: worktree was synced from main's uncommitted `pyproject.toml` pin `deepagents==0.5.3` — the committed pin was `>=0.4.4` which made an early `uv add --dev` resolve to 0.4.4 with the old `ls_info`/`glob_info` API; recommend committing the pin to main and rebasing the worktree branch. T9 (gemma4:31b post-fix verification) and T10 (qwen3.5:35b regression) deferred to a follow-up session — diagnosis and prompt-side fix are sufficient to unblock; live-LLM verification is a separate compute commitment. |

### Follow-ups

- Hypothesis-writer prompt is intentionally left alone — the new pipeline filter is the safety net. If the model continues to emit nonexistent `evidence_files` or `evidence_references`, a separate hypothesis-writer prompt plan can address the root cause.
- AC3 (drug-profile coverage) needs a non-empty `resolved_drugs.json` fixture to verify end-to-end. Today's baseline has empty drug arrays. A separate plan can either source a richer fixture or extend the baseline with synthetic OpenTargets drug entries to prove the allowlist-union prompt works in practice.
- qwen3.5:122b instability under this pipeline (v3/v4/v5 above) deserves its own investigation — possible causes include FilesystemBackend `virtual_mode` interaction with longer-context models, model-specific tool-call latency, or Ollama session caching effects that don't surface on 35b.
- Finalization gate failure (`target_assessment.json` missing after RepairCycleCounterMiddleware blocks the third report_writer invocation) is a separate hardening item — the SUMMARIZER currently exits BLOCKED with a usable `drug.md` but no `target_assessment.json`. A pre-write or `build_evidence_summary` lifecycle change is needed.

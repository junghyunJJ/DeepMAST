---
title: Closed-Book Hallucination-Reduction Policy
category: architecture
status: accepted
created: 2026-04-29
updated: 2026-07-15
tags: drug-target, hallucination, validation, quality-gate, adr
relates-to: src/agents/drug_target/tools/stage_logic.py, src/agents/drug_target/subagents/configs.py, src/agents/drug_target/subagents/critic_schema.py
depends-on: docs/drugtarget/drug_target_agent_reference.md
---

## 2026-07-15 production migration

`DrugReportGuardrailMiddleware` is the bounded production owner for direct Markdown validation, repair, Part 4, HTML, audits, and publication. The 2026-05-19 finalizer architecture is historical and superseded for production; `legacy_hypothesis` remains the explicit compatibility path only.

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

### Layer 5 — Historical 2026-05-19 finalizer architecture (superseded)

> **Note**: The summarizer-side Layer 5 helpers (`run_summarizer_loop`, `RepairCycleCounterMiddleware`,
> `synthesize_repair_instructions`) are **superseded** as of 2026-05-19. The `summarizer` subagent
> and its repair loop were removed; `src/agents/drug_target/subagents/summarizer/` was deleted.
> The following describes the retained **legacy compatibility** Layer 5 responsibilities in the
> `finalize_report` node; guarded production uses `report_writer` plus
> `DrugReportGuardrailMiddleware` instead.

The legacy compatibility `finalize_report` node (`src/agents/drug_target/finalize_report.py`)
enforces three
programmatic validation sub-layers inside `_persist_and_validate()`, **before any disk writes**:

**Validation gate** — `validate_report_expansions(data_dir, payload.model_dump())`
(`src/agents/drug_target/tools/report_expansion_schema.py`): schema validation of the
`ReportExpansionsPayload` structured output returned by the single LLM call. Errors are
classified as `validation_failed`.

**Cited-only provenance check** — `validate_cited_only_provenance(payload, reference_card)`
(`src/agents/drug_target/validators.py`): verifies that every sentence's
`source_provenance.source_file::source_field` key exists in the reference card's provenance
index (built by `_build_provenance_index(reference_card)`). Errors are classified as
`cited_only_violation` and take precedence over schema errors in `_classify_validation_error()`.

**Legacy token-budget fail-closed gate** — enforced in `finalize_report` before the LLM call
(`finalize_report.py:81–84`): if `len(json.dumps(evidence)) // 4 > 20_000`, the node returns
immediately with `evidence_truncated=True` and no LLM invocation. This is a hard pre-check,
not a post-validation step.

If any of these legacy compatibility checks fail, `finalize_report` sets `report_finalization_error` and returns
without writing any artifact to disk. This replaces the previous LLM-driven repair loop with
deterministic Python fail-closed semantics.

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

**E2E reproduction (post-2026-05-19 migration — `run_drug_target_summarizer_only.py` deleted):**

> `scripts/run_drug_target_summarizer_only.py` was deleted as part of the 2026-05-19
> legacy finalizer migration. Use the guarded writer-only, E2E, or BC runners for production;
> `scripts/run_drug_target_traced.py` remains a legacy compatibility runner.

```bash
LLM_PROVIDER=openrouter \
PYTHONUNBUFFERED=1 \
uv run python scripts/run_drug_target_traced.py \
  --data-dir /path/to/workspace
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

### 2026-05-19 — summarizer → finalize_report node migration

**Plan:** `.omb/plans/2026-05-19-drug-target-finalize-node.md`

**Outcome:** Layer 5 summarizer-side helpers (`run_summarizer_loop`, `RepairCycleCounterMiddleware`, `synthesize_repair_instructions`) superseded. The `summarizer` subagent and `subagents/summarizer/` directory were deleted. Legacy compatibility responsibilities migrated to three deterministic validation sub-layers inside `finalize_report._persist_and_validate()`:
- `validate_report_expansions()` (schema gate, existing)
- `validate_cited_only_provenance()` (NEW, `validators.py`)
- Token-budget fail-closed gate (NEW, `finalize_report.py:81–84`, before LLM call)

All three checks run before any disk writes. The `report_finalization_error` state field is the single observable failure surface, replacing `SUMMARIZER_STATUS: FAIL`.

### 2026-05-13 — Summarizer simplification

**Plan:** `.omb/plans/2026-05-13-drug-target-summarizer-simplification.md`

**Outcome:** the CompiledSubAgent shell + inner `report_writer`/`critic` workers
+ 6 summarizer-scoped middleware classes + Python repair loop were replaced
by a single flat dict subagent that executes a fixed 6-step tool sequence:
`build_evidence_summary` → `load_evidence_files` → `save_report_expansions`
→ `render_drug_md_from_expansions` → `validate_drug_md` →
`generate_drug_html_report`.

Middleware-level fail-closed enforcement was deliberately reduced:
`BuildEvidenceSummaryGuardMiddleware`, `RepairCycleCounterMiddleware`,
`AnnotationDensityMiddleware`, and `FrozenTemplateSpanMiddleware` were
deleted; their checks moved to prompt language ("call once", "max 2 retries")
and to the deterministic assembly of `drug.md` by
`render_drug_md_from_expansions` (which the LLM never hand-writes).

`SummarizerFinalizationGuardMiddleware` — the most important gate — was
**retained and adapted**: it now guards `generate_drug_html_report` against
`validate_drug_md` returning `valid=true` (previously guarded `save_drug_md`
and `task(report_writer)` against `validate_drug_report_finalization`).

Deleted modules: `subagents/critic_schema.py`, `subagents/summarizer/fs_backend.py`
(`LoggingAndFallbackFilesystemBackend`), `subagents/summarizer/fs_middleware.py`
(`LoggingFilesystemMiddleware`). Deleted helpers from `subagents/configs.py`:
`run_summarizer_loop`, `synthesize_repair_instructions`,
`write_critic_slices`, `cleanup_critic_slices`.
`DrugTargetConfig.report_writer_skill_names` renamed to
`summarizer_skill_names` and restricted to `("drug-target-reporting",)`.

**Accepted regression:** a non-compliant LLM can skip the prompt-level "max 2
retries" budget, call `build_evidence_summary` twice, or emit
`SUMMARIZER_STATUS: PASS` without `generate_drug_html_report`. The mechanical
gate via `SummarizerFinalizationGuardMiddleware` ensures HTML cannot land
without a `valid=true` validator pass, so a `SUMMARIZER_STATUS: PASS` token
without an HTML artifact remains a downstream-detectable inconsistency.

The orchestrator's `SUMMARIZER_STATUS: PASS|FAIL` literal-line contract is
unchanged.

**Tests:** 20 legacy summarizer/middleware tests deleted; 6 focused tests
added under `tests/agents/drug_target/test_summarizer_dict_spec.py`
(TS-01..TS-06). Verification: 394 drug-target tests pass.

See `docs/wiki/20_Lessons/drug-target-fail-closed-gates.md` (2026-05-13 update)
for the option-comparison rationale and the per-class accepted-regression table.

### Follow-ups

- Hypothesis-writer prompt is intentionally left alone — the new pipeline filter is the safety net. If the model continues to emit nonexistent `evidence_files` or `evidence_references`, a separate hypothesis-writer prompt plan can address the root cause.
- AC3 (drug-profile coverage) needs a non-empty `resolved_drugs.json` fixture to verify end-to-end. Today's baseline has empty drug arrays. A separate plan can either source a richer fixture or extend the baseline with synthetic OpenTargets drug entries to prove the allowlist-union prompt works in practice.
- qwen3.5:122b instability under this pipeline (v3/v4/v5 above) deserves its own investigation — possible causes include FilesystemBackend `virtual_mode` interaction with longer-context models, model-specific tool-call latency, or Ollama session caching effects that don't surface on 35b.
- Finalization gate failure (`target_assessment.json` missing after RepairCycleCounterMiddleware blocks the third report_writer invocation) is a separate hardening item — the SUMMARIZER currently exits BLOCKED with a usable `drug.md` but no `target_assessment.json`. A pre-write or `build_evidence_summary` lifecycle change is needed.

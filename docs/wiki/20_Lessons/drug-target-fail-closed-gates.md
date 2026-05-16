---
title: "Drug Target Agent Fail-Closed Quality Gates"
description: "Why deterministic middleware-level gates replace LLM self-judgment in the drug-target agent: 4 defect cases, the wrap_tool_call vs wrap_model_call hook selection, and the post-handler tool result inspection pattern reused from RepairCycleCounterMiddleware. Updated 2026-05-13 to record the summarizer simplification: 4 of 5 summarizer-scoped middleware classes were removed in favor of prompt-level enforcement; SummarizerFinalizationGuardMiddleware survived, adapted to the new 7-tool surface."
type: lesson
tags: [middleware, fail-closed, langchain, deepagents, drug_target, wrap_tool_call, quality-gate, deterministic]
created: 2026-05-06
updated: 2026-05-15
sources:
  - src/agents/deep_interpreter/middleware/think_tool_quality_gate.py
  - src/agents/deep_interpreter/middleware/write_file_guard.py
  - src/agents/drug_target/subagents/summarizer/middleware.py
  - src/agents/drug_target/subagents/summarizer/agent.py
  - src/agents/drug_target/tools/stage_logic.py
related-plans:
  - .omb/plans/2026-05-06-drug-target-agent-quality-gates.md
  - .omb/plans/2026-05-13-drug-target-summarizer-simplification.md
---

## Lesson: Drug Target Agent Fail-Closed Quality Gates

## TL;DR

Four quality-control failures in the `drug_target` agent were traced to LLM self-judgment overriding
deterministic intent. Replacing self-judgment with middleware-level gates at the **tool-call boundary**
closed all four failure modes. The central insight: `wrap_tool_call` intercepts `ToolCallRequest`
objects — it cannot intercept the LLM's free-text `AIMessage`. Therefore enforcement must happen
one level up: block the **tool call that enables a forbidden write**, not the text the LLM produces.

---

## The 4 Defects

### Defect 1 — think_tool quality regressions (R1/R2)

The `think_tool` already returned a JSON field `should_continue: false` and `parsed_score: 0.15`
when reflection quality was low. However, this signal was **advisory** — the LLM could read
`should_continue=false` and continue anyway. The `drug_target` agent's orchestrator had no server-side
mechanism to enforce a retry.

Observed in `trace_20260506_143625.log` lines 233 and 443: two separate reflections with
`parsed_score=0.15` and `parsed_score=1.00` were both accepted and the pipeline moved forward.
The `parsed_score=1.00` reflection contained no grounding evidence (no filename pattern, no numeric
value), so the LLM-supplied self-score was meaningless.

### Defect 2 — write_file double-nested absolute paths (R3)

`WriteFileArgGuardMiddleware` coerced `write_file` content to string but passed the `file_path`
argument through unchanged. When the LLM produced an absolute on-disk path such as
`/Users/jungj2/.../res_ipf_openai/validator_audit_repair_mode.json`, the DeepAgents
`FilesystemBackend(root_dir=data_dir, virtual_mode=True)` treated this as a virtual path and
created a double-nested structure:

```
res_ipf_openai/Users/jungj2/.../res_ipf_openai/validator_audit_repair_mode.json
```

This made the written file unreachable to downstream validators that expected the file at
`validator_audit_repair_mode.json` (relative to the backend root).

### Defect 3 — Validator bypass: finalize despite `valid=false` (R4)

The summarizer subagent called `validate_drug_report_finalization` and received back a
`ToolMessage` with `status=blocking_issues_remain, issue_count=7`. Instead of halting, the LLM
emitted a `"SUMMARIZER_STATUS: PASS"` string in its final text response, and the report was
finalized with 7 unresolved blocking issues still present.

The orchestrator system prompt at `agent.py:70-78` instructs the orchestrator LLM to treat the
substring `SUMMARIZER_STATUS: PASS` in the summarizer's final text as the pipeline-completion
signal. Because this is a prompt-level instruction processed by the LLM — not a deterministic
Python check — the LLM could (and did) emit the PASS token even after receiving `issue_count=7`
from the validator tool. This is precisely why a `wrap_model_call` middleware that rewrites the
AIMessage stream cannot fix the issue: the LLM's own reasoning still produces the PASS token.
The correct fix is to block the *write tool call* one level up — making the PASS token
semantically moot because no write can occur.

The root cause: `wrap_tool_call` cannot intercept the LLM's free-text `AIMessage`. Injecting
a stronger prompt ("do not output PASS if valid=false") was tried and failed to hold across
model versions and temperatures.

### Defect 4 — Reference card `matched_drugs` lost (R5)

`stage3_{CD4,ITGB2,ICAM1}.json` each contained 10 matched drugs under `chembl.matched_drugs`.
However, the `drug_report_reference_card.json` showed `matched_drugs: []` for all three genes.

Prior to this PR, the cause was a normalization step at `stage_logic.py:2018-2025` that
flattened `chembl.matched_drugs` into a `raw_drugs` list and then reconstructed separate keys
(`clinical_drugs`, `preclinical_compounds`, `drugs`) — dropping the original `matched_drugs`
key in the process. The `featured_cards` assembly loop at lines 2212-2226 used only the
normalized output, so `matched_drugs` was never present in the assembled card. After the fix,
the matched_drugs re-injection is visible at lines 2229-2234 (the builder loop now extends
through line 2234).

---

## Why Deterministic Gates Replace LLM Self-Judgment

**Prompt-only enforcement is unreliable for fail-closed decisions.** Evidence from this codebase:

- `think_tool` returns `should_continue: false` (advisory) — the LLM produces another reflection
  anyway, citing "high confidence" in its own reasoning. Prompt strengthening was tried; the
  failure persisted across multiple model versions (`qwen3.5:35b`, `gemma4:31b`).

- The summarizer LLM received `issue_count=7, status=blocking_issues_remain` verbatim in its
  context. It still emitted `SUMMARIZER_STATUS: PASS`. This is not a model defect — it is the
  correct behavior for a model instructed to complete the task. The **constraint** must come from
  outside the model, not from the model's own chain-of-thought.

**The correct mental model**: the LLM is the generator; middleware is the validator. Generators
do not self-police reliably. Validators must be deterministic, external, and operate on
machine-readable signals (tool results), not natural-language signals (AIMessage content).

**Applicable principle**: any fail-closed decision that can be grounded in a structured tool
result (JSON field, numeric value, boolean flag) should be enforced at the tool-call boundary
with deterministic middleware, not at the prompt level.

---

## `wrap_tool_call` vs `wrap_model_call`: The Hook Selection Problem

DeepAgents `AgentMiddleware` exposes two interception hooks:

| Hook | What it intercepts | Characteristics |
|------|--------------------|-----------------|
| `wrap_model_call` | The LLM's `AIMessage` (before tool node) | Fragile: stream vs non-stream split, LLM phrasing varies, no stable schema |
| `wrap_tool_call` | `ToolCallRequest` → `ToolMessage` round-trip | Deterministic: structured args in, structured result out, schema-stable |

For the four defects described above, `wrap_tool_call` is the correct hook:

1. **For write blocking (Defects 2 and 3)**: the goal is to prevent a write from landing on disk.
   The write happens when the tool executes, not when the LLM produces text. Intercepting
   `ToolCallRequest` and returning a blocked `ToolMessage` before `handler(request)` prevents
   the write entirely.

2. **For post-result inspection (Defects 1 and 3)**: call `handler(request)` first to get the
   tool's `ToolMessage`, then inspect its JSON content to decide whether to pass through or
   replace with a retry/blocked message. This is possible only in `wrap_tool_call`.

3. **Why not `wrap_model_call`**:
   - The orchestrator's PASS-token substring match (`agent.py:70`) is downstream of tool calls.
     Blocking at `wrap_model_call` would require parsing arbitrary LLM text, which is brittle.
   - Under streaming (`awrap_model_call`), the message arrives as a sequence of chunks — parsing
     is even harder.
   - Even if blocked at model level, the LLM can rephrase on the next step and bypass the check.

The pattern from plan §2.1.D (Option C — adopted): **block the tool call that enables a forbidden
write, not the text that describes it.** The write itself is the enforcement point.

---

## Pattern: Post-handler Tool Result Inspection via `_handle_critic_result`

The canonical pattern for this class of middleware was already present in `RepairCycleCounterMiddleware`
before this PR. It is now extracted as a reusable pattern used by three middleware classes.

### Canonical implementation (`middleware.py:143-155`)

```python
def _handle_critic_result(self, result: ToolMessage | Command) -> None:
    """Extract critic findings from tool result for use in BLOCKED message."""
    if isinstance(result, ToolMessage):
        self._last_critic_findings = str(result.content)
    elif isinstance(result, Command):
        update = getattr(result, "update", None)
        if isinstance(update, dict):
            msgs = update.get("messages", [])
            if msgs:
                last = msgs[-1]
                if isinstance(last, ToolMessage):
                    self._last_critic_findings = str(last.content)
```

Called from `wrap_tool_call` after `handler(request)` returns, when the tool name is
`"critic"` (the check tool whose result drives the decision).

### New variant: `SummarizerFinalizationGuardMiddleware._capture_validator_result`

```python
def _capture_validator_result(self, result: ToolMessage | Command) -> None:
    if not isinstance(result, ToolMessage):
        return
    try:
        parsed = json.loads(str(result.content))
        if isinstance(parsed, dict) and "valid" in parsed:
            self._validator_called = True
            self._last_valid = bool(parsed["valid"])
    except (ValueError, TypeError):
        pass
```

The difference: this variant parses a boolean `"valid"` field rather than capturing raw findings
text. The state (`_validator_called`, `_last_valid`) then gates a separate set of tool calls
(`save_drug_md`, `task(report_writer)`) on the next invocation.

### Full `wrap_tool_call` flow (pre-check + post-capture)

```python
def wrap_tool_call(self, request, handler):
    # 1. Pre-check: block guarded writes if gate not satisfied
    blocked = self._check_gate(request)
    if blocked is not None:
        return blocked
    # 2. Execute the tool
    result = handler(request)
    # 3. Post-capture: record validator result for future gate decisions
    if self._is_validator(request):
        self._capture_validator_result(result)
    return result
```

`ThinkToolQualityGateMiddleware` uses the same structure but collapses pre-check and post-capture
into a single `_evaluate(request, result)` call, since the think_tool is both the check and the
potential retry target.

---

## Reusing This Pattern

Apply this pattern when a future middleware needs to enforce a fail-closed constraint based on
a prior tool result.

**Checklist for future middleware authors**:

1. **Identify the WRITE/COMMIT tool** that should be blocked when the constraint is violated
   (e.g., `save_drug_md`, `task(subagent_type="report_writer")`).

2. **Identify the CHECK tool** whose `ToolMessage` result drives the decision
   (e.g., `validate_drug_report_finalization`, `task(subagent_type="critic")`).

3. **Hook in `wrap_tool_call`**:
   - On CHECK tool calls: let `handler(request)` run, then capture the result with a
     `_capture_*` helper. Parse the JSON field that represents pass/fail.
   - On WRITE tool calls: call `_check_gate(request)` before `handler(request)`. Return a
     blocked `ToolMessage` if the gate is not satisfied.

4. **Handle the "check never called" case explicitly.** Per D1 (strict policy): if the CHECK
   tool has not been called yet, the WRITE must also be blocked. The safe default is always
   `fail-closed`, not `fail-open`. Initialize `_validator_called = False` and treat the
   `not self._validator_called` branch as a blocking condition.

5. **Make state idempotent across re-runs.** Each middleware instance is created per agent
   invocation. Do not use class-level (shared) counters. The `__init__` method must initialize
   all state to its starting value; re-running the agent creates a fresh middleware instance
   with no memory of prior runs.

6. **Do not increment counters inside `_check_gate`.** Counter updates belong in the WRITE
   tool's `wrap_tool_call` branch, after confirming the call is not blocked. This avoids
   double-counting when a blocked response is returned before the handler runs.

---

## 2026-05-13 Update — Summarizer Simplification

The summarizer subagent was simplified from a `CompiledSubAgent` with inner
`report_writer`/`critic` workers plus six middleware classes to a single flat
dict subagent with seven tools. Most middleware-level fail-closed enforcement
moved to **prompt-level enforcement** plus a single **adapted** mechanical gate.
The architectural pivot was deliberate and made with full awareness of the
protections being surrendered.

### What was removed (4 of 5 summarizer-scoped middleware classes)

| Removed class | What it guarded | Replacement |
|---|---|---|
| `BuildEvidenceSummaryGuardMiddleware` | Duplicate `build_evidence_summary` calls per run | Prompt language: "Step 1. Call `build_evidence_summary` exactly once." No mechanical re-call check. **Accepted regression:** a non-compliant LLM can call it twice (idempotent in practice; cost-only). |
| `RepairCycleCounterMiddleware(max_cycles=2)` | The (N+1)-th `task(subagent_type="report_writer")` after N non-converging critic cycles | Prompt language: "REPEAT AT MOST 2 TIMES" on `validate_drug_md`-driven retry through `save_report_expansions`. **Accepted regression:** the model can exceed the budget; only `validate_drug_md` returning valid=true unblocks finalization. |
| `AnnotationDensityMiddleware` | Under-annotated `save_drug_md` content | `save_drug_md` no longer exists in the summarizer surface; drug.md is now assembled deterministically by `render_drug_md_from_expansions` from schema-validated per-section expansions. `validate_drug_md` continues to catch annotation density at validation time. |
| `FrozenTemplateSpanMiddleware` | `save_drug_md` content that mutated non-EXPAND template spans | `save_drug_md` not in tool list; template assembly is now performed by `render_drug_md_from_expansions`, which is deterministic. The model cannot corrupt template spans because it never hand-writes the rendered file. |

### What survived and was adapted

`SummarizerFinalizationGuardMiddleware` — the most important fail-closed gate — was **retained and adapted** to the new tool surface:

- **Before (pre-2026-05-13):** Guarded `save_drug_md` and `task(subagent_type="report_writer")` against `validate_drug_report_finalization` returning `valid=false`.
- **After (post-2026-05-13):** Guards `generate_drug_html_report` against `validate_drug_md` returning `valid=false`.
- **Invariant preserved:** The summarizer cannot emit `SUMMARIZER_STATUS: PASS` truthfully — the prompt requires HTML generation before PASS, and HTML generation is mechanically blocked until the validator passes. A non-compliant LLM may still try to emit PASS without calling `generate_drug_html_report`, but the orchestrator's literal-line contract plus the absence of an HTML artifact will fail downstream checks.

The adapted class is documented in `src/agents/drug_target/subagents/summarizer/middleware.py` (alongside the surviving `HypothesisRetryLoopMiddleware`, which is out of scope for the summarizer changes).

### Other removed scaffolding

- The Python repair loop `run_summarizer_loop()` and helpers `synthesize_repair_instructions()`, `write_critic_slices()`, `cleanup_critic_slices()` were deleted; the retry budget moved to prompt-level guidance.
- The `_CriticSliceWrapper` lifecycle helper and the per-gene `evidence/_critic_slices/` materialization were deleted; the simplified summarizer reads evidence directly via `load_evidence_files`.
- `subagents/critic_schema.py` (the `CriticOutput` TypedDict / Pydantic structured-output schema) was deleted; the inner critic subagent no longer exists.
- `subagents/summarizer/fs_backend.py` (`LoggingAndFallbackFilesystemBackend`) and `subagents/summarizer/fs_middleware.py` (`LoggingFilesystemMiddleware`) were deleted; the new dict summarizer shares the parent agent's `FilesystemBackend`.

### Decision rationale

The interview that produced `.omb/plans/2026-05-13-drug-target-summarizer-simplification.md` weighed three options:

1. **(a)** Delete all five summarizer-scoped middleware classes; rely on prompt + `validate_drug_md` + orchestrator literal-line contract alone.
2. **(b)** Retain `SummarizerFinalizationGuardMiddleware` as-is (no code change), delete the other four.
3. **(b')** Retain *and adapt* `SummarizerFinalizationGuardMiddleware` to guard the new finalization tool (`generate_drug_html_report`) against the new validator result (`validate_drug_md`), delete the other four.

Path **(b')** was adopted. (b) was rejected because the unadapted guard would become dead code under the new tool surface — `save_drug_md` and `task(report_writer)` no longer exist for it to guard, and `validate_drug_report_finalization` is no longer in the summarizer tool list for it to read. Option (a) was rejected because it leaves no mechanical backstop for `SUMMARIZER_STATUS: PASS` truthfulness; the LLM could declare success without ever attempting HTML generation. (b') preserves the single most important invariant — HTML generation is impossible without a real `validate_drug_md` pass — while shedding the complexity of the other four middlewares.

### Residual risk and mitigations

| Risk | Mitigation |
|---|---|
| LLM emits `SUMMARIZER_STATUS: PASS` without calling `generate_drug_html_report` | Orchestrator literal-line contract is still parsed; downstream consumers can additionally verify an HTML artifact was produced. |
| LLM exceeds the 2-retry budget on `save_report_expansions`/`validate_drug_md` | Recursion limit on the parent agent (`10000`) is conservative even for runaway loops. The accepted regression is cost, not correctness. |
| LLM calls `build_evidence_summary` more than once | Idempotent in practice; minor token cost overhead. |
| LLM emits non-compliant Markdown via `save_report_expansions` | `validate_drug_md` is the semantic gate; `render_drug_md_from_expansions` produces deterministic output from the schema-validated expansions, so prose-level template corruption is no longer reachable. |

### Tests

The 17 legacy summarizer-middleware tests (plus four additional consumer tests) were deleted. They are replaced by eight focused tests in `tests/agents/drug_target/test_summarizer_dict_spec.py`:

- TS-01: dict spec shape and required keys
- TS-02: exact 7-tool inventory
- TS-03: skill-name wiring under `DrugTargetConfig.summarizer_skill_names`
- TS-04: `SummarizerFinalizationGuardMiddleware` PASS path
- TS-05: `SummarizerFinalizationGuardMiddleware` FAIL paths (validator-never-called and validator-returned-invalid)
- TS-06: orchestrator contract preserved (`SUMMARIZER_STATUS:` literal + summarizer dispatch by name)
- TS-07: `save_report_expansions` auto-derives `reference_card_hash` when the caller omits it
- TS-08: `save_report_expansions` still rejects an explicit mismatched hash with `expected`/`supplied` in the error payload

### Live-smoke follow-up — round 7 + merge + 6-way verification (2026-05-14)

PR #19 merged into `main` as squash commit `1b3e824` at 21:43 UTC after a final 6-way live-smoke pass. The round-6 producer/validator contract bug surfaced by `UNCITED_QUANTITATIVE` on template-baked Census lines is closed by a template-side citation fix and locked by a deterministic round-trip regression test.

**Round 7 changes (commit `6a31d68` on the feat branch, squashed into `1b3e824`):**

- **P0-1 template-side citation** — `_preformat_cards` in `src/agents/drug_target/tools/drug_report_html.py:794-815` emits a `pair_file` field (`f"stage1_{ligand}--{receptor}.json"`) and `skills/drug-target-reporting/templates/drug_report.md.j2:137` now ends Census lines with `[from {{ p.pair_file }}]`. The producer becomes validator-compliant by construction — `validate_drug_md`'s UNCITED_QUANTITATIVE regex (`.json|\[from\s+[^\]]+\]|stage[123]_…`) is satisfied at template render time.

- **P0-2 round-trip regression test** — new `tests/agents/drug_target/test_summarizer_round_trip.py` exercises `build_evidence_summary → save_report_expansions → render_drug_md_from_expansions → validate_drug_md` with a minimal deterministic expansions payload built from `expansion_schema_spec.json` (no LLM in the loop). Two assertions: (a) `validate_drug_md` returns `valid: true` on the rendered output, (b) every Census line carries the inline `[from stage1_<LIG>--<REC>.json]` citation. Both verified to FAIL on `83b8c0f` (round-6 state) and PASS after P0-1.

- **P1-1 UNCITED_QUANTITATIVE bracketing pair** — `tests/agents/drug_target/test_drug_md_new_flags.py::TestUncitedQuantitativeBracketing` adds a positive case (`OR=2.1` in EXPAND prose fires) and a negative case (Census line + new citation does NOT fire) so producer-side drift in either direction surfaces as a targeted failure.

- **P1-2 path-traversal guard (DS-1)** — new `_validate_data_dir` helper in `src/agents/drug_target/tools/report_expansion_schema.py` resolves the path and confirms it falls under an allowed workspace root (defaults: `tempfile.gettempdir()`, env-configured `DRUG_TARGET_DATA_DIR` / `DEEP_INTERPRETER_DATA_DIR`, optional `DRUG_TARGET_ALLOWED_DATA_DIRS` override, `/tmp/deep_interpreter_workspace` fallback). Wired into both `save_report_expansions` (before `base.mkdir(...)`) and `lookup_provenance_value` (before any disk probe). Out-of-bounds paths return a structured `DATA_DIR_OUT_OF_BOUNDS` error envelope.

- **P1-3 prompt rubric correction** — `SUMMARIZER_PROMPT` Step 5 retry sub-rubric distinguishes EXPAND-region prose (LLM can repair the citation) from template-baked Census/filter lines (LLM has no authoring surface; emit `SUMMARIZER_STATUS: FAIL` and stop). Closes the unreachable-retry loop that wasted budget in rounds 1-6.

**Live-smoke verification — 6-way comparison.** The R7 fix was verified against six model configurations using `scripts/run_drug_target_summarizer_only.py`:

| Model | Status | Time | save retries | HTML generated | Final `SUMMARIZER_STATUS` |
|---|---|---|---|---|---|
| `gpt-5.4` | PASS | ~7 min | 1 (1-shot) | yes | `PASS` |
| `gpt-5.4-mini` | FAIL | 2.1 min | 2 (both fail) | no | `FAIL` |
| `qwen3.5:35b` @ shared ollama (model swap) | INCOMPLETE | 6.4 min | 4 (3 fail+1) | yes | (token missing) |
| `qwen3.5:35b` @ dedicated ollama (no swap) | PASS | 5.7 min | 2 (1 fail+1) | yes | `PASS` |
| `qwen3.6:35b` @ dedicated ollama | INCOMPLETE | 27.6 min | 2 (1 fail+1) | no | (virtual-path trap on validator result) |
| `qwen3.5:122b` @ dedicated ollama | PASS | 29.3 min | 4 (3 fail+1) | yes | `PASS` |

**Decisive evidence.** Both production-grade models (gpt-5.4, qwen3.5:122b) pass cleanly with no further code changes. Every model that reached `validate_drug_md` got `valid=true` and was allowed past the mechanically-gated `generate_drug_html_report`. `UNCITED_QUANTITATIVE` was not observed in any run — the producer/validator contract is repaired across the full model spectrum tested.

**The smaller-model failure modes are out of round-7 scope and are not regressions introduced by PR #19.** They are the R01 (b') accepted regression ("prompt-only enforcement may not converge for non-compliant LLMs") materializing on weaker instruction-following targets:

- `gpt-5.4-mini` fabricated provenance keys (`evidence/assessment_results.json::combined_total`) — bypassed the mandatory `lookup_provenance_value` call.
- `qwen3.5:35b` was nondeterministic across runs — same model, same fixture, two different terminal outcomes (one PASS, one INCOMPLETE with HTML generated but the final `SUMMARIZER_STATUS:` token omitted).
- `qwen3.6:35b` hit the documented virtual-path trap (`deepagents-virtual-mode-ls-glob-empty.md`) when reading the offloaded validator result via `read_file('/private/var/folders/.../drug.md')` instead of the virtual path; main's PR #17 `auto-normalize absolute paths in virtual_mode FilesystemBackend` is the backend-level fix for this, and it shipped on `main` independently.

**Content-quality observation (deferred to a follow-up PR).** Both PASS-state `drug.md` artifacts (gpt-5.4 and qwen3.5:122b) carry two non-validator-detectable issues:

- **EXPAND prose boilerplate**: each model repeats one identical sentence verbatim across 8 EXPAND slots. The boilerplate content differs by model (gpt-5.4 cites the static report template, qwen3.5:122b lists the specific drug names and gap analysis), but the 8x repetition pattern is identical.
- **External medical knowledge inject**: both models add ungrounded medical prose (e.g. *"T-cell mediated inflammation and fibrotic remodeling"*, *"clearance of proteases and regulation of TGF-beta signaling"*, *"epithelial injury and inflammatory adhesion biology"*) that is not anchored in any evidence file.

This is the explicit R01 (b') accepted regression — *prose-quality cost from removing the critic+repair loop*. R7's scope was producer/validator contract correctness, which is met. Prose-quality work is tracked separately and will land in a follow-up PR.

**Merge integration commit (`23f5501`, squashed into `1b3e824`).** Main had advanced independently with three PRs on 2026-05-07 (PR #16 fail-closed gates, PR #17 virtual-path normalize, PR #18 `DrugMdSaveSanitizerMiddleware`) that took a parallel design direction (middleware fortification) while feat developed the R01 (b') simplification on 2026-05-14. The merge keeps PR #19 as the source of truth for the summarizer design while admitting main's additive validator hardening that is layer-compatible — specifically five non-conflicting blocks in `stage_logic.py` (stoplist expansion, Stage 1 ligand/receptor allowlist for FABRICATED_DRUG_NAME, `_BLOCKING_VALIDATE_DRUG_MD_FINDINGS` allowlist, renderer-scoped finding suppression, disease scope note). Six middleware-targeted test files admitted from main (`test_drug_md_save_sanitizer.py`, `test_summarizer_finalization_gate.py`, `test_summarizer_middleware_runtime_state.py`, `test_summarizer_chain_regression.py`, `test_summarizer_middleware_chain_order.py`, `test_fs_backend_virtual_mode_fallback.py`) were removed because the middleware classes and `fs_backend` module they exercise were deleted by R01 (b'). One unrelated `req` file was dropped as out-of-scope. Final test count after merge: 410 passed (was 407 pre-merge + 3 admitted from compatible main tests), 3 pre-existing deselects, 4 xfailed. `ruff check` clean across all changed files.

### Live-smoke follow-up — round 6 + deepwork consensus (2026-05-14)

Round 6 live smoke (gpt-5.4) after `lookup_provenance_value` landed (commit `83b8c0f`) finally got past every LLM-side failure mode of rounds 1-5. The trace shows the LLM successfully:

1. Called `lookup_provenance_value` 7 times — all returned `ok: true` with exact source_values
2. Submitted `save_report_expansions` — **saved: true, errors: []** on first try
3. Rendered `drug.md` via `render_drug_md_from_expansions`
4. Called `validate_drug_md` — returned `valid: false, issue_count: 1, type: UNCITED_QUANTITATIVE`
5. Retry — identical failure

Final status: `SUMMARIZER_STATUS: FAIL` on 10 Census lines like `- Census: risk_ratio=0.0523, p_value=0.0` that the validator flagged as uncited.

**Crucially: this failure is qualitatively different from rounds 1-5.** Those were all LLM↔tool contract gaps that prompt/tool design could close. Round 6 is the **first server-side contract bug** — two Python modules disagree:

- Producer: `skills/drug-target-reporting/templates/drug_report.md.j2:136-138` emits the Census line with NO source annotation.
- Consumer: `src/agents/drug_target/tools/stage_logic.py:3001-3068` `UNCITED_QUANTITATIVE` regex requires `\.json|\[from\s+[^\]]+\]|stage[123]_…`. None of those appear in template output.
- LLM authoring surface (`save_report_expansions`, EXPAND markers) cannot touch template body. The retry budget is structurally unspendable.

**Git archaeology**: `UNCITED_QUANTITATIVE` was introduced in commit `a61f8f8` on `main` (pre-PR-19). The template was never modified on PR #19 either. The conflict was LATENT on `main` — masked by the now-deleted critic+repair loop in `567dcb1`, which had a `save_drug_md` + REPAIR MODE prompt branch granting the LLM line-level template patching. The simplification removed the masking layer but did not remove the underlying contract bug.

### Deepwork dual review (architect + code-reviewer) — consensus

Both reviewers identify the same root cause at the same file:line and recommend the same remediation:

**Cross-stance agreement clusters (CRITICAL):**
- **CAC-1**: validator-template contract violation. Fix template-side — extend `drug_report.md.j2:137` to emit `[from stage1_{{ p.pair_file }}.json]` inline; add `pair_file` field to `_preformat_cards` at `drug_report_html.py:794-803`. ~10 lines. Producer becomes validator-compliant by construction.
- **CAC-2** (HIGH): no LLM-free round-trip test exists that exercises `build_evidence_summary → save_report_expansions → render_drug_md_from_expansions → validate_drug_md` end-to-end. This admitted the round-6 class of bug into CI. Add `tests/agents/drug_target/test_summarizer_round_trip.py` — must fail on `83b8c0f`, pass after CAC-1.

**Rejected alternatives (both reviewers):**
- (a) Validator scope narrowing — MEDIUM rejection: requires byte-offset region tracking, weakens a paranoid check that catches real LLM hallucinations elsewhere.
- (c) Re-add line-level authoring tool — HIGH rejection: contradicts simplification intent ("LLM as NARRATIVE EXPANDER only"), re-opens hallucination surface.

**Strategic verdict (both): (i) Ship PR #19 with the targeted fix.** The convergence pattern (R1-R5 LLM↔tool, R6 server-side contract) supports shipping. (ii) Python composer, (iii) Revert, (iv) Critic tool — all rejected.

**Additional findings from code-reviewer (defensive stance):**
- **DS-1 (HIGH)**: path-traversal surface in `lookup_provenance_value` and `save_report_expansions` — `data_dir` accepted without allowlist; `mkdir` runs before validation. Production agent serves arbitrary upstream messages.
- **DS-2 (HIGH)**: no UNCITED_QUANTITATIVE bracketing tests (no positive-fires + negative-passes pair).
- **DS-3 (HIGH, off-topic)**: `coexpression_detected` boolean bug at `stage_logic.py:2371` conflates "no signal" with "significant depletion."
- **DS-4 (HIGH)**: `validate_report_expansions` mutates caller input — foot-gun for non-LLM callers passing Pydantic instances.
- Several MEDIUM/LOW items (claim_type loose typing, count claim shadowing, regex drift, smoke script legibility).

### Action plan — Round 7

Recorded in `.omb/plans/2026-05-14-pr19-round7-template-citation.md`:

- **P0**: CAC-1 (template fix) + CAC-2 (round-trip regression test)
- **P1 (same PR if scope allows)**: DS-2 (bracketing tests), DS-1 (path-traversal guard), drop unreachable retry sub-rubric from `SUMMARIZER_PROMPT`
- **Deferred (follow-up issues)**: DS-3, DS-4, MEDIUM/LOW items

This is expected to be the last round before merge. Round-7 risk is LOW because the remaining failure modes after CAC-1 land are LLM EXPAND-region hallucinations — exactly what the current validator + `lookup_provenance_value` are aligned against.

### Live-smoke follow-up — round 5 (2026-05-14)

After commit `ee46263` wired `SkillsMiddleware` + `SkillActivator` into
the standalone smoke script (round 4 had been running a strictly weaker
configuration than the production pipeline), the live smoke surfaced a
deeper failure mode: `save_report_expansions` rejected every retry with
`SOURCE_PROVENANCE_MISMATCH` because the LLM could not reliably
transcribe nested object values from the offloaded reference card into
the `source_provenance.source_value` field. gpt-5.4 oscillated between
`direct_value`, `absence`, and `count` claim_types trying to match the
validator's byte-equality / length-equality / emptiness checks; none of
the manual transcriptions stuck.

This is the decisive evidence that the 2026-05-13 plan's R01 (b')
accepted regression — "delete the critic+repair loop and rely on
prompt + skill + validate_drug_md" — actually does impose a real cost.
The original critic+repair loop hid this cost by iterating against the
schema until something matched; without that loop, the LLM has no
realistic path to converge on the exact-value match the validator
expects.

**Remediation (option iii from the architect review):** add a single
helper tool — `lookup_provenance_value(data_dir, source_file,
source_field)` — that reads `drug_report_reference_card.json` and
returns the exact indexed `source_value` for a given (source_file,
source_field) pair. The LLM calls this tool before composing each
sentence and copies the returned `source_value` VERBATIM into its
`source_provenance.source_value` field. The validator's byte-equality
check still runs (anti-hallucination intent preserved) but the LLM
no longer has to transcribe nested data structures by hand.

The summarizer tool surface grows from 7 to 8 tools. The 7-tool
invariant from the original plan is recorded as superseded; the
TS-02 test is renamed and updated accordingly.

`SUMMARIZER_PROMPT` Step 3 is restructured into substeps:
  3a. read `/expansion_schema_spec.json` (existing virtual-path
      discovery)
  3b. for every sentence, call `lookup_provenance_value` BEFORE
      composing the `source_provenance` block; copy the returned value
      verbatim
  3c. call `save_report_expansions` with the full slots list

Live smoke verification: TBD after this commit.

### Live-smoke follow-up — round 3 (2026-05-14)

Round 3 live smoke (gpt-5.4) after schema-discovery fix (commit `072a2bc`)
exposed two further prompt defects and one residual content-quality risk:

- **P0 — `SUMMARIZER_PROMPT` Step 3 instructed the LLM to read
  `<data_dir>/expansion_schema_spec.json`**, a disk-prefix path. Under
  `FilesystemBackend(virtual_mode=True)` the absolute path is reinterpreted
  as a virtual path relative to the backend root, producing
  `File not found` (the same gotcha documented in
  `deepagents-virtual-mode-ls-glob-empty.md`). The bottom-of-prompt
  GUIDANCE clause already warned against this antipattern; my Step 3
  wording contradicted it. Fix: Step 3 now says
  `read_file("/expansion_schema_spec.json")` (virtual path).

- **P1 — `save_report_expansions` retry semantics were ambiguous.**
  The LLM read the first validation issue (a single
  `UNCITED_QUANTITATIVE` finding), attempted a patch by submitting a
  payload that only included the modified slot, and the validator
  rejected with `missing required slot_id: ...`. The tool's contract is
  REPLACE, not PATCH — every required slot must appear in every payload.
  Step 5 now expands the retry rubric: read offloaded validator results
  via the virtual `/large_tool_results/...` path, identify offending
  slots, then rebuild the FULL payload (all required_slot_ids) before
  re-saving.

- **P2 — `subagents=[]` does NOT suppress
  `SubAgentMiddleware`/`task`**. deepagents auto-attaches the
  middleware with a default general-purpose subagent regardless of the
  `subagents` argument's emptiness. In round 3 the LLM dispatched the
  `task` tool once (msg 13-14) and used it productively for schema
  extraction, so the residual `task` tool was net positive for that
  run. Suppression is left out of scope until live-smoke evidence shows
  net negative impact.

**Residual content-quality risk (acknowledged):** the round 3 run
reached `validate_drug_md` and saw a single `UNCITED_QUANTITATIVE`
finding. The LLM's repair attempt broke slot inventory (P1 above) and
the run gave up. After the prompt fixes ship, the next live smoke
should at minimum reach validate cleanly. But the *content* itself
(uncited quantitative claims, unanchored sentences, fabricated drug
names) is a generation-quality problem the 2026-05-13 simplification
deliberately accepted as regression when it removed the critic→repair
loop. If round 4 fails on the same validator findings, the next
remediation tier is either (iii) Python-level deterministic prose
composition or (iv) a single critic tool (not a subagent) that returns
structured findings the LLM can fix per-sentence.

### Live-smoke follow-up (2026-05-14)

Live smoke against `openai gpt-5.4` surfaced a pre-existing tool-design issue
that the simplification deterministically exposed: `save_report_expansions`
required the caller to supply `reference_card_hash` = SHA256 of the
canonical JSON of `<data_dir>/drug_report_reference_card.json`. With the
reference card returned by `build_evidence_summary` exceeding the deepagents
`FilesystemMiddleware` eviction threshold (default 80 K chars / 20 K
tokens), the result is offloaded to `/large_tool_results/<call_id>` and the
LLM only sees a small preview. Computing canonical-JSON SHA256 from
partial reads is not feasible, so gpt-5.4 fabricated hashes and oscillated
on `RENDER_SOURCE_HASH_MISMATCH` until the prompt's max-2-retry budget
expired (final status: `SUMMARIZER_STATUS: FAIL`).

**Remediation (tool-side auto-derive):** in `validate_report_expansions`
(`src/agents/drug_target/tools/report_expansion_schema.py`), the
`reference_card_hash` field is now optional. When the caller omits it, the
validator derives the hash from the on-disk reference card and writes it
into the persisted `report_expansions.json` so the saved payload is
self-describing. When the caller does supply a hash, mismatch is still a
hard rejection — but the error payload now includes both `expected` and
`supplied` so a misbehaving LLM can self-correct in one turn instead of
oscillating. `SUMMARIZER_PROMPT` was updated with a single sentence
instructing the LLM to omit `reference_card_hash`. The pre-existing
`canonical_json_hash` helper is reused; no new tools were introduced.

Why this is safe: the original purpose of the hash check — ensuring the
expansions payload was authored against the same reference card currently
on disk — still holds for explicit-hash callers. For the LLM, the reference
card is written exactly once by `build_evidence_summary` at Step 1 and
never re-written during the run, so auto-derivation is equivalent to the
LLM correctly observing the current state of disk. There is no window in
which the auto-derived hash could disagree with what an LLM would have
supplied if it could compute SHA256.

---

## Related

- `docs/wiki/20_Lessons/deepagents-virtual-mode-ls-glob-empty.md` — related filesystem backend
  gotcha in the same agent (LLM-constructed absolute paths and virtual_mode path resolution).
- Plan: `.omb/plans/2026-05-06-drug-target-agent-quality-gates.md` — full architecture decisions,
  option comparison, acceptance criteria, and assumption verification table.
  (This path is repo-relative and resolves from the main checkout; the plan file is not present
  inside the `feat/drug-target-agent-quality-gates` worktree.)
- Plan: `.omb/plans/2026-05-13-drug-target-summarizer-simplification.md` — the simplification
  plan and option comparison that produced the 2026-05-13 update above.

---

## 2026-05-15 — Summarizer-local critic subagent + CriticGateMiddleware

### Decision

Replaced the previously-planned heuristic `src/agents/drug_target/tools/critic.py` tool file
with a summarizer-local critic subagent (`subagents/critic/agent.py`) and a new
`CriticGateMiddleware` in `subagents/summarizer/middleware.py`. The critic is an inner subagent
installed by `SubAgentMiddleware` inside the summarizer; it is never added to the top-level
`WORKFLOW_ORDER` and is never returned by `get_subagents()`.

### Why

A heuristic tool-based critic would require maintaining morphology/synonym/medical-vocabulary
rules for every assertion type. That maintenance burden is unsustainable as the report schema
evolves. A critic LLM can judge whether a cited source passage actually supports a sentence
without requiring rule maintenance — and it is explicitly forbidden from judging whether the
medical claim is generally true (that would reintroduce LLM self-judgment as a gate). The
boundary is: **does the cited provenance_context text support this sentence?** Only that.

### What it enforces (mechanical, not LLM-trust-based)

`CriticGateMiddleware` enforces four deterministic conditions before allowing
`save_report_expansions` to proceed. If any condition fails, the save is blocked:

1. **Critic was called** — `critic_called` must be `True`; no-call → block.
2. **Critic JSON parsed** — malformed or wrong-schema critic response → block.
3. **Critic approved** — critic must have returned `valid=True` with no blocker findings; else → block.
4. **Hash match** — the canonical payload hash submitted to `save_report_expansions` must equal
   the hash of the payload the critic reviewed. Hash computed **before** `handler(request)` runs
   (because `save_report_expansions` mutates `reference_card_hash` during its own validation pass).
   Mutation → block.

Both `CriticGateMiddleware` and `SummarizerFinalizationGuardMiddleware` reset all state on
`before_agent`/`abefore_agent`, so each summarizer run starts with a clean slate.

### Defense-in-depth hardenings (verify-loop additions, 2026-05-15)

After the implementation pass, a multi-agent verification (`/omb:verify`) surfaced four
additional hardenings; all are now wired into production code:

1. **Cited-only `provenance_context` is actively enforced.** `validate_cited_only_provenance`
   is no longer just defined — it is invoked from `CriticGateMiddleware._capture_critic_result`
   after each envelope parse, with violations recorded as a blocker finding so the save is
   blocked.

2. **Critic findings re-injection is bounded.** When the gate blocks a save with an "invalid"
   message, the critic's `findings` array is now passed through `_safe_findings_for_message`:
   - capped at 5 entries (with an `... N-5 more findings omitted` marker),
   - string fields truncated at 500 characters,
   - ASCII control characters (`\x00-\x1f` except `\n\r\t`) stripped.
   This prevents a compromised or jailbroken critic LLM from injecting arbitrary prompt text
   back into the summarizer's context via the ToolMessage body.

3. **`disease` is sanitized before system-prompt injection.** `_sanitize_data_dir` was
   generalized to `_sanitize_prompt_value` and now applies to both `data_dir` and `disease` in
   the three subagent system prompts (`evidence_assessor`, `hypothesis_writer`, `summarizer`).
   The sanitizer truncates at the first `\x00-\x1f` byte, blocking newline-based instruction
   injection. The orchestrator system prompt in `agent.py` is a separate path and remains a
   follow-up.

4. **`REPORT_WRITER_PROMPT` retention is now auditable.** Five live test readers still import
   it, so deletion remains a separate migration PR. An inline retention-decision comment block
   above the constant (and cross-reference comments at `SUBAGENT_PROMPTS["report_writer"]` and
   `__all__`) names the five readers and points at the `xfail(strict=True)` test
   (`test_report_writer_prompt_dead_code_removed`) that gates the cleanup. A new
   `test_report_writer_prompt_retention_is_documented` enforces that the comment block exists
   in CI.

### What the critic LLM is forbidden to do

The critic subagent has `tools=[]` — it cannot call any tool or write any file. Its system
prompt (Appendix A, read-only) explicitly forbids judging whether a medical claim is generally
true. The only permitted judgment: does the text in `provenance_context` (cited source passages
only) support the sentence being reviewed? `CriticGateMiddleware` is the enforcement layer;
the critic LLM is the signal source, not the authority.

### Canonical hash consolidation

`_canonical_payload_hash` was deleted from `summarizer/middleware.py`. Both
`HypothesisRetryLoopMiddleware` and `CriticGateMiddleware` now use `canonical_json_hash` from
`tools/report_expansion_schema.py`. `normalize_expansions_for_hash` strips `reference_card_hash`
before hashing on both the critic-envelope side and the save side, so omitted/auto-derived cases
produce identical hashes.

### Kill switch

`DRUG_TARGET_CRITIC_ENABLED=false` (also `0`, `no`, `off`, case-insensitive) disables both
`SubAgentMiddleware(critic)` and `CriticGateMiddleware` in the summarizer. The default is
**fail-closed** — an empty, unset, or misspelled value leaves the critic enabled. An explicit
constructor argument `DrugTargetConfig(critic_enabled=False)` wins over the env var.

### SummarizerFinalizationGuardMiddleware state-reset fix

The existing HTML gate gained `before_agent`/`abefore_agent` that reset `_validator_called=False`
and `_last_valid=None`. This closes a previously-known state leak where a prior run's validator
result could persist into the next run's gate check. Behavior is otherwise unchanged.

### Boundary: legacy persisted-report path

`validate_drug_report_finalization(require_critic=True)` remains importable and functional. It
produces `evidence/critic_report.json` for external callers and scripts. It is **not** called
by the new pre-save critic flow and has **no effect** on whether `save_report_expansions`
proceeds during a live agent run.

### Known follow-ups (not blockers for this PR)

- `REPORT_WRITER_PROMPT` deletion is blocked by 5 live test readers
  (`test_prompts_gap_analysis_rule.py`, `test_prompts_clinical_compounds_rule.py`,
  `test_prompts_reflection_guidance.py`, `test_drug_profile_coverage.py`,
  `tests/test_drug_target.py`). `test_report_writer_prompt_dead_code_removed` is marked
  `xfail(strict=True)` until those readers are migrated.
- `pyright` is not installed in this worktree's venv — flag as env gap for reviewer.
- 2 pre-existing failures in `test_drug_md_new_flags.py` (`TestWrongApprovalYearExtension`,
  `TestUngroundedMechanism`) predate this branch and are not introduced here.

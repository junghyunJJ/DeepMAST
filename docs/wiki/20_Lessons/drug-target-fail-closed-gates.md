---
title: "Drug Target Agent Fail-Closed Quality Gates"
description: "Why deterministic middleware-level gates replace LLM self-judgment in the drug-target agent: 4 defect cases, the wrap_tool_call vs wrap_model_call hook selection, and the post-handler tool result inspection pattern reused from RepairCycleCounterMiddleware. Updated 2026-05-13 to record the summarizer simplification: 4 of 5 summarizer-scoped middleware classes were removed in favor of prompt-level enforcement; SummarizerFinalizationGuardMiddleware survived, adapted to the new 7-tool surface."
type: lesson
tags: [middleware, fail-closed, langchain, deepagents, drug_target, wrap_tool_call, quality-gate, deterministic]
created: 2026-05-06
updated: 2026-05-13
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

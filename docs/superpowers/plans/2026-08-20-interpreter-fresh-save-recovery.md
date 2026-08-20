# Interpreter Fresh Save Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the final existing interpreter save retry use a fresh focused context, prove Part 3 can save and pass its scoped guardrail, then complete one fresh canonical no-SNI/SNI pair.

**Architecture:** Preserve the current three-invocation bound and all interpreter/guardrail components. The first save retry continues the accumulated conversation; only the final retry invokes the same graph with one fresh Part-specific recovery message, breaking the observed CSV-summary drift while still requiring a real `write_file` tool call. No chat-to-file fallback or new agent path is added.

**Tech Stack:** Python 3.12, asyncio, pytest, Ruff, existing DeepAgents/LangGraph interpreter, existing Ollama and SGCP-RAG integrations.

**Spec:** `docs/superpowers/specs/2026-08-20-interpreter-fresh-save-recovery-design.md`

## Global Constraints

- Keep `MAX_INTERPRETER_INVOKE_ATTEMPTS = 3`.
- Keep the initial invocation unchanged.
- Keep the first save retry history-preserving.
- Use a one-message fresh context only for the final existing retry.
- The fresh message must include the complete Part-specific assignment and mandatory `write_file` contract.
- A report counts as complete only when the expected `partN_final.md` exists.
- Never auto-save, parse, or infer a report from assistant chat content.
- Preserve existing missing-output, exception, retry-count, and fail-closed behavior.
- Record `fresh_context` in retry start events and retry-history entries.
- Do not add dependencies, agents, middleware, graphs, retries, or fallback report generators.
- Do not change scientific prompts beyond the save-recovery context wording.
- Do not change Report Guardrail, RAG, SNI, target selection, selected genes, selected LR pairs, or collections.
- Run a disposable Part 3 smoke before any fresh full pair.
- Run pair 05 globally serial, no-SNI first; SNI starts only after no-SNI passes.
- Use RAG backend 4000, condition API 8883, Interpreter/Reporter Ollama 6000, model `qwen3.5:122b`, fixed collection UUID `a208e916-bd32-405a-9eee-de4cd82b2a3b`, 100 documents, and 1,553 chunks.
- Use no external total timeout for live interpreter or pair execution.
- Follow RED → GREEN TDD and the Lore commit protocol.

---

### Task 1: Reset only the final save retry context

**Files:**
- Modify: `scripts/run_deep_interpreter_agent.py:176-194`
- Modify: `scripts/run_deep_interpreter_agent.py:341-402`
- Modify: `tests/test_run_deep_interpreter_agent_cli.py:101-123`
- Modify: `tests/test_run_deep_interpreter_agent_cli.py:185-290`

**Interfaces:**
- Extend: `_build_interpreter_save_retry_message(data_dir: Path, part: int, *, fresh_context: bool = False) -> str`.
- Preserve: `_should_retry_interpreter_save(args, missing_outputs) -> bool`.
- Preserve: `run(args: argparse.Namespace) -> int` and three total invocations.
- Produce: retry start and retry-history objects containing `fresh_context: bool`.

- [ ] **Step 1: Write the RED final-retry message test**

Add this test beside the existing continuation-message test:

```python
@pytest.mark.parametrize("part", [1, 2, 3])
def test_interpreter_final_save_retry_message_starts_fresh(tmp_path, part):
    message = run_script._build_interpreter_save_retry_message(
        tmp_path,
        part,
        fresh_context=True,
    )

    assert f"Start a fresh Part {part} save recovery" in message
    assert "No prior conversation or tool results are attached" in message
    assert "Call load_analysis_data" in message
    assert "conversation and tool results above" not in message
    assert "Do not restart the analysis from scratch" not in message
    assert f"Part {part} ONLY" in message
    assert f'write_file(file_path="/part{part}_final.md"' in message
```

For Part 3, retain the existing assertion that the message contains
`selected_genes`, `selected_lr_pairs`, and the therapeutic-synthesis boundary.

- [ ] **Step 2: Write the RED payload-shape regression**

Replace `test_run_carries_message_history_into_each_save_retry` with:

```python
def test_run_carries_history_once_then_uses_fresh_final_retry(
    tmp_path,
    monkeypatch,
    capsys,
):
    fake_agent = _InterpreterRetryAgent(
        tmp_path,
        part=3,
        write_on_call=None,
    )
    monkeypatch.setitem(
        sys.modules,
        "src.agents.deep_interpreter.graph_builder",
        SimpleNamespace(create_subagent_graph=lambda *_args, **_kwargs: fake_agent),
    )

    exit_code = asyncio.run(run_script.run(_args(tmp_path, 3)))

    stdout = capsys.readouterr().out
    assert exit_code == 1
    assert len(fake_agent.payloads) == 3

    initial_messages = fake_agent.payloads[0]["messages"]
    first_retry_messages = fake_agent.payloads[1]["messages"]
    final_retry_messages = fake_agent.payloads[2]["messages"]

    assert first_retry_messages[:-1] == [
        *initial_messages,
        {"role": "assistant", "content": "attempt-1"},
        {
            "role": "tool",
            "content": "tool-result-1",
            "tool_call_id": "tool-call-1",
        },
    ]
    assert "Continue the existing Part 3 attempt" in first_retry_messages[-1]["content"]

    assert len(final_retry_messages) == 1
    assert final_retry_messages[0]["role"] == "user"
    assert "Start a fresh Part 3 save recovery" in final_retry_messages[0]["content"]
    assert "attempt-1" not in final_retry_messages[0]["content"]
    assert "tool-result-1" not in final_retry_messages[0]["content"]
    assert stdout.count('"fresh_context": false') >= 1
    assert stdout.count('"fresh_context": true') >= 1
```

- [ ] **Step 3: Verify RED**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/test_run_deep_interpreter_agent_cli.py::test_interpreter_final_save_retry_message_starts_fresh \
  tests/test_run_deep_interpreter_agent_cli.py::test_run_carries_history_once_then_uses_fresh_final_retry
```

Expected: FAIL because `_build_interpreter_save_retry_message` does not accept
`fresh_context` and both retries currently carry accumulated messages.

- [ ] **Step 4: Implement the two recovery message shapes**

Extend `_build_interpreter_save_retry_message` without duplicating the base
Part assignment:

```python
def _build_interpreter_save_retry_message(
    data_dir: Path,
    part: int,
    *,
    fresh_context: bool = False,
) -> str:
    if part not in {1, 2, 3}:
        raise ValueError("interpreter save retry requires Part 1, 2, or 3")
    base_message = _build_subagent_message("interpreter", data_dir, {}, part)
    if fresh_context:
        context_instruction = f"""Start a fresh Part {part} save recovery for {data_dir}.

No prior conversation or tool results are attached. Call load_analysis_data for this data directory, then complete the assigned Part report. Do not summarize raw CSV structure or return a generic dataset description."""
    else:
        context_instruction = f"""Continue the existing Part {part} attempt for {data_dir}.

Use the conversation and tool results above. Do not restart the analysis from scratch.
Reuse an existing load_analysis_data result when it is already present in the conversation.
Call load_analysis_data only if no usable result is present."""

    return f"""{context_instruction}

Do not blindly save a generic or incomplete previous response.
Correct or complete the report so it satisfies every assigned Part requirement.

{base_message}

Your final action MUST be write_file(file_path="/part{part}_final.md", content="complete markdown Part {part} report").
A chat response without that tool call is incomplete."""
```

- [ ] **Step 5: Use fresh context only on the final retry**

Inside the existing retry loop, calculate and record one flag:

```python
fresh_context = retry_number == MAX_INTERPRETER_INVOKE_ATTEMPTS - 1
```

Add `"fresh_context": fresh_context` to the retry-start event and the attempt
record. Build the retry message with the flag and invoke with:

```python
retry_messages = [retry_message] if fresh_context else [*messages, retry_message]
result = await agent.ainvoke({"messages": retry_messages}, config=None)
```

Do not change the loop range, output existence check, exception handling, or
terminal return code.

- [ ] **Step 6: Run focused and full runner tests to GREEN**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/test_run_deep_interpreter_agent_cli.py
uv run ruff check \
  scripts/run_deep_interpreter_agent.py \
  tests/test_run_deep_interpreter_agent_cli.py
uv run python -m py_compile scripts/run_deep_interpreter_agent.py
git diff --check
```

Expected: all runner tests pass, including third-attempt success, three-attempt
exhaustion, early stop when the file exists, and guardrail exception behavior.

- [ ] **Step 7: Commit Task 1 with Lore trailers**

```bash
git add scripts/run_deep_interpreter_agent.py tests/test_run_deep_interpreter_agent_cli.py
git add -f \
  docs/superpowers/plans/2026-08-20-interpreter-fresh-save-recovery.md \
  docs/superpowers/specs/2026-08-20-interpreter-fresh-save-recovery-design.md
git commit -m "Let the final report-save retry escape a drifted context

Constraint: Preserve three total interpreter invocations and real write_file completion
Rejected: Auto-saving assistant chat | Generic CSV summaries are not valid reports
Rejected: Additional retries | Repeating a drifted context does not repair the control failure
Confidence: high
Scope-risk: narrow
Directive: Keep only the final save retry fresh and Part-specific
Tested: test_run_deep_interpreter_agent_cli.py; Ruff; py_compile; git diff --check
Not-tested: Live qwen3.5:122b Part 3 smoke"
```

---

### Task 2: Pass a disposable production-shaped Part 3 smoke

**Files:**
- Verification only; use a `mktemp -d` copy of the failed attempt-2 no-SNI condition.

**Interfaces:**
- Consume: Task 1 retry behavior.
- Produce: a real `part3_final.md`, scoped Part 3 guardrail pass, timing artifact, and preserved heading/PMID evidence.

- [ ] **Step 1: Re-run the complete relevant regression gate**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/test_run_deep_interpreter_agent_cli.py \
  tests/scripts/test_repair_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/scripts/test_validate_report.py \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/agents/deep_interpreter/test_synthesis_consistency_validation.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py \
  tests/test_rag_path_resolution.py \
  tests/test_sni_ablation_runner.py \
  tests/test_reporter.py \
  tests/test_reporter_phase5.py
```

Expected: exit 0. Record the exact test count and pre-existing warnings.

- [ ] **Step 2: Verify live dependencies and copy the failed Part 3 condition**

```bash
curl --fail --silent http://localhost:6000/api/tags | jq -e '.models[] | select(.name == "qwen3.5:122b")'
curl --fail --silent --show-error http://localhost:8883/health
part3_smoke_source="res/deep_interpreter/bc/sni_repair_ablation/safe_complete_20260819T233329Z/pairs/pair-05/wiki-off"
part3_smoke_dir="$(mktemp -d /tmp/deepmast-part3-save-smoke.XXXXXX)"
cp -R "${part3_smoke_source}/." "${part3_smoke_dir}/"
test ! -e "${part3_smoke_dir}/part3_final.md"
```

- [ ] **Step 3: Run Part 3 with the production model, collection binding, and scoped guardrail**

```bash
PART3_SMOKE_DIR="${part3_smoke_dir}" uv run python - <<'PY'
import asyncio
import json
import os
import shutil
from pathlib import Path

from scripts import run_bc_sni_repair_ablation as ablation
from src.agents.deep_interpreter.middleware import report_guardrail as middleware_guardrail

data_dir = Path(os.environ["PART3_SMOKE_DIR"]).resolve()
env = {
    "LLM_PROVIDER": "ollama",
    "OLLAMA_BASE_URL": "http://localhost:6000",
    "OLLAMA_MODEL": "qwen3.5:122b",
    "OLLAMA_REASONING": "true",
    "OLLAMA_REQUEST_TIMEOUT_SECONDS": "10800",
    "CLAIM_RAG_JUDGE_NUM_PREDICT": "3000",
    "CLAIM_RAG_JUDGE_TIMEOUT_SECONDS": "300",
    "CLAIM_RAG_PRIMARY_JUDGE_TIMEOUT_SECONDS": "180",
    "CLAIM_RAG_SINGLE_CLAIM_TIMEOUT_SECONDS": "120",
    "CCI_RAG_BASE_URL": "http://localhost:8883",
    "DEEP_INTERPRETER_DATA_DIR": str(data_dir),
    "DEEP_INTERPRETER_USE_WIKI_CONTEXT": "false",
    "DEEP_INTERPRETER_REQUIRE_AGENTIC_RAG": "true",
    "DEEP_INTERPRETER_FIXED_COLLECTION_ID": "a208e916-bd32-405a-9eee-de4cd82b2a3b",
    "DEEP_INTERPRETER_RAG_AUDIT_PATH": str(data_dir / "rag_audit_part3_smoke.jsonl"),
}

def run() -> int:
    aliases = ablation._bind_read_only_collection(data_dir)
    ablation._disable_collection_preparation_tool()
    ablation.write_json(
        data_dir / "rag_binding.json",
        {"collection_id": ablation.BC_COLLECTION_ID, "aliases": aliases},
    )
    original_guardrail = middleware_guardrail.run_report_guardrail

    def scoped_guardrail(path, *, provider=None, filenames=ablation.REPORT_FILES[:3]):
        resolved = Path(path).resolve()
        before_dir = resolved / "before_part3_smoke"
        before_dir.mkdir(exist_ok=True)
        source = resolved / "part3_final.md"
        if source.is_file() and not (before_dir / source.name).exists():
            shutil.copy2(source, before_dir / source.name)
        result = original_guardrail(
            resolved,
            provider=provider,
            filenames=("part3_final.md",),
        )
        ablation.write_json(resolved / "part3_smoke_guardrail.json", result)
        return result

    middleware_guardrail.run_report_guardrail = scoped_guardrail
    try:
        stage = asyncio.run(ablation._run_deep_stage(data_dir, "part3", 3))
        ablation.write_json(data_dir / "part3_smoke_timing.json", stage)
        return int(stage["return_code"])
    finally:
        middleware_guardrail.run_report_guardrail = original_guardrail

return_code = ablation._with_env(env, run)
result = json.loads((data_dir / "part3_smoke_guardrail.json").read_text())
print(json.dumps({"return_code": return_code, "guardrail": result}, indent=2))
assert return_code == 0
assert (data_dir / "part3_final.md").is_file()
assert result["status"] == "passed"
assert result["final_error_count"] == 0
PY
```

- [ ] **Step 4: Verify smoke structure and evidence**

```bash
diff \
  <(rg '^#{1,6} ' "${part3_smoke_dir}/before_part3_smoke/part3_final.md") \
  <(rg '^#{1,6} ' "${part3_smoke_dir}/part3_final.md")
jq . "${part3_smoke_dir}/part3_smoke_timing.json"
jq . "${part3_smoke_dir}/part3_smoke_guardrail.json"
test -s "${part3_smoke_dir}/part3_final.md"
```

Require an unchanged historical source, no newly introduced PMID, fixed UUID
in the smoke RAG audit, and no modification outside the disposable directory.

- [ ] **Step 5: Stop at the smoke gate on any failure**

If Part 3 does not save, the scoped guardrail does not pass, headings change,
or a new PMID appears, preserve the smoke directory and evidence and return to
Task 1's TDD/fix loop. Do not start a full pair.

---

### Task 3: Complete one fresh canonical no-SNI then SNI pair

**Files:**
- Live verification only; generated outputs remain under ignored `res/` paths.

**Interfaces:**
- Consume: reviewed Task 1 code and passed Task 2 smoke.
- Produce: one complete pair-05 comparison with both manifests passed.

- [ ] **Step 1: Recheck canonical invariants**

Require ports 4000 and 6000 to list `qwen3.5:122b`, API 8883 healthy, fixed
collection UUID/counts unchanged, source/collection exact 100-PMID identity,
pair-05 order no-SNI → SNI, and no active matching runner.

- [ ] **Step 2: Launch one fresh pair without external cutoff**

```bash
save_recovery_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
save_recovery_root="res/deep_interpreter/bc/sni_repair_ablation/save_recovery_${save_recovery_stamp}/pairs"
uv run python scripts/run_bc_sni_repair_ablation.py \
  --pair 5 \
  --output-root "${save_recovery_root}" \
  --source /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res/deep_interpreter/bc/bc \
  --manifest res/deep_interpreter/bc/sni_repair_ablation/experiment_manifest_rag4000.json
```

Keep the process in a managed foreground session and monitor Part and condition
boundaries. Do not start another full run if this one fails; preserve evidence.

- [ ] **Step 3: Verify the no-SNI boundary**

Before accepting SNI progress, require the no-SNI manifest passed,
`report_validation_final.json` and synthesis validation contain zero hard
errors, Part/synthesis headings are preserved, fixed PMID identity remains 100,
and the repair trace has no accepted unsafe or ambiguous target.

- [ ] **Step 4: Verify SNI and summarize**

After terminal completion:

```bash
uv run python scripts/run_bc_sni_repair_ablation.py \
  --summarize \
  --output-root "${save_recovery_root}" \
  --source /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res/deep_interpreter/bc/bc \
  --manifest res/deep_interpreter/bc/sni_repair_ablation/experiment_manifest_rag4000.json
```

Require both manifests passed and no lingering runner. Report initial/final
errors, regular/terminal/total repairs, deterministic/replace/delete counts,
changed targets, heading preservation, retrieval attempts/positive/zero-hit/
unique PMIDs/time, total elapsed time, and source/selected/cited/collection PMID
flow for each condition.

---

## Plan Self-Review

- Spec coverage: history-preserving first retry, fresh final retry, bounded
  failure, audit metadata, Part 3 smoke, and final pair each map to a task.
- Minimality: one production file and one test file change; no new runtime
  component or dependency is introduced.
- Type consistency: `_build_interpreter_save_retry_message`, `run`,
  `fresh_context`, retry events, and existing return types are consistent.
- TDD: the fresh message and exact payload shape fail before implementation and
  pass after the minimal loop change.
- Safety: chat content is never written automatically; file existence and
  Report Guardrail remain the completion gates.
- Performance: the Part 3 smoke gates the expensive fresh pair.
- Placeholder scan: every code change, test, command, expected result, and stop
  condition is explicit.


# Part Guardrail Failure Propagation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent Interpreter and standalone CLI runs from reporting success when bounded part-level report repair finishes with hard validation errors.

**Architecture:** Keep `run_report_guardrail()` as the single validator/repair owner and preserve its existing structured result and JSON artifacts. Convert only `status == "failed"` into an exception at the `ReportGuardrailMiddleware` boundary; the existing standalone runner already converts agent exceptions into `invoke_error` and exit code `1`, while embedded LangGraph execution will no longer receive a normal success message for a failed report.

**Tech Stack:** Python 3.12, LangChain `AgentMiddleware`, LangGraph runtime hooks, pytest, Ruff, Pyright, Git/GitHub PR #54.

## Global Constraints

- Preserve `MAX_GUARDRAIL_REPAIR_PASSES = 3` and early exit when hard errors reach zero.
- Keep warning-only results non-blocking.
- Keep `status == "skipped"` silent so incomplete Part 1/2 runs and Part 3 save recovery retain their current behavior.
- Preserve `report_validation_initial.json` and `report_validation_final.json` names and contents.
- Do not change Synthesis guardrail behavior; it already blocks HTML rendering on failure.
- Do not add dependencies or introduce a second validation path in the CLI.
- Do not include local uncommitted changes in `src/agents/deep_interpreter/tools/report.py`, `tests/deep_interpreter/test_report_therapeutic_summary.py`, or any `tmp_*` directory.

## File Structure

- Modify `src/agents/deep_interpreter/middleware/report_guardrail.py`: raise a report failure after the bounded repair loop leaves hard errors.
- Modify `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`: replace the current soft-failure expectation and cover sync/async failure propagation without regressing passed/skipped behavior.
- Modify `tests/test_run_deep_interpreter_agent_cli.py`: lock the existing agent-exception-to-exit-1 contract used by standalone execution.

---

### Task 1: Make Part Guardrail Failure a Hard Agent Failure

**Files:**
- Modify: `src/agents/deep_interpreter/middleware/report_guardrail.py:30-49`
- Modify: `tests/agents/deep_interpreter/test_report_guardrail_middleware.py:400-512`

**Interfaces:**
- Consumes: `run_report_guardrail(data_dir: str | Path, *, provider: str | None = None) -> dict[str, Any]`
- Preserves: `ReportGuardrailMiddleware.after_agent(...) -> dict[str, Any] | None` for passed/skipped runs
- Produces: `RuntimeError` containing the remaining hard-error count and `report_validation_final.json` path when `result["status"] == "failed"`

- [ ] **Step 1: Add failing sync and async middleware tests**

Replace the existing async soft-failure assertion and add the equivalent sync contract:

```python
def _failed_guardrail_result() -> dict[str, object]:
    return {
        "status": "failed",
        "initial_issue_count": 1,
        "initial_error_count": 1,
        "repair_attempt_count": 3,
        "changed_sections": 0,
        "final_issue_count": 1,
        "final_error_count": 1,
    }


def test_report_guardrail_middleware_raises_when_hard_errors_remain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter.middleware.report_guardrail import ReportGuardrailMiddleware

    monkeypatch.setattr(
        "src.agents.deep_interpreter.middleware.report_guardrail.run_report_guardrail",
        lambda *_args, **_kwargs: _failed_guardrail_result(),
    )

    with pytest.raises(
        RuntimeError,
        match=r"Report guardrail failed with 1 hard error\(s\).*report_validation_final\.json",
    ):
        ReportGuardrailMiddleware(data_dir=tmp_path).after_agent(_agent_state(), None)


@pytest.mark.asyncio
async def test_report_guardrail_middleware_async_hook_raises_when_hard_errors_remain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter.middleware.report_guardrail import ReportGuardrailMiddleware

    monkeypatch.setattr(
        "src.agents.deep_interpreter.middleware.report_guardrail.run_report_guardrail",
        lambda *_args, **_kwargs: _failed_guardrail_result(),
    )

    with pytest.raises(
        RuntimeError,
        match=r"Report guardrail failed with 1 hard error\(s\).*report_validation_final\.json",
    ):
        await ReportGuardrailMiddleware(data_dir=tmp_path).aafter_agent(_agent_state(), None)
```

- [ ] **Step 2: Run the focused tests and verify the red state**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_report_guardrail_middleware_raises_when_hard_errors_remain \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_report_guardrail_middleware_async_hook_raises_when_hard_errors_remain
```

Expected: both tests fail with `Failed: DID NOT RAISE <class 'RuntimeError'>` because failed results are still returned as `AIMessage` content.

- [ ] **Step 3: Add the minimal failure gate in the shared middleware path**

Insert the failure branch after the existing skipped branch in `ReportGuardrailMiddleware._run()`:

```python
        result = run_report_guardrail(data_dir, provider=self._provider)
        if result.get("status") == "skipped":
            return None
        if result.get("status") == "failed":
            final_error_count = result.get("final_error_count", "unknown")
            validation_path = data_dir / "report_validation_final.json"
            raise RuntimeError(
                "Report guardrail failed with "
                f"{final_error_count} hard error(s); see {validation_path}"
            )

        return {
            "messages": [
                AIMessage(
                    content=json.dumps(
                        {"report_guardrail": result},
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            ]
        }
```

Do not add exception handling inside the middleware. The exception must leave the agent boundary so the existing CLI `ainvoke` error path can return nonzero.

- [ ] **Step 4: Run middleware regression tests**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
```

Expected: all middleware tests pass. In particular, passed results still return guardrail metadata, skipped results still return `None`, and failed results raise in both sync and async hooks.

- [ ] **Step 5: Commit the middleware failure contract**

```bash
git add -f docs/superpowers/plans/2026-07-15-part-guardrail-failure-propagation.md
git add \
  src/agents/deep_interpreter/middleware/report_guardrail.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
git commit -m "$(cat <<'EOF'
Stop invalid interpreter reports from completing successfully

Constraint: Warning-only and incomplete pre-Part3 states must remain non-blocking.
Rejected: Revalidate separately in the CLI | duplicates the middleware-owned guardrail path.
Confidence: high
Scope-risk: narrow
Directive: Keep failed part validation fatal while preserving bounded repair and JSON evidence.
Tested: OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py
Not-tested: Live Ollama failure exhaustion path.
EOF
)"
```

---

### Task 2: Lock Standalone CLI Nonzero Propagation

**Files:**
- Modify: `tests/test_run_deep_interpreter_agent_cli.py:110-209`
- Verify only: `scripts/run_deep_interpreter_agent.py:296-318`

**Interfaces:**
- Consumes: an exception raised by `agent.ainvoke(...)`, including `RuntimeError` from `ReportGuardrailMiddleware`
- Produces: stderr event `invoke_error` and process return code `1`
- Preserves: Part 3 save retry only for missing `/part3_final.md`; guardrail failures must not be converted into save retries

- [ ] **Step 1: Add a CLI regression test for guardrail exceptions**

Add a fake agent and test beside the existing Part 3 retry tests:

```python
class _GuardrailFailureAgent:
    async def ainvoke(self, payload, config=None):
        raise RuntimeError(
            "Report guardrail failed with 1 hard error(s); "
            "see /tmp/report_validation_final.json"
        )


def test_run_returns_nonzero_when_report_guardrail_raises(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    fake_agent = _GuardrailFailureAgent()
    monkeypatch.setitem(
        sys.modules,
        "src.agents.deep_interpreter.graph_builder",
        SimpleNamespace(create_subagent_graph=lambda *_args, **_kwargs: fake_agent),
    )

    exit_code = asyncio.run(run_script.run(_args(tmp_path, 3)))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert '"event": "invoke_error"' in captured.err
    assert '"exception_type": "RuntimeError"' in captured.err
    assert "Report guardrail failed with 1 hard error" in captured.err
    assert "part3_save_retry_start" not in captured.out
```

- [ ] **Step 2: Run the CLI regression test**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/test_run_deep_interpreter_agent_cli.py::test_run_returns_nonzero_when_report_guardrail_raises
```

Expected: PASS. This test locks the runner's already-existing generic `ainvoke` exception handling; no production change to `scripts/run_deep_interpreter_agent.py` is expected.

- [ ] **Step 3: Run the complete CLI retry suite**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q tests/test_run_deep_interpreter_agent_cli.py
```

Expected: all tests pass, including successful third-attempt save, bounded missing-output failure, early save success, and immediate guardrail failure.

- [ ] **Step 4: Commit the standalone propagation regression**

```bash
git add tests/test_run_deep_interpreter_agent_cli.py
git commit -m "$(cat <<'EOF'
Keep report guardrail failures visible to standalone callers

Constraint: Reuse the runner's existing invoke-error path without adding duplicate validation.
Rejected: Parse guardrail JSON from AI messages | failed middleware results should never become success messages.
Confidence: high
Scope-risk: narrow
Directive: Do not route guardrail failures through Part 3 save recovery.
Tested: OPENAI_API_KEY=test uv run pytest -q tests/test_run_deep_interpreter_agent_cli.py
Not-tested: Live Ollama failure exhaustion path.
EOF
)"
```

---

### Task 3: Verify the PR Against Current Remote Main

**Files:**
- Verify: all files changed by PR #54
- Do not modify: local dirty `main`, `tmp_final_bc/`, `tmp_final_ipf/`, `tmp_interpreter_runs/`

**Interfaces:**
- Consumes: updated feature branch with fatal part guardrail behavior
- Produces: merge-readiness evidence for PR #54

- [ ] **Step 1: Run the targeted guardrail and reporter suite**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/scripts/test_validate_report.py \
  tests/scripts/test_repair_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/test_run_deep_interpreter_agent_cli.py \
  tests/test_reporter.py \
  tests/test_reporter_phase45.py \
  tests/test_reporter_phase5.py \
  tests/deep_interpreter/test_skill_loader.py \
  tests/deep_interpreter/test_comprehensive_template_report.py
```

Expected: all selected tests pass with no failures.

- [ ] **Step 2: Run static checks on committed PR Python files**

Run:

```bash
git diff --name-only --diff-filter=ACM origin/main...HEAD -- '*.py' \
  | xargs uv run ruff check

uv run pyright \
  scripts/validate_report.py \
  scripts/repair_report.py \
  scripts/validate_repair_report.py \
  scripts/run_deep_interpreter_agent.py \
  src/agents/deep_interpreter/report_guardrails.py \
  src/agents/deep_interpreter/middleware/report_guardrail.py \
  src/agents/deep_interpreter/graph_builder.py \
  src/agents/deep_interpreter/subagents/configs.py \
  src/agents/deep_interpreter/subagents/prompts.py

git diff --check origin/main...HEAD
```

Expected: Ruff passes, Pyright reports `0 errors, 0 warnings`, and `git diff --check` emits no output.

- [ ] **Step 3: Verify a clean merge against the latest remote main**

Use a temporary worktree so the dirty local `main` is never checked out or modified:

```bash
git fetch origin main feat/report-validate-repair-loop
merge_dir="/tmp/deepmast-pr54-final-merge-$(date +%s)"
git worktree add --detach "$merge_dir" origin/main
git -C "$merge_dir" merge --no-commit --no-ff origin/feat/report-validate-repair-loop
(
  cd "$merge_dir"
  OPENAI_API_KEY=test uv run --active pytest -q \
    tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
    tests/test_run_deep_interpreter_agent_cli.py
)
git -C "$merge_dir" merge --abort
git worktree remove "$merge_dir"
```

Expected: merge reports no conflicts and both post-merge test modules pass.

- [ ] **Step 4: Push commits and update PR state**

Run:

```bash
git push origin feat/report-validate-repair-loop
gh pr view 54 --json mergeable,mergeStateStatus,isDraft,statusCheckRollup,headRefOid
```

Expected: the PR head matches local `HEAD`, `mergeable` is `MERGEABLE`, and `mergeStateStatus` is `CLEAN`. Keep the PR draft until the fresh review confirms that no blocking findings remain.

## Self-Review

- Spec coverage: Task 1 makes failed part validation fatal; Task 2 proves standalone exit `1`; Task 3 verifies clean integration with current remote `main`.
- Preserved behavior: warnings, skipped incomplete runs, bounded repair, Part 3 save retry, Synthesis gating, and validation artifact names are explicitly unchanged.
- Placeholder scan: no deferred implementation or unspecified tests remain.
- Type consistency: all code uses the existing `dict[str, Any]` result contract and existing sync/async middleware hook signatures.

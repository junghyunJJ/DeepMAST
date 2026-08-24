# Reporter Recovery Final Review Fix Report

## Scope

Implemented only the two final-review fixes from `final-review-fix-brief.md`:

1. Synchronous Reporter task timeout recovery now waits for the already-running timed-out handler before quarantine/retry begins, preventing attempt-1 and attempt-2 artifact writes from racing.
2. Retry preparation is persisted immediately after quarantine/preservation, and non-timeout invocation exceptions are recorded in `reporter_recovery.json` before the original exception is re-raised.

Changed files:

- `src/agents/deep_interpreter/reporter_recovery.py`
- `tests/agents/deep_interpreter/test_reporter_recovery.py`

No live Reporter replay was run. No RAG, SNI, Claim-RAG, timeout value, guardrail, dependency, or attempt-count changes were made.

## TDD Cycle 1: Timed-Out Sync Handler Late Writer

### RED

Added/modified:

- `test_reporter_task_recovery_middleware_waits_for_timed_out_sync_reporter`

The test makes attempt 1 sleep past the timeout, write invalid `synthesis.md`, and return. Attempt 2 writes valid Reporter outputs. It asserts attempt 2 starts only after attempt 1 finishes, total duration includes attempt-1 cleanup, and final `synthesis.md` remains valid after a post-return sleep.

Command:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_reporter_recovery.py -k 'waits_for_timed_out_sync_reporter or persists_retry_audit_when_second_attempt_raises'
```

Observed RED:

```text
FAILED test_reporter_task_recovery_middleware_waits_for_timed_out_sync_reporter
AssertionError: At index 1 diff: 'attempt-2-start' != 'attempt-1-finish'
```

This proved the old sync middleware started attempt 2 before the timed-out attempt 1 finished.

### GREEN

Production change:

- Use a single-thread `ThreadPoolExecutor` for synchronous Reporter task recovery.
- Wrap the submitted future in `asyncio.shield`.
- On cancellation from `asyncio.wait_for`, await the already-running handler future before re-raising cancellation so the recovery loop still records a timeout and retries only after attempt 1 finishes.
- Shut the executor down with `wait=True`.

Focused GREEN command:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_reporter_recovery.py -k 'waits_for_timed_out_sync_reporter or persists_retry_audit_when_second_attempt_raises'
```

Observed GREEN:

```text
2 passed, 15 deselected, 1 warning in 2.19s
```

## TDD Cycle 2: Retry Audit Persistence and Exception Recording

### RED

Added:

- `test_reporter_recovery_persists_retry_audit_when_second_attempt_raises`

The test has attempt 1 write invalid HTML and return incomplete. It asserts attempt 2 starts after `synthesis.md` is quarantined, then raises `RuntimeError("retry exploded")`. It verifies the original `RuntimeError` is re-raised and `reporter_recovery.json` persists retry preparation, failed status, attempt count 2, and attempt-2 exception metadata.

Command:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_reporter_recovery.py -k 'waits_for_timed_out_sync_reporter or persists_retry_audit_when_second_attempt_raises'
```

Observed RED:

```text
FAILED test_reporter_recovery_persists_retry_audit_when_second_attempt_raises
FileNotFoundError: reporter_recovery.json
```

This proved retry preparation/audit state was not persisted before attempt 2 raised.

### GREEN

Production change:

- Write `reporter_recovery.json` immediately after `_prepare_synthesis_retry()` and before attempt 2 begins.
- Add a non-timeout `Exception` path in `run_reporter_with_recovery()` that records duration, completion state, repeated-invalid-synthesis state, `exception_type`, and `exception_repr`, writes failed audit status, and re-raises the original exception.

Focused GREEN command:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_reporter_recovery.py -k 'waits_for_timed_out_sync_reporter or persists_retry_audit_when_second_attempt_raises'
```

Observed GREEN:

```text
2 passed, 15 deselected, 1 warning in 2.19s
```

## Full Verification

Command:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/deep_interpreter/test_reporter_prompt_policy.py
```

Observed:

```text
87 passed, 1 warning in 2.62s
```

Warning was the existing LangGraph `config_schema` deprecation from `src/base/base_agent.py`.

Command:

```bash
uv run ruff check \
  src/agents/deep_interpreter/reporter_recovery.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py
```

Observed:

```text
All checks passed!
```

Command:

```bash
uv run python -m py_compile \
  src/agents/deep_interpreter/reporter_recovery.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py
```

Observed: exit 0.

Command:

```bash
git diff --check
```

Observed: exit 0.

## Self-Review

- Scope stayed within Reporter recovery, its tests, and this requested report.
- `MAX_REPORTER_ATTEMPTS` and timeout configuration were not changed.
- Non-timeout invocation exceptions are not converted to retries or `ReporterRecoveryError`; the original exception is re-raised after audit persistence.
- Timeout recovery behavior is preserved: timeout attempts still enter the existing retry path, with sync handlers now drained before retry.
- The sync fix intentionally waits for an already-running Python thread because it cannot be safely killed.

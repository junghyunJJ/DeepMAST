# Task 2 Report: Quarantine Invalid Synthesis

## Status

Complete.

## Changes

- Strengthened invalid-synthesis retry coverage so attempt 2 must start without the invalid working `synthesis.md`, must name `synthesis_not_markdown`, and must record retry preparation in the audit.
- Added coverage for byte-identical invalid retry output, asserting `repeated_invalid_synthesis` is recorded on attempt 2 and the first invalid artifact is preserved as `synthesis_reporter_attempt1.md`.
- Replaced copy-only retry setup with `_prepare_synthesis_retry`, which copies attempt 1 synthesis for audit, removes invalid HTML synthesis from the retry workspace, preserves valid synthesis, and records the attempt 1 SHA256.
- Extended the recovery prompt to include quarantine failure feedback only for rebuild retries.
- Added repeated invalid output detection without adding a third attempt.

## RED Evidence

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py::test_reporter_recovery_uses_fresh_context_once
```

Result: failed as expected because attempt 2 still saw `synthesis.md`.

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py::test_reporter_recovery_records_byte_identical_invalid_retry
```

Result: failed as expected with `KeyError: 'repeated_invalid_synthesis'`.

## GREEN Evidence

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py::test_reporter_recovery_uses_fresh_context_once \
  tests/agents/deep_interpreter/test_reporter_recovery.py::test_reporter_recovery_records_byte_identical_invalid_retry
```

Result: `2 passed, 1 warning`.

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/deep_interpreter/test_reporter_prompt_policy.py
```

Result: `85 passed, 1 warning`.

```bash
uv run ruff check src/agents/deep_interpreter/reporter_recovery.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py
```

Result: `All checks passed!`.

## Notes

- The warning is the existing `LangGraphDeprecatedSinceV10` warning from `src/base/base_agent.py:129`.
- Live Reporter replay was not run.

## Fix Round 1

### Issue

`_prepare_synthesis_retry()` incorrectly filtered retry `failure_codes` down to only `synthesis_not_markdown`. The spec requires retaining every `validate_synthesis_report()` issue with `severity == "error"`; `synthesis_not_markdown` only decides whether the invalid working synthesis is unlinked.

### RED Evidence

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py::test_reporter_recovery_retains_all_invalid_retry_error_codes
```

Result: failed as expected because the retry prompt lacked `papers_json_missing`.

### GREEN Evidence

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py::test_reporter_recovery_retains_all_invalid_retry_error_codes
```

Result: `1 passed, 1 warning`.

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py::test_reporter_recovery_uses_fresh_context_once \
  tests/agents/deep_interpreter/test_reporter_recovery.py::test_reporter_recovery_retains_all_invalid_retry_error_codes \
  tests/agents/deep_interpreter/test_reporter_recovery.py::test_reporter_recovery_records_byte_identical_invalid_retry
```

Result: `3 passed, 1 warning`.

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/deep_interpreter/test_reporter_prompt_policy.py
```

Result: `86 passed, 1 warning`.

```bash
uv run ruff check src/agents/deep_interpreter/reporter_recovery.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py
```

Result: `All checks passed!`.

# Task 2 Report: Wire Shared Recovery into Full LangGraph and Standalone Reporter

## Files Changed
- `src/agents/deep_interpreter/middleware/__init__.py` exports `ReporterTaskRecoveryMiddleware`.
- `src/agents/deep_interpreter/agent.py` attaches one parent-level `ReporterTaskRecoveryMiddleware` to `create_deep_agent`.
- `src/agents/deep_interpreter/graph_builder.py` wraps only the standalone reporter graph after existing recursion config.
- `src/agents/deep_interpreter/reporter_recovery.py` adds `wrap_reporter_runnable`.
- `tests/agents/deep_interpreter/test_reporter_recovery.py` adds full-graph middleware wiring and reporter-task interception tests.
- `tests/agents/deep_interpreter/test_report_guardrail_middleware.py` asserts reporter-only standalone wrapper metadata.

## RED Evidence
Command:
```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  -k 'reporter_recovery or standalone_subagent_graph_uses_configured_middleware'
```

Result:
```text
2 failed, 9 passed, 32 deselected, 1 warning
FAILED test_deep_interpreter_agent_attaches_reporter_recovery_middleware
  assert 0 == 1
FAILED test_standalone_subagent_graph_uses_configured_middleware
  getattr(graph, "reporter_recovery_enabled", False) is False
```

## GREEN Evidence
Focused command:
```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  -k 'reporter_recovery or standalone_subagent_graph_uses_configured_middleware'
```

Result:
```text
11 passed, 32 deselected, 1 warning
```

Affected pytest command:
```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/test_run_deep_interpreter_agent_cli.py \
  tests/deep_interpreter/test_comprehensive_template_report.py \
  tests/deep_interpreter/test_reporter_prompt_policy.py
```

Result:
```text
90 passed, 1 warning
```

Static checks:
```bash
uv run ruff check \
  src/agents/deep_interpreter/reporter_recovery.py \
  src/agents/deep_interpreter/middleware/__init__.py \
  src/agents/deep_interpreter/agent.py \
  src/agents/deep_interpreter/graph_builder.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
```

```text
All checks passed!
```

```bash
uv run pyright \
  src/agents/deep_interpreter/reporter_recovery.py \
  src/agents/deep_interpreter/agent.py \
  src/agents/deep_interpreter/graph_builder.py
```

```text
0 errors, 0 warnings, 0 informations
```

Whitespace check:
```bash
git diff --check
```

```text
passed with no output
```

```bash
git diff --check
```

```text
passed with no output
```

## Self-Review
- Full Deep Agent recovery is parent-level only, so it sees and replaces `task(subagent_type="reporter")`; planner/searcher/interpreter subagent configs are not given the middleware.
- `ReporterTaskRecoveryMiddleware` still gates on tool name `task` and `subagent_type == "reporter"`, so non-reporter tasks pass through unchanged.
- Standalone `create_subagent_graph` builds the existing agent and recursion config first. Planner, searcher, and interpreter return the configured agent unchanged. Reporter alone returns `wrap_reporter_runnable(...)`.
- The standalone wrapper delegates retry/completion behavior to `run_reporter_with_recovery`; it does not introduce another retry loop.
- The wrapper preserves caller runnable config when calling the underlying reporter and sends a fresh one-message user state for each attempt.
- Existing unrelated dirty files were not edited or reverted.

## Concerns
- Live Ollama execution was not run; verification stayed model-free per the brief.
- Pytest emits a pre-existing LangGraph deprecation warning from `src/base/base_agent.py:129`.
- `uv` warns that the active `VIRTUAL_ENV` differs from the project `.venv`; commands still completed successfully.

## Review Fix Evidence
- Updated `tests/agents/deep_interpreter/test_reporter_recovery.py` type annotations in the middleware test: `seen_calls` is `list[ToolCall]`, `runtime` is explicitly cast for `ToolCallRequest`, and `ToolMessage | Command` results are narrowed before `.content`.
- Production behavior was not changed.

Focused pytest:
```bash
OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_reporter_recovery.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py -k 'reporter_recovery or standalone_subagent_graph_uses_configured_middleware'
```

```text
11 passed, 32 deselected, 1 warning
```

Ruff:
```bash
uv run ruff check src/agents/deep_interpreter/reporter_recovery.py src/agents/deep_interpreter/middleware/__init__.py src/agents/deep_interpreter/agent.py src/agents/deep_interpreter/graph_builder.py tests/agents/deep_interpreter/test_reporter_recovery.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py
```

```text
All checks passed!
```

Pyright:
```bash
uv run pyright src/agents/deep_interpreter/reporter_recovery.py src/agents/deep_interpreter/middleware/__init__.py src/agents/deep_interpreter/agent.py src/agents/deep_interpreter/graph_builder.py tests/agents/deep_interpreter/test_reporter_recovery.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py
```

```text
0 errors, 0 warnings, 0 informations
```

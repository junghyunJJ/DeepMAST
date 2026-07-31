# Contradiction Repair Task 1 Report

## Changes

- Added a narrowly gated exact-evidence contradiction rewrite before the existing synthesis hedge fallback.
- Added regression coverage for the LAMA5 contradiction rewrite and for fallback when a model rewrite omits the exact PMID.

## Verification

- Red: `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py -k contradiction` -> failed because the old hedge preserved `worse recurrence-free survival`.
- Focused tests: `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py` -> 30 passed, 1 existing LangGraph deprecation warning.
- Ruff: `uv run ruff check src/agents/deep_interpreter/report_guardrails.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py` -> all checks passed.
- Pyright: `uv run pyright src/agents/deep_interpreter/report_guardrails.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py` -> 0 errors, 0 warnings, 0 informations.

## Scope Notes

- Modified only `src/agents/deep_interpreter/report_guardrails.py`, `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`, and this report.
- Did not change collections, `mcp_clients`, other repair paths, or `.superpowers/sdd/task-3-report.md`.

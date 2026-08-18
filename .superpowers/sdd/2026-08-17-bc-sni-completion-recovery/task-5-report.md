# Task 5 Report: Exact Repair Routing

## Changed Files

- `scripts/repair_report.py` - routes `claim_rag_overclaimed`, `claim_rag_unsupported`, and `part3_therapeutic_spillover` through exact-claim repair; records rejected whole-section candidate metadata to an existing `repair_trace.jsonl`.
- `scripts/validate_report.py` - emits Part3 therapeutic spillover issues with the exact offending sentence as `value`.
- `tests/scripts/test_repair_report.py` - adds regression coverage for non-inline claim repair routing and rejected section audit rows.
- `tests/scripts/test_validate_report.py` - tightens Part3 spillover validation to require exact sentence values.

## RED Evidence

```text
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/scripts/test_repair_report.py::test_repair_routes_non_inline_claim_rag_overclaimed_to_exact_claim
F
E       assert 0 == 1
1 failed, 1 warning in 3.54s
```

```text
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/scripts/test_validate_report.py::test_flags_part3_therapeutic_spillover
F
E       AssertionError: assert 'therapeutic/druggability language' == 'MIF-CD74 is ...druggability.'
1 failed in 0.09s
```

```text
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/scripts/test_repair_report.py::test_rejected_section_repair_appends_metadata_without_candidate_text
F
E       assert 0 == 1
1 failed, 1 warning in 3.54s
```

## GREEN Evidence

```text
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/scripts/test_repair_report.py::test_repair_routes_non_inline_claim_rag_overclaimed_to_exact_claim
1 passed, 1 warning in 3.18s
```

```text
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/scripts/test_validate_report.py::test_flags_part3_therapeutic_spillover
1 passed in 0.02s
```

```text
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/scripts/test_repair_report.py::test_rejected_section_repair_appends_metadata_without_candidate_text
1 passed, 1 warning in 2.62s
```

## Verification

```text
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/scripts/test_validate_report.py tests/scripts/test_repair_report.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py
100 passed, 1 warning in 2.22s
```

```text
uv run ruff check scripts/validate_report.py scripts/repair_report.py tests/scripts/test_validate_report.py tests/scripts/test_repair_report.py
All checks passed!
```

```text
uv run python -m py_compile scripts/validate_report.py scripts/repair_report.py
exit 0
```

```text
git diff --check
exit 0
```

## Mutation Checks

- Non-inline `claim_rag_overclaimed` test fails if the code falls back to whole-section repair or edits the matching claim in a different section.
- Part3 therapeutic spillover test fails if the validator returns the previous generic value instead of an exact substring.
- Rejected section audit test fails if no audit row is appended or if candidate body text appears in `repair_trace.jsonl`.
- Existing unsafe exact-claim replacement tests still cover deletion, section heading output, and invented PMID rejection.

## Self-Review

- Scope stayed within the four owned code/test files plus this requested report.
- No fallback loop, new dependency, runner edit, service edit, artifact edit, or collection change was added.
- Remaining warning is pre-existing LangGraph `config_schema` deprecation from `src/base/base_agent.py`.

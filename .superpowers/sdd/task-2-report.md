# Task 2 Report: Make Structured Claim Judging Non-Thinking

Status: DONE

## Changed Files

- `src/agents/deep_interpreter/claim_rag_validation.py`
- `tests/agents/deep_interpreter/test_claim_rag_validation.py`
- `.superpowers/sdd/task-2-report.md`

## TDD Evidence

- RED: `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py -q`
  - Result: `2 failed, 28 passed`; failures showed `_create_judge_llm("ollama")` still forwarded `reasoning=True` and `_create_judge_llm("vllm")` still forwarded `enable_thinking=True`.
- GREEN: `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py tests/agents/test_model_ollama_openai.py`
  - Result: `58 passed, 4 warnings in 5.41s`.

## Implementation

- Changed structured Claim-RAG judge factory kwargs so local Ollama receives `reasoning=False`.
- Changed vLLM and Ollama-OpenAI structured judge kwargs so they receive `enable_thinking=False`.
- Preserved `CLAIM_RAG_JUDGE_NUM_PREDICT`, primary timeout, single-claim timeout, provider routing, model endpoints, output parsing, report-level `OLLAMA_REASONING`, and report guardrails.
- Added no configuration flag.

## Verification

- `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py tests/agents/test_model_ollama_openai.py`
  - Result: `58 passed, 4 warnings in 5.41s`.
- `uv run ruff check src/agents/deep_interpreter/claim_rag_validation.py tests/agents/deep_interpreter/test_claim_rag_validation.py`
  - Result: `All checks passed!`.
- `uv run pyright src/agents/deep_interpreter/claim_rag_validation.py tests/agents/deep_interpreter/test_claim_rag_validation.py`
  - Result: `0 errors, 0 warnings, 0 informations`.

## Self-Review

- Diff is limited to the allowed implementation file, allowed test file, and this report.
- Existing bounded `num_predict` and `request_timeout` assertions remain unchanged.
- Unrelated `.superpowers/sdd/task-3-report.md` modification was present before this task and was not touched.

## Notes

- `uv` printed the ambient `VIRTUAL_ENV` mismatch warning while using the project environment.
- Pytest retained pre-existing warnings from LangGraph `config_schema` deprecation and LangChain `parallel_tool_calls` model kwargs in the model tests.
- Pyright reported a newer version is available after passing.

## Review Fix Evidence

- Added direct coverage that `_create_judge_llm("ollama-openai")` forwards `enable_thinking=False` while preserving `num_predict=3000` and `request_timeout=300.0`.
- `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py tests/agents/test_model_ollama_openai.py`
  - Result: `58 passed, 4 warnings in 4.64s`.
- `uv run ruff check src/agents/deep_interpreter/claim_rag_validation.py tests/agents/deep_interpreter/test_claim_rag_validation.py`
  - Result: `All checks passed!`.
- `uv run pyright src/agents/deep_interpreter/claim_rag_validation.py tests/agents/deep_interpreter/test_claim_rag_validation.py`
  - Result: `0 errors, 0 warnings, 0 informations`.
- Notes: `uv` printed the ambient `VIRTUAL_ENV` mismatch warning; Pyright also reported a newer version is available.

## Hedged Inline Citation Review Fix

- Fix commit: `96b0c48`
- Changed: hedged `inline_citation_unsupported` and `inline_citation_overclaimed` now remain `error`; `inline_citation_unverifiable` remains `warning`; hedged non-inline Claim-RAG issues still downgrade to warning.
- Regression: added repair coverage proving a hedged failed inline PMID is removed when a supported sibling citation remains.
- TDD RED: `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/scripts/test_repair_report.py::test_repair_handles_hedged_failed_inline_pmid_when_sibling_supports` failed because severity was `warning`.
- TDD RED: `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py::test_issue_severity_applies_hedged_warning_only_to_non_inline_claim_rag_issues` failed for hedged inline `unsupported` and `overclaimed`.
- GREEN: `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/scripts/test_repair_report.py::test_repair_handles_hedged_failed_inline_pmid_when_sibling_supports tests/agents/deep_interpreter/test_claim_rag_validation.py::test_issue_severity_applies_hedged_warning_only_to_non_inline_claim_rag_issues` -> 5 passed, 1 warning.
- Verification: `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/scripts/test_repair_report.py tests/agents/deep_interpreter/test_claim_rag_validation.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py` -> 80 passed, 1 warning.
- Ruff: `uv run ruff check scripts/repair_report.py src/agents/deep_interpreter/claim_rag_validation.py src/agents/deep_interpreter/report_guardrails.py tests/scripts/test_repair_report.py tests/agents/deep_interpreter/test_claim_rag_validation.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py` -> All checks passed.
- Pyright: `uv run pyright scripts/repair_report.py src/agents/deep_interpreter/claim_rag_validation.py src/agents/deep_interpreter/report_guardrails.py tests/scripts/test_repair_report.py tests/agents/deep_interpreter/test_claim_rag_validation.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py` -> 0 errors, 0 warnings, 0 informations.
- Notes: did not touch Synthesis Task3, deadlines Task4, `mcp_clients`, or user-owned `.superpowers/sdd/task-3-report.md`.

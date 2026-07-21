# Task 2a Report: Pin Claim Judge Structured Output Method

Status: DONE

## Changed Files

- `src/agents/deep_interpreter/claim_rag_validation.py`
- `tests/agents/deep_interpreter/test_claim_rag_validation.py`
- `.superpowers/sdd/task-2a-report.md`

## TDD Evidence

- RED: `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py -k invoke_judgment_uses_function_calling_structured_output`
  - Result: failed as expected because `_invoke_judgment` called `with_structured_output(ClaimJudgmentBatch)` with `method=None`.
- GREEN: same focused command
  - Result: `1 passed, 30 deselected, 1 warning in 1.87s`.

## Implementation

- `_invoke_judgment` now calls `model.with_structured_output(ClaimJudgmentBatch, method="function_calling")`.
- No changes to global structured-output defaults, model factory, reasoning settings, prompt, timeouts, provider routing, or schema.

## Verification

- `OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py tests/agents/test_model_ollama_openai.py`
  - Result: `59 passed, 4 warnings in 4.69s`.
- `uv run ruff check src/agents/deep_interpreter/claim_rag_validation.py tests/agents/deep_interpreter/test_claim_rag_validation.py`
  - Result: `All checks passed!`.
- `uv run pyright src/agents/deep_interpreter/claim_rag_validation.py tests/agents/deep_interpreter/test_claim_rag_validation.py`
  - Result: `0 errors, 0 warnings, 0 informations`.
- One-claim live smoke after commit:
  - Command used `LLM_PROVIDER=ollama OLLAMA_MODEL=qwen3.5:122b OLLAMA_BASE_URL=http://localhost:6000` and called `_invoke_judgment` with one TGFB claim.
  - Result: passed in `29.107` seconds with parsed status `overclaimed` and evidence quote `TGFB is associated with fibrosis.`

## Self-Review

- Diff is limited to the two allowed source/test files plus this report.
- The only production behavior change is the explicit `method="function_calling"` argument in `_invoke_judgment`.
- Existing live evidence under `tmp_interpreter_runs/qwen122b_bc_claim_rag_30_20260721_104848/` shows native `json_schema` failed with plaintext while `function_calling` parsed a `ClaimJudgmentBatch` in 3.339 seconds.
- Unrelated `.superpowers/sdd/task-3-report.md` was already modified and was not touched.

## Notes

- `uv` printed the ambient `VIRTUAL_ENV` mismatch warning while using the project environment.
- Pytest retained pre-existing warnings from LangGraph `config_schema` deprecation and LangChain `parallel_tool_calls` model kwargs.
- Pyright reported a newer version is available after passing.

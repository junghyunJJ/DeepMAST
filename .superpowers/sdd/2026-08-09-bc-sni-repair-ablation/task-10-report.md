# Task 10 report — terminal agentic zero hits

## Change

- `src/agents/deep_interpreter/tools/literature_rag.py`: in
  `DEEP_INTERPRETER_REQUIRE_AGENTIC_RAG=true`, a valid agentic zero-hit now
  returns `[]` instead of raising `RAGSearchError`.
- `tests/test_rag_path_resolution.py`: updated the required-agentic zero-hit
  regression to require terminal `[]` while proving fallback is not called.

## TDD evidence

- RED:
  `pytest tests/test_rag_path_resolution.py::TestRagSniIntegration::test_search_fulltext_rag_required_agentic_returns_empty_before_fallback`
  failed with `RAGSearchError: Required agentic RAG returned no usable results`.
- GREEN:
  same command passed.

## Verification

- `pytest tests/test_rag_path_resolution.py` -> 56 passed.
- `ruff check src/agents/deep_interpreter/tools/literature_rag.py tests/test_rag_path_resolution.py`
  -> passed.
- `uv run pyright src/agents/deep_interpreter/tools/literature_rag.py tests/test_rag_path_resolution.py`
  -> 0 errors.

## Notes

- No fallback path was enabled or changed.
- Transport, malformed payload, and agentic exceptions still keep their
  existing invalid/error behavior.

## Review fix round 1

- Reviewer finding: the first fix returned `[]` for every required-agentic
  empty result, including transport and malformed-payload failures.
- Fix: `_agentic_search_with_sni` now receives `require_agentic`; it still
  returns `[]` for valid `NoRelevantContext`, but raises after audit for
  `ToolNotFound`, transport exceptions, JSON decode errors, `AgenticError`,
  and invalid `sources`.
- RED:
  `pytest tests/test_rag_path_resolution.py::TestRagSniIntegration::test_search_fulltext_rag_required_agentic_raises_on_invalid_sources tests/test_rag_path_resolution.py::TestRagSniIntegration::test_search_fulltext_rag_required_agentic_raises_on_transport_error`
  failed because neither path raised `RAGSearchError`.
- GREEN:
  same two tests plus the zero-hit test passed.
- Verification:
  `pytest tests/test_rag_path_resolution.py` -> 58 passed;
  `ruff check src/agents/deep_interpreter/tools/literature_rag.py tests/test_rag_path_resolution.py`
  -> passed;
  `uv run pyright src/agents/deep_interpreter/tools/literature_rag.py tests/test_rag_path_resolution.py`
  -> 0 errors.

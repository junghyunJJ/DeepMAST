# Task 11 report — agentic query recurrence audit

## Outcome

Added `query_sha256` to every `_agentic_search_with_sni` audit event. The
fingerprint is SHA-256 of the exact query string and does not store raw query
text.

## Changed

- `src/agents/deep_interpreter/tools/literature_rag.py` — threads `query`
  into `_append_rag_audit` and writes deterministic `query_sha256`.
- `tests/test_rag_path_resolution.py` — verifies the stable digest for a
  positive agentic result and valid `NoRelevantContext` zero-hit records, and
  asserts raw query text is absent.

## TDD evidence

- RED:
  `pytest tests/test_rag_path_resolution.py -k 'can_disable_wiki_context_per_run or audits_no_relevant_context_payload'`
  failed because `query_sha256` was missing.
- GREEN:
  same command passed after implementation.

## Verification

- `pytest tests/test_rag_path_resolution.py` → 58 passed, 1 pre-existing
  LangGraph deprecation warning.
- `ruff check src/agents/deep_interpreter/tools/literature_rag.py tests/test_rag_path_resolution.py`
  → passed.
- `uv run pyright src/agents/deep_interpreter/tools/literature_rag.py tests/test_rag_path_resolution.py`
  → 0 errors, 0 warnings.
- `git diff --check` → passed.

## Notes

- No RAG prompts, payloads, strict error behavior, fallback behavior, runner
  schema, collection, SNI pack, Docker stack, or experiment outputs changed.

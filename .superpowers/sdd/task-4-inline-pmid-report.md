Task 4: DONE

Implemented Claim-RAG judge deadline accounting in `src/agents/deep_interpreter/claim_rag_validation.py` and regressions in `tests/agents/deep_interpreter/test_claim_rag_validation.py`.

Changes:
- Kept `CLAIM_RAG_JUDGE_TIMEOUT_SECONDS` as the 300s monotonic batch deadline.
- Added `CLAIM_RAG_PRIMARY_JUDGE_TIMEOUT_SECONDS` default 180s and retained the 120s single-claim timeout.
- Added provider-aware judge batch sizing: native `ollama` uses 1 claim; other providers use 5.
- Stopped fallback requests once the shared deadline is exhausted and emitted exact `Claim judge batch deadline exhausted.` rows.
- Marked deadline-exhausted rows as incomplete so they are not checkpointed or cached.
- Added `judge_batch_size` and `judge_deadline_exhaustion_count` to selection metadata.

Verification:
- `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py` -> 44 passed, 1 warning.
- `uv run ruff check src/agents/deep_interpreter/claim_rag_validation.py tests/agents/deep_interpreter/test_claim_rag_validation.py` -> All checks passed.
- `uv run pyright src/agents/deep_interpreter/claim_rag_validation.py tests/agents/deep_interpreter/test_claim_rag_validation.py` -> 0 errors, 0 warnings, 0 informations.

Notes:
- Left `src/agents/deep_interpreter/tools/mcp_clients.py`, report guardrails, repair behavior, and `.superpowers/sdd/task-3-report.md` untouched.

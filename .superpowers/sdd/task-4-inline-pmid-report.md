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

Follow-up review fix: DONE

Reviewer finding:
- A fallback request could start before the aggregate batch deadline, time out after consuming that deadline, and leave the current row as `Claim judge failed: TimeoutError.` while only later rows were marked deadline-exhausted.

Changes:
- `src/agents/deep_interpreter/claim_rag_validation.py` now treats fallback `TimeoutError` as deadline exhaustion only when the aggregate deadline is exhausted at catch time, marking the current and remaining unjudged rows with exact reason `Claim judge batch deadline exhausted.`.
- `tests/agents/deep_interpreter/test_claim_rag_validation.py` adds a regression proving one fallback call starts, consumes the deadline, counts all three unjudged rows in `judge_deadline_exhaustion_count`, and makes no second fallback call.

RED:
- `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py::test_fallback_timeout_that_consumes_deadline_exhausts_current_and_remaining` -> failed with `assert 2 == 3`.

GREEN / verification:
- `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py::test_fallback_timeout_that_consumes_deadline_exhausts_current_and_remaining tests/agents/deep_interpreter/test_claim_rag_validation.py::test_judge_group_falls_back_to_single_claim_batches_after_primary_timeout tests/agents/deep_interpreter/test_claim_rag_validation.py::test_judge_group_does_not_persist_failed_judge_results` -> 3 passed, 1 warning.
- `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py` -> 45 passed, 1 warning.
- `uv run ruff check src/agents/deep_interpreter/claim_rag_validation.py tests/agents/deep_interpreter/test_claim_rag_validation.py` -> All checks passed.
- `uv run pyright src/agents/deep_interpreter/claim_rag_validation.py tests/agents/deep_interpreter/test_claim_rag_validation.py` -> 0 errors, 0 warnings, 0 informations.

Scope:
- Did not modify report guardrail, repairs, `mcp_clients`, or `.superpowers/sdd/task-3-report.md`.

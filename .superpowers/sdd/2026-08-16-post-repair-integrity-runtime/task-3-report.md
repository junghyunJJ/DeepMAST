## Task 3 RED/GREEN Report

### Scope

- Modified `src/agents/deep_interpreter/claim_rag_validation.py`.
- Modified `tests/agents/deep_interpreter/test_claim_rag_validation.py`.
- Added persistent Claim-RAG retrieval checkpointing before judgment batch caching.
- Did not change judge batching, claim selection, evidence ranking, issue severity, dependencies, or SGCP code.

### RED

Added tests:

- `test_validate_claims_reuses_persisted_retrieval_across_fresh_calls`
  - Uses a counting fake for `search_literature_fulltext.invoke`.
  - Calls `validate_claims` twice with separate `cache={}` values and the same `data_dir`.
  - Expected persistent retrieval reuse on the second invocation.
- `test_validate_claims_does_not_persist_transport_failure_retrievals`
  - Uses a failing retrieval fake.
  - Calls `validate_claims` twice with separate `cache={}` values.
  - Verifies transport failures are retried and not stored under checkpoint `retrievals`.

RED command:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py -k 'persisted_retrieval or transport_failure_retrievals'
```

RED result:

- Failed as intended on `test_validate_claims_reuses_persisted_retrieval_across_fresh_calls`.
- Observable failure: `assert retrieval_calls == 1` failed with `2 == 1`.
- Transport failure test passed on existing behavior, confirming failed retrievals were already not cached.

### GREEN

Implementation:

- Extended checkpoint default shape to `{"version": 1, "batches": {}, "retrievals": {}}`.
- Added `_retrieval_checkpoint_key(item)` using:
  - claim
  - candidate PMIDs
  - collection ID / resolved collection key
  - wiki context condition
  - evidence policy version
- Reused persisted retrievals in `_judge_group` before calling `_retrieve_evidence_status`.
- Persisted completed retrieval evidence and `unverifiable_reason`.
- Skipped persistence for reasons beginning with `Literature retrieval failed:`.
- Added `selection["retrieval_cache_hits"]`.
- Updated the keyboard-interrupt recovery test to expect retrieval reuse while preserving unfinished judgment retry behavior.

GREEN command:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py -k 'persisted_retrieval or transport_failure_retrievals'
```

GREEN result:

- `2 passed, 54 deselected, 1 warning`.

### Verification

Focused plus guardrail suites:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
```

Result:

- `89 passed, 1 warning`.
- Warning is pre-existing LangGraph deprecation from `src/base/base_agent.py:129`.

Ruff:

```bash
uv run ruff check \
  src/agents/deep_interpreter/claim_rag_validation.py \
  tests/agents/deep_interpreter/test_claim_rag_validation.py
```

Result:

- `All checks passed!`

Py compile:

```bash
uv run python -m py_compile \
  src/agents/deep_interpreter/claim_rag_validation.py \
  tests/agents/deep_interpreter/test_claim_rag_validation.py
```

Result:

- Passed with no output.

Diff whitespace:

```bash
git diff --check
```

Result:

- Passed with no output.

### Self-Review

- Retrieval cache lookup occurs before judgment checkpoint lookup because the existing flow enriches evidence before computing judgment batch keys.
- Transport failures remain uncached and do not create a checkpoint in the failure-only path.
- Existing judgment checkpoint behavior remains separate under `batches`.
- Retrieval checkpoint persistence can reuse retrievals after an interrupted judgment run, while the unfinished judgment batch is still retried.
- No dependency or SGCP code changes.

### Concerns

- `_retrieval_collection_id` uses `DEEP_INTERPRETER_FIXED_COLLECTION_ID` when set; otherwise it uses the same resolved `all` collection key passed into the RAG tool. The actual backend collection UUID is resolved inside the RAG tool and is not exposed to this validator without changing SGCP/RAG code.

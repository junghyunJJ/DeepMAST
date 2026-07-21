# Task 1 Report

Status: DONE

## Changed Files

- `src/agents/deep_interpreter/claim_rag_validation.py` - added the fixed high-risk / inline-PMID / external-evidence selector, preserved parsed inline PMIDs, attached `selection_reason`, counted selected reasons, and renamed skipped out-of-scope claims to `outside_claim_rag_scope`.
- `tests/agents/deep_interpreter/test_claim_rag_validation.py` - replaced the high-risk-only selector test with the bounded union selector test and adjusted low-risk skipped fixtures to avoid inline PMIDs.
- `.superpowers/sdd/task-1-report.md` - this report.

## RED Evidence

Command:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py::test_validate_claims_retrieves_bounded_union_of_claim_categories
```

Result after correcting a fixture typo:

```text
FAILED ... AssertionError
Right contains 2 more items, first extra item: 'CXCL12 marks the migratory region (PMID: 22222222).'
1 failed, 1 warning
```

The old selector only retrieved the high-risk claim.

## GREEN Evidence

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py
```

Result:

```text
24 passed, 1 warning in 2.38s
```

```bash
uv run ruff check src/agents/deep_interpreter/claim_rag_validation.py tests/agents/deep_interpreter/test_claim_rag_validation.py
```

Result:

```text
All checks passed!
```

```bash
uv run pyright src/agents/deep_interpreter/claim_rag_validation.py tests/agents/deep_interpreter/test_claim_rag_validation.py
```

Result:

```text
0 errors, 0 warnings, 0 informations
```

## Notes

- Preserved `OLLAMA_REASONING` behavior; `_create_judge_llm` was not changed.
- Did not edit report guardrail code or `.superpowers/sdd/task-3-report.md`.

## Task 1 Reviewer Fixes

### Changed Paths

- `src/agents/deep_interpreter/claim_rag_validation.py`
- `tests/agents/deep_interpreter/test_claim_rag_validation.py`
- `.superpowers/sdd/task-1-report.md`

### RED Evidence

Command run against a temporary `ee9481e` checkout with only the new tests applied:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py::test_validate_claims_caps_matching_claims_and_audits_overflow tests/agents/deep_interpreter/test_claim_rag_validation.py::test_judge_group_does_not_reuse_checkpoint_without_selection_reason
```

Result:

```text
2 failed, 1 warning in 17.68s
```

Failures:

```text
test_validate_claims_caps_matching_claims_and_audits_overflow: selected 32 matching claims instead of 30.
test_judge_group_does_not_reuse_checkpoint_without_selection_reason: reused a checkpoint key that lacked selection_reason.
```

### GREEN Evidence

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py
```

Result:

```text
30 passed, 1 warning in 2.52s
```

```bash
uv run ruff check src/agents/deep_interpreter/claim_rag_validation.py tests/agents/deep_interpreter/test_claim_rag_validation.py
```

Result:

```text
All checks passed!
```

```bash
uv run pyright src/agents/deep_interpreter/claim_rag_validation.py tests/agents/deep_interpreter/test_claim_rag_validation.py
```

Result:

```text
0 errors, 0 warnings, 0 informations
```

### Notes

- Added the fixed `MAX_SELECTED_CLAIMS = 30` cap in deterministic extraction order.
- Matching claims after the cap are audited with `selection_limit_reached`; selected reason counters remain selected-only.
- `_checkpoint_key` now includes `selection_reason`.
- Added only direct assertions for generic association, crosstalk, interaction, and hedge exclusions.

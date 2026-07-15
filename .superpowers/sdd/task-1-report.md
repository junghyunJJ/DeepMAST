# Task 1 Report: Extract Claims and Assign the Allowed PMID Pool

Status: DONE

## Changes Made

- Created `src/agents/deep_interpreter/claim_rag_validation.py`.
- Created `tests/agents/deep_interpreter/test_claim_rag_validation.py`.

## TDD Evidence

- RED: `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py`
  - Result: failed during collection because `src.agents.deep_interpreter.claim_rag_validation` did not exist.
- GREEN: `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py`
  - Result: `4 passed, 1 warning in 3.01s`.

## Implementation Notes

- Part report claims are extracted only from `### Biological Interpretation` blocks.
- Synthesis claims are extracted from section bodies.
- Inline PMIDs are preferred when present and filtered to `papers.json`.
- Part report fallback PMIDs come from the section `### References` block.
- Synthesis fallback PMIDs come from the full `papers.json` universe.
- Explicit hypothesis marker sentences are excluded as asserted claims while adjacent asserted claims are marked hedged.

## Self-Review

- Scope is limited to extraction and PMID-pool assignment.
- No retrieval, judgment execution, or guardrail integration was added.
- The ignored implementation plan was not edited.

## Concerns

- The focused test command emits a pre-existing LangGraph deprecation warning from `src/base/base_agent.py:129`.

## Review Fix

- Fixed synthesis fallback PMID assignment so non-inline synthesis claims always receive the full `papers.json` PMID pool, regardless of local `### References`.
- Added regression coverage for a synthesis section whose local References block contains only one PMID while the non-inline claim still receives all PMIDs from `papers.json`.
- Part report fallback behavior remains unchanged.

## Review Fix Evidence

- RED: `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py`
  - Result: `1 failed, 4 passed, 1 warning`; `test_synthesis_references_do_not_narrow_non_inline_pmid_pool` got `['11111111']` instead of the full pool.
- GREEN: `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py`
  - Result: `5 passed, 1 warning in 2.21s`.
- Ruff: `uv run ruff check src/agents/deep_interpreter/claim_rag_validation.py tests/agents/deep_interpreter/test_claim_rag_validation.py`
  - Result: `All checks passed!`.

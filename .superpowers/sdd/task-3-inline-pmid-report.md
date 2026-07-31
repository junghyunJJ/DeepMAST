# Task 3 Inline PMID Grounding Report

Status: DONE

## Changes

- Replaced the old synthesis no-Claim-RAG regression with coverage/artifact integration coverage.
- Added a synthesis sibling-citation fixture proving supported PMID retention and unsupported sibling removal.
- Integrated `validate_claims(data_dir, ("synthesis.md",), provider=provider, cache=claim_cache)` into synthesis guardrail validation.
- Reused one Claim-RAG cache across synthesis repair passes.
- Persisted `claim_validation`, `claim_selection`, and `inline_citation_coverage` in initial/final guardrail artifacts.
- Passed current Claim-RAG rows into citation-local synthesis repair before hedge and consistency repair.

## Verification

- RED: `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py -k synthesis` failed because synthesis did not call Claim-RAG and did not remove the unsupported sibling PMID.
- GREEN: `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py -k synthesis` passed: 12 passed, 15 deselected.
- Focused suite: `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py` passed: 27 passed.
- Ruff: `uv run ruff check src/agents/deep_interpreter/report_guardrails.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py` passed.
- Pyright: `uv run pyright src/agents/deep_interpreter/report_guardrails.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py` passed with 0 errors.

## Notes

- Did not modify `.superpowers/sdd/task-3-report.md`.
- Did not change Task 4 deadline behavior, `mcp_clients`, or `generate_html_report` ordering.

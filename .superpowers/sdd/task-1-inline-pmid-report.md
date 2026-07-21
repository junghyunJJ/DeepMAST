# Task 1 Inline PMID Report

## Scope

- Modified `src/agents/deep_interpreter/claim_rag_validation.py`.
- Modified `tests/agents/deep_interpreter/test_claim_rag_validation.py`.
- Added this report.
- Did not edit `.superpowers/sdd/task-3-report.md`; it was already modified in the worktree.

## RED Evidence

Command:

```bash
OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py -k 'inline_pmid or selection or coverage'
```

Result: failed as expected before production changes.

- `test_claim_items_expand_each_inline_pmid_into_exact_candidate` failed with `KeyError: 'source_claim_index'`.
- `test_inline_pairs_bypass_the_non_inline_selection_cap` failed with `KeyError: 'non_inline_selected_count'`.
- `test_unknown_inline_pmid_is_expected_in_incomplete_coverage` failed with `KeyError: 'inline_citation_coverage'`.

## GREEN Evidence

Command:

```bash
OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py -k 'inline_pmid or selection or coverage'
```

Result: `12 passed, 24 deselected, 1 warning`.

Command:

```bash
OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_claim_rag_validation.py
```

Result: `36 passed, 1 warning`.

Command:

```bash
uv run ruff check src/agents/deep_interpreter/claim_rag_validation.py tests/agents/deep_interpreter/test_claim_rag_validation.py
```

Result: `All checks passed!`

Command:

```bash
uv run pyright src/agents/deep_interpreter/claim_rag_validation.py tests/agents/deep_interpreter/test_claim_rag_validation.py
```

Result: `0 errors, 0 warnings, 0 informations`.

## Changes

- `_claim_items()` now emits one item per inline PMID with stable `source_claim_index`, exact `inline_pmid`, unique item `index`, and exact `candidate_pmids`.
- Non-inline claims are capped by `MAX_NON_INLINE_SELECTED_CLAIMS`; inline citation pairs bypass that cap.
- `_judgment_prompt()` includes `inline_pmid` and instructs the judge that supported inline citations require that exact PMID.
- Supported inline judgments that omit the exact PMID are converted to `unverifiable`.
- `validate_claims()` now returns `inline_citation_coverage` with expected/evaluated/supported counts, completion status, and citation rows.

## Concerns

- Verification commands emit a pre-existing `VIRTUAL_ENV` mismatch warning because `uv` ignores the outer `.venv`.
- Pyright reports a newer version is available; current scoped run has zero errors.
- Pytest emits a pre-existing LangGraph deprecation warning from `src/base/base_agent.py:129`.

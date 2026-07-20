# Task 1 Report: Define and Test Canonical Consistency Facts

Status: DONE

## Changes Made

- Created `src/agents/deep_interpreter/synthesis_consistency_validation.py`.
- Created `tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`.

## TDD Evidence

- RED: `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
  - Result: collection failed with `ModuleNotFoundError` for `src.agents.deep_interpreter.synthesis_consistency_validation`.
- GREEN: `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
  - Result: `6 passed, 1 warning in 2.47s`.

## Implementation Notes

- `validate_synthesis_consistency(data_dir)` returns `issues` and `results`.
- Candidate scores are extracted only from explicit Part 4 candidate headings and `combined N` lines.
- Selected genes and L-R pairs are extracted only from `part4_candidate_selection.json`.
- L-R keys normalize `^` and `-` for comparison while source values remain literal replacements.
- Quantitative facts are extracted only from `### Quantitative Findings` sections with explicit `label = number.` anchors.
- Repairs replace only literal observed substrings from repairable issues.

## Verification

- Focused tests: `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
  - Result: `6 passed, 1 warning in 2.70s`.
- Ruff: `OPENAI_API_KEY=test uv run ruff check src/agents/deep_interpreter/synthesis_consistency_validation.py tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
  - Result: `All checks passed!`.
- Compile: `OPENAI_API_KEY=test uv run python -m py_compile src/agents/deep_interpreter/synthesis_consistency_validation.py tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
  - Result: passed.

## Self-Review

- Scope stayed limited to the requested validator and focused tests.
- No changes were made to `report_guardrails.py` or integration tests.
- No dependencies or abstractions were added.

## Concerns

- The focused pytest command emits a pre-existing LangGraph deprecation warning from `src/base/base_agent.py:129`.
- `uv` warns that the parent `VIRTUAL_ENV` differs from this worktree's `.venv`; commands still completed through `uv`.

## Fix Wave

### Finding 1: Repair order must not depend on issue order

- Changed files:
  - `src/agents/deep_interpreter/synthesis_consistency_validation.py`
  - `tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
- Fix: mismatch issues now carry `start_offset` and `end_offset`; repairs are collected and applied from end to start, so reversed issue lists still repair all literal source-derived values.
- RED command/output:
  - `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
  - Output: `test_repair_handles_issues_out_of_document_order` failed with `assert 1 == 3`.
- GREEN command/output:
  - `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
  - Output: `10 passed, 1 warning in 2.49s`.

### Finding 2: Missing optional canonical text artifacts must warn and skip dependent checks

- Changed files:
  - `src/agents/deep_interpreter/synthesis_consistency_validation.py`
  - `tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
- Fix: missing `part4_therapeutic_synthesis.md` now emits `synthesis_consistency_source_missing` only when valid Part 4 JSON and a synthesis candidate anchor make candidate-score checks relevant; missing Part 1-3 files warn when quantitative synthesis anchors require upstream text facts.
- RED command/output:
  - `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
  - Output: `test_missing_dependent_text_sources_warn_and_skip_checks` failed because an unresolved error was emitted instead of source-missing warnings.
- GREEN command/output:
  - `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
  - Output: `10 passed, 1 warning in 2.49s`.

### Finding 3: Wrong-shape Part 4 JSON must warn rather than crash

- Changed files:
  - `src/agents/deep_interpreter/synthesis_consistency_validation.py`
  - `tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
- Fix: `part4_candidate_selection.json` must parse to an object; other valid JSON shapes emit `synthesis_consistency_source_malformed` and skip JSON-dependent checks.
- RED command/output:
  - `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
  - Output: `test_wrong_shape_part4_json_warns_without_crashing` failed with `AttributeError: 'list' object has no attribute 'get'`.
- GREEN command/output:
  - `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
  - Output: `10 passed, 1 warning in 2.49s`.

### Finding 4: Part 1-3 explicit numeric headings must be extractable

- Changed files:
  - `src/agents/deep_interpreter/synthesis_consistency_validation.py`
  - `tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
- Fix: Part 1-3 extraction now accepts bounded `### identifier = number` headings while ignoring biological-interpretation free text; synthesis L-R `combinedscore` lines are excluded from generic quantitative matching.
- RED command/output:
  - `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
  - Output: `test_part_numeric_heading_facts_are_extracted_without_free_text` failed with `ValueError: not enough values to unpack`.
- GREEN command/output:
  - `OPENAI_API_KEY=test uv run pytest -q tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
  - Output: `10 passed, 1 warning in 2.49s`.

### Fix Wave Verification

- Ruff command/output:
  - `OPENAI_API_KEY=test uv run ruff check src/agents/deep_interpreter/synthesis_consistency_validation.py tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
  - Output: `All checks passed!`.
- Compile command/output:
  - `OPENAI_API_KEY=test uv run python -m py_compile src/agents/deep_interpreter/synthesis_consistency_validation.py tests/agents/deep_interpreter/test_synthesis_consistency_validation.py`
  - Output: passed.

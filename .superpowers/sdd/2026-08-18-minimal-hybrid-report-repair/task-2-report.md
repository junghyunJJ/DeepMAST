# Task 2 Report: Part Validators Emit Generic Targets

## Changes

- Extended `scripts/validate_report.py` `_issue()` with optional `target_text` and `replacement_text`, omitted when empty.
- LR metric mismatches now emit exact `target_text` and deterministic `replacement_text` by replacing only the matched numeric token with `expected:.4f`.
- Semantic/directional hard errors now emit exact `target_text` only:
  - `unsupported_mechanistic_interpretation`
  - `unsupported_pathway_factor_significance`
  - `factor_pathway_direction_mismatch`
  - `part3_therapeutic_spillover`
- Hedged mechanistic warnings remain non-repairing warnings.

## RED Evidence

Command:

```bash
OPENAI_API_KEY=test uv run pytest -q tests/scripts/test_validate_report.py tests/scripts/test_validate_repair_report.py
```

Result before implementation:

```text
7 failed, 42 passed in 0.22s
```

Expected failures were missing `target_text` / `replacement_text` fields and the real validate-repair-validate flow applying zero repairs.

## GREEN Evidence

Command:

```bash
OPENAI_API_KEY=test uv run pytest -q tests/scripts/test_validate_report.py tests/scripts/test_validate_repair_report.py
```

Result after implementation:

```text
49 passed in 0.09s
```

## Required Verification

Command:

```bash
OPENAI_API_KEY=test uv run pytest -q tests/scripts/test_validate_report.py tests/scripts/test_validate_repair_report.py tests/scripts/test_repair_report.py
```

Result:

```text
87 passed, 1 warning in 3.15s
```

Warning: pre-existing LangGraph deprecation from `src/base/base_agent.py:129`.

Command:

```bash
uv run ruff check scripts/validate_report.py tests/scripts/test_validate_report.py tests/scripts/test_validate_repair_report.py
```

Result:

```text
All checks passed!
```

Command:

```bash
uv run python -m py_compile scripts/validate_report.py
```

Result: exit 0.

Command:

```bash
git diff --check
```

Result: exit 0.

## Self-Review

- Scope stayed inside requested files plus this required report.
- `repair_report.py` was not modified.
- Issue code, value, evidence, severity, and repair instructions were preserved.
- No invented deterministic replacement was added for pathway direction, mechanistic interpretation, unsupported significance, or Part3 therapeutic spillover.

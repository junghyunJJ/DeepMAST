# Synthesis No-RAG Guardrail Report

Status: DONE

## Scope

Implemented the confirmed policy in the owned files only:

- `src/agents/deep_interpreter/report_guardrails.py`
- `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`

This pass did not edit `src/agents/deep_interpreter/claim_rag_validation.py`.

## Policy Implemented

Claim-level RAG validation now applies to Part 1-3 through `run_report_guardrail`.

The synthesis path now validates `synthesis.md` with:

- deterministic synthesis validation
- Part 1-4 consistency validation
- existing deterministic/consistency repair loop
- existing `MAX_GUARDRAIL_REPAIR_PASSES = 3`
- existing guardrail artifact writes

The synthesis path no longer calls:

```python
claim_rag_validation.validate_claims(data_dir, ("synthesis.md",), ...)
```

## Backward-Compatible Result Shape

Synthesis artifacts still include `claim_validation`, but it is always an empty list.

Returned synthesis fields remain present and stable:

- `claims_validated`
- `claims_by_status`
- `validation_results`
- `consistency_checked`
- `consistency_issue_count`
- `consistency_validation`

For synthesis, `claims_validated` is `0`, `validation_results` is `[]`, and each `claims_by_status` count is `0`.

## Tests Updated

Updated focused synthesis coverage so networked Claim RAG would fail the test if invoked:

- `test_run_synthesis_guardrail_never_calls_claim_rag_and_keeps_empty_claim_artifacts`
- `test_run_synthesis_guardrail_repairs_consistency_mismatch`

The first test proves synthesis skips Claim RAG while deterministic overclaim repair still runs and writes empty claim artifacts.

The second test proves Part 1-4 consistency mismatch repair still runs while Claim RAG is forbidden.

Existing Part 1-3 behavior remains covered by `test_run_report_guardrail_merges_claim_errors_and_revalidates_after_repair`, which still verifies Claim RAG calls and repair revalidation for part reports.

## Verification

Red check before production edit:

```bash
pytest tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  -k "synthesis_guardrail_never_calls_claim_rag or synthesis_guardrail_repairs_consistency_mismatch"
```

Result before source edit: 2 failed because synthesis called `claim_rag_validation.validate_claims`.

Focused guardrail tests after source edit:

```bash
pytest tests/agents/deep_interpreter/test_report_guardrail_middleware.py
```

Result:

```text
24 passed, 1 warning in 2.08s
```

Ruff:

```bash
ruff check src/agents/deep_interpreter/report_guardrails.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
```

Result:

```text
All checks passed!
```

Pyright:

```bash
pyright src/agents/deep_interpreter/report_guardrails.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
```

Result:

```text
0 errors, 0 warnings, 0 informations
```

Non-failing notes:

- Pytest emits the existing LangGraph `config_schema` deprecation warning from `src/base/base_agent.py`.
- Pyright reports an available tool update from `v1.1.409` to `v1.1.411`.

## Concerns

No source-level concerns remain for the requested policy.

The public `run_synthesis_guardrail(..., provider=...)` argument is intentionally still accepted for API compatibility, but synthesis no longer uses it because it no longer performs LLM-backed Claim RAG validation.

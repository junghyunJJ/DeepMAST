# Task 3 prose inline convergence fix report

## Status

Complete in commit `e41da27f639fd952646f15c8fd996e7bc9cbaa66`:

`Make sole inline PMID repair deterministic`

The production change is limited to `scripts/repair_report.py`: grouped hard inline-citation issues now try the existing reference-only deterministic delete first, then continue through the existing grouped exact PMID-removal path when reference-only deletion does not apply. This prevents sole prose inline PMID failures from falling through to stochastic LLM target repair.

## Files changed

- `scripts/repair_report.py` - changed the no-supported-sibling grouped inline branch from an unconditional reference-only return to a conditional early return only when reference-only deletion succeeds.
- `tests/scripts/test_repair_report.py` - added sole prose inline PMID regression coverage, updated grouped inline expectations to deterministic PMID removal, and moved unsafe LLM replacement validation onto a generic Claim-RAG target issue so it still tests the model-repair safety path.
- `tests/agents/deep_interpreter/test_report_guardrail_middleware.py` - updated the synthesis sole-inline test to assert deterministic failed PMID removal, warning-only uncited revalidation, no hard final errors, and no model call.

## RED

Command:

```bash
pytest tests/scripts/test_repair_report.py::test_repair_removes_sole_failed_prose_inline_pmid_without_llm tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_run_synthesis_guardrail_removes_sole_failed_inline_pmid_without_model
```

Result:

- Exit code: `1`
- `tests/scripts/test_repair_report.py::test_repair_removes_sole_failed_prose_inline_pmid_without_llm` failed because the issue fell through to model repair. The provided `FailLLM` did not implement `with_structured_output`, proving the model path was reached.
- `tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_run_synthesis_guardrail_removes_sole_failed_inline_pmid_without_model` failed with `AssertionError: model should not be called`, proving synthesis also reached `_create_model`.

This was the expected RED: sole unsupported/overclaimed prose inline PMIDs did not use deterministic grouped removal before the fix.

## GREEN

Focused command:

```bash
pytest tests/scripts/test_repair_report.py::test_repair_removes_sole_failed_prose_inline_pmid_without_llm tests/scripts/test_repair_report.py::test_repair_removes_multiple_unsupported_inline_pmids_when_sibling_supports tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_run_synthesis_guardrail_removes_sole_failed_inline_pmid_without_model
```

Result:

- Exit code: `0`
- `3 passed`

Full required verification:

```bash
pytest tests/scripts/test_repair_report.py
```

- Exit code: `0`
- `48 passed`

```bash
pytest tests/agents/deep_interpreter/test_report_guardrail_middleware.py
```

- Exit code: `0`
- `54 passed`

```bash
ruff check scripts/repair_report.py tests/scripts/test_repair_report.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py
```

- Exit code: `0`
- `All checks passed!`

```bash
python -m py_compile scripts/repair_report.py tests/scripts/test_repair_report.py tests/agents/deep_interpreter/test_report_guardrail_middleware.py
```

- Exit code: `0`

```bash
git diff --check
```

- Exit code: `0`

Final pre-report commit status check after commit:

```bash
git status --short
```

- Exit code: `0`
- Clean output

## Production rationale

The brief required keeping `_repair_inline_citation_issue` unchanged and reusing the grouped PMID-removal path. The smallest safe production change was:

```python
if not sibling_supported and _delete_reference_only_inline_target(data_dir, first):
    return True
```

This preserves the existing reference-only whole-line delete as the first no-sibling attempt. If that delete does not apply to a prose target, execution continues into the existing grouped loop that removes only the grouped failed `inline_pmid` values, requires a unique exact section occurrence, and preserves unfailed/supported sibling PMIDs. Ambiguous or missing targets still fail closed through the existing guards.

No controller, retry, cache, prompt, dependency, or prose-cleanup logic was changed.

## Modified test rationale

### `test_repair_removes_sole_failed_prose_inline_pmid_without_llm`

Added to prove the bug directly: a sole prose inline `inline_citation_overclaimed` issue with `FailLLM()` now returns `changed == 1`, keeps the claim text visible, removes the failed PMID, and does not leave empty parentheses. Without the production fix, this test reached model fallback.

### `test_repair_removes_multiple_unsupported_inline_pmids_when_sibling_supports`

Kept as the existing safety proof for mixed citations: grouped failed PMIDs are removed while the supported PMID remains, without LLM.

### `test_repair_removes_grouped_failed_inline_pmids_without_llm`

Updated from the stale LLM rewrite expectation. Under the approved policy, grouped hard inline failures should remove failed inline PMIDs deterministically instead of asking the model to rewrite the claim. The test still verifies exact-section preservation, unrelated text preservation, heading preservation, and no empty parentheses in the repaired claim span.

### `test_repair_rejects_unsafe_exact_claim_replacements`

Changed from `inline_citation_unsupported` to `claim_rag_unsupported` with `target_text` so the test continues to exercise the generic LLM target-repair safety checks. Leaving it as an inline issue would conflict with the new deterministic inline policy and would no longer test unsafe model replacement rejection.

### `test_run_synthesis_guardrail_removes_sole_failed_inline_pmid_without_model`

Updated from hedging via model rewrite to deterministic failed PMID removal. The fake validator now emits a hard `inline_citation_overclaimed` while the PMID is present, then warning-only `claim_rag_overclaimed` after the deterministic PMID removal. `_create_model` raises if called, proving synthesis uses the shared deterministic repair path and finishes with `final_error_count == 0`.

## Self-review

- Production diff is one conditional branch in the grouped helper.
- `_repair_inline_citation_issue` remains unchanged.
- Existing grouped removal machinery is reused; no new parser, dependency, prompt, controller, retry, cache, or prose rewrite was added.
- Reference-only deterministic deletion remains first for no-supported-sibling targets.
- Sole prose inline targets retain claim text and remove only the failed inline PMID.
- Existing unique exact-section and empty-parenthesis protections remain on the reused path.
- The known punctuation artifact, such as a space before a period after citation removal, was not normalized because prose cleanup was explicitly out of scope.

## Warnings and gaps

- Pytest emitted the existing `pytest_asyncio` deprecation warning about unset `asyncio_default_fixture_loop_scope`.
- Pytest emitted the existing LangGraph deprecation warning: `config_schema` is deprecated in favor of `context_schema`.
- Live RAG/frontier guardrail replay was not run.

## Fix Round 1

Reviewer finding addressed:

- The post-removal `claim_rag_overclaimed` warning fixture in `tests/agents/deep_interpreter/test_report_guardrail_middleware.py` included `target_text`, which conflicted with production policy that uncited semantic warnings have no repair target.

Changed file:

- `tests/agents/deep_interpreter/test_report_guardrail_middleware.py` - removed `target_text` from the warning fixture and added an assertion that final `claim_rag_overclaimed` warnings do not include `target_text`.

Production code was not changed.

Commands and results:

```bash
pytest tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_run_synthesis_guardrail_removes_sole_failed_inline_pmid_without_model
```

- Exit code: `0`
- `1 passed`

```bash
pytest tests/agents/deep_interpreter/test_report_guardrail_middleware.py
```

- Exit code: `0`
- `54 passed`

```bash
ruff check tests/agents/deep_interpreter/test_report_guardrail_middleware.py
```

- Exit code: `0`
- `All checks passed!`

```bash
python -m py_compile tests/agents/deep_interpreter/test_report_guardrail_middleware.py
```

- Exit code: `0`

```bash
git diff --check
```

- Exit code: `0`

Warnings:

- Pytest emitted the existing `pytest_asyncio` deprecation warning about unset `asyncio_default_fixture_loop_scope`.
- Pytest emitted the existing LangGraph deprecation warning: `config_schema` is deprecated in favor of `context_schema`.

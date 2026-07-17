# Missing hypothesis artifact fix: TDD evidence

## Scope

Repair the terminal-state gap in `HypothesisReportGuardrailMiddleware` when a
hypothesis role returns without a valid canonical handoff. The repair must
write the pre-existing rejection-sidecar layout before preserving the current
`RuntimeError` and report-writer block.

The root-cause report establishes that production's deterministic coordinator
invokes this middleware before its own direct validation branch. The
coordinator branch therefore cannot bypass the shared middleware in current
production and was intentionally left unchanged.

## RED

Added
`test_hypothesis_guardrail_missing_handoff_persists_terminal_rejection` in
`tests/agents/drug_target/test_report_guardrail_middleware.py`. It creates an
empty `evidence/` directory, invokes the real `after_agent` middleware path,
asserts the existing `HYPOTHESIS_REPORT_MISSING` exception, then reads the
durable sidecar and checks:

- `saved is False`
- `stage == "hypothesis_report_guardrail"`
- an error record with code `HYPOTHESIS_REPORT_MISSING`

Before production changes, ran:

```text
pytest -q tests/agents/drug_target/test_report_guardrail_middleware.py -k missing_handoff_persists_terminal_rejection
```

Result: **1 failed, 76 deselected**. The middleware raised as expected, then
the test failed with `FileNotFoundError` because
`evidence/hypothesis_report_last_rejection.json` did not exist.

## GREEN

In the invalid branch of `HypothesisReportGuardrailMiddleware._run()`, call the
existing `_write_hypothesis_rejection()` serializer with the already-computed
`quality` result and `stage="hypothesis_report_guardrail"`, immediately before
the unchanged error construction and raise. No schema validation, coordinator,
runner, report guardrail, model, schema, or config behavior changed.

The stage distinguishes a missing-handoff guardrail rejection from an attempted
`save_hypothesis_report` rejection while retaining the exact existing JSON
serialization/layout.

After the production change, ran the new test:

```text
1 passed, 76 deselected
```

## Verification

```text
pytest -q tests/agents/drug_target/test_report_guardrail_middleware.py \
  tests/agents/drug_target/test_hypothesis_schema.py \
  tests/agents/drug_target/test_guarded_pipeline.py
121 passed in 1.85s

ruff check src/agents/drug_target/middleware.py \
  tests/agents/drug_target/test_report_guardrail_middleware.py
All checks passed!

git diff --check
exit 0
```

No model-backed live tests were run.

## Self-review

- The existing `RuntimeError` text and report-writer blocking behavior remain
  unchanged; only persistence precedes the raise.
- The existing serializer is reused directly, avoiding a second JSON shape or
  a new abstraction.
- The existing untracked benchmark `__pycache__/` directory was not modified
  or staged.

## Empty-run directory follow-up

### RED

The original regression pre-created `evidence/`, so it could not establish the
empty-run contract. Replaced the redundant error-only test with
`test_hypothesis_guardrail_missing_handoff_from_empty_run_persists_terminal_rejection`.
It asserts that `tmp_path / "evidence"` is absent before invoking the real
middleware path, then keeps the same exception and sidecar assertions.

Before the serializer change, ran:

```text
pytest -q tests/agents/drug_target/test_report_guardrail_middleware.py -k empty_run_persists_terminal_rejection
```

Result: **1 failed, 75 deselected**. The middleware raised the expected
`HYPOTHESIS_REPORT_MISSING`, then the test failed with `FileNotFoundError`
because the serializer did not create `evidence/`.

### GREEN

Added `evidence_dir.mkdir(parents=True, exist_ok=True)` inside the existing
`try` block in `_write_hypothesis_rejection()`, immediately before the existing
sidecar write. Directory-creation failures are still `OSError` values handled
by the same pre-existing silent return, so the serializer's failure behavior
is unchanged.

```text
pytest -q tests/agents/drug_target/test_report_guardrail_middleware.py -k empty_run_persists_terminal_rejection
1 passed, 75 deselected

pytest -q tests/agents/drug_target/test_report_guardrail_middleware.py \
  tests/agents/drug_target/test_hypothesis_schema.py \
  tests/agents/drug_target/test_guarded_pipeline.py
120 passed in 1.77s

ruff check src/agents/drug_target/middleware.py \
  src/agents/drug_target/tools/hypothesis_schema.py \
  tests/agents/drug_target/test_report_guardrail_middleware.py
All checks passed!

git diff --check
exit 0
```

No model-backed live tests were run. The existing-directory setup was removed
because the empty-run regression strictly covers the required durable sidecar
behavior without duplicate test setup.

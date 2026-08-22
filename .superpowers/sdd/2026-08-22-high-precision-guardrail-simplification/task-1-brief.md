### Task 1: Separate semantic warnings from hard evidence failures

**Files:**
- Modify: `src/agents/deep_interpreter/claim_rag_validation.py:741-789`
- Modify: `scripts/validate_report.py:313-340`
- Modify: `src/agents/deep_interpreter/report_guardrails.py:320-590`
- Test: `tests/agents/deep_interpreter/test_claim_rag_validation.py`
- Test: `tests/scripts/test_validate_report.py`
- Test: `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`
- Add to commit: this plan and its spec.

**Interfaces:**
- Preserve `_issue_for(result) -> dict | None`.
- Preserve `validate_synthesis_report()` and guardrail result schemas.
- Produce warning issues without `target_text` for non-inline semantic judgments.

- [ ] **Step 1: Write RED Claim-RAG severity tests**

Add/replace tests so these assertions are explicit:

```python
def test_non_inline_overclaim_is_warning_without_repair_target() -> None:
    issue = claim_rag_validation._issue_for(
        {
            "status": "overclaimed",
            "hedged": False,
            "supporting_pmids": ["11111111"],
            "evidence_quote": "TGFB is associated with fibrosis.",
            "reason": "Association only.",
            "file": "part1_final.md",
            "section": "## Biology",
            "source_claim_index": 0,
            "inline_pmid": None,
            "claim": "TGFB drives fibrosis.",
        }
    )
    assert issue is not None
    assert issue["code"] == "claim_rag_overclaimed"
    assert issue["severity"] == "warning"
    assert "target_text" not in issue


def test_inline_overclaim_remains_hard_and_targeted() -> None:
    issue = claim_rag_validation._issue_for(
        {
            "status": "overclaimed",
            "hedged": True,
            "supporting_pmids": ["11111111"],
            "evidence_quote": "Association only.",
            "reason": "Citation does not support causality.",
            "file": "part1_final.md",
            "section": "## Biology",
            "source_claim_index": 0,
            "inline_pmid": "11111111",
            "claim": "TGFB drives fibrosis (PMID: 11111111).",
        }
    )
    assert issue is not None
    assert issue["code"] == "inline_citation_overclaimed"
    assert issue["severity"] == "error"
    assert issue["target_text"] == issue["value"]
```

- [ ] **Step 2: Write RED general interpretation warning tests**

Add a Parts test proving an unhedged report-derived mechanism emits
`mechanistic_interpretation_warning`, severity warning, and no target. Add a
synthesis test proving an unhedged spatial therapeutic/mechanistic claim emits
`synthesis_overclaim_warning`, severity warning, and no target.

- [ ] **Step 3: Verify RED**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/scripts/test_validate_report.py -k 'mechanistic' \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py -k 'overclaim'
```

- [ ] **Step 4: Implement the hard/soft boundary**

In `_issue_for`, use:

```python
    hard_inline = bool(inline_pmid) and status in {"unsupported", "overclaimed"}
    severity = "error" if hard_inline else "warning"
```

Keep inline issue codes for inline citations and existing `claim_rag_*` codes
for non-inline audit. Add `target_text` only for `hard_inline`.

Make `_check_mechanistic_interpretations` always emit
`mechanistic_interpretation_warning`, severity warning, with no target.

Make synthesis mechanistic/therapeutic overclaims always emit
`synthesis_overclaim_warning`, severity warning, with no target. Structural H1
and HTML errors remain unchanged.

- [ ] **Step 5: Delete dead semantic repair paths**

Delete the trusted semantic-heading repair handler and its tests. Remove
`unsupported_synthesis_overclaim`, non-inline `claim_rag_unsupported`, and
non-inline `claim_rag_overclaimed` from automatic synthesis repair routing.
Delete automatic generic hypothesis-caveat appending for targetless semantic
issues.

Simplify `_strict_phase_progress` so same-phase progress again requires strict
hard-error decrease; retain deterministic→semantic acceptance and reject every
other phase change. Remove equal-count semantic frontier tests.

- [ ] **Step 6: Run regressions and commit**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/scripts/test_validate_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/scripts/test_repair_report.py \
  tests/deep_interpreter/test_comprehensive_template_report.py
uv run ruff check src/agents/deep_interpreter/claim_rag_validation.py \
  src/agents/deep_interpreter/report_guardrails.py scripts/validate_report.py
uv run python -m py_compile src/agents/deep_interpreter/claim_rag_validation.py \
  src/agents/deep_interpreter/report_guardrails.py scripts/validate_report.py
git diff --check
```

Commit with Lore trailers explaining that uncited semantic judgments moved to
audit while explicit citations remain hard.

---


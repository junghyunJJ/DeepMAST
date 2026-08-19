# Safe Complete Atomic Report Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the existing Deep Interpreter Report Guardrail safely resolve every targetable hard error through deterministic replacement or one structured exact-target `replace|delete` decision, while publishing only reports that revalidate to zero hard errors.

**Architecture:** Keep the current validator → exact-target patcher → bounded revalidation loop. Change the semantic decision inside `scripts/repair_report.py`: deterministic `replacement_text` remains unchanged, while semantic repairs use one Pydantic structured result whose action is `replace` or `delete`; exact target bounds, no-new-PMID checks, heading identity, and the existing full validator remain the safety boundary. Make one independent vocabulary correction in `scripts/validate_report.py` so `negatively` and `positively` are classified consistently with `negative` and `positive`. No new agent, graph, middleware, strategy registry, or dependency is introduced.

**Tech Stack:** Python 3.12, Pydantic already installed in the repository, LangChain `BaseChatModel.with_structured_output`, pytest, Ruff, stdlib JSON/regex/path handling, existing Ollama and Claim-RAG integrations.

**Spec:** `docs/superpowers/specs/2026-08-19-safe-complete-atomic-report-repair-design.md`

## Global Constraints

- Keep the existing Report Guardrail controller, validators, middleware, and three-pass bound.
- Keep existing trusted deterministic PMID, citation, metric, and synthesis repairs unchanged.
- Keep exact target matching first and whitespace/soft-wrap matching second.
- Reject missing, stale, ambiguous, or occurrence-count-mismatched targets without modifying reports.
- Never rewrite a whole section or report.
- A semantic repair may change only resolved `target_text` spans.
- `replace` requires non-empty replacement text; `delete` requires empty replacement text.
- Neither semantic action may add a Markdown heading or a PMID absent from the target.
- Deterministic replacements retain the current 50% check; semantic retention ratio remains audit metadata and is not a blanket rejection rule.
- Final validation, not the LLM decision, determines success.
- Hard errors after bounded repair remain fail-closed and block publication.
- Do not install LangChain Skills, Harbor, a new package, or a trained editor.
- Do not modify SGCP-RAG collections, SNI content, Reporter generation, or Interpreter generation.
- Validate on disposable artifact copies before starting a fresh canonical run.
- Run pair 05 globally serial: no-SNI first, SNI only after no-SNI passes.
- Use RAG backend 4000 through the configured condition API, Interpreter/Reporter Ollama 6000, and model `qwen3.5:122b`.
- Every production change follows RED → GREEN TDD and uses a Lore-format commit.

---

### Task 1: Replace free-form semantic output with one structured repair decision

**Files:**
- Modify: `scripts/repair_report.py:6-23`
- Modify: `scripts/repair_report.py:85-93`
- Modify: `scripts/repair_report.py:261-282`
- Modify: `scripts/repair_report.py:433-499`
- Modify: `tests/scripts/test_repair_report.py`

**Interfaces:**
- Preserve: `repair_issues(data_dir: Path, issues: list[dict[str, Any]], *, llm: Any | None = None, provider: str | None = None, claim_validation: list[dict[str, Any]] | None = None) -> int`.
- Preserve: `repair_report(data_dir: Path, issues_path: Path, *, llm: Any | None = None, provider: str | None = None, claim_validation: list[dict[str, Any]] | None = None) -> int`.
- Add: `RepairDecision(BaseModel)` with `action: Literal["replace", "delete"]` and `replacement_text: str = ""`.
- Add: `_invoke_repair_decision(model: Any, issues: list[dict[str, Any]], target_text: str) -> RepairDecision`.
- Preserve: `_safe_claim_replacement(original: str, candidate: str) -> bool` for deterministic replacements.
- Add: `_safe_semantic_decision(original: str, decision: RepairDecision) -> bool`.
- Preserve: deterministic `replacement_text` dispatch without an LLM call.

- [ ] **Step 1: Convert the semantic test double to structured output**

Replace the plain-text `ClaimReplacementLLM` helper with a reusable structured fake:

```python
class RepairDecisionLLM:
    def __init__(self, *, action: str = "replace", replacement_text: str = "") -> None:
        self.action = action
        self.replacement_text = replacement_text
        self.calls = 0
        self.prompts: list[str] = []
        self.schema = None

    def with_structured_output(self, schema, **_kwargs):
        self.schema = schema
        return self

    def invoke(self, prompt: str):
        self.calls += 1
        self.prompts.append(prompt)
        assert self.schema is not None
        return self.schema(
            action=self.action,
            replacement_text=self.replacement_text,
        )
```

Update existing semantic repair tests to construct it with
`action="replace"`. Keep `FailLLM` for deterministic tests so an accidental
semantic call still fails immediately.

- [ ] **Step 2: Write RED tests for structured replace and delete**

Add these exact tests to `tests/scripts/test_repair_report.py`:

```python
def test_repair_accepts_structured_replace_below_old_half_length_limit(tmp_path: Path) -> None:
    target = "NECTIN4 is an underexplored therapeutic target that warrants drug development."
    report = tmp_path / "part3_final.md"
    report.write_text(f"## Biology\nBefore.\n{target}\nAfter.\n", encoding="utf-8")
    issues = _write_issues(tmp_path, [{
        "severity": "error",
        "code": "part3_therapeutic_spillover",
        "file": report.name,
        "section": "## Biology",
        "target_text": target,
        "evidence": "Part3 contains spatial evidence only.",
        "repair_instruction": "Remove therapeutic framing.",
    }])

    changed = repair_report.repair_report(
        tmp_path,
        issues,
        llm=RepairDecisionLLM(
            action="replace",
            replacement_text="NECTIN4 remains a selected spatial signal.",
        ),
    )

    assert changed == 1
    assert report.read_text(encoding="utf-8") == (
        "## Biology\nBefore.\nNECTIN4 remains a selected spatial signal.\nAfter.\n"
    )
```

```python
def test_repair_accepts_structured_delete_for_only_the_exact_target(tmp_path: Path) -> None:
    target = "NECTIN4 is an underexplored therapeutic target."
    original = f"## Biology\nKeep before.\n{target}\nKeep after.\n## Later\nKeep later.\n"
    report = tmp_path / "part3_final.md"
    report.write_text(original, encoding="utf-8")
    trace = tmp_path / "repair_trace.jsonl"
    trace.write_text("", encoding="utf-8")
    issues = _write_issues(tmp_path, [{
        "severity": "error",
        "code": "part3_therapeutic_spillover",
        "file": report.name,
        "section": "## Biology",
        "target_text": target,
        "evidence": "No supported spatial statement remains in this sentence.",
        "repair_instruction": "Delete the unsupported target only.",
    }])

    changed = repair_report.repair_report(
        tmp_path,
        issues,
        llm=RepairDecisionLLM(action="delete", replacement_text=""),
    )

    repaired = report.read_text(encoding="utf-8")
    assert changed == 1
    assert target not in repaired
    assert "Keep before." in repaired
    assert "Keep after." in repaired
    assert "## Later\nKeep later.\n" in repaired
    assert repair_report._markdown_headings(repaired) == repair_report._markdown_headings(original)
    assert _trace_rows(trace)[-1]["path"] == "llm_delete"
```

- [ ] **Step 3: Run the two new tests and verify RED**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/scripts/test_repair_report.py::test_repair_accepts_structured_replace_below_old_half_length_limit \
  tests/scripts/test_repair_report.py::test_repair_accepts_structured_delete_for_only_the_exact_target
```

Expected: FAIL because semantic repair still consumes free-form content, empty
replacement is rejected, and the 50% target-length rule is still active.

- [ ] **Step 4: Implement the minimal structured contract**

Add the existing-dependency schema and a single invocation helper:

```python
from typing import Any, Literal

from pydantic import BaseModel, ValidationError


class RepairDecision(BaseModel):
    action: Literal["replace", "delete"]
    replacement_text: str = ""


def _invoke_repair_decision(
    model: Any,
    issues: list[dict[str, Any]],
    target_text: str,
) -> RepairDecision:
    result = model.with_structured_output(
        RepairDecision,
        method="function_calling",
    ).invoke(_build_claim_prompt(issues, target_text))
    if isinstance(result, RepairDecision):
        return result
    return RepairDecision.model_validate(result)
```

Update `_build_claim_prompt` so it treats issue evidence and instructions
as binding, prefers `replace`, permits `delete` only when no supported assertion
can remain, and removes the existing `Do not delete the claim` instruction.

Keep `_safe_claim_replacement` unchanged for deterministic replacements. Add
action-aware safety only for semantic decisions:

```python
def _safe_semantic_decision(
    original: str,
    decision: RepairDecision,
) -> bool:
    candidate = decision.replacement_text.strip()
    if decision.action == "replace" and not candidate:
        return False
    if decision.action == "delete" and candidate:
        return False
    if _markdown_headings(candidate):
        return False
    return _pmids(candidate).issubset(_pmids(original))
```

In the semantic branch, catch `ValidationError`, `TypeError`, and `ValueError`,
record `invalid_repair_decision`, and preserve the report. Validate the result
with `_safe_semantic_decision`. Use audit path `llm_replace` or `llm_delete`;
keep `retention_ratio`, including `0.0` for a delete. Remove `_content` after
confirming it has no remaining callers.

- [ ] **Step 5: Write RED safety tests for contradictory or malformed decisions**

Add a parameterized test that preserves the exact original file for:

```python
@pytest.mark.parametrize(
    ("action", "candidate", "reason"),
    [
        ("replace", "", "unsafe_replacement"),
        ("delete", "text must be empty", "unsafe_replacement"),
        ("replace", "### New Heading", "unsafe_replacement"),
        ("replace", "Claim (PMID: 99999999).", "unsafe_replacement"),
    ],
)
def test_repair_rejects_unsafe_structured_decisions_and_preserves_file(
    tmp_path: Path,
    action: str,
    candidate: str,
    reason: str,
) -> None:
    target = "Original supported context with an unsupported conclusion (PMID: 12345678)."
    original = f"## Biology\n{target}\n"
    report = tmp_path / "part2_final.md"
    report.write_text(original, encoding="utf-8")
    trace = tmp_path / "repair_trace.jsonl"
    trace.write_text("", encoding="utf-8")
    issues = _write_issues(tmp_path, [{
        "severity": "error",
        "code": "claim_rag_overclaimed",
        "file": report.name,
        "section": "## Biology",
        "target_text": target,
    }])

    changed = repair_report.repair_report(
        tmp_path,
        issues,
        llm=RepairDecisionLLM(action=action, replacement_text=candidate),
    )

    assert changed == 0
    assert report.read_text(encoding="utf-8") == original
    assert _trace_rows(trace)[-1]["reason"] == reason
```

Add the malformed-result case explicitly:

```python
class MalformedDecisionLLM:
    def with_structured_output(self, _schema, **_kwargs):
        return self

    def invoke(self, _prompt: str):
        return {"action": "rewrite", "replacement_text": "x"}


def test_repair_rejects_malformed_structured_decision(tmp_path: Path) -> None:
    target = "Unsupported claim."
    original = f"## Biology\n{target}\n"
    report = tmp_path / "part2_final.md"
    report.write_text(original, encoding="utf-8")
    trace = tmp_path / "repair_trace.jsonl"
    trace.write_text("", encoding="utf-8")
    issues = _write_issues(tmp_path, [{
        "severity": "error",
        "code": "claim_rag_unsupported",
        "file": report.name,
        "section": "## Biology",
        "target_text": target,
    }])

    changed = repair_report.repair_report(
        tmp_path,
        issues,
        llm=MalformedDecisionLLM(),
    )

    assert changed == 0
    assert report.read_text(encoding="utf-8") == original
    assert _trace_rows(trace)[-1]["reason"] == "invalid_repair_decision"
```

- [ ] **Step 6: Run Task 1 tests to GREEN**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/scripts/test_repair_report.py
uv run ruff check scripts/repair_report.py tests/scripts/test_repair_report.py
uv run python -m py_compile scripts/repair_report.py
git diff --check
```

Expected: all repair-script tests pass; deterministic tests prove the LLM is
not called; all target ambiguity and heading tests remain green.

- [ ] **Step 7: Commit Task 1 with Lore trailers**

```bash
git add scripts/repair_report.py tests/scripts/test_repair_report.py
git add -f \
  docs/superpowers/plans/2026-08-19-safe-complete-atomic-report-repair.md \
  docs/superpowers/specs/2026-08-19-safe-complete-atomic-report-repair-design.md
git commit -m "Let exact targets reach evidence-safe terminal states

Constraint: Keep deterministic repairs and exact-target fail-closed boundaries unchanged
Rejected: Whole-section fallback | It changes unrelated report content
Rejected: Per-error repair strategies | The validator issue already carries the repair contract
Confidence: high
Scope-risk: narrow
Directive: Keep semantic repair structured and confined to target_text
Tested: tests/scripts/test_repair_report.py; Ruff; py_compile; git diff --check
Not-tested: Live qwen3.5:122b artifact replay"
```

---

### Task 2: Remove the direction false positive and lock remaining BC failure shapes

**Files:**
- Modify: `scripts/validate_report.py:40-57`
- Modify: `tests/scripts/test_validate_report.py`
- Modify: `tests/scripts/test_validate_repair_report.py`
- Modify: `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`

**Interfaces:**
- Consume: Task 1 `RepairDecision` structured path through the unchanged `repair_report` interface.
- Preserve: `_pathway_direction_claims(text: str, pathway_labels: dict[str, str]) -> dict[str, tuple[bool, bool]]` and its existing positive/negative tuple contract.
- Preserve: `run_report_guardrail` regular three-pass loop, existing terminal repair for newly surfaced errors, and fail-closed result shape.
- Produce: regression evidence for negative pathway direction, unsupported claim deletion, unsupported citation deletion, and Part 3 therapeutic spillover.

- [ ] **Step 1: Write the RED validator regression from the latest failed artifact**

Add this case to `tests/scripts/test_validate_report.py` using two negative
estimates in `sig_liana_pathway_factor.csv`:

```python
def test_allows_negatively_associated_factor_pathways_with_negative_estimates(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [
            {
                "factor": "Factor3",
                "pathway": "Estrogen",
                "estimate": -5.4798,
                "p": 4.98e-08,
                "adj_p": 1.0e-06,
            },
            {
                "factor": "Factor3",
                "pathway": "EGFR",
                "estimate": -2.8971,
                "p": 0.0038,
                "adj_p": 0.02,
            },
        ],
    )
    (tmp_path / "part2_final.md").write_text(
        "## Analysis 2-8\n"
        "The pathway enrichment analysis shows Factor3 is negatively associated "
        "with Estrogen and EGFR.\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not [
        issue
        for issue in issues
        if issue["code"] == "factor_pathway_direction_mismatch"
    ]
```

- [ ] **Step 2: Run the new validator test and verify RED**

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/scripts/test_validate_report.py::test_allows_negatively_associated_factor_pathways_with_negative_estimates
```

Expected: FAIL with direction mismatch issues because `negative` matches but
`negatively` does not, while `enrichment` is classified as positive.

- [ ] **Step 3: Extend only the existing direction vocabulary**

Update the three existing factor-pathway direction regexes so their literal
vocabulary includes these forms:

```python
FACTOR_PATHWAY_POSITIVE_RE = re.compile(
    r"\b(enriched|enrichment|activation|activated|active|higher|increased|positive(?:ly)?)\b",
    re.IGNORECASE,
)
FACTOR_PATHWAY_NEGATIVE_RE = re.compile(
    r"\b(depleted|depletion|negative(?:ly)?|inverse(?:ly)?|lower|reduced|attenuated|suppressed)\b",
    re.IGNORECASE,
)
```

Mirror `positive(?:ly)?`, `negative(?:ly)?`, and `inverse(?:ly)?` in
`FACTOR_PATHWAY_NEGATED_DIRECTION_RE` and `FACTOR_PATHWAY_CLAIM_RE`. Do not
change factor/pathway locality, estimate lookup, or mismatch routing.

- [ ] **Step 4: Run the direction validator suite to GREEN**

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/scripts/test_validate_report.py -k 'pathway and direction'
uv run ruff check scripts/validate_report.py tests/scripts/test_validate_report.py
uv run python -m py_compile scripts/validate_report.py
```

Expected: the new adverbial regression and all existing genuine-mismatch tests
pass.

- [ ] **Step 5: Update the existing direction integration fake**

Replace the existing plain-text `DirectionLLM.invoke` result with this local
structured fake:

```python
class StructuredDecisionLLM:
    def __init__(self, *, action: str, replacement_text: str) -> None:
        self.action = action
        self.replacement_text = replacement_text
        self.schema = None

    def with_structured_output(self, schema, **_kwargs):
        self.schema = schema
        return self

    def invoke(self, _prompt: str):
        assert self.schema is not None
        return self.schema(
            action=self.action,
            replacement_text=self.replacement_text,
        )


class DirectionLLM(StructuredDecisionLLM):
    def __init__(self) -> None:
        super().__init__(
            action="replace",
            replacement_text="Factor3 shows EGFR depletion.",
        )
```

Keep the existing assertion that real validation reports zero hard errors and
that headings are unchanged after repair.

- [ ] **Step 6: Add a real-validator Part 3 delete regression**

Add this integration shape to `tests/scripts/test_validate_repair_report.py`:

```python
def test_real_validate_repair_validate_deletes_unsupported_part3_spillover(
    tmp_path: Path,
) -> None:
    _write_json(tmp_path / "papers.json", [])
    report = tmp_path / "part3_final.md"
    report.write_text(
        "## Analysis 3-10\n"
        "### Biological Interpretation\n"
        "NECTIN4 is an underexplored therapeutic target.\n"
        "Spatial evidence remains unchanged.\n",
        encoding="utf-8",
    )
    before = _headings(report.read_text(encoding="utf-8"))
    issues = validate_report.validate_report(tmp_path)
    issues_path = tmp_path / "issues.json"
    _write_json(issues_path, {"issues": issues})

    changed = repair_report.repair_report(
        tmp_path,
        issues_path,
        llm=StructuredDecisionLLM(action="delete", replacement_text=""),
    )

    final = validate_report.validate_report(tmp_path)
    assert changed == 1
    assert not [issue for issue in final if issue["severity"] == "error"]
    assert _headings(report.read_text(encoding="utf-8")) == before
    assert "Spatial evidence remains unchanged." in report.read_text(encoding="utf-8")
```

- [ ] **Step 7: Add common-path regressions for the latest unresolved issue classes**

Add one parameterized exact-target deletion test for the two remaining
Claim-RAG shapes. The direction-mismatch replacement is already covered by the
real-validator integration test updated in Step 1.

Add `import pytest` to `tests/scripts/test_validate_repair_report.py` before
adding the parameterized test.

```python
@pytest.mark.parametrize(
    "code",
    ["claim_rag_unsupported", "inline_citation_unsupported"],
)
def test_unsupported_claim_shapes_delete_only_the_exact_target(
    tmp_path: Path,
    code: str,
) -> None:
    target = "p53 directly drives invasion (PMID: 12345678)."
    original = f"## Biology\nKeep before.\n{target}\nKeep after.\n"
    report = tmp_path / "part1_final.md"
    report.write_text(original, encoding="utf-8")
    issue = {
        "severity": "error",
        "code": code,
        "file": report.name,
        "section": "## Biology",
        "value": target,
        "target_text": target,
        "evidence": "The supplied evidence does not support this assertion.",
        "repair_instruction": "Remove the unsupported assertion.",
    }
    if code == "inline_citation_unsupported":
        issue["inline_pmid"] = "12345678"
        issue["source_claim_index"] = 0
    issues_path = tmp_path / "issues.json"
    _write_json(issues_path, {"issues": [issue]})

    changed = repair_report.repair_report(
        tmp_path,
        issues_path,
        llm=StructuredDecisionLLM(action="delete", replacement_text=""),
        claim_validation=[],
    )

    repaired = report.read_text(encoding="utf-8")
    assert changed == 1
    assert target not in repaired
    assert "Keep before." in repaired
    assert "Keep after." in repaired
    assert _headings(repaired) == _headings(original)
    assert repair_report._pmids(repaired).issubset(repair_report._pmids(original))
```

Do not add error-code dispatch to production code; both cases must pass through
the same field-driven semantic branch.

- [ ] **Step 8: Prove synthesis reaches the same structured delete path**

Add this regression to
`tests/agents/deep_interpreter/test_report_guardrail_middleware.py`:

```python
def test_repair_synthesis_report_uses_structured_delete_for_targeted_issue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    target = "CXCL12 directly drives immune migration."
    original = f"## Cross-Part Themes\n\nKeep before.\n{target}\nKeep after.\n"
    synthesis = tmp_path / "synthesis.md"
    synthesis.write_text(original, encoding="utf-8")
    issues = [{
        "severity": "error",
        "code": "claim_rag_unsupported",
        "file": synthesis.name,
        "section": "## Cross-Part Themes",
        "value": target,
        "target_text": target,
        "evidence": "No retrieved evidence supports the causal assertion.",
        "repair_instruction": "Remove the unsupported assertion.",
    }]

    class DeleteDecisionLLM:
        def with_structured_output(self, schema, **_kwargs):
            self.schema = schema
            return self

        def invoke(self, _prompt: str):
            return self.schema(action="delete", replacement_text="")

    monkeypatch.setattr(
        report_guardrails.repair_report_script,
        "_create_model",
        lambda _provider: DeleteDecisionLLM(),
    )

    changed = report_guardrails.repair_synthesis_report(
        tmp_path,
        issues,
        provider="ollama",
    )

    repaired = synthesis.read_text(encoding="utf-8")
    assert changed == 1
    assert target not in repaired
    assert "Keep before." in repaired
    assert "Keep after." in repaired
    assert [line for line in repaired.splitlines() if line.startswith("#")] == [
        line for line in original.splitlines() if line.startswith("#")
    ]
```

- [ ] **Step 9: Prove controller revalidation and fail-closed behavior remain unchanged**

Run the existing controller tests together with the new integration tests:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/scripts/test_validate_repair_report.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_run_report_guardrail_retries_up_to_three_repairs \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_run_report_guardrail_terminally_repairs_new_final_error \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_run_report_guardrail_does_not_terminally_retry_persistent_error \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_report_guardrail_middleware_raises_when_hard_errors_remain
```

Expected: all tests pass without changing `report_guardrails.py`.

- [ ] **Step 10: Commit Task 2 with Lore trailers**

```bash
git add \
  scripts/validate_report.py \
  tests/scripts/test_validate_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
git commit -m "Distinguish repaired negative associations from positive enrichment

Constraint: Cover production-shaped direction, citation, unsupported-claim, and Part3 scope failures
Rejected: Error-code-specific patch functions | All cases use the shared atomic issue contract
Confidence: high
Scope-risk: moderate
Directive: New semantic validators must remain repairable through target_text and evidence
Tested: direction validator suite, validate-repair-validate integration tests, and bounded guardrail controller tests
Not-tested: Live Claim-RAG and qwen3.5:122b"
```

---

### Task 3: Pass static, regression, and failed-artifact replay gates

**Files:**
- Verification only; do not modify historical artifacts.
- Use a `mktemp -d` disposable replay directory.

**Interfaces:**
- Consume: committed Task 1 and Task 2 changes.
- Produce: fresh evidence that the latest failed no-SNI report copy reaches zero hard errors with identical headings.

- [ ] **Step 1: Run the complete relevant regression suite**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/scripts/test_repair_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/scripts/test_validate_report.py \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/agents/deep_interpreter/test_synthesis_consistency_validation.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py \
  tests/test_rag_path_resolution.py \
  tests/test_sni_ablation_runner.py \
  tests/test_reporter.py \
  tests/test_reporter_phase5.py
uv run ruff check \
  scripts/repair_report.py \
  scripts/validate_report.py \
  tests/scripts/test_repair_report.py \
  tests/scripts/test_validate_report.py \
  tests/scripts/test_validate_repair_report.py
uv run python -m py_compile scripts/repair_report.py scripts/validate_report.py
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 2: Verify live dependencies before replay**

Check, without starting a production run:

```bash
curl --fail --silent http://localhost:6000/api/tags | jq -e '.models[] | select(.name == "qwen3.5:122b")'
curl --fail --silent --show-error http://localhost:8883/health
```

Expected: qwen3.5:122b is listed on 6000 and the pair-05 no-SNI condition API
on 8883 returns HTTP 2xx and still routes to RAG backend 4000.

- [ ] **Step 3: Copy the latest failed report into a disposable replay directory**

```bash
repair_replay_source="res/deep_interpreter/bc/sni_repair_ablation/hybrid_20260819T085406Z/pairs/pair-05/wiki-off"
repair_replay_dir="$(mktemp -d /tmp/deepmast-safe-repair.XXXXXX)"
repair_pristine_dir="$(mktemp -d /tmp/deepmast-safe-repair-pristine.XXXXXX)"
cp -R "${repair_replay_source}/." "${repair_replay_dir}/"
cp -R "${repair_replay_source}/." "${repair_pristine_dir}/"
```

Verify both copies are initially identical to the historical source with
`diff -qr`. Never invoke the guardrail against `repair_replay_source` or
`repair_pristine_dir`.

- [ ] **Step 4: Run the real bounded guardrail on the disposable copy**

```bash
CCI_RAG_BASE_URL=http://localhost:8883 \
OLLAMA_BASE_URL=http://localhost:6000 \
OLLAMA_MODEL=qwen3.5:122b \
LLM_PROVIDER=ollama \
uv run python -c '
import json
import sys
from pathlib import Path
from src.agents.deep_interpreter.report_guardrails import run_report_guardrail

data_dir = Path(sys.argv[1]).resolve()
result = run_report_guardrail(data_dir, provider="ollama")
print(json.dumps(result, indent=2, sort_keys=True))
assert result["status"] == "passed", result
assert result["final_error_count"] == 0, result
' "${repair_replay_dir}"
```

Expected: the copied artifact's current 12 hard errors reach zero within the
existing bounded loop. Run these exact structural checks:

```bash
for repair_file in part1_final.md part2_final.md part3_final.md; do
  diff \
    <(rg '^#{1,6} ' "${repair_pristine_dir}/${repair_file}") \
    <(rg '^#{1,6} ' "${repair_replay_dir}/${repair_file}")
done
diff -qr "${repair_replay_source}" "${repair_pristine_dir}"
uv run python -c '
import re
import sys
from pathlib import Path

before = Path(sys.argv[1])
after = Path(sys.argv[2])
pmid = re.compile(r"\bPMID[:\s]*(\d{6,9})\b", re.IGNORECASE)
before_pmids = set().union(*(set(pmid.findall((before / name).read_text())) for name in ("part1_final.md", "part2_final.md", "part3_final.md")))
after_pmids = set().union(*(set(pmid.findall((after / name).read_text())) for name in ("part1_final.md", "part2_final.md", "part3_final.md")))
assert after_pmids <= before_pmids, sorted(after_pmids - before_pmids)
' "${repair_pristine_dir}" "${repair_replay_dir}"
```

Require identical headings, no newly introduced PMID, and an unchanged
historical source.

- [ ] **Step 5: Replay synthesis through the same semantic patcher**

Use the saved complete-run synthesis before-repair artifact, not generated
content from the failed Part 3 run:

```bash
synthesis_source="res/deep_interpreter/bc/sni_repair_ablation/task6_20260817T072643Z/pairs/pair-05/wiki-off"
synthesis_replay_dir="$(mktemp -d /tmp/deepmast-safe-synthesis.XXXXXX)"
cp -R "${synthesis_source}/." "${synthesis_replay_dir}/"
cp "${synthesis_replay_dir}/before/synthesis.md" "${synthesis_replay_dir}/synthesis.md"
CCI_RAG_BASE_URL=http://localhost:8883 \
OLLAMA_BASE_URL=http://localhost:6000 \
OLLAMA_MODEL=qwen3.5:122b \
LLM_PROVIDER=ollama \
uv run python -c '
import json
import sys
from pathlib import Path
from src.agents.deep_interpreter.report_guardrails import run_synthesis_guardrail

data_dir = Path(sys.argv[1]).resolve()
before_headings = [line for line in (data_dir / "synthesis.md").read_text().splitlines() if line.startswith("#")]
result = run_synthesis_guardrail(data_dir, provider="ollama")
after_headings = [line for line in (data_dir / "synthesis.md").read_text().splitlines() if line.startswith("#")]
print(json.dumps(result, indent=2, sort_keys=True))
assert result["status"] == "passed", result
assert result["final_error_count"] == 0, result
assert after_headings == before_headings
' "${synthesis_replay_dir}"
```

Expected: synthesis reaches zero hard errors, preserves headings, and leaves
the saved source directory unchanged.

- [ ] **Step 6: Stop at the replay gate on any failure**

If the replay fails, preserve the disposable directory and its
`report_validation_final.json`, classify the remaining error as patcher,
validator, Claim-RAG, or infrastructure evidence, and return to the owning TDD
task. Do not start Part generation or the SNI condition while replay has a hard
error.

---

### Task 4: Complete one fresh canonical no-SNI then SNI pair

**Files:**
- Live verification only; generated outputs remain under ignored `res/` paths.

**Interfaces:**
- Consume: passed Task 3 gates.
- Produce: one complete pair-05 no-SNI/SNI comparison with both condition manifests passed.

- [ ] **Step 1: Recheck the canonical runtime contract**

Confirm immediately before launch:

- port 4000 serves the fixed RAG backend;
- port 6000 lists and can invoke `qwen3.5:122b`;
- pair-05 condition API uses port 8883;
- fixed collection UUID remains `a208e916-bd32-405a-9eee-de4cd82b2a3b`;
- source and collection contain the same exact 100 PMIDs;
- no matching ablation runner is active; and
- the experiment manifest still orders pair 05 as no-SNI then SNI.

- [ ] **Step 2: Launch one fresh serial pair without an external timeout**

```bash
repair_run_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
repair_output_root="res/deep_interpreter/bc/sni_repair_ablation/safe_complete_${repair_run_stamp}/pairs"
uv run python scripts/run_bc_sni_repair_ablation.py \
  --pair 5 \
  --output-root "${repair_output_root}" \
  --source /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res/deep_interpreter/bc/bc \
  --manifest res/deep_interpreter/bc/sni_repair_ablation/experiment_manifest_rag4000.json
```

The runner remains foreground/monitored, globally serial, and fail-fast. SNI
must not start unless no-SNI ends with zero final hard errors and a passed
manifest.

- [ ] **Step 3: Verify no-SNI before allowing SNI to continue**

At the no-SNI boundary, independently require:

- `report_validation_final.json` has zero severity-error issues;
- Part 1, Part 2, Part 3, and synthesis heading sequences are preserved;
- no repair added a PMID absent from the condition's original report set;
- source/collection identity remains exactly 100 PMIDs;
- the condition manifest is marked passed; and
- repair trace contains no accepted ambiguous target or unsafe structured decision.

- [ ] **Step 4: Monitor SNI to terminal and summarize the pair**

After SNI completes, invoke the runner's existing summary mode with the same
manifest and output root. Require both condition manifests passed and no
lingering runner process.

```bash
uv run python scripts/run_bc_sni_repair_ablation.py \
  --summarize \
  --output-root "${repair_output_root}" \
  --source /Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res/deep_interpreter/bc/bc \
  --manifest res/deep_interpreter/bc/sni_repair_ablation/experiment_manifest_rag4000.json
```

Report for each condition:

- initial and final hard-error counts;
- regular, terminal, and total repair counts;
- `replace`, `delete`, and deterministic repair counts;
- changed target count and heading preservation;
- Claim-RAG attempts, positive hits, zero hits, unique PMIDs, and elapsed time;
- total condition elapsed time; and
- source, selected-paper, cited-PMID, and collection PMID flow.

- [ ] **Step 5: Perform final branch verification**

```bash
git status --short
git log -2 --format=fuller
git diff HEAD~2..HEAD --check
```

Expected: only intentional commits are present, the worktree has no uncommitted
production/test changes, both Lore commits contain required trailers, and live
artifacts remain ignored.

---

## Plan Self-Review

- Spec coverage: structured replace, structured delete, deterministic bypass,
  local safety, full revalidation, fail-closed publication, replay, and fresh
  no-SNI/SNI completion each map to a task.
- Minimality: two production files change: one shared semantic patcher and one
  direction-vocabulary correction; the existing controller remains the source
  of truth.
- Type consistency: `RepairDecision`, `_invoke_repair_decision`,
  `_safe_claim_replacement`, `_safe_semantic_decision`, `repair_issues`, and
  `repair_report` have one consistent signature throughout the plan.
- Regression coverage: the four remaining live error classes are exercised
  without adding production error-code dispatch.
- Safety: exact target boundaries, heading identity, no-new-PMID checks,
  structured-result validation, bounded retries, and final zero-error gating
  remain mandatory.
- Performance: unit tests and saved-artifact replay gate the expensive fresh
  pair; no repeated 10-hour generation is authorized before replay passes.
- Scope exclusions: no LangChain Skills runtime, new dependency, repair agent,
  strategy registry, fuzzy locator, whole-section rewrite, SGCP-RAG mutation,
  or replicated experiment is introduced.
- Placeholder scan: all task files, interfaces, test names, commands, expected
  outcomes, and stop conditions are explicit.

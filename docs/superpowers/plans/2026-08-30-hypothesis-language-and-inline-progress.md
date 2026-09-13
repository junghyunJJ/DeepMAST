# Hypothesis Language and Inline Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the Pair-15 plural-hypothesis false positive, preserve only
Pair-16-shaped disjoint repairable inline-citation progress, and prevent a
leading PMID repair from leaving subjectless prose.

**Architecture:** Make three local policy edits at existing shared decision
points. `HYPOTHESIS_RE` gains the missing plural word form;
`_strict_phase_progress` adds one bounded same-count exception; and
`_remove_inline_pmid` declines only a leading-PMID alphabetic prose target so
the existing structured exact-target repair handles it.

**Tech Stack:** Python 3.11, stdlib `re`, pytest, existing Deep Interpreter validator and guardrail modules.

**Spec:** `docs/superpowers/specs/2026-08-30-hypothesis-language-and-inline-progress-design.md`

## Global Constraints

- Treat the spec and `docs/superpowers/specs/2026-08-30-hypothesis-language-and-inline-progress-evidence.md` as authoritative; the 2026-08-29 frontier documents are historical only.
- Planned production/test scope is limited to `scripts/validate_report.py`,
  `tests/scripts/test_validate_report.py`,
  `src/agents/deep_interpreter/report_guardrails.py`,
  `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`,
  `scripts/repair_report.py`, and `tests/scripts/test_repair_report.py`.
- Tasks 1-3 preserve `scripts/repair_report.py`. Task 4 may add only the
  replay-proven leading-PMID prose guard and its focused tests; grouped
  non-supported cleanup, supported-sibling retention, and reference-only
  deletion must remain intact.
- Keep deterministic-to-semantic admission and same-phase lower-count admission unchanged.
- Equal-count progress requires semantic phases, equal non-zero counts, exclusively `REPAIRABLE_INLINE_CITATION_CODES`, non-empty key sets, and disjoint `(file, section, value)` key sets.
- Equal-count count increase, same/overlapping targets, mixed/generic errors, phase regression, and zero-count/empty frontiers remain rejected.
- Do not change RAG/SNI/query/collection behavior, Reporter timeout or attempts, repair-pass counts, Part generation, recovery, finalizer ownership, rendering, models, or ports.
- Add no dependency, module, configuration switch, or abstraction.
- Follow RED -> observed expected failure -> minimal GREEN for each production edit.
- Every commit must follow the Lore protocol and must not rewrite existing commits.

---

## File Structure

- `scripts/validate_report.py` — pathway-factor hypothesis-language recognition.
- `tests/scripts/test_validate_report.py` — Pair-15 exact-sentence regression plus existing singular/variant/significance boundaries.
- `src/agents/deep_interpreter/report_guardrails.py` — shared repair progress admission used by Part and synthesis loops.
- `tests/agents/deep_interpreter/test_report_guardrail_middleware.py` — Pair-16 progress truth table and real two-repair guardrail chain.
- `scripts/repair_report.py` — shared inline-PMID token stripping and structured fallback routing.
- `tests/scripts/test_repair_report.py` — replay-shaped leading-PMID RED/GREEN and retained deterministic boundaries.

No production or test file is created.

### Task 1: Recognize plural hypothesis language

**Files:**
- Modify: `tests/scripts/test_validate_report.py`
- Modify: `scripts/validate_report.py:72-76`

**Interfaces:**
- Consumes: `validate_report.validate_report(data_dir: Path) -> list[dict[str, str]]`
- Produces: `HYPOTHESIS_RE` recognizes `hypotheses` while retaining `hypothesis`, `hypothesized`, and `hypothesised`.

- [ ] **Step 1: Add the exact Pair-15 RED and direct word-form regressions**

Add this test beside the existing factor-pathway hypothesis tests:

```python
def test_allows_pair15_plural_hypotheses_language(tmp_path: Path) -> None:
    _write_json(tmp_path / "papers.json", [])
    _write_csv(
        tmp_path / "sig_liana_pathway_factor.csv",
        [
            {
                "factor": "Factor3",
                "pathway": "EGFR",
                "estimate": -2.897,
                "p": 0.004,
                "adj_p": 0.028,
            },
            {
                "factor": "Factor3",
                "pathway": "Estrogen",
                "estimate": -5.480,
                "p": 4.98e-08,
                "adj_p": 4.98e-07,
            },
            {
                "factor": "Factor2",
                "pathway": "Hypoxia",
                "estimate": 7.335,
                "p": 3.59e-13,
                "adj_p": 3.59e-12,
            },
        ],
    )
    target = (
        "- **Connection to Analysis 2-7 (NMF Factor)**: The pathway enrichments "
        "provide annotation-based hypotheses for Factor3's biological program, "
        "suggesting potential associations with estrogen-independent, "
        "hypoxia-resistant states and restrained EGFR signaling."
    )
    (tmp_path / "part2_final.md").write_text(
        f"## Analysis 2-8: Pathway-Factor Enrichment\n{target}\n",
        encoding="utf-8",
    )

    issues = validate_report.validate_report(tmp_path)

    assert not any(
        issue["code"] == "unsupported_pathway_factor_significance"
        and issue["value"] == "Factor3: Hypoxia"
        for issue in issues
    )


def test_allows_hypothesis_word_forms_in_triggering_pathway_claims(
    tmp_path: Path,
) -> None:
    for case, word_form in (
        ("singular", "hypothesis"),
        ("american", "hypothesized"),
        ("british", "hypothesised"),
    ):
        data_dir = tmp_path / case
        data_dir.mkdir()
        _write_json(data_dir / "papers.json", [])
        _write_csv(
            data_dir / "sig_liana_pathway_factor.csv",
            [
                {
                    "factor": "Factor3",
                    "pathway": "EGFR",
                    "estimate": -2.897,
                    "p": 0.004,
                    "adj_p": 0.028,
                },
                {
                    "factor": "Factor2",
                    "pathway": "Hypoxia",
                    "estimate": 7.335,
                    "p": 3.59e-13,
                    "adj_p": 3.59e-12,
                },
            ],
        )
        (data_dir / "part2_final.md").write_text(
            "## Analysis 2-8: Pathway-Factor Enrichment\n"
            f"Factor3 Hypoxia enrichment remains an annotation-based {word_form}.\n",
            encoding="utf-8",
        )

        issues = validate_report.validate_report(data_dir)

        assert not any(
            issue["code"] == "unsupported_pathway_factor_significance"
            and issue["value"] == "Factor3: Hypoxia"
            for issue in issues
        ), word_form
```

- [ ] **Step 2: Run the exact test and observe RED**

Run:

```bash
pytest -q tests/scripts/test_validate_report.py::test_allows_pair15_plural_hypotheses_language
```

Expected: FAIL because the issues contain
`unsupported_pathway_factor_significance` with value `Factor3: Hypoxia`.

- [ ] **Step 3: Make the minimal production change**

Change only the hypothesis branch in `HYPOTHESIS_RE`:

```python
HYPOTHESIS_RE = re.compile(
    r"\b(may|might|could|hypothes(?:is|es|i[sz]ed)|hypothetical|inferred|suggests?|consistent with|"
    r"not pathway-factor significance)\b",
    re.IGNORECASE,
)
```

- [ ] **Step 4: Run the positive and retained-boundary tests**

Run:

```bash
pytest -q \
  tests/scripts/test_validate_report.py::test_allows_pair15_plural_hypotheses_language \
  tests/scripts/test_validate_report.py::test_allows_hypothesis_word_forms_in_triggering_pathway_claims \
  tests/scripts/test_validate_report.py::test_allows_factor1_hypothesis_language \
  tests/scripts/test_validate_report.py::test_allows_hypothetical_factor_pathway_language \
  tests/scripts/test_validate_report.py::test_flags_factor_pathway_significance_when_csv_lacks_claimed_pair
```

Expected: 5 passed. The second test directly protects singular `hypothesis`,
`hypothesized`, and `hypothesised` in otherwise-hard known-label claims; the
fourth retains `hypothetical`; and the last proves explicit unsupported
significance remains hard.

- [ ] **Step 5: Run the validator module**

Run:

```bash
pytest -q tests/scripts/test_validate_report.py
```

Expected: all tests pass with no new warning or error.

- [ ] **Step 6: Self-review the diff**

Confirm:

- the exact Pair-15 sentence is present in the test;
- no assertion inspects regex source text;
- only `|es` changes production behavior; and
- no unrelated formatting changed.

- [ ] **Step 7: Commit with Lore metadata**

Run:

```bash
git add scripts/validate_report.py tests/scripts/test_validate_report.py
git diff --cached --check
git commit \
  -m "Recognize plural hypothesis language at the validation boundary" \
  -m "Constraint: Preserve explicit unsupported pathway-factor significance errors and all existing hypothesis forms." \
  -m "Rejected: Broaden hypothesis detection outside the existing word-form branch | Pair-15 proves only the plural form is missing." \
  -m "Confidence: high" \
  -m "Scope-risk: narrow" \
  -m "Directive: Keep pathway-factor assertions hard unless the claim itself is explicitly hypothetical." \
  -m "Tested: Pair-15 exact RED/GREEN, singular and spelling variants, explicit significance boundary, and validator module." \
  -m "Not-tested: Pair-15 isolated artifact replay remains a post-review gate."
```

### Task 2: Admit only disjoint repairable inline same-count progress

**Files:**
- Modify: `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`
- Modify: `src/agents/deep_interpreter/report_guardrails.py:138-150`

**Interfaces:**
- Consumes: `_error_count`, `_issue_claim_key`, and `repair_report_script.REPAIRABLE_INLINE_CITATION_CODES`.
- Produces: `_strict_phase_progress(before, before_phase, after, after_phase) -> bool` with the spec's equal-count exception.
- Preserves: current Part and synthesis repair loops, grouped repair implementation, pass budgets, and rollback snapshots.

- [ ] **Step 1: Add the progress truth-table regression**

Add this test after `test_strict_phase_progress_accepts_only_safe_phase_transitions`:

```python
def test_strict_phase_progress_allows_only_disjoint_repairable_inline_same_count() -> None:
    from src.agents.deep_interpreter import report_guardrails

    def inline_issue(value: str, section: str = "## Cross-Part Themes") -> dict[str, str]:
        return {
            "severity": "error",
            "code": "inline_citation_overclaimed",
            "file": "synthesis.md",
            "section": section,
            "value": value,
        }

    reference = inline_issue(
        "PMID: 18922900 - LRIG1 suppression in ErbB2+ tumors",
        "## References",
    )
    prose = inline_issue(
        "Literature support (PMID: 28174229, 26148232, 39753722) confirms an ErbB mechanism."
    )
    other = inline_issue("A second inline target.")
    generic = {
        "severity": "error",
        "code": "synthesis_consistency_unresolved",
        "file": "synthesis.md",
        "section": "## Cross-Part Themes",
        "value": "A generic semantic target.",
    }

    assert report_guardrails._strict_phase_progress(
        [reference], "semantic", [prose], "semantic"
    )
    assert not report_guardrails._strict_phase_progress(
        [reference], "semantic", [reference], "semantic"
    )
    assert not report_guardrails._strict_phase_progress(
        [reference, other], "semantic", [other, prose], "semantic"
    )
    assert not report_guardrails._strict_phase_progress(
        [reference], "semantic", [prose, other], "semantic"
    )
    assert not report_guardrails._strict_phase_progress(
        [reference, other], "semantic", [prose, generic], "semantic"
    )
    assert not report_guardrails._strict_phase_progress(
        [generic], "semantic", [{**generic, "value": "Another generic target."}], "semantic"
    )
    assert not report_guardrails._strict_phase_progress(
        [reference], "semantic", [prose], "deterministic"
    )
    assert not report_guardrails._strict_phase_progress(
        [], "semantic", [], "semantic"
    )
```

- [ ] **Step 2: Add the Pair-16-shaped guardrail regression**

Add this test beside the existing grouped inline guardrail tests:

```python
def test_run_synthesis_guardrail_repairs_pair16_disjoint_inline_frontier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    reference = (
        "PMID: 18922900 - LRIG1 suppression in ErbB2+ tumors creates "
        "feed-forward loop contributing to overexpression"
    )
    compound = (
        "Literature support (PMID: 28174229, 26148232, 39753722) confirms "
        "ErbB2 overexpression alters cellular phenotype, LRIG1 negatively "
        "regulates ErbB3, and NRG1-ERBB3 signaling drives CTC survival."
    )
    pmids = ("18922900", "28174229", "26148232", "39753722")
    (tmp_path / "papers.json").write_text(
        json.dumps(
            {
                "papers": [
                    {"pmid": pmid, "abstract": "captured Pair-16 evidence"}
                    for pmid in pmids
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "synthesis.md").write_text(
        "# Synthesis Report\n\n"
        f"## Cross-Part Themes\n\n{compound}\n\n"
        f"## References\n\n{reference}\n",
        encoding="utf-8",
    )

    validate_calls = 0

    def citation(
        *,
        section: str,
        index: int,
        pmid: str,
        claim: str,
        status: str,
    ) -> dict[str, Any]:
        return {
            "file": "synthesis.md",
            "section": section,
            "source_claim_index": index,
            "inline_pmid": pmid,
            "claim": claim,
            "status": status,
            "supporting_pmids": [pmid] if status == "supported" else [],
            "evidence_quote": "captured Pair-16 evidence",
            "reason": "captured Pair-16 judgment",
        }

    def hard_issue(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "code": "inline_citation_overclaimed",
            "severity": "error",
            "file": row["file"],
            "section": row["section"],
            "source_claim_index": row["source_claim_index"],
            "inline_pmid": row["inline_pmid"],
            "value": row["claim"],
            "target_text": row["claim"],
        }

    def fake_validate(
        _data_dir: Path,
        filenames: tuple[str, ...],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        nonlocal validate_calls
        validate_calls += 1
        assert filenames == ("synthesis.md",)
        text = (tmp_path / "synthesis.md").read_text(encoding="utf-8")
        if reference in text:
            claims = [
                citation(
                    section="## References",
                    index=4,
                    pmid="18922900",
                    claim=reference,
                    status="overclaimed",
                )
            ]
            issues = [hard_issue(claims[0])]
        elif "28174229" in text:
            claims = [
                citation(
                    section="## Cross-Part Themes",
                    index=13,
                    pmid=pmid,
                    claim=compound,
                    status="overclaimed" if pmid == "28174229" else "supported",
                )
                for pmid in ("28174229", "26148232", "39753722")
            ]
            issues = [hard_issue(claims[0])]
        else:
            claims = [
                citation(
                    section="## Cross-Part Themes",
                    index=13,
                    pmid=pmid,
                    claim=compound,
                    status="supported",
                )
                for pmid in ("26148232", "39753722")
            ]
            issues = []
        return {
            "claims": claims,
            "issues": issues,
            "selection": {"selected_claim_count": len(claims)},
            "inline_citation_coverage": {
                "expected_count": len(claims),
                "evaluated_count": len(claims),
                "supported_count": sum(
                    row["status"] == "supported" for row in claims
                ),
                "coverage_complete": not issues,
                "citations": claims,
            },
        }

    monkeypatch.setattr(
        report_guardrails.claim_rag_validation,
        "validate_claims",
        fake_validate,
    )
    monkeypatch.setattr(
        report_guardrails.repair_report_script,
        "_create_model",
        lambda *_: (_ for _ in ()).throw(AssertionError("model must not be called")),
    )

    result = report_guardrails.run_synthesis_guardrail(
        tmp_path,
        provider="ollama",
    )

    repaired = (tmp_path / "synthesis.md").read_text(encoding="utf-8")
    assert result["status"] == "passed"
    assert result["initial_error_count"] == 1
    assert result["repair_attempt_count"] == 2
    assert result["terminal_repair_count"] == 0
    assert result["changed_claims"] == 2
    assert result["final_error_count"] == 0
    assert reference not in repaired
    assert "28174229" not in repaired
    assert "26148232" in repaired
    assert "39753722" in repaired
    assert validate_calls == 3
```

- [ ] **Step 3: Run the new tests and observe RED**

Run:

```bash
pytest -q \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_strict_phase_progress_allows_only_disjoint_repairable_inline_same_count \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_run_synthesis_guardrail_repairs_pair16_disjoint_inline_frontier
```

Expected: both fail on current strict aggregate progress. The unit test's first
assertion is false, and the guardrail result remains failed with the first
repair rolled back.

- [ ] **Step 4: Implement the minimal progress predicate**

Replace only the final aggregate return in `_strict_phase_progress`:

```python
    before_count = _error_count(before)
    after_count = _error_count(after)
    if after_count < before_count:
        return True
    if before_phase != "semantic" or after_count != before_count or not before_count:
        return False

    before_errors = [issue for issue in before if issue.get("severity") == "error"]
    after_errors = [issue for issue in after if issue.get("severity") == "error"]
    repairable = repair_report_script.REPAIRABLE_INLINE_CITATION_CODES
    if any(
        issue.get("code") not in repairable
        for issue in (*before_errors, *after_errors)
    ):
        return False

    before_keys = {_issue_claim_key(issue) for issue in before_errors}
    after_keys = {_issue_claim_key(issue) for issue in after_errors}
    return bool(before_keys and after_keys) and before_keys.isdisjoint(after_keys)
```

Do not edit either repair loop or `scripts/repair_report.py`.

- [ ] **Step 5: Run focused GREEN**

Run the Step 3 command again.

Expected: 2 passed. The Pair-16-shaped chain uses two deterministic repairs,
retains both supported PMIDs, and never creates a repair model.

- [ ] **Step 6: Run retained grouped-repair and phase/count boundaries**

Run:

```bash
pytest -q \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_strict_phase_progress_accepts_only_safe_phase_transitions \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_run_synthesis_guardrail_removes_grouped_non_supported_inline_pmids \
  tests/scripts/test_repair_report.py::test_repair_removes_all_non_supported_inline_pmids_without_llm \
  tests/scripts/test_repair_report.py::test_repair_deletes_unsupported_reference_only_inline_target_without_llm
```

Expected: 4 passed.

- [ ] **Step 7: Run the guardrail module**

Run:

```bash
pytest -q tests/agents/deep_interpreter/test_report_guardrail_middleware.py
```

Expected: all tests pass with only pre-existing warnings.

- [ ] **Step 8: Self-review the diff**

Confirm every new production line implements one selected-policy condition,
the lower-count branch is unchanged, and no repair/budget/runtime code changed.

- [ ] **Step 9: Commit with Lore metadata**

Run:

```bash
git add \
  src/agents/deep_interpreter/report_guardrails.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
git diff --cached --check
git commit \
  -m "Preserve disjoint repairable inline progress" \
  -m "Constraint: Admit only equal non-zero semantic hard-error counts with exclusively repairable inline codes and disjoint exact claim keys." \
  -m "Rejected: Restore count-increasing or generic semantic frontier movement | Pair-15 proved those candidates unsafe." \
  -m "Confidence: high" \
  -m "Scope-risk: narrow" \
  -m "Directive: Keep count increase, overlap, mixed errors, and phase regression fail-closed." \
  -m "Tested: Pair-16 exact RED/GREEN chain, progress truth table, grouped repair invariants, and guardrail module." \
  -m "Not-tested: Pair-16 isolated finalizer replay remains a post-review gate."
```

### Task 3: Run combined regression and static verification

**Files:**
- No tracked file changes expected.
- Write the verification transcript only to this plan's SDD report file.

**Interfaces:**
- Consumes: Task 1 and Task 2 commits.
- Produces: fresh evidence for final whole-branch review and the isolated replay gate.

- [ ] **Step 1: Run the exact combined regression command**

```bash
pytest -q \
  tests/scripts/test_validate_report.py \
  tests/scripts/test_repair_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py \
  tests/deep_interpreter/test_reporter_prompt_policy.py \
  tests/test_reporter.py \
  tests/test_reporter_phase45.py \
  tests/test_reporter_phase5.py \
  tests/test_sni_ablation_runner.py
```

Expected: every test passes; any failure returns to the task whose behavior it
covers with a focused RED test.

- [ ] **Step 2: Run exact static checks**

```bash
ruff check \
  scripts/validate_report.py \
  src/agents/deep_interpreter/report_guardrails.py \
  tests/scripts/test_validate_report.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
python -m py_compile \
  scripts/validate_report.py \
  src/agents/deep_interpreter/report_guardrails.py
git diff --check
```

Expected: all commands exit zero.

- [ ] **Step 3: Verify scope and history**

Run:

```bash
git status --short --branch
git log --oneline --decorate -6
git diff 3dcd928..HEAD -- \
  scripts/validate_report.py \
  tests/scripts/test_validate_report.py \
  src/agents/deep_interpreter/report_guardrails.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
```

Expected: only the four approved implementation/test files differ from
`3dcd928`, in addition to the committed superseding spec, evidence, and plan.
No new commit is made for a verification-only task.

### Task 4: Preserve grammar for a leading-PMID prose target

**Files:**
- Modify: `tests/scripts/test_repair_report.py`
- Modify: `scripts/repair_report.py:160-171`

**Interfaces:**
- Consumes: `_remove_inline_pmid(value: str, pmid: str) -> str` and the existing
  exact-target structured repair fallback in `repair_issues`.
- Produces: a leading `PMID: <id> <alphabetic prose>` target declines
  deterministic token stripping so structured delete/replace owns the whole
  target.
- Preserves: parenthetical/grouped inline removal, supported siblings,
  reference-only line deletion, headings, repair budgets, and progress policy.

- [ ] **Step 1: Add the replay-shaped failing regression**

Add beside the existing inline-PMID repair tests:

```python
def test_repair_routes_leading_pmid_prose_to_structured_target_repair(
    tmp_path: Path,
) -> None:
    for case, issue_code, pmid, target in (
        (
            "cdh1_erbb3",
            "inline_citation_overclaimed",
            "28174229",
            "PMID: 28174229 demonstrates that ErbB2 overexpression alters "
            "the proteome and phosphosignaling in mammary luminal epithelial "
            "cells, with CDH1-ERBB3 being one of the key interactions identified.",
        ),
        (
            "lrig1_erbb2",
            "inline_citation_overclaimed",
            "28174229",
            "PMID: 28174229 demonstrates that ErbB2 overexpression alters "
            "the proteome and phosphosignaling in mammary luminal epithelial "
            "cells, with LRIG1-ERBB2 being one of the key interactions identified.",
        ),
        (
            "nectin4",
            "inline_citation_unsupported",
            "39753722",
            "PMID: 39753722 reports NECTIN4 expression patterns in breast "
            "cancer progression and immune evasion contexts.",
        ),
    ):
        data_dir = tmp_path / case
        data_dir.mkdir()
        report = data_dir / "part3_final.md"
        original = f"## Evidence\nContext before. {target} Context after.\n"
        report.write_text(original, encoding="utf-8")
        trace = data_dir / "repair_trace.jsonl"
        trace.write_text("", encoding="utf-8")
        issues = _write_issues(
            data_dir,
            [
                {
                    "severity": "error",
                    "code": issue_code,
                    "file": report.name,
                    "section": "## Evidence",
                    "source_claim_index": 0,
                    "inline_pmid": pmid,
                    "value": target,
                    "target_text": target,
                }
            ],
        )
        rows = [
            {
                "file": report.name,
                "section": "## Evidence",
                "source_claim_index": 0,
                "inline_pmid": pmid,
                "status": "overclaimed",
            }
        ]
        llm = RepairDecisionLLM(action="delete", replacement_text="")

        changed = repair_report.repair_report(
            data_dir,
            issues,
            llm=llm,
            claim_validation=rows,
        )

        repaired = report.read_text(encoding="utf-8")
        assert changed == 1
        assert llm.calls == 1
        assert target not in repaired
        assert "Context before." in repaired
        assert "Context after." in repaired
        assert repair_report._markdown_headings(repaired) == ["## Evidence"]
        assert _trace_rows(trace)[-1]["path"] == "llm_delete"
```

- [ ] **Step 2: Run the exact test and observe RED**

```bash
pytest -q tests/scripts/test_repair_report.py::test_repair_routes_leading_pmid_prose_to_structured_target_repair
```

Expected: FAIL because current deterministic stripping returns success,
`llm.calls == 0`, and a subjectless `demonstrates` / `reports` fragment remains.

- [ ] **Step 3: Add the minimum shared guard**

At the start of `_remove_inline_pmid`, after defining `token`, add:

```python
    if re.match(
        rf"^\s*(?:[-*]\s+)?{token}\s+[A-Za-z]",
        value,
        flags=re.IGNORECASE,
    ):
        return value
```

Do not change either caller or the structured repair loop.

- [ ] **Step 4: Run focused GREEN and retained deterministic boundaries**

```bash
pytest -q \
  tests/scripts/test_repair_report.py::test_repair_routes_leading_pmid_prose_to_structured_target_repair \
  tests/scripts/test_repair_report.py::test_repair_removes_all_non_supported_inline_pmids_without_llm \
  tests/scripts/test_repair_report.py::test_repair_deletes_unsupported_reference_only_inline_target_without_llm \
  tests/scripts/test_repair_report.py::test_repair_removes_only_unsupported_inline_pmid_when_sibling_supports \
  tests/scripts/test_repair_report.py::test_repair_removes_multiple_unsupported_inline_pmids_when_sibling_supports \
  tests/scripts/test_repair_report.py::test_repair_removes_sole_failed_prose_inline_pmid_without_llm
```

Expected: 6 passed.

- [ ] **Step 5: Run repair and combined regression suites**

```bash
pytest -q tests/scripts/test_repair_report.py
pytest -q \
  tests/scripts/test_validate_report.py \
  tests/scripts/test_repair_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py \
  tests/deep_interpreter/test_reporter_prompt_policy.py \
  tests/test_reporter.py \
  tests/test_reporter_phase45.py \
  tests/test_reporter_phase5.py \
  tests/test_sni_ablation_runner.py
```

Expected: repair module and combined suite pass; the combined total increases
from 336 to 337.

- [ ] **Step 6: Run static checks and commit with Lore metadata**

```bash
ruff check scripts/repair_report.py tests/scripts/test_repair_report.py
python -m py_compile scripts/repair_report.py
git diff --check
git add scripts/repair_report.py tests/scripts/test_repair_report.py
git diff --cached --check
git commit \
  -m "Preserve grammar when an inline PMID leads prose" \
  -m "Constraint: Route only leading-PMID alphabetic prose to existing structured exact-target repair; preserve all other deterministic citation paths." \
  -m "Rejected: Strip the PMID token and normalize whitespace | That leaves a subjectless demonstrates/reports fragment." \
  -m "Confidence: high" \
  -m "Scope-risk: narrow" \
  -m "Directive: Keep grouped, supported-sibling, parenthetical, and reference-only citation repair deterministic." \
  -m "Tested: Replay-shaped RED/GREEN, retained deterministic citation boundaries, repair module, combined suite, Ruff, py_compile, and diff check." \
  -m "Not-tested: Pair-15 Replay A rerun remains the launch gate."
```

## Controller Gates After SDD

After all four tasks pass their task-scoped spec and quality reviews, run the
Subagent-Driven final whole-branch review. Fix any Critical or Important
finding through the required single fix/re-review loop before continuing.

The leader then executes, in order, the spec's two required isolated replays:

1. Pair-15-R2 no-SNI Parts on a fresh copy, seeded only with the prior replay's
   production Claim-RAG checkpoint to avoid repeating judgments. Require zero
   hard errors, only initial-hard-target citation repairs, no dangling prose
   fragment, stable headings, and unchanged original hashes. Inspect the live
   replay-root `part1_final.md`, `part2_final.md`, and especially
   `part3_final.md`; do not use copied `after/` files or `diffs/*.diff`, which
   predate the live guardrail mutation.
2. Pair-16 SNI finalizer on a fresh fixed-collection copy, requiring preserved
   reference deletion, accepted disjoint `1 -> 1` progress, subsequent repair,
   zero final hard errors, validation/targets/HTML, and unchanged Part/source
   hashes.

Either replay failure returns to root-cause diagnosis and blocks the full run.
Pair-16 Reporter-only replay remains conditional on an unresolved Reporter
integration question.

Only after both required replays and independent final code review pass may the
leader launch a new tmux sequence root with:

`Pair-15-R2 -> Pair-16 -> Pair-17 -> Pair-18 -> Pair-19 -> Pair-20`, each
`no-SNI -> SNI`, fixed model/ports/collection/timeout, content-failure
continuation, service-failure stop, preserved failed artifacts, and portable
`sequence.exit_code` writing exactly as specified by the design.

## Plan Self-Review Checklist

- Spec coverage: Task 1 maps A to the exact Pair-15 test; B and C to the
  non-vacuous known-label table test for `hypothesis`, `hypothesized`, and
  `hypothesised`; and D to
  `test_flags_factor_pathway_significance_when_csv_lacks_claimed_pair`.
  Task 2 implements E-M; Task 3 proves the original code gates; Task 4 maps N
  to the prose-prefix structured fallback and O to the named deterministic
  regressions. Controller Gates cover isolated replays and the fresh sequence.
- Placeholder scan: no `TBD`, `TODO`, deferred implementation, or unstated test
  exists.
- Type consistency: tests use existing `dict[str, Any]`, `Path`, pytest, and
  guardrail signatures; no new production interface is introduced.
- Task boundaries: Pair-15, Pair-16, and post-replay grammar integrity can be
  independently rejected, tested, reviewed, and committed; combined
  verification changes no production file.

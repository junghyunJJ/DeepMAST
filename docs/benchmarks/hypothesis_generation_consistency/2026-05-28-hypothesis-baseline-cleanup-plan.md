# Hypothesis Baseline Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make hypothesis generation outputs clean enough for consistency benchmarking by deterministically fixing gap analysis, reducing overclaiming, and preventing stale/draft artifacts from influencing runs.

**Architecture:** Keep canonicalization inside `save_hypothesis_report` so both direct saves and the legacy `save_evidence(..., "hypothesis_report.json", ...)` wrapper get the same deterministic behavior. Keep benchmark isolation in the benchmark runner cleanup/validation layer, and keep overclaim control prompt-level because the current codebase does not have a semantic claim verifier. Add tests before implementation for each behavior.

**Tech Stack:** Python 3.12, pytest, LangChain/LangGraph middleware, DeepMAST drug-target subagent tools.

---

## File Structure

- Modify: `src/agents/drug_target/tools/evidence_loader.py`
  - Extend deterministic hypothesis diagnostics so `gap_analysis` is computed from eligible evidence and actual citations, not from LLM-provided fields.
- Modify: `src/agents/drug_target/tools/hypothesis_schema.py`
  - Persist deterministic `gap_analysis` from diagnostics before writing `evidence/hypothesis_report.json`.
- Modify: `tests/agents/drug_target/test_hypothesis_schema.py`
  - Add regression tests for cited files not appearing as orphan files and stale LLM gap fields being overwritten.
- Modify: `src/agents/drug_target/subagents/prompts.py`
  - Add evidence-vs-inference wording rules to reduce unsupported mechanism/therapy overclaims.
- Modify: `tests/agents/drug_target/test_hypothesis_writer_prompt_save_contract.py`
  - Add prompt contract tests for overclaim mitigation.
- Modify: `src/agents/deep_interpreter/middleware/write_file_guard.py`
  - Block `write_file` attempts for `hypothesis_report_draft.json` and other `hypothesis_report*.json` variants.
- Modify: `tests/test_write_file_guard.py`
  - Add regression coverage for blocked draft hypothesis report writes.
- Modify: `docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py`
  - Clean root-level draft/report/log artifacts and mark trials invalid if forbidden draft artifacts are produced.
- Modify: `docs/benchmarks/hypothesis_generation_consistency/analysis.py`
  - Compute pairwise consistency metrics from validation-passed runs rather than merely parse-successful runs.
- Modify: `tests/benchmarks/test_hypothesis_generation_consistency.py`
  - Add tests for cleanup, forbidden artifact validation, and validation-passed aggregation.

---

### Task 1: Deterministic Gap Analysis Recalculation

**Files:**
- Modify: `src/agents/drug_target/tools/evidence_loader.py:858-878`
- Modify: `src/agents/drug_target/tools/hypothesis_schema.py:297-315`
- Test: `tests/agents/drug_target/test_hypothesis_schema.py`

- [ ] **Step 1: Write the failing gap-analysis regression test**

Append this test to `tests/agents/drug_target/test_hypothesis_schema.py` after `test_save_hypothesis_report_canonicalizes_labels_and_refs`:

```python
def test_save_hypothesis_report_recomputes_gap_analysis_from_actual_citations(
    tmp_path: Path,
) -> None:
    data_dir = _write_hypothesis_evidence(tmp_path)
    report = _clone_report()
    report["gap_analysis"] = {
        "total_evidence_files": 99,
        "referenced_files": 1,
        "orphan_files": [
            "stage1_FN1--CD4.json",
            "stage3_CD4.json",
            "stage3_NOT_REAL.json",
        ],
    }

    result = json.loads(
        save_hypothesis_report.invoke({"data_dir": str(data_dir), "report": report})
    )

    assert result["saved"] is True, result
    saved = json.loads((data_dir / "evidence" / "hypothesis_report.json").read_text())
    assert saved["gap_analysis"] == {
        "total_evidence_files": 4,
        "referenced_files": 2,
        "orphan_files": ["stage1_FN1--SDC2.json", "stage3_FN1.json"],
    }
    cited = {
        ref
        for hyp in saved["hypotheses"]
        for ref in hyp.get("evidence_references", [])
    }
    assert not (set(saved["gap_analysis"]["orphan_files"]) & cited)
    assert saved["evidence_coverage_pct"] == 50.0
```

- [ ] **Step 2: Update the existing canonicalization assertion to the deterministic result**

In `test_save_hypothesis_report_canonicalizes_labels_and_refs`, replace:

```python
assert saved["gap_analysis"]["orphan_files"] == ["stage1_FN1--CD4.json"]
```

with:

```python
assert saved["gap_analysis"] == {
    "total_evidence_files": 4,
    "referenced_files": 2,
    "orphan_files": ["stage1_FN1--SDC2.json", "stage3_FN1.json"],
}
assert saved["evidence_coverage_pct"] == 50.0
```

- [ ] **Step 3: Run the focused test and verify it fails**

Run:

```bash
PYTHONPATH=. pytest -q tests/agents/drug_target/test_hypothesis_schema.py::test_save_hypothesis_report_recomputes_gap_analysis_from_actual_citations tests/agents/drug_target/test_hypothesis_schema.py::test_save_hypothesis_report_canonicalizes_labels_and_refs
```

Expected: FAIL because `gap_analysis` still preserves stale LLM-provided orphan/count fields.

- [ ] **Step 4: Add deterministic gap diagnostics**

In `src/agents/drug_target/tools/evidence_loader.py`, update the diagnostic dict in `_validate_hypothesis_report_topn_and_failed_pairs`:

```python
diag: dict = {
    "topn_coverage": {"covered": [], "missing": [], "coverage_pct": 100.0},
    "evidence_coverage_pct": 0.0,
    "gap_analysis": {
        "total_evidence_files": 0,
        "referenced_files": 0,
        "orphan_files": [],
    },
    "failed_pair_violations": [],
    "reject_reason": None,
}
```

Replace the existing evidence coverage block at lines 858-878 with:

```python
    # 3. Deterministic evidence coverage and gap analysis over eligible
    # hypothesis evidence only: current stage3 candidate files plus Stage 1
    # pair files that passed the filter.
    stage_files = _eligible_hypothesis_stage_files(
        evidence_dir,
        featured_genes,
        filter_results,
    )
    cited_files: set[str] = set()
    if isinstance(hypotheses, list):
        for hyp in hypotheses:
            if not isinstance(hyp, dict):
                continue
            for ref in hyp.get("evidence_references", []) or []:
                if not isinstance(ref, str):
                    continue
                token_match = re.search(
                    r"([A-Za-z0-9_.\-]+\.json)",
                    ref.replace(".json_FAILED", ".json"),
                )
                if token_match:
                    cited_files.add(token_match.group(1))

    cited_stage = cited_files & stage_files
    orphan_stage = stage_files - cited_stage
    if stage_files:
        diag["evidence_coverage_pct"] = round(
            100.0 * len(cited_stage) / len(stage_files),
            2,
        )
    diag["gap_analysis"] = {
        "total_evidence_files": len(stage_files),
        "referenced_files": len(cited_stage),
        "orphan_files": sorted(orphan_stage),
    }
```

- [ ] **Step 5: Persist deterministic gap analysis**

In `src/agents/drug_target/tools/hypothesis_schema.py`, after:

```python
canonical["evidence_coverage_pct"] = diag["evidence_coverage_pct"]
canonical["topn_coverage"] = diag["topn_coverage"]
```

add:

```python
canonical["gap_analysis"] = diag["gap_analysis"]
```

Then remove this call because deterministic recomputation replaces LLM-provided gap fields:

```python
_sanitize_gap_analysis(canonical, evidence_dir)
```

Also remove `_sanitize_gap_analysis` from the local import if it becomes unused.

- [ ] **Step 6: Run the focused test and verify it passes**

Run:

```bash
PYTHONPATH=. pytest -q tests/agents/drug_target/test_hypothesis_schema.py
```

Expected: PASS, with no orphan file that is also cited in `evidence_references`.

---

### Task 2: Prompt-Level Overclaim Mitigation

**Files:**
- Modify: `src/agents/drug_target/subagents/prompts.py:318-330`
- Test: `tests/agents/drug_target/test_hypothesis_writer_prompt_save_contract.py`

- [ ] **Step 1: Write the failing prompt contract test**

Append this test to `tests/agents/drug_target/test_hypothesis_writer_prompt_save_contract.py`:

```python
def test_hypothesis_writer_prompt_requires_evidence_vs_inference_wording() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "Evidence-vs-Inference Wording" in text
    assert "Direct evidence" in text
    assert "Hypothesis-level inference" in text
    assert "may", "could", "test whether"
    assert "Do not list anti-* antibodies" in text
    assert "validation_approach as perturbation reagents" in text
```

Immediately correct the malformed assertion before running:

```python
def test_hypothesis_writer_prompt_requires_evidence_vs_inference_wording() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "Evidence-vs-Inference Wording" in text
    assert "Direct evidence" in text
    assert "Hypothesis-level inference" in text
    assert "may`, `could`, or `test whether" in text
    assert "Do not list anti-* antibodies" in text
    assert "validation_approach as perturbation reagents" in text
```

- [ ] **Step 2: Run the focused prompt test and verify it fails**

Run:

```bash
PYTHONPATH=. pytest -q tests/agents/drug_target/test_hypothesis_writer_prompt_save_contract.py
```

Expected: FAIL because the prompt does not yet contain the evidence-vs-inference contract.

- [ ] **Step 3: Add the overclaim mitigation prompt section**

In `src/agents/drug_target/subagents/prompts.py`, after the Stage 1 eligibility hard rules block ending near:

```text
The save_hypothesis_report validator checks both citations and hypothesis text.
It rejects failed pair references and failed pair primary claims even if the
failed pair file is not cited directly.
```

insert:

```text
### Evidence-vs-Inference Wording (ANTI-OVERCLAIM)

Each hypothesis must clearly separate direct evidence from hypothesis-level
inference:

- **Direct evidence**: only state that the cited files show a value, association,
  pass/fail status, target profile, drug match, or named relationship when that
  fact is actually present in `evidence_references`.
- **Hypothesis-level inference**: mechanisms that are biologically plausible but
  not directly present in the cited files must be phrased with `may`, `could`,
  `suggests`, or `test whether`. Do not write these as established facts.
- Avoid unsupported therapeutic certainty. Do not claim a combination "provides
  therapeutic benefit", "restores fibrosis resolution", or "drives disease"
  unless the cited evidence directly supports that claim. Prefer testable
  wording such as "may reduce", "could alter", or "will test whether".
- Do not list anti-* antibodies, immune modulators, or experimental blockers
  under `biological_entities.drugs` unless the exact agent appears in
  `known_drugs.json`, `resolved_drugs.json`, or a cited `stage3_<GENE>.json`.
  If the agent is only an experimental perturbation, mention it only in
  `validation_approach as perturbation reagents`.
- Genes or pathways not present in cited evidence may appear as mechanistic
  context, but the hypothesis must not imply that the current evidence directly
  validates them.
```

- [ ] **Step 4: Run prompt tests**

Run:

```bash
PYTHONPATH=. pytest -q tests/agents/drug_target/test_hypothesis_writer_prompt_save_contract.py tests/test_drug_target.py::TestDrugTargetAgent::test_hypothesis_writer_prompt_contains_required_output
```

Expected: prompt contract test passes. If the second test path is not collected in this repo version, run the whole `tests/test_drug_target.py` file section that contains hypothesis prompt assertions:

```bash
PYTHONPATH=. pytest -q tests/test_drug_target.py -k hypothesis_report
```

Expected: PASS.

---

### Task 3: Block Draft Hypothesis Reports Written Via `write_file`

**Files:**
- Modify: `src/agents/deep_interpreter/middleware/write_file_guard.py:41-49`
- Test: `tests/test_write_file_guard.py`

- [ ] **Step 1: Write the failing write-file guard test**

Add this test to `tests/test_write_file_guard.py` after `test_non_write_file_tool_call_is_unchanged`:

```python
def test_write_file_blocks_hypothesis_report_draft_artifacts():
    middleware = WriteFileArgGuardMiddleware()
    req = _request(
        "write_file",
        {
            "file_path": "/hypothesis_report_draft.json",
            "content": {"hypotheses": []},
        },
    )
    called = False

    def handler(_request):
        nonlocal called
        called = True
        raise AssertionError("handler should not be called for blocked artifacts")

    result = middleware.wrap_tool_call(req, handler)

    assert called is False
    assert "write_file" in str(result.content)
    assert "save_hypothesis_report" in str(result.content)
```

- [ ] **Step 2: Run the focused guard test and verify it fails**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_write_file_guard.py::test_write_file_blocks_hypothesis_report_draft_artifacts
```

Expected: FAIL because `hypothesis_report_draft.json` currently bypasses the blocked artifact list.

- [ ] **Step 3: Update the guard implementation**

In `src/agents/deep_interpreter/middleware/write_file_guard.py`, add this import:

```python
import re
```

Replace:

```python
_BLOCKED_ARTIFACT_NAMES = ("target_assessment.json", "drug.md", "hypothesis_report.json")
```

with:

```python
_BLOCKED_ARTIFACT_NAMES = ("target_assessment.json", "drug.md")
_BLOCKED_HYPOTHESIS_REPORT_RE = re.compile(
    r"^hypothesis_report(?:[._-].*)?\.json$"
)
```

Replace the error message with:

```python
_BLOCKED_ARTIFACT_ERROR = (
    "ERROR: Do not use write_file for output artifacts. "
    "Use save_target_assessment for target_assessment.json, "
    "save_drug_md for drug.md, and "
    "save_hypothesis_report(data_dir, report) for hypothesis_report.json."
)
```

Replace `_is_blocked_artifact` with:

```python
    @classmethod
    def _is_blocked_artifact(cls, request: ToolCallRequest) -> bool:
        """Return True if write_file targets a protected output artifact."""
        tool_call = request.tool_call
        if tool_call.get("name") != "write_file":
            return False
        args = tool_call.get("args")
        if not isinstance(args, dict):
            return False
        path = str(args.get("path", "") or args.get("file_path", ""))
        name = Path(path).name
        return name in _BLOCKED_ARTIFACT_NAMES or bool(
            _BLOCKED_HYPOTHESIS_REPORT_RE.fullmatch(name)
        )
```

- [ ] **Step 4: Run guard tests**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_write_file_guard.py tests/agents/deep_interpreter/test_write_file_path_normalization.py
```

Expected: PASS.

---

### Task 4: Benchmark Cleanup for Draft and Run-Derived Artifacts

**Files:**
- Modify: `docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py:38-49`
- Test: `tests/benchmarks/test_hypothesis_generation_consistency.py:169-244`

- [ ] **Step 1: Extend cleanup tests with root-level stale artifacts**

In `test_prepare_trial_workspace_removes_prior_report_artifacts`, after writing `target_assessment.json`, add:

```python
    (source / "hypothesis_report_draft.json").write_text("{}", encoding="utf-8")
    (source / "report_data.json").write_text("{}", encoding="utf-8")
    (source / "report_validation.json").write_text("{}", encoding="utf-8")
    (source / "trace_20260528_113442.log").write_text("trace", encoding="utf-8")
    (source / "token_usage_20260528_113442.json").write_text("{}", encoding="utf-8")
```

After the existing stale artifact assertions, add:

```python
    assert not (workspace / "hypothesis_report_draft.json").exists()
    assert not (workspace / "report_data.json").exists()
    assert not (workspace / "report_validation.json").exists()
    assert not (workspace / "trace_20260528_113442.log").exists()
    assert not (workspace / "token_usage_20260528_113442.json").exists()
```

In `test_clean_hypothesis_benchmark_workspace_reports_removed_artifacts`, after writing `drug.md`, add:

```python
    (workspace / "hypothesis_report_draft.json").write_text("{}", encoding="utf-8")
    (workspace / "report_data.json").write_text("{}", encoding="utf-8")
    (workspace / "report_validation.json").write_text("{}", encoding="utf-8")
    (workspace / "trace_20260528_113442.log").write_text("trace", encoding="utf-8")
    (workspace / "token_usage_20260528_113442.json").write_text("{}", encoding="utf-8")
```

Update the exact `removed` assertion to:

```python
    assert removed == [
        "drug.md",
        "drug_report.html",
        "drug_report_reference_card.json",
        "report_expansions.json",
        "target_assessment.json",
        "hypothesis_report_draft.json",
        "report_data.json",
        "report_validation.json",
        "evidence/hypothesis_report.json",
        "conversation_history/",
        "large_tool_results/",
        "token_usage_20260528_113442.json",
        "trace_20260528_113442.log",
    ]
```

If this test does not create all listed files, either create the missing files in the test or assert a smaller exact list matching the files created by that test. Do not use a loose subset assertion for cleanup ordering because the return value is used as audit output.

- [ ] **Step 2: Run cleanup tests and verify they fail**

Run:

```bash
PYTHONPATH=. pytest -q tests/benchmarks/test_hypothesis_generation_consistency.py::test_prepare_trial_workspace_removes_prior_report_artifacts tests/benchmarks/test_hypothesis_generation_consistency.py::test_clean_hypothesis_benchmark_workspace_reports_removed_artifacts
```

Expected: FAIL because the new root-level artifacts and globbed logs are not cleaned.

- [ ] **Step 3: Add cleanup files and glob cleanup**

In `docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py`, update constants:

```python
HYPOTHESIS_BENCHMARK_CLEAN_FILES = (
    "drug.md",
    "drug_report.html",
    "drug_report_reference_card.json",
    "report_expansions.json",
    "target_assessment.json",
    "hypothesis_report_draft.json",
    "report_data.json",
    "report_validation.json",
    "evidence/hypothesis_report.json",
)
HYPOTHESIS_BENCHMARK_CLEAN_DIRS = (
    "conversation_history",
    "large_tool_results",
)
HYPOTHESIS_BENCHMARK_CLEAN_GLOBS = (
    "token_usage_*.json",
    "trace_*.log",
)
```

Then extend `clean_hypothesis_benchmark_workspace` after directory cleanup:

```python
    for pattern in HYPOTHESIS_BENCHMARK_CLEAN_GLOBS:
        for path in sorted(workspace.glob(pattern)):
            if path.is_file():
                path.unlink()
                removed.append(path.name)
            elif path.is_dir():
                shutil.rmtree(path)
                removed.append(f"{path.name}/")
```

- [ ] **Step 4: Run cleanup tests**

Run:

```bash
PYTHONPATH=. pytest -q tests/benchmarks/test_hypothesis_generation_consistency.py::test_prepare_trial_workspace_removes_prior_report_artifacts tests/benchmarks/test_hypothesis_generation_consistency.py::test_clean_hypothesis_benchmark_workspace_reports_removed_artifacts
```

Expected: PASS.

---

### Task 5: Benchmark Validation Fails on Forbidden Draft Artifacts

**Files:**
- Modify: `docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py:163-255`
- Test: `tests/benchmarks/test_hypothesis_generation_consistency.py`

- [ ] **Step 1: Add a failing validation test**

Append this test near the other `validate_trial_output` tests:

```python
def test_validate_trial_output_marks_forbidden_draft_artifact_invalid(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    evidence = workspace / "evidence"
    evidence.mkdir(parents=True)
    (workspace / "hypothesis_report_draft.json").write_text("{}", encoding="utf-8")
    (evidence / "hypothesis_report.json").write_text(
        json.dumps(_report_one()),
        encoding="utf-8",
    )

    row = validate_trial_output("run_01", workspace, elapsed_s=1.25, error=None)

    assert row["success"] is True
    assert row["validation_passed"] is False
    assert row["forbidden_artifacts"] == ["hypothesis_report_draft.json"]
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
PYTHONPATH=. pytest -q tests/benchmarks/test_hypothesis_generation_consistency.py::test_validate_trial_output_marks_forbidden_draft_artifact_invalid
```

Expected: FAIL because `validate_trial_output` does not currently inspect forbidden artifacts.

- [ ] **Step 3: Add forbidden artifact detection**

In `docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py`, add this helper after `clean_hypothesis_benchmark_workspace`:

```python
FORBIDDEN_HYPOTHESIS_ARTIFACT_GLOBS = (
    "hypothesis_report*.json",
)


def find_forbidden_hypothesis_artifacts(workspace: Path) -> list[str]:
    """Return root-level hypothesis report artifacts outside evidence/."""
    found: set[str] = set()
    for pattern in FORBIDDEN_HYPOTHESIS_ARTIFACT_GLOBS:
        for path in workspace.glob(pattern):
            if path.is_file() and path.name != "hypothesis_report.json":
                found.add(path.name)
    return sorted(found)
```

At the start of `validate_trial_output`, after `report_path` is assigned, add:

```python
    forbidden_artifacts = find_forbidden_hypothesis_artifacts(workspace)
```

Include `"forbidden_artifacts": forbidden_artifacts` in every returned row from `validate_trial_output`.

In the final `validation_passed` expression, add:

```python
        and not forbidden_artifacts
```

- [ ] **Step 4: Run benchmark validation tests**

Run:

```bash
PYTHONPATH=. pytest -q tests/benchmarks/test_hypothesis_generation_consistency.py -k "validate_trial_output or forbidden"
```

Expected: PASS.

---

### Task 6: Aggregate Consistency Metrics from Validation-Passed Runs

**Files:**
- Modify: `docs/benchmarks/hypothesis_generation_consistency/analysis.py:85-120`
- Test: `tests/benchmarks/test_hypothesis_generation_consistency.py`

- [ ] **Step 1: Add a failing aggregation test**

Append this test after `test_aggregate_trial_rows_handles_failed_row_without_summary`:

```python
def test_aggregate_trial_rows_pairwise_metrics_use_validation_passed_runs() -> None:
    invalid_report = _report_two()
    invalid_report["hypotheses"][0]["title"] = "invalid divergent title"
    rows = [
        {
            "run_id": "run_valid",
            "success": True,
            "validation_passed": True,
            "report_summary": summarize_report(_report_one()),
        },
        {
            "run_id": "run_invalid",
            "success": True,
            "validation_passed": False,
            "report_summary": summarize_report(invalid_report),
        },
    ]

    aggregate = aggregate_trial_rows(rows)

    assert aggregate["successful_runs"] == 2
    assert aggregate["validation_passed_runs"] == 1
    assert aggregate["hypothesis_count_values"] == [2]
    assert aggregate["mean_pairwise_title_similarity"] is None
    assert aggregate["mean_pairwise_core_claim_similarity"] is None
```

- [ ] **Step 2: Run the focused aggregation test and verify it fails**

Run:

```bash
PYTHONPATH=. pytest -q tests/benchmarks/test_hypothesis_generation_consistency.py::test_aggregate_trial_rows_pairwise_metrics_use_validation_passed_runs
```

Expected: FAIL because summaries currently include all successful rows.

- [ ] **Step 3: Filter summaries by validation status**

In `docs/benchmarks/hypothesis_generation_consistency/analysis.py`, replace:

```python
def _successful_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row["report_summary"]
        for row in rows
        if row.get("success") and isinstance(row.get("report_summary"), dict)
    ]
```

with:

```python
def _validation_passed_summaries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row["report_summary"]
        for row in rows
        if row.get("validation_passed") and isinstance(row.get("report_summary"), dict)
    ]
```

Then in `aggregate_trial_rows`, replace:

```python
summaries = _successful_summaries(rows)
```

with:

```python
summaries = _validation_passed_summaries(rows)
```

- [ ] **Step 4: Run aggregation tests**

Run:

```bash
PYTHONPATH=. pytest -q tests/benchmarks/test_hypothesis_generation_consistency.py -k aggregate
```

Expected: PASS.

---

### Task 7: Final Verification

**Files:**
- No code changes in this task.

- [ ] **Step 1: Run the focused regression suite**

Run:

```bash
PYTHONPATH=. pytest -q \
  tests/agents/drug_target/test_hypothesis_schema.py \
  tests/agents/drug_target/test_hypothesis_writer_prompt_save_contract.py \
  tests/test_write_file_guard.py \
  tests/agents/deep_interpreter/test_write_file_path_normalization.py \
  tests/benchmarks/test_hypothesis_generation_consistency.py
```

Expected: PASS, with the existing skipped tests still skipped only for missing optional benchmark source data.

- [ ] **Step 2: Smoke-check the current `res_ipf_ollama` report without editing it**

Run:

```bash
PYTHONPATH=. python - <<'PY'
import json
from pathlib import Path

report = json.loads(Path("res_ipf_ollama/evidence/hypothesis_report.json").read_text())
refs = {
    ref
    for hyp in report.get("hypotheses", [])
    for ref in hyp.get("evidence_references", [])
}
orphans = set(report.get("gap_analysis", {}).get("orphan_files", []))
print("orphan_but_referenced", sorted(refs & orphans))
print("schema_version", report.get("schema_version"))
print("hypotheses", len(report.get("hypotheses", [])))
PY
```

Expected before regenerating the report: it may still print `stage1_ICAM1--PECAM1.json` because this command reads the old artifact. That is acceptable at this stage; the code fix affects newly saved reports.

- [ ] **Step 3: Verify canonical save behavior on a temporary copy**

Run:

```bash
tmpdir="$(mktemp -d)"
cp -R res_ipf_ollama/evidence "$tmpdir/evidence"
PYTHONPATH=. python - <<'PY' "$tmpdir"
import json
import sys
from pathlib import Path
from src.agents.drug_target.tools.hypothesis_schema import persist_hypothesis_report

data_dir = Path(sys.argv[1])
report_path = data_dir / "evidence" / "hypothesis_report.json"
report = json.loads(report_path.read_text())
result = persist_hypothesis_report(data_dir, report)
print(json.dumps(result, indent=2))
saved = json.loads(report_path.read_text())
refs = {
    ref
    for hyp in saved.get("hypotheses", [])
    for ref in hyp.get("evidence_references", [])
}
orphans = set(saved.get("gap_analysis", {}).get("orphan_files", []))
print("orphan_but_referenced", sorted(refs & orphans))
print("gap_analysis", saved.get("gap_analysis"))
PY
```

Expected: `saved` is true, `orphan_but_referenced []`, and `gap_analysis.referenced_files` matches the number of eligible cited evidence files.

- [ ] **Step 4: Review the diff**

Run:

```bash
git diff -- \
  src/agents/drug_target/tools/evidence_loader.py \
  src/agents/drug_target/tools/hypothesis_schema.py \
  src/agents/drug_target/subagents/prompts.py \
  src/agents/deep_interpreter/middleware/write_file_guard.py \
  docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py \
  docs/benchmarks/hypothesis_generation_consistency/analysis.py \
  tests/agents/drug_target/test_hypothesis_schema.py \
  tests/agents/drug_target/test_hypothesis_writer_prompt_save_contract.py \
  tests/test_write_file_guard.py \
  tests/benchmarks/test_hypothesis_generation_consistency.py
```

Expected: diff is limited to deterministic canonicalization, prompt wording, artifact cleanup/validation, and matching tests. No generated benchmark output files should be edited.

---

## Self-Review

**Spec coverage:**  
- `stage1_ICAM1--PECAM1.json` coverage/orphan inconsistency is handled by Task 1.  
- Overclaim mitigation is handled by Task 2.  
- `hypothesis_report_draft.json` and stale artifact influence are handled by Tasks 3-5.  
- Benchmark consistency metrics only using valid outputs is handled by Task 6.  
- Verification is handled by Task 7.

**Placeholder scan:**  
No `TBD`, `TODO`, “similar to”, or unspecified implementation steps remain. Each code-changing task includes exact file paths, code snippets, commands, and expected results.

**Type consistency:**  
New helper/function names are consistent across tasks: `find_forbidden_hypothesis_artifacts`, `FORBIDDEN_HYPOTHESIS_ARTIFACT_GLOBS`, `_validation_passed_summaries`, and `diag["gap_analysis"]`.


# Hypothesis Benchmark Cleanup And Save Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove stale `large_tool_results/` from isolated benchmark workspaces and make the hypothesis writer prompt consistently prefer `save_hypothesis_report`.

**Architecture:** Keep the benchmark change inside the existing workspace cleanup helper so every trial copy gets the same artifact hygiene. Keep the prompt change text-only and narrow: `save_hypothesis_report` is the canonical persistence path, while `save_evidence(..., "hypothesis_report.json", ...)` remains a clearly labeled compatibility fallback only at the final save step.

**Tech Stack:** Python 3.11, pytest, LangChain tools, DeepAgents, local markdown prompt strings.

---

## File Structure

- Modify: `docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py`
  - Add `large_tool_results` to `HYPOTHESIS_BENCHMARK_CLEAN_DIRS`.
- Modify: `tests/benchmarks/test_hypothesis_generation_consistency.py`
  - Extend existing cleanup tests so copied `large_tool_results/` is removed and reported.
- Modify: `src/agents/drug_target/subagents/prompts.py`
  - Update only `HYPOTHESIS_WRITER_PROMPT` save instructions.
- Create: `tests/agents/drug_target/test_hypothesis_writer_prompt_save_contract.py`
  - Add deterministic prompt-contract tests that prevent reintroducing mixed primary save guidance.

---

### Task 1: Benchmark Workspace Cleanup For `large_tool_results/`

**Files:**
- Modify: `tests/benchmarks/test_hypothesis_generation_consistency.py`
- Modify: `docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py`

- [ ] **Step 1: Write the failing cleanup test**

In `tests/benchmarks/test_hypothesis_generation_consistency.py`, update `test_prepare_trial_workspace_removes_prior_report_artifacts` by creating `large_tool_results/` in the source and asserting it is absent in the copied workspace:

```python
def test_prepare_trial_workspace_removes_prior_report_artifacts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    evidence = source / "evidence"
    history = source / "conversation_history"
    large_tool_results = source / "large_tool_results"
    evidence.mkdir(parents=True)
    history.mkdir()
    large_tool_results.mkdir()
    (source / "lr_candidates.json").write_text("{}", encoding="utf-8")
    (source / "drug.md").write_text("stale drug report", encoding="utf-8")
    (source / "drug_report.html").write_text("<html></html>", encoding="utf-8")
    (source / "drug_report_reference_card.json").write_text("{}", encoding="utf-8")
    (source / "report_expansions.json").write_text("{}", encoding="utf-8")
    (source / "target_assessment.json").write_text("{}", encoding="utf-8")
    (history / "prior.md").write_text("old conversation", encoding="utf-8")
    (large_tool_results / "prior-tool-call").write_text(
        '{"data_dir": "res_ipf_ollama"}',
        encoding="utf-8",
    )
    (evidence / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "ICAM1"}]}),
        encoding="utf-8",
    )
    (evidence / "hypothesis_report.json").write_text(
        json.dumps({"schema_version": "hypothesis_report.v2"}),
        encoding="utf-8",
    )

    workspace = prepare_trial_workspace(
        source,
        tmp_path / "workspaces",
        "run_01",
        force=True,
    )

    assert (workspace / "lr_candidates.json").exists()
    assert (workspace / "evidence" / "assessment_results.json").exists()
    assert not (workspace / "drug.md").exists()
    assert not (workspace / "drug_report.html").exists()
    assert not (workspace / "drug_report_reference_card.json").exists()
    assert not (workspace / "report_expansions.json").exists()
    assert not (workspace / "target_assessment.json").exists()
    assert not (workspace / "conversation_history").exists()
    assert not (workspace / "large_tool_results").exists()
    assert not (workspace / "evidence" / "hypothesis_report.json").exists()
```

Also update `test_clean_hypothesis_benchmark_workspace_reports_removed_artifacts` to assert the helper reports the removed directory:

```python
def test_clean_hypothesis_benchmark_workspace_reports_removed_artifacts(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "evidence").mkdir(parents=True)
    (workspace / "large_tool_results").mkdir()
    (workspace / "drug.md").write_text("stale", encoding="utf-8")
    (workspace / "large_tool_results" / "old-tool-result").write_text(
        "stale payload",
        encoding="utf-8",
    )
    (workspace / "evidence" / "hypothesis_report.json").write_text(
        "{}",
        encoding="utf-8",
    )

    removed = clean_hypothesis_benchmark_workspace(workspace)

    assert removed == [
        "drug.md",
        "evidence/hypothesis_report.json",
        "large_tool_results/",
    ]
    assert not (workspace / "drug.md").exists()
    assert not (workspace / "large_tool_results").exists()
    assert not (workspace / "evidence" / "hypothesis_report.json").exists()
```

- [ ] **Step 2: Run the targeted tests to verify RED**

Run:

```bash
pytest -q tests/benchmarks/test_hypothesis_generation_consistency.py::test_prepare_trial_workspace_removes_prior_report_artifacts tests/benchmarks/test_hypothesis_generation_consistency.py::test_clean_hypothesis_benchmark_workspace_reports_removed_artifacts
```

Expected: fail because `large_tool_results/` is still copied and not reported in `removed`.

- [ ] **Step 3: Implement the minimal cleanup change**

In `docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py`, change:

```python
HYPOTHESIS_BENCHMARK_CLEAN_DIRS = ("conversation_history",)
```

to:

```python
HYPOTHESIS_BENCHMARK_CLEAN_DIRS = (
    "conversation_history",
    "large_tool_results",
)
```

- [ ] **Step 4: Run the cleanup tests to verify GREEN**

Run:

```bash
pytest -q tests/benchmarks/test_hypothesis_generation_consistency.py::test_prepare_trial_workspace_removes_prior_report_artifacts tests/benchmarks/test_hypothesis_generation_consistency.py::test_clean_hypothesis_benchmark_workspace_reports_removed_artifacts
```

Expected: both tests pass.

---

### Task 2: Hypothesis Writer Save Contract Prompt

**Files:**
- Create: `tests/agents/drug_target/test_hypothesis_writer_prompt_save_contract.py`
- Modify: `src/agents/drug_target/subagents/prompts.py`

- [ ] **Step 1: Write prompt-contract tests**

Create `tests/agents/drug_target/test_hypothesis_writer_prompt_save_contract.py`:

```python
from src.agents.drug_target.subagents import prompts


def test_hypothesis_writer_file_access_rules_name_save_hypothesis_report_as_primary() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT
    file_rules = text.split("## Execution Discipline", 1)[0]

    assert "ALWAYS use `save_hypothesis_report(data_dir=data_dir, report=report)`" in file_rules
    assert "NEVER use `write_file`" in file_rules
    assert "`save_evidence(data_dir, filename, data)`" not in file_rules


def test_hypothesis_writer_final_save_step_marks_save_evidence_as_fallback_only() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT
    final_save = text.split("### Phase 5: Save Report", 1)[1]

    assert "`save_hypothesis_report(data_dir=data_dir, report=report)`" in final_save
    assert "Compatibility fallback only" in final_save
    assert "`save_evidence(data_dir=data_dir, filename=\"hypothesis_report.json\", data=report)`" in final_save
    assert final_save.index("`save_hypothesis_report(data_dir=data_dir, report=report)`") < final_save.index(
        "Compatibility fallback only"
    )
```

- [ ] **Step 2: Run the prompt tests to verify RED**

Run:

```bash
pytest -q tests/agents/drug_target/test_hypothesis_writer_prompt_save_contract.py
```

Expected: fail because the current file-access rules still say `save_evidence(data_dir, filename, data)` is the general save path.

- [ ] **Step 3: Update the file-access rules**

In `src/agents/drug_target/subagents/prompts.py`, replace the `HYPOTHESIS_WRITER_PROMPT` file-access rules at the top with:

```text
## CRITICAL: File Access Rules
- NEVER use `read_file` — it accesses real filesystem and will return "not found" for virtual files
- NEVER use `write_file` — use the dedicated `save_hypothesis_report(data_dir=data_dir, report=report)` tool for the final hypothesis artifact
- NEVER use `ls` to check if files exist — ls shows virtual filesystem which may include stale files
- ALWAYS use `load_evidence_files(data_dir, scope="hypothesis")` to read evidence data
- ALWAYS use `save_hypothesis_report(data_dir=data_dir, report=report)` to save the final `hypothesis_report.json`
```

- [ ] **Step 4: Update the final save example**

In the same prompt, replace the Phase 5 JSON example intro:

```text
Save the hypothesis report as JSON:
```

and the following `save_evidence(...)` code fence with:

```text
Build `report` as this JSON-compatible object, then pass it to:
`save_hypothesis_report(data_dir=data_dir, report=report)`

Required object shape:
```

Keep the example object body unchanged, but remove the wrapping `save_evidence(data_dir, "hypothesis_report.json", ... )` call so the sample does not teach the fallback path as primary.

- [ ] **Step 5: Run the prompt tests to verify GREEN**

Run:

```bash
pytest -q tests/agents/drug_target/test_hypothesis_writer_prompt_save_contract.py
```

Expected: both tests pass.

---

### Task 3: Regression Verification

**Files:**
- No additional code changes.

- [ ] **Step 1: Run benchmark tests**

Run:

```bash
pytest -q tests/benchmarks/test_hypothesis_generation_consistency.py
```

Expected: all tests pass.

- [ ] **Step 2: Run prompt-related tests**

Run:

```bash
pytest -q tests/agents/drug_target/test_hypothesis_writer_prompt_save_contract.py tests/agents/drug_target/test_prompts_reflection_guidance.py tests/agents/drug_target/test_subagent_prompts_cleanup.py
```

Expected: tests pass, with the existing strict xfail in `test_subagent_prompts_cleanup.py` still reported as xfailed.

- [ ] **Step 3: Run syntax checks**

Run:

```bash
python -m py_compile docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py tests/benchmarks/test_hypothesis_generation_consistency.py tests/agents/drug_target/test_hypothesis_writer_prompt_save_contract.py src/agents/drug_target/subagents/prompts.py
```

Expected: command exits with status 0.

- [ ] **Step 4: Clean generated bytecode and inspect status**

Run:

```bash
rm -rf docs/benchmarks/hypothesis_generation_consistency/__pycache__ tests/benchmarks/__pycache__ tests/agents/drug_target/__pycache__ src/agents/drug_target/subagents/__pycache__
git status --short
```

Expected: only the planned source/test/plan files are modified or created.

---

## Self-Review

**Spec coverage:** The plan covers exactly the two requested changes: `large_tool_results/` cleanup and hypothesis writer save-instruction cleanup.

**Placeholder scan:** No implementation step uses TBD/TODO/fill-in language. Every code-edit step includes the exact target file and replacement content.

**Type consistency:** The tests reference existing `prompts.HYPOTHESIS_WRITER_PROMPT`, `prepare_trial_workspace`, and `clean_hypothesis_benchmark_workspace` names already present in the codebase.

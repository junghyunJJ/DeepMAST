# Deterministic-First Atomic Report Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Parts and synthesis repair target exact Markdown units, defer agentic RAG until deterministic hard errors are zero, and retain only candidates that reduce errors within the active phase or safely advance from deterministic to semantic validation.

**Architecture:** Extend the existing claim-window locator so Markdown table rows are atomic targets. Keep the current validators, structured `replace|delete` patcher, and bounded loops, but reorder validation into cheap deterministic then semantic RAG phases and treat every repair mutation as tentative until phase-aware progress is proven.

**Tech Stack:** Python 3.12, pytest, existing Pydantic/LangChain structured repair, Ollama `qwen3.5:122b`, SGCP-RAG, existing BC pair runner.

**Spec:** `docs/superpowers/specs/2026-08-21-deterministic-first-atomic-report-repair-design.md`

## Global Constraints

- Apply deterministic-first ordering to both Parts and synthesis.
- Keep exact target splicing and structured `RepairDecision(action="replace"|"delete")` unchanged.
- Accept deterministic same-phase repair candidates only when retained hard-error count strictly decreases; accept semantic same-phase candidates when the count decreases or when equal-count old and candidate error-key sets are non-empty and disjoint; accept deterministic-to-semantic phase transition and reject semantic-to-deterministic regression.
- Restore every scoped Markdown file after a no-progress candidate.
- Count only retained mutations in `changed_sections` and `changed_claims`.
- Record deterministic and semantic initial hard-error counts separately and keep their sum as `initial_error_count`.
- Preserve the three regular repair attempts and the bounded newly-surfaced terminal repair.
- Do not weaken validators, hard-code phrase replacements, or skip Claim-RAG.
- Add no dependency, Markdown framework, repair framework, or runner resume subsystem.
- Preserve Markdown heading level and position, existing PMIDs, unrelated table rows, and source artifacts. Validator-owned semantic heading repair may change only exact targeted H2-H6 heading text; validator-owned synthesis title repair remains the sole level change and may promote only the first H2-H6 marker to H1 without changing its text.
- Use ports 4000/6000, API 8883, model `qwen3.5:122b`, fixed collection UUID `a208e916-bd32-405a-9eee-de4cd82b2a3b`, 100 documents, and 1,553 chunks for live verification.
- Run pair 05 globally serial, no-SNI first; SNI starts only after no-SNI passes.
- Follow RED → GREEN TDD and Lore commit trailers.

---

### Task 1: Make Markdown table rows atomic validator targets

**Files:**
- Modify: `scripts/validate_report.py:269-294`
- Test: `tests/scripts/test_validate_report.py`
- Test: `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`
- Add to first commit: `docs/superpowers/specs/2026-08-21-deterministic-first-atomic-report-repair-design.md`
- Add to first commit: `docs/superpowers/plans/2026-08-21-deterministic-first-atomic-report-repair.md`

**Interfaces:**
- Consumes: `_claim_windows(text: str) -> list[str]`.
- Produces: the same signature, with each non-separator Markdown table row emitted as one window.
- Preserves: sentence splitting for prose, heading/list handling, and Claim-RAG's existing table-row exclusion.

- [ ] **Step 1: Write the RED unit test for table row windows**

Add to `tests/scripts/test_validate_report.py`:

```python
def test_claim_windows_treats_markdown_table_rows_as_atomic_claims() -> None:
    header = "| Theme | Strength | Supporting Evidence |"
    safe_row = "| Spatial Association | Strong | Factor3 loadings exceed 0.5 |"
    unsafe_row = (
        "| Tumor-Vascular Spatial Association | Strong | "
        "Spatial plots confirm epithelial-vascular co-localization. "
        "Moran's R = 0.4767 |"
    )
    text = "\n".join(
        [
            "## Emergent Themes Summary",
            "",
            header,
            "|---|---|---|",
            safe_row,
            unsafe_row,
        ]
    )

    windows = validate_report._claim_windows(text)

    assert header in windows
    assert safe_row in windows
    assert unsafe_row in windows
    assert "|---|---|---|" not in windows
    assert not any(safe_row in window and unsafe_row in window for window in windows)
```

- [ ] **Step 2: Write the RED integration test for exact synthesis target locality**

Add to `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`:

```python
def test_synthesis_table_overclaim_targets_only_the_offending_row(tmp_path: Path) -> None:
    from src.agents.deep_interpreter import report_guardrails

    safe_row = "| Spatial Association | Strong | Factor3 loadings exceed 0.5 |"
    unsafe_row = (
        "| Tumor-Vascular Spatial Association | Strong | "
        "Spatial plots confirm epithelial-vascular co-localization. "
        "Moran's R = 0.4767 |"
    )
    (tmp_path / "papers.json").write_text('{"papers": []}', encoding="utf-8")
    (tmp_path / "synthesis.md").write_text(
        "## Emergent Themes Summary\n\n"
        "| Theme | Strength | Supporting Evidence |\n"
        "|---|---|---|\n"
        f"{safe_row}\n"
        f"{unsafe_row}\n",
        encoding="utf-8",
    )

    errors = [
        issue
        for issue in report_guardrails.validate_synthesis_report(tmp_path)
        if issue["severity"] == "error"
    ]

    assert len(errors) == 1
    assert errors[0]["code"] == "unsupported_synthesis_overclaim"
    assert errors[0]["target_text"] == unsafe_row
    assert safe_row not in errors[0]["target_text"]
```

- [ ] **Step 3: Run both tests and verify RED**

Run:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/scripts/test_validate_report.py::test_claim_windows_treats_markdown_table_rows_as_atomic_claims \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_table_overclaim_targets_only_the_offending_row
```

Expected: both tests fail because the table header, separator, and data rows are currently merged into one paragraph window.

- [ ] **Step 4: Implement table-row locality in `_claim_windows`**

Add near the other regex constants in `scripts/validate_report.py`:

```python
MARKDOWN_TABLE_SEPARATOR_RE = re.compile(
    r"^\|(?:\s*:?-+:?\s*\|)+$"
)
```

Change `chunks` from `list[str]` to `list[tuple[str, bool]]`, where the boolean
marks a chunk that must bypass sentence splitting. `flush_paragraph()` appends
`(paragraph_text, False)` and the existing heading/list branch appends
`(line, False)`. Insert this branch after blank-line handling and before
heading/list handling:

```python
        if line.startswith("|") and line.endswith("|"):
            flush_paragraph()
            if not MARKDOWN_TABLE_SEPARATOR_RE.fullmatch(line):
                chunks.append((line, True))
            continue
```

Replace the final chunk expansion with:

```python
    windows: list[str] = []
    for chunk, atomic in chunks:
        if atomic:
            windows.append(chunk)
            continue
        windows.extend(
            part.strip()
            for part in re.split(r"(?<=[.!?])(?:[ \t]+|\n+)(?=\S)", chunk)
            if part.strip()
        )
    return windows
```

Do not import or duplicate `claim_rag_validation.MARKDOWN_TABLE_RE`; the dependency direction remains `claim_rag_validation → validate_report`.

- [ ] **Step 5: Run focused and nearby tests to GREEN**

Run:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/scripts/test_validate_report.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/agents/deep_interpreter/test_claim_rag_validation.py
uv run ruff check scripts/validate_report.py \
  tests/scripts/test_validate_report.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
uv run python -m py_compile scripts/validate_report.py \
  tests/scripts/test_validate_report.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
git diff --check
```

- [ ] **Step 6: Commit Task 1 with the plan and spec**

```bash
git add scripts/validate_report.py \
  tests/scripts/test_validate_report.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
git add -f \
  docs/superpowers/specs/2026-08-21-deterministic-first-atomic-report-repair-design.md \
  docs/superpowers/plans/2026-08-21-deterministic-first-atomic-report-repair.md
git commit -m "Keep Markdown table repairs local to one row

Constraint: Preserve existing prose claim windows and Claim-RAG table exclusion
Rejected: Markdown parser dependency | Row locality requires only existing line boundaries
Confidence: high
Scope-risk: narrow
Directive: Validator targets for tables must never include unrelated rows
Tested: validate-report, guardrail middleware, Claim-RAG validation, Ruff, py_compile, diff check
Not-tested: Live qwen3.5:122b artifact replay"
```

---

### Task 2: Defer Claim-RAG until deterministic hard errors are zero

**Files:**
- Modify: `src/agents/deep_interpreter/report_guardrails.py:165-197`
- Modify: `src/agents/deep_interpreter/report_guardrails.py:450-488`
- Test: `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`

**Interfaces:**
- Modify: `_validate_part_reports` appends `Literal["deterministic", "semantic"]` to its internal return tuple.
- Modify: `_validate_synthesis_guardrails` appends `Literal["deterministic", "semantic"]` to its internal return tuple.
- Produces: empty claim-validation fields with phase `deterministic` while local hard errors remain; semantic results with phase `semantic` after local hard errors reach zero.
- Produces: `report_validation_semantic_initial.json` and `synthesis_guardrail_semantic_initial.json` when the semantic phase is first reached.
- Produces: `deterministic_initial_error_count`, `semantic_initial_error_count`, and their sum in legacy `initial_error_count`.
- Preserves: warnings do not block semantic validation.

- [ ] **Step 1: Write the RED Parts ordering test**

Add to `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`:

```python
def test_parts_guardrail_defers_claim_rag_until_deterministic_errors_clear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)
    events: list[str] = []
    deterministic_calls = 0

    def fake_deterministic(_data_dir: Path) -> list[dict[str, str]]:
        nonlocal deterministic_calls
        deterministic_calls += 1
        events.append("deterministic")
        if deterministic_calls == 1:
            return [{"severity": "error", "code": "local_error", "file": "part1_final.md"}]
        return []

    def fake_rag(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        events.append("rag")
        return {"claims": [], "issues": []}

    def fake_repair(*_args: Any, **_kwargs: Any) -> int:
        events.append("repair")
        return 1

    monkeypatch.setattr(report_guardrails.validate_report_script, "validate_report", fake_deterministic)
    monkeypatch.setattr(report_guardrails.claim_rag_validation, "validate_claims", fake_rag)
    monkeypatch.setattr(report_guardrails.repair_report_script, "repair_report", fake_repair)

    result = report_guardrails.run_report_guardrail(tmp_path, provider="ollama")

    assert result["status"] == "passed"
    assert events == ["deterministic", "repair", "deterministic", "rag"]
```

- [ ] **Step 2: Write the RED synthesis ordering test**

Add:

```python
def test_synthesis_guardrail_defers_claim_rag_until_deterministic_errors_clear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text('{"papers": []}', encoding="utf-8")
    (tmp_path / "synthesis.md").write_text(
        "## Summary\n\nSpatial plots confirm a mechanism.\n",
        encoding="utf-8",
    )
    events: list[str] = []
    deterministic_calls = 0

    def fake_deterministic(_data_dir: Path) -> list[dict[str, str]]:
        nonlocal deterministic_calls
        deterministic_calls += 1
        events.append("deterministic")
        if deterministic_calls == 1:
            return [{"severity": "error", "code": "local_error", "file": "synthesis.md"}]
        return []

    def fake_consistency(_data_dir: Path) -> dict[str, list[dict[str, Any]]]:
        events.append("consistency")
        return {"issues": [], "results": []}

    def fake_rag(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        events.append("rag")
        return {"claims": [], "issues": []}

    def fake_repair(*_args: Any, **_kwargs: Any) -> int:
        events.append("repair")
        return 1

    monkeypatch.setattr(report_guardrails, "validate_synthesis_report", fake_deterministic)
    monkeypatch.setattr(
        report_guardrails.synthesis_consistency_validation,
        "validate_synthesis_consistency",
        fake_consistency,
    )
    monkeypatch.setattr(report_guardrails.claim_rag_validation, "validate_claims", fake_rag)
    monkeypatch.setattr(report_guardrails, "repair_synthesis_report", fake_repair)

    result = report_guardrails.run_synthesis_guardrail(tmp_path, provider="ollama")

    assert result["status"] == "passed"
    assert events == [
        "deterministic",
        "consistency",
        "repair",
        "deterministic",
        "consistency",
        "rag",
    ]
```

- [ ] **Step 3: Verify both tests fail because RAG runs in the initial pass**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_parts_guardrail_defers_claim_rag_until_deterministic_errors_clear \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_guardrail_defers_claim_rag_until_deterministic_errors_clear
```

Expected: event order contains `rag` before the first `repair`.

- [ ] **Step 4: Write the RED phase-metrics test**

Add a controller test whose fake validations return one deterministic error,
then two semantic errors, then no errors after a semantic repair:

```python
def test_report_guardrail_preserves_deterministic_and_semantic_initial_error_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)
    deterministic = {
        "severity": "error",
        "code": "local_error",
        "file": "part1_final.md",
    }
    semantic = [
        {
            "severity": "error",
            "code": "claim_rag_unsupported",
            "file": "part1_final.md",
        },
        {
            "severity": "error",
            "code": "claim_rag_overclaimed",
            "file": "part2_final.md",
        },
    ]
    validations = [
        ([deterministic], [], None, None, "deterministic"),
        (semantic, [{"status": "unsupported"}], None, None, "semantic"),
        ([], [], None, None, "semantic"),
    ]

    monkeypatch.setattr(
        report_guardrails,
        "_validate_part_reports",
        lambda *_args, **_kwargs: validations.pop(0),
    )
    monkeypatch.setattr(
        report_guardrails.repair_report_script,
        "repair_report",
        lambda *_args, **_kwargs: 1,
    )

    result = report_guardrails.run_report_guardrail(tmp_path, provider="ollama")

    assert result["status"] == "passed"
    assert result["deterministic_initial_error_count"] == 1
    assert result["semantic_initial_error_count"] == 2
    assert result["initial_error_count"] == 3
    semantic_initial = json.loads(
        (tmp_path / "report_validation_semantic_initial.json").read_text(encoding="utf-8")
    )
    assert len([issue for issue in semantic_initial["issues"] if issue["severity"] == "error"]) == 2
```

Add the synthesis counterpart:

```python
def test_synthesis_guardrail_preserves_deterministic_and_semantic_initial_error_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text('{"papers": []}', encoding="utf-8")
    (tmp_path / "synthesis.md").write_text("## Summary\n\nClaim.\n", encoding="utf-8")
    deterministic = {"severity": "error", "code": "local", "file": "synthesis.md"}
    semantic = {
        "severity": "error",
        "code": "claim_rag_unsupported",
        "file": "synthesis.md",
    }
    empty_consistency = {"issues": [], "results": []}
    validations = [
        ([deterministic], [], empty_consistency, None, None, "deterministic"),
        ([semantic], [{"status": "unsupported"}], empty_consistency, None, None, "semantic"),
        ([], [], empty_consistency, None, None, "semantic"),
    ]

    monkeypatch.setattr(
        report_guardrails,
        "_validate_synthesis_guardrails",
        lambda *_args, **_kwargs: validations.pop(0),
    )
    monkeypatch.setattr(
        report_guardrails,
        "repair_synthesis_report",
        lambda *_args, **_kwargs: 1,
    )

    result = report_guardrails.run_synthesis_guardrail(tmp_path, provider="ollama")

    assert result["status"] == "passed"
    assert result["deterministic_initial_error_count"] == 1
    assert result["semantic_initial_error_count"] == 1
    assert result["initial_error_count"] == 2
    assert (tmp_path / "synthesis_guardrail_semantic_initial.json").is_file()
```

Run both phase-metrics tests and require failure because the phase fields,
artifacts, and combined counts do not exist.

- [ ] **Step 5: Add the deterministic hard-error gate for Parts**

Import `Literal` from `typing`. In `_validate_part_reports()`, replace the
current papers-only early return with:

```python
    if _error_count(deterministic):
        return deterministic, [], None, None, "deterministic"
```

Return semantic results with a final `"semantic"` value:

```python
    return (
        deterministic + semantic["issues"],
        semantic["claims"],
        semantic.get("selection"),
        semantic.get("inline_citation_coverage"),
        "semantic",
    )
```

This retains papers failures and additionally defers RAG for every local hard
error. Update the three controller unpack sites and test fakes to carry the
phase value.

- [ ] **Step 6: Move synthesis consistency ahead of semantic RAG**

In `_validate_synthesis_guardrails()`, preserve the current fatal HTML/papers early return, then use:

```python
    consistency = synthesis_consistency_validation.validate_synthesis_consistency(data_dir)
    cheap_issues = deterministic + consistency["issues"]
    if _error_count(cheap_issues):
        return cheap_issues, [], consistency, None, None, "deterministic"

    semantic = claim_rag_validation.validate_claims(
        data_dir,
        ("synthesis.md",),
        provider=provider,
        cache=claim_cache,
    )
    return (
        cheap_issues + semantic["issues"],
        semantic["claims"],
        consistency,
        semantic.get("selection"),
        semantic.get("inline_citation_coverage"),
        "semantic",
    )
```

The existing fatal HTML/papers return also appends `"deterministic"`. Update
the three synthesis controller unpack sites and every monkeypatched return
tuple in this test file.

- [ ] **Step 7: Preserve phase-initial metrics**

In each controller:

1. Initialize deterministic or semantic count from the first returned phase.
2. When semantic phase is reached for the first time, record its hard-error
   count and write the corresponding semantic-initial JSON artifact.
3. Return both phase counts.
4. Set legacy `initial_error_count` to their sum.

Use zero for a phase that is reached with no hard errors. If a run fails before
semantic validation becomes reachable, use `0` for
`semantic_initial_error_count` and do not create the semantic-initial artifact.

- [ ] **Step 8: Run ordering and regression suites**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/scripts/test_validate_repair_report.py \
  tests/scripts/test_repair_report.py
uv run ruff check src/agents/deep_interpreter/report_guardrails.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
uv run python -m py_compile src/agents/deep_interpreter/report_guardrails.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
git diff --check
```

- [ ] **Step 9: Commit Task 2**

```bash
git add src/agents/deep_interpreter/report_guardrails.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
git commit -m "Keep agentic RAG behind deterministic report checks

Constraint: Parts and synthesis retain the same final validators and fixed corpus
Rejected: Reducing RAG rewrites | Experimental retrieval policy must remain unchanged
Confidence: high
Scope-risk: moderate
Directive: Never spend semantic retrieval while a local hard error blocks acceptance
Tested: guardrail middleware, Claim-RAG, validate-repair, repair suites, Ruff, py_compile, diff check
Not-tested: Live 4000 retrieval timing"
```

---

### Task 3: Roll back every no-progress repair candidate

**Files:**
- Modify: `src/agents/deep_interpreter/report_guardrails.py:500-748`
- Test: `tests/agents/deep_interpreter/test_report_guardrail_middleware.py`

**Interfaces:**
- Create: `_snapshot_markdown_files(data_dir: Path, filenames: tuple[str, ...]) -> dict[str, str]`.
- Create: `_restore_markdown_files(data_dir: Path, snapshot: dict[str, str]) -> None`.
- Create: `_strict_phase_progress(before: list[dict[str, Any]], before_phase: Literal["deterministic", "semantic"], after: list[dict[str, Any]], after_phase: Literal["deterministic", "semantic"]) -> bool`.
- Preserves: the existing `run_report_guardrail` and `run_synthesis_guardrail` result dictionaries.
- Changes metric meaning: changed counts include retained mutations only.

- [ ] **Step 1: Write the RED synthesis rollback test using the exact failure shape**

Add:

```python
def test_synthesis_guardrail_rolls_back_caveat_only_table_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    unsafe_row = (
        "| Tumor-Vascular Spatial Association | Strong | "
        "Spatial plots confirm epithelial-vascular co-localization |"
    )
    original = (
        "## Emergent Themes Summary\n\n"
        "| Theme | Strength | Supporting Evidence |\n"
        "|---|---|---|\n"
        f"{unsafe_row}\n"
    )
    (tmp_path / "papers.json").write_text('{"papers": []}', encoding="utf-8")
    (tmp_path / "synthesis.md").write_text(original, encoding="utf-8")
    caveat_only = (
        f"{unsafe_row}\n\n"
        "*Note: All themes are dataset-derived associations, not established mechanisms.*"
    )
    model = StructuredRepairModel(caveat_only)
    monkeypatch.setattr(report_guardrails.repair_report_script, "_create_model", lambda *_: model)

    result = report_guardrails.run_synthesis_guardrail(tmp_path, provider="ollama")

    assert result["status"] == "failed"
    assert result["repair_attempt_count"] == 3
    assert result["changed_claims"] == 0
    assert result["final_error_count"] == 1
    retained = (tmp_path / "synthesis.md").read_text(encoding="utf-8")
    assert retained == original
    assert "*Note:" not in retained
```

- [ ] **Step 2: Write the RED Parts rollback test**

Add:

```python
def test_parts_guardrail_restores_all_files_after_no_progress_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)
    originals = {
        name: (tmp_path / name).read_text(encoding="utf-8")
        for name in ("part1_final.md", "part2_final.md", "part3_final.md")
    }

    monkeypatch.setattr(
        report_guardrails.validate_report_script,
        "validate_report",
        lambda _data_dir: [
            {"severity": "error", "code": "persistent", "file": "part1_final.md"}
        ],
    )

    def append_without_progress(data_dir: Path, *_args: Any, **_kwargs: Any) -> int:
        path = data_dir / "part1_final.md"
        path.write_text(path.read_text(encoding="utf-8") + "Unhelpful caveat.\n", encoding="utf-8")
        return 1

    monkeypatch.setattr(
        report_guardrails.repair_report_script,
        "repair_report",
        append_without_progress,
    )

    result = report_guardrails.run_report_guardrail(tmp_path, provider="ollama")

    assert result["status"] == "failed"
    assert result["repair_attempt_count"] == 3
    assert result["changed_sections"] == 0
    assert {
        name: (tmp_path / name).read_text(encoding="utf-8")
        for name in originals
    } == originals
```

- [ ] **Step 3: Write the RED accepted-repair and idempotence test**

Add:

```python
def test_synthesis_atomic_table_repair_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    unsafe_row = (
        "| Tumor-Vascular Spatial Association | Strong | "
        "Spatial plots confirm epithelial-vascular co-localization |"
    )
    safe_row = (
        "| Tumor-Vascular Spatial Association | Strong | "
        "Spatial plots show epithelial-vascular co-localization |"
    )
    (tmp_path / "papers.json").write_text('{"papers": []}', encoding="utf-8")
    (tmp_path / "synthesis.md").write_text(
        "## Emergent Themes Summary\n\n"
        "| Theme | Strength | Supporting Evidence |\n"
        "|---|---|---|\n"
        f"{unsafe_row}\n",
        encoding="utf-8",
    )
    model = StructuredRepairModel(safe_row)
    monkeypatch.setattr(report_guardrails.repair_report_script, "_create_model", lambda *_: model)

    first = report_guardrails.run_synthesis_guardrail(tmp_path, provider="ollama")
    after_first = (tmp_path / "synthesis.md").read_bytes()
    second = report_guardrails.run_synthesis_guardrail(tmp_path, provider="ollama")

    assert first["status"] == "passed"
    assert first["initial_error_count"] == 1
    assert first["final_error_count"] == 0
    assert first["changed_claims"] == 1
    assert second["status"] == "passed"
    assert second["initial_error_count"] == 0
    assert second["repair_attempt_count"] == 0
    assert second["changed_claims"] == 0
    assert (tmp_path / "synthesis.md").read_bytes() == after_first
    assert safe_row in after_first.decode("utf-8")
```

- [ ] **Step 4: Verify all three tests fail before the controller change**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_guardrail_rolls_back_caveat_only_table_repair \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_parts_guardrail_restores_all_files_after_no_progress_repair \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py::test_synthesis_atomic_table_repair_is_idempotent
```

Expected: caveats remain in files, no-progress changes are counted, or the table repair target is retained incorrectly.

- [ ] **Step 5: Write the RED phase-transition policy test**

Add:

```python
def test_strict_phase_progress_accepts_only_safe_phase_transitions() -> None:
    from src.agents.deep_interpreter import report_guardrails

    deterministic_error = [{"severity": "error", "code": "local"}]
    semantic_errors = [
        {"severity": "error", "code": "claim_rag_unsupported"},
        {"severity": "error", "code": "claim_rag_overclaimed"},
    ]

    assert report_guardrails._strict_phase_progress(
        deterministic_error,
        "deterministic",
        semantic_errors,
        "semantic",
    )
    assert not report_guardrails._strict_phase_progress(
        semantic_errors,
        "semantic",
        deterministic_error,
        "deterministic",
    )
    assert report_guardrails._strict_phase_progress(
        semantic_errors,
        "semantic",
        semantic_errors[:1],
        "semantic",
    )
    assert not report_guardrails._strict_phase_progress(
        semantic_errors,
        "semantic",
        semantic_errors,
        "semantic",
    )
```

Run it and require failure because `_strict_phase_progress` does not exist.

- [ ] **Step 6: Add shared snapshot and phase-aware progress helpers**

Add above `run_report_guardrail()`:

```python
def _snapshot_markdown_files(
    data_dir: Path,
    filenames: tuple[str, ...],
) -> dict[str, bytes]:
    return {
        filename: (data_dir / filename).read_bytes()
        for filename in filenames
        if (data_dir / filename).is_file()
    }


def _restore_markdown_files(data_dir: Path, snapshot: dict[str, bytes]) -> None:
    for filename, content in snapshot.items():
        (data_dir / filename).write_bytes(content)


def _strict_phase_progress(
    before: list[dict[str, Any]],
    before_phase: Literal["deterministic", "semantic"],
    after: list[dict[str, Any]],
    after_phase: Literal["deterministic", "semantic"],
) -> bool:
    if before_phase == "deterministic" and after_phase == "semantic":
        return True
    if before_phase != after_phase:
        return False
    before_count = _error_count(before)
    after_count = _error_count(after)
    if after_count < before_count:
        return True
    if before_phase != "semantic" or after_count != before_count:
        return False
    before_keys = {
        _issue_claim_key(issue)
        for issue in before
        if issue.get("severity") == "error"
    }
    after_keys = {
        _issue_claim_key(issue)
        for issue in after
        if issue.get("severity") == "error"
    }
    return bool(before_keys) and before_keys.isdisjoint(after_keys)
```

- [ ] **Step 7: Make regular Parts repair tentative**

In the Parts loop:

1. Snapshot `filenames` before `repair_report()`.
2. Increment `repair_attempt_count` for every attempted repair.
3. If `changed == 0`, restore and break without semantic revalidation.
4. Validate the candidate.
5. If `_strict_phase_progress(current_issues, current_phase, candidate_issues,
   candidate_phase)` is false,
   restore the snapshot and continue from the unchanged current issues and
   issue JSON.
6. Only after strict progress, add `changed` to `changed_sections` and replace
   current validation state.

Use this retained-state assignment after candidate validation:

```python
        if not _strict_phase_progress(
            current_issues,
            current_phase,
            candidate_issues,
            candidate_phase,
        ):
            _restore_markdown_files(data_dir, snapshot)
            continue

        changed_sections += changed
        current_issues = candidate_issues
        current_claims = candidate_claims
        current_selection = candidate_selection
        current_coverage = candidate_coverage
        current_phase = candidate_phase
        issues_path = final_path
```

- [ ] **Step 8: Make regular synthesis repair tentative**

Apply the same contract using `("synthesis.md",)` and update
`changed_claims` only after strict progress. Keep the prior retained
`current_issues`, claim results, consistency results, selection, coverage, and
phase after rollback.

- [ ] **Step 9: Apply the same contract to terminal repair**

For Parts and synthesis terminal attempts:

- snapshot before terminal repair;
- validate only when the terminal repair reports a change;
- retain and count it only when hard-error count strictly decreases;
- otherwise restore the snapshot and keep the pre-terminal validation state.

- [ ] **Step 10: Align bounded retry tests with retained-change metrics**

Update these existing assertions in
`tests/agents/deep_interpreter/test_report_guardrail_middleware.py`:

- `test_run_synthesis_guardrail_retries_up_to_three_repairs`: three attempts,
  one accepted changed claim.
- `test_run_report_guardrail_retries_up_to_three_repairs`: three attempts, one
  accepted changed section.
- both persistent-error tests: three attempts, zero accepted changes.
- both terminal-repair tests: use validation sequences where the third regular
  candidate reduces total hard errors while surfacing a new error; terminal
  repair then reduces that new error to zero.

Use this sequence for the synthesis terminal test:

```python
old_a = {
    "severity": "error",
    "code": "old_a",
    "file": "synthesis.md",
    "section": "## Summary",
    "value": "Old A",
}
old_b = {**old_a, "code": "old_b", "value": "Old B"}
old_c = {**old_a, "code": "old_c", "value": "Old C"}
latent = {
    "severity": "warning",
    "code": "claim_rag_unverifiable",
    "file": "synthesis.md",
    "section": "## Summary",
    "value": "New semantic claim",
}
promoted = {
    **latent,
    "severity": "error",
    "code": "claim_rag_unsupported",
}
repaired = {
    **latent,
    "code": "claim_rag_hypothesis_warning",
}
validations = [
    [old_a, old_b, old_c, latent],
    [old_a, old_b, latent],
    [old_a, old_b, latent],
    [promoted],
    [repaired],
]
```

Use the equivalent file-scoped issues for the Parts terminal test.

- [ ] **Step 11: Run full repair and guardrail regression suites**

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/scripts/test_validate_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/scripts/test_repair_report.py \
  tests/deep_interpreter/test_comprehensive_template_report.py
uv run ruff check src/agents/deep_interpreter/report_guardrails.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
uv run python -m py_compile src/agents/deep_interpreter/report_guardrails.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
git diff --check
```

- [ ] **Step 12: Commit Task 3**

```bash
git add src/agents/deep_interpreter/report_guardrails.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
git commit -m "Keep no-progress report repairs out of retained artifacts

Constraint: Preserve bounded retries and fail-closed final validation
Rejected: Caveat deduplication rule | Rollback removes every no-progress mutation generically
Confidence: high
Scope-risk: moderate
Directive: Changed repair metrics must describe retained error reduction only
Tested: guardrail, Claim-RAG, validator, repair, comprehensive report suites; Ruff; py_compile; diff check
Not-tested: Historical qwen3.5:122b artifact corpus"
```

---

### Task 4: Replay the preserved failure corpus and measure retrieval work

**Files:**
- Verification only; use copies under `mktemp -d`.
- Write report: `.superpowers/sdd/2026-08-21-deterministic-first-atomic-report-repair/task-4-replay-report.md`
- Write raw log: `.superpowers/sdd/2026-08-21-deterministic-first-atomic-report-repair/task-4-replay.log`

**Interfaces:**
- Consumes: reviewed Tasks 1-3.
- Produces: per-case initial/final errors, accepted changes, idempotence, elapsed time, new RAG audit rows, and source immutability evidence.

- [ ] **Step 1: Recheck runtime dependencies**

```bash
git status --short --branch
curl -fsS http://localhost:8883/health
curl -fsS http://localhost:4000/api/tags | jq -e '.models | map(.name) | index("qwen3.5:122b") != null'
curl -fsS http://localhost:6000/api/tags | jq -e '.models | map(.name) | index("qwen3.5:122b") != null'
curl -fsS --max-time 240 http://localhost:6000/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.5:122b","prompt":"Reply exactly OK","stream":false,"options":{"num_predict":8}}' \
  | jq -e '.done == true and .model == "qwen3.5:122b"'
```

- [ ] **Step 2: Create immutable replay and pristine copies**

Use these exact sources:

```text
inline = res/deep_interpreter/bc/sni_repair_ablation/save_recovery_20260820T041110Z/pairs/pair-05/wiki-off
direction_v1 = res/deep_interpreter/bc/sni_repair_ablation/inline_recovery_20260820T065140Z/pairs/pair-05/wiki-off
direction_v2 = res/deep_interpreter/bc/sni_repair_ablation/restart_after_accidental_stop_20260820T203303Z/pairs/pair-05/wiki-off
html = res/deep_interpreter/bc/sni_repair_ablation/locality_recovery_20260820T093323Z/pairs/pair-05/wiki-off
table = res/deep_interpreter/bc/sni_repair_ablation/descriptor_locality_recovery_20260821T080305Z/pairs/pair-05/wiki-off
```

Create one temp root and the SDD evidence directory:

```bash
replay_root="$(mktemp -d /tmp/deepmast-atomic-repair-replay.XXXXXX)"
test -d "$replay_root"
replay_workspace=".superpowers/sdd/2026-08-21-deterministic-first-atomic-report-repair"
mkdir -p "$replay_workspace"
replay_log="$replay_workspace/task-4-replay.log"
```

- [ ] **Step 3: Run the four guardrail replays**

Run this complete replay driver. It copies every source twice, clears only stale
validation outputs in the replay copy, seeds the table case from
`before/synthesis.md`, checks idempotence, and verifies source immutability:

```bash
set -o pipefail
CCI_RAG_BASE_URL=http://localhost:8883 \
OLLAMA_BASE_URL=http://localhost:6000 \
OLLAMA_MODEL=qwen3.5:122b \
OLLAMA_REASONING=true \
OLLAMA_REQUEST_TIMEOUT_SECONDS=10800 \
LLM_PROVIDER=ollama \
DEEP_INTERPRETER_USE_WIKI_CONTEXT=false \
DEEP_INTERPRETER_REQUIRE_AGENTIC_RAG=true \
DEEP_INTERPRETER_FIXED_COLLECTION_ID=a208e916-bd32-405a-9eee-de4cd82b2a3b \
uv run python - "$replay_root" <<'PY' 2>&1 | tee "$replay_log"
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from src.agents.deep_interpreter.report_guardrails import (
    run_report_guardrail,
    run_synthesis_guardrail,
)

repo = Path.cwd().resolve()
temp_root = Path(sys.argv[1]).resolve()
fixed_uuid = "a208e916-bd32-405a-9eee-de4cd82b2a3b"
cases = {
    "inline": (
        repo / "res/deep_interpreter/bc/sni_repair_ablation/"
        "save_recovery_20260820T041110Z/pairs/pair-05/wiki-off",
        "parts",
    ),
    "direction_v1": (
        repo / "res/deep_interpreter/bc/sni_repair_ablation/"
        "inline_recovery_20260820T065140Z/pairs/pair-05/wiki-off",
        "parts",
    ),
    "direction_v2": (
        repo / "res/deep_interpreter/bc/sni_repair_ablation/"
        "restart_after_accidental_stop_20260820T203303Z/pairs/pair-05/wiki-off",
        "parts",
    ),
    "table": (
        repo / "res/deep_interpreter/bc/sni_repair_ablation/"
        "descriptor_locality_recovery_20260821T080305Z/pairs/pair-05/wiki-off",
        "synthesis",
    ),
}


def content_manifest(directory: Path) -> dict[str, str]:
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def heading_layout(paths: list[Path]) -> list[tuple[str, int, str]]:
    return [
        (path.name, line_number, match.group(1))
        for path in paths
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines())
        if (match := re.match(r"^(#{1,6})\s+", line))
    ]


def safe_heading_layout(
    before: list[tuple[str, int, str]],
    after: list[tuple[str, int, str]],
) -> bool:
    if len(before) != len(after):
        return False
    for index, (old, new) in enumerate(zip(before, after)):
        if old[:2] != new[:2]:
            return False
        if old[2] != new[2] and not (index == 0 and 2 <= len(old[2]) <= 6 and new[2] == "#"):
            return False
    return True


def pmids(paths: list[Path]) -> set[str]:
    return {
        pmid
        for path in paths
        for pmid in re.findall(
            r"\bPMID[:\s]*(\d{6,9})\b",
            path.read_text(encoding="utf-8"),
            flags=re.IGNORECASE,
        )
    }


def audit_rows(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


summaries: dict[str, dict[str, object]] = {}
for label, (source, lane) in cases.items():
    case_root = temp_root / label
    replay = case_root / "replay"
    pristine = case_root / "pristine"
    source_before = content_manifest(source)
    shutil.copytree(source, replay)
    shutil.copytree(source, pristine)
    assert content_manifest(pristine) == source_before

    if lane == "parts":
        stale = (
            "report_validation_initial.json",
            "report_validation_final.json",
            "report_validation_terminal.json",
            "parts_guardrail_result.json",
        )
        target_paths = [replay / name for name in ("part1_final.md", "part2_final.md", "part3_final.md")]
        changed_key = "changed_sections"
        runner = run_report_guardrail
    else:
        shutil.copyfile(replay / "before" / "synthesis.md", replay / "synthesis.md")
        stale = (
            "synthesis_guardrail_initial.json",
            "synthesis_guardrail_final.json",
            "synthesis_guardrail_result.json",
            "synthesis_validation.json",
            "synthesis_targets.json",
        )
        target_paths = [replay / "synthesis.md"]
        changed_key = "changed_claims"
        runner = run_synthesis_guardrail

    for filename in stale:
        (replay / filename).unlink(missing_ok=True)

    heading_layout_before = heading_layout(target_paths)
    pmids_before = pmids(target_paths)
    table_rows_before = sum(
        line.strip().startswith("|")
        for line in target_paths[0].read_text(encoding="utf-8").splitlines()
    )
    audit_path = replay / "rag_audit_atomic_replay.jsonl"
    audit_path.unlink(missing_ok=True)
    os.environ["DEEP_INTERPRETER_RAG_AUDIT_PATH"] = str(audit_path)

    started = time.monotonic()
    first = runner(replay, provider="ollama")
    elapsed = time.monotonic() - started
    retained = {path.name: path.read_bytes() for path in target_paths}
    second = runner(replay, provider="ollama")
    rows = audit_rows(audit_path)

    assert first["status"] == "passed", (label, first)
    assert first["final_error_count"] == 0, (label, first)
    assert second["status"] == "passed", (label, second)
    assert second["initial_error_count"] == 0, (label, second)
    assert second["repair_attempt_count"] == 0, (label, second)
    assert second[changed_key] == 0, (label, second)
    assert retained == {path.name: path.read_bytes() for path in target_paths}
    assert safe_heading_layout(heading_layout_before, heading_layout(target_paths))
    assert pmids(target_paths).issubset(pmids_before)
    if lane == "synthesis":
        table_rows_after = sum(
            line.strip().startswith("|")
            for line in target_paths[0].read_text(encoding="utf-8").splitlines()
        )
        assert table_rows_after == table_rows_before
        caveats = [
            line
            for line in target_paths[0].read_text(encoding="utf-8").splitlines()
            if "All themes represent dataset-derived" in line
        ]
        assert len(caveats) == len(set(caveats))
    assert content_manifest(source) == source_before
    assert content_manifest(pristine) == source_before
    assert all(row.get("collection_uuid") == fixed_uuid for row in rows)
    assert all(row.get("use_wiki_context") is False for row in rows)

    summaries[label] = {
        "elapsed_seconds": round(elapsed, 3),
        "first": first,
        "second": second,
        "new_rag_rows": len(rows),
        "rag_elapsed_seconds": round(
            sum(float(row.get("elapsed_seconds") or 0.0) for row in rows),
            3,
        ),
        "zero_hit_count": sum(int(row.get("result_count") or 0) == 0 for row in rows),
        "source_immutable": True,
    }

print(json.dumps(summaries, indent=2, sort_keys=True))
PY
test "$?" -eq 0
```

- [ ] **Step 4: Re-run the HTML Reporter boundary on its copy**

Create the HTML replay and pristine copies, then prepare only the replay copy:

```bash
html_source="res/deep_interpreter/bc/sni_repair_ablation/locality_recovery_20260820T093323Z/pairs/pair-05/wiki-off"
html_replay_dir="$replay_root/html/replay"
html_pristine_dir="$replay_root/html/pristine"
mkdir -p "$html_replay_dir" "$html_pristine_dir"
cp -R "$html_source/." "$html_replay_dir/"
cp -R "$html_source/." "$html_pristine_dir/"
diff -qr "$html_source" "$html_pristine_dir"

uv run python - "$html_replay_dir" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
(root / "data_path.txt").write_text(f"{root}\n", encoding="utf-8")
for filename in (
    "synthesis.md",
    "synthesis_validation.json",
    "synthesis_targets.json",
    "synthesis_guardrail_initial.json",
    "synthesis_guardrail_final.json",
    "synthesis_guardrail_result.json",
    "reporter_recovery.json",
    "CCI_Analysis_Report.html",
):
    (root / filename).unlink(missing_ok=True)
PY
```

Then:

```bash
CCI_RAG_BASE_URL=http://localhost:8883 \
OLLAMA_BASE_URL=http://localhost:6000 \
OLLAMA_MODEL=qwen3.5:122b \
OLLAMA_REASONING=true \
OLLAMA_REQUEST_TIMEOUT_SECONDS=10800 \
REPORTER_ATTEMPT_TIMEOUT_SECONDS=3600 \
LLM_PROVIDER=ollama \
DEEP_INTERPRETER_USE_WIKI_CONTEXT=false \
DEEP_INTERPRETER_REQUIRE_AGENTIC_RAG=true \
DEEP_INTERPRETER_FIXED_COLLECTION_ID=a208e916-bd32-405a-9eee-de4cd82b2a3b \
uv run python scripts/run_deep_interpreter_agent.py \
  --provider ollama \
  --subagent reporter \
  --data-dir "$html_replay_dir" \
  --disable-summarization \
  --traceback
```

Verify the regenerated outputs and source immutability:

```bash
uv run python - "$html_replay_dir" <<'PY'
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
synthesis = (root / "synthesis.md").read_text(encoding="utf-8")
result = json.loads((root / "synthesis_validation.json").read_text(encoding="utf-8"))
guardrail = result["synthesis_guardrail"]
assert synthesis.startswith("# ")
assert len(re.findall(r"^## ", synthesis, flags=re.MULTILINE)) >= 2
assert not re.search(
    r"^\s*<(?:article|div|h[1-6]|li|ol|p|section|table|ul)\b",
    synthesis,
    flags=re.IGNORECASE | re.MULTILINE,
)
assert guardrail["status"] == "passed"
assert guardrail["final_error_count"] == 0
assert (root / "synthesis_targets.json").is_file()
assert (root / "CCI_Analysis_Report.html").is_file()
PY
diff -qr "$html_source" "$html_pristine_dir"
```

- [ ] **Step 5: Verify invariants and source immutability**

For every replay:

- compare heading levels and positions before/after while allowing validator-owned
  exact heading text replacement;
- assert repaired PMID set is a subset of the original PMID set;
- compare table row count before/after for the table case;
- assert no repeated identical caveat lines;
- compare source to pristine after replay;
- verify every new audit row uses the fixed UUID and `use_wiki_context=false`.

- [ ] **Step 6: Record performance evidence**

Report for each case:

- wall-clock elapsed;
- first/second error counts;
- accepted changed count;
- repair attempts;
- new RAG audit row count and elapsed total;
- zero-hit count;
- whether Claim-RAG was called before deterministic error 0.

Compare the table case to the preserved baseline of 96 attempts and 6,270.622
retrieval seconds. Treat timing as observational; correctness gates remain hard.

- [ ] **Step 7: Stop on any replay failure**

Do not launch the full pair unless all five cases pass and every source/pristine
comparison remains clean. This task is verification-only and creates no commit.

---

### Task 5: Complete one fresh no-SNI then SNI pair

**Files:**
- Live verification only.
- Write report: `.superpowers/sdd/2026-08-21-deterministic-first-atomic-report-repair/task-5-final-pair-report.md`

**Interfaces:**
- Consumes: reviewed Tasks 1-3 and passed Task 4 corpus.
- Produces: two passed condition manifests and comparison metrics.

- [ ] **Step 1: Run final preflight**

Confirm:

- clean worktree at the reviewed Task 3 HEAD;
- no active `run_bc_sni_repair_ablation.py` process;
- 4000 and 6000 both list `qwen3.5:122b`;
- a real 6000 generate returns HTTP 200 and `done=true`;
- 8883 health is OK;
- fixed collection UUID has 100 documents and 1,553 chunks;
- source and collection contain the same 100 PMIDs and SHA-256
  `cb4b1230365790bd078ad796e90194c462ccbef673709af8f8d015044598b604`.

- [ ] **Step 2: Create a durable tmux run**

```bash
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
pair_root="res/deep_interpreter/bc/sni_repair_ablation/atomic_repair_recovery_${stamp}/pairs"
session="bc_pair05_atomic_${stamp}"
mkdir -p "$pair_root"
printf '%s\n' "$session" > "$pair_root/runner.tmux"

tmux new-session -d -s "$session" -c "$PWD" \
  "set -o pipefail; uv run python scripts/run_bc_sni_repair_ablation.py \
    --pair 5 \
    --output-root '$pair_root' \
    --source '/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/res/deep_interpreter/bc/bc' \
    --manifest 'res/deep_interpreter/bc/sni_repair_ablation/experiment_manifest_rag4000.json' \
    > '$pair_root/final_pair.stdout.log' \
    2> '$pair_root/final_pair.stderr.log'; \
    rc=\$?; printf '%s\\n' \$rc > '$pair_root/runner.exit'; exit \$rc"

tmux has-session -t "$session"
```

Require one actual Python runner and `pair-05/wiki-off` before considering the
launch successful. Do not use `nohup`; the tool process group reaped prior
nohup attempts.

- [ ] **Step 3: Monitor the fail-fast boundary**

Do not terminate a healthy stage when an intermediate guardrail JSON appears.
Wait for the no-SNI `run_manifest.json` terminal status. SNI may start only when
no-SNI reports `return_status="passed"`.

- [ ] **Step 4: Verify both condition outputs**

For no-SNI and SNI require:

- `run_manifest.json` passed;
- Parts final hard errors 0;
- synthesis final hard errors 0;
- second offline guardrail invocation changes 0;
- Markdown heading levels/positions preserved, validator-owned targeted heading
  text changes allowed, and no HTML fragments in `synthesis.md`;
- no new PMID;
- fixed collection/source identity;
- safe repair metrics and audit;
- Reporter HTML/validation/targets present.

- [ ] **Step 5: Generate the comparison report**

Report per condition:

- initial/final Parts errors;
- initial/final synthesis errors;
- deterministic-initial and semantic-initial errors for Parts and synthesis;
- regular, terminal, accepted, and rolled-back attempts when auditable;
- changed targets;
- retrieval attempts, positives, zero hits, unique PMIDs, and elapsed time;
- deterministic-phase elapsed and semantic-phase elapsed when available;
- total elapsed.

Then compare no-SNI versus SNI on repair count, error burden, retrieval coverage,
unique PMIDs, and runtime. This task is verification-only and creates no commit.

---

## Final Verification

After Task 5, run:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/scripts/test_validate_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/scripts/test_repair_report.py \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/deep_interpreter/test_comprehensive_template_report.py \
  tests/test_sni_ablation_runner.py
uv run ruff check scripts/validate_report.py \
  src/agents/deep_interpreter/report_guardrails.py \
  tests/scripts/test_validate_report.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py
uv run python -m py_compile scripts/validate_report.py \
  src/agents/deep_interpreter/report_guardrails.py
git diff --check
git status --short --branch
```

Do not claim completion unless every code test passes, all historical replays
pass, both pair conditions pass, no runner remains, and the worktree contains no
unexpected changes.

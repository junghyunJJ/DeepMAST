# Reporter Deterministic Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete valid Reporter synthesis deterministically in the same LLM attempt and reserve the second LLM attempt for genuine synthesis failure.

**Architecture:** Keep orchestration in `reporter_recovery.py` and reuse the existing guardrail/bookkeeping/render path in `tools/report.py` through one structured internal helper. Assess artifact validity explicitly, refresh only the invalid downstream suffix, and apply SHA freshness only to `required_refresh`; remove HTML orchestration from the Reporter LLM.

**Tech Stack:** Python 3.12, asyncio, hashlib, pathlib, pytest, LangChain tools/middleware, existing DeepMAST synthesis guardrails and comprehensive HTML renderer

**Spec:** `docs/superpowers/specs/2026-08-25-reporter-deterministic-finalization-design.md`

## Global Constraints

- Keep `MAX_REPORTER_ATTEMPTS = 2`.
- Keep `REPORTER_ATTEMPT_TIMEOUT_SECONDS` and its configured values unchanged.
- Keep the synthesis guardrail's three repair passes and optional terminal repair unchanged.
- Do not weaken `synthesis_not_markdown` or any hard guardrail.
- Do not change SGCP-RAG, SNI page selection, query count, Claim-RAG selection, batching, caching, or collection binding.
- Do not change or rerun Part 1/2/3 generation during Reporter finalization.
- Do not add HTML-to-Markdown conversion, a dependency, a graph node, a manifest, or a third Reporter attempt.
- Preserve invalid-synthesis snapshots, all hard failure codes, repeated-invalid evidence, timeout integrity, and attempt-exception audit fields.
- Do not run a full SNI/no-SNI pair. Stop live validation after Reporter-only replay on an isolated copy.
- Match existing dict-based internal results; do not add a class hierarchy or new production module.
- Every commit follows the repository Lore trailer protocol.

## File Structure

- Modify `src/agents/deep_interpreter/reporter_recovery.py`: artifact validity, refresh scope, post-attempt finalization, recovery eligibility, audit, timeout result retention.
- Modify `src/agents/deep_interpreter/tools/report.py`: structured internal finalizer shared by recovery and the public `generate_html_report` tool.
- Modify `src/agents/deep_interpreter/subagents/configs.py`: remove HTML generation from Reporter LLM tools while keeping the stage output contract.
- Modify `src/agents/deep_interpreter/subagents/prompts.py`: make Reporter stop after writing synthesis.
- Modify `scripts/run_deep_interpreter_agent.py`: make standalone Reporter instructions synthesis-only.
- Modify existing Reporter tests only; do not create a new production file.
- Create no checked-in runtime replay artifacts.

---

### Task 1: Model artifact validity and refresh responsibility

**Files:**
- Modify: `src/agents/deep_interpreter/reporter_recovery.py:22-126`
- Modify: `tests/agents/deep_interpreter/test_reporter_recovery.py:15-136`

**Interfaces:**
- Consumes: `REPORTER_OUTPUTS`, `_file_sha256(path)`, `_reporter_output_state(data_dir)`
- Produces: `DERIVED_REPORTER_OUTPUTS`, `_reporter_artifact_validity(data_dir)`, `_required_reporter_refresh(data_dir, synthesis_changed=False)`, `inspect_reporter_completion(..., required_refresh=())`

- [ ] **Step 1: Make Reporter fixtures valid under the new predicates**

Add explicit fixture helpers and make `_write_reporter_outputs` delegate to them so existing tests do not accidentally use `{}` targets or fragmentary HTML:

```python
def _write_valid_synthesis(
    data_dir: Path,
    *,
    text: str = "# Synthesis\n\n## Executive Summary\n\nGrounded narrative.\n",
) -> None:
    (data_dir / "synthesis.md").write_text(text, encoding="utf-8")


def _write_valid_validation(data_dir: Path) -> None:
    (data_dir / "synthesis_validation.json").write_text(
        json.dumps(
            {
                "synthesis_guardrail": {
                    "status": "passed",
                    "final_error_count": 0,
                }
            }
        ),
        encoding="utf-8",
    )


def _write_valid_targets(data_dir: Path) -> None:
    from src.agents.deep_interpreter.tools.report import _default_synthesis_targets

    (data_dir / "synthesis_targets.json").write_text(
        json.dumps(_default_synthesis_targets(str(data_dir))),
        encoding="utf-8",
    )


def _write_valid_html(data_dir: Path) -> None:
    (data_dir / "CCI_Analysis_Report.html").write_text(
        "<!DOCTYPE html><html><body>report</body></html>",
        encoding="utf-8",
    )
```

Retain `_write_reporter_outputs(..., status, errors)` for failed-guardrail tests, but use the valid targets/HTML helpers and vary only the validation status/error count.

- [ ] **Step 2: Write the state-D regression first**

Add helpers for valid synthesis, validation, targets, and HTML fixtures. Then add a focused test that pre-populates valid synthesis/sidecars, captures their hashes, leaves HTML missing, and asserts only HTML is refresh-required:

```python
def test_required_reporter_refresh_only_requests_missing_html(
    tmp_path: Path,
) -> None:
    _write_valid_synthesis(tmp_path)
    _write_valid_validation(tmp_path)
    _write_valid_targets(tmp_path)
    hashes = _reporter_output_state(tmp_path)

    assert _required_reporter_refresh(tmp_path) == ("CCI_Analysis_Report.html",)
    assert _reporter_output_state(tmp_path) == hashes
```

- [ ] **Step 3: Run state D and confirm RED**

Run:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py::test_required_reporter_refresh_only_requests_missing_html
```

Expected: FAIL during import because `_required_reporter_refresh` does not exist.

- [ ] **Step 4: Add table-driven validity and cascade cases**

Add one parameterized test for E/F/K/L without combining orchestration assertions:

```python
@pytest.mark.parametrize(
    ("invalid_artifact", "expected"),
    [
        (None, ()),
        (
            "synthesis_validation.json",
            (
                "synthesis_validation.json",
                "synthesis_targets.json",
                "CCI_Analysis_Report.html",
            ),
        ),
        (
            "synthesis_targets.json",
            ("synthesis_targets.json", "CCI_Analysis_Report.html"),
        ),
        ("CCI_Analysis_Report.html", ("CCI_Analysis_Report.html",)),
    ],
)
def test_required_reporter_refresh_uses_downstream_suffix(
    tmp_path: Path,
    invalid_artifact: str | None,
    expected: tuple[str, ...],
) -> None:
    _write_reporter_outputs(tmp_path, status="passed", errors=0)
    _write_valid_targets(tmp_path)
    if invalid_artifact == "synthesis_validation.json":
        (tmp_path / invalid_artifact).write_text("{", encoding="utf-8")
    elif invalid_artifact == "synthesis_targets.json":
        (tmp_path / invalid_artifact).write_text("[]", encoding="utf-8")
    elif invalid_artifact == "CCI_Analysis_Report.html":
        (tmp_path / invalid_artifact).write_text("not html", encoding="utf-8")

    assert _required_reporter_refresh(tmp_path) == expected
```

Add a separate test proving changed synthesis invalidates all downstream artifacts:

```python
def test_required_reporter_refresh_cascades_after_synthesis_change(tmp_path: Path) -> None:
    _write_reporter_outputs(tmp_path, status="passed", errors=0)
    _write_valid_targets(tmp_path)

    assert _required_reporter_refresh(tmp_path, synthesis_changed=True) == (
        "synthesis_validation.json",
        "synthesis_targets.json",
        "CCI_Analysis_Report.html",
    )
```

- [ ] **Step 5: Implement the minimal artifact predicates**

In `reporter_recovery.py`, keep tuple ordering deterministic:

```python
DERIVED_REPORTER_OUTPUTS = (
    "synthesis_validation.json",
    "synthesis_targets.json",
    "CCI_Analysis_Report.html",
)


def _load_json_object(path: Path) -> dict[str, Any] | None:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _valid_synthesis_validation(data_dir: Path) -> bool:
    validation = _load_json_object(data_dir / "synthesis_validation.json")
    if validation is None:
        return False
    guardrail = validation.get("synthesis_guardrail")
    return bool(
        isinstance(guardrail, dict)
        and guardrail.get("status") == "passed"
        and guardrail.get("final_error_count") == 0
    )


def _valid_synthesis_targets(data_dir: Path) -> bool:
    targets = _load_json_object(data_dir / "synthesis_targets.json")
    if targets is None:
        return False
    from src.agents.deep_interpreter.tools.report import _default_synthesis_targets

    expected = _default_synthesis_targets(str(data_dir))
    keys = (
        "part4_synthesis_available",
        "drug_md_available",
        "canonical_source",
        "supporting_source",
    )
    return all(targets.get(key) == expected[key] for key in keys)


def _valid_report_html(data_dir: Path) -> bool:
    path = data_dir / "CCI_Analysis_Report.html"
    if not path.is_file() or path.stat().st_size == 0:
        return False
    content = path.read_bytes().lower()
    return b"<!doctype html" in content and b"<html" in content and b"</html>" in content


def _reporter_artifact_validity(data_dir: Path) -> dict[str, bool]:
    return {
        "synthesis_validation.json": _valid_synthesis_validation(data_dir),
        "synthesis_targets.json": _valid_synthesis_targets(data_dir),
        "CCI_Analysis_Report.html": _valid_report_html(data_dir),
    }


def _required_reporter_refresh(
    data_dir: Path,
    *,
    synthesis_changed: bool = False,
) -> tuple[str, ...]:
    if synthesis_changed:
        return DERIVED_REPORTER_OUTPUTS
    validity = _reporter_artifact_validity(data_dir)
    for index, name in enumerate(DERIVED_REPORTER_OUTPUTS):
        if not validity[name]:
            return DERIVED_REPORTER_OUTPUTS[index:]
    return ()
```

- [ ] **Step 6: Scope completion freshness to `required_refresh`**

Extend, rather than replace, the current completion interface:

```python
def inspect_reporter_completion(
    data_dir: str | Path,
    previous_state: ReporterOutputState | None = None,
    *,
    required_refresh: tuple[str, ...] = (),
) -> dict[str, Any]:
```

Compute `invalid_outputs` from `_reporter_artifact_validity`, and compute stale outputs only from the requested names:

```python
stale_outputs = [
    name
    for name in required_refresh
    if name in (previous_state or {})
    and current_state.get(name) == previous_state[name]
]
complete = (
    not missing_outputs
    and not invalid_outputs
    and not stale_outputs
    and status == "passed"
    and final_error_count == 0
)
```

Retain `missing_outputs`, guardrail fields, parse-error reporting, and add `invalid_outputs` and `required_refresh` to the returned audit dict.

- [ ] **Step 7: Replace the old global-staleness assertion**

Change `test_inspect_reporter_completion_treats_identical_rewrite_as_stale` so identical valid preserved files are accepted when `required_refresh=()`, and add a second assertion proving only an explicitly requested identical HTML is stale:

```python
assert inspect_reporter_completion(tmp_path, previous)["complete"] is True

refresh_result = inspect_reporter_completion(
    tmp_path,
    previous,
    required_refresh=("CCI_Analysis_Report.html",),
)
assert refresh_result["stale_outputs"] == ["CCI_Analysis_Report.html"]
```

- [ ] **Step 8: Run Task 1 tests**

Run:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py -k \
  'required_reporter_refresh or inspect_reporter_completion'
```

Expected: PASS.

- [ ] **Step 9: Commit Task 1**

```bash
git add src/agents/deep_interpreter/reporter_recovery.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py
git commit \
  -m "Separate Reporter validity from refresh responsibility" \
  -m "Model the downstream invalidation suffix so valid preserved artifacts no longer fail global freshness." \
  -m $'Constraint: Keep SHA identity for explicitly refresh-required artifacts\nRejected: Add validation/targets exemptions | A dependency suffix covers every partial state\nConfidence: high\nScope-risk: narrow\nDirective: Do not reintroduce freshness checks for artifacts outside required_refresh\nTested: Reporter artifact validity and refresh-scope tests\nNot-tested: Finalizer wiring and live replay'
```

---

### Task 2: Expose one structured deterministic finalizer

**Files:**
- Modify: `src/agents/deep_interpreter/tools/report.py:1062-1185,1531-1619`
- Modify: `tests/deep_interpreter/test_comprehensive_template_report.py:142-460`

**Interfaces:**
- Consumes: `_run_synthesis_guardrail_before_html`, `_ensure_reporter_artifacts`, `_generate_html_report_impl`, ordered `required_refresh`
- Produces: `_finalize_reporter_artifacts(*, parts, output_path, data_dir, required_refresh) -> dict[str, Any]`; backward-compatible `generate_html_report(...) -> str`

- [ ] **Step 1: Write failing structured-finalizer tests**

Add three focused tests:

1. HTML-only refresh preserves validation and targets byte-for-byte.
2. Invalid-validation cascade replaces validation, targets, and HTML.
3. Guardrail failure returns structured `guardrail_failed` and does not render HTML.

Use the existing fixture and monkeypatch pattern. The first test's core assertion is:

```python
before = {
    name: (tmp_path / name).read_bytes()
    for name in ("synthesis_validation.json", "synthesis_targets.json")
}
result = report_tool._finalize_reporter_artifacts(
    parts={"template_mode": "comprehensive"},
    output_path="CCI_Analysis_Report.html",
    data_dir=str(tmp_path),
    required_refresh=("CCI_Analysis_Report.html",),
)

assert result["status"] == "passed"
assert result["required_refresh"] == ["CCI_Analysis_Report.html"]
assert (tmp_path / "CCI_Analysis_Report.html").is_file()
for name, content in before.items():
    assert (tmp_path / name).read_bytes() == content
```

- [ ] **Step 2: Run the new helper test and confirm RED**

Run:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/deep_interpreter/test_comprehensive_template_report.py -k \
  'structured_finalizer or refreshes_invalid_validation'
```

Expected: FAIL because `_finalize_reporter_artifacts` does not exist.

- [ ] **Step 3: Implement the structured helper around existing code**

Keep the public tool a thin formatter. The helper must materialize synthesis, run the current guardrail once, broaden refresh if synthesis changed, remove only refresh-required derived files, regenerate sidecars through `_ensure_reporter_artifacts`, and render only when HTML is requested:

```python
_REPORTER_DERIVED_OUTPUTS = (
    "synthesis_validation.json",
    "synthesis_targets.json",
    "CCI_Analysis_Report.html",
)


def _finalize_reporter_artifacts(
    *,
    parts: dict,
    output_path: str,
    data_dir: str,
    required_refresh: tuple[str, ...],
) -> dict[str, Any]:
    resolved_data_dir = str(Path(data_dir).expanduser().resolve())
    resolved_output = output_path
    if not os.path.isabs(resolved_output):
        resolved_output = os.path.join(resolved_data_dir, resolved_output)

    _materialize_synthesis_for_guardrail(parts, resolved_data_dir)
    synthesis_path = Path(resolved_data_dir) / "synthesis.md"
    before_synthesis = synthesis_path.read_bytes() if synthesis_path.is_file() else None
    guardrail_result = _run_synthesis_guardrail_before_html(resolved_data_dir)
    refresh = list(required_refresh)

    if guardrail_result is None or guardrail_result.get("status") in {"failed", "skipped"}:
        return {
            "status": "guardrail_failed",
            "guardrail": guardrail_result,
            "required_refresh": refresh,
            "refreshed_outputs": [],
            "preserved_outputs": [],
            "render_message": None,
        }

    after_synthesis = synthesis_path.read_bytes() if synthesis_path.is_file() else None
    if before_synthesis != after_synthesis:
        refresh = list(_REPORTER_DERIVED_OUTPUTS)

    for name in refresh:
        if name != "CCI_Analysis_Report.html":
            (Path(resolved_data_dir) / name).unlink(missing_ok=True)
    reporter_artifacts = _ensure_reporter_artifacts(resolved_data_dir, guardrail_result)

    render_message = None
    if "CCI_Analysis_Report.html" in refresh:
        Path(resolved_output).unlink(missing_ok=True)
        render_message = _generate_html_report_impl(
            parts=parts,
            output_path=resolved_output,
            data_dir=resolved_data_dir,
        )
    render_failed = (
        render_message is not None
        and (
            render_message.startswith("Error generating report:")
            or not Path(resolved_output).is_file()
            or Path(resolved_output).stat().st_size == 0
        )
    )
    return {
        "status": "render_failed" if render_failed else "passed",
        "guardrail": guardrail_result,
        "required_refresh": refresh,
        "refreshed_outputs": refresh,
        "preserved_outputs": [
            name for name in _REPORTER_DERIVED_OUTPUTS if name not in refresh
        ],
        "reporter_artifacts": reporter_artifacts,
        "render_message": render_message,
    }
```

- [ ] **Step 4: Delegate the public tool to the helper**

Keep the current tool arguments and returned text. It always requests HTML rendering and requests missing sidecars; then format the structured result:

```python
requested = tuple(
    name
    for name in ("synthesis_validation.json", "synthesis_targets.json")
    if not (Path(resolved_data_dir) / name).is_file()
) + ("CCI_Analysis_Report.html",)
finalization = _finalize_reporter_artifacts(
    parts=parts,
    output_path=output_path,
    data_dir=resolved_data_dir,
    required_refresh=requested,
)
```

For `guardrail_failed`, return the current `Error generating report: synthesis guardrail failed...` text. For passed/render-failed results, retain the existing report, guardrail, and reporter-artifact message layout so external callers do not need changes.

- [ ] **Step 5: Update the existing preservation test narrowly**

Keep `test_generate_html_report_preserves_existing_reporter_artifacts`; it must still prove valid sidecars remain unchanged when guardrail does not change synthesis. Do not weaken it to existence-only assertions.

- [ ] **Step 6: Run the report-tool suite**

Run:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/deep_interpreter/test_comprehensive_template_report.py
```

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/agents/deep_interpreter/tools/report.py \
  tests/deep_interpreter/test_comprehensive_template_report.py
git commit \
  -m "Give Reporter finalization one structured execution path" \
  -m "Share the existing guardrail and renderer without parsing tool prose or duplicating HTML logic." \
  -m $'Constraint: Preserve the public generate_html_report contract\nRejected: Parse the tool return string | Recovery needs structured status, not prose coupling\nConfidence: high\nScope-risk: moderate\nDirective: Refresh only the requested downstream suffix unless guardrail changes synthesis\nTested: Comprehensive report finalizer and compatibility tests\nNot-tested: Recovery-loop integration and live replay'
```

---

### Task 3: Finalize valid synthesis before any recovery decision

**Files:**
- Modify: `src/agents/deep_interpreter/reporter_recovery.py:231-325`
- Modify: `tests/agents/deep_interpreter/test_reporter_recovery.py:242-455`

**Interfaces:**
- Consumes: `_required_reporter_refresh`, `_finalize_reporter_artifacts`, `inspect_reporter_completion`
- Produces: `ReporterFinalizer`, `_default_reporter_finalizer`, `run_reporter_with_recovery(..., finalize=None)` with post-attempt deterministic completion

- [ ] **Step 1: Write the full state-D orchestration regression**

Pre-populate valid synthesis/validation/targets, leave HTML missing, make the LLM invoke return without rewriting files, and inject a fake finalizer that writes only HTML:

```python
@pytest.mark.asyncio
async def test_reporter_finalization_renders_missing_html_without_rewriting_valid_sidecars(
    tmp_path: Path,
) -> None:
    _write_valid_synthesis(tmp_path)
    _write_valid_validation(tmp_path)
    _write_valid_targets(tmp_path)
    before = _reporter_output_state(tmp_path)
    prompts: list[str] = []
    finalizer_calls: list[tuple[str, ...]] = []

    async def invoke(description: str) -> dict[str, str]:
        prompts.append(description)
        return {"content": "done"}

    async def finalize(root: Path, required: tuple[str, ...]) -> dict[str, Any]:
        finalizer_calls.append(required)
        (root / "CCI_Analysis_Report.html").write_text(
            "<!DOCTYPE html><html><body>ok</body></html>",
            encoding="utf-8",
        )
        return {
            "status": "passed",
            "guardrail": {"status": "passed", "final_error_count": 0},
            "required_refresh": list(required),
            "refreshed_outputs": list(required),
            "preserved_outputs": [
                "synthesis_validation.json",
                "synthesis_targets.json",
            ],
        }

    result = await run_reporter_with_recovery(
        invoke=invoke,
        finalize=finalize,
        initial_description="report",
        data_dir=tmp_path,
        timeout_seconds=1,
    )

    assert result == {"content": "done"}
    assert prompts == ["report"]
    assert finalizer_calls == [("CCI_Analysis_Report.html",)]
    after = _reporter_output_state(tmp_path)
    for name in ("synthesis.md", "synthesis_validation.json", "synthesis_targets.json"):
        assert after[name] == before[name]
```

- [ ] **Step 2: Run state D and confirm RED**

Run:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py::test_reporter_finalization_renders_missing_html_without_rewriting_valid_sidecars
```

Expected: FAIL because `run_reporter_with_recovery` does not accept `finalize` and still enters attempt 2.

- [ ] **Step 3: Add C/E/F/K/L orchestration tests**

Add separate tests with one behavioral assertion each:

- C: valid synthesis only -> one LLM attempt, finalizer receives all three derived outputs.
- E: all artifacts valid -> one LLM attempt, zero finalizer calls.
- F: invalid validation -> one LLM attempt, finalizer receives validation/targets/HTML.
- K: invalid targets -> one LLM attempt, finalizer receives targets/HTML.
- L: invalid HTML -> one LLM attempt, finalizer receives HTML.

Each test must assert `recovery_used is False` and `attempt_count == 1` in `reporter_recovery.json`.

- [ ] **Step 4: Add the finalizer callable and default adapter**

Use the existing injected-`invoke` style rather than a new object:

```python
ReporterFinalizer = Callable[
    [Path, tuple[str, ...]],
    Awaitable[dict[str, Any]],
]


async def _default_reporter_finalizer(
    data_dir: Path,
    required_refresh: tuple[str, ...],
) -> dict[str, Any]:
    from src.agents.deep_interpreter.tools.report import _finalize_reporter_artifacts

    return await asyncio.to_thread(
        _finalize_reporter_artifacts,
        parts={"template_mode": "comprehensive"},
        output_path="CCI_Analysis_Report.html",
        data_dir=str(data_dir),
        required_refresh=required_refresh,
    )
```

Extend the run-loop signature:

```python
async def run_reporter_with_recovery(
    *,
    invoke: Callable[[str], Awaitable[T]],
    initial_description: str,
    data_dir: str | Path,
    timeout_seconds: float | None = None,
    finalize: ReporterFinalizer | None = None,
) -> T:
    finalizer = finalize or _default_reporter_finalizer
```

- [ ] **Step 5: Run finalization inside the logical attempt**

Refactor the repeated timeout/exception/else completion code into one attempt outcome path. After `invoke` returns:

```python
current_state = _reporter_output_state(root)
synthesis_changed = previous_state.get("synthesis.md") != current_state.get("synthesis.md")
if _valid_existing_synthesis(root):
    required_refresh = _required_reporter_refresh(
        root,
        synthesis_changed=synthesis_changed,
    )
    pre_finalizer_state = _reporter_output_state(root)
    if required_refresh:
        finalization = await finalizer(root, required_refresh)
        required_refresh = tuple(finalization.get("required_refresh", required_refresh))
    completion = inspect_reporter_completion(
        root,
        pre_finalizer_state,
        required_refresh=required_refresh,
    )
```

Record `required_refresh` and structured `finalizer` under the attempt. If finalizer status is `render_failed`, write the failed audit and raise `ReporterRecoveryError` immediately; do not enter attempt 2.

- [ ] **Step 6: Remove the old preserved-synthesis second-attempt test**

Replace `test_reporter_recovery_preserves_valid_synthesis_and_renders_once`, which expects two LLM prompts, with state C/D tests that expect one prompt and one deterministic finalizer call.

- [ ] **Step 7: Run Reporter recovery tests**

Run:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py -k \
  'finalization or completion or required_reporter_refresh'
```

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add src/agents/deep_interpreter/reporter_recovery.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py
git commit \
  -m "Finish valid Reporter synthesis without another LLM attempt" \
  -m "Run refresh-scoped finalization before recovery so missing HTML cannot become a false failure." \
  -m $'Constraint: Finalizer calls do not increment Reporter attempt_count\nRejected: Keep the preserve-synthesis recovery prompt | Valid synthesis no longer needs LLM recovery\nConfidence: high\nScope-risk: moderate\nDirective: Deterministic finalization must precede every recovery decision\nTested: Reporter states C, D, E, F, K, and L\nNot-tested: Guardrail-exhaustion recovery, timeout carrier, and live replay'
```

---

### Task 4: Restrict clean recovery to synthesis failure

**Files:**
- Modify: `src/agents/deep_interpreter/reporter_recovery.py:129-228,252-325`
- Modify: `tests/agents/deep_interpreter/test_reporter_recovery.py:242-616`

**Interfaces:**
- Consumes: finalizer `guardrail_failed` status, `synthesis_guardrail_final.json`, attempt-1 synthesis digest
- Produces: synthesis-only `build_reporter_recovery_message`, clean `_prepare_synthesis_retry`, actions `absent`, `quarantined_invalid`, `quarantined_guardrail_failed`

- [ ] **Step 1: Write state J RED**

Inject a finalizer that returns guardrail failure on attempt 1, writes a final issue file with one hard code, and passes on attempt 2. Assert that attempt 2 starts with no working synthesis or derived outputs:

```python
@pytest.mark.asyncio
async def test_reporter_recovery_retries_after_guardrail_repairs_are_exhausted(
    tmp_path: Path,
) -> None:
    prompts: list[str] = []

    async def invoke(description: str) -> dict[str, str]:
        prompts.append(description)
        assert not (tmp_path / "synthesis.md").exists() or len(prompts) == 1
        _write_valid_synthesis(tmp_path, text=f"# Synthesis {len(prompts)}\n\n## Summary\n\nText.\n")
        return {"content": f"attempt-{len(prompts)}"}

    async def finalize(root: Path, required: tuple[str, ...]) -> dict[str, Any]:
        if len(prompts) == 1:
            (root / "synthesis_guardrail_final.json").write_text(
                json.dumps(
                    {
                        "issues": [
                            {
                                "severity": "error",
                                "code": "synthesis_consistency_mismatch",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            return {
                "status": "guardrail_failed",
                "guardrail": {"status": "failed", "final_error_count": 1},
                "required_refresh": list(required),
            }
        _write_valid_validation(root)
        _write_valid_targets(root)
        _write_valid_html(root)
        return {
            "status": "passed",
            "guardrail": {"status": "passed", "final_error_count": 0},
            "required_refresh": list(required),
        }

    result = await run_reporter_with_recovery(
        invoke=invoke,
        finalize=finalize,
        initial_description="report",
        data_dir=tmp_path,
        timeout_seconds=1,
    )

    assert result == {"content": "attempt-2"}
    audit = json.loads((tmp_path / "reporter_recovery.json").read_text())
    assert audit["retry_preparation"]["action"] == "quarantined_guardrail_failed"
    assert audit["retry_preparation"]["failure_codes"] == [
        "synthesis_consistency_mismatch"
    ]
```

- [ ] **Step 2: Run state J and confirm RED**

Run:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py::test_reporter_recovery_retries_after_guardrail_repairs_are_exhausted
```

Expected: FAIL because current retry preparation preserves Markdown instead of quarantining guardrail-exhausted synthesis.

- [ ] **Step 3: Make the recovery message synthesis-only**

Remove `preserve_synthesis` and the downstream-render branch from `build_reporter_recovery_message`. The message must instruct a clean synthesis write and stop:

```python
def build_reporter_recovery_message(
    data_dir: Path,
    *,
    failure_codes: tuple[str, ...] = (),
) -> str:
    failure_note = (
        f"The invalid attempt was quarantined after: {', '.join(failure_codes)}.\n"
        if failure_codes
        else ""
    )
    return f"""[REPORTER_RECOVERY]
The previous REPORTER synthesis attempt for {data_dir} was absent or invalid.
Start from a fresh message context and rebuild synthesis from the existing artifacts.

Read /part1_final.md, /part2_final.md, /part3_final.md,
/part4_therapeutic_synthesis.md when present, /drug.md when present, and /papers.json.
Use only the already-bound part_name="all" RAG collection.
Do not call prepare_rag_literature or run a new literature search.
{failure_note}Write a complete Markdown document to /synthesis.md.
Stop after /synthesis.md is written. Deterministic code owns guardrail and HTML finalization.
"""
```

- [ ] **Step 4: Clear all derived outputs before a clean synthesis attempt**

Add one small helper and use it for absent, non-Markdown, and guardrail-exhausted states:

```python
def _clear_derived_reporter_outputs(data_dir: Path) -> None:
    for name in DERIVED_REPORTER_OUTPUTS:
        (data_dir / name).unlink(missing_ok=True)
```

Extend `_prepare_synthesis_retry` to accept `guardrail_failed: bool = False`. When true, collect all severity-error codes from `synthesis_guardrail_final.json`, snapshot synthesis, unlink it, clear derived outputs, and return `quarantined_guardrail_failed`. For absent synthesis, clear derived outputs and keep `attempt1_synthesis_sha256=None`.

- [ ] **Step 5: Keep B/G/I audit behavior**

Update the existing invalid-synthesis tests to assert:

- Attempt 2 prompt does not mention `generate_html_report`.
- Attempt 2 begins without synthesis/validation/targets/HTML.
- All deterministic and semantic hard failure codes remain ordered.
- Byte-identical invalid attempt 2 still sets `repeated_invalid_synthesis=True`.
- Attempt-2 exception retains attempt-1 quarantine plus `exception_type` and `exception_repr`.

- [ ] **Step 6: Add state A**

Add `test_reporter_recovery_retries_when_synthesis_is_absent`: attempt 1 returns without Reporter outputs; attempt 2 writes valid synthesis; injected finalizer writes downstream outputs. Assert two LLM attempts, `retry_preparation.action == "absent"`, and final status passed.

- [ ] **Step 7: Run synthesis recovery tests**

Run:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py -k \
  'guardrail_repairs_are_exhausted or synthesis_is_absent or invalid or raises'
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

```bash
git add src/agents/deep_interpreter/reporter_recovery.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py
git commit \
  -m "Reserve Reporter recovery for failed synthesis" \
  -m "Quarantine absent, non-Markdown, or guardrail-exhausted synthesis and let code own every downstream artifact." \
  -m $'Constraint: Keep two LLM attempts and every hard failure code\nRejected: Preserve guardrail-failed Markdown | Recovery must regenerate synthesis, not render it\nConfidence: high\nScope-risk: moderate\nDirective: Downstream incompleteness must never set recovery_used\nTested: Reporter states A, B, G, I, and J\nNot-tested: Sync timeout carrier and live replay'
```

---

### Task 5: Preserve a real result across sync timeout settlement

**Files:**
- Modify: `src/agents/deep_interpreter/reporter_recovery.py:33-38,231-325,390-424`
- Modify: `tests/agents/deep_interpreter/test_reporter_recovery.py:456-509`

**Interfaces:**
- Consumes: generic attempt result `T`, protected sync handler future, finalizer result
- Produces: private `_ReporterAttemptTimedOutWithResult`, timeout audit with no concurrent writer, state H success without fabricated return values

- [ ] **Step 1: Replace H with the approved late-valid-synthesis behavior**

Update the sync timeout test so attempt 1 sleeps beyond the deadline, writes valid synthesis, returns a real `ToolMessage`, and the injected finalizer creates downstream outputs. Assert:

```python
assert attempts == 1
assert response.content == "attempt-1-result"
assert events == [
    "attempt-1-start",
    "attempt-1-finish",
    "finalizer-start",
    "finalizer-finish",
]
audit = json.loads((tmp_path / "reporter_recovery.json").read_text())
assert audit["attempts"][0]["timed_out"] is True
assert audit["status"] == "passed"
assert audit["recovery_used"] is False
```

- [ ] **Step 2: Run H and confirm RED**

Run:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py::test_reporter_task_recovery_middleware_waits_for_timed_out_sync_reporter
```

Expected: FAIL because the current cancellation path discards the attempt-1 result and starts attempt 2.

- [ ] **Step 3: Add the private timeout result carrier**

Keep it private and dict-free because it is control flow, not persisted domain state:

```python
class _ReporterAttemptTimedOutWithResult(TimeoutError):
    def __init__(self, result: Any, finalization: dict[str, Any] | None = None) -> None:
        super().__init__("REPORTER attempt timed out after producing a result")
        self.result = result
        self.finalization = finalization
```

- [ ] **Step 4: Preserve sync handler results on cancellation**

In `ReporterTaskRecoveryMiddleware.wrap_tool_call`'s inner `invoke`:

```python
try:
    return await asyncio.shield(wrapped_future)
except asyncio.CancelledError as exc:
    result = await wrapped_future
    raise _ReporterAttemptTimedOutWithResult(result) from exc
```

Keep `executor.shutdown(wait=True, cancel_futures=True)`.

- [ ] **Step 5: Protect an in-flight finalizer and carry the LLM result**

When a finalizer is required, create one task and shield it. If the logical attempt is cancelled after the LLM returned, drain the finalizer and raise the same carrier with both the real LLM result and settled finalization:

```python
finalizer_task = asyncio.create_task(finalizer(root, required_refresh))
try:
    finalization = await asyncio.shield(finalizer_task)
except asyncio.CancelledError as exc:
    finalization = await finalizer_task
    raise _ReporterAttemptTimedOutWithResult(result, finalization) from exc
```

Catch `_ReporterAttemptTimedOutWithResult` before `TimeoutError`, set `timed_out=True`, reuse its real result/finalization, and run no second finalizer call. If completion passes, return the carried result.

- [ ] **Step 6: Add a no-result timeout assertion**

Keep a separate async timeout test showing that valid files without a real generic `T` do not produce a fabricated success. Assert the timeout audit is written and the real `TimeoutError` propagates.

- [ ] **Step 7: Run timeout and exception tests**

Run:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py -k 'timeout or raises'
```

Expected: PASS and no sleep-based overlap after the middleware returns.

- [ ] **Step 8: Commit Task 5**

```bash
git add src/agents/deep_interpreter/reporter_recovery.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py
git commit \
  -m "Keep Reporter timeout settlement usable" \
  -m "Return the real late sync result after deterministic completion without allowing concurrent retry writes." \
  -m $'Constraint: Never fabricate the generic Reporter result type\nRejected: Start attempt 2 to obtain a return value | Valid synthesis is not recovery work\nConfidence: high\nScope-risk: moderate\nDirective: Drain every protected writer before another attempt can start\nTested: Sync late-write, no-result timeout, and attempt-exception tests\nNot-tested: Live Reporter timeout behavior'
```

---

### Task 6: Remove HTML orchestration from the Reporter LLM

**Files:**
- Modify: `src/agents/deep_interpreter/subagents/configs.py:1-31,131-161`
- Modify: `src/agents/deep_interpreter/subagents/prompts.py:914-1079,1090-1140`
- Modify: `scripts/run_deep_interpreter_agent.py:162-172`
- Modify: `tests/deep_interpreter/test_reporter_prompt_policy.py:166-199`
- Modify: `tests/test_run_deep_interpreter_agent_cli.py:68-75`
- Modify: `tests/test_reporter.py:60-110`
- Modify: `tests/test_reporter_phase5.py:67-105`

**Interfaces:**
- Consumes: deterministic finalizer attached by the recovery wrapper
- Produces: Reporter tool list without `generate_html_report`; synthesis-only system/recovery/standalone instructions; unchanged overall four-output stage contract

- [ ] **Step 1: Write prompt/tool RED assertions**

Replace the current Phase 5 expectations with:

```python
from src.agents.deep_interpreter.subagents.configs import SUBAGENT_CONFIGS


def test_reporter_hands_finalization_to_wrapper_code():
    block = _extract_phase5_block()

    assert "deterministic finalizer" in block.lower()
    assert "stop after" in block.lower()
    assert "synthesis.md" in block
    assert "generate_html_report(" not in block


def test_reporter_tool_list_excludes_html_orchestration():
    names = {
        getattr(tool, "name", getattr(tool, "__name__", ""))
        for tool in SUBAGENT_CONFIGS["reporter"]["tools"]
    }
    assert "generate_html_report" not in names
```

Update the CLI-message test to require `write_file("/synthesis.md"...)`, forbid `generate_html_report`, and name deterministic code as the owner of validation/targets/HTML.

- [ ] **Step 2: Run prompt tests and confirm RED**

Run:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/deep_interpreter/test_reporter_prompt_policy.py \
  tests/test_run_deep_interpreter_agent_cli.py \
  tests/test_reporter.py \
  tests/test_reporter_phase5.py
```

Expected: FAIL because the Reporter still owns `generate_html_report` orchestration.

- [ ] **Step 3: Remove the report tool only from the Reporter subagent**

Delete `generate_html_report` from `SUBAGENT_CONFIGS["reporter"]["tools"]`. Do not remove the public tool from `tools/__init__.py` or the main agent tool list; other callers retain compatibility.

- [ ] **Step 4: Replace Reporter Phase 5 with a deterministic handoff**

Keep all synthesis/RAG/Part 4 instructions. Replace the tool call block with concise ownership text:

```text
### Phase 5: Hand Off to Deterministic Finalization

Confirm `/synthesis.md` is a complete Markdown document, then stop.
Do not call `generate_html_report` and do not write
`/synthesis_validation.json`, `/synthesis_targets.json`, or HTML.
The Reporter wrapper runs the synthesis guardrail, refreshes deterministic
bookkeeping artifacts, and renders `CCI_Analysis_Report.html` after you return.
```

Update critical rules accordingly. Do not change RAG queries, validation calls, or synthesis content requirements.

- [ ] **Step 5: Update standalone and manual Reporter messages**

In `scripts/run_deep_interpreter_agent.py`, replace lines 168-171 with the same synthesis-only stop rule. Update `tests/test_reporter.py` and `tests/test_reporter_phase5.py` message fixtures so they no longer command tool-driven HTML generation.

- [ ] **Step 6: Run prompt/tool tests**

Run:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/deep_interpreter/test_reporter_prompt_policy.py \
  tests/test_run_deep_interpreter_agent_cli.py \
  tests/test_reporter.py \
  tests/test_reporter_phase5.py
```

Expected: PASS.

- [ ] **Step 7: Run import/config smoke tests**

Run:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/agents/deep_interpreter/test_reporter_recovery.py::test_deep_interpreter_agent_attaches_reporter_recovery_middleware \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py -k reporter_recovery_enabled
```

Expected: PASS; both standalone and embedded wrappers still attach recovery/finalization.

- [ ] **Step 8: Commit Task 6**

```bash
git add src/agents/deep_interpreter/subagents/configs.py \
  src/agents/deep_interpreter/subagents/prompts.py \
  scripts/run_deep_interpreter_agent.py \
  tests/deep_interpreter/test_reporter_prompt_policy.py \
  tests/test_run_deep_interpreter_agent_cli.py \
  tests/test_reporter.py \
  tests/test_reporter_phase5.py
git commit \
  -m "Keep Reporter LLM focused on synthesis" \
  -m "Remove downstream tool orchestration from the model so code deterministically owns guardrail, sidecars, and HTML." \
  -m $'Constraint: Preserve Reporter RAG and synthesis-content instructions\nRejected: Leave generate_html_report available but discourage it | Tool removal enforces the ownership boundary\nConfidence: high\nScope-risk: narrow\nDirective: Reporter prompts must stop after synthesis.md is written\nTested: Reporter prompt, config, CLI, and wrapper attachment tests\nNot-tested: Live model compliance'
```

---

### Task 7: Run the full regression gate and independent code review

**Files:**
- Verify: all modified production/test files
- Read: `docs/superpowers/specs/2026-08-25-reporter-deterministic-finalization-design.md`
- Read: `docs/superpowers/plans/2026-08-25-reporter-deterministic-finalization.md`

**Interfaces:**
- Consumes: Tasks 1-6 commits
- Produces: fresh unit/integration/static-analysis evidence and an independent review verdict

- [ ] **Step 1: Run the complete targeted regression suite**

Run:

```bash
OPENAI_API_KEY=test LANGCHAIN_TRACING_V2=false uv run pytest -q \
  tests/scripts/test_validate_report.py \
  tests/scripts/test_validate_repair_report.py \
  tests/scripts/test_repair_report.py \
  tests/agents/deep_interpreter/test_claim_rag_validation.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py \
  tests/agents/deep_interpreter/test_report_guardrail_middleware.py \
  tests/deep_interpreter/test_comprehensive_template_report.py \
  tests/deep_interpreter/test_reporter_prompt_policy.py \
  tests/test_run_deep_interpreter_agent_cli.py \
  tests/test_reporter.py \
  tests/test_reporter_phase5.py \
  tests/test_sni_ablation_runner.py
```

Expected: all tests PASS with no changed attempt-count, timeout, RAG, SNI, Claim-RAG, or guardrail expectations.

- [ ] **Step 2: Run static checks**

Run:

```bash
uv run ruff check \
  src/agents/deep_interpreter/reporter_recovery.py \
  src/agents/deep_interpreter/tools/report.py \
  src/agents/deep_interpreter/subagents/configs.py \
  src/agents/deep_interpreter/subagents/prompts.py \
  scripts/run_deep_interpreter_agent.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py \
  tests/deep_interpreter/test_comprehensive_template_report.py \
  tests/deep_interpreter/test_reporter_prompt_policy.py \
  tests/test_run_deep_interpreter_agent_cli.py

uv run python -m py_compile \
  src/agents/deep_interpreter/reporter_recovery.py \
  src/agents/deep_interpreter/tools/report.py \
  src/agents/deep_interpreter/subagents/configs.py \
  src/agents/deep_interpreter/subagents/prompts.py \
  scripts/run_deep_interpreter_agent.py \
  tests/agents/deep_interpreter/test_reporter_recovery.py

git diff --check
```

Expected: every command exits 0.

- [ ] **Step 3: Inspect scope and invariants**

Run:

```bash
git diff 22440a6 --stat
git diff 22440a6 -- \
  src/agents/deep_interpreter/reporter_recovery.py \
  src/agents/deep_interpreter/tools/report.py \
  src/agents/deep_interpreter/subagents/configs.py \
  src/agents/deep_interpreter/subagents/prompts.py \
  scripts/run_deep_interpreter_agent.py
rg -n 'MAX_REPORTER_ATTEMPTS|REPORTER_ATTEMPT_TIMEOUT_SECONDS|MAX_GUARDRAIL_REPAIR_PASSES' \
  src/agents/deep_interpreter/reporter_recovery.py \
  src/agents/deep_interpreter/report_guardrails.py
```

Expected: only planned Reporter surfaces changed; constants remain 2, unchanged timeout handling, and 3 repair passes.

- [ ] **Step 4: Request independent code review**

Require the reviewer to check:

- state D preserves valid sidecars and succeeds after HTML-only refresh;
- missing/invalid downstream artifacts never trigger LLM attempt 2;
- J quarantines guardrail-exhausted Markdown and retains remaining hard codes;
- H returns a real late result and permits no overlapping writers;
- prompt/tool ownership matches the spec;
- public `generate_html_report` behavior remains compatible;
- no RAG/SNI/Claim-RAG/timeout/attempt-count/Part changes escaped scope.

If review reports Critical or Important findings, add one failing regression per finding, apply only the necessary fix, rerun Steps 1-3, and request re-review.

- [ ] **Step 5: Commit review-driven fixes only if needed**

Use a separate Lore commit naming the rejected behavior, test evidence, and remaining gaps. Do not squash away the TDD history during implementation.

---

### Task 8: Run Reporter-only replay on the failed no-SNI copy

**Files:**
- Read/copy: `res/deep_interpreter/bc/sni_repair_ablation/post_recovery_retry_pair06_20260825T033933Z/pairs/pair-06/wiki-off/`
- Execute: `scripts/run_deep_interpreter_agent.py --subagent reporter`
- Create runtime evidence: one validated `/tmp/deepmast-reporter-finalization-pair06.*` directory

**Interfaces:**
- Consumes: verified implementation and the latest failed no-SNI artifacts
- Produces: Reporter exit 0, one-attempt deterministic completion evidence, valid artifacts, unchanged Part hashes, untouched original directory

- [ ] **Step 1: Verify external prerequisites without changing state**

Check the configured Ollama and RAG endpoints before creating the replay copy:

```bash
curl --fail --silent --show-error http://localhost:6000/api/tags >/dev/null
curl --fail --silent --show-error http://localhost:8883/health >/dev/null
```

If an endpoint is unavailable, record the exact failure and stop before claiming live replay completion. Do not substitute a full pair run.

- [ ] **Step 2: Create and validate an isolated copy**

Run:

```bash
REPORTER_REPLAY_ROOT=$(mktemp -d /tmp/deepmast-reporter-finalization-pair06.XXXXXX)
case "$REPORTER_REPLAY_ROOT" in
  /tmp/deepmast-reporter-finalization-pair06.*) ;;
  *) exit 2 ;;
esac
rsync -a \
  res/deep_interpreter/bc/sni_repair_ablation/post_recovery_retry_pair06_20260825T033933Z/pairs/pair-06/wiki-off/ \
  "$REPORTER_REPLAY_ROOT/"
```

Record the printed absolute path in the execution report.

- [ ] **Step 3: Preserve hashes and reproduce state D in the copy**

Run:

```bash
shasum -a 256 \
  "$REPORTER_REPLAY_ROOT/part1_final.md" \
  "$REPORTER_REPLAY_ROOT/part2_final.md" \
  "$REPORTER_REPLAY_ROOT/part3_final.md" \
  > "$REPORTER_REPLAY_ROOT/parts.before.sha256"

shasum -a 256 \
  "$REPORTER_REPLAY_ROOT/synthesis.md" \
  "$REPORTER_REPLAY_ROOT/synthesis_validation.json" \
  "$REPORTER_REPLAY_ROOT/synthesis_targets.json" \
  > "$REPORTER_REPLAY_ROOT/reporter.before.sha256"

rm -f \
  "$REPORTER_REPLAY_ROOT/CCI_Analysis_Report.html" \
  "$REPORTER_REPLAY_ROOT/reporter_recovery.json" \
  "$REPORTER_REPLAY_ROOT/synthesis_reporter_attempt1.md"
```

The validated `/tmp` copy is the only deletion target. Do not alter the original pair directory.

- [ ] **Step 4: Run Reporter only with the unchanged no-SNI settings**

Run:

```bash
OPENAI_API_KEY=test \
LANGCHAIN_TRACING_V2=false \
LLM_PROVIDER=ollama \
LLM_MODEL=qwen3.5:122b \
OLLAMA_MODEL=qwen3.5:122b \
OLLAMA_BASE_URL=http://localhost:6000 \
OLLAMA_HOST=http://localhost:6000 \
OLLAMA_REASONING=true \
OLLAMA_REQUEST_TIMEOUT_SECONDS=10800 \
REPORTER_ATTEMPT_TIMEOUT_SECONDS=10800 \
CCI_RAG_BASE_URL=http://localhost:8883 \
DEEP_INTERPRETER_FIXED_COLLECTION_ID=a208e916-bd32-405a-9eee-de4cd82b2a3b \
DEEP_INTERPRETER_REQUIRE_AGENTIC_RAG=true \
DEEP_INTERPRETER_USE_WIKI_CONTEXT=false \
uv run python scripts/run_deep_interpreter_agent.py \
  --subagent reporter \
  --data-dir "$REPORTER_REPLAY_ROOT" \
  --traceback
```

Expected: exit code 0. Do not launch Part, SNI, or no-SNI stages.

- [ ] **Step 5: Verify Reporter audit and artifacts**

Run:

```bash
jq -e '
  .status == "passed"
  and .attempt_count == 1
  and .recovery_used == false
  and .attempts[0].completion.complete == true
' "$REPORTER_REPLAY_ROOT/reporter_recovery.json"

head -n 1 "$REPORTER_REPLAY_ROOT/synthesis.md" | rg '^# '
jq -e '
  .synthesis_guardrail.status == "passed"
  and .synthesis_guardrail.final_error_count == 0
' "$REPORTER_REPLAY_ROOT/synthesis_validation.json"
jq -e 'type == "object"' "$REPORTER_REPLAY_ROOT/synthesis_targets.json"
test -s "$REPORTER_REPLAY_ROOT/CCI_Analysis_Report.html"
head -c 256 "$REPORTER_REPLAY_ROOT/CCI_Analysis_Report.html" | rg -i '<!doctype html'
tail -c 256 "$REPORTER_REPLAY_ROOT/CCI_Analysis_Report.html" | rg -i '</html>'
```

Expected: every command exits 0.

- [ ] **Step 6: Verify immutable Part inputs and original result**

Run:

```bash
shasum -a 256 \
  "$REPORTER_REPLAY_ROOT/part1_final.md" \
  "$REPORTER_REPLAY_ROOT/part2_final.md" \
  "$REPORTER_REPLAY_ROOT/part3_final.md" \
  > "$REPORTER_REPLAY_ROOT/parts.after.sha256"
diff -u \
  "$REPORTER_REPLAY_ROOT/parts.before.sha256" \
  "$REPORTER_REPLAY_ROOT/parts.after.sha256"

git status --short
git diff --check
```

Expected: Part hash diff is empty; the original `res/.../wiki-off` directory has not changed; source worktree contains only planned commits/changes.

- [ ] **Step 7: Report the replay boundary honestly**

Report:

- replay copy path;
- Reporter exit code and attempt/finalizer audit;
- synthesis/validation/targets/HTML validity;
- Part 1/2/3 before/after hash comparison;
- whether synthesis/validation/targets hashes were preserved or legitimately refreshed after LLM synthesis changes;
- original result untouched;
- full SNI/no-SNI pair not run.

Do not claim end-to-end pair completion from Reporter-only evidence.

---

## Self-review Checklist

- [ ] State D is the first RED test and proves valid unchanged sidecars can succeed.
- [ ] States A-L map to Tasks 1, 3, 4, and 5.
- [ ] Every finalizer result and callable name is defined before later tasks consume it.
- [ ] Recovery never handles renderer/bookkeeping failure.
- [ ] Timeout handling never fabricates generic result `T` and drains protected writers.
- [ ] Reporter LLM loses HTML orchestration without losing synthesis/RAG instructions.
- [ ] Public `generate_html_report` callers retain their string API.
- [ ] Regression commands cover Reporter, guardrails, Claim-RAG, SNI runner, prompt policy, timeout, and attempt count.
- [ ] Replay uses a validated temporary copy and never runs the full pair.
- [ ] No placeholder, speculative abstraction, new dependency, or unrelated cleanup remains.

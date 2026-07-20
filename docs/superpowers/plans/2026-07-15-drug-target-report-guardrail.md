# Drug Target Report Guardrail Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Drug Target production super-graph finalization path with an agent-authored `drug.md` that is validated, repaired up to three times, and published fail-closed by a report-writer middleware while preserving the Step 9.5 integration envelope.

**Architecture:** The production flow becomes `DrugReportRunCleanupMiddleware -> evidence_assessor -> report_writer -> DrugReportGuardrailMiddleware`. The run-start middleware removes stale success artifacts even if orchestration exits before the writer. The report writer persists `target_assessment.json` and a complete `drug.md`, including Section 4 hypotheses. The report guardrail treats that Markdown as the sole production hypothesis source, runs the existing finalization validator in an explicit agent-authored mode, performs bounded repair with the same report-writer prompt, and only then derives Part 4 and HTML outputs. The outer Drug Target super-graph and deterministic finalizer remain importable for benchmark/compatibility callers but leave the production graph and integration path.

**Tech Stack:** Python 3.12, DeepAgents, LangChain `AgentMiddleware`, LangGraph runnable export, Jinja2, pytest/pytest-asyncio, Ruff, Pyright.

## Target Runtime

```text
lr_candidates.json
        |
        v
DrugReportRunCleanupMiddleware (production run start)
        |
        v
evidence_assessor  -> evidence/*.json + assessment_results.json
        |
        v
report_writer      -> target_assessment.json + drug.md (Section 4 included)
        |
        v
DrugReportGuardrailMiddleware
        |-- validate -> repair (maximum 3 passes) -> validate
        |-- fail closed if hard errors remain
        `-- publish in memory -> Part 4 JSON/Markdown + drug_report.html
```

## Global Constraints

- Keep exactly two callable production domain subagents: `evidence_assessor` and `report_writer`. DeepAgents may internally register its automatic `general-purpose` spec, but guarded `task` calls must reject it before dispatch.
- Keep `src.agents.drug_target.graph_builder:drug_target_graph` as the `langgraph.json` export symbol.
- Preserve the integration envelope with exactly these keys and no additions: `success`, `drug_md`, `target_assessment`, `errors`, `evidence_truncated`.
- Preserve these successful-run files:
  - `drug.md`
  - `target_assessment.json`
  - `part4_candidate_selection.json`
  - `part4_therapeutic_synthesis.md`
  - `drug_report.html`
  - `drug_report_validation_initial.json`
  - `drug_report_validation_final.json`
- Do not read or write `report_data.json` or any `evidence/hypothesis_report*.json` artifact (raw, summarizer-sanitized, last-rejection, draft variants) anywhere in the new production path. Preserve raw/default tool behavior only for explicit legacy/direct callers.
- Treat the final repaired `drug.md` as the only production source for hypotheses. Convert parsed Markdown hypotheses to the legacy in-memory shape only at the publication boundary.
- Retain `[source: ...]` provenance annotations in the final direct-authored `drug.md`; do not claim a renderer cleanup step exists or mutate the report after its final validation audit.
- Preserve `MAX_DRUG_REPORT_REPAIR_PASSES = 3`. Stop early when validation passes or a repair leaves `drug.md` unchanged.
- In `agent_markdown` mode, classify a missing, unparseable, or field-incomplete Section 4 as an ordinary hard validation issue before publication so it receives the same bounded repair loop.
- Preserve unexpanded `<!-- EXPAND: ... -->` markers when `save_drug_md` is called by default. A leftover marker must remain visible to deterministic validation instead of being silently stripped into a blank section; legacy callers that intentionally want stripping must opt in explicitly.
- Treat warnings as non-blocking. Missing/invalid input evidence, missing required artifacts, or invalid `target_assessment.json` are non-repairable and fail immediately.
- If hard report errors remain after repair, or Part 4/HTML publication raises, fail the whole assessment. Keep `drug.md` and both audit files for diagnosis; remove all derived Part 4/HTML outputs.
- Clear stale `drug.md`, `target_assessment.json`, Part 4, HTML, and guardrail audit files at production run start, before `evidence_assessor`, and repeat the same cleanup before each production `report_writer` run. The first boundary prevents an early orchestrator exit from inheriting prior success; the second protects repeated or misrouted writer calls. A no-op writer must fail missing-artifact validation rather than republish a prior run. Ignore rather than delete unrelated legacy files such as both hypothesis-report variants, `report_data.json`, and renderer sidecars; forced-safe production tools and filesystem guards make them inaccessible instead.
- Block DeepAgents content/shell filesystem built-ins (`read_file`, `grep`, `write_file`, `edit_file`, `execute`) at every guarded production agent layer. Production code must use the dedicated forced-safe evidence loaders and save tools; `ls`/`glob` may remain available for content-free discovery.
- Do not expose the raw project-relative `read_skill_file` reader at any guarded production layer. The top-level orchestrator has no skills and omits it; each production subagent receives only a same-name wrapper constrained to its configured skill roots. Preserve the raw reader only for explicit legacy/direct callers.
- Bind every guarded production domain tool call, including repair, to the resolved `DrugTargetConfig.data_dir`; caller-supplied or omitted `data_dir` values must be replaced with the configured run directory before the tool handler runs. No model-controlled path may select another existing workspace.
- Reject `DrugTargetConfig.custom_tools` and direct production `get_subagents(custom_tools=...)` in `guarded_report` mode. Arbitrary developer tools are outside the closed production trust boundary and remain available only through explicit `legacy_hypothesis`/direct legacy factories.
- Keep the default behavior of `validate_drug_report_finalization(...)`, `build_report_data(...)`, and `build_drug_html_context(...)` compatible with independent legacy/benchmark callers.
- Do not delete or broadly rewrite `super_graph.py`, `finalize_report.py`, `deterministic_report.py`, `hypothesis_retry.py`, hypothesis prompt variants, `HypothesisRetryLoopMiddleware`, or `scripts/run_drug_target_traced.py`. Remove them only from production imports and routing. Keep the outer super-graph and traced benchmark runnable through an explicit `legacy_hypothesis` workflow mode; production defaults must never select it.
- Do not add dependencies.
- Use tests before production edits in each task. No test may invoke a live LLM; monkeypatch the repair and selector provider boundaries.

## Audit Contract

`drug_report_validation_initial.json` and `drug_report_validation_final.json` retain the complete dictionary returned by `validate_drug_report_finalization`. The guardrail adds namespaced metadata without replacing validator fields:

```json
{
  "valid": true,
  "issue_count": 0,
  "issues": [],
  "checks": {},
  "sources": [],
  "guardrail": {
    "status": "passed",
    "repair_attempt_count": 1,
    "changed_report_count": 1,
    "final_error_count": 0
  },
  "publication": {
    "status": "passed",
    "artifacts": [
      "part4_candidate_selection.json",
      "part4_therapeutic_synthesis.md",
      "drug_report.html"
    ],
    "error": null
  }
}
```

The initial audit uses `publication.status = "pending"`. A validation failure uses `"skipped"`; a publication exception uses `"failed"` and a bounded error string. Integration success requires both `valid is True` and `publication.status == "passed"` in the final audit.

## File Structure

- Create `src/agents/drug_target/report_guardrails.py`: validation, bounded repair, Markdown-hypothesis conversion, fail-closed publication, audit persistence, and stale-output cleanup.
- Create `src/agents/drug_target/production_report_tools.py`: same-name production wrappers that bind the run directory, force safe evidence scopes/legacy opt-outs, and leave raw tools available only to explicit legacy callers.
- Modify `src/agents/drug_target/middleware.py`: add report guardrail, run cleanup, configured-directory/filesystem enforcement, and production task-subagent allow-listing; retain `HypothesisRetryLoopMiddleware` for legacy callers.
- Modify `src/agents/drug_target/tools/stage_logic.py`: add an explicit `agent_markdown` publication mode to the existing validator.
- Modify `src/agents/drug_target/tools/assessment_output.py`: keep post-save quality flags while disabling legacy hypothesis-file checks for every `save_drug_md` call.
- Modify `src/agents/drug_target/deterministic_report.py`: allow validated in-memory hypothesis data while retaining the legacy file-backed default.
- Modify `src/agents/drug_target/tools/drug_report_html.py`: allow production callers to disable the legacy hypothesis JSON fallback.
- Modify `src/agents/drug_target/part4_candidate_selector.py`: remove legacy-only filenames from production evidence references.
- Modify `src/agents/drug_target/subagents/prompts.py`: make `REPORT_WRITER_PROMPT` the production direct-Markdown contract.
- Modify `src/agents/drug_target/subagents/configs.py`: expose `report_writer`, substitute forced-safe production load/save wrappers, attach managed-filesystem guards to both production subagents, and preserve raw legacy specs.
- Modify `src/agents/drug_target/agent.py`: update orchestrator routing, configuration, model/skill maps, comments, and production run-start cleanup for the new two-agent flow.
- Modify `src/agents/drug_target/__init__.py`: make the package architecture docstring describe the guarded two-subagent production flow.
- Modify `src/agents/drug_target/tools/evidence_loader.py`: add `scope="assessment"` and exclude every `hypothesis_report*.json` prior-output variant plus exact `report_data.json` from both production-safe scopes before content reads while preserving raw `scope="all"` compatibility.
- Modify `src/agents/deep_interpreter/middleware/write_file_guard.py`: protect managed artifacts from both built-in `write_file` and `edit_file`, including the internal `report_data.json` artifact.
- Modify `skills/drug-target-reporting/SKILL.md`: replace the renderer-era narrative-expander workflow with the guarded direct-author contract actually available to `report_writer`.
- Modify `skills/drug-target-reporting/references/scoring_guide.md`: source Section 4 from hypothesis-scope evidence and final `drug.md`, never `hypothesis_report.json`.
- Modify `skills/drug-target-reporting/evals/evals.json`: evaluate initial direct write and repair behavior instead of expansion/renderer/HTML calls.
- Modify both `skills/drug-target-reporting/templates/drug_report.md.j2` and `src/agents/drug_target/templates/drug_report.md.j2`: replace the obsolete hypothesis-writer fallback sentence with an explicit Section 4 authoring marker that validation can see.
- Modify `src/agents/drug_target/graph_builder.py`: export the direct Deep Agent runnable rather than the outer super-graph.
- Modify `src/agents/drug_target/integration.py`: construct a per-call agent for the caller's `data_dir`, verify the final audit/artifacts, and clean up its backend.
- Modify `src/agents/drug_target/super_graph.py`, `src/agents/drug_target/finalize_report.py`, and `scripts/run_drug_target_traced.py`: retain the compatibility implementation while labeling it explicitly legacy/deprecated, selecting `legacy_hypothesis` at its entrypoints, and keeping the finalizer's legacy evidence-summary opt-in explicit.
- Modify `tests/agents/drug_target/test_finalization_validator.py`: cover the new validator mode and legacy default.
- Modify `tests/agents/drug_target/test_reference_card_matched_drugs.py`: prove the production reference-card builder does not read a prior-run hypothesis file and preserve an explicit legacy opt-in.
- Modify `tests/agents/drug_target/test_summarizer_round_trip.py`: make its renderer-era hypothesis inclusion explicit after the production-safe reference-card default changes.
- Modify `tests/agents/drug_target/test_deterministic_report_mvp.py`: cover in-memory hypotheses without a legacy hypothesis file.
- Create `tests/agents/drug_target/test_drug_report_html.py`: lock the opt-out from the legacy hypothesis fallback.
- Modify `tests/agents/drug_target/test_part4_candidate_selector.py`: lock the new production evidence-reference allow-list.
- Verify only `tests/agents/drug_target/test_part4_candidate_selector_integration.py`: selector fallback and selected-pair behavior remain compatible with in-memory report data.
- Verify only `tests/agents/drug_target/test_part4_therapeutic_synthesis.py`: downstream Part 4 synthesis remains compatible with the narrowed evidence-reference list.
- Create `tests/agents/drug_target/test_report_guardrail_middleware.py`: cover validation, repair, publication, cleanup, and sync/async middleware behavior.
- Create `tests/agents/drug_target/test_report_writer_prompt.py`: lock the direct-write and repair prompt contracts.
- Create `tests/agents/drug_target/test_report_writer_skill_contract.py`: prove the loaded reporting skill and scoring guide match the direct-write tool surface and contain no positive legacy workflow instructions.
- Modify `tests/test_drug_target.py`: assert production subagent names, tools, middleware, model keys, and orchestrator messages.
- Modify `tests/agents/drug_target/test_orchestrator_middleware_chain.py`: assert the report guardrail is scoped to `report_writer`.
- Modify `tests/agents/drug_target/test_subagent_prompt_sanitization.py`: preserve safe `data_dir`/disease injection after the new subagent name.
- Modify `tests/agents/drug_target/test_subagent_prompts_cleanup.py`: replace the obsolete expected-failure/dead-code decision with an assertion that `REPORT_WRITER_PROMPT` is now an intentional production surface.
- Modify `tests/agents/drug_target/test_hypothesis_writer_skill_activation_prompt.py`: move prompt-mode assertions to `render_hypothesis_writer_prompt` and middleware unit construction rather than production `get_subagents`.
- Modify `tests/agents/drug_target/test_resume_instruction.py`: rename the helper/field assertions to the production `report_writer` resume contract.
- Modify `tests/agents/drug_target/test_config_ollama_openai.py`: teach its AST helper to resolve the new module-level `Provider` alias.
- Modify `tests/agents/drug_target/test_hypothesis_celltype_focus.py`: prove production assessment/hypothesis scopes and same-name wrappers exclude raw, sanitized, last-rejection, and draft prior-report variants before parsing while legacy raw scope remains explicit.
- Modify `tests/test_write_file_guard.py`: prove built-in `write_file` and `edit_file` cannot mutate `report_data.json` or existing managed artifacts.
- Modify `docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py`: opt the retained hypothesis-only benchmark into `legacy_hypothesis` explicitly.
- Modify `scripts/run_report_writer_only.py`: route the evidence-resume utility through the canonical guarded agent instead of duplicating a raw report writer.
- Modify `scripts/run_drug_target_e2e.py`: remove post-agent message-to-`drug.md` fallback mutation and gate E2E success on guarded publication.
- Modify `scripts/run_drug_target_agent_bc.py`: keep the fixed breast-cancer convenience runner, but make guarded mode explicit and replace unconditional `DONE` with the same final-audit/seven-artifact success gate.
- Modify `docs/drugtarget/drug_target_agent_reference.md`, `drug_target_stage_guide.md`, and `closed-book-policy.md`: make their current-architecture sections describe the guarded two-subagent flow while preserving dated legacy history.
- Modify `tests/benchmarks/test_hypothesis_generation_consistency.py`: capture the benchmark config and prove that explicit legacy routing is preserved without a model call.
- Create `tests/scripts/test_run_report_writer_only.py`, `test_run_drug_target_e2e.py`, and `test_run_drug_target_agent_bc.py`: lock all three migrated runnable entrypoints to guarded construction, fail-closed audit/artifact gating, and backend lifecycle without live models.
- Verify only `tests/test_run_drug_target_traced.py` and `tests/scripts/test_run_drug_target_traced_budget.py`: traced benchmark helpers remain compatible with the narrow legacy-mode edit.
- Verify only `tests/agents/drug_target/test_super_graph_hypothesis_retry.py`, `test_hypothesis_writer_prompt_category_contract.py`, and `test_hypothesis_writer_prompt_save_contract.py`: the explicitly retained hypothesis workflow remains runnable and preserves its prompt contracts.
- Verify only `tests/test_drug_target_fixes.py`: Stage-logic/reference-card regressions remain green after the validator and instruction changes.
- Verify only `tests/agents/drug_target/test_prompts_clinical_compounds_rule.py`, `test_prompts_gap_analysis_rule.py`, `test_prompts_reflection_guidance.py`, and `test_drug_profile_coverage.py`: retained grounding rules must remain green.
- Modify `tests/agents/drug_target/test_super_graph_topology.py`: replace production super-graph assertions with direct-export assertions while retaining explicitly legacy node tests.
- Modify `tests/agents/drug_target/test_integration_envelope.py`: cover per-call construction, audit gating, exact envelope shape, and backend cleanup.
- Modify `tests/agents/deep_interpreter/test_run_drug_target_node_transparency.py`: update the Step 9.5 disk-artifact contract to the guarded direct-agent path.
- Verify only `tests/test_wrapper_hitl_fixes.py`: its existing cache and selected-pair tests must remain green without wrapper production edits.

---

### Task 1: Add an Agent-Authored Mode to the Existing Finalization Validator

**Files:**
- Modify: `src/agents/drug_target/tools/stage_logic.py:5340-5610`
- Modify: `src/agents/drug_target/tools/assessment_output.py:356-430`
- Modify: `src/agents/drug_target/finalize_report.py:325-335` (explicit legacy-summary opt-in)
- Modify: `tests/agents/drug_target/test_finalization_validator.py:20-120` and renderer/hypothesis test sections
- Modify: `tests/agents/drug_target/test_reference_card_matched_drugs.py`
- Modify: `tests/agents/drug_target/test_summarizer_round_trip.py:98-175`
- Modify: `tests/agents/drug_target/test_finalize_report_mvp3_integration.py`
- Verify only: `tests/test_drug_target_fixes.py`

**Interfaces:**
- Change: `build_evidence_summary(data_dir: str, include_legacy_hypothesis: bool = False) -> str`
- Change: `validate_drug_md(data_dir: str | Path, include_legacy_hypothesis_checks: bool = True, include_renderer_provenance: bool = True) -> str`
- Change: `save_drug_md(data_dir: str, content: str | dict | list, strip_unexpanded_markers: bool = False) -> str`
- Change: `validate_drug_report_finalization(data_dir: str, require_critic: bool = False, publication_mode: Literal["renderer", "agent_markdown"] = "renderer") -> str`
- Preserve: existing calls to both validators default to current renderer/legacy behavior.
- Preserve: the retained `finalize_report` compatibility node explicitly calls `build_evidence_summary(..., include_legacy_hypothesis=True)` so changing the tool default cannot silently remove its hypothesis source.
- New behavior: `publication_mode="agent_markdown"` skips only hypothesis-file freshness/numeric checks and renderer metadata/hash checks.
- New behavior: agent mode and `save_drug_md` quality-flag persistence do not read `report_expansions.json` or `drug_report_reference_card.json` for provenance allow-list fields.
- New behavior: `publication_mode="agent_markdown"` requires at least one parser-compatible Section 4 entry and rejects any entry missing title, category, core claim, a gene, falsifiable prediction, or validation approach.
- Preserve in both modes: required artifacts, `validate_drug_md`, blocking P0 findings, target-assessment contract, Markdown tables, Stage 1 counts, gap analysis, MOA, failed suffixes, disease scope, and optional critic checks.
- Intentional safety change: `save_drug_md` preserves `EXPAND` markers by default so validation can repair them; the prior timeout cleanup remains available only as `strip_unexpanded_markers=True` for an explicit legacy caller.

- [ ] **Step 1: Extend the test helper and write mode-specific failing tests**

Update `_invoke` so tests can send the new keyword through the tool schema:

```python
def _invoke(
    data_dir: Path,
    *,
    allow_legacy: bool = True,
    publication_mode: str = "renderer",
) -> dict:
    previous = os.environ.get("DEEPMAST_ALLOW_LEGACY_DRUG_MD")
    if allow_legacy:
        os.environ["DEEPMAST_ALLOW_LEGACY_DRUG_MD"] = "1"
    else:
        os.environ.pop("DEEPMAST_ALLOW_LEGACY_DRUG_MD", None)
    try:
        return json.loads(
            validate_drug_report_finalization.invoke(
                {
                    "data_dir": str(data_dir),
                    "publication_mode": publication_mode,
                }
            )
        )
    finally:
        if previous is None:
            os.environ.pop("DEEPMAST_ALLOW_LEGACY_DRUG_MD", None)
        else:
            os.environ["DEEPMAST_ALLOW_LEGACY_DRUG_MD"] = previous
```

Add tests with the existing fixture helpers:

Import `_is_expand_prose` and `_EXPAND_SENTENCE_END_RE` from `stage_logic` in this test module so the synthetic agent fixture follows the validator's exact prose classification rather than duplicating it. `_canonical_parser_compatible_section_4()` returns the complete canonical entry shown in Task 3.

```python
def _copy_valid_agent_markdown_fixture(name: str, tmp_path: Path) -> Path:
    data_dir = _copy_fixture(name, tmp_path)
    drug_path = data_dir / "drug.md"
    lines = []
    for line in drug_path.read_text(encoding="utf-8").splitlines():
        if (
            _is_expand_prose(line)
            and _EXPAND_SENTENCE_END_RE.search(line.strip())
            and "[source:" not in line.casefold()
        ):
            line = f"{line} [source: interpretation]"
        lines.append(line)
    drug_path.write_text(
        "\n".join(lines)
        + "\n\n"
        + _canonical_parser_compatible_section_4()
        + "\n\n## 5. Pipeline Execution Summary & Recommendations\n",
        encoding="utf-8",
    )
    return data_dir


def test_agent_markdown_mode_ignores_renderer_sidecars(tmp_path: Path) -> None:
    data_dir = _copy_valid_agent_markdown_fixture("clean", tmp_path)
    _write_renderer_sidecars(data_dir, bad_source_hash=True, bad_drug_hash=True)

    result = _invoke(
        data_dir,
        allow_legacy=False,
        publication_mode="agent_markdown",
    )

    assert result["valid"] is True
    assert not _has_issue(result, "VALIDATE_DRUG_MD_BLOCKING_FINDING")
    assert not _has_issue(result, "RENDER_SOURCE_HASH_MISMATCH")
    assert not _has_issue(result, "RENDERED_DRUG_MD_HASH_MISMATCH")


def test_agent_markdown_mode_ignores_newer_legacy_hypothesis_file(
    tmp_path: Path,
) -> None:
    data_dir = _copy_valid_agent_markdown_fixture("clean", tmp_path)
    hypothesis_path = data_dir / "evidence" / "hypothesis_report.json"
    hypothesis_path.touch()

    result = _invoke(data_dir, publication_mode="agent_markdown")

    assert not _has_issue(result, "STALE_HYPOTHESIS_REPORT")


@pytest.mark.parametrize(
    "relative_path",
    [
        "evidence/hypothesis_report.json",
        "evidence/hypothesis_report.summarizer_sanitized.json",
        "evidence/hypothesis_report_last_rejection.json",
        "evidence/hypothesis_report_draft.json",
        "evidence/report_data.json",
        "report_expansions.json",
        "drug_report_reference_card.json",
    ],
)
def test_agent_markdown_mode_never_reads_legacy_or_renderer_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
) -> None:
    data_dir = _copy_valid_agent_markdown_fixture("clean", tmp_path)
    (data_dir / relative_path).parent.mkdir(parents=True, exist_ok=True)
    (data_dir / relative_path).write_text("{not-json", encoding="utf-8")
    forbidden_reads: list[Path] = []
    original_read_text = Path.read_text

    def guarded_read_text(path: Path, *args, **kwargs) -> str:
        if path == data_dir / relative_path:
            forbidden_reads.append(path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)

    result = _invoke(data_dir, publication_mode="agent_markdown")

    assert result["valid"] is True
    assert forbidden_reads == []


@pytest.mark.parametrize(
    "relative_path",
    [
        "evidence/assessment_results.json",
        "evidence/stage1_filter_results.json",
    ],
)
def test_agent_markdown_mode_rejects_malformed_required_json(
    tmp_path: Path,
    relative_path: str,
) -> None:
    data_dir = _copy_valid_agent_markdown_fixture("clean", tmp_path)
    (data_dir / relative_path).write_text("{not-json", encoding="utf-8")

    result = _invoke(data_dir, publication_mode="agent_markdown")

    assert result["valid"] is False
    assert result["checks"]["required_artifacts"]["status"] == "fail"
    assert relative_path in result["checks"]["required_artifacts"]["invalid"]
    assert _has_issue(result, "INVALID_REQUIRED_ARTIFACT")


def test_validator_rejects_git_worktree_root(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: /tmp/example", encoding="utf-8")

    result = _invoke(tmp_path, publication_mode="agent_markdown")

    assert result["valid"] is False
    assert _has_issue(result, "INVALID_DATA_DIR")


def test_save_drug_md_quality_flags_do_not_read_legacy_or_renderer_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _copy_fixture("clean", tmp_path)
    content = (data_dir / "drug.md").read_text(encoding="utf-8")
    forbidden_paths = {
        data_dir / "evidence" / "hypothesis_report.json",
        data_dir / "evidence" / "hypothesis_report.summarizer_sanitized.json",
        data_dir / "evidence" / "hypothesis_report_last_rejection.json",
        data_dir / "evidence" / "hypothesis_report_draft.json",
        data_dir / "evidence" / "report_data.json",
        data_dir / "report_expansions.json",
        data_dir / "drug_report_reference_card.json",
    }
    for path in forbidden_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not-json", encoding="utf-8")
    forbidden_reads: list[Path] = []
    original_read_text = Path.read_text

    def tracking_read_text(path: Path, *args, **kwargs) -> str:
        if path in forbidden_paths:
            forbidden_reads.append(path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracking_read_text)

    save_drug_md.invoke({"data_dir": str(data_dir), "content": content})

    assert forbidden_reads == []


def test_agent_markdown_mode_still_blocks_report_findings(tmp_path: Path) -> None:
    data_dir = _copy_valid_agent_markdown_fixture(
        "validate_drug_md_failed",
        tmp_path,
    )

    result = _invoke(
        data_dir,
        allow_legacy=False,
        publication_mode="agent_markdown",
    )

    assert result["valid"] is False
    assert _has_issue(result, "VALIDATE_DRUG_MD_FAILED")


def test_agent_markdown_mode_requires_parseable_section_4(tmp_path: Path) -> None:
    data_dir = _copy_valid_agent_markdown_fixture("clean", tmp_path)
    drug_path = data_dir / "drug.md"
    drug_path.write_text(
        re.sub(
            r"(?ms)^## 4\..*?(?=^## 5\.)",
            "## 4. Mechanistic Hypothesis Recommendations\n\n"
            "No recommendation was authored.\n\n",
            drug_path.read_text(encoding="utf-8"),
        ),
        encoding="utf-8",
    )

    result = _invoke(data_dir, publication_mode="agent_markdown")

    assert result["valid"] is False
    assert _has_issue(result, "AGENT_REPORT_HYPOTHESES_MISSING")


@pytest.mark.parametrize(
    "missing_label",
    [
        "title",
        "category",
        "core_claim",
        "genes",
        "falsifiable_prediction",
        "validation_approach",
    ],
)
def test_agent_markdown_mode_rejects_incomplete_section_4_entry(
    tmp_path: Path,
    missing_label: str,
) -> None:
    data_dir = _copy_valid_agent_markdown_fixture("clean", tmp_path)
    _replace_section_4_with_parser_fixture(data_dir, missing=missing_label)

    result = _invoke(data_dir, publication_mode="agent_markdown")

    assert result["valid"] is False
    assert _has_issue(result, "AGENT_REPORT_HYPOTHESIS_INCOMPLETE")


def test_save_drug_md_preserves_expand_markers_by_default(tmp_path: Path) -> None:
    content = "# Report\n\n<!-- EXPAND: write the summary -->\n"

    save_drug_md.invoke({"data_dir": str(tmp_path), "content": content})

    assert "<!-- EXPAND:" in (tmp_path / "drug.md").read_text(encoding="utf-8")


def test_save_drug_md_legacy_marker_stripping_requires_opt_in(tmp_path: Path) -> None:
    content = "# Report\n\n<!-- EXPAND: write the summary -->\n"

    save_drug_md.invoke(
        {
            "data_dir": str(tmp_path),
            "content": content,
            "strip_unexpanded_markers": True,
        }
    )

    assert "<!-- EXPAND:" not in (tmp_path / "drug.md").read_text(encoding="utf-8")
```

Retain an explicit default-mode test showing corrupted renderer metadata still fails.

Build `_replace_section_4_with_parser_fixture` from the exact canonical Markdown shown in Task 3. Do not make the validator tests depend on the publisher; these tests prove malformed Section 4 is visible to the repair loop itself.

Extend the existing `_invoke_build_evidence_summary` helper with keyword-only `include_legacy_hypothesis: bool = False`. Keep its existing three patch context managers, pass the new value to `build_evidence_summary.func`, and return `json.loads(raw)` unchanged.

Then add:

```python
@pytest.mark.parametrize(
    "filename",
    [
        "hypothesis_report.json",
        "hypothesis_report.summarizer_sanitized.json",
    ],
)
def test_reference_card_default_does_not_read_prior_hypothesis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
) -> None:
    data_dir = _setup_evidence_dir(
        tmp_path,
        "ITGB2",
        _MINIMAL_RUBRIC_ROW_ITGB2,
    )
    hypothesis_path = data_dir / "evidence" / filename
    hypothesis_path.write_text("not valid json", encoding="utf-8")
    forbidden_reads: list[Path] = []
    original_read_text = Path.read_text

    def tracking_read_text(path: Path, *args, **kwargs) -> str:
        if path == hypothesis_path:
            forbidden_reads.append(path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracking_read_text)

    result = _invoke_build_evidence_summary(data_dir)

    assert "error" not in result
    assert result.get("hypothesis_source") is None
    assert forbidden_reads == []


def test_reference_card_legacy_hypothesis_loading_is_explicit(
    tmp_path: Path,
) -> None:
    data_dir = _setup_evidence_dir(
        tmp_path,
        "ITGB2",
        _MINIMAL_RUBRIC_ROW_ITGB2,
    )
    (data_dir / "evidence" / "hypothesis_report.json").write_text(
        json.dumps({"hypotheses": []}),
        encoding="utf-8",
    )
    result = _invoke_build_evidence_summary(
        data_dir,
        include_legacy_hypothesis=True,
    )

    assert result.get("hypothesis_source", {}).get("path").endswith(
        "hypothesis_report.json"
    )
```

Use the fixture/helper names already present in that test file; the key assertion is default no-read plus explicit legacy opt-in.

Add `test_legacy_finalize_report_explicitly_includes_hypothesis_summary` to `test_finalize_report_mvp3_integration.py`. Monkeypatch `_build_evidence_summary_st`, call `_load_expansion_inputs`, and assert the captured invocation contains `include_legacy_hypothesis=True`; this must be red when only the summary tool default changes.

- [ ] **Step 2: Run the new tests and verify the red state**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/agents/drug_target/test_finalization_validator.py \
  tests/agents/drug_target/test_reference_card_matched_drugs.py \
  tests/agents/drug_target/test_finalize_report_mvp3_integration.py \
  -k 'agent_markdown_mode or renderer_metadata or save_drug_md_quality_flags or save_drug_md_preserves or legacy_marker_stripping or reference_card_default or reference_card_legacy or legacy_finalize_report'
```

Expected: the agent-mode tests fail because the tool schema rejects `publication_mode`, malformed Section 4 is not yet checked, or legacy files are still read; marker preservation fails because `save_drug_md` silently strips placeholders; the reference-card test fails while malformed prior-run hypothesis JSON is loaded by default.

- [ ] **Step 3: Add the explicit mode and narrow the mode-dependent checks**

Import `Literal`, define `PublicationMode = Literal["renderer", "agent_markdown"]`, and change the decorated validator signature exactly to `validate_drug_report_finalization(data_dir: str, require_critic: bool = False, publication_mode: PublicationMode = "renderer") -> str`. Keep the existing function body and make only the mode branches specified below.

Tighten the existing repository-root guard from `(data_dir_path / ".git").is_dir()` to `(data_dir_path / ".git").exists()` so linked worktree roots (whose `.git` is a file) are rejected before any guardrail cleanup. Preserve the same `INVALID_DATA_DIR` result shape.

Change the decorated `validate_drug_md` signature exactly to `validate_drug_md(data_dir: str | Path, include_legacy_hypothesis_checks: bool = True, include_renderer_provenance: bool = True) -> str`. Guard only its current “Hypothesis drug claims validation” loop with `include_legacy_hypothesis_checks and hypothesis_path.exists() and resolved_drugs_path.exists()`; leave the existing loop body unchanged.

The explicit hypothesis-claims block is not the only legacy read. Change `_build_evidence_field_set` to accept keyword-only `include_legacy_report_provenance: bool = True` and `include_renderer_provenance: bool = True`. When the first flag is false, skip before `read_text` any evidence JSON whose case-folded basename starts with `hypothesis_report` and ends with `.json`, plus the exact case-folded basename `report_data.json`; this covers raw, summarizer-sanitized, last-rejection, draft, and internal report-data variants without maintaining another filename list. When `include_renderer_provenance` is false, do not inspect either root `report_expansions.json` or root `drug_report_reference_card.json`; both can contribute stale provenance fields to the T7 allow-list. Call it from `validate_drug_md` with:

```python
evidence_field_set = _build_evidence_field_set(
    evidence_dir,
    include_legacy_report_provenance=include_legacy_hypothesis_checks,
    include_renderer_provenance=include_renderer_provenance,
)
```

When `validate_drug_report_finalization` unwraps the tool, pass both booleans as `publication_mode == "renderer"`. In `_persist_pipeline_quality_flags`, pass both as `False`. Defaults stay `True`, so direct renderer/benchmark calls retain all hypothesis-report, expansion, and reference-card provenance behavior.

Change the decorated signature exactly to `save_drug_md(data_dir: str, content: str | dict | list, strip_unexpanded_markers: bool = False) -> str`. Move the existing marker-removal substitution under this exact condition, before the unchanged persistence logic:

```python
if strip_unexpanded_markers:
    content = re.sub(r"\n*<!-- EXPAND:.*?-->\n*", "\n", content)
```

Do not add a second save tool. The one production tool must leave markers intact by default, allowing the existing `UNEXPANDED_PLACEHOLDER` finding to enter the repair loop. Keep the explicit `True` branch only for a legacy caller that knowingly accepts the previous timeout-cleanup behavior.

When `validate_drug_report_finalization` unwraps and invokes `validate_drug_md`, pass `include_legacy_hypothesis_checks=publication_mode == "renderer"` and `include_renderer_provenance=publication_mode == "renderer"`. This is required for the “sole production hypothesis source” contract; skipping only the explicit claim/freshness helpers would still let `_build_evidence_field_set` read stale hypothesis, expansion, or reference-card sidecars.

Extend `checks["required_artifacts"]` with `invalid: []`. After resolving the four required paths but before `validate_drug_md`, parse the required JSON inputs (`evidence/assessment_results.json` and the resolved evidence/root `stage1_filter_results.json`) exactly once. Require each to decode to a mapping or list as accepted by its existing downstream helper. On decode/type failure, append the canonical relative path to `invalid`, set the required-artifact check to `fail`, and add a critical `INVALID_REQUIRED_ARTIFACT` issue with the bounded exception text. Missing and invalid are both input failures, not report-writing failures; the middleware must perform zero repair attempts for either.

In `assessment_output._persist_pipeline_quality_flags`, invoke the unwrapped validator with `include_legacy_hypothesis_checks=False, include_renderer_provenance=False`. This helper runs inside every initial and repair `save_drug_md`; leaving its current one-argument call unchanged would reintroduce hidden production reads before the middleware validator runs. Legacy callers still get both legacy inputs when they call `validate_drug_md` or the default finalization validator directly.

Change `build_evidence_summary` so the existing hypothesis-loading block is entered only when `include_legacy_hypothesis is True`. Keep `hypothesis_data = {}` and `hypothesis_source = None` otherwise. The default must be `False`; this makes no prior-run hypothesis read possible even if the report-writer model omits the optional argument. Update only legacy tests that need the old renderer fixture to pass `include_legacy_hypothesis=True` explicitly.

In `finalize_report._load_expansion_inputs`, pass `include_legacy_hypothesis=True` to `_build_evidence_summary_st`. Add a focused monkeypatched regression in `test_finalize_report_mvp3_integration.py` that captures the unwrapped tool call and asserts this exact opt-in. This is the single retained compatibility caller; do not restore the unsafe default.

In `test_summarizer_round_trip.py`, both renderer-era calls use:

```python
_call_tool(
    build_evidence_summary,
    str(tmp_path),
    include_legacy_hypothesis=True,
)
```

This preserves that test's legacy producer/renderer round trip without weakening the production default.

Calculate renderer activity only in renderer mode, while always blocking report findings in the new production mode:

```python
sidecars_present = any(
    (data_dir_path / rel).exists()
    for rel in (
        "drug_report_render.json",
        "drug_report_reference_card.json",
        "report_expansions.json",
    )
)
renderer_mode_active = publication_mode == "renderer" and sidecars_present
block_findings = (
    publication_mode == "agent_markdown"
    or require_critic
    or renderer_mode_active
    or os.getenv("DEEPMAST_ALLOW_LEGACY_DRUG_MD") != "1"
)
```

Wrap only the legacy-coupled finalization checks:

```python
if publication_mode == "renderer":
    finalization_issues.extend(
        _check_stale_hypothesis_report(drug_text, data_dir_path)
    )
    finalization_issues.extend(
        _check_renderer_metadata(
            drug_text=drug_text,
            data_dir_path=data_dir_path,
        )
    )
    numeric_issues, numeric_warnings = _check_unverified_numeric_predictions(
        data_dir_path,
        strict=os.getenv("DEEPMAST_STRICT_NUMERIC_PREDICTIONS") == "1",
    )
    finalization_issues.extend(numeric_issues)
```

Add `_check_agent_markdown_hypotheses(drug_text, drug_md_path)` in `stage_logic.py`. Import `parse_drug_md` lazily inside this helper to preserve the existing `stage_logic -> drug_report_html -> evidence_loader -> stage_logic` circular-import boundary. Call the parser once, read `context["hypothesis"]`, and return:

- one high-severity `AGENT_REPORT_HYPOTHESES_MISSING` issue when no entry is parsed (including a missing/non-compatible Section 4 heading);
- one high-severity `AGENT_REPORT_HYPOTHESIS_INCOMPLETE` issue per parsed entry, with `evidence.missing_fields`, when any of `title`, `category`, `core_claim`, `falsifiable_prediction`, or `validation_approach` is blank, or when `genes` has no non-blank value.

Invoke it only when `publication_mode == "agent_markdown"`, alongside the other `report_finalization` checks and before returning the initial validation result:

```python
if publication_mode == "agent_markdown":
    finalization_issues.extend(
        _check_agent_markdown_hypotheses(
            drug_text,
            data_dir_path / "drug.md",
        )
    )
```

These are repairable report-content issues. Do not add their codes to the middleware's non-repairable check set. Task 3 repeats the same structural checks at the publication boundary as defense in depth, but publication must not be the first place they are discovered.

Do not condition the table, count, gap, MOA, suffix, disease-scope, target-assessment, or `validate_drug_md` checks.

- [ ] **Step 4: Run the complete validator suite**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/agents/drug_target/test_finalization_validator.py \
  tests/agents/drug_target/test_reference_card_matched_drugs.py \
  tests/agents/drug_target/test_summarizer_round_trip.py \
  tests/agents/drug_target/test_finalize_report_mvp3_integration.py \
  tests/test_drug_target_fixes.py
```

Expected: all tests pass; the unchanged default retains all current renderer behavior.

- [ ] **Step 5: Commit the validator seam**

```bash
git add -f docs/superpowers/plans/2026-07-15-drug-target-report-guardrail.md
git add \
  src/agents/drug_target/tools/stage_logic.py \
  src/agents/drug_target/tools/assessment_output.py \
  src/agents/drug_target/finalize_report.py \
  tests/agents/drug_target/test_finalization_validator.py \
  tests/agents/drug_target/test_reference_card_matched_drugs.py \
  tests/agents/drug_target/test_summarizer_round_trip.py \
  tests/agents/drug_target/test_finalize_report_mvp3_integration.py
git commit -m "$(cat <<'EOF'
Let agent-authored reports use the full validator without renderer coupling

Constraint: Existing renderer and benchmark callers must retain their default validation behavior.
Rejected: Environment-variable mode switching | makes production correctness depend on ambient process state.
Confidence: high
Scope-risk: moderate
Directive: Keep agent_markdown strict for content and evidence checks, and preserve unexpanded markers by default so repair can see them; exempt only legacy renderer/hypothesis-file coupling.
Tested: OPENAI_API_KEY=test uv run pytest -q tests/agents/drug_target/test_finalization_validator.py tests/agents/drug_target/test_reference_card_matched_drugs.py tests/agents/drug_target/test_summarizer_round_trip.py tests/agents/drug_target/test_finalize_report_mvp3_integration.py tests/test_drug_target_fixes.py
Not-tested: Live report-writer repair output.
EOF
)"
```

---

### Task 2: Make Final Markdown the In-Memory Hypothesis Source

**Files:**
- Modify: `src/agents/drug_target/deterministic_report.py:175-205,1711-1895`
- Modify: `src/agents/drug_target/tools/drug_report_html.py:1486-1545`
- Modify: `src/agents/drug_target/part4_candidate_selector.py:35-46`
- Modify: `tests/agents/drug_target/test_deterministic_report_mvp.py`
- Create: `tests/agents/drug_target/test_drug_report_html.py`
- Modify: `tests/agents/drug_target/test_part4_candidate_selector.py`
- Verify only: `tests/agents/drug_target/test_part4_candidate_selector_integration.py`
- Verify only: `tests/agents/drug_target/test_part4_therapeutic_synthesis.py`

**Interfaces:**
- Change: `build_report_data(data_dir: str, disease: str, *, hypothesis_data: dict[str, Any] | None = None) -> dict[str, Any]`
- Preserve: omitting `hypothesis_data` reads and requires `evidence/hypothesis_report.json` exactly as before.
- Change: `build_drug_html_context(data_dir: str, *, allow_legacy_hypothesis_fallback: bool = True) -> dict[str, Any]`
- Preserve: default `True` for legacy callers; production publication will pass `False`.
- Change: `PART4_CANDIDATE_SELECTION_EVIDENCE_REFERENCES == ["drug.md", "target_assessment.json"]`.

- [ ] **Step 1: Write failing tests for the three compatibility seams**

Add an in-memory hypothesis test beside existing `build_report_data` tests:

```python
def test_build_report_data_accepts_hypotheses_without_legacy_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = _copy_baseline_workspace(tmp_path)
    (data_dir / "evidence" / "hypothesis_report.json").write_text(
        "stale legacy payload that must not be parsed",
        encoding="utf-8",
    )
    hypothesis_data = {
        "hypotheses": [
            {
                "rank": 1,
                "title": "Markdown-derived hypothesis",
                "category": "mechanistic",
                "core_claim": "A testable association.",
                "biological_entities": {
                    "genes": ["GENE1"],
                    "pathways": [],
                    "cell_types": [],
                    "drugs": [],
                },
                "falsifiable_prediction": "GENE1 changes in the disease context.",
                "validation_approach": "Perturb GENE1 and measure the endpoint.",
                "evidence_references": ["drug.md"],
            }
        ]
    }
    original_sha256_path = deterministic_report._sha256_path

    def guarded_sha256_path(path: Path) -> str:
        if path.name == "hypothesis_report.json":
            raise AssertionError("injected mode must not hash the legacy hypothesis file")
        return original_sha256_path(path)

    monkeypatch.setattr(deterministic_report, "_sha256_path", guarded_sha256_path)

    report_data = build_report_data(
        str(data_dir),
        "IPF",
        hypothesis_data=hypothesis_data,
    )

    assert report_data["valid"] is True
    assert report_data["hypotheses"][0]["title"] == "Markdown-derived hypothesis"
    assert report_data["sections"]["hypotheses"]["sources"] == ["drug.md"]
    assert "evidence/hypothesis_report.json" not in report_data["sources"]
```

Create the HTML fallback test:

```python
def test_html_context_can_disable_legacy_hypothesis_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "drug.md").write_text("# Drug Report\n", encoding="utf-8")
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    hypothesis_path = evidence_dir / "hypothesis_report.json"
    hypothesis_path.write_text(
        json.dumps(
            {
                "hypotheses": [
                    {
                        "title": "Legacy-only hypothesis",
                        "category": "mechanistic",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    forbidden_reads: list[Path] = []
    original_read_text = Path.read_text

    def tracking_read_text(path: Path, *args, **kwargs) -> str:
        if path == hypothesis_path:
            forbidden_reads.append(path)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracking_read_text)

    context = build_drug_html_context(
        str(tmp_path),
        allow_legacy_hypothesis_fallback=False,
    )

    assert context.get("hypothesis", []) == []
    assert forbidden_reads == []
```

Add a selector allow-list assertion:

```python
def test_production_evidence_references_exclude_legacy_intermediates() -> None:
    assert PART4_CANDIDATE_SELECTION_EVIDENCE_REFERENCES == [
        "drug.md",
        "target_assessment.json",
    ]
```

- [ ] **Step 2: Run the focused tests and verify the red state**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/agents/drug_target/test_deterministic_report_mvp.py \
  tests/agents/drug_target/test_drug_report_html.py \
  tests/agents/drug_target/test_part4_candidate_selector.py \
  -k 'hypotheses_without_legacy_file or disable_legacy_hypothesis or production_evidence_references'
```

Expected: failures for unexpected keyword arguments and the old four-item evidence-reference list.

- [ ] **Step 3: Add the optional in-memory data path without changing the default**

Change `build_report_data` to the exact signature `build_report_data(data_dir: str, disease: str, *, hypothesis_data: dict[str, Any] | None = None) -> dict[str, Any]`. Immediately after resolving `base`, set `require_hypothesis_file = hypothesis_data is None` and pass it as `require_hypothesis=require_hypothesis_file` to `_missing_required_evidence`. At the existing hypothesis load site, use this complete branch:

```python
if hypothesis_data is None:
    hypothesis = _load_json(paths["hypothesis_report"])
    hypothesis_source = "evidence/hypothesis_report.json"
else:
    hypothesis = hypothesis_data
    hypothesis_source = "drug.md"
```

Update `_missing_required_evidence` with a keyword-only boolean and use `hypothesis_source` for the hypotheses section and cited-source set. When data is injected, add only `evidence/assessment_results.json` plus `drug.md`; do not iterate/hash the stale hypothesis path merely because it exists. Do not mutate or persist `hypothesis_data`. Keep the legacy invalid-shape/error codes for the file-backed path; use `INVALID_HYPOTHESIS_SHAPE` for an invalid injected mapping.

- [ ] **Step 4: Gate the HTML fallback and narrow Part 4 references**

Change the signature exactly to `build_drug_html_context(data_dir: str, *, allow_legacy_hypothesis_fallback: bool = True) -> dict[str, Any]`. At the existing evidence/hypothesis-report compatibility block, replace its current condition with `if allow_legacy_hypothesis_fallback and not context.get("hypothesis"):` and leave the existing block body unchanged.

Set the selector constant to:

```python
PART4_CANDIDATE_SELECTION_EVIDENCE_REFERENCES = [
    "drug.md",
    "target_assessment.json",
]
```

- [ ] **Step 5: Run deterministic report, HTML, and Part 4 regressions**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/agents/drug_target/test_deterministic_report_mvp.py \
  tests/agents/drug_target/test_drug_report_html.py \
  tests/agents/drug_target/test_part4_candidate_selector.py \
  tests/agents/drug_target/test_part4_candidate_selector_integration.py \
  tests/agents/drug_target/test_part4_therapeutic_synthesis.py
```

Expected: all tests pass, including legacy file-backed deterministic finalization tests.

- [ ] **Step 6: Commit the in-memory publication seam**

```bash
git add \
  src/agents/drug_target/deterministic_report.py \
  src/agents/drug_target/tools/drug_report_html.py \
  src/agents/drug_target/part4_candidate_selector.py \
  tests/agents/drug_target/test_deterministic_report_mvp.py \
  tests/agents/drug_target/test_drug_report_html.py \
  tests/agents/drug_target/test_part4_candidate_selector.py
git commit -m "$(cat <<'EOF'
Use final Markdown as the only production hypothesis source

Constraint: Legacy deterministic benchmarks still require file-backed hypothesis loading by default.
Rejected: Persist a replacement report_data.json | creates another source of truth between validation and publication.
Confidence: high
Scope-risk: moderate
Directive: Production callers must inject Markdown-derived hypotheses and disable the legacy HTML fallback.
Tested: OPENAI_API_KEY=test uv run pytest -q tests/agents/drug_target/test_deterministic_report_mvp.py tests/agents/drug_target/test_drug_report_html.py tests/agents/drug_target/test_part4_candidate_selector.py tests/agents/drug_target/test_part4_candidate_selector_integration.py tests/agents/drug_target/test_part4_therapeutic_synthesis.py
Not-tested: Live Part 4 selector provider.
EOF
)"
```

---

### Task 3: Implement the Bounded Drug Report Guardrail and Fail-Closed Publisher

**Files:**
- Create: `src/agents/drug_target/report_guardrails.py`
- Create: `src/agents/drug_target/production_report_tools.py`
- Modify: `src/agents/drug_target/middleware.py`
- Create: `tests/agents/drug_target/test_report_guardrail_middleware.py`
- Verify only: `tests/agents/drug_target/test_finalization_validator.py`
- Verify only: `tests/agents/drug_target/test_deterministic_report_mvp.py`
- Verify only: `tests/agents/drug_target/test_drug_report_html.py`
- Verify only: `tests/agents/drug_target/test_part4_candidate_selector.py`
- Verify only: `tests/agents/drug_target/test_part4_candidate_selector_integration.py`
- Verify only: `tests/agents/drug_target/test_part4_therapeutic_synthesis.py`

**Interfaces:**
- Add: `MAX_DRUG_REPORT_REPAIR_PASSES = 3`
- Add: `run_drug_report_guardrail(data_dir: str | Path, *, provider: str | None = None, disease: str = "") -> dict[str, Any]`
- Add: `clear_derived_report_artifacts(data_dir: str | Path, *, include_audits: bool = False, include_sources: bool = False) -> None`
- Add: `DrugReportGuardrailMiddleware(data_dir: str | Path | None, *, provider: str | None = None, disease: str = "")`
- Add: `DrugReportRunCleanupMiddleware(data_dir: str | Path | None)` with sync/async `before_agent` hooks only.
- Add: `DrugTargetManagedFilesystemGuardMiddleware(data_dir: str | Path, *, data_dir_tool_names: Collection[str])`, blocking DeepAgents built-ins `read_file`, `grep`, `write_file`, `edit_file`, and `execute`, while forcing the configured run directory into every named domain tool before dispatch and allowing content-free discovery (`ls`, `glob`).
- Add: `DrugTargetTaskAllowlistMiddleware(allowed_subagent_types)`, rejecting `task` calls for DeepAgents' automatic `general-purpose` agent or any type outside the exact production domain set.
- Add: `production_hypothesis_evidence_tool(data_dir) -> StructuredTool` and `production_save_drug_md_tool(data_dir) -> StructuredTool`, exposed to repair under the original public names while forcing `scope="hypothesis"`, the configured run directory, and `strip_unexpanded_markers=False` regardless of caller arguments.
- Middleware hooks: sync/async `before_agent` clear stale derived/audit outputs; sync/async `after_agent` run the guardrail and raise `RuntimeError` on failed validation or publication.

Reuse the existing Deep Interpreter middleware shape, not its class implementation. Its runner import, audit names, and hook lifecycle are domain-specific, so generalizing `ReportGuardrailMiddleware` during this migration would widen the change without reducing the Drug Target boundary work.

- [ ] **Step 1: Write unit tests for repair control flow and audit persistence**

Use monkeypatched private boundaries rather than a live model. Create one focused test for each exact behavior below; use the shown names so the later `pytest -k` and review references stay stable:

- `test_nonrepairable_input_fails_without_calling_repair`, `test_missing_target_assessment_fails_without_calling_repair`, `test_unreadable_required_evidence_fails_without_calling_repair`, and `test_malformed_required_json_fails_without_calling_repair`: monkeypatch repair/publication to raise if called and assert zero calls plus a failed final audit.
- `test_guardrail_repairs_until_valid_and_writes_both_audits`, `test_guardrail_stops_after_three_changed_repairs`, and `test_guardrail_stops_when_drug_md_is_unchanged`: drive explicit validator sequences and assert exact attempt/change counts.
- `test_missing_section_4_is_repaired_before_publication` and `test_incomplete_section_4_is_repaired_before_publication`: assert the issue reaches repair and publication runs only after revalidation.
- `test_repair_prompt_json_encodes_control_characters` and `test_repair_exception_writes_failed_final_audit_and_clears_outputs`: capture the repair message and filesystem state.
- `test_warning_only_validation_publishes_without_repair`, `test_publication_failure_removes_derived_outputs_but_keeps_diagnostics`, and `test_success_audit_write_failure_removes_published_outputs`: assert the transaction boundary and retained diagnostics.
- `test_middleware_without_data_dir_fails_before_touching_cwd`, `test_cleanup_rejects_root_and_repository_directory_without_unlinking`, and `test_cleanup_preserves_legacy_hypothesis_and_report_data_files`: monkeypatch `Path.unlink` and assert the exact touched-path set.
- `test_middleware_before_hooks_clear_stale_publication_outputs`, `test_middleware_before_hooks_clear_stale_source_outputs`, `test_noop_writer_cannot_republish_stale_source_outputs`, and `test_run_cleanup_middleware_clears_sources_audits_and_publication_outputs`: seed every managed artifact and assert the per-hook cleanup contract.
- `test_production_hypothesis_loader_forces_scope_when_caller_requests_all` and `test_repair_agent_tools_cannot_switch_data_dir`: capture the raw handler arguments and assert the configured directory/scope.
- `test_managed_filesystem_guard_blocks_content_read_write_and_execute_sync`, its async counterpart, both configured-directory sync/async tests, and `test_managed_filesystem_guard_allows_discovery_and_domain_tools`: use a recording handler and assert dispatch/no-dispatch plus rewritten arguments.
- `test_task_allowlist_rejects_general_purpose_without_dispatch_sync`, its async counterpart, and `test_task_allowlist_allows_only_evidence_assessor_and_report_writer`: use the same recording handler and assert the exact allowed set.
- `test_middleware_after_hooks_return_metadata_on_success` and `test_middleware_after_hooks_raise_on_validation_or_publication_failure`: patch the guardrail result and assert returned `AIMessage` versus raised `RuntimeError`.

Use validator sequences shaped like the real validator:

```python
def _validation(*, valid: bool, issues: list[dict] | None = None) -> dict:
    return {
        "valid": valid,
        "issue_count": len(issues or []),
        "issues": issues or [],
        "checks": {
            "data_dir": {"status": "pass"},
            "required_artifacts": {"status": "pass", "missing": []},
            "target_assessment": {"status": "pass", "issues": []},
        },
        "sources": [],
    }
```

Assert all of the following explicitly:

- repair receives only hard issues and never receives warning-only findings;
- an invalid `checks.required_artifacts` or `checks.target_assessment` result performs zero repairs;
- malformed `assessment_results.json` or `stage1_filter_results.json` is represented by `checks.required_artifacts.status == "fail"` and performs zero repairs;
- the repair count never exceeds three;
- unchanged Markdown exits after the first repair attempt;
- `AGENT_REPORT_HYPOTHESES_MISSING` and `AGENT_REPORT_HYPOTHESIS_INCOMPLETE` are passed to repair like other hard content issues, then revalidated before any publisher helper runs;
- `drug_report_validation_initial.json` is the first validator result;
- `drug_report_validation_final.json` includes final validator fields, guardrail metadata, and publication status;
- no test creates `report_data.json` or `evidence/hypothesis_report.json`.

- [ ] **Step 2: Write publication tests using Markdown-derived hypotheses**

Add a parseable Section 4 fixture directly in the test:

```python
DRUG_MD_WITH_HYPOTHESIS = """# Drug Target Report

## 4. Mechanistic Hypothesis Recommendations

#### 4.1.1. GENE1 state tracks disease activity
**Category:** mechanistic
**Core Claim:** GENE1-associated signaling tracks disease activity.
- Genes: GENE1
- Pathways: test pathway
- Cell Types: fibroblast
- Drugs: compound A
**Falsifiable Prediction:** GENE1 perturbation changes the endpoint.
**Validation Approach:** Perturb GENE1 and measure the endpoint.
"""
```

Monkeypatch deterministic report/Part 4/HTML helpers at their import locations and assert the publisher passes this normalized shape in memory:

```python
{
    "hypotheses": [
        {
            "rank": 1,
            "title": "GENE1 state tracks disease activity",
            "category": "mechanistic",
            "core_claim": "GENE1-associated signaling tracks disease activity.",
            "biological_entities": {
                "genes": ["GENE1"],
                "pathways": ["test pathway"],
                "cell_types": ["fibroblast"],
                "drugs": ["compound A"],
            },
            "falsifiable_prediction": "GENE1 perturbation changes the endpoint.",
            "validation_approach": "Perturb GENE1 and measure the endpoint.",
            "evidence_references": ["drug.md"],
        }
    ]
}
```

Also assert publication fails before Part 4 when Section 4 has no parseable hypotheses, or when a parsed entry lacks any of: title, category, core claim, at least one gene, falsifiable prediction, or validation approach. These are transaction-boundary defense-in-depth tests; Task 1 and the repair-flow tests above prove the same defects are normally detected and repaired before publication.
Add parametrized failures for a malformed candidate-selection mapping, a wrong synthesis schema version, blank Part 4 Markdown, and blank/non-HTML renderer output; each case must leave every `PUBLICATION_ARTIFACTS` path absent.

- [ ] **Step 3: Run the new tests and verify the red state**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/agents/drug_target/test_report_guardrail_middleware.py
```

Expected: collection fails because `report_guardrails.py` and `DrugReportGuardrailMiddleware` do not exist.

- [ ] **Step 4: Implement validation, audit, and repair helpers**

Start `report_guardrails.py` with the concrete artifact sets:

```python
MAX_DRUG_REPORT_REPAIR_PASSES = 3
PUBLICATION_ARTIFACTS = (
    "part4_candidate_selection.json",
    "part4_therapeutic_synthesis.md",
    "drug_report.html",
)
GUARDRAIL_AUDIT_ARTIFACTS = (
    "drug_report_validation_initial.json",
    "drug_report_validation_final.json",
)
```

Add `_resolve_safe_run_dir` and use it before every cleanup or audit write. It applies the validator's same fail-closed path rules: resolve without environment fallback; require an existing directory; reject filesystem root and any directory containing a `.git` entry (file or directory). `clear_derived_report_artifacts` must perform no unlink before this guard passes. This prevents a bad direct/integration call from deleting a repository/worktree-level `drug.md` or `/drug.md` before the validator can reject the path.

After that guard, `clear_derived_report_artifacts` unlinks the named final paths and their sibling `.tmp` paths. With `include_audits=False`, it must never remove either diagnostic audit. With `include_sources=True`, it additionally removes `drug.md` and `target_assessment.json`; otherwise it preserves them so a failed publication retains diagnostic source artifacts.

Both sync and async `DrugReportGuardrailMiddleware.before_agent` hooks call it with `include_audits=True, include_sources=True`. This is the report-writer freshness boundary: the writer must recreate both source files in that invocation. The top-level production run-cleanup middleware and the integration entrypoint also perform the same cleanup at overall-run start, preventing a premature orchestrator exit before `report_writer` from inheriting a prior success. Never use `include_sources=True` in post-validation/publication failure cleanup.

Implement `DrugReportRunCleanupMiddleware` as the same safe sync/async before-hook cleanup with no after hook. Task 4 attaches it to the top-level production orchestrator, so direct `langgraph.json`/script invocations clear stale success artifacts before `evidence_assessor` starts—even if orchestration exits before dispatching `report_writer`. Keep the report-writer `before_agent` cleanup too; it is a deliberate second boundary for repeated/misrouted report-writer calls. Never attach the run cleanup middleware in `legacy_hypothesis` mode.

Implement `_validate` by invoking the existing tool with `publication_mode="agent_markdown"`, parsing the JSON once, and returning a dictionary. Implement `_hard_issues` as issues whose severity is not `warning`. Implement `_nonrepairable_check_failure` from failed `checks.data_dir`, `checks.required_artifacts`, or `checks.target_assessment`, plus a non-empty `checks.validate_drug_md.raw.error` (the existing validator uses that field when required evidence JSON cannot be read). Ordinary `validate_drug_md` content findings remain repairable.

Implement `_write_audit` with a sibling temporary file plus `Path.replace`. Build audit payloads from `copy.deepcopy(validation)` so adding `guardrail`/`publication` metadata never mutates the validator dictionary used by the repair loop.

The repair prompt must start with the exact heading `## REPAIR MODE` and contain only the current Markdown, hard issues, resolved `data_dir`, and disease:

```python
repair_prompt = f"""## REPAIR MODE

Repair the existing drug.md in place. Fix only the listed validation issues.
Do not rebuild evidence, target_assessment.json, Part 4, or HTML.
Call save_drug_md exactly once with strip_unexpanded_markers=False after the repair.

Data directory: {data_dir}
Disease: {disease or "unspecified"}

Validation issues:
{json.dumps(issues, ensure_ascii=False, indent=2)}

Current drug.md:
{current_markdown}
"""
```

In the implementation, render `data_dir` and `disease` on those two lines with `json.dumps(...)` so control characters cannot create new repair-prompt sections; the displayed pseudocode keeps them readable. `get_subagents` already supplies the middleware's sanitized disease value.

Create `production_report_tools.py` with same-name `StructuredTool` factories bound to a resolved run directory. `production_hypothesis_evidence_tool(data_dir)` accepts caller `data_dir`/`scope` for schema compatibility but ignores both and invokes the raw boundary with the configured directory and `scope="hypothesis"`. `production_save_drug_md_tool(data_dir)` likewise delegates with the configured directory and `strip_unexpanded_markers=False`. Unit-test both against monkeypatched raw functions using an adversarial different existing directory, `scope="all"`, and `strip_unexpanded_markers=True`; the captured calls must still use only the configured production values.

Create a one-off `langchain.agents.create_agent` with `create_llm(provider=provider)`, `REPORT_WRITER_PROMPT`, and only `[production_hypothesis_evidence_tool(data_dir), production_save_drug_md_tool(data_dir)]`. Attach `DrugTargetManagedFilesystemGuardMiddleware(data_dir, data_dir_tool_names={"load_evidence_files", "save_drug_md"})` so the repair layer has the same bound-directory contract even though both wrappers already force it. Do not attach `DrugReportGuardrailMiddleware` or expose `read_skill_file`; `REPORT_WRITER_PROMPT`'s `REPAIR MODE` is self-contained and must not require unavailable initial-write tools. Compare SHA-256 before and after invocation and return whether `drug.md` changed.

- [ ] **Step 5: Implement Markdown conversion and publication as one fail-closed transaction**

Add `_hypothesis_payload_from_markdown` using `parse_drug_md`. Require at least one parsed hypothesis. For every retained entry, require non-blank `title`, `category`, `core_claim`, `falsifiable_prediction`, and `validation_approach`, plus at least one non-blank `genes` value; fail the entire publication rather than silently dropping an incomplete entry. Normalize the flat parser keys into `biological_entities` as shown in the test.

Implement async `_publish_report_outputs(...)` in this order:

1. Parse final `drug.md`; fail if no hypotheses are parseable.
2. Call `build_report_data(..., hypothesis_data=payload)` and `validate_report_data(report_data)`; fail on any issue.
3. Build the deterministic Part 4 synthesis and its selected-gene list.
4. Build `selector_config = {"configurable": {"llm_provider": provider}}` when a provider is present (otherwise `{}`), resolve the provider through `part4_candidate_selector_provider_from_config(selector_config)`, then call `generate_part4_candidate_selection(..., config=selector_config)`.
5. Require the candidate-selection payload to be a mapping with `schema_version == PART4_CANDIDATE_SELECTION_SCHEMA_VERSION` and a list-valued `selected_genes`. Deterministic fallback status is valid; malformed output is not.
6. Build the final Part 4 synthesis; require `schema_version == PART4_SYNTHESIS_SCHEMA_VERSION`; render it and require non-blank Markdown.
7. Call `build_drug_html_context(..., allow_legacy_hypothesis_fallback=False)` and `render_drug_html(...)`; require non-blank HTML containing an `<html` tag.
8. Serialize all three outputs before replacing any final file. Write sibling temporary files, parse the temporary JSON back once, require all temporary files to be non-empty, then `Path.replace` them into the final names.
9. On any exception, delete temporary files and all `PUBLICATION_ARTIFACTS`, then re-raise.

Do not call `_write_json` from `deterministic_report.py` and do not persist the in-memory `report_data` mapping.

- [ ] **Step 6: Implement the bounded runner**

The runner algorithm is fixed:

1. Clear derived outputs/audits, validate once, and persist the initial audit with publication pending.
2. If data-dir, required-artifact, target-assessment, or raw-evidence checks are non-repairable, clear only derived publication files and write/return a failed final audit with zero repair attempts.
3. While hard issues remain and attempts are below `MAX_DRUG_REPORT_REPAIR_PASSES`, call `_repair_drug_md`, increment attempts, revalidate, and stop immediately when the Markdown hash is unchanged.
4. If repair raises, retain source/audits, clear derived publication files, and finish with bounded repair error text.
5. If hard issues remain after the loop, finish failed without publication.
6. Otherwise run `_publish_report_outputs`; on exception, delete temporary/final publication artifacts and finish with bounded publication error text.
7. Persist the passed final audit only after all publication artifacts exist; if that write fails, remove the publication artifacts and propagate the error.

Always write the final audit before returning. Bound exception text stored in JSON to a stable maximum such as 500 characters. If the passed final audit cannot be persisted after publication, clear `PUBLICATION_ARTIFACTS` and propagate the audit-write error so the middleware fails closed; the initial audit remains diagnostic evidence. Return a compact result containing `status`, issue/error counts, repair counts, and publication status; the audit remains the detailed source.

- [ ] **Step 7: Add the middleware beside the retained legacy middleware**

Implement sync and async hooks following the Deep Interpreter precedent. Put the shared safe directory resolution/cleanup call in a private base/helper so `DrugReportRunCleanupMiddleware` and `DrugReportGuardrailMiddleware` do not drift:

```python
class DrugReportGuardrailMiddleware(AgentMiddleware):
    def before_agent(self, state, runtime) -> None:
        data_dir = self._require_data_dir()
        clear_derived_report_artifacts(
            data_dir,
            include_audits=True,
            include_sources=True,
        )
        return None

    async def abefore_agent(self, state, runtime) -> None:
        data_dir = self._require_data_dir()
        await asyncio.to_thread(
            clear_derived_report_artifacts,
            data_dir,
            include_audits=True,
            include_sources=True,
        )
        return None

    def after_agent(self, state, runtime) -> dict[str, Any]:
        return self._run()

    async def aafter_agent(self, state, runtime) -> dict[str, Any]:
        return await asyncio.to_thread(self._run)
```

`_run()` calls `run_drug_report_guardrail`. On `status == "failed"`, raise `RuntimeError` naming the remaining hard-error count or publication error and `drug_report_validation_final.json`. On success, return one `AIMessage` containing sorted JSON under `drug_report_guardrail`.

Store `None` rather than `Path("")` when the constructor receives no directory. `_require_data_dir()` must raise a clear `RuntimeError` instead of resolving the repository working directory; `create_drug_target_agent` always supplies the resolved production directory.

In the same module, add `DrugTargetManagedFilesystemGuardMiddleware` with one frozen blocked-name set: `{"read_file", "grep", "write_file", "edit_file", "execute"}`, one resolved configured directory, and a frozen set of tool names whose schemas accept `data_dir`. Its sync and async wrappers must (1) return a `ToolMessage` without dispatch for a blocked built-in, and otherwise (2) copy the tool call and replace/insert `args["data_dir"]` with the configured directory for every bound domain-tool name before calling the handler. Allow `ls`, `glob`, and dedicated query/load/save tools. Task 4 computes the bound-name set from each returned tool's schema/signature and attaches the guard to the production top-level orchestrator and both production subagents; the repair agent receives it in Step 4. Never attach it to explicit legacy workflow specs.

Also add `DrugTargetTaskAllowlistMiddleware` for the guarded top-level agent. Its sync/async wrappers inspect only the `task` tool and reject without handler dispatch unless `subagent_type` is exactly `evidence_assessor` or `report_writer`; all non-`task` calls pass through unchanged. This is required because installed DeepAgents automatically registers a separate `general-purpose` subagent with its own `FilesystemMiddleware`, which does not inherit the production subagent middleware. Unit tests must prove a `general-purpose` call never reaches its handler and both domain types do. Legacy mode receives no task allowlist and preserves current behavior.

- [ ] **Step 8: Run guardrail and dependent publication tests**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/agents/drug_target/test_report_guardrail_middleware.py \
  tests/agents/drug_target/test_finalization_validator.py \
  tests/agents/drug_target/test_deterministic_report_mvp.py \
  tests/agents/drug_target/test_drug_report_html.py \
  tests/agents/drug_target/test_part4_candidate_selector.py \
  tests/agents/drug_target/test_part4_candidate_selector_integration.py \
  tests/agents/drug_target/test_part4_therapeutic_synthesis.py
```

Expected: all tests pass; failure cases retain `drug.md` plus audits and leave no Part 4/HTML files.

- [ ] **Step 9: Commit the guardrail owner**

```bash
git add \
  src/agents/drug_target/report_guardrails.py \
  src/agents/drug_target/production_report_tools.py \
  src/agents/drug_target/middleware.py \
  tests/agents/drug_target/test_report_guardrail_middleware.py
git commit -m "$(cat <<'EOF'
Make guarded publication the only successful report completion path

Constraint: Repair is bounded to three passes and downstream artifacts must never survive a failed publication.
Rejected: Let the report writer self-retry | mixes generation policy with deterministic validation and cannot enforce publication cleanup.
Confidence: high
Scope-risk: moderate
Directive: Keep validation, repair accounting, audit persistence, and Part 4/HTML publication owned by DrugReportGuardrailMiddleware.
Tested: OPENAI_API_KEY=test uv run pytest -q tests/agents/drug_target/test_report_guardrail_middleware.py tests/agents/drug_target/test_finalization_validator.py tests/agents/drug_target/test_deterministic_report_mvp.py tests/agents/drug_target/test_drug_report_html.py tests/agents/drug_target/test_part4_candidate_selector.py tests/agents/drug_target/test_part4_candidate_selector_integration.py tests/agents/drug_target/test_part4_therapeutic_synthesis.py
Not-tested: Live report repair or live Part 4 selector provider.
EOF
)"
```

---

### Task 4: Replace the Production Hypothesis Writer with the Guarded Report Writer

**Files:**
- Modify: `src/agents/drug_target/subagents/prompts.py:1-1510,2375-2390`
- Modify: `src/agents/drug_target/subagents/configs.py:1-35,250-455`
- Modify: `src/agents/drug_target/agent.py:1-360`
- Modify: `src/agents/drug_target/production_report_tools.py`
- Modify: `src/agents/drug_target/tools/evidence_loader.py`
- Modify: `src/agents/deep_interpreter/middleware/write_file_guard.py`
- Modify: `src/agents/drug_target/super_graph.py` (set explicit legacy workflow mode and label its module docstring as compatibility-only)
- Modify: `src/agents/drug_target/finalize_report.py` (legacy/deprecated wording only)
- Modify: `scripts/run_drug_target_traced.py` (set the explicit legacy workflow mode and deprecation label only)
- Modify: `docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py:449-463` (set the explicit legacy workflow mode only)
- Modify: `scripts/run_report_writer_only.py`
- Modify: `scripts/run_drug_target_e2e.py`
- Modify: `scripts/run_drug_target_agent_bc.py`
- Modify: `docs/drugtarget/drug_target_agent_reference.md`
- Modify: `docs/drugtarget/drug_target_stage_guide.md`
- Modify: `docs/drugtarget/closed-book-policy.md`
- Modify: `src/agents/drug_target/tools/stage_logic.py:3375-3410` (reference-card instruction only; validator changes are Task 1)
- Modify: `skills/drug-target-reporting/SKILL.md`
- Modify: `skills/drug-target-reporting/references/scoring_guide.md`
- Modify: `skills/drug-target-reporting/evals/evals.json`
- Modify: `skills/drug-target-reporting/templates/drug_report.md.j2:300-315`
- Modify: `src/agents/drug_target/templates/drug_report.md.j2:300-315`
- Create: `tests/agents/drug_target/test_report_writer_prompt.py`
- Create: `tests/agents/drug_target/test_report_writer_skill_contract.py`
- Modify: `tests/test_drug_target.py`
- Modify: `tests/agents/drug_target/test_orchestrator_middleware_chain.py`
- Modify: `tests/agents/drug_target/test_subagent_prompt_sanitization.py`
- Modify: `tests/agents/drug_target/test_subagent_prompts_cleanup.py`
- Modify: `tests/agents/drug_target/test_hypothesis_writer_skill_activation_prompt.py:450-660`
- Modify: `tests/agents/drug_target/test_resume_instruction.py`
- Modify: `tests/agents/drug_target/test_config_ollama_openai.py`
- Modify: `tests/agents/drug_target/test_hypothesis_celltype_focus.py`
- Modify: `tests/test_write_file_guard.py`
- Create: `tests/scripts/test_run_report_writer_only.py`
- Create: `tests/scripts/test_run_drug_target_e2e.py`
- Create: `tests/scripts/test_run_drug_target_agent_bc.py`
- Modify: `tests/benchmarks/test_hypothesis_generation_consistency.py`
- Verify only: `tests/test_run_drug_target_traced.py`
- Verify only: `tests/scripts/test_run_drug_target_traced_budget.py`
- Verify only: `tests/agents/drug_target/test_super_graph_hypothesis_retry.py`
- Verify only: `tests/agents/drug_target/test_hypothesis_writer_prompt_category_contract.py`
- Verify only: `tests/agents/drug_target/test_hypothesis_writer_prompt_save_contract.py`
- Verify only: `tests/agents/drug_target/test_prompts_clinical_compounds_rule.py`
- Verify only: `tests/agents/drug_target/test_prompts_gap_analysis_rule.py`
- Verify only: `tests/agents/drug_target/test_prompts_reflection_guidance.py`
- Verify only: `tests/agents/drug_target/test_drug_profile_coverage.py`

**Interfaces:**
- Add/reuse: `Provider = Literal["openai", "google", "ollama", "ollama-openai", "vllm", "claude", "openrouter"]` in `agent.py`; use it for `DrugTargetConfig.provider` and the Task 5 factories.
- Add: `WorkflowMode = Literal["guarded_report", "legacy_hypothesis"]` and `DrugTargetConfig.workflow_mode: WorkflowMode = "guarded_report"`.
- Production top-level middleware: prepend exactly one `DrugReportRunCleanupMiddleware(resolved_data_dir)` in `create_drug_target_agent`; explicit `legacy_hypothesis` construction must attach none.
- Production filesystem boundary: attach exactly one configured-directory `DrugTargetManagedFilesystemGuardMiddleware` to the guarded top-level orchestrator and to each production subagent (`evidence_assessor`, `report_writer`); neither subagent may rely on raw DeepAgents `read_file`, `grep`, `write_file`, `edit_file`, or Docker `execute`, and every tool whose schema accepts `data_dir` is rewritten to the run directory before dispatch.
- Production dispatch boundary: attach exactly one `DrugTargetTaskAllowlistMiddleware({"evidence_assessor", "report_writer"})` at the guarded top level so the automatic DeepAgents `general-purpose` subagent is unreachable. Explicit legacy construction keeps the dependency default.
- Production orchestrator tool boundary: expose only the dedicated `load_lr_candidates` tool at the guarded top level. Remove raw `read_skill_file` there because the orchestrator has no skill contract; preserve it only in explicit `legacy_hypothesis` construction if that compatibility path still requires it.
- Production evidence boundary: add `scope="assessment"` to raw `load_evidence_files` as an opt-in that behaves like `all` except it excludes every `hypothesis_report*.json` prior output and exact `report_data.json` before opening either. Apply the same early exclusion to `scope="hypothesis"`; preserve raw tool default `scope="all"` for independent legacy callers.
- Production tool wrappers: every wrapper is constructed with the resolved run directory and ignores a caller-supplied alternate path. `evidence_assessor` gets same-name wrappers that force `load_evidence_files(scope="assessment")` and reject forbidden output names before delegating `save_evidence`; `report_writer` gets same-name wrappers that force `load_evidence_files(scope="hypothesis")`, `build_evidence_summary(include_legacy_hypothesis=False)`, `save_target_assessment`, and `save_drug_md(strip_unexpanded_markers=False)`. `report_writer` gets a same-name skill reader restricted to `skills/drug-target-reporting/...`; `evidence_assessor` omits `read_skill_file` when its configured skill tuple is empty and otherwise gets the same allow-listed wrapper. Caller-supplied unsafe values are ignored or rejected, not forwarded. Explicit legacy factories retain raw tools.
- Production extension boundary: `guarded_report` rejects non-empty `custom_tools` before agent/subagent construction. `get_legacy_subagents` and explicit `legacy_hypothesis` configuration retain the prior extension behavior.
- Shared defense: `WriteFileArgGuardMiddleware` treats both `write_file` and `edit_file` as mutations and blocks `report_data.json` in addition to the existing managed report/hypothesis names; deterministic legacy writers that write directly are unaffected.
- Add: `LEGACY_ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE` and `LEGACY_RESUME_ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE` by renaming the current hypothesis/finalizer templates; production keeps the unprefixed names.
- Production `WORKFLOW_ORDER == ["evidence_assessor", "report_writer"]`.
- Production `_TOP_LEVEL_SUBAGENTS == ("evidence_assessor", "report_writer")`.
- Production `get_subagents(...)` returns those two names only, requires a non-empty resolved `data_dir`, and accepts `provider: str | None = None` plus the resolved skills root for middleware/tool construction.
- Add `get_legacy_subagents(...)` as the only factory that returns `evidence_assessor` plus `hypothesis_writer`; call it only when `workflow_mode == "legacy_hypothesis"`.
- `SUBAGENT_CONFIGS["hypothesis_writer"]`, hypothesis prompt renderers, and `HypothesisRetryLoopMiddleware` remain available to direct legacy/benchmark imports but are never returned by production `get_subagents()`.
- Keep the `hypothesis_writer_prompt_mode` keyword accepted but document it as deprecated and ignored by production `get_subagents`; explicit legacy callers pass it to `get_legacy_subagents` or use `render_hypothesis_writer_prompt` directly.

- [ ] **Step 1: Write failing topology, tool, prompt, and middleware tests**

Assert the production subagent contract:

```python
subagents = get_subagents(data_dir=str(tmp_path), disease="IPF", provider="ollama")
assert [item["name"] for item in subagents] == [
    "evidence_assessor",
    "report_writer",
]

report_writer = subagents[1]
tool_names = {
    getattr(tool, "name", getattr(tool, "__name__", type(tool).__name__))
    for tool in report_writer["tools"]
}
assert tool_names == {
    "build_evidence_summary",
    "load_evidence_files",
    "load_lr_candidates",
    "read_skill_file",
    "save_drug_md",
    "save_target_assessment",
    "sequential_thinking",
    "think_tool",
    "validate_quality",
}
assert sum(
    isinstance(item, DrugReportGuardrailMiddleware)
    for item in report_writer["middleware"]
) == 1
assert not any(
    isinstance(item, DrugReportGuardrailMiddleware)
    for item in subagents[0]["middleware"]
)
assert all(
    sum(
        isinstance(item, DrugTargetManagedFilesystemGuardMiddleware)
        for item in subagent["middleware"]
    ) == 1
    for subagent in subagents
)
```

Locate the two same-name loader tools, target/report save tools, reporting skill reader, and report summary tool in those returned specs. Assert they are not the raw exported tool objects. Invoke every production wrapper with a different existing caller `data_dir` and adversarial optional values: the raw boundaries must receive only the configured run directory, assessment/report loaders must force `"assessment"`/`"hypothesis"`, summary must force `include_legacy_hypothesis=False`, and `save_drug_md` must force `strip_unexpanded_markers=False`. For the evidence-assessor save wrapper, parameterize raw, summarizer-sanitized, last-rejection, and draft `hypothesis_report*.json` names plus `report_data.json`; assert each returns `saved=False` without calling raw `save_evidence`, while a normal `stage3_GENE1.json` delegates in the configured directory. Assert the default evidence assessor has no `read_skill_file`; when an explicit non-empty skill tuple is configured, use a temporary custom `skills_dir` and assert its same-name reader returns bounded line-numbered content for both `skills/<allowed-name>/...` and an absolute path canonically inside `<skills_dir>/<allowed-name>/`. Reject other relative paths, outside absolute paths, traversal, another skill, and a symlink escape. Assert the same resolved root/allow-list is supplied to `SkillsMiddleware`, and assert `get_legacy_subagents` still holds the raw loader/save/skill-reader tools.

For each production subagent, inspect every returned tool schema/signature. Collect all public tool names that accept `data_dir`, locate its `DrugTargetManagedFilesystemGuardMiddleware`, and assert its `data_dir_tool_names` is exactly that set and its configured directory is `tmp_path`. Exercise one unwrapped query tool through the guard with an omitted path and another with a different existing path; both handlers must receive `tmp_path`. This proves the generic guard covers stage query/batch tools in addition to the critical same-name wrappers.

Capture the top-level `tools=`, `subagents=`, and `middleware=` arguments passed to `create_deep_agent`. In default/guarded mode, assert the public tool-name set is exactly `{"load_lr_candidates"}`, the raw `read_skill_file` object is absent, the configured-directory filesystem guard binds `load_lr_candidates`, and exactly one `DrugTargetTaskAllowlistMiddleware` allows only `evidence_assessor`/`report_writer`. Invoke the allowlist with `subagent_type="general-purpose"` and assert the handler is not called, then prove both domain names pass. In explicit `legacy_hypothesis` mode, assert the pre-migration top-level tools/subagents remain available and neither production boundary middleware is attached. This regression is required because installed DeepAgents auto-registers `general-purpose` with a separate filesystem stack.

Add guarded/legacy extension tests: `DrugTargetConfig(workflow_mode="guarded_report", custom_tools=[reader_tool])` and direct `get_subagents(custom_tools=[reader_tool])` must raise a clear `ValueError` before `create_deep_agent`; `workflow_mode="legacy_hypothesis"`/`get_legacy_subagents` must retain the current custom-tool propagation test. Use an innocuous fake tool; the boundary is policy, not name matching.

In the prompt regression, also assert the evidence-assessor surface advertises `load_evidence_files(data_dir=data_dir, scope="assessment")` rather than a bare/default-all call.

In `test_hypothesis_celltype_focus.py`, parameterize malformed raw, summarizer-sanitized, last-rejection, and draft hypothesis outputs plus `report_data.json`. Prove raw `load_evidence_files(scope="assessment")` and `scope="hypothesis"` place them in `excluded_files`, return no parse error, and never place them in `files`; the malformed payload makes the test red if any path is opened. Keep an explicit `scope="all"` compatibility test showing the raw default behavior is unchanged for legacy/direct callers.

In `test_write_file_guard.py`, parameterize `write_file` and `edit_file` across `drug.md`, `target_assessment.json`, a hypothesis-report variant, and `report_data.json`. In both sync and async wrappers, assert the handler is not called. Keep a near-miss path test and the existing non-string `write_file` coercion tests.

In `test_orchestrator_middleware_chain.py`, capture the middleware passed to the top-level `create_deep_agent` and assert that default/guarded construction has exactly one `DrugReportRunCleanupMiddleware`, one configured-directory `DrugTargetManagedFilesystemGuardMiddleware`, and one `DrugTargetTaskAllowlistMiddleware`, while explicit `legacy_hypothesis` construction has none. Seed stale source, audit, Part 4, and HTML files; invoke the captured cleanup middleware's sync `before_agent` without dispatching either subagent; assert every guarded output is removed and unrelated legacy sidecars remain. This proves direct `langgraph.json` runs cannot inherit prior success when orchestration exits before `report_writer`.

In the new prompt test, assert both modes and forbidden production operations:

```python
def test_report_writer_prompt_owns_direct_markdown_and_repair_contract() -> None:
    assert "build_evidence_summary" in REPORT_WRITER_PROMPT
    assert "include_legacy_hypothesis=False" in REPORT_WRITER_PROMPT
    assert "load_evidence_files" in REPORT_WRITER_PROMPT
    assert 'scope="hypothesis"' in REPORT_WRITER_PROMPT
    assert "save_target_assessment" in REPORT_WRITER_PROMPT
    assert "save_target_assessment exactly once" in REPORT_WRITER_PROMPT
    assert "save_drug_md" in REPORT_WRITER_PROMPT
    assert "strip_unexpanded_markers=False" in REPORT_WRITER_PROMPT
    assert "## REPAIR MODE" in REPORT_WRITER_PROMPT
    assert "Do not read skills or call initial-write tools" in REPORT_WRITER_PROMPT
    assert "Section 4" in REPORT_WRITER_PROMPT
    assert "#### 4.1.1." in REPORT_WRITER_PROMPT
    assert "- Genes:" in REPORT_WRITER_PROMPT
    assert "save_report_expansions" not in REPORT_WRITER_PROMPT
    assert "render_drug_md_from_expansions" not in REPORT_WRITER_PROMPT
    assert "generate_drug_html_report" not in REPORT_WRITER_PROMPT
    assert "NEVER create or read evidence/hypothesis_report.json" in REPORT_WRITER_PROMPT
    assert "NEVER create or write report_data.json" in REPORT_WRITER_PROMPT
    assert REPORT_WRITER_PROMPT.index(
        "save_target_assessment"
    ) < REPORT_WRITER_PROMPT.index("save_drug_md")
```

In `test_report_writer_skill_contract.py`, read the exact files that `report_writer` is told to load and lock them to the same tool/file contract:

```python
SKILL_PATH = Path("skills/drug-target-reporting/SKILL.md")
SCORING_PATH = Path("skills/drug-target-reporting/references/scoring_guide.md")


def test_reporting_skill_matches_guarded_direct_writer_surface() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")

    assert "GUARDED REPORT AUTHOR" in text
    assert "build_evidence_summary" in text
    assert 'load_evidence_files' in text
    assert 'scope="hypothesis"' in text
    assert "save_target_assessment" in text
    assert "save_target_assessment exactly once" in text
    assert "save_drug_md" in text
    assert "strip_unexpanded_markers=False" in text
    assert "DrugReportGuardrailMiddleware" in text
    assert "NEVER create or read evidence/hypothesis_report.json" in text
    assert "NEVER create or write report_data.json" in text
    assert text.index("save_target_assessment") < text.index("save_drug_md")
    for retired_operation in (
        "save_report_expansions",
        "render_drug_md_from_expansions",
        "generate_drug_html_report",
    ):
        assert retired_operation not in text


def test_reporting_scoring_guide_does_not_source_section_4_from_legacy_json() -> None:
    text = SCORING_PATH.read_text(encoding="utf-8")

    assert "hypothesis_report.json" not in text
    assert "hypothesis-scope evidence" in text
    assert "drug.md" in text
```

Also parse `evals/evals.json` and assert its scenarios mention initial direct write and repair, never the three retired operations. Assert both Markdown templates contain the same explicit Section 4 `EXPAND` marker and no longer contain “hypothesis_writer subagent may not have completed.”

Update `test_config_ollama_openai.py::_get_provider_literal_values` before changing the annotation. Build a module-level map of `AnnAssign` aliases, and when `DrugTargetConfig.provider` is an `ast.Name`, resolve that name to the aliased `Literal[...]` subscript before extracting constants. Keep all existing provider-membership assertions and add `test_drug_target_config_provider_uses_shared_provider_alias`, which asserts the field annotation is the name `Provider`. This preserves the AST regression's intent instead of weakening it.

Update orchestrator tests to require the exact terminal line `REPORT_PIPELINE_COMPLETE` and to reject production dispatch to `hypothesis_writer`.

- [ ] **Step 2: Run the focused configuration tests and verify the red state**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/test_drug_target.py \
  tests/agents/drug_target/test_report_writer_prompt.py \
  tests/agents/drug_target/test_report_writer_skill_contract.py \
  tests/agents/drug_target/test_orchestrator_middleware_chain.py \
  tests/agents/drug_target/test_hypothesis_celltype_focus.py \
  tests/agents/drug_target/test_subagent_prompt_sanitization.py \
  tests/agents/drug_target/test_resume_instruction.py \
  tests/test_write_file_guard.py \
  tests/scripts/test_run_report_writer_only.py \
  tests/scripts/test_run_drug_target_e2e.py \
  tests/scripts/test_run_drug_target_agent_bc.py
```

Expected: failures show `hypothesis_writer` is still returned, production safe-tool/filesystem guards are absent, the top-level raw skill reader remains exposed, sanitized prior-report evidence is still opened, `report_data.json` edit/write is not blocked, migrated runners lack canonical guarded/audit success gating, the resume helper is still hypothesis-specific, and the loaded reporting skill/evals/templates still advertise the retired renderer workflow.

- [ ] **Step 3: Rewrite only the production report-writer prompt contract**

Keep the existing closed-book, source-grounding, clinical-compound, MOA, rubric, and gap-analysis rules. Replace renderer/expansion/HTML instructions with these exact operational phases:

```text
MODE SELECTION
If the user message starts with ## REPAIR MODE, follow only REPAIR MODE. Do not read skills or call initial-write tools. Otherwise follow INITIAL WRITE.

INITIAL WRITE
1. Read the drug-target-reporting skill and scoring guide.
2. Call load_lr_candidates.
3. Call build_evidence_summary exactly once with include_legacy_hypothesis=False; use its Markdown template and reference card.
4. Call load_evidence_files with scope="hypothesis" for grounded Section 4 content.
5. Construct the complete target-assessment payload from the loaded evidence and call save_target_assessment exactly once. This run starts without target_assessment.json.
6. Complete every required drug.md section, including parseable Section 4 hypotheses.
7. Call save_drug_md exactly once with strip_unexpanded_markers=False and stop. save_target_assessment must happen first. Do not self-repair, render HTML, or build Part 4.

REPAIR MODE
1. Use the current Markdown embedded in the repair request.
2. Fix only the listed validation issues.
3. Do not call build_evidence_summary or regenerate target_assessment.json.
4. Call save_drug_md exactly once with strip_unexpanded_markers=False and stop.
```

The prompt must include the two exact `NEVER` file sentences asserted above, and must state that the writer does not build renderer expansions, Part 4, or HTML. Do not include the retired tool names; the test distinguishes an explicit file prohibition from accidentally advertising obsolete operations.

Embed one canonical parser-compatible Section 4 entry in the prompt; subsequent entries use `4.1.2`, `4.2.1`, or `4.3.1` as appropriate:

```markdown
## 4. Mechanistic Hypothesis Recommendations

#### 4.1.1. <hypothesis title>
**Category:** <category>
**Core Claim:** <grounded, hedged claim>
- Genes: <comma-separated genes>
- Pathways: <comma-separated pathways or data not available>
- Cell Types: <comma-separated cell types or data not available>
- Drugs: <comma-separated drugs or data not available>
**Falsifiable Prediction:** <prediction>
**Validation Approach:** <test>
```

These labels/capitalization match `parse_drug_md`; do not invent a second hypothesis parser in the guardrail.

- [ ] **Step 4: Align the loaded reporting skill, scoring guide, evals, and templates**

Rewrite only the reporting skill's runtime contract; retain its evidence hierarchy, score/tone calibration, clinical-compound, MOA, closed-book, and anti-hallucination rules. The resulting skill must:

- name the role `GUARDED REPORT AUTHOR`, not `NARRATIVE EXPANDER`;
- describe the same `INITIAL WRITE` and `REPAIR MODE` phases as `REPORT_WRITER_PROMPT`;
- list only tools present on the production `report_writer` surface;
- require `build_evidence_summary(..., include_legacy_hypothesis=False)` and `load_evidence_files(..., scope="hypothesis")` during initial write;
- require exactly one `save_target_assessment` call followed by one `save_drug_md(..., strip_unexpanded_markers=False)` call, and no self-validation/publication calls;
- make `DrugReportGuardrailMiddleware` the owner of deterministic validation, up-to-three repair passes, Part 4, HTML, and audits;
- include the same parser-compatible Section 4 example and the two exact forbidden-file sentences;
- state that `[source: ...]` annotations are retained in `drug.md` as deterministic audit provenance in the direct-writer path. Remove the false renderer-era claim that post-processing strips them before users see the file; do not add an unvalidated cleanup pass after the final audit.

Remove every positive instruction for `save_report_expansions`, `render_drug_md_from_expansions`, `validate_drug_md`, `generate_drug_html_report`, running after `hypothesis_writer`, or using `hypothesis_report.json` as the Section 4 source. The legacy modules may keep those operations, but the production-loaded skill must not advertise unavailable tools.

In `references/scoring_guide.md`, map the recommendation section to `load_evidence_files(scope="hypothesis")` evidence plus the final `drug.md`. In `evals/evals.json`, replace the old expansion/HTML happy path with two no-live-model fixtures: a complete initial direct write and a repair request that changes only listed issues and saves once.

In both Markdown template copies, replace:

```markdown
*No follow-up recommendation analysis available. The hypothesis_writer subagent may not have completed.*
```

with:

```markdown
<!-- EXPAND: Author one or more parser-compatible Section 4 recommendations from hypothesis-scope evidence. -->
```

Keep the copies byte-identical. Because `save_drug_md` now preserves markers, an omitted Section 4 remains a visible `UNEXPANDED_PLACEHOLDER` and `AGENT_REPORT_HYPOTHESES_MISSING` repair target instead of becoming silent blank text.

Also update the `build_evidence_summary` reference-card instruction in `stage_logic.py`: describe the template as a factual skeleton for a complete direct Markdown write, explicitly require replacing all markers and authoring Section 4 from hypothesis-scope evidence, and remove the old “ONLY expand 2-4 sentences” wording.

- [ ] **Step 5: Add production-safe tool surfaces and the report-writer config**

In `evidence_loader.py`, add one `_is_forbidden_prior_report_output(name)` predicate: the case-folded basename either starts with `hypothesis_report` and ends with `.json`, or equals `report_data.json`. Use it alongside `_HYPOTHESIS_DENIED_CITATIONS` in every hypothesis citation gate and in both safe loader scopes. Recognize `scope="assessment"`; before opening JSON content, append any matching prior-report filename to `excluded_files` and continue. All other files follow the current `scope="all"` size/full-content behavior. Apply the same early exclusion in `scope="hypothesis"`. Keep omitted/`scope="all"` loading behavior byte-for-byte compatible for direct legacy callers, and update the tool docstring with all three scopes.

Update the evidence-assessor prompt's existing bare `load_evidence_files(data_dir)` instruction to `load_evidence_files(data_dir, scope="assessment")`. The wrapper remains the enforcement boundary if the model omits or changes that argument; the prompt change keeps the advertised workflow honest.

Extend `production_report_tools.py` with these same-name `StructuredTool` factories:

- `production_assessment_evidence_tool(data_dir)`: accepts caller `data_dir`/`scope` for schema compatibility but always invokes raw `load_evidence_files` with the configured directory and `scope="assessment"`;
- `production_hypothesis_evidence_tool(data_dir)`: retains Task 3 behavior while forcing the configured directory and `scope="hypothesis"`;
- `production_evidence_summary_tool(data_dir)`: accepts caller `data_dir`/`include_legacy_hypothesis` but always invokes raw `build_evidence_summary` with the configured directory and `False`;
- `production_assessment_save_evidence_tool(data_dir)`: preserves the raw `save_evidence` signature/name, forces the configured directory, and returns a deterministic `saved=False` JSON response without delegation for any basename matching `hypothesis_report*.json` or exactly `report_data.json`; all other filenames delegate;
- `production_save_target_assessment_tool(data_dir)`: preserves the public name/signature while forcing the configured directory;
- `production_save_drug_md_tool(data_dir)`: preserves the public name/signature while forcing the configured directory and `strip_unexpanded_markers=False`;
- `production_skill_reader_tool(skills_dir, allowed_skill_names)`: preserves the `read_skill_file(skill_path, offset=0, limit=2000)` public contract. Normalize the prompt-facing `skills/<name>/...` alias by stripping the leading `skills/` before joining the configured skills root; also accept an absolute path only when its canonical target remains under `<skills_dir>/<allowed-name>/`. Reject every other relative/absolute path, traversal, symlink escape, and unlisted skill. Implement the bounded line-numbered read inside the wrapper so a supported `DrugTargetConfig.skills_dir` outside the project root does not fall back to the raw reader's project-root restriction.

Keep the public names `load_evidence_files`, `build_evidence_summary`, `save_evidence`, `save_target_assessment`, `save_drug_md`, and `read_skill_file`, so existing prompts and DeepAgents tool selection remain stable. Keep the raw exported tools unchanged for direct callers and `get_legacy_subagents`. The wrapper tests from Step 1 must invoke unsafe optional values/paths—not merely inspect prompt text.

In `WriteFileArgGuardMiddleware`, change the managed-artifact predicate to run for both `write_file` and `edit_file`; add `report_data.json` to `_BLOCKED_ARTIFACT_NAMES`. Preserve content coercion/path normalization only for `write_file`. Update the blocked message without removing the existing dedicated-save guidance, and state that `report_data.json` is internal and may not be agent-authored. This is defense in depth; the production managed-filesystem guard blocks both mutation tools entirely.

Import `REPORT_WRITER_PROMPT`, `DrugReportGuardrailMiddleware`, `DrugTargetManagedFilesystemGuardMiddleware`, and the production tool factories. Add `SUBAGENT_PROMPTS["report_writer"]` and a raw compatibility `SUBAGENT_CONFIGS["report_writer"]`; production copies replace every path-sensitive load/save tool with the same-name bound factory while preserving the exact public tool-name set from Step 1.

When constructing production copies, require the resolved `data_dir`, resolve an omitted `skills_dir` through the repository-root helper, and reject non-empty `custom_tools`. Replace the evidence assessor's raw loader/save tools with `production_assessment_evidence_tool(data_dir)` and `production_assessment_save_evidence_tool(data_dir)`. Remove raw `read_skill_file` when its configured skill tuple is empty; otherwise insert `production_skill_reader_tool(skills_dir, allowed_names)`. Give `report_writer` the bound hypothesis loader, evidence summary, target save, drug save, and `production_skill_reader_tool(skills_dir, ("drug-target-reporting",))`. After the final tool lists are built, derive each subagent's `data_dir_tool_names` from `BaseTool.args` and callable signatures and prepend exactly one `DrugTargetManagedFilesystemGuardMiddleware(data_dir, data_dir_tool_names=...)` before skill middleware is added. Pass the same `skills_dir`/allow-list pairs to `SkillsMiddleware` and the reader factory so discovery and content access cannot disagree. The explicit legacy factory must clone raw evidence-assessor/hypothesis-writer tool lists, retain custom-tool propagation, and attach no production boundary middleware.

Set:

```python
WORKFLOW_ORDER = ["evidence_assessor", "report_writer"]
_TOP_LEVEL_SUBAGENTS = ("evidence_assessor", "report_writer")
```

Inside `get_subagents`, attach:

```python
DrugReportGuardrailMiddleware(
    data_dir=data_dir,
    provider=provider,
    disease=safe_disease,
)
```

only when `subagent["name"] == "report_writer"`, reusing the same `_sanitize_prompt_value` result already injected into the subagent prompt. Remove production insertion of `HypothesisRetryLoopMiddleware`; do not delete that class or the legacy config.

Update the skill-governor branch for the new production owner:

```python
hard_required_skill_names = (
    ("drug-target-reporting",)
    if (
        subagent["name"] == "report_writer"
        and "drug-target-reporting" in allowed_names
    )
    else ()
)
artifact_gate = (
    "save_drug_md"
    if subagent["name"] == "report_writer"
    else "final artifact"
)
```

Remove hypothesis-writer prompt mode from production governor decisions. Update the injected data-directory note to name tools actually available to each returned subagent rather than advertising `save_evidence` to `report_writer`.

Move the current hypothesis-writer branch into exported `get_legacy_subagents(...)` without changing its prompt-mode rendering, skill governor, tool set, or `HypothesisRetryLoopMiddleware`. In `create_drug_target_agent`, choose that factory only for `config.workflow_mode == "legacy_hypothesis"`; otherwise call production `get_subagents`. Keep `WORKFLOW_ORDER` and `_TOP_LEVEL_SUBAGENTS` production-only, and name the legacy tuple `LEGACY_WORKFLOW_ORDER` so no shared constant can silently switch production back. Add the legacy factory/order to `configs.__all__` with a deprecation comment; do not alias either one back to the production names.

Rename the existing hypothesis/finalizer orchestrator templates in `agent.py` to `LEGACY_ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE` and `LEGACY_RESUME_ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE` before adding the new production templates. `create_drug_target_agent` must select the subagent factory, normal/resume orchestrator template, model map, skill map, and resume helper from the same `workflow_mode` branch. This prevents the retained outer super-graph from receiving a production prompt that dispatches nonexistent `report_writer`, and prevents production from receiving the old finalizer instructions.

Set `workflow_mode="legacy_hypothesis"` in the configuration built by `super_graph._drug_target_config_from_state` and by `scripts/run_drug_target_traced.py`. Label the `super_graph.py` module docstring as an explicit compatibility-only graph, and add a deprecation/help label to the traced CLI stating that it exercises the retained outer hypothesis/finalizer benchmark, not the production guardrail path. Do not otherwise rewrite either legacy algorithm in this migration.

Add tests that default `DrugTargetConfig()` and both Task 5 entrypoints use `guarded_report`, while explicit legacy mode still constructs `evidence_assessor` + `hypothesis_writer` with `HypothesisRetryLoopMiddleware` and a prompt containing `hypothesis_writer`/`finalize_report` but not a `report_writer` dispatch. Conversely, assert the production prompt contains `report_writer`/`REPORT_PIPELINE_COMPLETE` and no finalizer dispatch. Run the existing async `test_super_graph_hypothesis_retry.py` cases as runnable compatibility evidence, not just import checks.

Replace the obsolete strict-xfail cleanup test with a positive production-surface test:

```python
def test_report_writer_prompt_is_registered_as_a_production_surface() -> None:
    from src.agents.drug_target.subagents import prompts

    assert prompts.SUBAGENT_PROMPTS["report_writer"] is prompts.REPORT_WRITER_PROMPT
```

Update the comment immediately above `REPORT_WRITER_PROMPT` to say it is the canonical production writer prompt; remove the old “retained pending reader migration” rationale.

- [ ] **Step 6: Update `DrugTargetConfig` and orchestrator routing**

Add production fields:

```python
workflow_mode: WorkflowMode = "guarded_report"
report_writer_skill_names: tuple[str, ...] = (
    "drug-target-reporting",
)
report_writer_resume_instruction: str | None = None
```

Keep legacy hypothesis fields with a deprecation comment for benchmark constructors. In `DrugTargetConfig.__post_init__`, reject non-empty `custom_tools` when `workflow_mode == "guarded_report"`, load model overrides for `evidence_assessor` plus `report_writer` in that mode, and load `evidence_assessor` plus `hypothesis_writer` when `workflow_mode == "legacy_hypothesis"`; never drop `SUBAGENT_HYPOTHESIS_WRITER_*` overrides from the retained benchmarks. Make the per-subagent skill map branch on the same mode. Pass `provider=config.provider`, resolved `data_dir`, and resolved `_resolve_skills_dir(config)` into production `get_subagents`; pass custom tools only to the explicit legacy factory.

Resolve the configured skills directory before the host/Docker backend branch. Keep the current Docker choice to omit shared `SkillsMiddleware` if required, but still pass the canonical host skills root into the bounded `read_skill_file` wrapper so the production report-writer prompt has the same allow-listed content surface in both backends.

Build the top-level middleware and tool lists once in `create_drug_target_agent`. For `guarded_report`, pass only `[load_lr_candidates]` as top-level tools and prepend `DrugReportRunCleanupMiddleware(data_dir=resolved_data_dir)`, `DrugTargetManagedFilesystemGuardMiddleware(resolved_data_dir, data_dir_tool_names={"load_lr_candidates"})`, and `DrugTargetTaskAllowlistMiddleware({"evidence_assessor", "report_writer"})` ahead of the existing write-file, think-quality, read-file, and subagent-error guards. The task allowlist must reject DeepAgents' automatically registered `general-purpose` subagent before dispatch. For `legacy_hypothesis`, preserve the existing tools, custom tools, subagent specs, and middleware exactly and attach none of the three production middleware. Pass these mode-specific lists to `create_deep_agent`; do not rely on `graph_builder.py` or the integration wrapper to perform the only cleanup. The middleware's unit tests in Task 3 prove sync/async semantics, and `test_orchestrator_middleware_chain.py` proves production attachment, configured-directory binding, automatic-subagent rejection, raw-reader removal, and legacy exclusion.

Change the normal orchestrator sequence to:

```text
load_lr_candidates -> evidence_assessor -> report_writer -> REPORT_PIPELINE_COMPLETE
```

Replace the literal `load_lr_candidates(data_dir="{data_dir}", disease="{disease}")` template line in both normal workflow templates with `{load_lr_candidates_invocation}`. Build that string in `create_drug_target_agent` from JSON-quoted/sanitized values: include the `disease=` keyword only when `config.disease.strip()` is non-empty; otherwise call `load_lr_candidates(data_dir=...)` so the tool uses the disease in `lr_candidates.json`. Use “the disease returned by load_lr_candidates” as prose context for the blank case—never the truthy sentinel `"(see lr_candidates.json)"` as a tool argument. Add mocked `create_deep_agent` tests for explicit `IPF` and blank disease prompt rendering in both guarded and legacy normal modes.

Change production resume mode to dispatch only `report_writer` using a renamed `_format_report_writer_resume_instruction`. Its exact default is:

```python
(
    "Write target_assessment.json and a complete drug.md from evidence already "
    f"on disk. Data dir: {resolved_data_dir}"
)
```

Keep the existing quote/newline sanitization. In `test_resume_instruction.py`, import the renamed helper, assert that exact default, and set/assert `report_writer_resume_instruction` for the custom case. The explicit `legacy_hypothesis` branch may continue to use the old helper/field for the retained super-graph/traced benchmark; do not leave production resume coupled to it. Remove production imports and comments that claim the outer finalizer writes the report.

In `docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py::run_hypothesis_writer_once`, add `workflow_mode="legacy_hypothesis"` to its `DrugTargetConfig`. Add an async test in `tests/benchmarks/test_hypothesis_generation_consistency.py` that monkeypatches `create_drug_target_agent` with a fake agent/backend, captures the config, runs the helper without a live model, and asserts the legacy workflow, hypothesis skill tuple, prompt mode, and resume instruction are all forwarded. Do not edit the frozen `repro/` snapshot copies.

Replace the duplicated raw-agent construction in `scripts/run_report_writer_only.py` with the canonical guarded factory. After the existing evidence prerequisite check, call `clear_derived_report_artifacts(..., include_audits=True, include_sources=True)` through `asyncio.to_thread`; this is intentionally redundant with the canonical run-start middleware and makes stale-output behavior testable even with a fake agent. Build `DrugTargetConfig(provider=..., data_dir=..., disease=..., workflow_mode="guarded_report", use_checkpointer=True, report_writer_resume_instruction=...)`; when `--model` is supplied, create that report-writer model once and pass it through `subagent_models={"report_writer": model}`. Set `DRUG_TARGET_SKIP_EVIDENCE_ASSESSOR=1` only around factory creation/invocation and restore its prior value in `finally`. Invoke the returned top-level agent, clean up its backend in `finally`, and require the same passed final-audit plus seven-artifact gate as integration before printing `DONE`/returning exit code 0. Remove direct imports of `SUBAGENT_PROMPTS`, raw evidence tools, `create_deep_agent`, and `MemorySaver`; the canonical factory supplies safe wrappers, managed-filesystem guards, run cleanup, report guardrail, and publication.

In `tests/scripts/test_run_report_writer_only.py`, import the script module without running `main`, monkeypatch its agent factory/model boundary, and use a fake agent/backend. Assert `workflow_mode="guarded_report"`, resume mode is active only during invocation and restored afterward, the optional model maps only to `report_writer`, backend cleanup always runs, and a passed audit with all seven outputs returns success. Add failures for missing/failed final audit and a no-op fake writer with stale pre-seeded outputs; run-start cleanup must prevent either from returning success. No case may instantiate a live model.

Update `scripts/run_drug_target_e2e.py` as the canonical full guarded smoke runner: correct the stale three-subagent docstring to `evidence_assessor -> report_writer`, set `workflow_mode="guarded_report"` explicitly, and delete `_extract_drug_md_from_messages` plus its call. A missing `drug.md` is a guardrail failure, never permission to write unvalidated message content after the final audit. Wrap invocation in `try/finally`, restore the prior `DRUG_TARGET_DATA_DIR`, and clean the backend on success, timeout, or exception. Replace `drug_md.exists() and evidence_count > 0` with the final-audit gate (`valid is True`, `publication.status == "passed"`) plus all seven required output files; diagnostics/previews may read outputs but must not mutate them.

In `tests/scripts/test_run_drug_target_e2e.py`, monkeypatch `tempfile.mkdtemp`, agent construction, and the fake invocation so no API/model is used. Assert guarded config, env restoration, backend cleanup, passed-audit/seven-artifact success, failure on timeout or missing publication artifact, and that no helper or fallback call writes `drug.md` from messages. Include a fake long Markdown message with no on-disk report and assert failure with `drug.md` absent.

Update `scripts/run_drug_target_agent_bc.py` as the fixed-dataset convenience runner, not a separate workflow implementation. Make `workflow_mode="guarded_report"` explicit, clear guarded source/audit/derived outputs before construction, retain backend cleanup in `finally`, and change `main()` to return an exit code consumed by `raise SystemExit(asyncio.run(main()))`. Print `DONE` and return `0` only when the final audit is valid, publication passed, and all seven successful-run artifacts exist; otherwise print an error and return `1`. Do not infer success from `drug.md` or evidence counts alone.

In `tests/scripts/test_run_drug_target_agent_bc.py`, monkeypatch its fixed `DATA_DIR`, canonical factory, and fake agent/backend. Assert explicit guarded construction, stale-output cleanup, backend cleanup on success and exception, passed-audit/seven-artifact exit code `0`, and nonzero exit for a no-op agent, failed audit, or missing publication artifact. No test may instantiate a provider model.

Update the three self-described current documents in the same task. In `drug_target_agent_reference.md` and `drug_target_stage_guide.md`, set the verification date to 2026-07-15 and replace current topology, workflow order, entrypoint, middleware, failure, artifact, integration, and runner sections with the direct `DrugReportRunCleanupMiddleware -> evidence_assessor -> report_writer -> DrugReportGuardrailMiddleware` contract. Document `drug.md` as the sole production hypothesis source, the two audits/seven successful artifacts, configured-directory/forced-safe tool surfaces, the blocked automatic `general-purpose` route, guarded custom-tool rejection, all three migrated guarded runners, and `legacy_hypothesis` as the only outer-super-graph/finalizer compatibility path. Do not rewrite dated migration-history sections as if they never happened. In `closed-book-policy.md`, replace the current Layer 5 owner with the bounded guardrail middleware and append a dated 2026-07-15 migration note; keep the 2026-05-19 historical entry explicitly labeled as superseded production architecture.

Make wording-only boundary repairs in already touched legacy surfaces: label the removed summarizer/finalizer note in `subagents/prompts.py` as historical compatibility, label `check_hypothesis_completion` and its recommendations in `tools/evidence_loader.py` as legacy-hypothesis workflow guidance, replace `finalize_report.py`'s “only production caller” comment with the explicit legacy super-graph/traced callers, and replace “production super-graph” comments in `scripts/run_drug_target_traced.py` with “legacy compatibility super-graph.” Do not alter those legacy algorithms in this task.

Migrate the production-assumption sections in `tests/test_drug_target.py` rather than deleting coverage:

- change production workflow/order assertions from `hypothesis_writer` to `report_writer`; update registry assertions to expect all three available prompt/config surfaces (`evidence_assessor`, production `report_writer`, and legacy `hypothesis_writer`);
- pass `tmp_path` explicitly to every production `get_subagents` test and add a fail-fast case for missing/blank `data_dir`; move the existing custom-tool propagation assertion to `get_legacy_subagents` and assert production rejection separately;
- change progressive-disclosure tests to assert `drug-target-reporting` skills on `report_writer`;
- change skill activator/governor tests to use `report_writer_skill_names` and locate `report_writer`;
- replace the production `ReadFileBlockMiddleware` type assertion with `DrugTargetManagedFilesystemGuardMiddleware` assertions covering all five blocked built-ins, and also require `DrugReportGuardrailMiddleware` on `report_writer`; keep the narrower `ReadFileBlockMiddleware` assertion only on the explicit legacy hypothesis writer;
- keep direct `SUBAGENT_CONFIGS["hypothesis_writer"]`, prompt-renderer, retry-middleware, schema, and score-normalization tests as legacy unit coverage;
- remove tests that expect `hypothesis_writer_prompt_mode` to alter the result of production `get_subagents`; move their assertions to `render_hypothesis_writer_prompt(...)` or direct `HypothesisRetryLoopMiddleware` construction.

In `test_hypothesis_writer_skill_activation_prompt.py`, replace production `get_subagents(...)` lookups in the prompt-mode section with `render_hypothesis_writer_prompt(mode)` or explicit `get_legacy_subagents(...)` calls. Convert retry-policy-only cases into direct constructor cases for `HypothesisRetryLoopMiddleware`, preserving checks for `stop_after_first_save`, three-attempt limits, and single-read skill paths. Keep the two hypothesis-specific `SkillActivationGovernor` integration tests, but point them at `get_legacy_subagents` so they prove the explicit benchmark factory retains its old contract without leaking into production `get_subagents`.

- [ ] **Step 7: Run production topology and retained legacy prompt regressions**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/test_drug_target.py \
  tests/agents/drug_target/test_report_writer_prompt.py \
  tests/agents/drug_target/test_report_writer_skill_contract.py \
  tests/agents/drug_target/test_orchestrator_middleware_chain.py \
  tests/agents/drug_target/test_hypothesis_celltype_focus.py \
  tests/agents/drug_target/test_subagent_prompt_sanitization.py \
  tests/agents/drug_target/test_subagent_prompts_cleanup.py \
  tests/agents/drug_target/test_hypothesis_writer_skill_activation_prompt.py \
  tests/agents/drug_target/test_resume_instruction.py \
  tests/agents/drug_target/test_config_ollama_openai.py \
  tests/agents/drug_target/test_super_graph_hypothesis_retry.py \
  tests/benchmarks/test_hypothesis_generation_consistency.py \
  tests/test_write_file_guard.py \
  tests/scripts/test_run_report_writer_only.py \
  tests/scripts/test_run_drug_target_e2e.py \
  tests/scripts/test_run_drug_target_agent_bc.py \
  tests/test_run_drug_target_traced.py \
  tests/scripts/test_run_drug_target_traced_budget.py \
  tests/agents/drug_target/test_prompts_clinical_compounds_rule.py \
  tests/agents/drug_target/test_prompts_gap_analysis_rule.py \
  tests/agents/drug_target/test_prompts_reflection_guidance.py \
  tests/agents/drug_target/test_drug_profile_coverage.py \
  tests/agents/drug_target/test_hypothesis_writer_prompt_category_contract.py \
  tests/agents/drug_target/test_hypothesis_writer_prompt_save_contract.py
```

Expected: all tests pass. Production topology/middleware tests prove the new wiring, forced safe tool scopes, managed-filesystem boundary, and run-start stale-output cleanup even when no subagent is dispatched; the writer-only CLI test proves there is no duplicate unguarded caller; the hypothesis prompt, retry, and super-graph tests prove retained legacy surfaces remain runnable only through the explicit legacy factory without re-entering production `get_subagents`.

Run:

```bash
for doc in \
  docs/drugtarget/drug_target_agent_reference.md \
  docs/drugtarget/drug_target_stage_guide.md \
  docs/drugtarget/closed-book-policy.md
do
  rg -q 'DrugReportGuardrailMiddleware' "$doc"
  rg -q 'legacy_hypothesis' "$doc"
done
for doc in \
  docs/drugtarget/drug_target_agent_reference.md \
  docs/drugtarget/drug_target_stage_guide.md
do
  rg -q 'DrugReportRunCleanupMiddleware' "$doc"
  rg -q 'drug_report_validation_final.json' "$doc"
done
```

Expected: each current document independently names the guarded production owner and explicit legacy boundary; the two architecture guides also name cleanup and the final audit. Dated history may still name `finalize_report`, but no section labeled current/default describes it as production.

Run:

```bash
rg -n \
  'only production caller|production super-graph|Report finalization is now handled by the deterministic finalize_report|proceed to summarizer for production output' \
  src/agents/drug_target/finalize_report.py \
  src/agents/drug_target/tools/evidence_loader.py \
  src/agents/drug_target/subagents/prompts.py \
  scripts/run_drug_target_traced.py
```

Expected: no matches and exit status `1`; retained finalizer/summarizer language is explicitly legacy or historical.

- [ ] **Step 8: Commit the production report-writer topology**

```bash
git add \
  src/agents/drug_target/subagents/prompts.py \
  src/agents/drug_target/subagents/configs.py \
  src/agents/drug_target/agent.py \
  src/agents/drug_target/production_report_tools.py \
  src/agents/drug_target/tools/evidence_loader.py \
  src/agents/deep_interpreter/middleware/write_file_guard.py \
  src/agents/drug_target/super_graph.py \
  src/agents/drug_target/finalize_report.py \
  src/agents/drug_target/tools/stage_logic.py \
  scripts/run_drug_target_traced.py \
  scripts/run_report_writer_only.py \
  scripts/run_drug_target_e2e.py \
  scripts/run_drug_target_agent_bc.py \
  docs/drugtarget/drug_target_agent_reference.md \
  docs/drugtarget/drug_target_stage_guide.md \
  docs/drugtarget/closed-book-policy.md \
  docs/benchmarks/hypothesis_generation_consistency/run_benchmark.py \
  skills/drug-target-reporting/SKILL.md \
  skills/drug-target-reporting/references/scoring_guide.md \
  skills/drug-target-reporting/evals/evals.json \
  skills/drug-target-reporting/templates/drug_report.md.j2 \
  src/agents/drug_target/templates/drug_report.md.j2 \
  tests/agents/drug_target/test_report_writer_prompt.py \
  tests/agents/drug_target/test_report_writer_skill_contract.py \
  tests/test_drug_target.py \
  tests/agents/drug_target/test_orchestrator_middleware_chain.py \
  tests/agents/drug_target/test_subagent_prompt_sanitization.py \
  tests/agents/drug_target/test_subagent_prompts_cleanup.py \
  tests/agents/drug_target/test_hypothesis_writer_skill_activation_prompt.py \
  tests/agents/drug_target/test_resume_instruction.py \
  tests/agents/drug_target/test_config_ollama_openai.py \
  tests/agents/drug_target/test_hypothesis_celltype_focus.py \
  tests/benchmarks/test_hypothesis_generation_consistency.py \
  tests/test_write_file_guard.py \
  tests/scripts/test_run_report_writer_only.py \
  tests/scripts/test_run_drug_target_e2e.py \
  tests/scripts/test_run_drug_target_agent_bc.py
git commit -m "$(cat <<'EOF'
Move production report authorship behind the Drug Target guardrail

Constraint: The outer super-graph and traced benchmark remain runnable only through explicit legacy_hypothesis mode even though production no longer dispatches hypothesis_writer.
Rejected: Add a third report subagent | retains duplicate hypothesis ownership and lengthens the production chain.
Confidence: high
Scope-risk: moderate
Directive: Keep report_writer as the sole writer of target_assessment.json and drug.md; middleware owns all post-write work.
Tested: OPENAI_API_KEY=test uv run pytest -q tests/test_drug_target.py tests/agents/drug_target/test_report_writer_prompt.py tests/agents/drug_target/test_report_writer_skill_contract.py tests/agents/drug_target/test_orchestrator_middleware_chain.py tests/agents/drug_target/test_hypothesis_celltype_focus.py tests/agents/drug_target/test_subagent_prompt_sanitization.py tests/agents/drug_target/test_subagent_prompts_cleanup.py tests/agents/drug_target/test_resume_instruction.py tests/agents/drug_target/test_config_ollama_openai.py tests/agents/drug_target/test_super_graph_hypothesis_retry.py tests/benchmarks/test_hypothesis_generation_consistency.py tests/test_write_file_guard.py tests/scripts/test_run_report_writer_only.py tests/scripts/test_run_drug_target_e2e.py tests/scripts/test_run_drug_target_agent_bc.py tests/test_run_drug_target_traced.py tests/scripts/test_run_drug_target_traced_budget.py tests/agents/drug_target/test_prompts_clinical_compounds_rule.py tests/agents/drug_target/test_prompts_gap_analysis_rule.py tests/agents/drug_target/test_prompts_reflection_guidance.py tests/agents/drug_target/test_drug_profile_coverage.py tests/agents/drug_target/test_hypothesis_writer_prompt_category_contract.py tests/agents/drug_target/test_hypothesis_writer_prompt_save_contract.py tests/agents/drug_target/test_hypothesis_writer_skill_activation_prompt.py
Not-tested: Live evidence-assessor to report-writer handoff.
EOF
)"
```

---

### Task 5: Remove the Outer Super-Graph from Production Graph and Integration Paths

**Files:**
- Modify: `src/agents/drug_target/__init__.py:1-14` (package architecture docstring only)
- Modify: `src/agents/drug_target/graph_builder.py:1-34`
- Modify: `src/agents/drug_target/integration.py:1-125`
- Modify: `tests/test_drug_target.py:5419-5455`
- Modify: `tests/agents/drug_target/test_super_graph_topology.py:1-75`
- Modify: `tests/agents/drug_target/test_integration_envelope.py`
- Modify: `tests/agents/deep_interpreter/test_run_drug_target_node_transparency.py`
- Verify only: `langgraph.json:13`
- Verify only: `tests/test_wrapper_hitl_fixes.py:900-1170`

**Interfaces:**
- Preserve: module-level `drug_target_graph` runnable export.
- Preserve: `run_drug_target_assessment(data_dir: str, disease: str) -> str` and its exact five-key JSON envelope.
- New success gate: final audit is valid, publication passed, and all seven required successful-run files exist/read correctly.
- New execution: each integration call builds `DrugTargetConfig(data_dir=..., disease=..., use_checkpointer=False)`, invokes the returned agent with messages, and cleans its backend in `finally` off the event-loop thread.
- Provider policy: both the module export and per-call integration resolve `LLM_PROVIDER`, defaulting to `openrouter` to preserve the current outer super-graph behavior, and pass the resolved `Provider` into `DrugTargetConfig`.
- Disease policy: per-call integration preserves its required `disease` argument; the environment-bound module export passes optional `DRUG_TARGET_DISEASE` and otherwise leaves `DrugTargetConfig.disease == ""`, causing the blank-safe orchestrator prompt from Task 4 to omit `disease=` and let `load_lr_candidates` use the disease stored in `lr_candidates.json`.

- [ ] **Step 1: Replace production topology tests before changing the export**

Replace only the top production assertions in `test_super_graph_topology.py`:

```python
def test_production_export_is_direct_deep_agent_runnable() -> None:
    from src.agents.drug_target.graph_builder import drug_target_graph

    node_ids = set(drug_target_graph.get_graph().nodes)

    assert "run_deep_agent" not in node_ids
    assert "validate_and_maybe_retry_hypothesis" not in node_ids
    assert "finalize_report" not in node_ids
```

Keep tests that directly import `src.agents.drug_target.super_graph` under a clearly marked legacy-compatibility section; they must not be reinterpreted as production topology.

In the same test module, read `src/agents/drug_target/__init__.py`, `graph_builder.py`, and `integration.py` as text. Assert their production-facing docstrings name `evidence_assessor`, `report_writer`, and `DrugReportGuardrailMiddleware`, and do not describe “3 top-level subagents,” `hypothesis_writer -> summarizer`, or `START -> run_deep_agent -> finalize_report` as the current/default path. Historical/legacy modules may retain those terms only with an explicit legacy label.

- [ ] **Step 2: Rewrite integration tests around per-call construction and audit gating**

Use a fake agent/backend and patch `src.agents.drug_target.agent.create_drug_target_agent`. The fake agent writes the seven required files and returns a normal message result. Add assertions that:

- `DrugTargetConfig.data_dir`, `disease`, and `use_checkpointer=False` match the tool call;
- `DrugTargetConfig.provider` equals `LLM_PROVIDER` when set and defaults to `openrouter` when absent;
- `DrugTargetConfig.workflow_mode == "guarded_report"` for both export and integration construction;
- construction and backend cleanup do not run on `MainThread`;
- all disk artifact reads remain inside `asyncio.to_thread`, preserving the existing event-loop transparency assertion;
- `ainvoke` receives a `messages` payload and top-level `recursion_limit`;
- the success envelope has exactly `EXPECTED_KEYS`;
- invalid/missing final audit produces `success=False` even if `drug.md` exists;
- a passed audit and derived files left from a prior run are cleared before invocation, so a fake agent that writes nothing cannot inherit success;
- `publication.status="failed"` produces `success=False`;
- a missing Part 4 or HTML artifact produces `success=False`;
- backend cleanup runs after both successful invocation and an exception.

The fake final audit should use the Audit Contract near the top of this plan.

Migrate `tests/test_drug_target.py::TestIntegration::test_run_drug_target_assessment_with_mock_agent` in the same step. Replace its `graph_builder.drug_target_graph` patch with `src.agents.drug_target.agent.create_drug_target_agent`; make the fake agent write both audits and all five report/publication artifacts, return a normal messages result, and assert the unchanged five-key success envelope. Keeping this old graph patch would leave a contradictory production test even if the focused integration file passes.

- [ ] **Step 3: Run the changed tests and verify the red state**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/agents/drug_target/test_super_graph_topology.py \
  tests/agents/drug_target/test_integration_envelope.py \
  tests/agents/deep_interpreter/test_run_drug_target_node_transparency.py \
  tests/test_drug_target.py
```

Expected: production topology and per-call construction tests fail while `graph_builder` still exports the super-graph.

- [ ] **Step 4: Export the direct agent runnable**

Replace the super-graph import in `graph_builder.py` with a small factory:

```python
import os
from typing import cast

from langchain_core.runnables import Runnable

from src.agents.drug_target.agent import (
    DrugTargetConfig,
    Provider,
    create_drug_target_agent,
)


def create_drug_target_graph(
    *,
    provider: Provider = "openrouter",
    data_dir: str = "",
    disease: str = "",
    use_checkpointer: bool = False,
) -> Runnable:
    resolved_data_dir = data_dir or os.getenv(
        "DRUG_TARGET_DATA_DIR",
        os.getenv("DEEP_INTERPRETER_DATA_DIR", "/tmp/deep_interpreter_workspace"),
    )
    agent, _backend = create_drug_target_agent(
        DrugTargetConfig(
            provider=provider,
            data_dir=resolved_data_dir,
            disease=disease,
            use_checkpointer=use_checkpointer,
            workflow_mode="guarded_report",
        )
    )
    return agent


drug_target_graph = create_drug_target_graph(
    provider=cast(Provider, os.getenv("LLM_PROVIDER", "openrouter")),
    disease=os.getenv("DRUG_TARGET_DISEASE", ""),
    use_checkpointer=False,
)
```

Keep `load_dotenv()` before environment reads and keep the symbol name unchanged. Reuse the `Provider` alias introduced in Task 4; do not leave an undefined annotation or duplicate the literal union. The module export is environment-bound: `DRUG_TARGET_DATA_DIR`/`DEEP_INTERPRETER_DATA_DIR` select its workspace and optional `DRUG_TARGET_DISEASE` overrides file disease. When the disease env var is absent, the blank-safe orchestrator call from Task 4 omits the tool keyword and `load_lr_candidates` reads disease from the selected file. Do not import `super_graph` or `finalize_report` from this module. Rewrite the `graph_builder.py` module docstring to describe the direct guarded runnable and move any recursion-limit guidance that still applies to that runnable without mentioning the old node topology.

In the graph test, patch `agent.create_llm` and `agent.create_deep_agent` with local fakes, then wrap `agent.create_drug_target_agent` so it records the config while calling the real factory; this keeps module reload offline and also captures the rendered `system_prompt`. Monkeypatch `LLM_PROVIDER="google"` and `DRUG_TARGET_DISEASE="IPF"`, reload `graph_builder`, and assert `DrugTargetConfig.provider == "google"`, `.disease == "IPF"`, and `.workflow_mode == "guarded_report"`. Repeat with both variables absent and assert provider `"openrouter"`, disease `""`, and a captured orchestrator prompt whose `load_lr_candidates` call has no `disease=` keyword. Restore the module/environment and imported factory after each case so `langgraph.json` imports are not order-dependent.

- [ ] **Step 5: Invoke a dynamic direct agent in the integration tool**

Retain prerequisite and environment restoration logic. Replace graph state construction with:

```python
await asyncio.to_thread(
    clear_derived_report_artifacts,
    resolved_dir,
    include_audits=True,
    include_sources=True,
)
provider = cast(Provider, os.getenv("LLM_PROVIDER", "openrouter"))
config = DrugTargetConfig(
    provider=provider,
    data_dir=resolved_dir,
    disease=disease,
    use_checkpointer=False,
    workflow_mode="guarded_report",
)
agent, backend = await asyncio.to_thread(create_drug_target_agent, config)
try:
    await agent.ainvoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"Run the drug-target assessment for {disease}. "
                        f"Data directory: {resolved_dir}."
                    ),
                }
            ]
        },
        config={
            "recursion_limit": 10000,
            "configurable": {"thread_id": str(uuid.uuid4())},
        },
    )
finally:
    cleanup = getattr(backend, "cleanup", None)
    if callable(cleanup):
        await asyncio.to_thread(cleanup)
```

Import `DrugTargetConfig`, `Provider`, and `create_drug_target_agent` lazily inside the tool body to preserve the current circular-import boundary; import `cast` from `typing` at module scope. The integration default must remain `openrouter`, matching the super-graph path it replaces, rather than falling through to `DrugTargetConfig`'s historical `ollama` default.

Import `clear_derived_report_artifacts` lazily in the same block. Clearing source, audit, and derived outputs at integration-run start is intentionally redundant with the report-writer `before_agent` hook: it prevents a premature orchestrator return before `report_writer` from reusing prior `drug.md`, `target_assessment.json`, or a passed audit.

After invocation, read `drug_report_validation_final.json`. Return failure unless:

```python
final_audit.get("valid") is True
and final_audit.get("publication", {}).get("status") == "passed"
```

Then require and read all successful-run artifacts listed in Global Constraints. Set `evidence_truncated` to `False`; no outer state exists to supply it. Convert any exception, malformed JSON, failed audit, or missing artifact into the unchanged failure envelope.

Perform `Path.exists`/`Path.read_text` work through `asyncio.to_thread` as in the current integration implementation; JSON decoding may occur after the text returns to the event loop.

Update the package and integration docstrings in the same step. `src/agents/drug_target/__init__.py` must describe `run_drug_target_assessment -> evidence_assessor -> report_writer -> DrugReportGuardrailMiddleware`; `integration.py` must describe per-call guarded-agent construction and the final-audit/seven-artifact success gate. These are documentation-only edits and must not add exports or change the five-key envelope.

- [ ] **Step 6: Update the wrapper-facing artifact test without changing wrapper code**

Refactor `test_run_drug_target_node_transparency.py` to use the same fake direct agent and write both audits plus Part 4/HTML outputs. Remove fake `DrugTargetState` helpers and super-graph patching. Add a failure case where `drug.md` and `target_assessment.json` exist but final publication is failed; the envelope must still fail.

Run the existing wrapper tests that prove:

- cache hit requires `drug.md` plus `part4_therapeutic_synthesis.md`;
- selected pairs prefer `part4_candidate_selection.json`;
- fallback behavior remains unchanged.

- [ ] **Step 7: Run graph, integration, and wrapper regressions**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/agents/drug_target/test_super_graph_topology.py \
  tests/agents/drug_target/test_integration_envelope.py \
  tests/agents/deep_interpreter/test_run_drug_target_node_transparency.py \
  tests/test_drug_target.py \
  tests/test_wrapper_hitl_fixes.py
```

Expected: all tests pass. Direct imports of legacy `super_graph` still work, but neither production export nor integration imports it.

- [ ] **Step 8: Commit the production runtime cutover**

```bash
git add \
  src/agents/drug_target/__init__.py \
  src/agents/drug_target/graph_builder.py \
  src/agents/drug_target/integration.py \
  tests/test_drug_target.py \
  tests/agents/drug_target/test_super_graph_topology.py \
  tests/agents/drug_target/test_integration_envelope.py \
  tests/agents/deep_interpreter/test_run_drug_target_node_transparency.py
git commit -m "$(cat <<'EOF'
Run Drug Target directly so guarded reports define integration success

Constraint: LangGraph export naming and the Step 9.5 five-key envelope cannot change.
Rejected: Reuse the module-level graph for integration | binds requests to one environment-derived data directory and backend lifecycle.
Confidence: high
Scope-risk: moderate
Directive: Construct integration agents per data directory and require a passed final audit plus complete publication artifacts.
Tested: OPENAI_API_KEY=test uv run pytest -q tests/agents/drug_target/test_super_graph_topology.py tests/agents/drug_target/test_integration_envelope.py tests/agents/deep_interpreter/test_run_drug_target_node_transparency.py tests/test_drug_target.py tests/test_wrapper_hitl_fixes.py
Not-tested: LangGraph server deployment process shutdown with the module-level FilesystemBackend.
EOF
)"
```

---

### Task 6: Prove the Production/Legacy Boundary and Run Final Verification

**Files:**
- Verify: all files changed in Tasks 1-5
- Verify: `src/agents/drug_target/super_graph.py`, `src/agents/drug_target/finalize_report.py`, and `scripts/run_drug_target_traced.py` contain only the planned explicit legacy-mode, evidence-summary opt-in, and legacy/deprecation wording edits
- Verify only: `src/agents/drug_target/hypothesis_retry.py`
- Verify: `tests/agents/drug_target/test_finalize_report_mvp3_integration.py` retains the explicit legacy evidence-summary opt-in regression from Task 1

- [ ] **Step 1: Prove production routing contains no outer finalizer**

Run:

```bash
rg -n \
  'build_drug_target_super_graph|finalize_report|report_finalization_error' \
  src/agents/drug_target/graph_builder.py \
  src/agents/drug_target/integration.py
```

Expected: no matches and exit status `1`.

Run:

```bash
rg -n \
  '3 top-level subagents|hypothesis_writer -> summarizer|START.*run_deep_agent.*finalize_report|DrugTargetAgent super-graph' \
  src/agents/drug_target/__init__.py \
  src/agents/drug_target/graph_builder.py \
  src/agents/drug_target/integration.py
```

Expected: no matches and exit status `1`; all production-facing package/export/integration docstrings describe the direct guarded path.

Run:

```bash
rg -n \
  'hypothesis_writer|HypothesisRetryLoopMiddleware' \
  src/agents/drug_target/agent.py \
  src/agents/drug_target/subagents/configs.py
```

Expected: matches are limited to clearly marked legacy configuration/prompt compatibility declarations; no orchestrator step, `WORKFLOW_ORDER`, `_TOP_LEVEL_SUBAGENTS`, returned middleware, or production model/skill map uses them.

Run:

```bash
rg -n 'DrugReportRunCleanupMiddleware|DrugTargetManagedFilesystemGuardMiddleware|DrugTargetTaskAllowlistMiddleware|production_(assessment|hypothesis)_evidence_tool|production_(assessment_save_evidence|evidence_summary|save_target_assessment|save_drug_md)_tool' \
  src/agents/drug_target/agent.py \
  src/agents/drug_target/subagents/configs.py \
  src/agents/drug_target/production_report_tools.py \
  tests/agents/drug_target/test_orchestrator_middleware_chain.py
```

Expected: production run cleanup, top-level task allow-listing, configured-directory filesystem guards, all bound load/save substitutions, and guarded/legacy regression assertions are present; the explicit legacy branch contains none of these production wrappers/guards.

Run:

```bash
rg -n 'workflow_mode="legacy_hypothesis"' \
  src/agents/drug_target/super_graph.py \
  scripts/run_drug_target_traced.py
```

Expected: both retained legacy entrypoints opt in explicitly. The default `DrugTargetConfig`, `graph_builder.py`, and `integration.py` contain no `legacy_hypothesis` selection.

- [ ] **Step 2: Prove forbidden production files are never persisted or consumed**

Run:

```bash
rg -n \
  'hypothesis_report[^ ]*\.json|report_data\.json' \
  src/agents/drug_target/report_guardrails.py \
  src/agents/drug_target/graph_builder.py \
  src/agents/drug_target/integration.py \
  scripts/run_report_writer_only.py \
  scripts/run_drug_target_e2e.py \
  scripts/run_drug_target_agent_bc.py
```

Expected: no matches and exit status `1`.

Run:

```bash
rg -n \
  'write_text\(.*report_data|_write_json\(.*report_data|save_hypothesis_report' \
  src/agents/drug_target/report_guardrails.py
```

Expected: no matches and exit status `1`.

- [ ] **Step 3: Run the focused Drug Target and Step 9.5 suite**

Run:

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/agents/drug_target \
  tests/agents/deep_interpreter/test_run_drug_target_node_transparency.py \
  tests/test_drug_target.py \
  tests/test_drug_target_fixes.py \
  tests/benchmarks/test_hypothesis_generation_consistency.py \
  tests/test_write_file_guard.py \
  tests/scripts/test_run_report_writer_only.py \
  tests/scripts/test_run_drug_target_e2e.py \
  tests/scripts/test_run_drug_target_agent_bc.py \
  tests/test_run_drug_target_traced.py \
  tests/scripts/test_run_drug_target_traced_budget.py \
  tests/test_wrapper_hitl_fixes.py
```

Expected: all selected tests pass with no live model calls.

Run the retained runtime compatibility smoke checks explicitly:

```bash
OPENAI_API_KEY=test uv run pytest -q \
  tests/agents/drug_target/test_super_graph_hypothesis_retry.py \
  tests/agents/drug_target/test_finalize_report_mvp3_integration.py
PYTHONDONTWRITEBYTECODE=1 uv run python scripts/run_drug_target_traced.py --help >/dev/null
PYTHONDONTWRITEBYTECODE=1 uv run python scripts/run_report_writer_only.py --help >/dev/null
```

Expected: direct outer-super-graph/finalizer tests execute successfully, the traced legacy benchmark CLI still parses/loads, and the guarded writer-only CLI parses without invoking a model. This is the runnability boundary; production does not import legacy paths.

- [ ] **Step 4: Run static checks on changed Python files**

Run:

```bash
git diff --name-only --diff-filter=ACM origin/main...HEAD \
  | rg '\.py$' \
  | xargs uv run ruff check
```

Expected: `All checks passed!`.

Run:

```bash
git diff --name-only --diff-filter=ACM origin/main...HEAD \
  | rg '\.py$' \
  | xargs uv run pyright
```

Expected: zero errors across every changed Python source and test file. If repository-wide pre-existing diagnostics appear through imports, record them separately and still resolve every diagnostic introduced by this branch.

- [ ] **Step 5: Run diff hygiene and inspect scope**

Run:

```bash
git diff --check origin/main...HEAD
git status --short
git diff --stat origin/main...HEAD
```

Expected: no whitespace errors; only planned source, tests, production scripts, current architecture docs, skills/templates, and this plan are changed. `super_graph.py`, `finalize_report.py`, and `scripts/run_drug_target_traced.py` contain only the planned explicit legacy-mode, legacy-summary opt-in, and deprecation/wording edits; other legacy hypothesis modules remain otherwise unmodified unless a test exposed a narrowly required compatibility fix.

- [ ] **Step 6: Request final code review before branch integration**

Use `superpowers:requesting-code-review` with this plan, the full branch diff, and the verification outputs. The reviewer must specifically confirm:

- one production hypothesis source (`drug.md`);
- one validation/repair owner (`DrugReportGuardrailMiddleware`);
- one production run-start stale-output owner (`DrugReportRunCleanupMiddleware`), excluded from legacy mode;
- managed filesystem built-ins blocked on the top-level agent and both production subagents, including Docker `execute`, with the repair agent using only bound dedicated tools;
- automatic `general-purpose` dispatch rejected before handler invocation, leaving only the two domain subagents callable;
- production evidence/report wrappers and generic tool middleware bind the configured run directory, force safe scopes, reject unsafe save names, and cannot be caller-switched back to legacy inputs;
- guarded custom tools are rejected while explicit legacy custom-tool behavior remains intact;
- three-pass cap and unchanged-output early exit;
- warnings non-blocking and input failures non-repairable;
- no derived outputs after failure;
- exact integration envelope;
- no production super-graph/finalizer dependency;
- all three migrated runnable scripts use guarded construction, audit/artifact success gates, backend cleanup, and environment restoration wherever they mutate process state;
- the explicit legacy super-graph/finalizer/traced benchmark remains runnable without entering production routing.

Resolve every correctness finding, rerun the smallest affected test set, then rerun Steps 3-5 before claiming completion.

- [ ] **Step 7: Commit review fixes, if any, and re-prove the final branch**

If review produced tracked-file fixes, inspect `git status --short`, explicitly `git add` any reviewer-requested new test file, then stage tracked fixes and create one Lore commit:

```bash
git add -u
git commit -m "$(cat <<'EOF'
Close review-found gaps before integrating the guarded Drug Target path

Constraint: Final review findings must be committed before branch-range static and diff checks can prove them.
Rejected: Leave review fixes in the working tree | origin/main...HEAD verification would omit them and branch integration would be incomplete.
Confidence: high
Scope-risk: narrow
Directive: Preserve the single-source, forced-safe tool, managed-filesystem, audit, and explicit-legacy boundaries established by this migration.
Tested: Reviewer-requested targeted regressions plus Task 6 Steps 3-5.
Not-tested: Live provider/API execution.
EOF
)"
```

Skip this commit only when review returns no actionable finding and `git status --short` is already empty. After committing any fixes, rerun Steps 3, 4, and 5 against the new `HEAD`. Stop only when all tests/static checks pass, `git diff --check origin/main...HEAD` is clean, and `git status --short` has no output.

## Stop Condition

The migration is complete only when the direct production graph runs `evidence_assessor -> report_writer`, automatic `general-purpose` dispatch and guarded custom tools are rejected, every guarded production/repair layer blocks raw content/shell filesystem built-ins and binds domain calls to the configured run directory, forced-safe tools prevent all `hypothesis_report*.json`/`report_data.json` reads or writes, each invocation requires fresh `drug.md` and `target_assessment.json`, the report-writer middleware repairs Section 4/content defects before producing a passed final audit and all derived artifacts from final Markdown, malformed inputs and every invalid/incomplete publication return the unchanged failure envelope, all three migrated runners use the canonical guarded factory/audit gate, the explicit legacy benchmark smoke checks and all focused/static checks above pass, every review fix is committed, and the final worktree is clean.

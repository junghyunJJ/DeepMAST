from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from docs.benchmarks.harness_x_model.common import (
    BENCHMARK_APPENDIX_B_PINNED,
    BENCHMARK_APPENDIX_BPRIME_C,
    BENCHMARK_SKILL_KWARG_HINT,
    HARDCODED_SKILL_BLOCK,
    SearchTrialResult,
    _make_benchmark_search_tool,
    _searcher_tools,
    _SEARCHER_PROMPT_KWARG_STRIPS,
    build_trial_schedule,
    check_cases_coherence,
    check_mode_coherence,
    compose_searcher_prompt,
    compute_cases_sha256,
    load_cases,
    load_completed_trial_indices,
    normalize_case,
    select_pilot_cases,
)


@pytest.fixture
def sample_case() -> dict:
    return {
        "case_id": "cci_full_01_EGF_RACK1",
        "benchmark_type": "cci_interpretation_v2",
        "lr_pair": "EGF-RACK1",
        "category": "low_morans_known",
        "input_bundle": {
            "ligand": "EGF",
            "receptor": "RACK1",
            "interaction": "EGF^RACK1",
            "pathway_associations": ["Hypoxia"],
            "ligand_cell_types": ["DCIS 2", "Invasive Tumor"],
            "receptor_cell_types": ["Endothelial", "Invasive Tumor"],
            "tissue_context": "Breast cancer Visium spatial transcriptomics",
        },
    }


def test_normalize_case_extracts_search_fields(sample_case: dict) -> None:
    normalized = normalize_case(sample_case)

    assert normalized["case_id"] == "cci_full_01_EGF_RACK1"
    assert normalized["genes"] == ["EGF", "RACK1"]
    assert normalized["pathways"] == ["Hypoxia"]
    assert normalized["celltypes"] == ["DCIS 2", "Endothelial", "Invasive Tumor"]
    assert normalized["disease"] == "breast cancer"


def test_normalize_case_prefers_enriched_genes_when_present(sample_case: dict) -> None:
    """Rev 7: when a case carries `enriched_genes` (STRING+KEGG), normalize_case
    must use that list verbatim (order + dedup preserved) instead of falling
    back to the 2-gene ligand+receptor split. Legacy cases without the field
    continue to use the fallback path (covered by the preceding test)."""
    enriched_case = {
        **sample_case,
        "enriched_genes": [
            "EGF", "RACK1", "EGFR", "ERBB2", "ERBB3",
            "HIF1A", "VHL", "EPAS1", "VEGFA", "KDR",
            "FLT1", "GRB2", "SOS1", "SHC1", "PIK3CA",
        ],
    }

    normalized = normalize_case(enriched_case)

    assert normalized["genes"] == enriched_case["enriched_genes"]
    assert len(normalized["genes"]) == 15
    # Fallback path must still resolve ligand/receptor correctly for downstream
    # prompt rendering even when enriched_genes is in control.
    assert normalized["lr_pair"] == "EGF-RACK1"


def test_build_trial_schedule_is_deterministic_and_case_grouped(sample_case: dict) -> None:
    cases = [
        sample_case,
        {
            **sample_case,
            "case_id": "cci_full_02_ANOS1_FGFR1",
            "category": "high_morans_unknown",
            "input_bundle": {
                **sample_case["input_bundle"],
                "ligand": "ANOS1",
                "receptor": "FGFR1",
                "interaction": "ANOS1^FGFR1",
            },
        },
    ]

    first = build_trial_schedule(cases=cases, repeats=2, seed=42)
    second = build_trial_schedule(cases=cases, repeats=2, seed=42)

    assert first == second
    assert len(first) == 16

    first_case_block = [row for row in first if row["repeat"] == 1][:4]
    assert {row["condition"] for row in first_case_block} == {
        "strong_off",
        "strong_on",
        "weak_off",
        "weak_on",
    }
    assert len({row["case_id"] for row in first_case_block}) == 1


def test_compose_searcher_prompt_toggles_skill_visibility() -> None:
    prompt_on = compose_searcher_prompt(skill_on=True)
    prompt_off = compose_searcher_prompt(skill_on=False)

    assert "biomedical-literature-search" in prompt_on
    assert "biomedical-literature-search" not in prompt_off
    assert "Use the provided benchmark case context directly" in prompt_on
    assert "Use the provided benchmark case context directly" in prompt_off


def test_compose_searcher_prompt_removes_reflection_loop_language() -> None:
    prompt = compose_searcher_prompt(skill_on=True)

    assert "think_tool" not in prompt
    assert "Reflect (Quality Loop)" not in prompt
    assert "recommended_actions" in prompt


def test_load_completed_trial_indices_reads_trial_files(tmp_path: Path) -> None:
    first = tmp_path / "trial_0001.jsonl"
    first.write_text(json.dumps({"trial_index": 1}) + "\n", encoding="utf-8")
    second = tmp_path / "trial_0007.jsonl"
    second.write_text(json.dumps({"trial_index": 7}) + "\n", encoding="utf-8")

    completed = load_completed_trial_indices(tmp_path)

    assert completed == {1, 7}


def test_select_pilot_cases_keeps_two_per_category(sample_case: dict) -> None:
    cases = []
    for category in ("low_morans_known", "low_morans_unknown"):
        for idx in range(3):
            case = {
                **sample_case,
                "case_id": f"{category}_{idx}",
                "category": category,
            }
            cases.append(case)

    pilot = select_pilot_cases(cases, per_category=2)

    assert len(pilot) == 4
    counts: dict[str, int] = {}
    for case in pilot:
        counts[case["category"]] = counts.get(case["category"], 0) + 1
    assert counts == {"low_morans_known": 2, "low_morans_unknown": 2}


# ---------------------------------------------------------------------------
# REV5 Tier 1 regression guards
# ---------------------------------------------------------------------------


def test_compose_searcher_prompt_strips_mandatory_block() -> None:
    """The HARDCODED_SKILL_BLOCK must be removed from both arms' composed prompt.

    If the string-replace silently no-ops (whitespace drift in
    `prompts.py:182-194`), the original MANDATORY block remains in both arms
    alongside the freshly rendered harness prompt, corrupting the measurement.
    """
    for skill_on in (True, False):
        prompt = compose_searcher_prompt(skill_on=skill_on)
        assert "## MANDATORY: Skill Evaluation Protocol" not in prompt, (
            f"HARDCODED_SKILL_BLOCK not stripped (skill_on={skill_on})"
        )


def test_hardcoded_skill_block_matches_searcher_prompt() -> None:
    """HARDCODED_SKILL_BLOCK must remain an exact substring of SEARCHER_PROMPT.

    If this test fails, someone changed `prompts.py:182-194` and
    `compose_searcher_prompt` now silently preserves the block, breaking the
    benchmark contract.
    """
    from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS

    assert HARDCODED_SKILL_BLOCK in SUBAGENT_PROMPTS["searcher"], (
        "HARDCODED_SKILL_BLOCK no longer matches prompts.py; the "
        "compose_searcher_prompt replace will silently no-op."
    )


def test_search_trial_result_has_tier1_fields() -> None:
    """Tier 1 dual-endpoint + BioMCP telemetry fields must exist on the dataclass."""
    required = {
        "genes_coverage_pct_tagoff",
        "pathways_coverage_pct_tagoff",
        "coverage_pass_tagoff",
        "biomcp_latency_ms",
        "biomcp_error",
        "biomcp_paper_count_raw",
    }
    fields = set(SearchTrialResult.__dataclass_fields__.keys())
    missing = required - fields
    assert not missing, f"SearchTrialResult missing Tier 1 fields: {sorted(missing)}"


def test_build_trial_schedule_minimizes_model_swaps() -> None:
    """Option β (T6) must bound total model swaps across the full 360-trial run.

    Prior implementation shuffled all 4 conditions within each case, producing
    ~226 swaps over 360 trials. T6 groups conditions by model_strength and
    only randomizes skill_on order inside each block, bounding **intra-case**
    swaps to exactly 1 per case (90 across 30×3 trials). Inter-case
    transitions are then 50/50 random, adding ~45 more, so the realistic
    expected total is ~135. Threshold 150 catches regression back to the
    old interleaved behavior (which produced 226) while accepting pure
    per-case randomization. A Latin-square alternation is a possible
    Tier 2 optimization if the ~65 min swap overhead matters.
    """
    cases_path = (
        PROJECT_ROOT
        / "docs/benchmarks/cci_skill_ablation/cases/cci_full_cases.json"
    )
    cases = load_cases(cases_path)
    schedule = build_trial_schedule(cases=cases, repeats=3, seed=42)
    assert len(schedule) == 360
    swaps = sum(
        1
        for i in range(1, len(schedule))
        if schedule[i]["model"] != schedule[i - 1]["model"]
    )
    assert swaps < 150, (
        f"Option β regression: {swaps} model swaps in 360 trials "
        "(expected ~135; pre-fix was ~226)"
    )


def test_run_full_rejects_non_stratified_max_cases(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """run_full.py must raise SystemExit when --max-cases is not 30 and --per-category is absent."""
    from docs.benchmarks.harness_x_model import run_full

    cases_path = (
        PROJECT_ROOT
        / "docs/benchmarks/cci_skill_ablation/cases/cci_full_cases.json"
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_full.py",
            "--cases-file",
            str(cases_path),
            "--results-dir",
            str(tmp_path / "results"),
            "--workspace-root",
            str(tmp_path / "workspaces"),
            "--max-cases",
            "12",
        ],
    )
    with pytest.raises(SystemExit):
        run_full.main()


def test_load_completed_trial_indices_excludes_error_rows(tmp_path: Path) -> None:
    """Rows whose latest entry carries a non-empty error field must not be treated as completed."""
    ok = tmp_path / "trial_0001.jsonl"
    ok.write_text(json.dumps({"trial_index": 1}) + "\n", encoding="utf-8")

    failed = tmp_path / "trial_0002.jsonl"
    failed.write_text(
        json.dumps({"trial_index": 2, "error": "papers_not_written"}) + "\n",
        encoding="utf-8",
    )

    retry_after_error = tmp_path / "trial_0003.jsonl"
    retry_after_error.write_text(
        json.dumps({"trial_index": 3, "error": "transient"})
        + "\n"
        + json.dumps({"trial_index": 3})
        + "\n",
        encoding="utf-8",
    )

    completed = load_completed_trial_indices(tmp_path)
    assert completed == {1, 3}


# ---------------------------------------------------------------------------
# Rev 4 / P0.4 — Mode-parameterized + schema-parity regression tests
# ---------------------------------------------------------------------------


def test_benchmark_appendix_bprime_c_does_not_pin_kwargs() -> None:
    """B'/C appendix must NOT pin the two advanced kwargs."""
    assert "enable_lr_pair_queries=True" not in BENCHMARK_APPENDIX_BPRIME_C
    assert "coverage_weighted_sort=True" not in BENCHMARK_APPENDIX_BPRIME_C


def test_mode_b_appendix_has_kwarg_pin() -> None:
    """Mode B appendix MUST pin both kwargs (null-control experiment)."""
    assert "enable_lr_pair_queries=True" in BENCHMARK_APPENDIX_B_PINNED
    assert "coverage_weighted_sort=True" in BENCHMARK_APPENDIX_B_PINNED


def test_compose_searcher_prompt_on_arm_has_kwarg_hint_mode_c() -> None:
    prompt = compose_searcher_prompt(skill_on=True, benchmark_mode="C")
    assert "Advanced Kwargs" in prompt
    assert "enable_lr_pair_queries=True" in prompt


def test_compose_searcher_prompt_off_arm_hides_kwarg_hint_mode_c() -> None:
    prompt = compose_searcher_prompt(skill_on=False, benchmark_mode="C")
    assert "Advanced Kwargs" not in prompt
    assert "enable_lr_pair_queries=True" not in prompt


def test_off_arm_has_no_behavioral_fan_out_hint_mode_bprime() -> None:
    """OFF-arm B'/C prompt must not leak the 'deterministic singleton' behavioral hint."""
    prompt = compose_searcher_prompt(skill_on=False, benchmark_mode="B_prime")
    assert "deterministic singleton gene queries" not in prompt


def test_mode_b_prime_appendix_no_kwarg_pin_in_composed_prompt() -> None:
    """Mode B_prime composed prompt must NOT contain kwarg pin in the appendix section
    (the skill hint section may on ON arm only)."""
    on_prompt = compose_searcher_prompt(skill_on=True, benchmark_mode="B_prime")
    off_prompt = compose_searcher_prompt(skill_on=False, benchmark_mode="B_prime")
    # OFF arm: kwargs fully absent
    assert "enable_lr_pair_queries=True" not in off_prompt
    assert "Advanced Kwargs" not in off_prompt
    # ON arm: kwargs appear ONLY in the BENCHMARK_SKILL_KWARG_HINT section
    assert "Advanced Kwargs" in on_prompt
    # The appendix text (before Advanced Kwargs block) must not itself pin kwargs
    idx = on_prompt.find("Advanced Kwargs")
    pre_hint = on_prompt[:idx]
    assert "enable_lr_pair_queries=True" not in pre_hint, (
        "Mode B_prime appendix must not pin kwargs; only the skill hint may mention them."
    )


def test_mode_c_off_arm_tool_hides_advanced_kwargs() -> None:
    """Reframe C critical: schema-restricted tool must omit the two advanced kwargs."""
    tool = _make_benchmark_search_tool(skill_on=False)
    schema = tool.args_schema.model_json_schema()
    assert "enable_lr_pair_queries" not in schema["properties"]
    assert "coverage_weighted_sort" not in schema["properties"]


def test_mode_c_on_arm_tool_exposes_advanced_kwargs() -> None:
    """Mode C ON arm returns the unrestricted tool with full schema."""
    tool = _make_benchmark_search_tool(skill_on=True)
    schema = tool.args_schema.model_json_schema()
    assert "enable_lr_pair_queries" in schema["properties"]
    assert "coverage_weighted_sort" in schema["properties"]


def test_mode_b_searcher_tools_no_schema_isolation() -> None:
    """Mode B must NOT apply schema isolation on either arm."""
    for skill_on in (True, False):
        tools = _searcher_tools(skill_on=skill_on, benchmark_mode="B")
        search_tool = next(t for t in tools if getattr(t, 'name', '') == 'search_literature_dynamic')
        schema = search_tool.args_schema.model_json_schema()
        assert "enable_lr_pair_queries" in schema["properties"], (
            f"Mode B skill_on={skill_on} must have unrestricted tool schema"
        )


def test_mode_c_searcher_tools_has_schema_isolation() -> None:
    """Mode C OFF arm uses restricted tool; ON arm uses full tool."""
    off_tools = _searcher_tools(skill_on=False, benchmark_mode="C")
    off_search = next(t for t in off_tools if getattr(t, 'name', '') == 'search_literature_dynamic')
    off_schema = off_search.args_schema.model_json_schema()
    assert "enable_lr_pair_queries" not in off_schema["properties"]

    on_tools = _searcher_tools(skill_on=True, benchmark_mode="C")
    on_search = next(t for t in on_tools if getattr(t, 'name', '') == 'search_literature_dynamic')
    on_schema = on_search.args_schema.model_json_schema()
    assert "enable_lr_pair_queries" in on_schema["properties"]


def test_mode_default_preserves_backward_compat() -> None:
    """Default mode='C' must match explicit benchmark_mode='C' output."""
    default_on = compose_searcher_prompt(skill_on=True)
    explicit_c_on = compose_searcher_prompt(skill_on=True, benchmark_mode="C")
    assert default_on == explicit_c_on

    default_off = compose_searcher_prompt(skill_on=False)
    explicit_c_off = compose_searcher_prompt(skill_on=False, benchmark_mode="C")
    assert default_off == explicit_c_off


def test_compose_searcher_prompt_rejects_unknown_mode() -> None:
    """Unknown benchmark_mode values must fail fast."""
    import pytest as _pytest
    with _pytest.raises(ValueError, match="benchmark_mode"):
        compose_searcher_prompt(skill_on=True, benchmark_mode="D")


def test_restricted_schema_parity() -> None:
    """Architect-requested: catches additive kwarg drift in production tool.

    The restricted schema should differ from the full schema by EXACTLY the
    two intentionally-hidden kwargs. Any new param added to
    `search_literature_dynamic` must trigger a deliberate decision about
    whether to expose it in the restricted schema.
    """
    from src.agents.deep_interpreter.tools.literature import search_literature_dynamic
    full = set(search_literature_dynamic.args_schema.model_json_schema()["properties"].keys())
    restricted_tool = _make_benchmark_search_tool(skill_on=False)
    restricted = set(restricted_tool.args_schema.model_json_schema()["properties"].keys())
    diff = full - restricted
    assert diff == {"enable_lr_pair_queries", "coverage_weighted_sort"}, (
        f"Schema drift detected: full−restricted = {diff}; "
        "expected exactly {'enable_lr_pair_queries', 'coverage_weighted_sort'}. "
        "If production added a new advanced kwarg, decide whether to expose it "
        "in RestrictedSearchInput or add it to the intentional-hidden set."
    )


def test_search_trial_result_has_rev4_fields() -> None:
    """Rev 4 new fields (celltype primary + mode audit + cases SHA) must exist."""
    required = {
        "benchmark_mode",
        "celltypes_coverage_pct",
        "celltypes_coverage_pct_tagoff",
        "cases_sha256",
    }
    fields = set(SearchTrialResult.__dataclass_fields__.keys())
    missing = required - fields
    assert not missing, f"SearchTrialResult missing Rev 4 fields: {sorted(missing)}"


def test_search_trial_result_has_lr_cooccurrence_fields() -> None:
    required = {"lr_cooccurrence_count", "lr_cooccurrence_rate"}
    fields = set(SearchTrialResult.__dataclass_fields__.keys())
    assert required.issubset(fields)


def test_search_trial_result_has_used_lr_pair_queries_field() -> None:
    required = {"used_lr_pair_queries", "n_deterministic_queries", "n_llm_queries"}
    fields = set(SearchTrialResult.__dataclass_fields__.keys())
    assert required.issubset(fields)


# ---------------------------------------------------------------------------
# P0.5 — CI drift guard for _SEARCHER_PROMPT_KWARG_STRIPS
# ---------------------------------------------------------------------------


def test_searcher_prompt_kwarg_strips_all_present() -> None:
    """Every strip target must be an exact substring of the current production prompt.

    If this fails, production `prompts.py` changed and the benchmark's
    `compose_searcher_prompt` RuntimeError would fire on every call.
    """
    from src.agents.deep_interpreter.subagents.prompts import SUBAGENT_PROMPTS
    searcher_prompt = SUBAGENT_PROMPTS["searcher"]
    missing = []
    for i, section in enumerate(_SEARCHER_PROMPT_KWARG_STRIPS):
        if section not in searcher_prompt:
            snippet = section[:80].replace("\n", "\\n")
            missing.append(f"  #{i}: {snippet}...")
    assert not missing, (
        "Production SEARCHER_PROMPT no longer contains these strip targets:\n"
        + "\n".join(missing)
        + "\nUpdate _SEARCHER_PROMPT_KWARG_STRIPS in common.py to match."
    )


# ---------------------------------------------------------------------------
# P0.8.5 — Resume safety guards (mode + cases-hash coherence)
# ---------------------------------------------------------------------------


def _seed_trial_row(tmp_path: Path, payload: dict) -> None:
    """Helper: write a single-line JSONL trial file with the given payload."""
    payload = {"trial_index": payload.get("trial_index", 1), **payload}
    path = tmp_path / f"trial_{payload['trial_index']:04d}.jsonl"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_mode_coherence_guard_aborts_on_mismatch(tmp_path: Path) -> None:
    import pytest as _pytest
    _seed_trial_row(tmp_path, {"benchmark_mode": "B"})
    with _pytest.raises(SystemExit, match="Mode mismatch"):
        check_mode_coherence(tmp_path, "C")


def test_mode_coherence_guard_passes_on_match(tmp_path: Path) -> None:
    _seed_trial_row(tmp_path, {"benchmark_mode": "B"})
    check_mode_coherence(tmp_path, "B")  # no raise


def test_mode_coherence_guard_passes_on_empty(tmp_path: Path) -> None:
    check_mode_coherence(tmp_path, "C")  # no raise


def test_mode_coherence_guard_warns_on_legacy_rows(tmp_path: Path, caplog) -> None:
    import logging
    _seed_trial_row(tmp_path, {})  # no benchmark_mode field
    with caplog.at_level(logging.WARNING):
        check_mode_coherence(tmp_path, "C")
    assert any("lack benchmark_mode" in rec.message for rec in caplog.records)


def test_cases_coherence_guard_aborts_on_hash_mismatch(tmp_path: Path) -> None:
    import pytest as _pytest
    _seed_trial_row(tmp_path, {"cases_sha256": "abc123def456"})
    with _pytest.raises(SystemExit, match="Cases file modified"):
        check_cases_coherence(tmp_path, "xxx999")


def test_cases_coherence_guard_passes_on_match(tmp_path: Path) -> None:
    _seed_trial_row(tmp_path, {"cases_sha256": "abc123"})
    check_cases_coherence(tmp_path, "abc123")  # no raise


def test_cases_coherence_guard_passes_on_empty(tmp_path: Path) -> None:
    check_cases_coherence(tmp_path, "any_sha")  # no raise


def test_cases_coherence_guard_warns_on_legacy_rows(tmp_path: Path, caplog) -> None:
    import logging
    _seed_trial_row(tmp_path, {})  # no cases_sha256 field
    with caplog.at_level(logging.WARNING):
        check_cases_coherence(tmp_path, "any_sha")
    assert any("lack cases_sha256" in rec.message for rec in caplog.records)


def test_run_trial_rejects_mode_mismatch_with_existing_dir(tmp_path: Path) -> None:
    """Architect finding #1: `run_trial.py` must also guard against mode mismatch.

    Simulated via direct call to check_mode_coherence (same helper used by run_trial).
    """
    import pytest as _pytest
    _seed_trial_row(tmp_path, {"benchmark_mode": "B"})
    with _pytest.raises(SystemExit, match="Mode mismatch"):
        check_mode_coherence(tmp_path, "C")


def test_compute_cases_sha256_is_stable() -> None:
    """SHA-256 must be deterministic for the same file content."""
    path = PROJECT_ROOT / "docs/benchmarks/cci_skill_ablation/cases/cci_full_cases.json"
    sha1 = compute_cases_sha256(path)
    sha2 = compute_cases_sha256(path)
    assert sha1 == sha2
    assert len(sha1) == 64  # SHA-256 hex length


# ---------------------------------------------------------------------------
# P1.1 — Gate A (celltype@90%) + Gate Null (mode B only) regression tests
# ---------------------------------------------------------------------------


def _make_rows(
    *,
    strong_on_celltype: list[float],
    strong_off_celltype: list[float],
    weak_on_celltype: list[float] | None = None,
    weak_off_celltype: list[float] | None = None,
    benchmark_mode: str = "C",
) -> list[dict]:
    """Helper: construct synthetic rows for gate testing.

    Each trial row also gets minimal fields for Gates B/C/variance to
    evaluate without crashing (biomcp_latency_ms, case_id, condition).
    """
    rows = []
    idx = 0
    def _add(cond: str, vals: list[float]) -> None:
        nonlocal idx
        for i, pct in enumerate(vals):
            idx += 1
            rows.append({
                "trial_index": idx,
                "condition": cond,
                "case_id": f"case_{i}",
                "benchmark_mode": benchmark_mode,
                "celltypes_coverage_pct": pct,
                "genes_coverage_pct": 100.0,
                "biomcp_latency_ms": 100.0,
                "biomcp_paper_count_raw": 30,
            })
    _add("strong_on", strong_on_celltype)
    _add("strong_off", strong_off_celltype)
    if weak_on_celltype:
        _add("weak_on", weak_on_celltype)
    if weak_off_celltype:
        _add("weak_off", weak_off_celltype)
    return rows


def test_gate_a_uses_celltype_threshold() -> None:
    """Gate A must saturate on celltype@90% (Rev 4), not gene@95% (pre-Rev4)."""
    from docs.benchmarks.harness_x_model.common import check_pilot_gates

    # Gene coverage 100% everywhere (pre-Rev4 would saturate), but celltype 60% → PASS
    rows = _make_rows(
        strong_on_celltype=[60.0, 62.0, 64.0],
        strong_off_celltype=[38.0, 40.0, 42.0],
    )
    gates = check_pilot_gates(rows)
    assert gates["gate_a"]["passed"] is True, f"Gate A should pass at celltype 60%: {gates['gate_a']}"
    assert gates["gate_a"]["endpoint"] == "celltypes_coverage_pct"
    assert gates["gate_a"]["threshold_pct"] == 90.0


def test_gate_a_fails_when_celltype_saturates() -> None:
    """Gate A FAIL when both strong arms' celltype median >= 90%."""
    from docs.benchmarks.harness_x_model.common import check_pilot_gates

    rows = _make_rows(
        strong_on_celltype=[92.0, 94.0, 96.0],
        strong_off_celltype=[91.0, 93.0, 95.0],
    )
    gates = check_pilot_gates(rows)
    assert gates["gate_a"]["passed"] is False
    assert any("Gate A FAIL" in m for m in gates["messages"])


def test_gate_null_catches_mode_b_non_null() -> None:
    """Gate Null MUST fail when mode B shows Δ >= 3 pp in either strength."""
    from docs.benchmarks.harness_x_model.common import check_pilot_gates

    # Mode B with strong Δ = 10 pp (not null) → Gate Null FAIL
    rows = _make_rows(
        strong_on_celltype=[50.0, 52.0],
        strong_off_celltype=[40.0, 42.0],
        weak_on_celltype=[30.0, 32.0],
        weak_off_celltype=[30.0, 32.0],
        benchmark_mode="B",
    )
    gates = check_pilot_gates(rows, benchmark_mode="B")
    assert gates["gate_null"]["passed"] is False
    assert gates["gate_null"]["max_abs_delta_pp"] >= 3.0
    assert any("Gate Null FAIL" in m for m in gates["messages"])


def test_gate_null_passes_mode_b_null() -> None:
    """Gate Null MUST pass when mode B shows Δ < 3 pp in both strengths."""
    from docs.benchmarks.harness_x_model.common import check_pilot_gates

    # Mode B null-control: nearly identical arms → Gate Null PASS
    rows = _make_rows(
        strong_on_celltype=[60.0, 62.0],
        strong_off_celltype=[60.5, 62.5],
        weak_on_celltype=[40.0, 42.0],
        weak_off_celltype=[40.5, 42.5],
        benchmark_mode="B",
    )
    gates = check_pilot_gates(rows, benchmark_mode="B")
    assert gates["gate_null"]["passed"] is True
    assert gates["gate_null"]["max_abs_delta_pp"] < 3.0


def test_gate_null_skipped_for_mode_c() -> None:
    """Gate Null applies only to mode B; mode C should skip cleanly."""
    from docs.benchmarks.harness_x_model.common import check_pilot_gates

    rows = _make_rows(
        strong_on_celltype=[60.0, 62.0],
        strong_off_celltype=[40.0, 42.0],
        benchmark_mode="C",
    )
    gates = check_pilot_gates(rows, benchmark_mode="C")
    assert gates["gate_null"]["passed"] is True
    assert gates["gate_null"].get("skipped") is True

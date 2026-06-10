"""Unit tests for validate_drug_report_finalization and the validate_drug_md
signature refactor (str vs Path dispatch).

All tests use synthetic fixtures under tests/agents/drug_target/fixtures/.
No test depends on any live workspace (res_ipf_qwen* or similar).
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from src.agents.drug_target.tools import (
    validate_drug_report_finalization,
    validate_drug_md,
)
import src.agents.drug_target.tools.stage_logic as stage_logic
from src.agents.drug_target.tools.report_expansion_schema import (
    canonical_json_hash,
    persist_drug_report_reference_card,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoke(data_dir, *, allow_legacy: bool = True):
    """Invoke the @tool wrapper with data_dir as a string."""
    previous = os.environ.get("DEEPMAST_ALLOW_LEGACY_DRUG_MD")
    if allow_legacy:
        os.environ["DEEPMAST_ALLOW_LEGACY_DRUG_MD"] = "1"
    else:
        os.environ.pop("DEEPMAST_ALLOW_LEGACY_DRUG_MD", None)
    try:
        return json.loads(validate_drug_report_finalization.invoke({"data_dir": str(data_dir)}))
    finally:
        if previous is None:
            os.environ.pop("DEEPMAST_ALLOW_LEGACY_DRUG_MD", None)
        else:
            os.environ["DEEPMAST_ALLOW_LEGACY_DRUG_MD"] = previous


def _copy_fixture(name, tmp_path):
    """Copy a fixture into tmp_path and return the path."""
    src = FIXTURE_ROOT / name
    dst = tmp_path / name
    shutil.copytree(src, dst)
    return dst


def _move_stage1_filter_results_to_evidence(data_dir):
    evidence_dir = data_dir / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    shutil.move(
        str(data_dir / "stage1_filter_results.json"),
        str(evidence_dir / "stage1_filter_results.json"),
    )


def _has_issue(result, code):
    return any(issue["code"] == code for issue in result["issues"])


def _drug_hash(data_dir: Path) -> str:
    import hashlib

    return hashlib.sha256((data_dir / "drug.md").read_bytes()).hexdigest()


def _write_renderer_sidecars(data_dir: Path, *, bad_source_hash: bool = False, bad_drug_hash: bool = False) -> None:
    ref = persist_drug_report_reference_card(
        data_dir,
        {
            "markdown_template": (data_dir / "drug.md").read_text(encoding="utf-8"),
            "expansion_slots": [],
        },
    )
    expansions = {
        "schema_version": "report_expansions.v1",
        "template_id": "drug_report.md.j2",
        "reference_card_hash": canonical_json_hash(ref),
        "slots": [],
    }
    (data_dir / "report_expansions.json").write_text(
        json.dumps(expansions, indent=2),
        encoding="utf-8",
    )
    metadata = {
        "schema_version": "drug_report_render.v1",
        "renderer": "render_drug_md_from_expansions",
        "mode": "renderer",
        "source_hashes": {
            "reference_card": "bad" if bad_source_hash else canonical_json_hash(ref),
            "report_expansions": canonical_json_hash(expansions),
            "hypothesis_report": None,
            "template": "unused-in-this-unit-test",
        },
        "rendered_drug_md_sha256": "bad" if bad_drug_hash else _drug_hash(data_dir),
        "required_slot_count": 0,
        "rendered_slot_count": 0,
        "missing_slots": [],
        "extra_slots": [],
    }
    (data_dir / "drug_report_render.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 1. Negative control
# ---------------------------------------------------------------------------


def test_clean_fixture_passes(tmp_path):
    """The clean fixture must produce valid=True with zero issues."""
    d = _copy_fixture("clean", tmp_path)
    result = _invoke(d)
    assert result["valid"] is True
    assert result["issue_count"] == 0
    assert result["issues"] == []


# ---------------------------------------------------------------------------
# 2. INVALID_DATA_DIR
# ---------------------------------------------------------------------------


def test_invalid_data_dir_nonexistent(tmp_path):
    result = _invoke(tmp_path / "does_not_exist")
    assert _has_issue(result, "INVALID_DATA_DIR")
    assert result["valid"] is False


def test_invalid_data_dir_root():
    result = _invoke("/")
    assert _has_issue(result, "INVALID_DATA_DIR")
    assert result["valid"] is False


def test_invalid_data_dir_repo_root():
    # Walk up from this file until we find the directory that contains .git/
    candidate = Path(__file__).resolve()
    for parent in candidate.parents:
        if (parent / ".git").is_dir():
            repo_root = parent
            break
    else:
        pytest.skip("Could not locate repository root via .git/")
    result = _invoke(repo_root)
    assert _has_issue(result, "INVALID_DATA_DIR")
    assert result["valid"] is False


def test_invalid_data_dir_does_not_consult_env(tmp_path, monkeypatch):
    """Even when DRUG_TARGET_DATA_DIR/DEEP_INTERPRETER_DATA_DIR point to a valid
    clean fixture, invoking on a nonexistent path must still emit INVALID_DATA_DIR.
    The validator must NOT fall back to env vars."""
    clean_copy = _copy_fixture("clean", tmp_path)
    monkeypatch.setenv("DRUG_TARGET_DATA_DIR", str(clean_copy))
    monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", str(clean_copy))
    nonexistent = tmp_path / "clean_via_env"  # does not exist
    result = _invoke(nonexistent)
    assert _has_issue(result, "INVALID_DATA_DIR")
    assert result["valid"] is False


# ---------------------------------------------------------------------------
# 3. MISSING_REQUIRED_ARTIFACT  (parametrized over the 4 required files)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "artifact",
    [
        "drug.md",
        "target_assessment.json",
        "evidence/assessment_results.json",
        "stage1_filter_results.json",
    ],
)
def test_missing_required_artifact(artifact, tmp_path):
    """Deleting any one of the four required artifacts must produce
    MISSING_REQUIRED_ARTIFACT with the missing path mentioned in the issue."""
    d = _copy_fixture("clean", tmp_path)
    (d / artifact).unlink()
    result = _invoke(d, allow_legacy=False)
    assert _has_issue(result, "MISSING_REQUIRED_ARTIFACT"), (
        f"Expected MISSING_REQUIRED_ARTIFACT when {artifact} is deleted; "
        f"got issues: {result['issues']}"
    )
    # The location field of the issue should reference the missing artifact name.
    matching = [i for i in result["issues"] if i["code"] == "MISSING_REQUIRED_ARTIFACT"]
    assert any(artifact.split("/")[-1] in i["location"] for i in matching), (
        f"Location field does not mention '{artifact}'; issues: {matching}"
    )


def test_required_stage1_artifact_can_live_under_evidence(tmp_path):
    """Current pipeline runs persist stage1_filter_results.json under evidence/."""
    d = _copy_fixture("clean", tmp_path)
    _move_stage1_filter_results_to_evidence(d)
    result = _invoke(d)
    assert result["valid"] is True
    assert not _has_issue(result, "MISSING_REQUIRED_ARTIFACT"), (
        f"Expected evidence/stage1_filter_results.json to satisfy requirement; got: {result['issues']}"
    )


# ---------------------------------------------------------------------------
# 4. VALIDATE_DRUG_MD_FAILED
# ---------------------------------------------------------------------------


def test_validate_drug_md_failed(tmp_path):
    """The validate_drug_md_failed fixture has a BRCA1 classification mismatch
    (drug.md claims validated_target; assessment_results.json says exploratory_target).
    The finalization validator must propagate this as VALIDATE_DRUG_MD_FAILED and
    record valid=False inside checks.validate_drug_md.raw."""
    d = _copy_fixture("validate_drug_md_failed", tmp_path)
    result = _invoke(d)
    assert _has_issue(result, "VALIDATE_DRUG_MD_FAILED"), (
        f"Expected VALIDATE_DRUG_MD_FAILED; got issues: {result['issues']}"
    )
    raw = result["checks"]["validate_drug_md"]["raw"]
    assert raw.get("valid") is False


# ---------------------------------------------------------------------------
# 5. MISSING_TARGET_ASSESSMENT / TARGET_ASSESSMENT_INVALID for whitespace file
# ---------------------------------------------------------------------------


def test_missing_target_assessment_whitespace_file(tmp_path):
    """The missing_target_assessment fixture has a whitespace-only
    target_assessment.json (1-byte newline). The file exists on disk, so
    MISSING_REQUIRED_ARTIFACT is NOT emitted. Instead the JSON parse fails and
    validate_target_assessment_file returns valid=False, causing the finalization
    validator to emit TARGET_ASSESSMENT_INVALID.

    Implementation note: the validator reaches the target_assessment branch
    only after required-artifact check passes. Because target_assessment.json
    exists (albeit unparseable), it does not trigger MISSING_REQUIRED_ARTIFACT.
    """
    d = _copy_fixture("missing_target_assessment", tmp_path)
    result = _invoke(d)
    assert _has_issue(result, "TARGET_ASSESSMENT_INVALID"), (
        "Expected TARGET_ASSESSMENT_INVALID for whitespace-only target_assessment.json; "
        f"got issues: {result['issues']}"
    )


# ---------------------------------------------------------------------------
# 6. TARGET_ASSESSMENT_INVALID
# ---------------------------------------------------------------------------


def test_target_assessment_invalid(tmp_path):
    """The target_assessment_invalid fixture has a valid JSON object but missing
    the required druggability_matrix key, causing contract validation to fail."""
    d = _copy_fixture("target_assessment_invalid", tmp_path)
    result = _invoke(d)
    assert _has_issue(result, "TARGET_ASSESSMENT_INVALID"), (
        f"Expected TARGET_ASSESSMENT_INVALID; got issues: {result['issues']}"
    )


# ---------------------------------------------------------------------------
# 7. MARKDOWN_TABLE_PIPE_DRIFT
# ---------------------------------------------------------------------------


def test_markdown_table_pipe_drift(tmp_path):
    """The markdown_table_pipe_drift fixture has a TGFB1 Drug Profile row with
    an extra unescaped pipe (| used as separator inside a cell), shifting columns."""
    d = _copy_fixture("markdown_table_pipe_drift", tmp_path)
    result = _invoke(d)
    assert _has_issue(result, "MARKDOWN_TABLE_PIPE_DRIFT"), (
        f"Expected MARKDOWN_TABLE_PIPE_DRIFT; got issues: {result['issues']}"
    )
    # The location field should reference the divergent row in drug.md.
    matching = [i for i in result["issues"] if i["code"] == "MARKDOWN_TABLE_PIPE_DRIFT"]
    assert any("drug.md:" in i["location"] for i in matching), (
        f"Expected location to reference drug.md line; got: {[i['location'] for i in matching]}"
    )


def test_moa_table_parser_preserves_escaped_pipe_cell():
    """Escaped pipes inside a MoA cell must not split the cell."""
    markdown = """| Drug | ChEMBL ID | Mechanism of Action | Phase |
|------|-----------|---------------------|------:|
| **ComboDrug** | CHEMBL1 | alpha \\| beta inhibitor | 2 |"""

    rows = list(stage_logic._iter_drug_profile_moa_cells(markdown))
    assert rows == [(3, "ComboDrug", "CHEMBL1", "alpha | beta inhibitor")]


# ---------------------------------------------------------------------------
# 8. STAGE1_COUNT_MISMATCH
# ---------------------------------------------------------------------------


def test_stage1_count_mismatch_fixture(tmp_path):
    """The stage1_count_mismatch fixture explicitly states 'of 18 L-R pairs'
    but stage1_filter_results.json records 19 pairs."""
    d = _copy_fixture("stage1_count_mismatch", tmp_path)
    result = _invoke(d)
    assert _has_issue(result, "STAGE1_COUNT_MISMATCH"), (
        f"Expected STAGE1_COUNT_MISMATCH; got issues: {result['issues']}"
    )


def test_stage1_count_mismatch_uses_evidence_artifact(tmp_path):
    """Count claims must be checked against evidence/stage1_filter_results.json."""
    d = _copy_fixture("clean", tmp_path)
    _move_stage1_filter_results_to_evidence(d)
    drug_md_path = d / "drug.md"
    original = drug_md_path.read_text(encoding="utf-8")
    drug_md_path.write_text(
        "Analysis covers across 18 L-R pairs from the fibrotic cohort.\n\n" + original,
        encoding="utf-8",
    )

    result = _invoke(d)
    assert _has_issue(result, "STAGE1_COUNT_MISMATCH"), (
        f"Expected STAGE1_COUNT_MISMATCH using evidence artifact; got issues: {result['issues']}"
    )


@pytest.mark.parametrize(
    "count_phrase",
    [
        "of 18 ligand-receptor pairs",
        "across 18 L-R pairs",
        "across 18 ligand-receptor pairs",
        "from 18 pairs",
    ],
)
def test_stage1_count_mismatch_phrasings(count_phrase, tmp_path):
    """Each supported count-claim phrasing must be detected when it disagrees
    with stage1_filter_results.json.

    We copy the clean fixture (20 pairs) and inject a count claim of 18.
    """
    d = _copy_fixture("clean", tmp_path)
    drug_md_path = d / "drug.md"
    original = drug_md_path.read_text(encoding="utf-8")
    # Prepend a claim line in the Executive Summary to ensure the pattern fires.
    injected = f"Analysis covers {count_phrase} from the fibrotic cohort.\n\n" + original
    drug_md_path.write_text(injected, encoding="utf-8")
    result = _invoke(d)
    assert _has_issue(result, "STAGE1_COUNT_MISMATCH"), (
        f"Expected STAGE1_COUNT_MISMATCH for phrase '{count_phrase}'; "
        f"got issues: {result['issues']}"
    )


def test_stage1_count_mismatch_noop_when_no_claim(tmp_path):
    """When drug.md contains no count-claim phrase, STAGE1_COUNT_MISMATCH must
    NOT be emitted (the check is a no-op)."""
    d = _copy_fixture("clean", tmp_path)
    drug_md_path = d / "drug.md"
    text = drug_md_path.read_text(encoding="utf-8")
    # Verify the clean fixture itself has no count phrase; if it does, remove it.
    import re
    count_pattern = re.compile(
        r"(?:of|across|from)\s+\d+\s+(?:L[-\s]?R|ligand[-\s]?receptor|)[\w\s]*pairs",
        re.IGNORECASE,
    )
    cleaned = count_pattern.sub("", text)
    drug_md_path.write_text(cleaned, encoding="utf-8")
    result = _invoke(d)
    assert not _has_issue(result, "STAGE1_COUNT_MISMATCH"), (
        f"Expected no STAGE1_COUNT_MISMATCH with no count phrase; got: {result['issues']}"
    )


# ---------------------------------------------------------------------------
# 9. EMPTY_GAP_ANALYSIS
# ---------------------------------------------------------------------------


def test_empty_gap_analysis(tmp_path):
    """The empty_gap_analysis fixture has '### Gap Analysis' immediately followed
    by the next heading with no body text."""
    d = _copy_fixture("empty_gap_analysis", tmp_path)
    result = _invoke(d)
    assert _has_issue(result, "EMPTY_GAP_ANALYSIS"), (
        f"Expected EMPTY_GAP_ANALYSIS; got issues: {result['issues']}"
    )


# ---------------------------------------------------------------------------
# 10. UNSUPPORTED_MOA_CLAIM
# ---------------------------------------------------------------------------


def test_unsupported_moa_claim(tmp_path):
    """The unsupported_moa_claim fixture has TGFB1 Drug Profile MoA claiming
    'potent JAK1 selective inhibitor reducing cytokine storm in fibrosis' —
    a phrase absent from the stage3 evidence files."""
    d = _copy_fixture("unsupported_moa_claim", tmp_path)
    result = _invoke(d)
    assert _has_issue(result, "UNSUPPORTED_MOA_CLAIM"), (
        f"Expected UNSUPPORTED_MOA_CLAIM; got issues: {result['issues']}"
    )
    # The issue message should mention the unsupported MoA value.
    matching = [i for i in result["issues"] if i["code"] == "UNSUPPORTED_MOA_CLAIM"]
    assert any("jak1" in i["message"].lower() for i in matching), (
        f"Expected MoA value 'JAK1' mentioned in issue message; got: {[i['message'] for i in matching]}"
    )


def test_unsupported_moa_claim_negative(tmp_path):
    """When MoA cell values are present in stage3 evidence, no UNSUPPORTED_MOA_CLAIM
    should be emitted. The clean fixture has MoA values that match stage3 evidence."""
    d = _copy_fixture("clean", tmp_path)
    result = _invoke(d)
    assert not _has_issue(result, "UNSUPPORTED_MOA_CLAIM"), (
        f"Expected no UNSUPPORTED_MOA_CLAIM for clean fixture; got: {result['issues']}"
    )


def test_unsupported_moa_claim_negative_from_resolved_drugs(tmp_path):
    """A Drug Profile MoA is supported when resolved_drugs.json has the same drug-specific MoA."""
    d = _copy_fixture("unsupported_moa_claim", tmp_path)
    resolved_path = d / "evidence" / "resolved_drugs.json"
    resolved_path.write_text(
        json.dumps(
            [
                {
                    "gene": "TGFB1",
                    "resolved_name": "ruxolitinib",
                    "chembl_id": "CHEMBL1789941",
                    "mechanism_of_action": (
                        "potent JAK1 selective inhibitor reducing cytokine storm in fibrosis"
                    ),
                    "first_approval": 2011,
                }
            ]
        ),
        encoding="utf-8",
    )

    result = _invoke(d)
    assert not _has_issue(result, "UNSUPPORTED_MOA_CLAIM"), (
        f"Expected resolved_drugs.json to support MoA; got issues: {result['issues']}"
    )


# ---------------------------------------------------------------------------
# 11. STALE_HYPOTHESIS_REPORT
# ---------------------------------------------------------------------------


def test_stale_hypothesis_report_newer_than_drug_md_fails(tmp_path):
    """If hypothesis_report.json is newer than drug.md and the report still
    contains placeholder/unavailable hypothesis text, finalization must fail.
    """
    d = _copy_fixture("clean", tmp_path)
    evidence_dir = d / "evidence"
    hypothesis_path = evidence_dir / "hypothesis_report.json"
    hypothesis_path.write_text(
        json.dumps(
            {
                "hypotheses": [
                    {
                        "rank": 1,
                        "title": "Macrophage FN1 signalling hypothesis",
                        "core_claim": "FN1 signalling is testable in fibrosis.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    drug_md_path = d / "drug.md"
    drug_md_path.write_text(
        "## 4. Evidence-Grounded Follow-up Recommendations\n\n"
        "No hypothesis_report.json content was loaded in the local evidence bundle.\n",
        encoding="utf-8",
    )

    os.utime(drug_md_path, (1_700_000_000, 1_700_000_000))
    os.utime(hypothesis_path, (1_700_000_100, 1_700_000_100))

    result = _invoke(d)
    assert _has_issue(result, "STALE_HYPOTHESIS_REPORT"), (
        f"Expected STALE_HYPOTHESIS_REPORT; got issues: {result['issues']}"
    )


# ---------------------------------------------------------------------------
# 12. Renderer metadata and new finalization gates
# ---------------------------------------------------------------------------


def test_finalization_fails_when_renderer_metadata_missing_in_renderer_mode(tmp_path):
    d = _copy_fixture("clean", tmp_path)
    persist_drug_report_reference_card(
        d,
        {
            "markdown_template": (d / "drug.md").read_text(encoding="utf-8"),
            "expansion_slots": [],
        },
    )
    (d / "report_expansions.json").write_text(
        json.dumps({
            "schema_version": "report_expansions.v1",
            "reference_card_hash": "stale",
            "slots": [],
        }),
        encoding="utf-8",
    )

    result = _invoke(d)

    assert _has_issue(result, "MISSING_RENDER_METADATA"), result["issues"]


def test_markdown_only_finalization_requires_explicit_legacy_flag(tmp_path):
    d = _copy_fixture("clean", tmp_path)

    result = _invoke(d, allow_legacy=False)

    assert _has_issue(result, "MISSING_RENDER_METADATA"), result["issues"]


def test_finalization_fails_when_render_source_hash_mismatch(tmp_path):
    d = _copy_fixture("clean", tmp_path)
    _write_renderer_sidecars(d, bad_source_hash=True)

    result = _invoke(d)

    assert _has_issue(result, "RENDER_SOURCE_HASH_MISMATCH"), result["issues"]


def test_finalization_fails_when_rendered_drug_md_hash_mismatch(tmp_path):
    d = _copy_fixture("clean", tmp_path)
    _write_renderer_sidecars(d, bad_drug_hash=True)

    result = _invoke(d)

    assert _has_issue(result, "RENDERED_DRUG_MD_HASH_MISMATCH"), result["issues"]


def test_finalization_fails_when_renderer_source_artifacts_missing(tmp_path):
    d = _copy_fixture("clean", tmp_path)
    metadata = {
        "schema_version": "drug_report_render.v1",
        "renderer": "render_drug_md_from_expansions",
        "mode": "renderer",
        "source_hashes": {
            "reference_card": "missing-reference-card-hash",
            "report_expansions": "missing-expansions-hash",
            "hypothesis_report": None,
            "template": "unused-in-this-unit-test",
        },
        "rendered_drug_md_sha256": _drug_hash(d),
        "required_slot_count": 0,
        "rendered_slot_count": 0,
        "missing_slots": [],
        "extra_slots": [],
    }
    (d / "drug_report_render.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    result = _invoke(d)

    assert _has_issue(result, "MISSING_RENDER_SOURCE"), result["issues"]


def test_finalization_fails_when_failed_suffix_leaks_to_drug_md(tmp_path):
    d = _copy_fixture("clean", tmp_path)
    drug_path = d / "drug.md"
    drug_path.write_text(
        drug_path.read_text(encoding="utf-8") + "\nstage1_CD4--ITGB2.json_FAILED\n",
        encoding="utf-8",
    )

    result = _invoke(d)

    assert _has_issue(result, "FAILED_SUFFIX_LEAK"), result["issues"]


def test_finalization_reports_unverified_numeric_prediction_by_default(tmp_path):
    d = _copy_fixture("clean", tmp_path)
    hyp_path = d / "evidence" / "hypothesis_report.json"
    payload = {"hypotheses": []}
    payload["prediction_grounding_summary"] = {
        "unverified": 1,
        "unverified_indices": [0],
    }
    hyp_path.write_text(json.dumps(payload), encoding="utf-8")
    os.utime(hyp_path, (1_700_000_000, 1_700_000_000))
    os.utime(d / "drug.md", (1_700_000_100, 1_700_000_100))

    result = _invoke(d)

    assert not _has_issue(result, "UNVERIFIED_NUMERIC_PREDICTION"), result["issues"]
    assert any(
        "UNVERIFIED_NUMERIC_PREDICTION" in warning
        for warning in result["checks"]["report_finalization"]["warnings"]
    )


def test_finalization_strict_mode_fails_unverified_numeric_prediction(
    tmp_path, monkeypatch
):
    d = _copy_fixture("clean", tmp_path)
    hyp_path = d / "evidence" / "hypothesis_report.json"
    payload = {"hypotheses": []}
    payload["prediction_grounding_summary"] = {
        "unverified": 1,
        "unverified_indices": [0],
    }
    hyp_path.write_text(json.dumps(payload), encoding="utf-8")
    os.utime(hyp_path, (1_700_000_000, 1_700_000_000))
    os.utime(d / "drug.md", (1_700_000_100, 1_700_000_100))
    monkeypatch.setenv("DEEPMAST_STRICT_NUMERIC_PREDICTIONS", "1")

    result = _invoke(d)

    assert _has_issue(result, "UNVERIFIED_NUMERIC_PREDICTION"), result["issues"]


def test_finalization_fails_legacy_mode_unless_compat_flag_set(
    tmp_path, monkeypatch
):
    d = _copy_fixture("clean", tmp_path)
    metadata = {
        "schema_version": "drug_report_render.v1",
        "mode": "legacy_compat",
        "source_hashes": {},
        "rendered_drug_md_sha256": _drug_hash(d),
        "missing_slots": [],
        "extra_slots": [],
    }
    (d / "drug_report_render.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    result = _invoke(d, allow_legacy=False)
    assert _has_issue(result, "LEGACY_RENDER_MODE_NOT_ALLOWED"), result["issues"]

    monkeypatch.setenv("DEEPMAST_ALLOW_LEGACY_DRUG_MD", "1")
    result = _invoke(d)
    assert not _has_issue(result, "LEGACY_RENDER_MODE_NOT_ALLOWED"), result["issues"]


# ---------------------------------------------------------------------------
# 13. validate_drug_md signature dispatch
# ---------------------------------------------------------------------------


def test_validate_drug_md_str_uses_resolve_data_dir(tmp_path, monkeypatch):
    """When validate_drug_md is called with a str, it invokes _resolve_data_dir
    (lazily imported from evidence_loader inside the else-branch). We monkeypatch
    evidence_loader._resolve_data_dir to redirect any path to a valid clean fixture
    copy. The validator must return valid=True confirming the fallback executed."""
    clean_copy = _copy_fixture("clean", tmp_path)
    nonexistent_str = str(tmp_path / "nonexistent_workspace")

    import src.agents.drug_target.tools.evidence_loader as _el

    def _fake_resolve(path_str):
        # Ignore whatever was passed; return the clean fixture path.
        return clean_copy

    monkeypatch.setattr(_el, "_resolve_data_dir", _fake_resolve)

    # validate_drug_md is a @tool; unwrap to call the underlying function.
    impl = getattr(validate_drug_md, "func", None) or validate_drug_md
    raw_json = impl(nonexistent_str)
    raw = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
    # The redirect must have succeeded — valid=True (clean fixture passes).
    assert raw.get("valid") is True, (
        f"Expected valid=True after _resolve_data_dir redirect; got: {raw}"
    )


def test_validate_drug_md_path_skips_resolve_data_dir(tmp_path, monkeypatch):
    """When validate_drug_md is called with a Path, _resolve_data_dir must NOT
    be called. We monkeypatch it to raise AssertionError; if the Path branch
    fires correctly, no error is raised and valid=True is returned."""
    clean_copy = _copy_fixture("clean", tmp_path)

    import src.agents.drug_target.tools.stage_logic as _sl

    def _must_not_be_called(path_str):
        raise AssertionError("_resolve_data_dir must not be called when a Path is passed")

    monkeypatch.setattr(_sl, "_must_not_be_called_sentinel", _must_not_be_called, raising=False)

    # Patch the name actually imported inside validate_drug_md's else-branch.
    import src.agents.drug_target.tools.evidence_loader as _el
    monkeypatch.setattr(_el, "_resolve_data_dir", _must_not_be_called)

    impl = getattr(validate_drug_md, "func", None) or validate_drug_md
    # Pass a Path — must NOT raise AssertionError.
    raw_json = impl(clean_copy)  # clean_copy is already a Path
    raw = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
    assert raw.get("valid") is True, (
        f"Expected valid=True when called with Path; got: {raw}"
    )

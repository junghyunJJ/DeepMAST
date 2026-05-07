"""TC-T11 (RED): Verify featured_cards builder populates matched_drugs from evidence files.

The `build_evidence_summary` function in stage_logic.py assembles `featured_cards`
at lines 2212-2226. At RED state the `card["stage3"]` dict does NOT contain a
`matched_drugs` key — the normalization step at lines 2018-2025 strips it and the
assembly loop does not yet re-attach it from the on-disk evidence file.

Task #12 (GREEN) will add the copy line between lines 2224 and 2226.

Four scenarios:
    (a) ITGB2 with 10 matched_drugs — length and content preserved
    (b) MUC1 with 0 matched_drugs   — empty list, no KeyError / None
    (c) Missing stage3 evidence file — defaults to [], no KeyError raised
    (d) Bypass verification          — even though normalization drops matched_drugs,
        the assembly site reads evidence_dir/stage3_{gene}.json directly; assert
        that the fixture file content reaches card["stage3"]["matched_drugs"]
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures"

_MINIMAL_RUBRIC_ROW_ITGB2 = {
    "gene": "ITGB2",
    "existing_drug_evidence": 3,
    "clinical_trial_activity": 2,
    "safety_profile": 1,
    "validated_total": 6,
    "gwas_support": 1,
    "tractability": 2,
    "biological_plausibility": 2,
    "novelty_opportunity": 1,
    "exploratory_total": 6,
    "combined_total": 12,
    "classification": "validated_target",
    "priority": "high",
    "stage3_candidate": True,
}

_MINIMAL_RUBRIC_ROW_MUC1 = {
    "gene": "MUC1",
    "existing_drug_evidence": 1,
    "clinical_trial_activity": 1,
    "safety_profile": 1,
    "validated_total": 3,
    "gwas_support": 0,
    "tractability": 1,
    "biological_plausibility": 1,
    "novelty_opportunity": 1,
    "exploratory_total": 3,
    "combined_total": 6,
    "classification": "exploratory_target",
    "priority": "medium",
    "stage3_candidate": True,
}


def _make_assessment(gene: str, rubric_row: dict) -> dict:
    """Minimal assessment_results.json content for a single gene."""
    return {
        "disease": "test_disease",
        "rubric_assessment": [rubric_row],
        "stage3_candidates": [{"gene": gene}],
    }


def _setup_evidence_dir(tmp_path: Path, gene: str, rubric_row: dict) -> Path:
    """Write evidence dir with assessment_results.json for one gene; returns data_dir."""
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    assessment = _make_assessment(gene, rubric_row)
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps(assessment), encoding="utf-8"
    )
    return tmp_path


def _copy_stage3_fixture(gene: str, evidence_dir: Path) -> None:
    """Copy a pre-built stage3_{gene}.json fixture into evidence_dir."""
    src = FIXTURE_DIR / f"stage3_{gene}.json"
    dst = evidence_dir / f"stage3_{gene}.json"
    shutil.copy(src, dst)


def _invoke_build_evidence_summary(data_dir: Path) -> dict:
    """Call build_evidence_summary with mocked render_drug_md and sidecar persist.

    build_evidence_summary is a @tool-decorated StructuredTool. We access the
    underlying Python function via .func to invoke it directly without LangChain
    tool-call overhead, and mock its heavy dependencies to keep the test focused
    on the featured_cards assembly logic.
    """
    with (
        patch(
            "src.agents.drug_target.tools.drug_report_html.render_drug_md",
            return_value="# stub markdown",
        ),
        patch(
            "src.agents.drug_target.tools.report_expansion_schema.persist_drug_report_reference_card",
            side_effect=lambda _dir, card: card,
        ),
        patch(
            "src.agents.drug_target.tools.stage_logic._prebuild_target_assessment",
            return_value=None,
        ),
    ):
        from src.agents.drug_target.tools.stage_logic import build_evidence_summary

        # .func gives direct access to the unwrapped function under the @tool decorator
        raw = build_evidence_summary.func(str(data_dir))
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Scenario (a): ITGB2 with 10 matched_drugs — length and content preserved
# ---------------------------------------------------------------------------


def test_featured_card_itgb2_matched_drugs_has_length_10(tmp_path: Path) -> None:
    """After assembly, ITGB2 card must expose matched_drugs with exactly 10 entries."""
    # Arrange
    data_dir = _setup_evidence_dir(tmp_path, "ITGB2", _MINIMAL_RUBRIC_ROW_ITGB2)
    _copy_stage3_fixture("ITGB2", data_dir / "evidence")

    # Act
    result = _invoke_build_evidence_summary(data_dir)

    # Assert
    featured_genes = result["featured_genes"]
    assert len(featured_genes) == 1, "Expected exactly one featured gene"
    card = featured_genes[0]
    assert card["gene"] == "ITGB2"

    # RED: this key is absent until Task #12 adds the copy line
    matched_drugs = card["stage3"]["matched_drugs"]  # KeyError expected in RED state
    assert len(matched_drugs) == 10, (
        f"Expected 10 matched_drugs, got {len(matched_drugs)}"
    )


def test_featured_card_itgb2_matched_drugs_preserves_chembl_ids(tmp_path: Path) -> None:
    """matched_drugs entries must preserve chembl_id values from the fixture file."""
    # Arrange
    data_dir = _setup_evidence_dir(tmp_path, "ITGB2", _MINIMAL_RUBRIC_ROW_ITGB2)
    _copy_stage3_fixture("ITGB2", data_dir / "evidence")

    # Act
    result = _invoke_build_evidence_summary(data_dir)

    # Assert
    card = result["featured_genes"][0]

    # RED: KeyError expected here — matched_drugs key absent until GREEN
    matched_drugs = card["stage3"]["matched_drugs"]

    chembl_ids = {d["chembl_id"] for d in matched_drugs}
    expected_first = "CHEMBL12001"
    assert expected_first in chembl_ids, (
        f"Expected {expected_first} in matched_drugs chembl_ids, got {chembl_ids}"
    )
    # All 10 fixture items should be present
    assert len(chembl_ids) == 10, (
        f"Expected 10 distinct chembl_ids, got {len(chembl_ids)}"
    )


# ---------------------------------------------------------------------------
# Scenario (b): MUC1 with 0 matched_drugs — empty list, no exception
# ---------------------------------------------------------------------------


def test_featured_card_muc1_matched_drugs_is_empty_list(tmp_path: Path) -> None:
    """MUC1 card with empty chembl.matched_drugs must yield [] — not None, not KeyError."""
    # Arrange
    data_dir = _setup_evidence_dir(tmp_path, "MUC1", _MINIMAL_RUBRIC_ROW_MUC1)
    _copy_stage3_fixture("MUC1", data_dir / "evidence")

    # Act
    result = _invoke_build_evidence_summary(data_dir)

    # Assert
    card = result["featured_genes"][0]
    assert card["gene"] == "MUC1"

    # RED: KeyError expected — matched_drugs absent until GREEN
    matched_drugs = card["stage3"]["matched_drugs"]
    assert matched_drugs == [], (
        f"Expected empty list for MUC1 matched_drugs, got {matched_drugs!r}"
    )
    assert matched_drugs is not None, "matched_drugs must be [] not None"


# ---------------------------------------------------------------------------
# Scenario (c): Missing stage3 evidence file — defaults to [], no KeyError
# ---------------------------------------------------------------------------


def test_featured_card_missing_stage3_file_matched_drugs_is_empty_list(
    tmp_path: Path,
) -> None:
    """When stage3_{gene}.json is absent, card["stage3"]["matched_drugs"] must be []."""
    # Arrange — do NOT copy any stage3 fixture; the file is intentionally absent
    data_dir = _setup_evidence_dir(tmp_path, "ITGB2", _MINIMAL_RUBRIC_ROW_ITGB2)
    assert not (data_dir / "evidence" / "stage3_ITGB2.json").exists(), (
        "Test setup error: stage3 file must be absent for this scenario"
    )

    # Act
    result = _invoke_build_evidence_summary(data_dir)

    # Assert
    card = result["featured_genes"][0]
    assert card["gene"] == "ITGB2"

    # RED: KeyError expected — matched_drugs absent until GREEN adds fallback
    matched_drugs = card["stage3"]["matched_drugs"]
    assert matched_drugs == [], (
        f"Missing stage3 file must yield matched_drugs=[], got {matched_drugs!r}"
    )


# ---------------------------------------------------------------------------
# Scenario (d): Normalization bypass — evidence file content reaches card
# ---------------------------------------------------------------------------


def test_featured_card_matched_drugs_sourced_from_evidence_dir_not_normalization(
    tmp_path: Path,
) -> None:
    """matched_drugs must come from on-disk stage3_{gene}.json, not the normalization pass.

    The normalization step at stage_logic.py:2018-2025 builds stage3_data[gene] WITHOUT
    a matched_drugs key (verified in Phase 1 #1). The assembly site at lines 2212-2226
    must read the evidence file directly and attach it. This test verifies the content
    at card["stage3"]["matched_drugs"] matches the fixture file — proving the data
    bypassed the normalization site and came directly from evidence_dir.
    """
    # Arrange
    data_dir = _setup_evidence_dir(tmp_path, "ITGB2", _MINIMAL_RUBRIC_ROW_ITGB2)
    evidence_dir = data_dir / "evidence"
    _copy_stage3_fixture("ITGB2", evidence_dir)

    # Read the fixture directly to know the expected content
    fixture_content = json.loads((evidence_dir / "stage3_ITGB2.json").read_text())
    expected_drugs = fixture_content["chembl"]["matched_drugs"]
    assert len(expected_drugs) == 10, "Fixture must have 10 drugs"

    # Act
    result = _invoke_build_evidence_summary(data_dir)

    # Assert
    card = result["featured_genes"][0]

    # RED: KeyError expected here — the normalization path does NOT populate matched_drugs;
    # only the Task #12 fix at the assembly site will do so
    matched_drugs = card["stage3"]["matched_drugs"]

    # The first drug's drug_name must match exactly what is in the on-disk fixture
    first_expected_name = expected_drugs[0]["drug_name"]
    first_actual_name = matched_drugs[0]["drug_name"]
    assert first_actual_name == first_expected_name, (
        f"Expected drug_name={first_expected_name!r} from evidence file, "
        f"got {first_actual_name!r} — data did not originate from evidence_dir"
    )

    # Verify mechanism_of_action is also preserved (field confirmed present in fixture)
    first_expected_moa = expected_drugs[0]["mechanism_of_action"]
    first_actual_moa = matched_drugs[0]["mechanism_of_action"]
    assert first_actual_moa == first_expected_moa, (
        f"Expected mechanism_of_action={first_expected_moa!r}, got {first_actual_moa!r}"
    )

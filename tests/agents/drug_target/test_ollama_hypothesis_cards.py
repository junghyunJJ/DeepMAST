from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.drug_target.ollama_hypothesis_cards import (
    build_ollama_card_specs,
    build_ollama_hypothesis_report,
)
from src.agents.drug_target.tools.hypothesis_schema import (
    canonicalize_hypothesis_report,
    validate_canonical_hypothesis_report,
)


@pytest.fixture
def bc_data_dir() -> Path:
    return Path(__file__).resolve().parents[3].parent.parent / "final_bc"


def test_card_specs_cover_all_featured_genes_with_four_categories(
    bc_data_dir: Path,
) -> None:
    specs = build_ollama_card_specs(bc_data_dir)

    assert [spec["category"] for spec in specs] == [
        "Mechanism of Action",
        "Therapeutic Strategy",
        "Cross-Target Interaction",
        "Novel Pathway",
    ]
    assert {gene for spec in specs for gene in spec["genes"]} == {
        "EFNB2",
        "EPHB4",
        "ERBB2",
        "ERBB3",
        "INSR",
        "LAMA5",
        "NECTIN4",
    }
    assert all(spec["evidence_references"] for spec in specs)
    assert "SDC1" in specs[0]["known_genes"]


def test_skeleton_is_schema_valid_without_model_selected_references(
    bc_data_dir: Path,
) -> None:
    report = build_ollama_hypothesis_report(bc_data_dir, {})
    canonical, errors, _ = canonicalize_hypothesis_report(
        report,
        bc_data_dir / "evidence",
        legacy_compat=False,
    )

    assert canonical is not None, errors
    assert errors == []
    assert validate_canonical_hypothesis_report(
        canonical,
        bc_data_dir / "evidence",
    ) == []


def test_skeleton_replaces_unsafe_card_text_with_its_fallback(
    bc_data_dir: Path,
) -> None:
    report = build_ollama_hypothesis_report(
        bc_data_dir,
        {"mechanism": "ERBB3 has synergistic effects with EPHB4."},
    )

    assert report["hypotheses"][0]["core_claim"] == (
        "ERBB3 and EFNB2 are evidence-supported candidates for validation "
        "in malignant cell context."
    )


def test_skeleton_replaces_card_text_that_repeats_a_filename(
    bc_data_dir: Path,
) -> None:
    report = build_ollama_hypothesis_report(
        bc_data_dir,
        {"mechanism": "ERBB3 is supported by ot_ERBB3.json."},
    )

    assert report["hypotheses"][0]["core_claim"] == (
        "ERBB3 and EFNB2 are evidence-supported candidates for validation "
        "in malignant cell context."
    )

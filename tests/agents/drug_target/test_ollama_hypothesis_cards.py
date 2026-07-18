from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.drug_target.ollama_hypothesis_cards import (
    OllamaCardSpec,
    build_ollama_card_specs,
    build_ollama_hypothesis_report,
    is_ollama_card_text_safe,
)
from src.agents.drug_target.tools.hypothesis_schema import (
    canonicalize_hypothesis_report,
    validate_canonical_hypothesis_report,
)


@pytest.fixture
def bc_data_dir() -> Path:
    return Path(__file__).resolve().parents[3].parent.parent / "final_bc"


def _bounded_card() -> str:
    return "\n".join((
        "CORE: ERBB3 and EFNB2 are evidence-supported candidates for validation in malignant cell context.",
        "CONSTRAINT: This follow-up does not establish a causal mechanism.",
        "PREDICTION: Test separate ERBB3 and EFNB2 perturbations with prespecified malignant cell readouts.",
        "VALIDATION: Evaluate separate perturbation readouts in malignant cell context.",
    ))


def _mechanism_spec() -> OllamaCardSpec:
    return {
        "id": "mechanism",
        "category": "Mechanism of Action",
        "genes": ["ERBB3", "EFNB2"],
        "evidence_references": [],
        "cell_anchor": "malignant cell",
        "fallback_hypothesis": (
            "ERBB3 and EFNB2 are evidence-supported candidates for validation "
            "in malignant cell context."
        ),
        "fallback_card": {
            "core_claim": (
                "ERBB3 and EFNB2 are evidence-supported candidates for validation "
                "in malignant cell context."
            ),
            "interpretation_note": "This follow-up does not establish a causal mechanism.",
            "falsifiable_prediction": (
                "Test whether separate perturbation of the listed candidates "
                "changes prespecified malignant cell readouts."
            ),
            "validation_approach": (
                "Evaluate separate perturbation readouts in malignant cell context."
            ),
        },
        "known_genes": ["ERBB3", "EFNB2", "SDC1"],
    }


def test_parse_bounded_hypothesis_card_returns_named_fields() -> None:
    from src.agents.drug_target.ollama_hypothesis_cards import parse_ollama_hypothesis_card

    card, errors = parse_ollama_hypothesis_card(_bounded_card())

    assert errors == []
    assert card is not None
    assert card["interpretation_note"] == "This follow-up does not establish a causal mechanism."


def test_hypothesis_report_uses_all_fallback_fields(bc_data_dir: Path) -> None:
    hypothesis = build_ollama_hypothesis_report(bc_data_dir, {})["hypotheses"][0]

    assert hypothesis["interpretation_note"] == "This follow-up does not establish a causal mechanism."
    assert hypothesis["core_claim"].endswith("malignant cell context.")
    assert hypothesis["falsifiable_prediction"].startswith("Test whether")
    assert hypothesis["validation_approach"].startswith("Evaluate")


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (_bounded_card().replace("ERBB3 and EFNB2", "ERBB3 and SDC1"), "UNSUPPORTED_GENE"),
        (_bounded_card().replace("does not establish", "proves"), "CONSTRAINT_UNSAFE_CLAIM"),
        (_bounded_card().replace("prespecified", "99% prespecified"), "UNSUPPORTED_NUMBER"),
        (_bounded_card() + "\nEXTRA: text", "CARD_FORMAT"),
    ],
)
def test_bounded_hypothesis_card_rejects_unsafe_content(text: str, code: str) -> None:
    from src.agents.drug_target.ollama_hypothesis_cards import (
        parse_ollama_hypothesis_card,
        validate_ollama_hypothesis_card,
    )

    card, errors = parse_ollama_hypothesis_card(text)
    if card is not None:
        errors = validate_ollama_hypothesis_card(card, spec=_mechanism_spec())
    assert any(code in error for error in errors)


def test_canonicalization_revalidates_marked_ollama_enrichment(
    bc_data_dir: Path,
) -> None:
    report = build_ollama_hypothesis_report(bc_data_dir, {})
    report["hypotheses"][0]["interpretation_note"] = (
        "This follow-up proves a causal mechanism."
    )

    canonical, errors, _ = canonicalize_hypothesis_report(
        report,
        bc_data_dir / "evidence",
        legacy_compat=False,
    )

    assert canonical is not None
    assert "hypotheses[0].ollama_enrichment:CONSTRAINT_UNSAFE_CLAIM" in errors


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


def test_skeleton_replaces_causal_card_text_with_its_fallback(
    bc_data_dir: Path,
) -> None:
    causal_claim = "ERBB3 drives breast cancer invasion."

    assert not is_ollama_card_text_safe(
        causal_claim,
        allowed_genes=["ERBB3", "EFNB2"],
        known_genes=["ERBB3", "EFNB2", "EPHB4"],
    )
    report = build_ollama_hypothesis_report(
        bc_data_dir,
        {"mechanism": causal_claim},
    )

    assert report["hypotheses"][0]["core_claim"] == (
        "ERBB3 and EFNB2 are evidence-supported candidates for validation "
        "in malignant cell context."
    )


def test_card_text_accepts_only_conservative_candidate_form() -> None:
    assert is_ollama_card_text_safe(
        "ERBB3 and EFNB2 are evidence-supported candidates for validation "
        "in malignant cell context.",
        allowed_genes=["ERBB3", "EFNB2"],
        known_genes=["ERBB3", "EFNB2", "EPHB4"],
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

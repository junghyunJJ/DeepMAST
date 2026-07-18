from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.drug_target.ollama_hypothesis_cards import (
    OllamaCardSpec,
    VALIDATION_FOCUS_BY_CATEGORY,
    build_ollama_card_specs,
    build_ollama_hypothesis_report,
    is_ollama_card_text_safe,
    validation_focus_for_category,
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
        "PREDICTION: Test whether separate ERBB3 and EFNB2 perturbation shifts a prespecified malignant-cell readout.",
        "VALIDATION: Evaluate separate ERBB3 and EFNB2 perturbation with a generic primary assay, matched controls, and prespecified malignant-cell readouts.",
    ))


RICH_CARD = "\n".join((
    "CORE: ERBB3 is an evidence-supported validation candidate in the malignant-cell context. Its prioritization warrants validation against the supplied evidence references.",
    "CONSTRAINT: This follow-up does not establish a causal mechanism from the current evidence. It should be interpreted as a bounded candidate-level hypothesis.",
    "PREDICTION: Test whether separate ERBB3 perturbation shifts a prespecified malignant-cell readout. Compare the perturbation with a matched non-targeting control.",
    "VALIDATION: Evaluate ERBB3 perturbation using a generic primary assay with matched controls and prespecified readouts. Add an orthogonal comparator only as a future design choice, not as existing evidence.",
))


def _mechanism_spec() -> OllamaCardSpec:
    return {
        "id": "mechanism",
        "category": "Mechanism of Action",
        "validation_focus": "Mechanistic follow-up",
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
                "Test whether separate ERBB3 and EFNB2 perturbation shifts a "
                "prespecified malignant-cell readout."
            ),
            "validation_approach": (
                "Evaluate separate ERBB3 and EFNB2 perturbation with a generic "
                "primary assay, matched controls, and prespecified malignant-cell readouts."
            ),
        },
        "known_genes": ["ERBB3", "EFNB2", "SDC1"],
    }


def test_parse_bounded_hypothesis_card_returns_named_fields() -> None:
    from src.agents.drug_target.ollama_hypothesis_cards import (
        parse_ollama_hypothesis_card,
        validate_ollama_hypothesis_card,
    )

    card, errors = parse_ollama_hypothesis_card(_bounded_card())

    assert errors == []
    assert card is not None
    assert card["interpretation_note"] == "This follow-up does not establish a causal mechanism."
    assert validate_ollama_hypothesis_card(card, spec=_mechanism_spec()) == []


def test_bounded_hypothesis_card_accepts_two_sentence_fields() -> None:
    from src.agents.drug_target.ollama_hypothesis_cards import (
        parse_ollama_hypothesis_card,
        validate_ollama_hypothesis_card,
    )

    card, errors = parse_ollama_hypothesis_card(RICH_CARD)

    assert errors == []
    assert card is not None
    assert validate_ollama_hypothesis_card(card, spec=_mechanism_spec()) == []


def test_hypothesis_report_uses_all_fallback_fields(bc_data_dir: Path) -> None:
    hypothesis = build_ollama_hypothesis_report(bc_data_dir, {})["hypotheses"][0]

    assert hypothesis["interpretation_note"] == "This follow-up does not establish a causal mechanism."
    assert hypothesis["core_claim"].endswith("malignant cell context.")
    assert hypothesis["falsifiable_prediction"].startswith("Test whether")
    assert hypothesis["validation_approach"].startswith("Evaluate")


def test_hypothesis_report_keeps_valid_mapped_card(bc_data_dir: Path) -> None:
    from src.agents.drug_target.ollama_hypothesis_cards import parse_ollama_hypothesis_card

    card, errors = parse_ollama_hypothesis_card(_bounded_card())
    assert errors == []
    assert card is not None

    hypothesis = build_ollama_hypothesis_report(
        bc_data_dir,
        {"mechanism": card},
    )["hypotheses"][0]

    assert hypothesis["core_claim"] == card["core_claim"]
    assert hypothesis["interpretation_note"] == card["interpretation_note"]
    assert hypothesis["falsifiable_prediction"] == card["falsifiable_prediction"]
    assert hypothesis["validation_approach"] == card["validation_approach"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "falsifiable_prediction",
            "Test ERBB3 and EFNB2 with a prespecified malignant-cell readout under matched control conditions.",
        ),
        (
            "falsifiable_prediction",
            "Use separate ERBB3 and EFNB2 perturbation with a prespecified malignant-cell readout under matched control conditions.",
        ),
        (
            "validation_approach",
            "Evaluate ERBB3 and EFNB2 with matched control conditions and prespecified malignant-cell readouts for this future assay.",
        ),
        (
            "validation_approach",
            "Use separate ERBB3 and EFNB2 perturbation with matched control conditions and prespecified malignant-cell readouts for this future assay.",
        ),
    ],
)
def test_bounded_hypothesis_card_accepts_each_action_term_side(
    field: str,
    value: str,
) -> None:
    from src.agents.drug_target.ollama_hypothesis_cards import (
        parse_ollama_hypothesis_card,
        validate_ollama_hypothesis_card,
    )

    card, errors = parse_ollama_hypothesis_card(_bounded_card())
    assert errors == []
    assert card is not None
    card[field] = value

    assert validate_ollama_hypothesis_card(card, spec=_mechanism_spec()) == []


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (_bounded_card().replace("ERBB3 and EFNB2", "ERBB3 and SDC1"), "UNSUPPORTED_GENE"),
        (_bounded_card().replace("does not establish", "proves"), "CONSTRAINT_UNSAFE_CLAIM"),
        (_bounded_card().replace("prespecified", "99% prespecified"), "UNSUPPORTED_NUMBER"),
        (_bounded_card().replace("prespecified", "a .json marker in"), "PREDICTION_UNSAFE_CONTENT"),
        (
            _bounded_card().replace(
                "evidence-supported candidates",
                "evidence-*supported* candidates",
            ),
            "CORE_UNSAFE_CONTENT",
        ),
        (
            _bounded_card().replace(
                "evidence-supported candidates",
                "evidence-_supported_ candidates",
            ),
            "CORE_UNSAFE_CONTENT",
        ),
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


@pytest.mark.parametrize("causal_verb", ["mediate", "mediates", "mediated"])
def test_bounded_hypothesis_card_rejects_mediates_core_claim(causal_verb: str) -> None:
    from src.agents.drug_target.ollama_hypothesis_cards import (
        parse_ollama_hypothesis_card,
        validate_ollama_hypothesis_card,
    )

    card, errors = parse_ollama_hypothesis_card(
        _bounded_card().replace(
            "ERBB3 and EFNB2 are evidence-supported candidates for validation in malignant cell context.",
            "ERBB3 and EFNB2 are evidence-supported candidates for validation, but their pairing "
            f"{causal_verb} malignant cell outcomes.",
        )
    )

    assert errors == []
    assert card is not None
    assert "CORE_UNSAFE_CLAIM" in validate_ollama_hypothesis_card(
        card,
        spec=_mechanism_spec(),
    )


def test_bounded_hypothesis_card_rejects_hyphenated_direct_interaction() -> None:
    from src.agents.drug_target.ollama_hypothesis_cards import (
        parse_ollama_hypothesis_card,
        validate_ollama_hypothesis_card,
    )

    card, errors = parse_ollama_hypothesis_card(
        _bounded_card().replace(
            "in malignant cell context.",
            "in malignant cell context despite a direct-interaction claim.",
            1,
        )
    )

    assert errors == []
    assert card is not None
    assert "CORE_UNSAFE_CLAIM" in validate_ollama_hypothesis_card(
        card,
        spec=_mechanism_spec(),
    )


@pytest.mark.parametrize(
    ("replacement", "code"),
    [
        ("with aspirin.", "UNSUPPORTED_DRUG"),
        ("with ibuprofen.", "UNSUPPORTED_DRUG"),
        ("with tamoxifen.", "UNSUPPORTED_DRUG"),
        ("with warfarin.", "UNSUPPORTED_DRUG"),
        ("with metformin.", "UNSUPPORTED_DRUG"),
        ("with gefitinib.", "UNSUPPORTED_ENTITY"),
        ("with SDC1.", "UNSUPPORTED_GENE"),
        ("with a 10% threshold.", "UNSUPPORTED_NUMBER"),
        ("with citation [1].", "CORE_UNSAFE_CONTENT"),
        ("as PubMed supports this candidate.", "UNSUPPORTED_SOURCE"),
    ],
)
def test_bounded_hypothesis_card_rejects_unsupported_claim_inputs(
    replacement: str,
    code: str,
) -> None:
    from src.agents.drug_target.ollama_hypothesis_cards import (
        parse_ollama_hypothesis_card,
        validate_ollama_hypothesis_card,
    )

    card, errors = parse_ollama_hypothesis_card(
        _bounded_card().replace("in malignant cell context.", replacement, 1)
    )

    assert errors == []
    assert card is not None
    assert code in validate_ollama_hypothesis_card(card, spec=_mechanism_spec())


@pytest.mark.parametrize(
    "unsafe_claim",
    [
        "causes malignant-cell outcomes",
        "drives malignant-cell outcomes",
        "proves a mechanism",
        "demonstrates a mechanism",
        "establishes a mechanism",
        "mediates malignant-cell outcomes",
        "shows synergy",
        "shows a direct interaction",
        "directly interacts with a pathway",
        "interacts directly with a pathway",
        "has efficacy",
        "is an effective treatment",
    ],
)
def test_bounded_hypothesis_card_rejects_each_unsafe_claim_family(
    unsafe_claim: str,
) -> None:
    from src.agents.drug_target.ollama_hypothesis_cards import (
        parse_ollama_hypothesis_card,
        validate_ollama_hypothesis_card,
    )

    card, errors = parse_ollama_hypothesis_card(
        _bounded_card().replace(
            "in malignant cell context.",
            f"in malignant cell context and {unsafe_claim}.",
            1,
        )
    )

    assert errors == []
    assert card is not None
    assert "CORE_UNSAFE_CLAIM" in validate_ollama_hypothesis_card(
        card,
        spec=_mechanism_spec(),
    )


@pytest.mark.parametrize(
    "validation",
    [
        "Evaluate ERBB3 and EFNB2 perturbation with a generic primary assay and prespecified malignant-cell readouts.",
        "Evaluate ERBB3 and EFNB2 perturbation with a generic primary assay and matched controls.",
    ],
)
def test_bounded_hypothesis_card_requires_control_or_comparator_and_readout(
    validation: str,
) -> None:
    from src.agents.drug_target.ollama_hypothesis_cards import (
        parse_ollama_hypothesis_card,
        validate_ollama_hypothesis_card,
    )

    card, errors = parse_ollama_hypothesis_card(
        _bounded_card().replace(
            "Evaluate separate ERBB3 and EFNB2 perturbation with a generic primary assay, matched controls, and prespecified malignant-cell readouts.",
            validation,
        )
    )

    assert errors == []
    assert card is not None
    assert "VALIDATION_REQUIRED_TERMS" in validate_ollama_hypothesis_card(
        card,
        spec=_mechanism_spec(),
    )


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
    assert VALIDATION_FOCUS_BY_CATEGORY == {
        "Mechanism of Action": "Mechanistic follow-up",
        "Therapeutic Strategy": "Translational prioritization",
        "Cross-Target Interaction": "Pairwise context test",
        "Novel Pathway": "Orthogonal/novelty validation",
    }
    assert [spec["validation_focus"] for spec in specs] == list(
        VALIDATION_FOCUS_BY_CATEGORY.values()
    )
    assert validation_focus_for_category("unknown") == "Evidence-bound follow-up"


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

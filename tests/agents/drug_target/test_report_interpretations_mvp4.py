from __future__ import annotations

import asyncio
import shutil
from pathlib import Path


def _copy_baseline_workspace(tmp_path: Path) -> Path:
    fixture = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "baseline_hallucinated"
    )
    workspace = tmp_path / "workspace"
    shutil.copytree(fixture, workspace)
    return workspace


def test_report_interpretations_disabled_by_default(monkeypatch) -> None:
    from src.agents.drug_target.report_interpretations import (
        report_interpretations_enabled,
    )

    monkeypatch.delenv("DEEPMAST_ENABLE_REPORT_INTERPRETATIONS", raising=False)

    assert report_interpretations_enabled({}) is False


def test_report_interpretations_enabled_by_config(monkeypatch) -> None:
    from src.agents.drug_target.report_interpretations import (
        report_interpretations_enabled,
    )

    monkeypatch.delenv("DEEPMAST_ENABLE_REPORT_INTERPRETATIONS", raising=False)

    assert report_interpretations_enabled(
        {"configurable": {"enable_report_interpretations": True}}
    ) is True


def test_generate_interpretations_accepts_and_rejects_mock_provider(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data
    from src.agents.drug_target.report_interpretations import (
        generate_report_interpretations,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(str(workspace), "idiopathic pulmonary fibrosis")

    def provider(card):
        if card["id"] == "executive_summary.opportunities":
            return "FN1 anchors a deterministic opportunity in the 41-gene assessment."
        if card["id"] == "scoring_landscape":
            return "NINTEDANIB creates 99% unsupported benefit from fabricated.json."
        return ""

    payload, render_map = asyncio.run(
        generate_report_interpretations(report_data, provider=provider)
    )

    assert payload["schema_version"] == "drug_target.report_interpretations.v1"
    assert payload["summary"]["cards"] > 0
    assert payload["summary"]["accepted"] == 1
    assert payload["summary"]["rejected"] >= 1
    assert payload["summary"]["missing"] >= 1
    assert "executive_summary.opportunities" in payload["snippets"]
    accepted = payload["snippets"]["executive_summary.opportunities"]
    assert accepted["status"] == "accepted"
    assert accepted["text"].startswith("FN1 anchors")
    assert render_map["executive_summary_opportunities"].startswith("FN1 anchors")
    assert "scoring_landscape" not in render_map
    rejected = payload["snippets"]["scoring_landscape"]
    assert rejected["status"] == "rejected"
    assert {issue["code"] for issue in rejected["issues"]} >= {
        "UNSUPPORTED_ENTITY",
        "UNSUPPORTED_NUMBER",
        "UNSUPPORTED_SOURCE",
    }


def test_generate_interpretations_records_provider_error_with_card_id_key(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data
    from src.agents.drug_target.report_interpretations import (
        generate_report_interpretations,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(str(workspace), "idiopathic pulmonary fibrosis")

    def provider(card):
        if card["id"] == "executive_summary.opportunities":
            raise RuntimeError("provider unavailable")
        return ""

    payload, render_map = asyncio.run(
        generate_report_interpretations(report_data, provider=provider)
    )

    snippet = payload["snippets"]["executive_summary.opportunities"]
    assert snippet["status"] == "provider_error"
    assert snippet["issues"][0]["code"] == "INTERPRETATION_PROVIDER_ERROR"
    assert payload["summary"]["provider_errors"] == 1
    assert "executive_summary_opportunities" not in render_map


def test_generate_interpretations_accepts_async_provider(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data
    from src.agents.drug_target.report_interpretations import (
        generate_report_interpretations,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(str(workspace), "idiopathic pulmonary fibrosis")

    async def provider(card):
        if card["id"] == "executive_summary.opportunities":
            return "FN1 anchors a deterministic opportunity in the 41-gene assessment."
        return ""

    payload, render_map = asyncio.run(
        generate_report_interpretations(report_data, provider=provider)
    )

    assert payload["summary"]["accepted"] == 1
    assert render_map["executive_summary_opportunities"].startswith("FN1 anchors")


def test_build_interpretation_cards_include_existing_expand_slots(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data
    from src.agents.drug_target.report_interpretations import (
        build_interpretation_cards,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(
        str(workspace),
        "idiopathic pulmonary fibrosis",
    )

    cards = build_interpretation_cards(report_data)
    card_ids = {card["id"] for card in cards}

    assert "executive_summary.opportunities" in card_ids
    assert "scoring_landscape" in card_ids
    assert "stage1_filter.interpretation" in card_ids
    assert "hypotheses.overview" in card_ids
    assert "final_recommendations" in card_ids
    assert any(
        card_id.startswith("candidate.")
        and card_id.endswith(".drug_profile")
        for card_id in card_ids
    )
    assert any(
        card_id.startswith("candidate.")
        and card_id.endswith(".biological_context")
        for card_id in card_ids
    )
    assert any(
        card_id.startswith("candidate.")
        and card_id.endswith(".recommendation")
        for card_id in card_ids
    )
    assert any(
        card_id.startswith("hypothesis.")
        and card_id.endswith(".implication")
        for card_id in card_ids
    )

    executive = next(
        card
        for card in cards
        if card["id"] == "executive_summary.opportunities"
    )
    assert executive["kind"] == "section"
    assert "FN1" in executive["allowed_genes"]
    assert "evidence/assessment_results.json" in executive["allowed_sources"]
    assert executive["facts"]["disease"] == "idiopathic pulmonary fibrosis"


def test_validate_interpretation_accepts_allowed_entities() -> None:
    from src.agents.drug_target.report_interpretations import (
        validate_interpretation_text,
    )

    card = {
        "id": "executive_summary.opportunities",
        "allowed_genes": ["FN1", "MUC1"],
        "allowed_drugs": [],
        "allowed_numbers": ["41", "6", "2"],
        "allowed_sources": ["evidence/assessment_results.json"],
    }

    issues = validate_interpretation_text(
        card,
        (
            "FN1 and MUC1 define 2 prioritized adhesion targets in the "
            "deterministic matrix."
        ),
    )

    assert issues == []


def test_validate_interpretation_rejects_unsupported_claim_tokens() -> None:
    from src.agents.drug_target.report_interpretations import (
        validate_interpretation_text,
    )

    card = {
        "id": "executive_summary.opportunities",
        "allowed_genes": ["FN1"],
        "allowed_drugs": [],
        "allowed_numbers": ["41"],
        "allowed_sources": ["evidence/assessment_results.json"],
    }

    issues = validate_interpretation_text(
        card,
        (
            "NINTEDANIB improves 99% outcomes through TGFB2 according to "
            "fabricated.json."
        ),
    )

    assert {issue["code"] for issue in issues} >= {
        "UNSUPPORTED_ENTITY",
        "UNSUPPORTED_NUMBER",
        "UNSUPPORTED_SOURCE",
    }


def test_validate_interpretation_rejects_case_variant_entities_and_single_digit_claims() -> None:
    from src.agents.drug_target.report_interpretations import (
        validate_interpretation_text,
    )

    card = {
        "id": "executive_summary.opportunities",
        "allowed_genes": ["FN1"],
        "allowed_drugs": [],
        "allowed_numbers": ["41"],
        "allowed_sources": ["evidence/assessment_results.json"],
    }

    issues = validate_interpretation_text(
        card,
        "Nintedanib improves 3 outcomes through Tgfb2.",
    )

    assert {issue["code"] for issue in issues} >= {
        "UNSUPPORTED_ENTITY",
        "UNSUPPORTED_NUMBER",
    }


def test_validate_interpretation_allows_ordinary_sentence_initial_words() -> None:
    from src.agents.drug_target.report_interpretations import (
        validate_interpretation_text,
    )

    card = {
        "id": "executive_summary.opportunities",
        "allowed_genes": ["FN1"],
        "allowed_drugs": [],
        "allowed_numbers": [],
        "allowed_sources": ["evidence/assessment_results.json"],
    }

    issues = validate_interpretation_text(
        card,
        "These FN1 targets remain prioritized.",
    )

    assert issues == []


def test_validate_interpretation_allows_exact_multi_token_drug_names() -> None:
    from src.agents.drug_target.report_interpretations import (
        validate_interpretation_text,
    )

    card = {
        "id": "candidate.FN1.drug_profile",
        "allowed_genes": ["FN1"],
        "allowed_drugs": ["Chloropeptin I analogue"],
        "allowed_numbers": [],
        "allowed_sources": ["evidence/assessment_results.json"],
    }

    issues = validate_interpretation_text(
        card,
        "Chloropeptin I analogue remains listed as an allowed compound.",
    )

    assert issues == []

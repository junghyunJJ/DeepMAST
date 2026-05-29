from __future__ import annotations

import asyncio
import json
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


def test_resolve_interpretation_max_attempts_default(monkeypatch) -> None:
    from src.agents.drug_target.report_interpretations import (
        resolve_interpretation_max_attempts,
    )

    monkeypatch.delenv(
        "DEEPMAST_REPORT_INTERPRETATION_MAX_ATTEMPTS",
        raising=False,
    )

    assert resolve_interpretation_max_attempts({}) == 2


def test_resolve_interpretation_max_attempts_config_over_env(monkeypatch) -> None:
    from src.agents.drug_target.report_interpretations import (
        resolve_interpretation_max_attempts,
    )

    monkeypatch.setenv("DEEPMAST_REPORT_INTERPRETATION_MAX_ATTEMPTS", "5")

    assert (
        resolve_interpretation_max_attempts(
            {"configurable": {"report_interpretation_max_attempts": "4"}}
        )
        == 4
    )


def test_resolve_interpretation_max_attempts_env_cap_and_lower_clamp(
    monkeypatch,
) -> None:
    from src.agents.drug_target.report_interpretations import (
        resolve_interpretation_max_attempts,
    )

    monkeypatch.setenv("DEEPMAST_REPORT_INTERPRETATION_MAX_ATTEMPTS", "99")
    assert resolve_interpretation_max_attempts({}) == 5

    monkeypatch.setenv("DEEPMAST_REPORT_INTERPRETATION_MAX_ATTEMPTS", "0")
    assert resolve_interpretation_max_attempts({}) == 1


def test_resolve_interpretation_max_attempts_invalid_falls_back_to_default(
    monkeypatch,
) -> None:
    from src.agents.drug_target.report_interpretations import (
        resolve_interpretation_max_attempts,
    )

    monkeypatch.setenv("DEEPMAST_REPORT_INTERPRETATION_MAX_ATTEMPTS", "invalid")
    assert resolve_interpretation_max_attempts({}) == 2

    assert (
        resolve_interpretation_max_attempts(
            {"configurable": {"report_interpretation_max_attempts": object()}}
        )
        == 2
    )
    assert (
        resolve_interpretation_max_attempts(
            {"configurable": {"report_interpretation_max_attempts": True}}
        )
        == 2
    )


def test_build_interpretation_prompt_includes_style_and_allowed_terms() -> None:
    from src.agents.drug_target.report_interpretations import (
        build_interpretation_prompt,
    )

    card = {
        "id": "candidate.FN1.biological_context",
        "instruction": "Explain the Stage 1 biological rationale.",
        "allowed_genes": ["FN1"],
        "allowed_drugs": [],
        "allowed_numbers": [],
        "allowed_sources": ["evidence/stage1_FN1.json"],
        "allowed_terms": ["Stage 1", "biological context"],
        "facts": {"disease": "idiopathic pulmonary fibrosis", "gene": "FN1"},
    }

    prompt = build_interpretation_prompt(card)

    assert "Explain the Stage 1 biological rationale." in prompt
    assert "allowed_terms" in prompt
    assert "Stage 1" in prompt
    assert "Do not repeat the same sentence frame" in prompt


def test_build_interpretation_prompt_includes_repair_context() -> None:
    from src.agents.drug_target.report_interpretations import (
        build_interpretation_prompt,
    )

    card = {
        "id": "candidate.FN1.biological_context",
        "instruction": "Rewrite the previous rejected answer.",
        "allowed_genes": ["FN1"],
        "allowed_drugs": [],
        "allowed_numbers": [],
        "allowed_sources": ["evidence/stage1_FN1.json"],
        "allowed_terms": ["Stage 1"],
        "facts": {"disease": "idiopathic pulmonary fibrosis", "gene": "FN1"},
        "repair_context": {
            "previous_text": "Stage 9 makes FN1 decisive.",
            "issues": [
                {
                    "code": "UNSUPPORTED_NUMBER",
                    "number": "9",
                    "card_id": "candidate.FN1.biological_context",
                }
            ],
            "instruction": "Rewrite with a different sentence structure.",
        },
    }

    prompt = build_interpretation_prompt(card)

    assert "Previous text rejected by validator" in prompt
    assert "Stage 9 makes FN1 decisive." in prompt
    assert "UNSUPPORTED_NUMBER" in prompt
    assert "different sentence structure" in prompt


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
    assert accepted["stop_reason"] == "accepted"
    assert accepted["attempt_history"] == [
        {"attempt": 1, "status": "accepted", "issues": []}
    ]
    assert accepted["text"].startswith("FN1 anchors")
    assert render_map["executive_summary_opportunities"].startswith("FN1 anchors")
    assert "scoring_landscape" not in render_map
    rejected = payload["snippets"]["scoring_landscape"]
    assert rejected["status"] == "rejected"
    assert rejected["stop_reason"] == "max_attempts_exhausted"
    assert "text" not in rejected["attempt_history"][0]
    rejected_attempt_issues = rejected["attempt_history"][0]["issues"]
    assert {issue["code"] for issue in rejected_attempt_issues} >= {
        "UNSUPPORTED_ENTITY",
        "UNSUPPORTED_NUMBER",
        "UNSUPPORTED_SOURCE",
    }
    assert any(issue.get("number") == "99%" for issue in rejected_attempt_issues)
    assert any(
        issue.get("source") == "fabricated.json" for issue in rejected_attempt_issues
    )
    assert any(
        issue.get("token") == "NINTEDANIB" for issue in rejected_attempt_issues
    )
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
    assert snippet["stop_reason"] == "provider_error"
    assert snippet["attempt_history"] == [
        {
            "attempt": 1,
            "status": "provider_error",
            "issues": [
                {
                    "code": "INTERPRETATION_PROVIDER_ERROR",
                    "severity": "low",
                    "message": "provider unavailable",
                }
            ],
        }
    ]
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


def test_generate_interpretations_retries_rejected_text_with_repair_card(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data
    from src.agents.drug_target.report_interpretations import (
        generate_report_interpretations,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(str(workspace), "idiopathic pulmonary fibrosis")
    calls = []

    def provider(card):
        if card["id"] != "stage1_filter.interpretation":
            return ""
        calls.append(card)
        if "repair_context" in card:
            return "Stage 1 biological validation keeps FN1 grounded."
        return "Stage 9 biological validation keeps FN1 grounded."

    payload, render_map = asyncio.run(
        generate_report_interpretations(report_data, provider=provider)
    )

    snippet = payload["snippets"]["stage1_filter.interpretation"]
    assert snippet["status"] == "accepted"
    assert snippet["stop_reason"] == "accepted"
    assert snippet["attempts"] == 2
    assert snippet["attempt_history"] == [
        {
            "attempt": 1,
            "status": "rejected",
            "issues": [
                {
                    "code": "UNSUPPORTED_NUMBER",
                    "severity": "critical",
                    "message": "Unsupported numeric claim in interpretation: 9",
                    "number": "9",
                }
            ],
        },
        {"attempt": 2, "status": "accepted", "issues": []},
    ]
    assert payload["summary"]["accepted_after_retry"] == 1
    assert calls[1]["repair_context"]["previous_text"].startswith("Stage 9")
    assert calls[1]["repair_context"]["issues"][0]["code"] == "UNSUPPORTED_NUMBER"
    assert render_map["stage1_filter"] == (
        "Stage 1 biological validation keeps FN1 grounded."
    )


def test_generate_interpretations_accepts_after_attempt_four(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data
    from src.agents.drug_target.report_interpretations import (
        generate_report_interpretations,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(str(workspace), "idiopathic pulmonary fibrosis")
    calls = []

    def provider(card):
        if card["id"] != "stage1_filter.interpretation":
            return ""
        calls.append(card)
        if len(calls) == 4:
            return "Stage 1 biological validation keeps FN1 grounded."
        return "Stage 9 biological validation keeps FN1 grounded."

    payload, render_map = asyncio.run(
        generate_report_interpretations(
            report_data,
            provider=provider,
            max_attempts=4,
        )
    )

    snippet = payload["snippets"]["stage1_filter.interpretation"]
    assert snippet["status"] == "accepted"
    assert snippet["stop_reason"] == "accepted"
    assert snippet["attempts"] == 4
    assert len(snippet["attempt_history"]) == 4
    assert snippet["attempt_history"][-1] == {
        "attempt": 4,
        "status": "accepted",
        "issues": [],
    }
    assert payload["summary"]["accepted_after_retry"] == 1
    assert payload["summary"]["retry_exhausted"] == 0
    assert payload["summary"]["max_attempts_per_card"] == 4
    assert payload["summary"]["criteria_met"] is False
    assert len(calls) == 4
    assert render_map["stage1_filter"] == (
        "Stage 1 biological validation keeps FN1 grounded."
    )


def test_generate_interpretations_records_max_attempt_exhaustion(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data
    from src.agents.drug_target.report_interpretations import (
        generate_report_interpretations,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(str(workspace), "idiopathic pulmonary fibrosis")

    def provider(card):
        if card["id"] == "scoring_landscape":
            return "NINTEDANIB creates 99% unsupported benefit from fabricated.json."
        return ""

    payload, render_map = asyncio.run(
        generate_report_interpretations(
            report_data,
            provider=provider,
            max_attempts=3,
        )
    )

    snippet = payload["snippets"]["scoring_landscape"]
    assert snippet["status"] == "rejected"
    assert snippet["stop_reason"] == "max_attempts_exhausted"
    assert snippet["attempts"] == 3
    assert len(snippet["attempt_history"]) == 3
    assert all(
        attempt["status"] == "rejected"
        for attempt in snippet["attempt_history"]
    )
    assert all("text" not in attempt for attempt in snippet["attempt_history"])
    assert all(
        {issue["code"] for issue in attempt["issues"]}
        >= {"UNSUPPORTED_ENTITY", "UNSUPPORTED_NUMBER", "UNSUPPORTED_SOURCE"}
        for attempt in snippet["attempt_history"]
    )
    assert payload["summary"]["retry_exhausted"] == 1
    assert payload["summary"]["criteria_met"] is False
    assert "scoring_landscape" not in render_map


def test_generate_interpretations_sets_criteria_met_when_all_cards_accepted(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import build_report_data
    from src.agents.drug_target.report_interpretations import (
        generate_report_interpretations,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(str(workspace), "idiopathic pulmonary fibrosis")

    def provider(card):
        return "this report remains grounded."

    payload, render_map = asyncio.run(
        generate_report_interpretations(report_data, provider=provider)
    )

    assert payload["summary"]["accepted"] == payload["summary"]["cards"]
    assert payload["summary"]["criteria_met"] is True
    assert payload["summary"]["accepted_after_retry"] == 0
    assert payload["summary"]["retry_exhausted"] == 0
    assert render_map["executive_summary_opportunities"] == (
        "this report remains grounded."
    )


def test_generate_interpretations_rejects_lowercase_unsupported_entities(
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
            return "nintedanib may be relevant through tgfb2."
        return ""

    payload, render_map = asyncio.run(
        generate_report_interpretations(report_data, provider=provider)
    )

    snippet = payload["snippets"]["executive_summary.opportunities"]
    entity_tokens = {
        str(issue.get("token")).lower()
        for issue in snippet["issues"]
        if issue.get("code") == "UNSUPPORTED_ENTITY"
    }

    assert snippet["status"] == "rejected"
    assert {"nintedanib", "tgfb2"} <= entity_tokens
    assert "executive_summary_opportunities" not in render_map


def test_finalize_report_mvp_uses_configured_interpretation_attempts(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import finalize_report_mvp

    workspace = _copy_baseline_workspace(tmp_path)
    repaired_text = "Stage 1 biological validation keeps FN1 grounded."
    calls = []

    def provider(card):
        if card["id"] != "stage1_filter.interpretation":
            return ""
        calls.append(card)
        if len(calls) == 4:
            return repaired_text
        return "Stage 9 biological validation keeps FN1 grounded."

    result = asyncio.run(
        finalize_report_mvp(
            {
                "data_dir": str(workspace),
                "disease": "idiopathic pulmonary fibrosis",
                "report_finalization_error": None,
                "evidence_truncated": False,
            },
            {
                "configurable": {
                    "enable_report_interpretations": True,
                    "report_interpretation_provider": provider,
                    "report_interpretation_max_attempts": 4,
                }
            },
        )
    )

    assert result == {
        "report_finalization_error": None,
        "evidence_truncated": False,
    }
    assert len(calls) == 4
    markdown = (workspace / "drug.md").read_text(encoding="utf-8")
    payload = json.loads(
        (workspace / "report_interpretations.json").read_text(encoding="utf-8")
    )
    snippet = payload["snippets"]["stage1_filter.interpretation"]
    assert snippet["status"] == "accepted"
    assert snippet["attempts"] == 4
    assert payload["summary"]["max_attempts_per_card"] == 4
    assert repaired_text in markdown


def test_render_report_markdown_inserts_accepted_interpretations(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import (
        build_report_data,
        render_report_markdown,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(
        str(workspace),
        "idiopathic pulmonary fibrosis",
    )
    render_map = {
        "executive_summary_opportunities": (
            "Executive accepted snippet for FN1 and MUC1."
        ),
        "scoring_landscape": "Scoring landscape accepted snippet.",
        "stage1_filter": "Stage 1 filter accepted snippet.",
        "candidates": {
            "FN1": {
                "drug_profile": "FN1 drug profile accepted snippet.",
                "biological_context": "FN1 biology accepted snippet.",
                "recommendation": "FN1 recommendation accepted snippet.",
            }
        },
        "hypotheses_overview": "Hypotheses overview accepted snippet.",
        "hypotheses": {
            "1": {
                "implication": "Hypothesis 1 implication accepted snippet.",
            }
        },
        "final_recommendations": "Final recommendations accepted snippet.",
    }

    markdown = render_report_markdown(report_data, interpretations=render_map)

    assert "Executive accepted snippet for FN1 and MUC1." in markdown
    assert "Scoring landscape accepted snippet." in markdown
    assert "Stage 1 filter accepted snippet." in markdown
    assert "FN1 drug profile accepted snippet." in markdown
    assert "FN1 biology accepted snippet." in markdown
    assert "FN1 recommendation accepted snippet." in markdown
    assert "Hypotheses overview accepted snippet." in markdown
    assert "Hypothesis 1 implication accepted snippet." in markdown
    assert "Final recommendations accepted snippet." in markdown
    assert "EXPAND" not in markdown
    assert "_interpretations" not in report_data["candidates"][0]


def test_render_report_markdown_drops_non_string_top_level_interpretations(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import (
        build_report_data,
        render_report_markdown,
    )

    workspace = _copy_baseline_workspace(tmp_path)
    report_data = build_report_data(
        str(workspace),
        "idiopathic pulmonary fibrosis",
    )
    render_map = {
        "executive_summary_opportunities": {"bad": "dict"},
    }

    markdown = render_report_markdown(report_data, interpretations=render_map)

    assert "{'bad': 'dict'}" not in markdown
    assert "EXPAND" not in markdown


def test_drug_report_templates_are_byte_identical() -> None:
    skill_template = (
        Path(__file__).resolve().parents[3]
        / "skills"
        / "drug-target-reporting"
        / "templates"
        / "drug_report.md.j2"
    )
    package_template = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "agents"
        / "drug_target"
        / "templates"
        / "drug_report.md.j2"
    )

    assert skill_template.read_bytes() == package_template.read_bytes()


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


def test_build_interpretation_cards_include_type_specific_instructions_and_allowed_terms(
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
    drug_profile = next(
        card for card in cards if card["id"].endswith(".drug_profile")
    )
    biological_context = next(
        card for card in cards if card["id"].endswith(".biological_context")
    )
    recommendation = next(
        card for card in cards if card["id"].endswith(".recommendation")
    )
    hypothesis = next(
        card for card in cards if card["id"].startswith("hypothesis.")
    )
    scoring = next(card for card in cards if card["id"] == "scoring_landscape")

    assert "listed drugs" in drug_profile["instruction"]
    assert "biological rationale" in biological_context["instruction"]
    assert "actionable next step" in recommendation["instruction"]
    assert "therapeutic implication" in hypothesis["instruction"]
    assert len(
        {
            drug_profile["instruction"],
            biological_context["instruction"],
            recommendation["instruction"],
            hypothesis["instruction"],
        }
    ) == 4

    assert "Stage 1" in biological_context["allowed_terms"]
    assert "Stage 3" in recommendation["allowed_terms"]
    assert "validated track" in scoring["allowed_terms"]
    assert "exploratory track" in scoring["allowed_terms"]
    assert "validated track" not in biological_context["allowed_terms"]
    assert drug_profile["facts"]["candidate_kind"] == "featured candidate"
    assert "validated_total" in drug_profile["facts"]["scores"]


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


def test_validate_interpretation_rejects_lowercase_unsupported_entities() -> None:
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
        "nintedanib may be relevant through tgfb2.",
    )

    entity_tokens = {
        str(issue.get("token")).lower()
        for issue in issues
        if issue.get("code") == "UNSUPPORTED_ENTITY"
    }
    assert {"nintedanib", "tgfb2"} <= entity_tokens


def test_validate_interpretation_allows_case_variant_allowed_entities() -> None:
    from src.agents.drug_target.report_interpretations import (
        validate_interpretation_text,
    )

    card = {
        "id": "candidate.FN1.drug_profile",
        "allowed_genes": ["FN1"],
        "allowed_drugs": ["Nintedanib"],
        "allowed_numbers": [],
        "allowed_sources": ["evidence/assessment_results.json"],
    }

    issues = validate_interpretation_text(
        card,
        "fn1 and nintedanib remain listed in the deterministic card.",
    )

    assert issues == []


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


def test_validate_interpretation_allows_card_scoped_terms_with_numbers() -> None:
    from src.agents.drug_target.report_interpretations import (
        validate_interpretation_text,
    )

    card = {
        "id": "candidate.FN1.biological_context",
        "allowed_genes": ["FN1"],
        "allowed_drugs": [],
        "allowed_numbers": [],
        "allowed_sources": ["evidence/stage1_FN1.json"],
        "allowed_terms": ["Stage 1", "biological context"],
    }

    issues = validate_interpretation_text(
        card,
        "Stage 1 biological context keeps FN1 grounded in the report.",
    )

    assert issues == []


def test_validate_interpretation_rejects_unscoped_stage_numbers() -> None:
    from src.agents.drug_target.report_interpretations import (
        validate_interpretation_text,
    )

    card = {
        "id": "candidate.FN1.drug_profile",
        "allowed_genes": ["FN1"],
        "allowed_drugs": [],
        "allowed_numbers": [],
        "allowed_sources": ["evidence/assessment_results.json"],
        "allowed_terms": ["drug profile"],
    }

    issues = validate_interpretation_text(
        card,
        "Stage 3 drug profile keeps FN1 grounded in the report.",
    )

    assert any(
        issue["code"] == "UNSUPPORTED_NUMBER" and issue.get("number") == "3"
        for issue in issues
    )

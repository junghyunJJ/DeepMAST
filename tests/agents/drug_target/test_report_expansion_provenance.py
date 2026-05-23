from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.agents.drug_target.tools.report_expansion_schema import (
    EXPANSION_SCHEMA_SPEC_FILE,
    ReportExpansionsPayload,
    SlotItem,
    SentenceItem,
    SourceProvenance,
    canonical_json_hash,
    persist_drug_report_reference_card,
    save_report_expansions,
)


def _persist_reference(tmp_path: Path) -> str:
    ref = persist_drug_report_reference_card(
        tmp_path,
        {
            "markdown_template": "Intro\n\n<!-- EXPAND: Add summary -->\n",
            "expansion_slots": [
                {
                    "slot_id": "section:executive_summary|slot:add_summary",
                    "section": "executive_summary",
                    "slot": "add_summary",
                }
            ],
            "provenance_index": {
                "evidence/ot_CD4.json::clinical_drugs": {
                    "source_file": "evidence/ot_CD4.json",
                    "source_field": "clinical_drugs",
                    "source_class": "opentargets_clinical",
                    "source_value": ["ibalizumab"],
                },
                "evidence/stage3_CD4.json::preclinical_compounds": {
                    "source_file": "evidence/stage3_CD4.json",
                    "source_field": "preclinical_compounds",
                    "source_class": "chembl_preclinical",
                    "source_value": ["ibalizumab"],
                },
            },
        },
    )
    return canonical_json_hash(ref)


def _persist_reference_with_index(tmp_path: Path) -> str:
    ref = persist_drug_report_reference_card(
        tmp_path,
        {
            "markdown_template": "Intro\n\n<!-- EXPAND: Add summary -->\n",
            "expansion_slots": [
                {
                    "slot_id": "section:executive_summary|slot:add_summary",
                    "section": "executive_summary",
                    "slot": "add_summary",
                }
            ],
            "provenance_index": {
                "evidence/ot_CD4.json::clinical_drugs": {
                    "source_file": "evidence/ot_CD4.json",
                    "source_field": "clinical_drugs",
                    "source_class": "opentargets_clinical",
                    "source_value": ["ibalizumab"],
                }
            },
        },
    )
    return canonical_json_hash(ref)


def _base_expansion(reference_hash: str, sentence: dict) -> dict:
    return {
        "schema_version": "report_expansions.v1",
        "template_id": "drug_report.md.j2",
        "reference_card_hash": reference_hash,
        "slots": [
            {
                "slot_id": "section:executive_summary|slot:add_summary",
                "section_id": "executive_summary",
                "sentences": [sentence],
            }
        ],
    }


def test_false_absence_claim_rejected_when_source_value_non_empty(tmp_path: Path) -> None:
    reference_hash = _persist_reference(tmp_path)
    sentence = {
        "text": "Clinical compounds are not available in source data.",
        "source_fields": ["clinical_drugs"],
        "source_provenance": {
            "source_file": "evidence/ot_CD4.json",
            "source_field": "clinical_drugs",
            "source_class": "opentargets_clinical",
            "source_value": ["ibalizumab"],
            "claim_type": "absence",
        },
        "interpretation": False,
        "hedging_verbs_present": False,
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _base_expansion(reference_hash, sentence)}
        )
    )

    assert result["saved"] is False
    assert any(err["code"] == "FALSE_ABSENCE_CLAIM" for err in result["errors"])


def test_source_class_conflation_is_rejected(tmp_path: Path) -> None:
    reference_hash = _persist_reference(tmp_path)
    sentence = {
        "text": "The OpenTargets clinical compounds include ibalizumab.",
        "source_fields": ["preclinical_compounds"],
        "source_provenance": {
            "source_file": "evidence/stage3_CD4.json",
            "source_field": "preclinical_compounds",
            "source_class": "opentargets_clinical",
            "source_value": ["ibalizumab"],
            "claim_type": "direct_value",
        },
        "interpretation": False,
        "hedging_verbs_present": False,
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _base_expansion(reference_hash, sentence)}
        )
    )

    assert result["saved"] is False
    assert any(err["code"] == "SOURCE_PROVENANCE_MISMATCH" for err in result["errors"])


def test_generic_clinical_drugs_source_tag_is_rejected(tmp_path: Path) -> None:
    reference_hash = _persist_reference(tmp_path)
    sentence = {
        "text": "The OpenTargets clinical compounds include ibalizumab. [source: clinical_drugs]",
        "source_fields": ["clinical_drugs"],
        "source_provenance": {
            "source_file": "evidence/ot_CD4.json",
            "source_field": "clinical_drugs",
            "source_class": "opentargets_clinical",
            "source_value": ["ibalizumab"],
            "claim_type": "direct_value",
        },
        "interpretation": False,
        "hedging_verbs_present": False,
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _base_expansion(reference_hash, sentence)}
        )
    )

    assert result["saved"] is False
    assert any(err["code"] == "SOURCE_TAG_TOO_GENERIC" for err in result["errors"])


def test_wrong_class_qualified_source_tag_is_rejected(tmp_path: Path) -> None:
    reference_hash = _persist_reference(tmp_path)
    sentence = {
        "text": (
            "The OpenTargets clinical compounds include ibalizumab. "
            "[source: chembl_preclinical:clinical_drugs]"
        ),
        "source_fields": ["clinical_drugs"],
        "source_provenance": {
            "source_file": "evidence/ot_CD4.json",
            "source_field": "clinical_drugs",
            "source_class": "opentargets_clinical",
            "source_value": ["ibalizumab"],
            "claim_type": "direct_value",
        },
        "interpretation": False,
        "hedging_verbs_present": False,
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _base_expansion(reference_hash, sentence)}
        )
    )

    assert result["saved"] is False
    assert any(err["code"] == "SOURCE_TAG_PROVENANCE_MISMATCH" for err in result["errors"])


def test_false_absence_uses_reference_card_provenance_index(tmp_path: Path) -> None:
    reference_hash = _persist_reference_with_index(tmp_path)
    sentence = {
        "text": "Clinical compounds are not available in source data.",
        "source_fields": ["clinical_drugs"],
        "source_provenance": {
            "source_file": "evidence/ot_CD4.json",
            "source_field": "clinical_drugs",
            "source_class": "opentargets_clinical",
            "source_value": [],
            "claim_type": "absence",
        },
        "interpretation": False,
        "hedging_verbs_present": False,
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _base_expansion(reference_hash, sentence)}
        )
    )

    assert result["saved"] is False
    assert any(err["code"] == "FALSE_ABSENCE_CLAIM" for err in result["errors"])


def test_missing_provenance_index_entry_is_rejected(tmp_path: Path) -> None:
    reference_hash = _persist_reference_with_index(tmp_path)
    sentence = {
        "text": "MUC1 compounds are not available in source data.",
        "source_fields": ["clinical_drugs"],
        "source_provenance": {
            "source_file": "evidence/ot_MUC1.json",
            "source_field": "clinical_drugs",
            "source_class": "opentargets_clinical",
            "source_value": [],
            "claim_type": "absence",
        },
        "interpretation": False,
        "hedging_verbs_present": False,
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _base_expansion(reference_hash, sentence)}
        )
    )

    assert result["saved"] is False
    assert any(err["code"] == "SOURCE_PROVENANCE_MISSING" for err in result["errors"])


def test_count_claim_must_match_reference_card_source_value(tmp_path: Path) -> None:
    reference_hash = _persist_reference_with_index(tmp_path)
    sentence = {
        "text": "CD4 has 2 clinical compounds.",
        "source_fields": ["clinical_drugs"],
        "source_provenance": {
            "source_file": "evidence/ot_CD4.json",
            "source_field": "clinical_drugs",
            "source_class": "opentargets_clinical",
            "source_value": 2,
            "claim_type": "count",
        },
        "interpretation": False,
        "hedging_verbs_present": False,
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _base_expansion(reference_hash, sentence)}
        )
    )

    assert result["saved"] is False
    assert any(err["code"] == "SOURCE_PROVENANCE_MISMATCH" for err in result["errors"])


def test_direct_value_must_match_reference_card_source_value(tmp_path: Path) -> None:
    reference_hash = _persist_reference_with_index(tmp_path)
    sentence = {
        "text": "CD4 clinical compounds include fabricated-drug.",
        "source_fields": ["clinical_drugs"],
        "source_provenance": {
            "source_file": "evidence/ot_CD4.json",
            "source_field": "clinical_drugs",
            "source_class": "opentargets_clinical",
            "source_value": ["fabricated-drug"],
            "claim_type": "direct_value",
        },
        "interpretation": False,
        "hedging_verbs_present": False,
    }

    result = json.loads(
        save_report_expansions.invoke(
            {"data_dir": str(tmp_path), "expansions": _base_expansion(reference_hash, sentence)}
        )
    )

    assert result["saved"] is False
    assert any(err["code"] == "SOURCE_PROVENANCE_MISMATCH" for err in result["errors"])


def test_reference_card_routes_clinical_and_preclinical_sources_by_origin(tmp_path: Path) -> None:
    card = persist_drug_report_reference_card(
        tmp_path,
        {
            "markdown_template": "Intro\n\n<!-- EXPAND: Add summary -->\n",
            "featured_genes": [
                {
                    "gene": "CD4",
                    "stage3": {
                        "clinical_drugs": ["ibalizumab"],
                        "preclinical_compounds": ["CHEMBL123"],
                    },
                }
            ],
        },
    )

    index = card["provenance_index"]
    assert index["evidence/ot_CD4.json::clinical_drugs"] == {
        "source_file": "evidence/ot_CD4.json",
        "source_field": "clinical_drugs",
        "source_class": "opentargets_clinical",
        "source_value": ["ibalizumab"],
    }
    assert index["evidence/stage3_CD4.json::preclinical_compounds"] == {
        "source_file": "evidence/stage3_CD4.json",
        "source_field": "preclinical_compounds",
        "source_class": "chembl_preclinical",
        "source_value": ["CHEMBL123"],
    }
    assert "evidence/stage3_CD4.json::clinical_drugs" not in index


# =============================================================================
# finalize_report node — 7 behaviour tests (Phase 4a task #17)
# =============================================================================
#
# These tests exercise finalize_report() directly, mocking the LLM boundary
# and using tmp_path for filesystem isolation.  They do NOT mock
# validate_report_expansions (fixture-driven reference card instead).


def _make_reference_card(tmp_path: Path) -> dict:
    """Write a minimal reference card and return the loaded dict.

    Uses featured_genes so _build_provenance_index produces the correct key
    ``evidence/ot_CD4.json::clinical_drugs`` used by validate_cited_only_provenance.
    """
    return persist_drug_report_reference_card(
        tmp_path,
        {
            "markdown_template": "Intro\n\n<!-- EXPAND: Add summary -->\n",
            "expansion_slots": [
                {
                    "slot_id": "section:executive_summary|slot:add_summary",
                    "section": "executive_summary",
                    "slot": "add_summary",
                }
            ],
            "featured_genes": [
                {
                    "gene": "CD4",
                    "stage3": {
                        "clinical_drugs": ["ibalizumab"],
                        "preclinical_compounds": [],
                    },
                }
            ],
        },
    )


def _make_valid_payload() -> ReportExpansionsPayload:
    """Return a ReportExpansionsPayload that passes schema + cited-only checks."""
    return ReportExpansionsPayload(
        schema_version="report_expansions.v1",
        slots=[
            SlotItem(
                slot_id="section:executive_summary|slot:add_summary",
                sentences=[
                    SentenceItem(
                        text="CD4 has ibalizumab as a clinical drug.",
                        source_fields=["clinical_drugs"],
                        source_provenance=SourceProvenance(
                            source_file="evidence/ot_CD4.json",
                            source_field="clinical_drugs",
                            source_class="opentargets_clinical",
                            claim_type="direct_value",
                            source_value=["ibalizumab"],
                        ),
                    )
                ],
            )
        ],
    )


def _make_bad_provenance_payload() -> ReportExpansionsPayload:
    """Payload whose sentence cites a key NOT in the reference_card index."""
    return ReportExpansionsPayload(
        schema_version="report_expansions.v1",
        slots=[
            SlotItem(
                slot_id="section:executive_summary|slot:add_summary",
                sentences=[
                    SentenceItem(
                        text="FABRICATED_DRUG is a clinical drug.",
                        source_fields=["clinical_drugs"],
                        source_provenance=SourceProvenance(
                            source_file="evidence/ot_FAKE.json",
                            source_field="clinical_drugs",
                            source_class="opentargets_clinical",
                            claim_type="direct_value",
                            source_value=["FABRICATED_DRUG"],
                        ),
                    )
                ],
            )
        ],
    )


def _write_minimal_workspace(tmp_path: Path) -> None:
    """Write lr_candidates.json + evidence dir so load_evidence_files succeeds."""
    (tmp_path / "lr_candidates.json").write_text(
        json.dumps({"disease": "test disease", "pairs": []}), encoding="utf-8"
    )
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": []}), encoding="utf-8"
    )


def _make_state(tmp_path: Path) -> dict:
    return {"data_dir": str(tmp_path), "disease": "test disease"}


def _make_ot_payload(
    gene: str,
    *,
    evidence_count: int,
    association_count: int,
    drug_count: int,
) -> dict:
    return {
        "gene_symbol": gene,
        "disease": "test disease",
        "executed": True,
        "ensembl_id": f"ENSG_{gene}",
        "target_info": {
            "id": f"ENSG_{gene}",
            "approvedSymbol": gene,
            "approvedName": f"{gene} test target",
            "biotype": "protein_coding",
            "functionDescriptions": [
                f"{gene} function description " + ("x" * 200)
            ],
            "tractability": [
                {"modality": "SM", "id": f"tractability_{i}", "value": i % 2 == 0}
                for i in range(8)
            ],
            "safetyLiabilities": [
                {"event": f"safety_{i}", "datasource": "ToxCast"}
                for i in range(2)
            ],
        },
        "disease_evidence": [
            {
                "datasourceId": "europepmc",
                "datatypeId": "literature",
                "score": float(evidence_count - i),
                "studyId": None,
                "literature": [str(10_000 + i)],
            }
            for i in range(evidence_count)
        ],
        "associations": [
            {
                "disease": {"id": f"EFO_{i}", "name": f"association disease {i}"},
                "score": float(association_count - i),
                "datatypeScores": [{"id": "literature", "score": 1.0}],
            }
            for i in range(association_count)
        ],
        "target_drugs": {
            "count": drug_count,
            "rows": [
                {
                    "maxClinicalStage": i % 5,
                    "drug": {
                        "id": f"CHEMBL{i}",
                        "name": f"drug_{i}",
                        "maximumClinicalStage": i % 5,
                    },
                    "diseases": [
                        {
                            "diseaseFromSource": f"drug disease {i}",
                            "disease": {"id": f"MONDO_{i}", "name": f"drug disease {i}"},
                        }
                    ],
                }
                for i in range(drug_count)
            ],
        },
        "associations_total_count": association_count,
        "associations_truncated": association_count > 3,
        "disease_evidence_truncated": evidence_count > 3,
        "errors": [],
    }


def test_compact_evidence_preserves_featured_ot_payload() -> None:
    from src.agents.drug_target.finalize_report import _compact_evidence_for_budget

    featured_payload = _make_ot_payload("MUC1", evidence_count=5, association_count=5, drug_count=5)
    nonfeatured_payload = _make_ot_payload("TGFB1", evidence_count=6, association_count=6, drug_count=4)
    evidence = {"files": {"ot_MUC1.json": featured_payload, "ot_TGFB1.json": nonfeatured_payload}}
    reference_card = {"stage3_candidates": ["MUC1"], "featured_genes": [{"gene": "MUC1"}]}

    compacted = _compact_evidence_for_budget(evidence, reference_card, top_n=3)

    assert compacted["files"]["ot_MUC1.json"] == featured_payload
    compact_tgfb1 = compacted["files"]["ot_TGFB1.json"]
    assert compact_tgfb1["_compact_schema"] == "drug_target.ot_per_target_summary.v1"
    assert compact_tgfb1["_source_file"] == "evidence/ot_TGFB1.json"
    assert compact_tgfb1["counts"]["disease_evidence"] == 6
    assert compact_tgfb1["counts"]["associations_loaded"] == 6
    assert compact_tgfb1["counts"]["target_drugs"] == 4
    assert len(compact_tgfb1["top_disease_evidence"]) == 3
    assert len(compact_tgfb1["top_associations"]) == 3
    assert len(compact_tgfb1["top_target_drugs"]) == 3
    assert "_source_hash" in compact_tgfb1
    assert "_original_token_estimate" in compact_tgfb1


def test_compact_evidence_reduces_nonfeatured_ot_tokens() -> None:
    from src.agents.drug_target.finalize_report import (
        _compact_evidence_for_budget,
        _estimate_json_tokens,
    )

    nonfeatured_payload = _make_ot_payload("TGFB1", evidence_count=20, association_count=20, drug_count=10)
    evidence = {"files": {"ot_TGFB1.json": nonfeatured_payload}}
    reference_card = {"stage3_candidates": []}

    compacted = _compact_evidence_for_budget(evidence, reference_card, top_n=3)

    assert _estimate_json_tokens(compacted) < _estimate_json_tokens(evidence)


@pytest.mark.asyncio
async def test_finalize_report_compacts_large_nonfeatured_ot_before_budget_gate(tmp_path: Path, monkeypatch) -> None:
    import src.agents.drug_target.finalize_report as mod

    _write_minimal_workspace(tmp_path)
    reference_card = {"stage3_candidates": ["MUC1"], "featured_genes": [{"gene": "MUC1"}]}
    valid_payload = _make_valid_payload()

    monkeypatch.setattr(mod, "_TOKEN_BUDGET", 2_500)

    evidence = {
        "files": {
            "ot_MUC1.json": _make_ot_payload("MUC1", evidence_count=2, association_count=2, drug_count=2),
            "ot_TGFB1.json": _make_ot_payload("TGFB1", evidence_count=80, association_count=80, drug_count=20),
        }
    }

    with (
        patch("src.agents.drug_target.finalize_report._load_expansion_inputs", return_value=(evidence, {}, reference_card)),
        patch("src.agents.model.create_llm") as mock_llm,
        patch("src.agents.drug_target.finalize_report._persist_and_validate", return_value=[]),
        patch("src.agents.drug_target.finalize_report._render_outputs"),
        patch("src.agents.drug_target.finalize_report._finalize_workspace", return_value=[]),
    ):
        mock_model = MagicMock()
        mock_model.bind.return_value = mock_model
        structured = MagicMock()
        structured.with_retry.return_value = structured
        structured.invoke.return_value = valid_payload
        mock_model.with_structured_output.return_value = structured
        mock_llm.return_value = mock_model

        result = await mod.finalize_report_legacy(_make_state(tmp_path), config={})

    assert result["report_finalization_error"] is None
    mock_model.with_structured_output.assert_called_once()


@pytest.mark.asyncio
async def test_finalize_report_fails_closed_after_compaction_if_still_over_budget(tmp_path: Path, monkeypatch) -> None:
    import src.agents.drug_target.finalize_report as mod

    _write_minimal_workspace(tmp_path)
    reference_card = {"stage3_candidates": []}
    monkeypatch.setattr(mod, "_TOKEN_BUDGET", 200)

    evidence = {
        "files": {
            "ot_TGFB1.json": _make_ot_payload("TGFB1", evidence_count=80, association_count=80, drug_count=20),
        },
        "uncompactable": "x" * 5_000,
    }

    with (
        patch("src.agents.drug_target.finalize_report._load_expansion_inputs", return_value=(evidence, {}, reference_card)),
        patch("src.agents.model.create_llm") as mock_llm,
    ):
        mock_model = MagicMock()
        mock_model.bind.return_value = mock_model
        mock_llm.return_value = mock_model

        result = await mod.finalize_report_legacy(_make_state(tmp_path), config={})

    assert result["report_finalization_error"].startswith("evidence_budget_exceeded:")
    assert result["evidence_truncated"] is True
    mock_model.with_structured_output.assert_not_called()


# ---------------------------------------------------------------------------
# Test 1 — Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_report_happy_path_writes_artifacts(tmp_path: Path) -> None:
    """finalize_report writes drug.md, HTML, and target_assessment.json on success."""
    _write_minimal_workspace(tmp_path)
    _make_reference_card(tmp_path)

    valid_payload = _make_valid_payload()

    with (
        patch(
            "src.agents.drug_target.finalize_report._call_tool",
            side_effect=_mock_call_tool_factory(tmp_path, valid_payload),
        ),
        patch("src.agents.model.create_llm") as mock_llm,
    ):
        mock_model = MagicMock()
        mock_model.bind.return_value = mock_model
        structured = MagicMock()
        structured.with_retry.return_value = structured
        structured.invoke.return_value = valid_payload
        mock_model.with_structured_output.return_value = structured
        mock_llm.return_value = mock_model

        from src.agents.drug_target.finalize_report import (
            finalize_report_legacy as finalize_report,
        )

        result = await finalize_report(_make_state(tmp_path), config={})

    assert result["report_finalization_error"] is None
    assert result["evidence_truncated"] is False


def _mock_call_tool_factory(tmp_path: Path, payload: ReportExpansionsPayload):
    """Return a side_effect function that simulates tool calls."""
    from src.agents.drug_target.finalize_report import (
        _load_evidence_files_st,
        _save_report_expansions_st,
        _render_drug_md_st,
        _generate_drug_html_st,
        _finalize_stage1_st,
        _validate_finalization_st,
    )

    def _side_effect(tool, **kwargs):
        if tool is _load_evidence_files_st:
            return json.dumps({"files": {}, "contrast_evidence": {}})
        if tool is _save_report_expansions_st:
            return json.dumps({"saved": True, "errors": []})
        if tool is _render_drug_md_st:
            (tmp_path / "drug.md").write_text("# Report\nNo placeholders.\n", encoding="utf-8")
            return json.dumps({"rendered": True})
        if tool is _generate_drug_html_st:
            (tmp_path / "drug_report.html").write_text("<html></html>", encoding="utf-8")
            return json.dumps({"generated": True})
        if tool is _finalize_stage1_st:
            return json.dumps({"success": True})
        if tool is _validate_finalization_st:
            return json.dumps({"valid": True, "issue_count": 0, "issues": []})
        return json.dumps({})

    return _side_effect


# ---------------------------------------------------------------------------
# Test 2 — Schema validation failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_report_schema_validation_failure_sets_error(tmp_path: Path) -> None:
    """When validate_report_expansions returns errors, report_finalization_error is set
    and no disk artifacts are written."""
    _write_minimal_workspace(tmp_path)
    # Write a reference card WITHOUT the required slot so schema validation fails
    persist_drug_report_reference_card(
        tmp_path,
        {
            "markdown_template": "<!-- EXPAND: Add summary -->",
            "expansion_slots": [
                {"slot_id": "section:other|slot:something", "section": "other", "slot": "something"}
            ],
            "provenance_index": {},
        },
    )

    # Payload has wrong schema_version to force schema error
    bad_payload = ReportExpansionsPayload(
        schema_version="report_expansions.v1",
        slots=[
            SlotItem(
                slot_id="section:executive_summary|slot:add_summary",
                sentences=[
                    SentenceItem(
                        text="A sentence.",
                        source_fields=["clinical_drugs"],
                        source_provenance=SourceProvenance(
                            source_file="evidence/ot_CD4.json",
                            source_field="clinical_drugs",
                            source_class="opentargets_clinical",
                        ),
                    )
                ],
            )
        ],
    )
    # Mangle the schema_version at dict level so validate_report_expansions rejects it
    bad_dump = bad_payload.model_dump()
    bad_dump["schema_version"] = "wrong_version"

    with (
        patch(
            "src.agents.drug_target.finalize_report._call_tool",
            side_effect=_mock_call_tool_factory(tmp_path, bad_payload),
        ),
        patch("src.agents.model.create_llm") as mock_llm,
        patch(
            "src.agents.drug_target.finalize_report.validate_report_expansions",
            return_value=(None, [{"code": "REPORT_EXPANSIONS_INVALID", "message": "bad version"}]),
        ),
    ):
        mock_model = MagicMock()
        mock_model.bind.return_value = mock_model
        structured = MagicMock()
        structured.with_retry.return_value = structured
        structured.invoke.return_value = bad_payload
        mock_model.with_structured_output.return_value = structured
        mock_llm.return_value = mock_model

        from src.agents.drug_target.finalize_report import (
            finalize_report_legacy as finalize_report,
        )

        result = await finalize_report(_make_state(tmp_path), config={})

    assert result["report_finalization_error"] is not None
    # Either schema or cited_only gate may fire first — both block artifacts.
    # Under BUG-1 fix, cited_only wins when the payload also fails provenance check
    # (the reference card here has provenance_index: {} so the key is absent).
    error = result["report_finalization_error"]
    assert error.startswith("validation_failed:") or error.startswith("cited_only_violation:"), (
        f"Expected validation or cited-only error prefix, got: {error!r}"
    )
    # No disk artifacts written
    assert not (tmp_path / "drug.md").exists()
    assert not (tmp_path / "drug_report.html").exists()
    assert not (tmp_path / "target_assessment.json").exists()


# ---------------------------------------------------------------------------
# Test 3 — LLM retry exhaust
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_report_llm_retry_exhaust_sets_error(tmp_path: Path) -> None:
    """When _llm_fill_expansions_once exhausts retries, report_finalization_error
    is set to llm_call_failed_after_retries and no disk artifacts are written."""
    _write_minimal_workspace(tmp_path)
    _make_reference_card(tmp_path)

    with (
        patch(
            "src.agents.drug_target.finalize_report._call_tool",
            side_effect=_mock_call_tool_factory(tmp_path, _make_valid_payload()),
        ),
        patch("src.agents.model.create_llm") as mock_llm,
    ):
        mock_model = MagicMock()
        mock_model.bind.return_value = mock_model
        structured = MagicMock()
        retried = MagicMock()
        retried.invoke.side_effect = Exception("provider timeout")
        structured.with_retry.return_value = retried
        mock_model.with_structured_output.return_value = structured
        mock_llm.return_value = mock_model

        from src.agents.drug_target.finalize_report import (
            finalize_report_legacy as finalize_report,
        )

        result = await finalize_report(_make_state(tmp_path), config={})

    assert result["report_finalization_error"] is not None
    assert result["report_finalization_error"].startswith("llm_call_failed_after_retries:")
    assert not (tmp_path / "drug.md").exists()
    assert not (tmp_path / "drug_report.html").exists()
    assert not (tmp_path / "target_assessment.json").exists()


# ---------------------------------------------------------------------------
# Test 4 — Cited-only step: bad provenance → no disk artifacts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_report_cited_only_violation_blocks_artifacts(tmp_path: Path) -> None:
    """A payload with a fabricated evidence key sets a validation error and leaves
    4 disk artifacts absent.

    Schema validation (validate_report_expansions) runs before cited-only validation
    and also rejects an unknown source file, so the error starts with
    ``validation_failed:`` (schema) rather than ``cited_only_violation:`` when both
    checks catch the same unknown key.  The important invariant is that
    report_finalization_error is set and no artifacts are written.
    """
    _write_minimal_workspace(tmp_path)
    _make_reference_card(tmp_path)

    bad_payload = _make_bad_provenance_payload()

    with (
        patch(
            "src.agents.drug_target.finalize_report._call_tool",
            side_effect=_mock_call_tool_factory(tmp_path, bad_payload),
        ),
        patch("src.agents.model.create_llm") as mock_llm,
    ):
        mock_model = MagicMock()
        mock_model.bind.return_value = mock_model
        structured = MagicMock()
        structured.with_retry.return_value = structured
        structured.invoke.return_value = bad_payload
        mock_model.with_structured_output.return_value = structured
        mock_llm.return_value = mock_model

        from src.agents.drug_target.finalize_report import (
            finalize_report_legacy as finalize_report,
        )

        result = await finalize_report(_make_state(tmp_path), config={})

    assert result["report_finalization_error"] is not None
    # Schema validator fires first (SOURCE_PROVENANCE_MISSING) → validation_failed:
    # Cited-only validator also catches the unknown key → both signals present
    error = result["report_finalization_error"]
    assert error.startswith("validation_failed:") or error.startswith("cited_only_violation:"), (
        f"Expected validation or cited-only error prefix, got: {error!r}"
    )
    # 4 artifacts must be absent regardless of which validator fired first
    assert not (tmp_path / "drug.md").exists()
    assert not (tmp_path / "drug_report.html").exists()
    assert not (tmp_path / "target_assessment.json").exists()
    assert not (tmp_path / "report_expansions.json").exists()


# ---------------------------------------------------------------------------
# Test 5 — Cited-only pass + render
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_report_well_cited_payload_renders_artifacts(tmp_path: Path) -> None:
    """A well-cited payload passes validation and triggers render step,
    leaving report_finalization_error as None."""
    _write_minimal_workspace(tmp_path)
    _make_reference_card(tmp_path)

    valid_payload = _make_valid_payload()

    with (
        patch(
            "src.agents.drug_target.finalize_report._call_tool",
            side_effect=_mock_call_tool_factory(tmp_path, valid_payload),
        ),
        patch("src.agents.model.create_llm") as mock_llm,
    ):
        mock_model = MagicMock()
        mock_model.bind.return_value = mock_model
        structured = MagicMock()
        structured.with_retry.return_value = structured
        structured.invoke.return_value = valid_payload
        mock_model.with_structured_output.return_value = structured
        mock_llm.return_value = mock_model

        from src.agents.drug_target.finalize_report import (
            finalize_report_legacy as finalize_report,
        )

        result = await finalize_report(_make_state(tmp_path), config={})

    assert result["report_finalization_error"] is None
    assert result["evidence_truncated"] is False


# ---------------------------------------------------------------------------
# Test 6 — Evidence budget exceeded (fail-closed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_report_evidence_budget_exceeded_no_llm_call(tmp_path: Path) -> None:
    """When evidence JSON exceeds _TOKEN_BUDGET tokens, finalize_report sets
    evidence_budget_exceeded, evidence_truncated=True, makes NO LLM call, and
    writes no disk artifacts."""
    from src.agents.drug_target.finalize_report import _TOKEN_BUDGET

    _write_minimal_workspace(tmp_path)
    _make_reference_card(tmp_path)

    # Patch _load_expansion_inputs to return an evidence dict above the budget.
    large_evidence = {"data": "x" * (_TOKEN_BUDGET * 4 + 100)}  # > budget token estimate

    with (
        patch(
            "src.agents.drug_target.finalize_report._load_expansion_inputs",
            return_value=(large_evidence, {}, {}),
        ),
        patch("src.agents.model.create_llm") as mock_llm,
    ):
        mock_model = MagicMock()
        mock_model.bind.return_value = mock_model
        mock_llm.return_value = mock_model

        from src.agents.drug_target.finalize_report import (
            finalize_report_legacy as finalize_report,
        )

        result = await finalize_report(_make_state(tmp_path), config={})

    assert result["report_finalization_error"] is not None
    assert result["report_finalization_error"].startswith("evidence_budget_exceeded:")
    assert result["evidence_truncated"] is True
    # No LLM call
    mock_model.with_structured_output.assert_not_called()
    # No disk artifacts
    assert not (tmp_path / "drug.md").exists()
    assert not (tmp_path / "drug_report.html").exists()
    assert not (tmp_path / "target_assessment.json").exists()


# ---------------------------------------------------------------------------
# Test 7 — No short-circuit: regenerate even when drug.md exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_report_regenerates_when_drug_md_exists(tmp_path: Path) -> None:
    """A prior-run drug.md must NOT short-circuit finalization. finalize_report
    always proceeds to the LLM call so a reused workspace with different input
    cannot silently return stale results (Codex PR #32 P1)."""
    _write_minimal_workspace(tmp_path)
    _make_reference_card(tmp_path)
    # Pre-create drug.md to simulate a previous run with DIFFERENT input
    (tmp_path / "drug.md").write_text("# Stale prior-run report\n", encoding="utf-8")

    with patch("src.agents.model.create_llm") as mock_llm:
        mock_model = MagicMock()
        mock_model.bind.return_value = mock_model
        mock_llm.return_value = mock_model

        from src.agents.drug_target.finalize_report import (
            finalize_report_legacy as finalize_report,
        )

        await finalize_report(_make_state(tmp_path), config={})

    # The guard is gone: the LLM step is reached even though drug.md pre-exists.
    mock_model.with_structured_output.assert_called()

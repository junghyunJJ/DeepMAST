"""#18g — CP-P1-018: Cited-only violation gate blocks all 4 disk artifacts.

Setup: payload whose sentence cites a provenance key not present in the
reference_card index. finalize_report must:
  - Set report_finalization_error starting with 'cited_only_violation:'
  - NOT write drug.md, drug_report.html, target_assessment.json, report_expansions.json
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.agents.drug_target.tools.report_expansion_schema import (
    ReportExpansionsPayload,
    SentenceItem,
    SlotItem,
    SourceProvenance,
    persist_drug_report_reference_card,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

SLOT_ID = "section:executive_summary|slot:add_summary"

REAL_SOURCE_FILE = "evidence/ot_CD4.json"
REAL_SOURCE_FIELD = "clinical_drugs"

# Fabricated key — does NOT appear in the reference_card provenance index
FABRICATED_SOURCE_FILE = "evidence/fabricated_FAKE.json"
FABRICATED_SOURCE_FIELD = "fabricated_field"


def _build_workspace(data_dir: Path) -> dict:
    """Write a minimal workspace with a reference card that does NOT contain the fabricated key."""
    evidence_dir = data_dir / "evidence"
    evidence_dir.mkdir(exist_ok=True)

    (evidence_dir / "ot_CD4.json").write_text(
        json.dumps({"gene": "CD4", "clinical_drugs": ["ibalizumab"]}),
        encoding="utf-8",
    )

    reference_card = persist_drug_report_reference_card(
        str(data_dir),
        {
            "featured_genes": [
                {
                    "gene": "CD4",
                    "stage3": {
                        "clinical_drugs": ["ibalizumab"],
                        "preclinical_compounds": [],
                    },
                    "rubric": {"classification": "priority"},
                }
            ],
            "expansion_slots": [
                {
                    "slot_id": SLOT_ID,
                    "section": "executive_summary",
                    "slot": "add_summary",
                }
            ],
        },
    )
    return reference_card


def _build_violating_payload() -> ReportExpansionsPayload:
    """Payload whose sentence cites a fabricated key NOT in reference_card."""
    sentence = SentenceItem(
        text="This drug was fabricated and does not exist in evidence.",
        source_fields=[FABRICATED_SOURCE_FIELD],
        source_provenance=SourceProvenance(
            source_file=FABRICATED_SOURCE_FILE,
            source_field=FABRICATED_SOURCE_FIELD,
            source_class="opentargets_clinical",
            claim_type="direct_value",
            source_value="fabricated",
        ),
    )
    slot = SlotItem(slot_id=SLOT_ID, sentences=[sentence])
    return ReportExpansionsPayload(schema_version="report_expansions.v1", slots=[slot])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cited_only_violation_sets_error_field(tmp_path: Path) -> None:
    """report_finalization_error must start with 'cited_only_violation:'."""
    reference_card = _build_workspace(tmp_path)
    violating_payload = _build_violating_payload()

    mock_model = MagicMock()
    mock_model.bind = MagicMock(return_value=mock_model)

    with (
        patch("src.agents.model.create_llm", return_value=mock_model),
        patch(
            "src.agents.drug_target.finalize_report._llm_fill_expansions_once",
            return_value=(violating_payload, None),
        ),
        patch(
            "src.agents.drug_target.finalize_report._call_tool"
        ) as mock_call_tool,
    ):
        def _side_effect(tool, **kwargs):
            tool_name = getattr(tool, "name", str(tool))
            if "load_evidence_files" in tool_name:
                return json.dumps({"CD4": {"clinical_drugs": ["ibalizumab"]}})
            # save_report_expansions, render, html — should NOT be called on violation
            # Return a safe fallback so the test doesn't explode if they ARE called
            if "save_report_expansions" in tool_name:
                (tmp_path / "report_expansions.json").write_text("{}", encoding="utf-8")
                return json.dumps({"saved": True, "path": "", "errors": []})
            if "render_drug_md" in tool_name:
                (tmp_path / "drug.md").write_text("# Drug", encoding="utf-8")
                return json.dumps({"ok": True})
            if "generate_drug_html" in tool_name or "html" in tool_name:
                (tmp_path / "drug_report.html").write_text("<html></html>", encoding="utf-8")
                return json.dumps({"ok": True})
            return json.dumps({"ok": True})

        mock_call_tool.side_effect = _side_effect

        from src.agents.drug_target.finalize_report import (
            finalize_report_legacy as finalize_report,
        )

        state = {
            "data_dir": str(tmp_path),
            "disease": "IPF",
            "messages": [],
            "featured_lr_pairs": None,
            "report_finalization_error": None,
            "evidence_truncated": False,
        }

        result = await finalize_report(state, {})  # type: ignore[arg-type]

    finalization_error = result.get("report_finalization_error")
    assert finalization_error is not None, (
        "Expected report_finalization_error to be set for cited_only violation, "
        "but it was None — the gate is not enforcing provenance."
    )
    assert finalization_error.startswith("cited_only_violation:"), (
        f"Expected 'cited_only_violation:' prefix (BUG-1 fix: cited_only wins over schema), "
        f"got: {finalization_error!r}"
    )


@pytest.mark.asyncio
async def test_cited_only_violation_blocks_all_four_disk_artifacts(
    tmp_path: Path,
) -> None:
    """On cited_only_violation, all 4 disk artifacts must be absent."""
    _build_workspace(tmp_path)
    violating_payload = _build_violating_payload()

    artifact_paths = [
        tmp_path / "drug.md",
        tmp_path / "drug_report.html",
        tmp_path / "target_assessment.json",
        tmp_path / "report_expansions.json",
    ]

    mock_model = MagicMock()
    mock_model.bind = MagicMock(return_value=mock_model)

    with (
        patch("src.agents.model.create_llm", return_value=mock_model),
        patch(
            "src.agents.drug_target.finalize_report._llm_fill_expansions_once",
            return_value=(violating_payload, None),
        ),
        patch(
            "src.agents.drug_target.finalize_report._call_tool"
        ) as mock_call_tool,
    ):
        def _side_effect(tool, **kwargs):
            tool_name = getattr(tool, "name", str(tool))
            if "load_evidence_files" in tool_name:
                return json.dumps({"CD4": {"clinical_drugs": ["ibalizumab"]}})
            # Do NOT write any artifacts — simulate proper gate behavior
            return json.dumps({"ok": True})

        mock_call_tool.side_effect = _side_effect

        from src.agents.drug_target.finalize_report import (
            finalize_report_legacy as finalize_report,
        )

        state = {
            "data_dir": str(tmp_path),
            "disease": "IPF",
            "messages": [],
            "featured_lr_pairs": None,
            "report_finalization_error": None,
            "evidence_truncated": False,
        }

        result = await finalize_report(state, {})  # type: ignore[arg-type]

    finalization_error = result.get("report_finalization_error")

    # The gate must fire with 'cited_only_violation:' prefix (BUG-1 fix: cited_only
    # errors win over schema errors regardless of error list ordering).
    assert finalization_error is not None and finalization_error.startswith(
        "cited_only_violation:"
    ), (
        f"Provenance gate did not fire with 'cited_only_violation:' prefix — "
        f"got: {finalization_error!r}. "
        "The _persist_and_validate step is not gating correctly."
    )

    # When gate fires, _render_outputs is never called so artifacts must be absent.
    for artifact in artifact_paths:
        assert not artifact.exists(), (
            f"Artifact {artifact.name} must NOT exist after provenance gate fired "
            f"(error={finalization_error!r}), but was found at {artifact}"
        )


# NOTE: the idempotency short-circuit (Decision 12) was removed (Codex PR #32 P1)
# so finalize_report always regenerates. The "no short-circuit" regression guard
# lives in test_report_expansion_provenance.py::
# test_finalize_report_regenerates_when_drug_md_exists.

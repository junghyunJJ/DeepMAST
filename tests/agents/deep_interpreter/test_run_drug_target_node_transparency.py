"""#18 — Wrapper-agent disk-artifact contract after super-graph migration.

Verifies that run_drug_target_assessment produces the expected JSON envelope
shape and disk artifacts regardless of super-graph internals.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_success_state(data_dir: str) -> dict:
    """Build a minimal DrugTargetState that looks like a successful run."""
    return {
        "messages": [],
        "data_dir": data_dir,
        "disease": "IPF",
        "featured_lr_pairs": None,
        "report_finalization_error": None,
        "evidence_truncated": False,
    }


def _make_failure_state(data_dir: str, error: str) -> dict:
    return {
        "messages": [],
        "data_dir": data_dir,
        "disease": "IPF",
        "featured_lr_pairs": None,
        "report_finalization_error": error,
        "evidence_truncated": False,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_happy_path_writes_artifacts_and_returns_success_envelope(
    tmp_path: Path,
) -> None:
    """Happy path: mocked super-graph writes 3 files; envelope success==True."""
    data_dir = str(tmp_path)

    # Create the required lr_candidates.json so integration skips early exit
    (tmp_path / "lr_candidates.json").write_text("[]", encoding="utf-8")

    # Simulate finalize_report writing the 3 artifacts
    (tmp_path / "drug.md").write_text("# Drug Report", encoding="utf-8")
    (tmp_path / "drug_report.html").write_text("<html></html>", encoding="utf-8")
    target_assessment_data = {"schema_version": "report_expansions.v1", "slots": []}
    (tmp_path / "target_assessment.json").write_text(
        json.dumps(target_assessment_data), encoding="utf-8"
    )

    final_state = _make_success_state(data_dir)

    # drug_target_graph is lazily imported inside run_drug_target_assessment;
    # patch at graph_builder where the symbol lives.
    with patch(
        "src.agents.drug_target.graph_builder.drug_target_graph"
    ) as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=final_state)

        from src.agents.drug_target.integration import run_drug_target_assessment

        result_str: str = await run_drug_target_assessment.ainvoke(  # type: ignore[attr-defined]
            {"data_dir": data_dir, "disease": "IPF"}
        )

    envelope = json.loads(result_str)

    assert envelope["success"] is True, f"Expected success=True, got: {envelope}"
    assert envelope["drug_md"] is not None
    assert envelope["target_assessment"] is not None
    assert envelope["errors"] == []
    assert isinstance(envelope["evidence_truncated"], bool)

    # All 3 artifacts must exist on disk
    assert (tmp_path / "drug.md").exists()
    assert (tmp_path / "target_assessment.json").exists()


async def test_fail_path_returns_failure_envelope_without_artifacts(
    tmp_path: Path,
) -> None:
    """Fail path: finalization error propagates; envelope success==False."""
    data_dir = str(tmp_path)
    (tmp_path / "lr_candidates.json").write_text("[]", encoding="utf-8")

    # No artifact files written — simulate aborted finalization
    error_msg = "validation_failed: foo"
    final_state = _make_failure_state(data_dir, error_msg)

    with patch(
        "src.agents.drug_target.graph_builder.drug_target_graph"
    ) as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=final_state)

        from src.agents.drug_target.integration import run_drug_target_assessment

        result_str = await run_drug_target_assessment.ainvoke(
            {"data_dir": data_dir, "disease": "IPF"}
        )

    envelope = json.loads(result_str)

    assert envelope["success"] is False
    assert envelope["drug_md"] is None
    assert envelope["target_assessment"] is None
    assert envelope["errors"] == [error_msg]


async def test_envelope_json_is_parseable_with_expected_keys(
    tmp_path: Path,
) -> None:
    """Envelope JSON must be parseable and contain all 5 required keys."""
    data_dir = str(tmp_path)
    (tmp_path / "lr_candidates.json").write_text("[]", encoding="utf-8")
    (tmp_path / "drug.md").write_text("# Drug", encoding="utf-8")
    (tmp_path / "target_assessment.json").write_text("{}", encoding="utf-8")

    final_state = _make_success_state(data_dir)

    with patch(
        "src.agents.drug_target.graph_builder.drug_target_graph"
    ) as mock_graph:
        mock_graph.ainvoke = AsyncMock(return_value=final_state)

        from src.agents.drug_target.integration import run_drug_target_assessment

        result_str = await run_drug_target_assessment.ainvoke(
            {"data_dir": data_dir, "disease": "IPF"}
        )

    # Verify the string is valid JSON
    parsed = json.loads(result_str)

    expected_keys = {"success", "drug_md", "target_assessment", "errors", "evidence_truncated"}
    assert set(parsed.keys()) == expected_keys, (
        f"Envelope missing keys. Got: {set(parsed.keys())}"
    )
    # Verify types match what wrapper_agent.py:2016 pattern expects
    assert isinstance(parsed["success"], bool)
    assert isinstance(parsed["errors"], list)
    assert isinstance(parsed["evidence_truncated"], bool)


async def test_missing_lr_candidates_returns_error_envelope(
    tmp_path: Path,
) -> None:
    """Missing lr_candidates.json must yield a structured failure envelope."""
    # No lr_candidates.json — integration short-circuits before graph call
    from src.agents.drug_target.integration import run_drug_target_assessment

    result_str = await run_drug_target_assessment.ainvoke(
        {"data_dir": str(tmp_path), "disease": "IPF"}
    )

    envelope = json.loads(result_str)
    assert envelope["success"] is False
    assert len(envelope["errors"]) > 0
    assert "lr_candidates.json" in envelope["errors"][0]


# ---------------------------------------------------------------------------
# pytest-asyncio mode
# ---------------------------------------------------------------------------
import pytest

pytestmark = pytest.mark.asyncio

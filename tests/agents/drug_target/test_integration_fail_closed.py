"""Integration tests verifying the fail-closed contract end-to-end through
run_drug_target_assessment.

The deep agent and finalize_stage1_workspace are mocked so no LLM/network
calls are made. validate_drug_report_finalization is NOT mocked — it runs
against the real on-disk fixture files to exercise the full host-side gate.

Fixtures under tests/agents/drug_target/fixtures/:
  clean/                    — passes all validator checks
  markdown_table_pipe_drift/ — defect: MARKDOWN_TABLE_PIPE_DRIFT
"""

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

FIXTURE_ROOT = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _copy_fixture(name: str, dst_root: Path) -> Path:
    """Copy fixture directory tree into dst_root and return dst_root."""
    src = FIXTURE_ROOT / name
    shutil.copytree(src, dst_root)
    return dst_root


def _make_mock_agent(fixture_dir: Path):
    """Return a mock agent whose ainvoke copies fixture files into the run dir.

    The mock simulates the deep agent writing outputs by symlinking (via copy)
    the fixture's drug.md and target_assessment.json into the run dir.
    The fixture files are already present (copied by _copy_fixture), so the
    mock ainvoke is a no-op — the files are already at the right place.
    """
    mock_agent = MagicMock()

    async def mock_ainvoke(input_dict, config=None):
        # Files already exist because _copy_fixture placed them in fixture_dir.
        return {"messages": []}

    mock_agent.ainvoke = mock_ainvoke
    return mock_agent


# Stage1 success result — mirrors the shape finalize_stage1_workspace returns.
_STAGE1_SUCCESS = {
    "success": True,
    "post_validation": {
        "valid": True,
        "errors": [],
        "missing_csv_files": [],
    },
}


# ---------------------------------------------------------------------------
# Test 1: summarizer claims PASS but finalization validator rejects on-disk file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summarizer_pass_but_finalization_fails(tmp_path):
    """Agent returns success-shaped state but drug.md has MARKDOWN_TABLE_PIPE_DRIFT.

    The host-side gate must catch this and return success=False even though
    the agent itself did not report a failure.
    """
    run_dir = tmp_path / "run"
    _copy_fixture("markdown_table_pipe_drift", run_dir)

    from src.agents.drug_target.integration import run_drug_target_assessment

    mock_agent = _make_mock_agent(run_dir)

    with patch(
        "src.agents.drug_target.agent.create_drug_target_agent",
        return_value=(mock_agent, None),
    ), patch(
        "src.agents.drug_target.integration.finalize_stage1_workspace",
        return_value=_STAGE1_SUCCESS,
    ):
        raw = await run_drug_target_assessment.ainvoke(
            {"data_dir": str(run_dir), "disease": "ipf"}
        )

    result = json.loads(raw)

    assert result["success"] is False
    assert result["drug_md"] is None
    assert result["drug_md_path"] is not None
    assert Path(result["drug_md_path"]).exists()
    assert result["finalization_validation"]["valid"] is False
    assert len(result["finalization_validation"]["issues"]) > 0
    assert any(
        issue["code"] == "MARKDOWN_TABLE_PIPE_DRIFT"
        for issue in result["finalization_validation"]["issues"]
    )
    assert "errors" in result


# ---------------------------------------------------------------------------
# Test 2: clean fixture passes finalization gate end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clean_fixture_passes_finalization(tmp_path, monkeypatch):
    """Clean fixture passes finalization validator — success=True, drug_md populated."""
    run_dir = tmp_path / "run"
    _copy_fixture("clean", run_dir)
    monkeypatch.setenv("DEEPMAST_ALLOW_LEGACY_DRUG_MD", "1")

    from src.agents.drug_target.integration import run_drug_target_assessment

    mock_agent = _make_mock_agent(run_dir)

    with patch(
        "src.agents.drug_target.agent.create_drug_target_agent",
        return_value=(mock_agent, None),
    ), patch(
        "src.agents.drug_target.integration.finalize_stage1_workspace",
        return_value=_STAGE1_SUCCESS,
    ):
        raw = await run_drug_target_assessment.ainvoke(
            {"data_dir": str(run_dir), "disease": "ipf"}
        )

    result = json.loads(raw)

    assert result["success"] is True
    assert result["drug_md"] is not None
    assert result["finalization_validation"]["valid"] is True
    assert result["finalization_validation"]["issue_count"] == 0
    assert "stage1_validation" in result


# ---------------------------------------------------------------------------
# Test 3: defective drug.md is NOT deleted on failure (MR2 contract)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drug_md_file_not_deleted_on_failure(tmp_path):
    """On fail-closed rejection the on-disk drug.md must remain unchanged."""
    run_dir = tmp_path / "run"
    _copy_fixture("markdown_table_pipe_drift", run_dir)

    # Capture original content before the run.
    defective_content = (FIXTURE_ROOT / "markdown_table_pipe_drift" / "drug.md").read_text()

    from src.agents.drug_target.integration import run_drug_target_assessment

    mock_agent = _make_mock_agent(run_dir)

    with patch(
        "src.agents.drug_target.agent.create_drug_target_agent",
        return_value=(mock_agent, None),
    ), patch(
        "src.agents.drug_target.integration.finalize_stage1_workspace",
        return_value=_STAGE1_SUCCESS,
    ):
        raw = await run_drug_target_assessment.ainvoke(
            {"data_dir": str(run_dir), "disease": "ipf"}
        )

    result = json.loads(raw)
    assert result["success"] is False

    drug_md_path = run_dir / "drug.md"
    assert drug_md_path.exists(), "drug.md must not be deleted on failure"
    assert drug_md_path.read_text() == defective_content, (
        "drug.md content must be unchanged on failure"
    )

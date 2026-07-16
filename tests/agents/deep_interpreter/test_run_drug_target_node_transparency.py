"""Wrapper-facing disk-artifact contract for the direct guarded agent."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_success_artifacts(
    data_dir: Path,
    *,
    publication_status: str = "passed",
) -> None:
    artifacts = {
        "drug.md": "# Drug Report\n",
        "target_assessment.json": json.dumps({"schema_version": "report.v1"}),
        "report_sections.json": json.dumps({"schema_version": "hybrid_report_sections/v1"}),
        "part4_candidate_selection.json": json.dumps({"selected_lr_pairs": []}),
        "part4_therapeutic_synthesis.md": "# Part 4\n",
        "drug_report.html": "<html></html>",
        "drug_report_validation_initial.json": json.dumps(
            {"valid": True, "publication": {"status": "passed"}}
        ),
        "drug_report_validation_final.json": json.dumps(
            {"valid": True, "publication": {"status": publication_status}}
        ),
    }
    for name, content in artifacts.items():
        (data_dir / name).write_text(content, encoding="utf-8")


def _patch_direct_agent(monkeypatch: pytest.MonkeyPatch, invoke) -> None:
    class Backend:
        def cleanup(self) -> None:
            pass

    class Agent:
        async def ainvoke(self, _payload, config=None):
            return await invoke()

    monkeypatch.setattr(
        "src.agents.drug_target.agent.create_drug_target_agent",
        lambda _config: (Agent(), Backend()),
    )


@pytest.mark.asyncio
async def test_happy_path_writes_artifacts_and_returns_success_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "lr_candidates.json").write_text("[]", encoding="utf-8")

    async def invoke():
        _write_success_artifacts(tmp_path)
        return {"messages": []}

    _patch_direct_agent(monkeypatch, invoke)
    from src.agents.drug_target.integration import run_drug_target_assessment

    envelope = json.loads(
        await run_drug_target_assessment.ainvoke(
            {"data_dir": str(tmp_path), "disease": "IPF"}
        )
    )

    assert envelope["success"] is True
    assert envelope["drug_md"] == "# Drug Report\n"
    assert envelope["target_assessment"] == {"schema_version": "report.v1"}
    assert envelope["errors"] == []
    assert envelope["evidence_truncated"] is False


@pytest.mark.asyncio
async def test_failed_publication_is_not_wrapper_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "lr_candidates.json").write_text("[]", encoding="utf-8")

    async def invoke():
        _write_success_artifacts(tmp_path, publication_status="failed")
        return {"messages": []}

    _patch_direct_agent(monkeypatch, invoke)
    from src.agents.drug_target.integration import run_drug_target_assessment

    envelope = json.loads(
        await run_drug_target_assessment.ainvoke(
            {"data_dir": str(tmp_path), "disease": "IPF"}
        )
    )

    assert envelope["success"] is False
    assert envelope["drug_md"] is None
    assert envelope["target_assessment"] is None
    assert envelope["errors"]


@pytest.mark.asyncio
async def test_missing_lr_candidates_returns_error_envelope(tmp_path: Path) -> None:
    from src.agents.drug_target.integration import run_drug_target_assessment

    envelope = json.loads(
        await run_drug_target_assessment.ainvoke(
            {"data_dir": str(tmp_path), "disease": "IPF"}
        )
    )

    assert envelope["success"] is False
    assert "lr_candidates.json" in envelope["errors"][0]

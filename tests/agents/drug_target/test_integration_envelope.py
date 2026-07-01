"""#20c — CP-P0-008: Integration envelope shape invariant.

Tests that run_drug_target_assessment always returns a JSON string whose keys
and types match the documented contract, for both success and failure paths.

Failure paths are parametrized across the 5 error class prefixes.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


EXPECTED_KEYS = {"success", "drug_md", "target_assessment", "errors", "evidence_truncated"}

ERROR_PREFIXES = [
    "validation_failed",
    "llm_call_failed_after_retries",
    "cited_only_violation",
    "evidence_budget_exceeded",
    "finalization_validation_failed",
]


def _make_success_state(data_dir: str) -> dict:
    return {
        "messages": [],
        "data_dir": data_dir,
        "disease": "IPF",
        "featured_lr_pairs": None,
        "report_finalization_error": None,
        "evidence_truncated": False,
    }


def _make_failure_state(data_dir: str, error_msg: str) -> dict:
    return {
        "messages": [],
        "data_dir": data_dir,
        "disease": "IPF",
        "featured_lr_pairs": None,
        "report_finalization_error": error_msg,
        "evidence_truncated": False,
    }


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_envelope_shape_invariant_success_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Success envelope has exact keys and correct types."""
    data_dir = str(tmp_path)
    (tmp_path / "lr_candidates.json").write_text("[]", encoding="utf-8")
    (tmp_path / "drug.md").write_text("# Drug", encoding="utf-8")
    assessment_content = {"schema_version": "report_expansions.v1", "slots": []}
    (tmp_path / "target_assessment.json").write_text(
        json.dumps(assessment_content), encoding="utf-8"
    )

    final_state = _make_success_state(data_dir)
    original_read_text = Path.read_text
    read_threads: list[str] = []

    def tracking_read_text(path_self, *args, **kwargs):
        if path_self.name in {"drug.md", "target_assessment.json"}:
            read_threads.append(threading.current_thread().name)
        return original_read_text(path_self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracking_read_text)

    with patch("src.agents.drug_target.graph_builder.drug_target_graph") as mock_g:
        mock_g.ainvoke = AsyncMock(return_value=final_state)

        from src.agents.drug_target.integration import run_drug_target_assessment

        result_str = await run_drug_target_assessment.ainvoke(
            {"data_dir": data_dir, "disease": "IPF"}
        )

    envelope = json.loads(result_str)

    # Key set must be exact
    assert set(envelope.keys()) == EXPECTED_KEYS, (
        f"Unexpected keys: {set(envelope.keys()) - EXPECTED_KEYS} / "
        f"Missing keys: {EXPECTED_KEYS - set(envelope.keys())}"
    )

    # Type assertions
    assert isinstance(envelope["success"], bool)
    assert isinstance(envelope["drug_md"], str)
    assert isinstance(envelope["target_assessment"], dict)
    assert isinstance(envelope["errors"], list)
    assert isinstance(envelope["evidence_truncated"], bool)

    # Value assertions for success path
    assert envelope["success"] is True
    assert envelope["errors"] == []
    assert len(read_threads) == 2
    assert threading.main_thread().name not in read_threads


# ---------------------------------------------------------------------------
# Failure path — parametrized across 5 error prefixes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("error_prefix", ERROR_PREFIXES)
async def test_envelope_shape_invariant_failure_path(
    tmp_path: Path, error_prefix: str
) -> None:
    """Failure envelope has exact keys and correct types for each error class."""
    data_dir = str(tmp_path)
    (tmp_path / "lr_candidates.json").write_text("[]", encoding="utf-8")

    error_msg = f"{error_prefix}: some detail"
    final_state = _make_failure_state(data_dir, error_msg)

    with patch("src.agents.drug_target.graph_builder.drug_target_graph") as mock_g:
        mock_g.ainvoke = AsyncMock(return_value=final_state)

        from src.agents.drug_target.integration import run_drug_target_assessment

        result_str = await run_drug_target_assessment.ainvoke(
            {"data_dir": data_dir, "disease": "IPF"}
        )

    envelope = json.loads(result_str)

    # Key set must be exact
    assert set(envelope.keys()) == EXPECTED_KEYS, (
        f"[{error_prefix}] Unexpected/missing keys: got {set(envelope.keys())}"
    )

    # Type assertions
    assert isinstance(envelope["success"], bool)
    assert isinstance(envelope["errors"], list)
    assert isinstance(envelope["evidence_truncated"], bool)

    # Value assertions for failure path
    assert envelope["success"] is False
    assert envelope["drug_md"] is None
    assert envelope["target_assessment"] is None
    assert len(envelope["errors"]) >= 1, "errors list must not be empty on failure"
    assert envelope["errors"][0].startswith(error_prefix), (
        f"Expected errors[0] to start with {error_prefix!r}, "
        f"got {envelope['errors'][0]!r}"
    )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evidence_truncated_propagates_to_envelope(tmp_path: Path) -> None:
    """evidence_truncated from final state must appear verbatim in envelope."""
    data_dir = str(tmp_path)
    (tmp_path / "lr_candidates.json").write_text("[]", encoding="utf-8")

    final_state = {
        "messages": [],
        "data_dir": data_dir,
        "disease": "IPF",
        "featured_lr_pairs": None,
        "report_finalization_error": "evidence_budget_exceeded: 99999 > 20000",
        "evidence_truncated": True,
    }

    with patch("src.agents.drug_target.graph_builder.drug_target_graph") as mock_g:
        mock_g.ainvoke = AsyncMock(return_value=final_state)

        from src.agents.drug_target.integration import run_drug_target_assessment

        result_str = await run_drug_target_assessment.ainvoke(
            {"data_dir": data_dir, "disease": "IPF"}
        )

    envelope = json.loads(result_str)
    assert envelope["evidence_truncated"] is True
    assert envelope["success"] is False

"""TC-T17: Verify write_critic_slices is called at summarizer-start.

The summarizer subagent wrapper must:
1. Call write_critic_slices(data_dir) before invoking the inner agent.
2. Call cleanup_critic_slices(data_dir) in a finally block after the agent returns.
3. KEEP the slices (not clean up) when OMB_CRITIC_SLICES_KEEP=1 is set.

No live LLM is required — the DeepAgent is replaced with a no-op stub.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.agents.drug_target.subagents.summarizer.agent import (
    wrap_summarizer_with_critic_slices,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evidence_dir(tmp_path: Path) -> str:
    """Create a minimal evidence directory with the files write_critic_slices needs."""
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    # stage3_TGFB1.json — triggers one gene slice
    stage3 = {
        "gene": "TGFB1",
        "matched_drugs": [],
        "preclinical_compounds": [],
    }
    (evidence_dir / "stage3_TGFB1.json").write_text(json.dumps(stage3))

    # resolved_drugs.json
    resolved = [
        {
            "gene": "TGFB1",
            "chembl_id": "CHEMBL999",
            "resolved_name": "FAKE_DRUG",
            "molecule_type": "Small molecule",
            "max_phase": 2,
            "source": "opentargets",
        }
    ]
    (evidence_dir / "resolved_drugs.json").write_text(json.dumps(resolved))

    # hypothesis_report.json
    hyp = [
        {
            "hypothesis": "TGFB1 drives fibrosis.",
            "entities": ["TGFB1"],
        }
    ]
    (evidence_dir / "hypothesis_report.json").write_text(json.dumps(hyp))

    return str(tmp_path)


def _make_stub_agent() -> MagicMock:
    """Return a no-op Runnable stub that records invoke calls."""
    stub = MagicMock(spec=["invoke", "with_config"])
    stub.with_config.return_value = stub
    stub.invoke.return_value = {"messages": []}
    return stub


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_slices_written_before_invoke(tmp_path: Path) -> None:
    """Slice files must exist on disk BEFORE the inner agent's invoke is called."""
    data_dir = _make_evidence_dir(tmp_path)

    written_during_invoke: dict[str, bool] = {}

    stub = MagicMock(spec=["invoke", "with_config"])
    stub.with_config.return_value = stub

    def _check_slices(input: Any, *args: Any, **kwargs: Any) -> dict:  # noqa: A002
        slices_dir = Path(data_dir) / "evidence" / "_critic_slices"
        written_during_invoke["tgfb1"] = (slices_dir / "TGFB1.json").exists()
        written_during_invoke["hypothesis"] = (slices_dir / "_hypothesis.json").exists()
        return {"messages": []}

    stub.invoke.side_effect = _check_slices

    wrapped = wrap_summarizer_with_critic_slices(stub, data_dir=data_dir)
    wrapped.invoke({"messages": []})

    assert written_during_invoke.get("tgfb1"), (
        "evidence/_critic_slices/TGFB1.json must exist before inner agent invoke"
    )
    assert written_during_invoke.get("hypothesis"), (
        "evidence/_critic_slices/_hypothesis.json must exist before inner agent invoke"
    )


def test_slices_cleaned_up_after_invoke(tmp_path: Path) -> None:
    """Slices must be removed after invoke when OMB_CRITIC_SLICES_KEEP is unset."""
    data_dir = _make_evidence_dir(tmp_path)

    stub = _make_stub_agent()
    wrapped = wrap_summarizer_with_critic_slices(stub, data_dir=data_dir)

    env_before = os.environ.pop("OMB_CRITIC_SLICES_KEEP", None)
    try:
        wrapped.invoke({"messages": []})
    finally:
        if env_before is not None:
            os.environ["OMB_CRITIC_SLICES_KEEP"] = env_before

    slices_dir = Path(data_dir) / "evidence" / "_critic_slices"
    assert not slices_dir.exists(), (
        "_critic_slices directory must be removed after invoke when "
        "OMB_CRITIC_SLICES_KEEP is unset"
    )


def test_slices_kept_when_env_flag_set(tmp_path: Path) -> None:
    """Slices must be KEPT after invoke when OMB_CRITIC_SLICES_KEEP=1."""
    data_dir = _make_evidence_dir(tmp_path)

    stub = _make_stub_agent()
    wrapped = wrap_summarizer_with_critic_slices(stub, data_dir=data_dir)

    os.environ["OMB_CRITIC_SLICES_KEEP"] = "1"
    try:
        wrapped.invoke({"messages": []})
    finally:
        del os.environ["OMB_CRITIC_SLICES_KEEP"]

    slices_dir = Path(data_dir) / "evidence" / "_critic_slices"
    assert slices_dir.exists(), (
        "_critic_slices directory must be kept when OMB_CRITIC_SLICES_KEEP=1"
    )
    assert (slices_dir / "TGFB1.json").exists()
    assert (slices_dir / "_hypothesis.json").exists()


def test_slices_cleaned_up_even_when_agent_raises(tmp_path: Path) -> None:
    """cleanup_critic_slices must run even if the inner agent raises."""
    data_dir = _make_evidence_dir(tmp_path)

    stub = MagicMock(spec=["invoke", "with_config"])
    stub.with_config.return_value = stub
    stub.invoke.side_effect = RuntimeError("agent exploded")

    wrapped = wrap_summarizer_with_critic_slices(stub, data_dir=data_dir)

    env_before = os.environ.pop("OMB_CRITIC_SLICES_KEEP", None)
    try:
        with pytest.raises(RuntimeError, match="agent exploded"):
            wrapped.invoke({"messages": []})
    finally:
        if env_before is not None:
            os.environ["OMB_CRITIC_SLICES_KEEP"] = env_before

    slices_dir = Path(data_dir) / "evidence" / "_critic_slices"
    assert not slices_dir.exists(), (
        "cleanup must run even when the inner agent raises"
    )


def test_get_summarizer_subagent_includes_data_dir(tmp_path: Path) -> None:
    """get_summarizer_subagent must accept data_dir and expose wrap_invoke."""
    # Import here to avoid heavy top-level deepagents import in module loading
    from unittest.mock import patch

    data_dir = _make_evidence_dir(tmp_path)

    # Patch create_deep_agent so no LLM is constructed
    fake_agent = _make_stub_agent()

    with patch(
        "src.agents.drug_target.subagents.summarizer.agent.create_deep_agent",
        return_value=fake_agent,
    ):
        from src.agents.drug_target.subagents.summarizer.agent import (
            get_summarizer_subagent,
        )

        result = get_summarizer_subagent(data_dir=data_dir)

    assert "name" in result
    assert result["name"] == "summarizer"
    assert "runnable" in result
    # The runnable must be the wrapped version, not the raw agent
    runnable = result["runnable"]
    assert runnable is not fake_agent, (
        "get_summarizer_subagent must return a wrapped runnable, not the raw agent"
    )

"""Tests for _CriticSliceWrapper lifecycle logger emission (T3.6a)."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.agents.drug_target.subagents.summarizer.agent import _CriticSliceWrapper


@pytest.fixture
def stub_data_dir(tmp_path):
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "hypothesis_report.json").write_text('{"hypotheses": []}')
    return str(tmp_path)


def _make_wrapper(stub_data_dir):
    """Helper: construct _CriticSliceWrapper with a stub inner agent."""
    inner = MagicMock()
    inner.invoke.return_value = {"messages": []}
    return _CriticSliceWrapper(inner, data_dir=stub_data_dir)


def test_invoke_emits_5_lifecycle_phases(stub_data_dir, caplog):
    with (
        patch(
            "src.agents.drug_target.subagents.configs.filter_hypothesis_evidence_files"
        ),
        patch("src.agents.drug_target.subagents.configs.write_critic_slices"),
        patch("src.agents.drug_target.subagents.configs.cleanup_critic_slices"),
    ):
        wrapper = _make_wrapper(stub_data_dir)
        with caplog.at_level("INFO", logger="drug_target.lifecycle"):
            wrapper.invoke({"messages": []})

    phases = [json.loads(r.message)["phase"] for r in caplog.records]
    assert phases == [
        "before_filter",
        "before_write",
        "before_invoke",
        "after_invoke",
        "after_cleanup",
    ]


def test_invoke_emits_after_cleanup_even_on_inner_raise(stub_data_dir, caplog):
    with (
        patch(
            "src.agents.drug_target.subagents.configs.filter_hypothesis_evidence_files"
        ),
        patch("src.agents.drug_target.subagents.configs.write_critic_slices"),
        patch("src.agents.drug_target.subagents.configs.cleanup_critic_slices"),
    ):
        inner = MagicMock()
        inner.invoke.side_effect = RuntimeError("boom")
        wrapper = _CriticSliceWrapper(inner, data_dir=stub_data_dir)
        with caplog.at_level("INFO", logger="drug_target.lifecycle"):
            with pytest.raises(RuntimeError):
                wrapper.invoke({"messages": []})

    phases = [json.loads(r.message)["phase"] for r in caplog.records]
    assert "after_cleanup" in phases


def test_invoke_lifecycle_payload_contains_data_dir(stub_data_dir, caplog):
    with (
        patch(
            "src.agents.drug_target.subagents.configs.filter_hypothesis_evidence_files"
        ),
        patch("src.agents.drug_target.subagents.configs.write_critic_slices"),
        patch("src.agents.drug_target.subagents.configs.cleanup_critic_slices"),
    ):
        wrapper = _make_wrapper(stub_data_dir)
        with caplog.at_level("INFO", logger="drug_target.lifecycle"):
            wrapper.invoke({"messages": []})

    for record in caplog.records:
        payload = json.loads(record.message)
        assert payload["data_dir"] == stub_data_dir
        assert payload["event"] == "critic_slice_lifecycle"
        assert "timestamp" in payload


@pytest.mark.asyncio
async def test_ainvoke_emits_5_lifecycle_phases(stub_data_dir, caplog):
    with (
        patch(
            "src.agents.drug_target.subagents.configs.filter_hypothesis_evidence_files"
        ),
        patch("src.agents.drug_target.subagents.configs.write_critic_slices"),
        patch("src.agents.drug_target.subagents.configs.cleanup_critic_slices"),
    ):
        inner = MagicMock()
        inner.ainvoke = AsyncMock(return_value={"messages": []})
        wrapper = _CriticSliceWrapper(inner, data_dir=stub_data_dir)
        with caplog.at_level("INFO", logger="drug_target.lifecycle"):
            await wrapper.ainvoke({"messages": []})

    phases = [json.loads(r.message)["phase"] for r in caplog.records]
    assert phases == [
        "before_filter",
        "before_write",
        "before_invoke",
        "after_invoke",
        "after_cleanup",
    ]


@pytest.mark.asyncio
async def test_ainvoke_emits_after_cleanup_even_on_inner_raise(stub_data_dir, caplog):
    with (
        patch(
            "src.agents.drug_target.subagents.configs.filter_hypothesis_evidence_files"
        ),
        patch("src.agents.drug_target.subagents.configs.write_critic_slices"),
        patch("src.agents.drug_target.subagents.configs.cleanup_critic_slices"),
    ):
        inner = MagicMock()
        inner.ainvoke = AsyncMock(side_effect=RuntimeError("async boom"))
        wrapper = _CriticSliceWrapper(inner, data_dir=stub_data_dir)
        with caplog.at_level("INFO", logger="drug_target.lifecycle"):
            with pytest.raises(RuntimeError):
                await wrapper.ainvoke({"messages": []})

    phases = [json.loads(r.message)["phase"] for r in caplog.records]
    assert "after_cleanup" in phases

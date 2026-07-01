"""Spillover guard: DrugTarget must retain think_tool and validate_quality."""

from __future__ import annotations

from pathlib import Path


_DRUG_TARGET_PROMPTS = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "agents"
    / "drug_target"
    / "subagents"
    / "prompts.py"
)


def _read_drug_target_prompt_text() -> str:
    assert _DRUG_TARGET_PROMPTS.exists(), (
        f"DrugTarget prompts file missing at {_DRUG_TARGET_PROMPTS}"
    )
    return _DRUG_TARGET_PROMPTS.read_text(encoding="utf-8")


def test_drug_target_prompt_retains_shared_quality_tools():
    text = _read_drug_target_prompt_text()

    assert "think_tool" in text
    assert "validate_quality" in text


def test_drug_target_subagents_register_think_tool_and_validate_quality():
    """Every configured DrugTarget subagent tool-list must include BOTH tools."""
    from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS

    assert SUBAGENT_CONFIGS

    for name, config in SUBAGENT_CONFIGS.items():
        tool_names = {
            getattr(tool, "name", getattr(tool, "__name__", repr(tool)))
            for tool in config.get("tools", [])
        }
        assert "think_tool" in tool_names, (
            f"DrugTarget subagent {name!r} lost think_tool from its tool list; "
            f"present tools: {sorted(tool_names)}"
        )
        assert "validate_quality" in tool_names, (
            f"DrugTarget subagent {name!r} lost validate_quality from its tool list; "
            f"present tools: {sorted(tool_names)}"
        )

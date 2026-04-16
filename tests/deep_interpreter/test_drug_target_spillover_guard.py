"""Spillover guard: DrugTarget must retain both think_tool and validate_quality.

If Deep Interpreter's prompt/config changes accidentally remove these shared
tools from DrugTarget subagents, this test fails. It is a grep-style guard,
not a behavior test.

Anchors verified:
- src/agents/drug_target/subagents/prompts.py line 27, 245, 318, 530, 554, 640
  all reference think_tool (6 occurrences).
- src/agents/drug_target/subagents/prompts.py line 697 references validate_quality
  (1 occurrence).
- All four DrugTarget subagent configs register BOTH think_tool and validate_quality.
"""

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


def _read_drug_target_prompts() -> list[str]:
    assert _DRUG_TARGET_PROMPTS.exists(), (
        f"DrugTarget prompts file missing at {_DRUG_TARGET_PROMPTS}"
    )
    return _DRUG_TARGET_PROMPTS.read_text(encoding="utf-8").splitlines()


def test_drug_target_think_tool_line_anchors():
    """think_tool references at lines 27,245,318,530,554,640 in drug_target/prompts.py."""
    lines = _read_drug_target_prompts()

    expected_lines = [27, 245, 318, 530, 554, 640]
    missing: list[int] = []
    for lineno in expected_lines:
        # lineno is 1-based
        if lineno - 1 >= len(lines) or "think_tool" not in lines[lineno - 1]:
            missing.append(lineno)
    assert not missing, (
        f"DrugTarget prompts.py lost think_tool references at lines {missing}. "
        f"Spillover from Deep Interpreter changes suspected."
    )

    # Belt-and-suspenders: total think_tool occurrences across the file.
    total = sum(1 for line in lines if "think_tool" in line)
    assert total >= 6, (
        f"DrugTarget prompts.py has only {total} think_tool references; "
        f"expected at least 6."
    )


def test_drug_target_validate_quality_line_anchor():
    """validate_quality reference at line 697 in drug_target/prompts.py."""
    lines = _read_drug_target_prompts()

    assert 697 - 1 < len(lines), (
        f"DrugTarget prompts.py is shorter than 697 lines (total {len(lines)})."
    )
    assert "validate_quality" in lines[697 - 1], (
        f"DrugTarget prompts.py line 697 lost validate_quality reference: "
        f"{lines[697 - 1]!r}"
    )


def test_all_four_drug_target_subagents_register_think_tool_and_validate_quality():
    """All four DrugTarget subagent tool-lists must include BOTH tools."""
    from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS

    # DrugTarget has 4 subagents per project overview.
    assert len(SUBAGENT_CONFIGS) == 4, (
        f"Expected 4 DrugTarget subagents, got {len(SUBAGENT_CONFIGS)}: "
        f"{list(SUBAGENT_CONFIGS.keys())}"
    )

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

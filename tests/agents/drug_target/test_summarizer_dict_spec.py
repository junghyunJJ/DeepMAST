"""Tests for the simplified summarizer subagent (2026-05-13 simplification).

These six tests replace the 17-test legacy summarizer suite. They cover:

  TS-01: dict spec shape and required keys
  TS-02: exact 7-tool inventory
  TS-03: skill-name wiring under DrugTargetConfig
  TS-04: SummarizerFinalizationGuardMiddleware PASS path
         (generate_drug_html_report proceeds after validate_drug_md=valid)
  TS-05: SummarizerFinalizationGuardMiddleware FAIL path
         (generate_drug_html_report blocked when validate_drug_md=invalid
          or never called)
  TS-06: orchestrator contract — ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE still
         references SUMMARIZER_STATUS and dispatches summarizer by name.

TS-04/TS-05 unit-test the mechanical fail-closed gate directly at the
middleware layer — sufficient under the (b') decision to retain and adapt
``SummarizerFinalizationGuardMiddleware`` for the new tool surface.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from langchain_core.messages import ToolMessage

from src.agents.drug_target.agent import (
    ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE,
    DrugTargetConfig,
    _build_subagent_skill_name_map,
)
from src.agents.drug_target.subagents.summarizer import get_summarizer_subagent
from src.agents.drug_target.subagents.summarizer.middleware import (
    SummarizerFinalizationGuardMiddleware,
)


_REQUIRED_KEYS: frozenset[str] = frozenset(
    {"name", "description", "system_prompt", "tools", "middleware"}
)

_REQUIRED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "build_evidence_summary",
        "load_evidence_files",
        "save_report_expansions",
        "render_drug_md_from_expansions",
        "validate_drug_md",
        "generate_drug_html_report",
        "think_tool",
    }
)


def _build_tool_request(name: str, args: dict | None = None, tool_id: str = "t_1"):
    request = MagicMock()
    request.tool_call = {"name": name, "args": args or {}, "id": tool_id}
    return request


# ---------------------------------------------------------------------------
# TS-01
# ---------------------------------------------------------------------------

def test_summarizer_returns_dict_spec_with_required_keys() -> None:
    spec = get_summarizer_subagent()
    assert isinstance(spec, dict)
    assert frozenset(spec.keys()) == _REQUIRED_KEYS, (
        f"unexpected keys: {sorted(spec.keys())}"
    )
    assert spec["name"] == "summarizer"
    assert "SUMMARIZER_STATUS" in spec["system_prompt"]
    assert isinstance(spec["tools"], list)
    assert isinstance(spec["middleware"], list)


# ---------------------------------------------------------------------------
# TS-02
# ---------------------------------------------------------------------------

def test_summarizer_tools_are_exactly_the_seven_required() -> None:
    spec = get_summarizer_subagent()
    tool_names = {tool.name for tool in spec["tools"]}
    assert tool_names == _REQUIRED_TOOL_NAMES
    assert len(spec["tools"]) == 7
    # Middleware: only the adapted fail-closed gate is attached by the factory.
    mw_types = {type(m) for m in spec["middleware"]}
    assert SummarizerFinalizationGuardMiddleware in mw_types


# ---------------------------------------------------------------------------
# TS-03
# ---------------------------------------------------------------------------

def test_summarizer_skill_names_default_and_config_wiring() -> None:
    config = DrugTargetConfig()
    assert config.summarizer_skill_names == ("drug-target-reporting",)
    # Old field name no longer exists.
    assert not hasattr(config, "report_writer_skill_names")

    skill_map = _build_subagent_skill_name_map(config, enable_census=True)
    assert set(skill_map.keys()) == {
        "evidence_assessor",
        "hypothesis_writer",
        "summarizer",
    }
    assert skill_map["summarizer"] == ("drug-target-reporting",)


# ---------------------------------------------------------------------------
# TS-04 — PASS path through the mechanical gate
# ---------------------------------------------------------------------------

def test_finalization_guard_allows_html_after_validator_passes() -> None:
    """``generate_drug_html_report`` proceeds when ``validate_drug_md`` returned
    ``valid=true``."""
    guard = SummarizerFinalizationGuardMiddleware()

    validator_request = _build_tool_request("validate_drug_md", tool_id="v_1")
    validator_result = ToolMessage(
        content=json.dumps({"valid": True, "errors": []}),
        tool_call_id="v_1",
    )
    guard.wrap_tool_call(validator_request, lambda _r: validator_result)

    final_request = _build_tool_request(
        "generate_drug_html_report",
        args={"data_dir": "/tmp/x"},
        tool_id="g_1",
    )
    sentinel = ToolMessage(content="<html>...</html>", tool_call_id="g_1")
    result = guard.wrap_tool_call(final_request, lambda _r: sentinel)

    assert result is sentinel, "guard must pass through after valid=true"


# ---------------------------------------------------------------------------
# TS-05 — FAIL paths through the mechanical gate
# ---------------------------------------------------------------------------

def test_finalization_guard_blocks_html_when_validator_never_called() -> None:
    """``generate_drug_html_report`` is blocked if no ``validate_drug_md``
    call was observed beforehand."""
    guard = SummarizerFinalizationGuardMiddleware()

    final_request = _build_tool_request(
        "generate_drug_html_report",
        args={"data_dir": "/tmp/x"},
        tool_id="g_1",
    )
    handler_called = MagicMock()
    result = guard.wrap_tool_call(final_request, handler_called)

    assert isinstance(result, ToolMessage)
    payload = json.loads(str(result.content))
    assert payload["ok"] is False
    assert payload["blocked_by"] == "SummarizerFinalizationGuard"
    assert "validate_drug_md" in payload["error"]
    handler_called.assert_not_called()


def test_finalization_guard_blocks_html_when_validator_returned_invalid() -> None:
    """``generate_drug_html_report`` is blocked when the most recent
    ``validate_drug_md`` returned ``valid=false``."""
    guard = SummarizerFinalizationGuardMiddleware()

    validator_request = _build_tool_request("validate_drug_md", tool_id="v_1")
    validator_result = ToolMessage(
        content=json.dumps({"valid": False, "errors": ["WRONG_THING"]}),
        tool_call_id="v_1",
    )
    guard.wrap_tool_call(validator_request, lambda _r: validator_result)

    final_request = _build_tool_request(
        "generate_drug_html_report",
        args={"data_dir": "/tmp/x"},
        tool_id="g_1",
    )
    handler_called = MagicMock()
    result = guard.wrap_tool_call(final_request, handler_called)

    assert isinstance(result, ToolMessage)
    payload = json.loads(str(result.content))
    assert payload["ok"] is False
    assert "valid=false" in payload["error"]
    handler_called.assert_not_called()


# ---------------------------------------------------------------------------
# TS-06 — orchestrator contract preserved
# ---------------------------------------------------------------------------

def test_orchestrator_contract_unchanged() -> None:
    """The orchestrator still dispatches the ``summarizer`` subagent by name
    and parses the literal ``SUMMARIZER_STATUS:`` contract."""
    assert "SUMMARIZER_STATUS: PASS" in ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE
    assert "SUMMARIZER_STATUS: FAIL" in ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE
    assert 'subagent_type="summarizer"' in ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE
    # No lingering reference to the removed inner-subagent dispatch.
    assert 'subagent_type="report_writer"' not in ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE
    assert 'subagent_type="critic"' not in ORCHESTRATOR_SYSTEM_PROMPT_TEMPLATE

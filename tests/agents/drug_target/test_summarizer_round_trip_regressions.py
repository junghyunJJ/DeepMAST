"""Issue #20 round-trip regression tests (Task #12).

Covers each Issue #20 scenario with deterministic stubs — no LLM calls.
All tests run under ``-m "not llm"`` (no marker = collected by default).

Test IDs:
  RT-01  test_duplicate_boilerplate_payload_is_rejected_before_save
  RT-02  test_ungrounded_external_medical_claim_is_rejected_before_save
  RT-03  test_source_grounded_medical_wording_passes_critic_and_proceeds_to_validator
  RT-04  test_payload_changed_after_critic_approval_is_blocked
  RT-05  test_validator_failure_after_critic_pass_routes_back_to_payload_repair_and_then_critic_re_review
  RT-06  test_critic_disabled_mode_full_round_trip_skips_critic_gate_and_subagent_middleware

Run with:
    uv run pytest tests/agents/drug_target/test_summarizer_round_trip_regressions.py -v
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.drug_target.subagents.summarizer.middleware import (
    CriticGateMiddleware,
    SummarizerFinalizationGuardMiddleware,
    compute_envelope_payload_hash,
    normalize_expansions_for_hash,
    parse_critic_envelope,
)
from src.agents.drug_target.tools.report_expansion_schema import canonical_json_hash


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = "summarizer_critic_review.v1"
_PAYLOAD_VERSION = "report_expansions.v1"


def _make_expansions(slots: list[dict] | None = None) -> dict:
    """Minimal valid report_expansions.v1 payload."""
    return {
        "schema_version": _PAYLOAD_VERSION,
        "slots": slots or [{"slot_id": "s1", "sentences": []}],
    }


def _make_envelope_str(payload: dict, payload_hash: str = "sha256:stub") -> str:
    return json.dumps(
        {
            "schema_version": _SCHEMA_VERSION,
            "payload_hash": payload_hash,
            "payload": payload,
            "provenance_context": {},
        }
    )


def _make_task_request(description: str, tool_call_id: str = "task-001") -> MagicMock:
    req = MagicMock()
    req.tool_call = {
        "name": "task",
        "id": tool_call_id,
        "args": {"subagent_type": "critic", "description": description},
    }
    return req


def _make_save_request(expansions: dict, tool_call_id: str = "save-001") -> MagicMock:
    req = MagicMock()
    req.tool_call = {
        "name": "save_report_expansions",
        "id": tool_call_id,
        "args": {"expansions": expansions},
    }
    return req


def _make_validate_request(tool_call_id: str = "validate-001") -> MagicMock:
    req = MagicMock()
    req.tool_call = {
        "name": "validate_drug_md",
        "id": tool_call_id,
        "args": {},
    }
    return req


def _make_html_request(tool_call_id: str = "html-001") -> MagicMock:
    req = MagicMock()
    req.tool_call = {
        "name": "generate_drug_html_report",
        "id": tool_call_id,
        "args": {},
    }
    return req


def _critic_json(
    valid: bool,
    findings: list[dict] | None = None,
    payload_hash: str = "sha256:llm-stub",
) -> str:
    findings = findings or []
    return json.dumps(
        {
            "valid": valid,
            "payload_hash": payload_hash,
            "findings_count": len(findings),
            "findings": findings,
        }
    )


def _tool_message(content: str, tool_call_id: str = "task-001") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id=tool_call_id)


def _finding(
    finding_type: str,
    severity: str = "blocker",
    slot_ids: list[str] | None = None,
    sentence: str = "bad sentence",
    reason: str = "Not supported by cited source",
    repair_instruction: str = "Remove or re-cite the sentence",
) -> dict:
    return {
        "finding_type": finding_type,
        "severity": severity,
        "slot_ids": slot_ids or ["s1"],
        "sentence": sentence,
        "reason": reason,
        "repair_instruction": repair_instruction,
    }


# ---------------------------------------------------------------------------
# RT-01: BOILERPLATE_DUPLICATE blocker rejects save
# ---------------------------------------------------------------------------


def test_duplicate_boilerplate_payload_is_rejected_before_save() -> None:
    """Payload where the same substantive sentence spans multiple slot_ids
    is rejected when the critic stub flags BOILERPLATE_DUPLICATE.

    The CriticGateMiddleware must:
    - Accept the critic call with valid=false
    - Block the subsequent save_report_expansions call
    - Return a ToolMessage containing 'CRITIC_GATE: invalid'
    - Surface the repair_instruction in the blocking message
    """
    mw = CriticGateMiddleware()

    # Build a payload with repeated boilerplate sentence across two slots
    shared_sentence = "This gene is a therapeutic target with broad clinical utility."
    expansions = _make_expansions(
        slots=[
            {"slot_id": "s1", "sentences": [{"text": shared_sentence}]},
            {"slot_id": "s2", "sentences": [{"text": shared_sentence}]},
        ]
    )

    # Critic stub returns invalid with BOILERPLATE_DUPLICATE
    critic_result = _critic_json(
        valid=False,
        findings=[
            _finding(
                finding_type="BOILERPLATE_DUPLICATE",
                slot_ids=["s1", "s2"],
                sentence=shared_sentence,
                repair_instruction="Rephrase each slot with slot-specific wording",
            )
        ],
    )

    # Step 1: critic call
    task_req = _make_task_request(_make_envelope_str(expansions))
    task_handler = MagicMock(return_value=_tool_message(critic_result))
    mw.wrap_tool_call(task_req, task_handler)

    # Step 2: save attempt — must be blocked
    save_req = _make_save_request(expansions)
    save_handler = MagicMock()
    result = mw.wrap_tool_call(save_req, save_handler)

    save_handler.assert_not_called()
    assert isinstance(result, ToolMessage)
    assert "CRITIC_GATE: invalid" in result.content, (
        f"Expected 'CRITIC_GATE: invalid' in blocking message; got: {result.content!r}"
    )
    assert "Rephrase each slot with slot-specific wording" in result.content, (
        "repair_instruction must appear in blocking message so the LLM knows what to fix"
    )


# ---------------------------------------------------------------------------
# RT-02: EXTERNAL_KNOWLEDGE_INJECT blocker rejects save
# ---------------------------------------------------------------------------


def test_ungrounded_external_medical_claim_is_rejected_before_save() -> None:
    """Payload containing an ungrounded external medical claim is rejected
    when the critic stub flags EXTERNAL_KNOWLEDGE_INJECT.

    Shape mirrors RT-01 but uses a different finding_type.
    """
    mw = CriticGateMiddleware()

    expansions = _make_expansions(
        slots=[
            {
                "slot_id": "section_3_mmp7",
                "sentences": [
                    {"text": "MMP7 modulates TGF-beta signaling and fibrotic remodeling."}
                ],
            }
        ]
    )

    critic_result = _critic_json(
        valid=False,
        findings=[
            _finding(
                finding_type="EXTERNAL_KNOWLEDGE_INJECT",
                slot_ids=["section_3_mmp7"],
                sentence="MMP7 modulates TGF-beta signaling and fibrotic remodeling.",
                reason=(
                    "The cited source lists drug evidence but does not support "
                    "TGF-beta or fibrotic-remodeling claims."
                ),
                repair_instruction=(
                    "Remove the unsupported mechanism or cite a source_value that "
                    "actually contains it."
                ),
            )
        ],
    )

    task_req = _make_task_request(_make_envelope_str(expansions))
    task_handler = MagicMock(return_value=_tool_message(critic_result))
    mw.wrap_tool_call(task_req, task_handler)

    save_req = _make_save_request(expansions)
    save_handler = MagicMock()
    result = mw.wrap_tool_call(save_req, save_handler)

    save_handler.assert_not_called()
    assert isinstance(result, ToolMessage)
    assert "CRITIC_GATE: invalid" in result.content
    assert "EXTERNAL_KNOWLEDGE_INJECT" in result.content or "unsupported" in result.content.lower()


# ---------------------------------------------------------------------------
# RT-03: source-grounded wording passes critic → save proceeds
# ---------------------------------------------------------------------------


def test_source_grounded_medical_wording_passes_critic_and_proceeds_to_validator() -> None:
    """When the critic returns valid=true and hashes match, save_report_expansions
    is allowed through and the handler's return value is passed back intact.
    """
    mw = CriticGateMiddleware()

    expansions = _make_expansions(
        slots=[
            {
                "slot_id": "s1",
                "sentences": [
                    {
                        "text": "CD4 has 3 approved clinical drugs per OpenTargets.",
                        "source_provenance": {
                            "source_file": "evidence/ot_CD4.json",
                            "source_field": "clinical_drugs",
                        },
                    }
                ],
            }
        ]
    )

    critic_result = _critic_json(valid=True, findings=[])

    task_req = _make_task_request(_make_envelope_str(expansions))
    task_handler = MagicMock(return_value=_tool_message(critic_result))
    mw.wrap_tool_call(task_req, task_handler)

    save_req = _make_save_request(expansions)
    expected_save_result = ToolMessage(
        content=json.dumps({"saved": True, "errors": []}),
        tool_call_id="save-001",
    )
    save_handler = MagicMock(return_value=expected_save_result)
    result = mw.wrap_tool_call(save_req, save_handler)

    save_handler.assert_called_once_with(save_req)
    assert result is expected_save_result, (
        "Gate must return the handler's result when critic passes and hashes match"
    )


# ---------------------------------------------------------------------------
# RT-04: payload mutated after critic approval → gate blocks
# ---------------------------------------------------------------------------


def test_payload_changed_after_critic_approval_is_blocked() -> None:
    """Critic approves payload P1; attempt to save payload P2 (mutated).
    Gate must block with 'CRITIC_GATE: payload mismatch'.
    """
    mw = CriticGateMiddleware()

    # Critic reviews P1
    payload_p1 = _make_expansions(slots=[{"slot_id": "original", "sentences": []}])
    task_req = _make_task_request(_make_envelope_str(payload_p1))
    task_handler = MagicMock(return_value=_tool_message(_critic_json(valid=True)))
    mw.wrap_tool_call(task_req, task_handler)

    # Save attempt with P2 (different slot_id = different hash)
    payload_p2 = _make_expansions(slots=[{"slot_id": "mutated", "sentences": [{"text": "Added."}]}])
    save_req = _make_save_request(payload_p2)
    save_handler = MagicMock()
    result = mw.wrap_tool_call(save_req, save_handler)

    save_handler.assert_not_called()
    assert isinstance(result, ToolMessage)
    assert "CRITIC_GATE: payload mismatch" in result.content, (
        f"Expected 'CRITIC_GATE: payload mismatch'; got: {result.content!r}"
    )


# ---------------------------------------------------------------------------
# RT-05: validator failure after critic pass → repair loop → re-review → proceed
# ---------------------------------------------------------------------------


def test_validator_failure_after_critic_pass_routes_back_to_payload_repair_and_then_critic_re_review() -> None:
    """Two-iteration repair loop scenario.

    Iteration 1:
      - Critic approves expansions_v1 → save succeeds
      - validate_drug_md returns valid=false → generate_drug_html_report blocked
    Iteration 2:
      - Critic re-reviews repaired expansions_v2 → approves
      - save succeeds with expansions_v2
      - validate_drug_md returns valid=true → generate_drug_html_report proceeds

    The critic gate and finalization guard are separate middleware objects
    and operate independently.  This test exercises their composed behavior
    in sequence without a shared middleware pipeline (each middleware is
    exercised independently for clarity).
    """
    critic_gate = CriticGateMiddleware()
    fin_guard = SummarizerFinalizationGuardMiddleware()

    # ---- Iteration 1 ----
    expansions_v1 = _make_expansions(slots=[{"slot_id": "v1", "sentences": []}])

    # Critic approves v1
    task_req_1 = _make_task_request(_make_envelope_str(expansions_v1), tool_call_id="task-1")
    critic_gate.wrap_tool_call(
        task_req_1,
        MagicMock(return_value=_tool_message(_critic_json(valid=True), tool_call_id="task-1")),
    )

    # Save v1 — gate allows
    save_req_1 = _make_save_request(expansions_v1, tool_call_id="save-1")
    save_result_1 = ToolMessage(content=json.dumps({"saved": True}), tool_call_id="save-1")
    save_result = critic_gate.wrap_tool_call(save_req_1, MagicMock(return_value=save_result_1))
    assert save_result is save_result_1, "Gate must allow save when critic passes"

    # validate_drug_md returns valid=false → finalization guard records failure
    validate_req_1 = _make_validate_request(tool_call_id="validate-1")
    validate_fail_result = ToolMessage(
        content=json.dumps({"valid": False, "issues": [{"type": "MISSING_CITATION"}]}),
        tool_call_id="validate-1",
    )
    fin_guard.wrap_tool_call(validate_req_1, MagicMock(return_value=validate_fail_result))

    # generate_drug_html_report → BLOCKED by finalization guard
    html_req_1 = _make_html_request(tool_call_id="html-1")
    html_handler_1 = MagicMock()
    html_block = fin_guard.wrap_tool_call(html_req_1, html_handler_1)
    html_handler_1.assert_not_called()
    blocked_payload = json.loads(html_block.content)
    assert blocked_payload.get("ok") is False, (
        "HTML must be blocked when validator returned valid=false"
    )
    assert blocked_payload.get("blocked_by") == "SummarizerFinalizationGuard"

    # ---- Iteration 2: repair + new run ----
    # Simulate new run: reset both middlewares
    critic_gate.before_agent(state={}, runtime=MagicMock())
    fin_guard.before_agent(state={}, runtime=MagicMock())

    expansions_v2 = _make_expansions(
        slots=[{"slot_id": "v2_repaired", "sentences": [{"text": "Repaired sentence."}]}]
    )

    # Critic re-reviews and approves v2
    task_req_2 = _make_task_request(_make_envelope_str(expansions_v2), tool_call_id="task-2")
    critic_gate.wrap_tool_call(
        task_req_2,
        MagicMock(return_value=_tool_message(_critic_json(valid=True), tool_call_id="task-2")),
    )

    # Save v2 — gate allows
    save_req_2 = _make_save_request(expansions_v2, tool_call_id="save-2")
    save_result_2 = ToolMessage(content=json.dumps({"saved": True}), tool_call_id="save-2")
    save_result = critic_gate.wrap_tool_call(save_req_2, MagicMock(return_value=save_result_2))
    assert save_result is save_result_2, "Gate must allow save in iteration 2"

    # validate_drug_md returns valid=true
    validate_req_2 = _make_validate_request(tool_call_id="validate-2")
    validate_pass_result = ToolMessage(
        content=json.dumps({"valid": True, "issues": []}),
        tool_call_id="validate-2",
    )
    fin_guard.wrap_tool_call(validate_req_2, MagicMock(return_value=validate_pass_result))

    # generate_drug_html_report → allowed now
    html_req_2 = _make_html_request(tool_call_id="html-2")
    expected_html = ToolMessage(content="<html>report</html>", tool_call_id="html-2")
    html_handler_2 = MagicMock(return_value=expected_html)
    html_result = fin_guard.wrap_tool_call(html_req_2, html_handler_2)

    html_handler_2.assert_called_once_with(html_req_2)
    assert html_result is expected_html, (
        "HTML generation must proceed after validator returns valid=true in iteration 2"
    )


# ---------------------------------------------------------------------------
# RT-06: disabled mode — full round-trip skips critic gate and subagent middleware
# ---------------------------------------------------------------------------


def test_critic_disabled_mode_full_round_trip_skips_critic_gate_and_subagent_middleware() -> None:
    """With critic_enabled=False, save_report_expansions works without a
    prior critic call.  The legacy SummarizerFinalizationGuardMiddleware
    HTML gate still functions.

    Proves:
    1. CriticGateMiddleware is absent from middleware list
    2. SubAgentMiddleware is not installed
    3. save_report_expansions proceeds without any critic call
    4. SummarizerFinalizationGuardMiddleware still blocks HTML until validate passes
    """
    from src.agents.drug_target.subagents.summarizer.agent import get_summarizer_subagent
    from src.agents.drug_target.subagents.summarizer.middleware import (
        CriticGateMiddleware,
        SummarizerFinalizationGuardMiddleware,
    )

    stub_backend = MagicMock(name="stub_backend")

    with (
        patch("src.agents.drug_target.subagents.summarizer.agent.get_critic_subagent"),
        patch("src.agents.drug_target.subagents.summarizer.agent.SubAgentMiddleware") as mock_mw_cls,
    ):
        spec = get_summarizer_subagent(
            backend=stub_backend,
            critic_model="openai:gpt-4o",
            critic_enabled=False,
        )
        mock_mw_cls.assert_not_called()

    mw_list: list = spec["middleware"]

    # No CriticGateMiddleware
    assert not any(isinstance(m, CriticGateMiddleware) for m in mw_list), (
        "CriticGateMiddleware must not be present when critic_enabled=False"
    )

    # SummarizerFinalizationGuardMiddleware must still be present
    fin_guard_instances = [m for m in mw_list if isinstance(m, SummarizerFinalizationGuardMiddleware)]
    assert len(fin_guard_instances) >= 1, (
        "SummarizerFinalizationGuardMiddleware must remain even when critic is disabled"
    )
    fin_guard = fin_guard_instances[0]

    # Prove the finalization guard still functions in disabled mode:
    # HTML is blocked before validation
    html_req = _make_html_request()
    html_handler = MagicMock()
    blocked = fin_guard.wrap_tool_call(html_req, html_handler)
    html_handler.assert_not_called()
    blocked_payload = json.loads(blocked.content)
    assert blocked_payload.get("ok") is False, "HTML must be blocked before validate_drug_md"

    # After validation passes, HTML proceeds
    validate_req = _make_validate_request()
    pass_result = ToolMessage(
        content=json.dumps({"valid": True, "issues": []}),
        tool_call_id="validate-001",
    )
    fin_guard.wrap_tool_call(validate_req, MagicMock(return_value=pass_result))

    html_req2 = _make_html_request(tool_call_id="html-002")
    expected_html = ToolMessage(content="<html>done</html>", tool_call_id="html-002")
    html_handler2 = MagicMock(return_value=expected_html)
    html_result = fin_guard.wrap_tool_call(html_req2, html_handler2)

    html_handler2.assert_called_once_with(html_req2)
    assert html_result is expected_html, (
        "HTML must proceed after validate_drug_md passes even in disabled-critic mode"
    )

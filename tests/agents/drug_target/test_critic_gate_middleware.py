"""Task #7 tests: CriticGateMiddleware captures critic results and gates save.

Test IDs:
  CG-01  test_critic_gate_blocks_save_when_critic_never_called
  CG-02  test_critic_gate_blocks_save_when_critic_json_malformed
  CG-03  test_critic_gate_blocks_save_when_critic_valid_false
  CG-04  test_critic_gate_blocks_save_when_payload_hash_mismatch
  CG-05  test_critic_gate_allows_save_after_valid_matching_payload
  CG-06  test_critic_gate_captures_real_task_command_update_messages
  CG-07  test_critic_gate_resets_between_summarizer_runs
  CG-08  test_critic_gate_hashes_pre_validation_payload
  CG-09  test_summarizer_installs_critic_gate_between_finalization_guard_and_subagent_middleware
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
    compute_envelope_payload_hash,
    normalize_expansions_for_hash,
    parse_critic_envelope,
)
from src.agents.drug_target.tools.report_expansion_schema import canonical_json_hash

# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------

_SCHEMA_VERSION = "summarizer_critic_review.v1"
_PAYLOAD_VERSION = "report_expansions.v1"


def _make_expansions_payload(slots: list[dict] | None = None) -> dict:
    """Minimal valid report_expansions.v1 payload."""
    return {
        "schema_version": _PAYLOAD_VERSION,
        "slots": slots or [{"slot_id": "s1", "sentences": []}],
    }


def _make_critic_envelope_str(payload: dict, payload_hash: str = "sha256:dummy") -> str:
    """Build a valid critic envelope JSON string."""
    return json.dumps(
        {
            "schema_version": _SCHEMA_VERSION,
            "payload_hash": payload_hash,
            "payload": payload,
            "provenance_context": {},
        }
    )


def _make_save_request(expansions: dict) -> Any:
    """Build a minimal ToolCallRequest-like mock for save_report_expansions."""
    req = MagicMock()
    req.tool_call = {
        "name": "save_report_expansions",
        "id": "tool-call-save-001",
        "args": {"expansions": expansions},
    }
    return req


def _make_task_request(description: str) -> Any:
    """Build a minimal ToolCallRequest-like mock for task(subagent_type='critic')."""
    req = MagicMock()
    req.tool_call = {
        "name": "task",
        "id": "tool-call-task-001",
        "args": {"subagent_type": "critic", "description": description},
    }
    return req


def _critic_json(valid: bool, findings: list[dict] | None = None, payload_hash: str = "sha256:llm") -> str:
    """Build a valid Appendix A critic JSON string."""
    findings = findings or []
    return json.dumps(
        {
            "valid": valid,
            "payload_hash": payload_hash,
            "findings_count": len(findings),
            "findings": findings,
        }
    )


def _make_tool_message_result(content: str, tool_call_id: str = "tool-call-task-001") -> ToolMessage:
    """Build a ToolMessage (direct result shape, used in test fakes)."""
    return ToolMessage(content=content, tool_call_id=tool_call_id)


def _make_command_result(content: str, tool_call_id: str = "tool-call-task-001") -> Command:
    """Build the real DeepAgents Command(update={'messages': [ToolMessage]}) shape."""
    msg = ToolMessage(content=content, tool_call_id=tool_call_id)
    return Command(update={"messages": [msg]})


# ---------------------------------------------------------------------------
# CG-01: blocks save when critic never called
# ---------------------------------------------------------------------------


def test_critic_gate_blocks_save_when_critic_never_called() -> None:
    """Gate must block save_report_expansions if task(critic) was not called first."""
    mw = CriticGateMiddleware()
    expansions = _make_expansions_payload()
    save_req = _make_save_request(expansions)
    handler = MagicMock(return_value=ToolMessage(content='{"saved": true}', tool_call_id="x"))

    result = mw.wrap_tool_call(save_req, handler)

    handler.assert_not_called()
    assert isinstance(result, ToolMessage)
    assert "CRITIC_GATE" in result.content
    assert "critic was not called" in result.content


# ---------------------------------------------------------------------------
# CG-02: blocks save when critic JSON is malformed
# ---------------------------------------------------------------------------


def test_critic_gate_blocks_save_when_critic_json_malformed() -> None:
    """When the critic returns non-JSON, gate records failure and blocks save."""
    mw = CriticGateMiddleware()
    expansions = _make_expansions_payload()
    envelope_str = _make_critic_envelope_str(expansions)
    task_req = _make_task_request(envelope_str)

    # Critic handler returns ToolMessage with garbage content
    task_handler = MagicMock(return_value=_make_tool_message_result("NOT JSON AT ALL"))
    mw.wrap_tool_call(task_req, task_handler)

    # Now try save — should be blocked
    save_req = _make_save_request(expansions)
    save_handler = MagicMock()
    result = mw.wrap_tool_call(save_req, save_handler)

    save_handler.assert_not_called()
    assert isinstance(result, ToolMessage)
    assert "CRITIC_GATE" in result.content


# ---------------------------------------------------------------------------
# CG-03: blocks save when critic valid=false
# ---------------------------------------------------------------------------


def test_critic_gate_blocks_save_when_critic_valid_false() -> None:
    """Gate must block save when critic returned valid=false, surfacing findings."""
    mw = CriticGateMiddleware()
    expansions = _make_expansions_payload()
    envelope_str = _make_critic_envelope_str(expansions)
    task_req = _make_task_request(envelope_str)

    finding = {
        "finding_type": "hallucination",
        "severity": "blocker",
        "slot_ids": ["s1"],
        "sentence": "bad sentence",
        "reason": "Not supported",
        "repair_instruction": "Remove it",
    }
    critic_content = _critic_json(valid=False, findings=[finding])
    task_handler = MagicMock(return_value=_make_tool_message_result(critic_content))
    mw.wrap_tool_call(task_req, task_handler)

    save_req = _make_save_request(expansions)
    save_handler = MagicMock()
    result = mw.wrap_tool_call(save_req, save_handler)

    save_handler.assert_not_called()
    assert isinstance(result, ToolMessage)
    assert "CRITIC_GATE: invalid" in result.content
    # repair_instruction must appear so LLM can act on it
    assert "Remove it" in result.content


# ---------------------------------------------------------------------------
# CG-04: blocks save when payload hash mismatches
# ---------------------------------------------------------------------------


def test_critic_gate_blocks_save_when_payload_hash_mismatch() -> None:
    """Gate must block save when the expansions sent differ from those reviewed."""
    mw = CriticGateMiddleware()

    # Critic reviews payload A
    payload_a = _make_expansions_payload(slots=[{"slot_id": "s1", "sentences": []}])
    task_req = _make_task_request(_make_critic_envelope_str(payload_a))
    task_handler = MagicMock(return_value=_make_tool_message_result(_critic_json(valid=True)))
    mw.wrap_tool_call(task_req, task_handler)

    # Save is attempted with payload B (different)
    payload_b = _make_expansions_payload(slots=[{"slot_id": "s2", "sentences": []}])
    save_req = _make_save_request(payload_b)
    save_handler = MagicMock()
    result = mw.wrap_tool_call(save_req, save_handler)

    save_handler.assert_not_called()
    assert isinstance(result, ToolMessage)
    assert "CRITIC_GATE: payload mismatch" in result.content


# ---------------------------------------------------------------------------
# CG-05: allows save after valid critic + matching payload
# ---------------------------------------------------------------------------


def test_critic_gate_allows_save_after_valid_matching_payload() -> None:
    """Gate must allow save when critic was valid and payload hashes match."""
    mw = CriticGateMiddleware()
    expansions = _make_expansions_payload()

    # Critic call
    task_req = _make_task_request(_make_critic_envelope_str(expansions))
    task_handler = MagicMock(return_value=_make_tool_message_result(_critic_json(valid=True)))
    mw.wrap_tool_call(task_req, task_handler)

    # Save call — same payload
    save_req = _make_save_request(expansions)
    expected_result = ToolMessage(content='{"saved": true}', tool_call_id="save-001")
    save_handler = MagicMock(return_value=expected_result)
    result = mw.wrap_tool_call(save_req, save_handler)

    save_handler.assert_called_once_with(save_req)
    assert result is expected_result


# ---------------------------------------------------------------------------
# CG-06: captures real Command(update={messages:[ToolMessage]}) shape
# ---------------------------------------------------------------------------


def test_critic_gate_captures_real_task_command_update_messages() -> None:
    """Gate must correctly extract critic JSON from the real DeepAgents Command shape.

    Feeds Command(update={'messages': [ToolMessage(...)]}) — the exact return
    value confirmed by the spike test — and verifies the gate then allows a
    matching save.
    """
    mw = CriticGateMiddleware()
    expansions = _make_expansions_payload()

    task_req = _make_task_request(_make_critic_envelope_str(expansions))
    # Use Command shape (real DeepAgents path)
    command_result = _make_command_result(_critic_json(valid=True))
    task_handler = MagicMock(return_value=command_result)
    mw.wrap_tool_call(task_req, task_handler)

    # Save with matching payload must be allowed
    save_req = _make_save_request(expansions)
    expected_save_result = ToolMessage(content='{"saved": true}', tool_call_id="save-001")
    save_handler = MagicMock(return_value=expected_save_result)
    result = mw.wrap_tool_call(save_req, save_handler)

    save_handler.assert_called_once_with(save_req)
    assert result is expected_save_result


# ---------------------------------------------------------------------------
# CG-07: state resets between summarizer runs
# ---------------------------------------------------------------------------


def test_critic_gate_resets_between_summarizer_runs() -> None:
    """before_agent must clear critic_called / last_valid / last_findings / last_payload_hash."""
    mw = CriticGateMiddleware()
    expansions = _make_expansions_payload()

    # First run: call critic + save
    task_req = _make_task_request(_make_critic_envelope_str(expansions))
    mw.wrap_tool_call(task_req, MagicMock(return_value=_make_tool_message_result(_critic_json(valid=True))))

    # Reset via before_agent (simulates new summarizer invocation)
    mw.before_agent(state={}, runtime=MagicMock())

    # After reset: save should be blocked again (critic_called is False)
    save_req = _make_save_request(expansions)
    save_handler = MagicMock()
    result = mw.wrap_tool_call(save_req, save_handler)

    save_handler.assert_not_called()
    assert "CRITIC_GATE" in result.content
    assert "critic was not called" in result.content

    # Second reset — idempotent
    mw.before_agent(state={}, runtime=MagicMock())
    result2 = mw.wrap_tool_call(save_req, MagicMock())
    assert "CRITIC_GATE" in result2.content


# ---------------------------------------------------------------------------
# CG-08: hashes pre-validation payload (mutation invariant)
# ---------------------------------------------------------------------------


def test_critic_gate_hashes_pre_validation_payload() -> None:
    """Gate must compute the hash BEFORE calling handler(save_req).

    Simulate save_report_expansions mutating the expansions dict after being
    called (e.g., adding reference_card_hash). The gate must have already
    captured the pre-mutation hash so it can compare correctly.

    Test: critic reviews payload P. Save handler mutates P after being invoked.
    The gate should have already passed (pre-hash matched). The mutation must
    not retroactively break the gate.
    """
    mw = CriticGateMiddleware()
    expansions = _make_expansions_payload()

    # Critic approves expansions
    task_req = _make_task_request(_make_critic_envelope_str(expansions))
    mw.wrap_tool_call(task_req, MagicMock(return_value=_make_tool_message_result(_critic_json(valid=True))))

    # Build a save handler that mutates expansions after call
    saved_result = ToolMessage(content='{"saved": true}', tool_call_id="s")

    def _mutating_handler(req: Any) -> ToolMessage:
        # Simulate save_report_expansions adding reference_card_hash in place
        req.tool_call["args"]["expansions"]["reference_card_hash"] = "sha256:mutated"
        return saved_result

    save_req = _make_save_request(expansions)
    result = mw.wrap_tool_call(save_req, _mutating_handler)

    # Gate must have allowed the call (pre-hash matched before mutation)
    assert result is saved_result


# ---------------------------------------------------------------------------
# CG-09: summarizer installs CriticGateMiddleware between guard and subagent
# ---------------------------------------------------------------------------


def test_summarizer_installs_critic_gate_between_finalization_guard_and_subagent_middleware() -> None:
    """get_summarizer_subagent(critic_enabled=True) must install CriticGateMiddleware
    between SummarizerFinalizationGuardMiddleware and SubAgentMiddleware.

    Expected order: [..., SummarizerFinalizationGuardMiddleware, CriticGateMiddleware, SubAgentMiddleware(...)]
    """
    from deepagents import SubAgentMiddleware

    from src.agents.drug_target.subagents.summarizer import get_summarizer_subagent
    from src.agents.drug_target.subagents.summarizer.middleware import (
        CriticGateMiddleware,
        SummarizerFinalizationGuardMiddleware,
    )

    stub_critic_spec = {"name": "critic", "model": "openai:gpt-4o", "tools": []}
    stub_backend = MagicMock(name="stub_backend")
    stub_subagent_mw = MagicMock(name="stub_SubAgentMiddleware_instance")

    with (
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.get_critic_subagent",
            return_value=stub_critic_spec,
        ),
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.SubAgentMiddleware",
            return_value=stub_subagent_mw,
        ),
    ):
        spec = get_summarizer_subagent(
            backend=stub_backend,
            critic_model="openai:gpt-4o",
            critic_enabled=True,
        )

    mw_list = spec["middleware"]
    assert isinstance(mw_list, list), "middleware must be a list"

    # Find positions of each required middleware type
    guard_idx = next(
        (i for i, m in enumerate(mw_list) if isinstance(m, SummarizerFinalizationGuardMiddleware)),
        None,
    )
    gate_idx = next(
        (i for i, m in enumerate(mw_list) if isinstance(m, CriticGateMiddleware)),
        None,
    )
    subagent_idx = next(
        (i for i, m in enumerate(mw_list) if m is stub_subagent_mw),
        None,
    )

    assert guard_idx is not None, "SummarizerFinalizationGuardMiddleware must be in middleware"
    assert gate_idx is not None, "CriticGateMiddleware must be in middleware when critic_enabled=True"
    assert subagent_idx is not None, "SubAgentMiddleware must be in middleware when critic_enabled=True"

    assert guard_idx < gate_idx, (
        f"SummarizerFinalizationGuardMiddleware (idx={guard_idx}) must come "
        f"before CriticGateMiddleware (idx={gate_idx})"
    )
    assert gate_idx < subagent_idx, (
        f"CriticGateMiddleware (idx={gate_idx}) must come "
        f"before SubAgentMiddleware (idx={subagent_idx})"
    )


# ---------------------------------------------------------------------------
# CG-10: validate_cited_only_provenance is called during capture phase
# ---------------------------------------------------------------------------


def test_critic_gate_invokes_validate_cited_only_provenance() -> None:
    """Gate must call validate_cited_only_provenance after parse succeeds.

    Feed an envelope whose provenance_context references a (source_file,
    source_field) pair that is NOT cited in the corresponding slot's
    sentences.  The gate must record last_valid=False with a finding that
    mentions the provenance violation, and a subsequent save attempt must
    be blocked.
    """
    mw = CriticGateMiddleware()

    # Build a slot with NO cited provenance in any sentence
    slots = [
        {
            "slot_id": "s1",
            "sentences": [
                {
                    "text": "Some sentence with no provenance.",
                    "source_provenance": None,
                }
            ],
        }
    ]
    payload = _make_expansions_payload(slots=slots)

    # provenance_context references a source that is NOT cited in the slot
    envelope_dict = {
        "schema_version": _SCHEMA_VERSION,
        "payload_hash": "sha256:dummy",
        "payload": payload,
        "provenance_context": {
            "s1": {
                "cited_provenance_entries": [
                    {"source_file": "ghost.json", "source_field": "summary"}
                ]
            }
        },
    }
    envelope_str = json.dumps(envelope_dict)
    task_req = _make_task_request(envelope_str)

    # Critic handler returns a valid-looking response — the provenance
    # violation must be caught by the middleware, not by the critic.
    task_handler = MagicMock(return_value=_make_tool_message_result(_critic_json(valid=True)))
    mw.wrap_tool_call(task_req, task_handler)

    # Gate must have flagged the run as invalid
    assert mw._last_valid is False, "uncited provenance must set last_valid=False"
    assert mw._critic_called is True

    # At least one finding must point at the provenance violation
    assert any(
        "provenance" in str(f.get("reason", "")).lower()
        or "uncited" in str(f.get("reason", "")).lower()
        for f in mw._last_findings
    ), f"expected a provenance-violation finding, got: {mw._last_findings}"

    # A subsequent save attempt must be blocked
    save_req = _make_save_request(payload)
    save_handler = MagicMock()
    result = mw.wrap_tool_call(save_req, save_handler)

    save_handler.assert_not_called()
    assert isinstance(result, ToolMessage)
    assert "CRITIC_GATE" in result.content


# ---------------------------------------------------------------------------
# CG-11: findings_text in block message is capped at 5 entries
# ---------------------------------------------------------------------------


def test_critic_gate_invalid_message_caps_findings_at_5() -> None:
    """Block message must contain at most 5 findings + an omission marker.

    Feed 10 critic findings.  The serialized findings_text in the returned
    ToolMessage content must contain only 5 real findings plus a synthetic
    entry whose reason contains the '{N-5} more findings omitted' text.
    """
    mw = CriticGateMiddleware()
    expansions = _make_expansions_payload()
    envelope_str = _make_critic_envelope_str(expansions)
    task_req = _make_task_request(envelope_str)

    findings_10 = [
        {
            "finding_type": "hallucination",
            "severity": "blocker",
            "slot_ids": ["s1"],
            "sentence": f"sentence {i}",
            "reason": f"reason {i}",
            "repair_instruction": f"fix {i}",
        }
        for i in range(10)
    ]
    task_handler = MagicMock(
        return_value=_make_tool_message_result(_critic_json(valid=False, findings=findings_10))
    )
    mw.wrap_tool_call(task_req, task_handler)

    # Trigger the block path
    save_req = _make_save_request(expansions)
    save_handler = MagicMock()
    result = mw.wrap_tool_call(save_req, save_handler)

    assert isinstance(result, ToolMessage)
    assert "CRITIC_GATE" in result.content

    # Extract the findings array from the message JSON fragment
    # The message embeds a JSON-serialized findings list; parse it out.
    content = result.content
    # Find the JSON list embedded after "findings before retrying save: "
    findings_start = content.find("[")
    findings_end = content.rfind("]") + 1
    assert findings_start != -1, "findings JSON list not found in block message"
    serialized_findings: list[dict] = json.loads(content[findings_start:findings_end])

    assert len(serialized_findings) == 6, (
        f"expected 5 real + 1 omission marker = 6 entries, got {len(serialized_findings)}: "
        f"{serialized_findings}"
    )
    last_entry = serialized_findings[-1]
    assert "omitted" in last_entry.get("reason", "").lower(), (
        f"last entry must be the omission marker, got: {last_entry}"
    )


# ---------------------------------------------------------------------------
# CG-12: findings_text truncates string fields longer than 500 chars
# ---------------------------------------------------------------------------


def test_critic_gate_invalid_message_truncates_long_strings() -> None:
    """String fields in findings must be truncated to 500 chars with '...' appended."""
    mw = CriticGateMiddleware()
    expansions = _make_expansions_payload()
    envelope_str = _make_critic_envelope_str(expansions)
    task_req = _make_task_request(envelope_str)

    long_sentence = "X" * 600  # 600 chars — must be truncated to 500 + "..."
    finding = {
        "finding_type": "hallucination",
        "severity": "blocker",
        "slot_ids": ["s1"],
        "sentence": long_sentence,
        "reason": "Too long",
        "repair_instruction": "Y" * 600,
    }
    task_handler = MagicMock(
        return_value=_make_tool_message_result(_critic_json(valid=False, findings=[finding]))
    )
    mw.wrap_tool_call(task_req, task_handler)

    save_req = _make_save_request(expansions)
    result = mw.wrap_tool_call(save_req, MagicMock())

    assert isinstance(result, ToolMessage)
    content = result.content
    findings_start = content.find("[")
    findings_end = content.rfind("]") + 1
    serialized_findings: list[dict] = json.loads(content[findings_start:findings_end])

    assert len(serialized_findings) >= 1
    first = serialized_findings[0]
    assert first["sentence"].endswith("..."), (
        f"sentence must end with '...', got: {first['sentence'][-10:]!r}"
    )
    assert len(first["sentence"]) == 503, (
        f"truncated sentence must be 500 chars + '...', got length {len(first['sentence'])}"
    )
    assert first["repair_instruction"].endswith("..."), (
        f"repair_instruction must end with '...', got: {first['repair_instruction'][-10:]!r}"
    )


# ---------------------------------------------------------------------------
# CG-13: findings_text strips control characters
# ---------------------------------------------------------------------------


def test_critic_gate_invalid_message_strips_control_chars() -> None:
    """Control characters (\\x00-\\x08, \\x0b, \\x0c, \\x0e-\\x1f, \\x7f) must be
    stripped from string fields in the block message findings.
    \\n, \\r, \\t are allowed as readability characters.
    """
    mw = CriticGateMiddleware()
    expansions = _make_expansions_payload()
    envelope_str = _make_critic_envelope_str(expansions)
    task_req = _make_task_request(envelope_str)

    dirty_sentence = "clean\x00dirty\x07text\x1fend"
    finding = {
        "finding_type": "hallucination",
        "severity": "blocker",
        "slot_ids": ["s1"],
        "sentence": dirty_sentence,
        "reason": "has\x0bcontrol\x0cchars",
        "repair_instruction": "remove\x7fthem",
    }
    task_handler = MagicMock(
        return_value=_make_tool_message_result(_critic_json(valid=False, findings=[finding]))
    )
    mw.wrap_tool_call(task_req, task_handler)

    save_req = _make_save_request(expansions)
    result = mw.wrap_tool_call(save_req, MagicMock())

    assert isinstance(result, ToolMessage)
    content = result.content
    findings_start = content.find("[")
    findings_end = content.rfind("]") + 1
    serialized_findings: list[dict] = json.loads(content[findings_start:findings_end])

    assert len(serialized_findings) >= 1
    first = serialized_findings[0]

    # Banned control characters must be absent
    banned = set("\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f"
                 "\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f\x7f")
    for field_name in ("sentence", "reason", "repair_instruction"):
        value = first.get(field_name, "")
        found_banned = set(value) & banned
        assert not found_banned, (
            f"field {field_name!r} contains banned control chars {found_banned!r}: {value!r}"
        )

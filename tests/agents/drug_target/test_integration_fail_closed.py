"""Integration tests verifying the fail-closed contract end-to-end through
run_drug_target_assessment.

The deep agent and finalize_stage1_workspace are mocked so no LLM/network
calls are made. validate_drug_report_finalization is NOT mocked — it runs
against the real on-disk fixture files to exercise the full host-side gate.

Fixtures under tests/agents/drug_target/fixtures/:
  clean/                    — passes all validator checks
  markdown_table_pipe_drift/ — defect: MARKDOWN_TABLE_PIPE_DRIFT

Test 4 (test_finalization_guard_middleware_blocks_save_when_validator_invalid)
exercises the full summarizer middleware stack via create_summarizer_agent:
  - FakeChatModel drives: validate_drug_report_finalization (valid=false),
    then save_drug_md attempt.
  - SummarizerFinalizationGuardMiddleware (order=3) blocks save_drug_md.
  - Assertions verify: no file write, BLOCKED ToolMessage in message history,
    final LLM response contains "Pipeline incomplete".
"""

import json
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage

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


# ---------------------------------------------------------------------------
# Test 4: SummarizerFinalizationGuardMiddleware blocks task(report_writer) E2E
# ---------------------------------------------------------------------------
#
# Scenario:
#   1. create_summarizer_agent is called (real factory, real middleware stack).
#   2. FakeChatModel drives the conversation:
#        Turn 1 → emit validate_drug_report_finalization tool call (with data_dir)
#        Turn 2 → (after seeing valid=false result) emit task(report_writer) call
#        Turn 3 → (after seeing BLOCKED response from SummarizerFinalizationGuard)
#                 emit final AIMessage "Pipeline incomplete: report remains draft."
#   3. validate_drug_report_finalization.func is patched to return valid=false.
#   4. The backend write() is wrapped to detect any actual file write attempts.
#   5. SummarizerFinalizationGuardMiddleware (mounted at middleware index 3)
#      intercepts the task(report_writer) call and returns a BLOCKED ToolMessage
#      without ever reaching the inner report_writer subagent.
#
# Why task(report_writer) and not save_drug_md directly:
#   The summarizer is a READ-ONLY supervisor — ReadOnlyToolGuardMiddleware
#   (index 0) blocks direct save_drug_md calls.  The realistic flow is that
#   the summarizer dispatches to report_writer via task(...).
#   SummarizerFinalizationGuardMiddleware guards BOTH save_drug_md AND
#   task(subagent_type="report_writer") per its _GUARDED_SUBAGENTS tuple.
#
# Assertions (plan §1.4 + §6 row 7):
#   A. drug.md file MUST NOT be written — backend.write() not called.
#   B. The BLOCKED ToolMessage from SummarizerFinalizationGuard must appear
#      in the messages the LLM receives on its next turn.
#   C. The orchestrator's final response contains "Pipeline incomplete".
# ---------------------------------------------------------------------------

_VALIDATOR_INVALID_PAYLOAD = json.dumps(
    {
        "valid": False,
        "issue_count": 7,
        "issues": [
            {
                "code": "STAGE3_NORMALIZED_DRUGS_LOST",
                "severity": "blocking",
                "message": (
                    "stage3 evidence available but normalized cards have 0 drugs"
                ),
            }
        ],
        "checks": {},
        "sources": [],
    }
)


def _make_finalization_guard_fake_model(
    *,
    data_dir: str,
    received_messages: list[Any],
) -> Any:
    """Build a BaseChatModel subclass that drives the validator → task(report_writer) sequence.

    Extends BaseChatModel so that deepagents' resolve_model() short-circuits on
    isinstance(model, BaseChatModel) and does not call _get_harness_profile(model).

    Turn 0: emit validate_drug_report_finalization tool call (with data_dir arg).
    Turn 1: after receiving valid=false ToolMessage, emit task(report_writer) call.
    Turn 2+: after receiving BLOCKED ToolMessage from SummarizerFinalizationGuard,
             emit final AIMessage "Pipeline incomplete: report remains draft.".

    All messages received by _generate() are appended to received_messages so
    the test can inspect what the LLM observed (including the BLOCKED msg).
    """
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langchain_core.callbacks.manager import CallbackManagerForLLMRun

    # mutable state captured by closure so the class can use it
    state: dict[str, Any] = {"n": 0, "data_dir": data_dir}

    class _FinalizationGuardFakeModel(BaseChatModel):
        """Deterministic fake model for finalization guard E2E test."""

        model_config = {"arbitrary_types_allowed": True}

        @property
        def _llm_type(self) -> str:
            return "fake-finalization-guard-model"

        def bind_tools(self, tools: Any, **kwargs: Any) -> "_FinalizationGuardFakeModel":
            """Accept tool binding without raising — deepagents calls this during setup."""
            return self

        def _generate(
            self,
            messages: list[Any],
            stop: list[str] | None = None,
            run_manager: CallbackManagerForLLMRun | None = None,
            **kwargs: Any,
        ) -> ChatResult:
            # Record every message batch the LLM receives
            received_messages.extend(messages)

            n = state["n"]
            state["n"] += 1

            if n == 0:
                # Turn 0: call the validator (must pass data_dir — required field)
                msg = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_validate_001",
                            "name": "validate_drug_report_finalization",
                            "args": {"data_dir": state["data_dir"]},
                        }
                    ],
                )
            elif n == 1:
                # Turn 1: validator returned valid=false — dispatch to report_writer
                # The summarizer uses task(subagent_type="report_writer") since it is
                # a read-only supervisor; SummarizerFinalizationGuardMiddleware guards this.
                msg = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_task_001",
                            "name": "task",
                            "args": {
                                "subagent_type": "report_writer",
                                "instruction": "Write drug.md for IPF.",
                            },
                        }
                    ],
                )
            else:
                # Turn 2+: SummarizerFinalizationGuard blocked task(report_writer) — emit sentinel
                msg = AIMessage(
                    content="Pipeline incomplete: report remains draft."
                )

            return ChatResult(generations=[ChatGeneration(message=msg)])

    return _FinalizationGuardFakeModel()


@pytest.mark.asyncio
async def test_finalization_guard_middleware_blocks_save_when_validator_invalid(
    tmp_path: Path,
) -> None:
    """E2E: deterministic Summarizer fails closed before any direct drug.md save.

    Asserts:
      A. drug.md file is NOT written to disk (no backend.write() for drug.md).
      B. No legacy guard ToolMessage is required because the host loop owns gating.
      C. The final agent response starts with SUMMARIZER_STATUS: FAIL.
    """
    # ---- Arrange -------------------------------------------------------
    # Minimal workspace so FilesystemBackend and tools don't choke
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (tmp_path / "lr_candidates.json").write_text(json.dumps({"pairs": []}))

    # Track whether save_drug_md actually wrote to disk
    drug_md_path = tmp_path / "drug.md"
    assert not drug_md_path.exists(), "precondition: drug.md must not exist before test"

    # Collect all messages the LLM receives
    received_messages: list[Any] = []
    fake_model = _make_finalization_guard_fake_model(
        data_dir=str(tmp_path),
        received_messages=received_messages,
    )

    from deepagents.backends import FilesystemBackend

    backend = FilesystemBackend(root_dir=str(tmp_path), virtual_mode=True)

    # Track write() calls — if save_drug_md bypassed the guard it would call
    # backend.write(...).  We wrap it to detect this.
    original_write = backend.write
    write_calls: list[tuple[Any, ...]] = []

    def _spy_write(*args: Any, **kwargs: Any) -> Any:
        write_calls.append((args, kwargs))
        return original_write(*args, **kwargs)

    backend.write = _spy_write  # type: ignore[method-assign]

    # ---- Act -----------------------------------------------------------
    # Patch validate_drug_report_finalization.func so it returns valid=false
    # without hitting the real disk-based validator.
    # Use a plain function (not MagicMock) to avoid breaking typing.get_type_hints
    # which is called on the func's annotations during tool schema introspection.
    def _fake_validator(**kwargs: Any) -> str:  # noqa: ARG001
        return _VALIDATOR_INVALID_PAYLOAD

    with patch(
        "src.agents.drug_target.tools.validate_drug_report_finalization.func",
        new=_fake_validator,
    ):
        from src.agents.drug_target.subagents.summarizer.agent import (
            create_summarizer_agent,
        )

        # Real factory — deterministic host loop is wired here.
        agent = create_summarizer_agent(
            model=fake_model,
            data_dir=str(tmp_path),
        )

        result = await agent.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Finalize drug.md for IPF. "
                            "Data dir: " + str(tmp_path)
                        ),
                    }
                ]
            }
        )

    # ---- Assert A: save_drug_md side effect (file write) must NOT happen ---
    assert not drug_md_path.exists(), (
        "drug.md MUST NOT be created when SummarizerFinalizationGuard blocks "
        "save_drug_md after validator returned valid=false"
    )
    # Also verify no write() call was made for drug.md content
    drug_md_write_calls = [
        c for c in write_calls
        if any("drug.md" in str(a) for a in c[0])
        or any("drug.md" in str(v) for v in c[1].values())
    ]
    assert drug_md_write_calls == [], (
        f"backend.write() must not be called for drug.md when guard blocks; "
        f"got {drug_md_write_calls}"
    )

    # ---- Assert B: legacy middleware guard is no longer the runtime path ----
    assert received_messages == []

    # ---- Assert C: final response is fail-closed --------------------------
    final_messages = result.get("messages", [])
    assert final_messages, "Agent must return at least one message"
    last_message = final_messages[-1]
    assert str(last_message.content).startswith("SUMMARIZER_STATUS: FAIL")

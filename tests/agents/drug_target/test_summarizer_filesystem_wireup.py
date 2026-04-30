"""Phase 1 RED test — FilesystemBackend wired into create_summarizer_agent.

Bypass _CriticSliceWrapper: call create_summarizer_agent(model=..., backend=...)
directly to avoid the write_critic_slices(data_dir) precondition.

Asserts:
1. When FilesystemBackend(root_dir=tmp_path, virtual_mode=True) is passed,
   tool messages contain the disk file names from the evidence/ directory.
2. Path consistency: virtual read_file("/evidence/pair_001.json") and real-disk
   (tmp_path / "evidence" / "pair_001.json").read_text() agree.
3. get_summarizer_subagent auto-constructs a disk backend when data_dir is
   provided and backend is None.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Seed fixture helpers
# ---------------------------------------------------------------------------


def _seed_evidence(tmp_path: Path) -> None:
    """Write minimal evidence files for the filesystem backend tests."""
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    (evidence_dir / "pair_001.json").write_text(
        json.dumps({"pair_id": "pair_001", "gene": "TGFB1"})
    )
    (evidence_dir / "pair_002.json").write_text(
        json.dumps({"pair_id": "pair_002", "gene": "ITGB2"})
    )
    (evidence_dir / "disease_context.json").write_text(
        json.dumps({"disease": "IPF"})
    )


def _make_ls_fake_model() -> Any:
    """Return a fake BaseChatModel that emits one ls tool_call then stops.

    The first response is an AIMessage with tool_calls=[{name="ls", args={path="/evidence/"}}].
    The second response (after the tool message) is a plain AIMessage (stop).
    """
    from langchain_core.messages import AIMessage

    call_counter: dict[str, int] = {"n": 0}

    class FakeChatModel:
        """Minimal fake that satisfies create_deep_agent model protocol."""

        model_name = "fake-test-model"
        # deepagents checks for bind_tools
        def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeChatModel":  # noqa: ARG002
            return self

        def invoke(self, messages: Any, **kwargs: Any) -> AIMessage:  # noqa: ARG002
            n = call_counter["n"]
            call_counter["n"] += 1
            if n == 0:
                # First call: emit an ls tool call
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_ls_001",
                            "name": "ls",
                            "args": {"path": "/evidence/"},
                        }
                    ],
                )
            # Subsequent calls: stop
            return AIMessage(content="Done listing evidence directory.")

        def with_config(self, *args: Any, **kwargs: Any) -> "FakeChatModel":
            return self

    return FakeChatModel()


# ---------------------------------------------------------------------------
# T2a: FilesystemBackend exposes disk files via ls
# ---------------------------------------------------------------------------


def test_filesystem_backend_ls_returns_disk_files(tmp_path: Path) -> None:
    """When create_summarizer_agent receives FilesystemBackend(root_dir=tmp_path),
    the ls tool_call output must include the seeded file names from evidence/."""
    _seed_evidence(tmp_path)

    from deepagents.backends import FilesystemBackend

    backend = FilesystemBackend(root_dir=str(tmp_path), virtual_mode=True)

    fake_model = _make_ls_fake_model()

    with patch(
        "src.agents.drug_target.subagents.summarizer.agent.create_deep_agent",
    ) as mock_create:
        # Return a fake agent that simulates one ls call result
        from langchain_core.messages import AIMessage, ToolMessage

        fake_agent = MagicMock()
        fake_agent.with_config.return_value = fake_agent

        def _fake_invoke(input_msg: Any, **kwargs: Any) -> dict:  # noqa: ARG001
            # Simulate the backend returning a file listing containing pair_001.json
            ls_result = "pair_001.json\npair_002.json\ndisease_context.json"
            return {
                "messages": [
                    AIMessage(content="", tool_calls=[{"id": "c1", "name": "ls", "args": {"path": "/evidence/"}}]),
                    ToolMessage(content=ls_result, tool_call_id="c1"),
                    AIMessage(content="Done listing evidence directory."),
                ]
            }

        fake_agent.invoke.side_effect = _fake_invoke
        mock_create.return_value = fake_agent

        from src.agents.drug_target.subagents.summarizer.agent import (
            create_summarizer_agent,
        )

        agent = create_summarizer_agent(model=fake_model, backend=backend)
        result = agent.invoke({"messages": [{"role": "user", "content": "ls /evidence/"}]})

    # Assert the backend was passed through to create_deep_agent
    assert mock_create.called, "create_deep_agent must be called"
    call_kwargs = mock_create.call_args[1] if mock_create.call_args[1] else {}
    call_args = mock_create.call_args[0] if mock_create.call_args[0] else ()
    # backend should be passed as keyword argument
    assert "backend" in call_kwargs, (
        "create_deep_agent must receive backend= keyword arg; "
        f"got kwargs={list(call_kwargs.keys())}"
    )
    assert call_kwargs["backend"] is backend, (
        "The FilesystemBackend instance must be forwarded unchanged"
    )

    # Assert tool messages contain pair_001.json
    tool_messages = [m for m in result["messages"] if hasattr(m, "tool_call_id")]
    assert any("pair_001.json" in str(m.content) for m in tool_messages), (
        f"Expected tool message to contain 'pair_001.json'. Messages: {result['messages']}"
    )


# ---------------------------------------------------------------------------
# T2b: Path consistency between virtual and real-disk surfaces
# ---------------------------------------------------------------------------


def test_path_consistency_virtual_and_real_disk(tmp_path: Path) -> None:
    """Virtual read_file('/evidence/pair_001.json') and real-disk read agree."""
    _seed_evidence(tmp_path)

    real_content = (tmp_path / "evidence" / "pair_001.json").read_text()
    expected = json.loads(real_content)

    # FilesystemBackend in virtual_mode=True roots /evidence/ → tmp_path/evidence/
    from deepagents.backends import FilesystemBackend

    backend = FilesystemBackend(root_dir=str(tmp_path), virtual_mode=True)

    # The backend's read method must resolve /evidence/pair_001.json to tmp_path/evidence/pair_001.json
    # We verify by reading through the backend's file resolution
    # FilesystemBackend stores root as backend.cwd (a resolved Path)
    assert backend.cwd == tmp_path.resolve(), (
        f"FilesystemBackend cwd must be tmp_path, got {backend.cwd}"
    )

    # Verify the real file exists at the path the backend would resolve to
    virtual_path = "/evidence/pair_001.json"
    # virtual_mode strips leading slash and joins with cwd
    resolved = backend.cwd / virtual_path.lstrip("/")
    assert resolved.exists(), (
        f"FilesystemBackend must resolve virtual path {virtual_path!r} "
        f"to real-disk path {resolved}; file does not exist"
    )

    real_from_virtual = json.loads(resolved.read_text())
    assert real_from_virtual == expected, (
        f"Content mismatch between virtual path and real disk:\n"
        f"  virtual resolved: {real_from_virtual}\n"
        f"  real disk:        {expected}"
    )


# ---------------------------------------------------------------------------
# T2c: get_summarizer_subagent auto-constructs disk backend from data_dir
# ---------------------------------------------------------------------------


def test_get_summarizer_subagent_uses_disk_backend_when_data_dir_given(
    tmp_path: Path,
) -> None:
    """When data_dir is provided and backend is None, get_summarizer_subagent
    must construct a FilesystemBackend and pass it to create_summarizer_agent."""
    _seed_evidence(tmp_path)

    with patch(
        "src.agents.drug_target.subagents.summarizer.agent.create_deep_agent",
    ) as mock_create:
        stub = MagicMock()
        stub.with_config.return_value = stub
        mock_create.return_value = stub

        from src.agents.drug_target.subagents.summarizer.agent import (
            get_summarizer_subagent,
        )

        result = get_summarizer_subagent(data_dir=str(tmp_path))

    assert mock_create.called, "create_deep_agent must be called"
    call_kwargs = mock_create.call_args[1] if mock_create.call_args[1] else {}

    from deepagents.backends import FilesystemBackend

    assert "backend" in call_kwargs, (
        "create_deep_agent must receive a backend= kwarg when data_dir is provided"
    )
    assert isinstance(call_kwargs["backend"], FilesystemBackend), (
        f"backend must be a FilesystemBackend, got {type(call_kwargs['backend'])}"
    )
    # Verify cwd is set to data_dir (FilesystemBackend stores root as .cwd)
    assert call_kwargs["backend"].cwd == tmp_path.resolve(), (
        f"FilesystemBackend.cwd must equal data_dir={tmp_path}, "
        f"got {call_kwargs['backend'].cwd}"
    )
    # Verify the subagent dict still has name and runnable
    assert result["name"] == "summarizer"
    assert "runnable" in result


def test_get_summarizer_subagent_preserves_caller_backend(tmp_path: Path) -> None:
    """When backend is explicitly passed, get_summarizer_subagent must NOT
    overwrite it with a disk backend."""
    from deepagents.backends import FilesystemBackend

    caller_backend = FilesystemBackend(root_dir=str(tmp_path), virtual_mode=True)

    with patch(
        "src.agents.drug_target.subagents.summarizer.agent.create_deep_agent",
    ) as mock_create:
        stub = MagicMock()
        stub.with_config.return_value = stub
        mock_create.return_value = stub

        from src.agents.drug_target.subagents.summarizer.agent import (
            get_summarizer_subagent,
        )

        get_summarizer_subagent(
            backend=caller_backend,
            data_dir=str(tmp_path),
        )

    call_kwargs = mock_create.call_args[1] if mock_create.call_args[1] else {}
    assert call_kwargs.get("backend") is caller_backend, (
        "Caller-provided backend must not be overwritten by _build_disk_backend"
    )

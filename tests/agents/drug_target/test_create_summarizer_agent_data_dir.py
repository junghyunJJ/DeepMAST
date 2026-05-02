"""RED tests for T0.7a: create_summarizer_agent data_dir kwarg + mutual exclusivity.

Tests:
1. test_data_dir_only_builds_filesystem_backend  — data_dir alone → _build_disk_backend called
2. test_backend_only_does_not_invoke_build_disk_backend — backend= alone → _build_disk_backend NOT called
3. test_neither_backend_nor_data_dir_uses_default — neither → _build_disk_backend NOT called
4. test_both_backend_and_data_dir_raises_valueerror — both → ValueError("pass either")
5. test_get_summarizer_subagent_routes_data_dir_through_factory — get_summarizer_subagent routes
   data_dir to create_summarizer_agent which calls _build_disk_backend exactly once
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stub_model() -> FakeListChatModel:
    """Return a minimal fake model that satisfies create_deep_agent's type checks."""
    return FakeListChatModel(responses=["ok"])


def _make_fake_agent_stub() -> MagicMock:
    """Return a MagicMock that looks like a compiled DeepAgent Runnable."""
    stub = MagicMock()
    stub.with_config.return_value = stub
    return stub


# ---------------------------------------------------------------------------
# Test 1: data_dir alone → _build_disk_backend called once with data_dir value
# ---------------------------------------------------------------------------


def test_data_dir_only_builds_filesystem_backend(tmp_path: Path) -> None:
    """create_summarizer_agent(data_dir=str(tmp_path)) must call _build_disk_backend
    exactly once with str(tmp_path) and forward the returned backend to create_deep_agent.
    """
    from deepagents.backends import FilesystemBackend

    fake_backend = MagicMock(spec=FilesystemBackend)

    with (
        patch(
            "src.agents.drug_target.subagents.summarizer.agent._build_disk_backend",
            return_value=fake_backend,
        ) as mock_build,
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.create_deep_agent",
            return_value=_make_fake_agent_stub(),
        ) as mock_create,
    ):
        from src.agents.drug_target.subagents.summarizer.agent import (
            create_summarizer_agent,
        )

        create_summarizer_agent(
            model=_make_stub_model(),
            data_dir=str(tmp_path),
        )

    mock_build.assert_called_once_with(str(tmp_path))
    create_deep_agent_kwargs = mock_create.call_args[1] if mock_create.call_args[1] else {}
    assert create_deep_agent_kwargs.get("backend") is fake_backend, (
        "The FilesystemBackend returned by _build_disk_backend must be forwarded "
        f"as backend= to create_deep_agent; got {create_deep_agent_kwargs.get('backend')!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: backend= alone → _build_disk_backend NOT called
# ---------------------------------------------------------------------------


def test_backend_only_does_not_invoke_build_disk_backend(tmp_path: Path) -> None:
    """When backend= is explicitly provided, _build_disk_backend must NOT be called."""
    from deepagents.backends import FilesystemBackend

    explicit_backend = FilesystemBackend(root_dir=str(tmp_path), virtual_mode=True)

    with (
        patch(
            "src.agents.drug_target.subagents.summarizer.agent._build_disk_backend",
        ) as mock_build,
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.create_deep_agent",
            return_value=_make_fake_agent_stub(),
        ),
    ):
        from src.agents.drug_target.subagents.summarizer.agent import (
            create_summarizer_agent,
        )

        create_summarizer_agent(
            model=_make_stub_model(),
            backend=explicit_backend,
        )

    mock_build.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: neither backend nor data_dir → _build_disk_backend NOT called
# ---------------------------------------------------------------------------


def test_neither_backend_nor_data_dir_uses_default() -> None:
    """When neither backend= nor data_dir= is given, _build_disk_backend must NOT be
    called (the factory passes backend=None through to create_deep_agent unchanged).
    """
    with (
        patch(
            "src.agents.drug_target.subagents.summarizer.agent._build_disk_backend",
        ) as mock_build,
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.create_deep_agent",
            return_value=_make_fake_agent_stub(),
        ) as mock_create,
    ):
        from src.agents.drug_target.subagents.summarizer.agent import (
            create_summarizer_agent,
        )

        create_summarizer_agent(model=_make_stub_model())

    mock_build.assert_not_called()
    create_deep_agent_kwargs = mock_create.call_args[1] if mock_create.call_args[1] else {}
    assert create_deep_agent_kwargs.get("backend") is None, (
        "backend must remain None when no backend or data_dir is supplied; "
        f"got {create_deep_agent_kwargs.get('backend')!r}"
    )


# ---------------------------------------------------------------------------
# Test 4: both backend= and data_dir= → ValueError
# ---------------------------------------------------------------------------


def test_both_backend_and_data_dir_raises_valueerror(tmp_path: Path) -> None:
    """create_summarizer_agent must raise ValueError when both backend= and
    data_dir= are supplied.  The error message must contain 'pass either'.
    """
    from deepagents.backends import FilesystemBackend

    explicit_backend = FilesystemBackend(root_dir=str(tmp_path), virtual_mode=True)

    with (
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.create_deep_agent",
            return_value=_make_fake_agent_stub(),
        ),
    ):
        from src.agents.drug_target.subagents.summarizer.agent import (
            create_summarizer_agent,
        )

        with pytest.raises(ValueError, match="pass either"):
            create_summarizer_agent(
                model=_make_stub_model(),
                backend=explicit_backend,
                data_dir=str(tmp_path),
            )


# ---------------------------------------------------------------------------
# Test 5: get_summarizer_subagent routes data_dir through the factory
# ---------------------------------------------------------------------------


def test_get_summarizer_subagent_routes_data_dir_through_factory(
    tmp_path: Path,
) -> None:
    """get_summarizer_subagent(data_dir=str(tmp_path)) must cause
    _build_disk_backend to be called exactly once with str(tmp_path).

    This verifies that the local _build_disk_backend call in get_summarizer_subagent
    was removed and the factory (create_summarizer_agent) is now the single call site.
    """
    from deepagents.backends import FilesystemBackend

    fake_backend = MagicMock(spec=FilesystemBackend)

    with (
        patch(
            "src.agents.drug_target.subagents.summarizer.agent._build_disk_backend",
            return_value=fake_backend,
        ) as mock_build,
        patch(
            "src.agents.drug_target.subagents.summarizer.agent.create_deep_agent",
            return_value=_make_fake_agent_stub(),
        ),
    ):
        from src.agents.drug_target.subagents.summarizer.agent import (
            get_summarizer_subagent,
        )

        result = get_summarizer_subagent(data_dir=str(tmp_path))

    mock_build.assert_called_once_with(str(tmp_path))
    assert result["name"] == "summarizer", (
        f"Expected subagent name 'summarizer', got {result['name']!r}"
    )

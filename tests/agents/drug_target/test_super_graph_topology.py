"""Production direct-agent topology plus legacy super-graph compatibility."""

from __future__ import annotations

import importlib
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


# ---------------------------------------------------------------------------
# Production topology and documentation
# ---------------------------------------------------------------------------


@contextmanager
def _reloaded_guarded_export(monkeypatch, environment: dict[str, str | None]):
    """Reload graph_builder against an offline direct-agent factory."""
    import dotenv

    from src.agents.drug_target import agent

    graph_builder = importlib.import_module("src.agents.drug_target.graph_builder")
    configs = []
    create_kwargs = []
    real_factory = agent.create_drug_target_agent

    class FakeRunnable:
        def with_config(self, _config):
            return self

        def get_graph(self):
            return SimpleNamespace(nodes={"direct_agent": object()})

    def fake_create_deep_agent(**kwargs):
        create_kwargs.append(kwargs)
        return FakeRunnable()

    def record_config(config):
        configs.append(config)
        return real_factory(config)

    with monkeypatch.context() as local:
        local.setattr(dotenv, "load_dotenv", lambda: False)
        local.setattr(agent, "create_llm", lambda **_kwargs: object())
        local.setattr(agent, "create_deep_agent", fake_create_deep_agent)
        local.setattr(agent, "create_drug_target_agent", record_config)
        for name, value in environment.items():
            if value is None:
                local.delenv(name, raising=False)
            else:
                local.setenv(name, value)
        importlib.reload(graph_builder)
        yield graph_builder, configs, create_kwargs

    with monkeypatch.context() as local:
        local.setattr(dotenv, "load_dotenv", lambda: False)
        importlib.reload(graph_builder)
    setattr(graph_builder, "load_dotenv", dotenv.load_dotenv)


def test_production_export_is_direct_deep_agent_runnable(monkeypatch) -> None:
    with _reloaded_guarded_export(monkeypatch, {}) as (graph_builder, _, _):
        node_ids = set(graph_builder.drug_target_graph.get_graph().nodes)

        assert "run_deep_agent" not in node_ids
        assert "validate_and_maybe_retry_hypothesis" not in node_ids
        assert "finalize_report" not in node_ids


def test_production_export_uses_environment_guarded_configuration(monkeypatch) -> None:
    with _reloaded_guarded_export(
        monkeypatch,
        {"LLM_PROVIDER": "google", "DRUG_TARGET_DISEASE": "IPF"},
    ) as (_, configs, create_kwargs):
        assert configs[0].provider == "google"
        assert configs[0].disease == "IPF"
        assert configs[0].workflow_mode == "guarded_report"
        assert create_kwargs

    with _reloaded_guarded_export(
        monkeypatch,
        {"LLM_PROVIDER": None, "DRUG_TARGET_DISEASE": None},
    ) as (_, configs, create_kwargs):
        assert configs[0].provider == "openrouter"
        assert configs[0].disease == ""
        assert configs[0].workflow_mode == "guarded_report"
        system_prompt = create_kwargs[0]["system_prompt"]
        assert "load_lr_candidates(data_dir=" in system_prompt
        assert "disease=" not in system_prompt


def test_production_docs_describe_guarded_report_path() -> None:
    root = Path(__file__).parents[3]
    texts = [
        (root / "src/agents/drug_target" / name).read_text(encoding="utf-8")
        for name in ("__init__.py", "graph_builder.py", "integration.py")
    ]
    for production_doc in texts:
        for term in (
            "evidence_assessor",
            "report_writer",
            "DrugReportGuardrailMiddleware",
        ):
            assert term in production_doc
        for obsolete_description in (
            "3 top-level subagents",
            "hypothesis_writer -> summarizer",
            "START -> run_deep_agent -> finalize_report",
        ):
            assert obsolete_description not in production_doc


# ---------------------------------------------------------------------------
# Legacy compatibility super-graph contract (not production topology)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_messages_contract_only_last_ai_message_survives(
    tmp_path,
    monkeypatch,
) -> None:
    """run_deep_agent must return exactly 1 AIMessage; non-AI messages are dropped.

    Strategy: patch create_drug_target_agent (the lazy import inside run_deep_agent)
    to return a fake runnable that yields multiple mixed messages. Pre-write drug.md
    so finalize_report's idempotency guard exits immediately without an LLM call.
    """
    ai_first = AIMessage(content="intermediate reasoning")
    ai_last = AIMessage(content="final answer")
    multi_messages = [
        HumanMessage(content="start"),
        ToolMessage(content="tool result", tool_call_id="tc1"),
        ai_first,
        ai_last,
    ]

    import types

    async def _fake_ainvoke(inp, config=None):
        return {"messages": multi_messages}

    fake_runnable = types.SimpleNamespace(ainvoke=_fake_ainvoke)

    # create_drug_target_agent is imported inside run_deep_agent body at call time;
    # patch at the source module so the local `from … import` resolves to the mock.
    monkeypatch.setattr(
        "src.agents.drug_target.agent.create_drug_target_agent",
        lambda cfg: (fake_runnable, None),
    )

    # Pre-write drug.md so finalize_report's idempotency guard (Decision 12) exits
    # immediately — no LLM call needed and no further patching required.
    (tmp_path / "drug.md").write_text("# pre-existing", encoding="utf-8")

    from src.agents.drug_target.super_graph import build_drug_target_super_graph

    test_graph = build_drug_target_super_graph()

    initial_state = {
        "messages": [],
        "data_dir": str(tmp_path),
        "disease": "test-disease",
        "featured_lr_pairs": None,
        "report_finalization_error": None,
        "evidence_truncated": False,
    }

    final_state = await test_graph.ainvoke(
        initial_state,
        config={"recursion_limit": 100, "configurable": {"thread_id": "test-123"}},
    )

    msgs = final_state["messages"]
    assert len(msgs) == 1, f"Expected 1 message, got {len(msgs)}: {msgs}"
    assert isinstance(msgs[-1], AIMessage), (
        f"Last message must be AIMessage, got {type(msgs[-1])}"
    )
    assert msgs[-1].content == "final answer"


@pytest.mark.asyncio
async def test_run_deep_agent_builds_agent_and_cleans_backend_off_event_loop_thread(
    tmp_path,
    monkeypatch,
) -> None:
    """LangGraph async node must not run sync agent setup/cleanup on MainThread."""
    import types

    build_threads = []
    cleanup_threads = []

    async def _fake_ainvoke(inp, config=None):
        return {"messages": [AIMessage(content="final answer")]}

    class FakeBackend:
        def cleanup(self):
            cleanup_threads.append(threading.current_thread().name)

    def fake_create_agent(cfg):
        build_threads.append(threading.current_thread().name)
        return types.SimpleNamespace(ainvoke=_fake_ainvoke), FakeBackend()

    monkeypatch.setattr(
        "src.agents.drug_target.agent.create_drug_target_agent",
        fake_create_agent,
    )

    from src.agents.drug_target.super_graph import run_deep_agent

    result = await run_deep_agent(
        {
            "messages": [],
            "data_dir": str(tmp_path),
            "disease": "IPF",
            "featured_lr_pairs": None,
            "report_finalization_error": None,
            "evidence_truncated": False,
        },
        {"recursion_limit": 100, "configurable": {"thread_id": "thread-test"}},
    )

    assert result["messages"][0].content == "final answer"
    assert build_threads
    assert threading.main_thread().name not in build_threads
    assert cleanup_threads
    assert threading.main_thread().name not in cleanup_threads


@pytest.mark.asyncio
async def test_messages_contract_with_empty_initial_messages(
    tmp_path,
    monkeypatch,
) -> None:
    """Caller passing messages=[] must still get exactly 1 AIMessage back."""
    ai_msg = AIMessage(content="only answer")

    import types

    async def _fake_ainvoke(inp, config=None):
        return {"messages": [ai_msg]}

    fake_runnable = types.SimpleNamespace(ainvoke=_fake_ainvoke)

    monkeypatch.setattr(
        "src.agents.drug_target.agent.create_drug_target_agent",
        lambda cfg: (fake_runnable, None),
    )

    # idempotency guard so finalize_report is a no-op
    (tmp_path / "drug.md").write_text("# pre-existing", encoding="utf-8")

    from src.agents.drug_target.super_graph import build_drug_target_super_graph

    test_graph = build_drug_target_super_graph()

    initial_state = {
        "messages": [],
        "data_dir": str(tmp_path),
        "disease": "test-disease",
        "featured_lr_pairs": None,
        "report_finalization_error": None,
        "evidence_truncated": False,
    }

    final_state = await test_graph.ainvoke(
        initial_state,
        config={"recursion_limit": 100},
    )

    msgs = final_state["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[-1], AIMessage)

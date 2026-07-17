"""Integration contract for the direct guarded Drug Target agent."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agents.drug_target.middleware import HypothesisRetryLoopMiddleware


EXPECTED_KEYS = {"success", "drug_md", "target_assessment", "errors", "evidence_truncated"}
SUCCESS_ARTIFACTS = (
    "drug.md",
    "target_assessment.json",
    "report_sections.json",
    "part4_candidate_selection.json",
    "part4_therapeutic_synthesis.md",
    "drug_report.html",
    "drug_report_validation_initial.json",
    "drug_report_validation_final.json",
)
PUBLICATION_ARTIFACTS = (
    "part4_candidate_selection.json",
    "part4_therapeutic_synthesis.md",
    "drug_report.html",
)


def _passed_audit(*, publication_status: str = "passed") -> dict:
    return {
        "valid": True,
        "publication": {
            "status": publication_status,
            "artifacts": list(PUBLICATION_ARTIFACTS),
            "error": None,
        },
    }


def _write_success_artifacts(
    data_dir: Path,
    *,
    publication_status: str = "passed",
    missing: str | None = None,
) -> None:
    artifacts = {
        "drug.md": "# Drug report\n",
        "target_assessment.json": json.dumps({"schema_version": "report.v1"}),
        "report_sections.json": json.dumps({"schema_version": "hybrid_report_sections/v1"}),
        "part4_candidate_selection.json": json.dumps({"selected_lr_pairs": []}),
        "part4_therapeutic_synthesis.md": "# Part 4\n",
        "drug_report.html": "<html><body>report</body></html>",
        "drug_report_validation_initial.json": json.dumps(_passed_audit()),
        "drug_report_validation_final.json": json.dumps(
            _passed_audit(publication_status=publication_status)
        ),
    }
    for name, content in artifacts.items():
        if name != missing:
            (data_dir / name).write_text(content, encoding="utf-8")


def test_guarded_report_writer_has_one_sections_write_boundary(tmp_path: Path) -> None:
    from src.agents.drug_target.subagents.configs import get_subagents

    writer = next(
        subagent
        for subagent in get_subagents(data_dir=str(tmp_path), disease="IPF")
        if subagent["name"] == "report_writer"
    )
    tool_names = {tool.name for tool in writer["tools"]}

    assert "save_report_sections" in tool_names
    assert not {
        "build_evidence_summary",
        "save_drug_md",
        "save_target_assessment",
        "save_hypothesis_report",
        "save_report_expansions",
        "render_drug_md_from_expansions",
    } & tool_names
    terminal_save_middleware = [
        middleware
        for middleware in writer["middleware"]
        if isinstance(middleware, HypothesisRetryLoopMiddleware)
        and middleware._stop_after_first_save is True
        and middleware._stop_after_first_successful_save is True
        and middleware._terminal_save_tool_names == ("save_report_sections",)
        and middleware._max_hypothesis_save_attempts == 2
    ]

    assert len(terminal_save_middleware) == 1

    sections_tool = next(
        tool for tool in writer["tools"] if tool.name == "save_report_sections"
    )
    schema = sections_tool.args_schema.model_json_schema()

    def resolve_reference(node):
        while reference := node.get("$ref"):
            assert reference.startswith("#/$defs/")
            resolved = schema.get("$defs", {}).get(
                reference.removeprefix("#/$defs/")
            )
            assert isinstance(resolved, dict)
            node = resolved
        return node

    payload_schema = resolve_reference(schema["properties"]["payload"])
    assert set(payload_schema.get("required", ())) == {
        "schema_version",
        "pipeline_recommendations",
    }
    recommendation_schema = resolve_reference(
        payload_schema["properties"]["pipeline_recommendations"]["items"]
    )
    assert set(recommendation_schema.get("required", ())) == {
        "text",
        "supporting_sources",
    }
    assert recommendation_schema["properties"]["supporting_sources"]["maxItems"] == 5


def test_legacy_hypothesis_writer_retains_legacy_tools_and_prompt(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.subagents.configs import get_legacy_subagents

    writer = next(
        subagent
        for subagent in get_legacy_subagents(data_dir=str(tmp_path), disease="IPF")
        if subagent["name"] == "hypothesis_writer"
    )
    tool_names = {tool.name for tool in writer["tools"]}

    assert "save_hypothesis_report" in tool_names
    assert "save_report_sections" not in tool_names
    assert "save_hypothesis_report" in writer["system_prompt"]


def test_sections_save_failure_clears_stale_markdown(tmp_path: Path) -> None:
    from src.agents.drug_target.production_report_tools import (
        production_save_report_sections_tool,
    )

    stale_markdown = tmp_path / "drug.md"
    stale_markdown.write_text("# stale report\n", encoding="utf-8")

    receipt = json.loads(
        production_save_report_sections_tool(tmp_path, "IPF").invoke(
            {"payload": {"schema_version": "wrong"}}
        )
    )

    assert receipt["saved"] is False
    assert receipt["errors"]
    assert not stale_markdown.exists()


class _FakeBackend:
    def __init__(self, cleanup_threads: list[str]) -> None:
        self._cleanup_threads = cleanup_threads

    def cleanup(self) -> None:
        self._cleanup_threads.append(threading.current_thread().name)


class _FakeAgent:
    def __init__(self, invoke, calls: list[tuple[object, object]]) -> None:
        self._invoke = invoke
        self._calls = calls

    async def ainvoke(self, payload, config=None):
        self._calls.append((payload, config))
        return await self._invoke()


def _install_fake_factory(
    monkeypatch: pytest.MonkeyPatch,
    *,
    invoke,
):
    configs: list[object] = []
    build_threads: list[str] = []
    cleanup_threads: list[str] = []
    calls: list[tuple[object, object]] = []

    def factory(config):
        configs.append(config)
        build_threads.append(threading.current_thread().name)
        return _FakeAgent(invoke, calls), _FakeBackend(cleanup_threads)

    monkeypatch.setattr(
        "src.agents.drug_target.agent.create_drug_target_agent", factory
    )
    return SimpleNamespace(
        configs=configs,
        build_threads=build_threads,
        cleanup_threads=cleanup_threads,
        calls=calls,
    )


async def _run(data_dir: Path, disease: str = "IPF") -> dict:
    from src.agents.drug_target.integration import run_drug_target_assessment

    raw = await run_drug_target_assessment.ainvoke(
        {"data_dir": str(data_dir), "disease": disease}
    )
    return json.loads(raw)


@pytest.mark.asyncio
async def test_integration_constructs_guarded_agent_off_event_loop_and_reads_artifacts_off_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "lr_candidates.json").write_text("[]", encoding="utf-8")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    async def invoke():
        _write_success_artifacts(tmp_path)
        return {"messages": []}

    fake = _install_fake_factory(monkeypatch, invoke=invoke)
    original_read_text = Path.read_text
    read_threads: list[str] = []

    def tracking_read_text(path_self, *args, **kwargs):
        if path_self.name in SUCCESS_ARTIFACTS:
            read_threads.append(threading.current_thread().name)
        return original_read_text(path_self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", tracking_read_text)

    envelope = await _run(tmp_path)

    assert set(envelope) == EXPECTED_KEYS
    assert envelope == {
        "success": True,
        "drug_md": "# Drug report\n",
        "target_assessment": {"schema_version": "report.v1"},
        "errors": [],
        "evidence_truncated": False,
    }
    assert len(fake.configs) == 1
    config = fake.configs[0]
    assert config.data_dir == str(tmp_path.resolve())
    assert config.disease == "IPF"
    assert config.provider == "openrouter"
    assert config.use_checkpointer is False
    assert config.workflow_mode == "guarded_report"
    assert threading.main_thread().name not in fake.build_threads
    assert threading.main_thread().name not in fake.cleanup_threads
    assert read_threads
    assert threading.main_thread().name not in read_threads
    payload, runnable_config = fake.calls[0]
    assert payload["messages"][0]["role"] == "user"
    assert "IPF" in payload["messages"][0]["content"]
    assert runnable_config["recursion_limit"] == 10000
    assert "thread_id" in runnable_config["configurable"]


@pytest.mark.asyncio
async def test_integration_uses_llm_provider_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "lr_candidates.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("LLM_PROVIDER", "google")

    async def invoke():
        _write_success_artifacts(tmp_path)
        return {"messages": []}

    fake = _install_fake_factory(monkeypatch, invoke=invoke)

    assert (await _run(tmp_path))["success"] is True
    assert fake.configs[0].provider == "google"
    assert fake.configs[0].workflow_mode == "guarded_report"


@pytest.mark.asyncio
async def test_integration_requires_nonempty_report_sections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "lr_candidates.json").write_text("[]", encoding="utf-8")

    async def invoke():
        _write_success_artifacts(tmp_path)
        (tmp_path / "report_sections.json").write_text("", encoding="utf-8")
        return {"messages": []}

    _install_fake_factory(monkeypatch, invoke=invoke)

    envelope = await _run(tmp_path)

    assert envelope["success"] is False
    assert envelope["drug_md"] is None
    assert envelope["target_assessment"] is None
    assert envelope["errors"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "final_audit",
    [None, {"valid": False, "publication": {"status": "passed"}}],
)
async def test_invalid_or_missing_final_audit_fails_even_with_drug_markdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    final_audit: dict | None,
) -> None:
    (tmp_path / "lr_candidates.json").write_text("[]", encoding="utf-8")

    async def invoke():
        if final_audit is None:
            (tmp_path / "drug.md").write_text(
                "# stale-looking report\n", encoding="utf-8"
            )
        else:
            _write_success_artifacts(tmp_path)
            (tmp_path / "drug_report_validation_final.json").write_text(
                json.dumps(final_audit), encoding="utf-8"
            )
        return {"messages": []}

    _install_fake_factory(monkeypatch, invoke=invoke)

    envelope = await _run(tmp_path)

    assert set(envelope) == EXPECTED_KEYS
    assert envelope["success"] is False
    assert envelope["drug_md"] is None
    assert envelope["target_assessment"] is None
    assert envelope["errors"]


@pytest.mark.asyncio
async def test_integration_clears_prior_audit_and_outputs_before_a_noop_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "lr_candidates.json").write_text("[]", encoding="utf-8")
    _write_success_artifacts(tmp_path)

    async def invoke():
        assert not any((tmp_path / name).exists() for name in SUCCESS_ARTIFACTS)
        return {"messages": []}

    _install_fake_factory(monkeypatch, invoke=invoke)

    envelope = await _run(tmp_path)

    assert envelope["success"] is False
    assert envelope["errors"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("publication_status", "missing"),
    [("failed", None), ("passed", "part4_therapeutic_synthesis.md"), ("passed", "drug_report.html")],
)
async def test_integration_requires_passed_publication_and_all_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    publication_status: str,
    missing: str | None,
) -> None:
    (tmp_path / "lr_candidates.json").write_text("[]", encoding="utf-8")

    async def invoke():
        _write_success_artifacts(
            tmp_path,
            publication_status=publication_status,
            missing=missing,
        )
        return {"messages": []}

    _install_fake_factory(monkeypatch, invoke=invoke)

    envelope = await _run(tmp_path)

    assert envelope["success"] is False
    assert envelope["drug_md"] is None
    assert envelope["target_assessment"] is None
    assert envelope["errors"]


@pytest.mark.asyncio
async def test_integration_cleans_backend_when_invocation_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "lr_candidates.json").write_text("[]", encoding="utf-8")

    async def invoke():
        raise RuntimeError("agent failed")

    fake = _install_fake_factory(monkeypatch, invoke=invoke)

    envelope = await _run(tmp_path)

    assert envelope["success"] is False
    assert envelope["errors"] == ["agent failed"]
    assert fake.cleanup_threads
    assert threading.main_thread().name not in fake.cleanup_threads

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_deep_interpreter_agent.py"
SPEC = importlib.util.spec_from_file_location("run_deep_interpreter_agent", SCRIPT_PATH)
assert SPEC and SPEC.loader
run_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_script)


def test_standalone_seed_files_and_expected_outputs(tmp_path):
    targets = {"interest_clusters": ["4"], "data_directory": str(tmp_path)}

    run_script._seed_standalone_files(tmp_path, targets)

    assert (tmp_path / "data_path.txt").read_text(encoding="utf-8") == str(tmp_path)
    assert json.loads((tmp_path / "targets.json").read_text(encoding="utf-8")) == targets
    assert run_script._expected_outputs("interpreter", 3) == ["part3_final.md"]
    assert "papers.json" in run_script._expected_outputs("searcher", None)
    assert run_script._missing_outputs(tmp_path, ["data_path.txt", "missing.md"]) == [
        "missing.md"
    ]


def test_interpreter_subagent_message_requires_part(tmp_path):
    try:
        run_script._build_subagent_message("interpreter", tmp_path, {}, None)
    except ValueError as exc:
        assert "--part 1, 2, or 3" in str(exc)
    else:
        raise AssertionError("interpreter without --part should fail")


def test_interpreter_part3_message_is_single_part(tmp_path):
    message = run_script._build_subagent_message("interpreter", tmp_path, {}, 3)

    assert "Part 3 ONLY" in message
    assert "part4_candidate_selection.json" in message
    assert "selected_genes" in message
    assert "selected_lr_pairs" in message
    assert "/part3_final.md" in message
    assert "This is not a generic PPI network summary" in message
    assert "Part 3 ligand-receptor details only" in message
    assert 'write_file with file_path="/part3_final.md"' in message
    assert "chat response only" in message


def test_searcher_message_requests_lr_aware_full_search(tmp_path):
    message = run_script._build_subagent_message("searcher", tmp_path, {}, None)

    assert "max_results=100" in message
    assert "max_iterations=3" in message
    assert "enable_lr_pair_queries=True" in message
    assert "coverage_weighted_sort=True" in message
    assert "Do not pass lr_pairs to create_literature_handoff" in message
    assert "auto-load lr_candidates.json" in message


def test_reporter_message_delegates_reporter_artifacts_to_html_tool(tmp_path):
    message = run_script._build_subagent_message("reporter", tmp_path, {}, None)

    assert 'write_file("/synthesis.md"' in message
    assert 'write_file("/synthesis_validation.json"' not in message
    assert 'write_file("/synthesis_targets.json"' not in message
    assert '"template_mode": "comprehensive"' in message
    assert "generate_html_report writes synthesis_validation.json and synthesis_targets.json" in message


def test_part3_save_retry_only_applies_to_missing_part3_output():
    args = SimpleNamespace(subagent="interpreter", part=3)

    assert run_script._should_retry_part3_save(args, ["part3_final.md"])
    assert not run_script._should_retry_part3_save(args, [])
    assert not run_script._should_retry_part3_save(args, ["part3_final.md", "other.md"])
    assert not run_script._should_retry_part3_save(
        SimpleNamespace(subagent="interpreter", part=2),
        ["part3_final.md"],
    )
    assert not run_script._should_retry_part3_save(
        SimpleNamespace(subagent="reporter", part=3),
        ["part3_final.md"],
    )


def test_part3_save_retry_message_does_not_save_generic_chat_response(tmp_path):
    message = run_script._build_part3_save_retry_message(tmp_path)

    assert "Do not copy or save the previous chat-only response" in message
    assert "/data_path.txt" in message
    assert "/interpretation_guide.md" in message
    assert "/papers.json" in message
    assert "call load_analysis_data for the data directory" in message
    assert "Part 3 ligand-receptor interpretation only" in message
    assert "selected_genes and selected_lr_pairs" in message
    assert "therapeutic synthesis, druggability, drug ranking, and clinical prioritization" in message
    assert (
        'write_file(file_path="/part3_final.md", content=<complete markdown Part 3 report>)'
        in message
    )
    assert "A chat response without that tool call is incomplete." in message


class _Part3RetryAgent:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.calls = 0

    async def ainvoke(self, payload, config=None):
        self.calls += 1
        if self.calls == 2:
            (self.data_dir / "part3_final.md").write_text("# Part 3\n", encoding="utf-8")
        return {"messages": [{"content": payload["messages"][0]["content"]}]}


def _args(tmp_path: Path, part: int) -> SimpleNamespace:
    return SimpleNamespace(
        provider="openai",
        data_dir=str(tmp_path),
        targets_json=None,
        interest_clusters=None,
        interest_celltypes=None,
        sel_factor=None,
        message=None,
        subagent="interpreter",
        part=part,
        dry_run=False,
        disable_summarization=False,
        traceback=False,
    )


def test_run_retries_part3_once_when_expected_output_is_missing(tmp_path, monkeypatch, capsys):
    fake_agent = _Part3RetryAgent(tmp_path)
    monkeypatch.setitem(
        sys.modules,
        "src.agents.deep_interpreter.graph_builder",
        SimpleNamespace(create_subagent_graph=lambda *_args, **_kwargs: fake_agent),
    )

    exit_code = asyncio.run(run_script.run(_args(tmp_path, 3)))

    stdout = capsys.readouterr().out
    assert exit_code == 0
    assert fake_agent.calls == 2
    assert "part3_save_retry_start" in stdout
    assert "invoke_complete" in stdout
    assert (tmp_path / "part3_final.md").exists()


def test_run_does_not_retry_part2_missing_output(tmp_path, monkeypatch):
    fake_agent = _Part3RetryAgent(tmp_path)
    monkeypatch.setitem(
        sys.modules,
        "src.agents.deep_interpreter.graph_builder",
        SimpleNamespace(create_subagent_graph=lambda *_args, **_kwargs: fake_agent),
    )

    exit_code = asyncio.run(run_script.run(_args(tmp_path, 2)))

    assert exit_code == 1
    assert fake_agent.calls == 1

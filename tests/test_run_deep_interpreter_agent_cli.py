from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


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
    assert "generate_html_report" not in message
    assert 'write_file("/synthesis_validation.json"' not in message
    assert 'write_file("/synthesis_targets.json"' not in message
    assert "deterministic code" in message.lower()
    assert "validation" in message
    assert "targets" in message
    assert "HTML" in message


@pytest.mark.parametrize("part", [1, 2, 3])
def test_interpreter_save_retry_applies_to_each_missing_part_output(part):
    args = SimpleNamespace(subagent="interpreter", part=part)
    output = f"part{part}_final.md"

    assert run_script._should_retry_interpreter_save(args, [output])
    assert not run_script._should_retry_interpreter_save(args, [])
    assert not run_script._should_retry_interpreter_save(args, [output, "other.md"])
    assert not run_script._should_retry_interpreter_save(
        SimpleNamespace(subagent="reporter", part=part),
        [output],
    )


def test_interpreter_save_retry_rejects_wrong_part_output():
    args = SimpleNamespace(subagent="interpreter", part=1)

    assert not run_script._should_retry_interpreter_save(
        args,
        ["part2_final.md"],
    )


@pytest.mark.parametrize("part", [1, 2, 3])
def test_interpreter_save_retry_message_continues_prior_context(tmp_path, part):
    message = run_script._build_interpreter_save_retry_message(tmp_path, part)

    assert "Continue the existing Part" in message
    assert "conversation and tool results above" in message
    assert "Do not restart the analysis from scratch" in message
    assert "Reuse an existing load_analysis_data result" in message
    assert "only if no usable result is present" in message
    assert "Do not blindly save a generic or incomplete previous response" in message
    assert f"Part {part} ONLY" in message
    assert f'write_file(file_path="/part{part}_final.md"' in message
    assert "A chat response without that tool call is incomplete." in message


@pytest.mark.parametrize("part", [1, 2, 3])
def test_interpreter_final_save_retry_message_starts_fresh(tmp_path, part):
    message = run_script._build_interpreter_save_retry_message(
        tmp_path,
        part,
        fresh_context=True,
    )

    assert f"Start a fresh Part {part} save recovery" in message
    assert "No prior conversation or tool results are attached" in message
    assert "Call load_analysis_data" in message
    assert "conversation and tool results above" not in message
    assert "Do not restart the analysis from scratch" not in message
    assert f"Part {part} ONLY" in message
    assert f'write_file(file_path="/part{part}_final.md"' in message


def test_part3_retry_message_keeps_selected_pair_and_therapeutic_boundaries(tmp_path):
    message = run_script._build_interpreter_save_retry_message(tmp_path, 3)

    assert "selected_genes" in message
    assert "selected_lr_pairs" in message
    assert "therapeutic synthesis" in message


class _InterpreterRetryAgent:
    def __init__(
        self,
        data_dir: Path,
        *,
        part: int,
        write_on_call: int | None,
    ):
        self.data_dir = data_dir
        self.part = part
        self.write_on_call = write_on_call
        self.calls = 0
        self.payloads = []

    async def ainvoke(self, payload, config=None):
        self.calls += 1
        self.payloads.append(payload)
        if self.calls == self.write_on_call:
            output = self.data_dir / f"part{self.part}_final.md"
            output.write_text(f"# Part {self.part}\n", encoding="utf-8")
        return {
            "messages": [
                *payload["messages"],
                {
                    "role": "assistant",
                    "content": f"attempt-{self.calls}",
                },
                {
                    "role": "tool",
                    "content": f"tool-result-{self.calls}",
                    "tool_call_id": f"tool-call-{self.calls}",
                },
            ]
        }


class _GuardrailFailureAgent:
    async def ainvoke(self, payload, config=None):
        raise RuntimeError(
            "Report guardrail failed with 1 hard error(s); "
            "see /tmp/report_validation_final.json"
        )


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


@pytest.mark.parametrize("part", [1, 2, 3])
def test_run_retries_each_interpreter_part_until_third_total_attempt(
    tmp_path,
    monkeypatch,
    capsys,
    part,
):
    fake_agent = _InterpreterRetryAgent(
        tmp_path,
        part=part,
        write_on_call=3,
    )
    monkeypatch.setitem(
        sys.modules,
        "src.agents.deep_interpreter.graph_builder",
        SimpleNamespace(create_subagent_graph=lambda *_args, **_kwargs: fake_agent),
    )

    exit_code = asyncio.run(run_script.run(_args(tmp_path, part)))

    stdout = capsys.readouterr().out
    assert exit_code == 0
    assert fake_agent.calls == 3
    assert stdout.count(f'"event": "part{part}_save_retry_start"') == 2
    assert '"invoke_attempt_count": 3' in stdout
    assert '"retry_attempt_count": 2' in stdout
    assert "invoke_complete" in stdout
    assert (tmp_path / f"part{part}_final.md").exists()


@pytest.mark.parametrize("part", [1, 2, 3])
def test_run_stops_each_part_after_three_attempts_when_output_is_missing(
    tmp_path,
    monkeypatch,
    capsys,
    part,
):
    fake_agent = _InterpreterRetryAgent(
        tmp_path,
        part=part,
        write_on_call=None,
    )
    monkeypatch.setitem(
        sys.modules,
        "src.agents.deep_interpreter.graph_builder",
        SimpleNamespace(create_subagent_graph=lambda *_args, **_kwargs: fake_agent),
    )

    exit_code = asyncio.run(run_script.run(_args(tmp_path, part)))

    stdout = capsys.readouterr().out
    assert exit_code == 1
    assert fake_agent.calls == 3
    assert stdout.count(f'"event": "part{part}_save_retry_start"') == 2
    assert '"invoke_attempt_count": 3' in stdout
    assert "invoke_incomplete" in stdout


def test_run_carries_history_once_then_uses_fresh_final_retry(
    tmp_path,
    monkeypatch,
    capsys,
):
    fake_agent = _InterpreterRetryAgent(
        tmp_path,
        part=3,
        write_on_call=None,
    )
    monkeypatch.setitem(
        sys.modules,
        "src.agents.deep_interpreter.graph_builder",
        SimpleNamespace(create_subagent_graph=lambda *_args, **_kwargs: fake_agent),
    )

    exit_code = asyncio.run(run_script.run(_args(tmp_path, 3)))

    stdout = capsys.readouterr().out
    assert exit_code == 1
    assert len(fake_agent.payloads) == 3

    initial_messages = fake_agent.payloads[0]["messages"]
    first_retry_messages = fake_agent.payloads[1]["messages"]
    final_retry_messages = fake_agent.payloads[2]["messages"]

    assert first_retry_messages[:-1] == [
        *initial_messages,
        {"role": "assistant", "content": "attempt-1"},
        {
            "role": "tool",
            "content": "tool-result-1",
            "tool_call_id": "tool-call-1",
        },
    ]
    assert "Continue the existing Part 3 attempt" in first_retry_messages[-1]["content"]

    assert len(final_retry_messages) == 1
    assert final_retry_messages[0]["role"] == "user"
    assert "Start a fresh Part 3 save recovery" in final_retry_messages[0]["content"]
    assert "attempt-1" not in final_retry_messages[0]["content"]
    assert "tool-result-1" not in final_retry_messages[0]["content"]
    assert stdout.count('"fresh_context": false') >= 1
    assert stdout.count('"fresh_context": true') >= 1


@pytest.mark.parametrize("part", [1, 2, 3])
def test_run_stops_retry_when_each_part_output_exists(
    tmp_path,
    monkeypatch,
    capsys,
    part,
):
    fake_agent = _InterpreterRetryAgent(
        tmp_path,
        part=part,
        write_on_call=2,
    )
    monkeypatch.setitem(
        sys.modules,
        "src.agents.deep_interpreter.graph_builder",
        SimpleNamespace(create_subagent_graph=lambda *_args, **_kwargs: fake_agent),
    )

    exit_code = asyncio.run(run_script.run(_args(tmp_path, part)))

    stdout = capsys.readouterr().out
    assert exit_code == 0
    assert fake_agent.calls == 2
    assert stdout.count(f'"event": "part{part}_save_retry_start"') == 1
    assert '"invoke_attempt_count": 2' in stdout


def test_run_returns_nonzero_when_report_guardrail_raises(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    fake_agent = _GuardrailFailureAgent()
    monkeypatch.setitem(
        sys.modules,
        "src.agents.deep_interpreter.graph_builder",
        SimpleNamespace(create_subagent_graph=lambda *_args, **_kwargs: fake_agent),
    )

    exit_code = asyncio.run(run_script.run(_args(tmp_path, 3)))

    captured = capsys.readouterr()
    assert exit_code == 1
    assert '"event": "invoke_error"' in captured.err
    assert '"exception_type": "RuntimeError"' in captured.err
    assert "Report guardrail failed with 1 hard error" in captured.err
    assert "part3_save_retry_start" not in captured.out

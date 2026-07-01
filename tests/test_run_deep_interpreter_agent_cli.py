from __future__ import annotations

import importlib.util
import json
from pathlib import Path


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


def test_searcher_message_requests_lr_aware_full_search(tmp_path):
    message = run_script._build_subagent_message("searcher", tmp_path, {}, None)

    assert "max_results=100" in message
    assert "max_iterations=3" in message
    assert "enable_lr_pair_queries=True" in message
    assert "coverage_weighted_sort=True" in message
    assert "Do not pass lr_pairs to create_literature_handoff" in message
    assert "auto-load lr_candidates.json" in message

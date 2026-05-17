from __future__ import annotations

import argparse

import pytest

from scripts import run_drug_target_traced as traced


def test_parse_args_defaults_timeout_to_120():
    args = traced.parse_args([])
    assert args.timeout == 120
    assert args.port is None


def test_parse_args_accepts_port():
    args = traced.parse_args(["--port", "6000"])
    assert args.port == 6000
    assert args.provider == "ollama"


@pytest.mark.parametrize("port", ["0", "70000"])
def test_parse_args_rejects_invalid_port(port: str):
    with pytest.raises(SystemExit):
        traced.parse_args(["--port", port])


def test_parse_args_rejects_port_for_non_ollama_provider():
    with pytest.raises(SystemExit):
        traced.parse_args(["--provider", "openai", "--port", "6000"])


def test_configure_ollama_port_override_sets_env(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)

    args = argparse.Namespace(provider="ollama", port=6000)
    base_url = traced._configure_ollama_port_override(args)

    assert base_url == "http://localhost:6000"
    assert traced.os.environ["OLLAMA_BASE_URL"] == "http://localhost:6000"
    assert traced.os.environ["OLLAMA_HOST"] == "http://localhost:6000"


def test_configure_ollama_port_override_noops_without_port(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:7000")
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:7000")

    args = argparse.Namespace(provider="ollama", port=None)
    base_url = traced._configure_ollama_port_override(args)

    assert base_url is None
    assert traced.os.environ["OLLAMA_BASE_URL"] == "http://localhost:7000"
    assert traced.os.environ["OLLAMA_HOST"] == "http://localhost:7000"


def test_inspect_report_outputs_rejects_unexpanded_drug_md(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text("{}", encoding="utf-8")
    (tmp_path / "target_assessment.json").write_text("{}", encoding="utf-8")
    (tmp_path / "drug_report.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "drug.md").write_text("intro\n<!-- EXPAND: unfinished -->\n", encoding="utf-8")
    trace_log = tmp_path / "trace.log"
    trace_log.write_text(
        "content='{\"valid\": true}' name='validate_drug_md'\n"
        "AIMessage(content='SUMMARIZER_STATUS: PASS')\n",
        encoding="utf-8",
    )

    status = traced._inspect_report_outputs(tmp_path, trace_log)

    assert status["finalized"] is False
    assert status["drug_md_exists"] is True
    assert status["expand_marker_count"] == 1
    assert "no EXPAND markers" in status["missing_requirements"]


def test_inspect_report_outputs_accepts_validated_final_report(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text("{}", encoding="utf-8")
    (tmp_path / "target_assessment.json").write_text("{}", encoding="utf-8")
    (tmp_path / "drug.md").write_text("# Complete report\nNo placeholders.\n", encoding="utf-8")
    (tmp_path / "drug_report.html").write_text("<html></html>", encoding="utf-8")
    trace_log = tmp_path / "trace.log"
    trace_log.write_text(
        "content='{\"valid\": true}' name='validate_drug_md'\n"
        "AIMessage(content='SUMMARIZER_STATUS: PASS')\n",
        encoding="utf-8",
    )

    status = traced._inspect_report_outputs(tmp_path, trace_log)

    assert status["finalized"] is True
    assert status["missing_requirements"] == []


def test_inspect_report_outputs_accepts_structured_validate_tool_marker(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text("{}", encoding="utf-8")
    (tmp_path / "target_assessment.json").write_text("{}", encoding="utf-8")
    (tmp_path / "drug.md").write_text("# Complete report\nNo placeholders.\n", encoding="utf-8")
    (tmp_path / "drug_report.html").write_text("<html></html>", encoding="utf-8")
    trace_log = tmp_path / "trace.log"
    trace_log.write_text(
        "tool_calls=[validate_drug_md]\n"
        'tool: {"valid": true, "issues": []}...\n'
        "AIMessage(content='SUMMARIZER_STATUS: PASS')\n",
        encoding="utf-8",
    )

    status = traced._inspect_report_outputs(tmp_path, trace_log)

    assert status["validate_drug_md_passed"] is True
    assert status["finalized"] is True
    assert status["missing_requirements"] == []

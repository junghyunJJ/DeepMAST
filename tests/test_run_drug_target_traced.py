from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

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


def test_summarizer_stream_budget_only_applies_after_summarizer_starts():
    assert traced._is_summarizer_stream_node("report_writer > summarizer", "tools")
    assert traced._is_summarizer_stream_node("report_writer", "summarizer")
    assert not traced._is_summarizer_stream_node("evidence_assessor", "tools")

    assert not traced._summarizer_budget_exceeded(None, 200.0, 60)
    assert not traced._summarizer_budget_exceeded(100.0, 159.9, 60)
    assert traced._summarizer_budget_exceeded(100.0, 160.0, 60)


def test_hypothesis_stream_budget_only_applies_after_hypothesis_writer_starts():
    assert traced._is_hypothesis_writer_stream_node(
        "tools > task > hypothesis_writer",
        "model",
    )
    assert traced._is_hypothesis_writer_stream_node("tools > task", "hypothesis_writer")
    assert not traced._is_hypothesis_writer_stream_node("report_writer", "summarizer")


def test_evidence_ready_for_hypothesis_requires_stage3_candidates_and_files(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "MUC1"}, {"gene": "FN1"}]}),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_filter_results.json").write_text("[]", encoding="utf-8")
    (evidence_dir / "stage3_MUC1.json").write_text("{}", encoding="utf-8")

    assert traced._evidence_ready_for_hypothesis(tmp_path) is False

    (evidence_dir / "stage3_FN1.json").write_text("{}", encoding="utf-8")

    assert traced._evidence_ready_for_hypothesis(tmp_path) is True


def test_artifact_predates_run_when_mtime_is_older(tmp_path):
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}", encoding="utf-8")

    assert traced._artifact_predates_run(artifact, artifact.stat().st_mtime + 1)
    assert not traced._artifact_predates_run(artifact, artifact.stat().st_mtime - 1)
    assert traced._artifact_predates_run(tmp_path / "missing.json", 0)


def test_host_hypothesis_fallback_rewrites_failed_suffix_fixture(tmp_path):
    fixture_evidence = (
        Path(__file__).resolve().parent
        / "agents"
        / "drug_target"
        / "fixtures"
        / "baseline_hallucinated"
        / "evidence"
    )
    shutil.copytree(fixture_evidence, tmp_path / "evidence")
    stale = (tmp_path / "evidence" / "hypothesis_report.json").read_text(
        encoding="utf-8"
    )
    assert "_FAILED" in stale
    trace_log = tmp_path / "trace.log"
    trace_log.write_text("", encoding="utf-8")

    result = traced._run_host_hypothesis_fallback(
        tmp_path,
        "idiopathic pulmonary fibrosis",
        trace_log,
    )

    assert result["saved"] is True, result
    saved = json.loads((tmp_path / "evidence" / "hypothesis_report.json").read_text())
    assert "_FAILED" not in json.dumps(saved)

    candidates = {
        row["gene"].upper()
        for row in json.loads(
            (tmp_path / "evidence" / "assessment_results.json").read_text()
        )["stage3_candidates"]
    }
    covered = {
        gene.upper()
        for hyp in saved["hypotheses"]
        for gene in hyp["biological_entities"]["genes"]
    }
    assert candidates <= covered

    pass_map = {
        f"{row['ligand'].upper()}--{row['receptor'].upper()}": bool(row["passed"])
        for row in json.loads(
            (tmp_path / "evidence" / "stage1_filter_results.json").read_text()
        )
    }
    for hyp in saved["hypotheses"]:
        for detail in hyp["evidence_reference_details"]:
            filename = detail["filename"]
            if not filename.startswith("stage1_"):
                continue
            pair = filename.removeprefix("stage1_").removesuffix(".json")
            if detail["usage"] in {"primary", "supporting"}:
                assert pass_map[pair] is True


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


def test_inspect_report_outputs_accepts_validated_final_report(tmp_path, monkeypatch):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text("{}", encoding="utf-8")
    (tmp_path / "target_assessment.json").write_text("{}", encoding="utf-8")
    (tmp_path / "drug.md").write_text("# Complete report\nNo placeholders.\n", encoding="utf-8")
    (tmp_path / "drug_report.html").write_text("<html></html>", encoding="utf-8")
    trace_log = tmp_path / "trace.log"
    trace_log.write_text(
        "AIMessage(content='SUMMARIZER_STATUS: FAIL')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        traced,
        "_validate_report_finalization",
        lambda data_dir: {"valid": True, "issue_count": 0, "issues": []},
        raising=False,
    )

    status = traced._inspect_report_outputs(tmp_path, trace_log)

    assert status["finalized"] is True
    assert status["report_finalization_valid"] is True
    assert status["summarizer_status_passed"] is False
    assert status["missing_requirements"] == []


def test_inspect_report_outputs_rejects_trace_pass_without_host_finalization(
    tmp_path,
    monkeypatch,
):
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
    monkeypatch.setattr(
        traced,
        "_validate_report_finalization",
        lambda data_dir: {
            "valid": False,
            "issue_count": 1,
            "issues": [{"code": "HOST_VALIDATOR_FAILED"}],
        },
        raising=False,
    )

    status = traced._inspect_report_outputs(tmp_path, trace_log)

    assert status["validate_drug_md_passed"] is False
    assert status["report_finalization_valid"] is False
    assert status["finalized"] is False
    assert "validate_drug_report_finalization valid=true" in status["missing_requirements"]


def test_host_template_finalization_writes_valid_report_artifacts(tmp_path):
    fixture_evidence = (
        Path(__file__).resolve().parent
        / "agents"
        / "drug_target"
        / "fixtures"
        / "baseline_hallucinated"
        / "evidence"
    )
    shutil.copytree(fixture_evidence, tmp_path / "evidence")
    (tmp_path / "evidence" / "known_drugs.json").write_text("[]", encoding="utf-8")
    assessment_path = tmp_path / "evidence" / "assessment_results.json"
    assessment = json.loads(assessment_path.read_text(encoding="utf-8"))
    assessment["disease"] = "idiopathic pulmonary fibrosis"
    assessment_path.write_text(json.dumps(assessment, indent=2), encoding="utf-8")
    hypothesis_path = tmp_path / "evidence" / "hypothesis_report.json"
    hypothesis = json.loads(hypothesis_path.read_text(encoding="utf-8"))
    hypothesis["hypotheses"] = [
        hyp
        for hyp in hypothesis.get("hypotheses", [])
        if "_FAILED" not in json.dumps(hyp)
    ]
    hypothesis_path.write_text(json.dumps(hypothesis, indent=2), encoding="utf-8")
    (tmp_path / "lr_candidates.json").write_text(
        json.dumps(
            {
                "disease": "idiopathic pulmonary fibrosis",
                "pairs": [
                    {"ligand": "FN1", "receptor": "SDC2"},
                    {"ligand": "HLA-DQB1", "receptor": "CD4"},
                    {"ligand": "ICAM1", "receptor": "EZR"},
                    {"ligand": "ICAM1", "receptor": "ITGB2"},
                    {"ligand": "ICAM1", "receptor": "MUC1"},
                    {"ligand": "THBS1", "receptor": "CD47"},
                ],
            }
        ),
        encoding="utf-8",
    )
    trace_log = tmp_path / "trace.log"
    trace_log.write_text("", encoding="utf-8")

    result = traced._run_host_template_finalization(tmp_path, trace_log)

    assert result["finalized"] is True, result
    assert (tmp_path / "drug.md").exists()
    assert (tmp_path / "drug_report.html").exists()
    assert (tmp_path / "target_assessment.json").exists()
    drug_md = (tmp_path / "drug.md").read_text(encoding="utf-8")
    assert "<!-- EXPAND:" not in drug_md
    assert "Scope note: Stage 1 Census evidence for these hypotheses is labeled pulmonary fibrosis" in drug_md

    status = traced._inspect_report_outputs(tmp_path, trace_log)
    assert status["finalized"] is True, status

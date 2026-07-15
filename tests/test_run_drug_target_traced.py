from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import pytest

from scripts import run_drug_target_traced as traced


def test_parse_args_defaults_timeout_to_120():
    args = traced.parse_args([])
    assert args.timeout == 120
    assert args.port == traced.DEFAULT_OLLAMA_PORT


def test_parse_args_accepts_port():
    args = traced.parse_args(["--port", "6000"])
    assert args.port == 6000
    assert args.provider == "ollama"


def test_parse_args_accepts_vllm_port_and_generation_options():
    args = traced.parse_args(
        [
            "--provider",
            "vllm",
            "--port",
            "7001",
            "--model",
            "Qwen/Qwen3.5-122B-A10B-FP8",
            "--max-tokens",
            "16384",
            "--enable-thinking",
        ]
    )

    assert args.provider == "vllm"
    assert args.port == 7001
    assert args.model == "Qwen/Qwen3.5-122B-A10B-FP8"
    assert args.max_tokens == 16384
    assert args.enable_thinking is True


def test_parse_args_accepts_ollama_cloud_model():
    args = traced.parse_args(["--model", "qwen3.5:397b-cloud"])

    assert args.model == "qwen3.5:397b-cloud"


@pytest.mark.parametrize("port", ["0", "70000"])
def test_parse_args_rejects_invalid_port(port: str):
    with pytest.raises(SystemExit):
        traced.parse_args(["--port", port])


def test_parse_args_rejects_port_for_non_ollama_provider():
    with pytest.raises(SystemExit):
        traced.parse_args(["--provider", "openai", "--port", "6000"])


def test_parse_args_allows_non_ollama_provider_without_explicit_port():
    args = traced.parse_args(["--provider", "openai"])

    assert args.provider == "openai"
    assert args.port is None


def test_configure_ollama_port_override_sets_env(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setenv("SUBAGENT_HYPOTHESIS_WRITER_PROVIDER", "ollama")
    monkeypatch.setenv("SUBAGENT_HYPOTHESIS_WRITER_BASE_URL", "http://localhost:11434")

    args = argparse.Namespace(provider="ollama", port=6000)
    base_url = traced._configure_ollama_port_override(args)

    assert base_url == "http://localhost:6000"
    assert traced.os.environ["OLLAMA_BASE_URL"] == "http://localhost:6000"
    assert traced.os.environ["OLLAMA_HOST"] == "http://localhost:6000"
    assert (
        traced.os.environ["SUBAGENT_HYPOTHESIS_WRITER_BASE_URL"]
        == "http://localhost:6000"
    )


def test_configure_ollama_port_override_defaults_to_ollama_default(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    args = argparse.Namespace(provider="ollama", port=None)

    base_url = traced._configure_ollama_port_override(args)

    assert base_url == "http://localhost:11434"
    assert traced.os.environ["OLLAMA_BASE_URL"] == "http://localhost:11434"
    assert traced.os.environ["OLLAMA_HOST"] == "http://localhost:11434"


def test_configure_ollama_port_override_noops_for_non_ollama_provider(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:7000")
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:7000")
    args = argparse.Namespace(provider="openai", port=None)

    base_url = traced._configure_ollama_port_override(args)

    assert base_url is None
    assert traced.os.environ["OLLAMA_BASE_URL"] == "http://localhost:7000"
    assert traced.os.environ["OLLAMA_HOST"] == "http://localhost:7000"


def test_configure_ollama_port_override_sets_vllm_base_url_without_ollama_host(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    args = argparse.Namespace(provider="vllm", port=7001)

    base_url = traced._configure_ollama_port_override(args)

    assert base_url == "http://localhost:7001"
    assert traced.os.environ["OLLAMA_BASE_URL"] == "http://localhost:7001"
    assert "OLLAMA_HOST" not in traced.os.environ


def test_configure_provider_env_sets_llm_provider(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    args = argparse.Namespace(provider="ollama")

    traced._configure_provider_env(args)

    assert traced.os.environ["LLM_PROVIDER"] == "ollama"


def test_configure_provider_env_sets_cli_model_for_ollama(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    args = argparse.Namespace(provider="ollama", model="qwen3.5:397b-cloud")

    traced._configure_provider_env(args)

    assert traced.os.environ["LLM_PROVIDER"] == "ollama"
    assert traced.os.environ["LLM_MODEL"] == "qwen3.5:397b-cloud"
    assert traced.os.environ["OLLAMA_MODEL"] == "qwen3.5:397b-cloud"


def test_configure_provider_env_sets_vllm_generation_env(monkeypatch):
    for key in (
        "LLM_PROVIDER",
        "LLM_MODEL",
        "OLLAMA_MODEL",
        "VLLM_MAX_TOKENS",
        "OLLAMA_OPENAI_MAX_TOKENS",
        "VLLM_ENABLE_THINKING",
        "OLLAMA_OPENAI_ENABLE_THINKING",
    ):
        monkeypatch.delenv(key, raising=False)
    args = argparse.Namespace(
        provider="vllm",
        model="Qwen/Qwen3.5-122B-A10B-FP8",
        max_tokens=16384,
        enable_thinking=False,
    )

    traced._configure_provider_env(args)

    assert traced.os.environ["LLM_PROVIDER"] == "vllm"
    assert traced.os.environ["LLM_MODEL"] == "Qwen/Qwen3.5-122B-A10B-FP8"
    assert traced.os.environ["OLLAMA_MODEL"] == "Qwen/Qwen3.5-122B-A10B-FP8"
    assert traced.os.environ["VLLM_MAX_TOKENS"] == "16384"
    assert traced.os.environ["OLLAMA_OPENAI_MAX_TOKENS"] == "16384"
    assert traced.os.environ["VLLM_ENABLE_THINKING"] == "false"
    assert traced.os.environ["OLLAMA_OPENAI_ENABLE_THINKING"] == "false"


def test_finalize_report_config_forwards_provider(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)

    args = argparse.Namespace(provider="ollama")
    config = traced._finalize_report_config(args)

    assert config == {
        "recursion_limit": 100,
        "configurable": {"llm_provider": "ollama"},
    }


def test_finalize_report_config_forwards_llm_model(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "qwen3.5:122b")

    args = argparse.Namespace(provider="ollama")
    config = traced._finalize_report_config(args)

    assert config == {
        "recursion_limit": 100,
        "configurable": {
            "llm_provider": "ollama",
            "llm_model": "qwen3.5:122b",
        },
    }


def test_finalize_report_config_prefers_cli_model(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "qwen3.5:122b")

    args = argparse.Namespace(provider="ollama", model="qwen3.5:397b-cloud")
    config = traced._finalize_report_config(args)

    assert config == {
        "recursion_limit": 100,
        "configurable": {
            "llm_provider": "ollama",
            "llm_model": "qwen3.5:397b-cloud",
        },
    }


def test_capture_hypothesis_quality_state_records_gate_fields():
    holder = {
        "report_finalization_error": None,
        "evidence_truncated": False,
    }
    result = {
        "hypothesis_quality_valid": False,
        "hypothesis_quality_errors": [
            {
                "code": "MISSING_REQUIRED_CATEGORIES",
                "message": "Hypothesis report is missing required thematic categories.",
                "missing": ["Novel Pathway"],
            }
        ],
        "hypothesis_retry_attempted": True,
        "hypothesis_retry_attempts": 2,
        "hypothesis_retry_status": "failed",
        "hypothesis_retry_error": None,
        "report_finalization_error": "HYPOTHESIS_QUALITY_GATE_FAILED: missing category",
    }

    traced._capture_hypothesis_quality_state(result, holder)

    assert holder["hypothesis_quality_valid"] is False
    assert holder["hypothesis_retry_attempted"] is True
    assert holder["hypothesis_retry_attempts"] == 2
    assert holder["hypothesis_retry_status"] == "failed"
    assert holder["report_finalization_error"].startswith("HYPOTHESIS_QUALITY_GATE_FAILED")


def test_should_finalize_requires_passing_hypothesis_quality_gate():
    assert traced._should_finalize_after_hypothesis_quality(
        {"hypothesis_quality_valid": True}
    )
    assert not traced._should_finalize_after_hypothesis_quality(
        {"hypothesis_quality_valid": False}
    )
    assert not traced._should_finalize_after_hypothesis_quality({})


def test_remaining_timeout_seconds_clamps_at_zero():
    assert traced._remaining_timeout_seconds(100.0, 120.0, now=110.0) == 110.0
    assert traced._remaining_timeout_seconds(100.0, 120.0, now=220.0) == 0.0
    assert traced._remaining_timeout_seconds(100.0, 120.0, now=230.0) == 0.0


def test_record_hypothesis_quality_timeout_blocks_finalization_and_preserves_attempts():
    holder: dict[str, object] = {"hypothesis_retry_attempts": 2}

    traced._record_hypothesis_quality_timeout(
        holder,
        "CLI timeout reached during hypothesis quality gate.",
        attempted=True,
    )

    assert holder["hypothesis_quality_valid"] is False
    assert holder["hypothesis_retry_attempted"] is True
    assert holder["hypothesis_retry_attempts"] == 2
    assert holder["hypothesis_retry_status"] == "timeout"
    assert holder["hypothesis_retry_error"] == "CLI timeout reached during hypothesis quality gate."
    quality_errors = holder["hypothesis_quality_errors"]
    assert isinstance(quality_errors, list)
    assert isinstance(quality_errors[0], dict)
    assert quality_errors[0]["code"] == "HYPOTHESIS_QUALITY_GATE_TIMEOUT"
    finalization_error = holder["report_finalization_error"]
    assert isinstance(finalization_error, str)
    assert finalization_error.startswith("HYPOTHESIS_QUALITY_GATE_FAILED")
    assert not traced._should_finalize_after_hypothesis_quality(holder)


def test_record_hypothesis_quality_timeout_reports_at_least_one_started_attempt():
    holder: dict[str, object] = {}

    traced._record_hypothesis_quality_timeout(
        holder,
        "CLI timeout reached during hypothesis quality gate.",
        attempted=True,
    )

    assert holder["hypothesis_retry_attempted"] is True
    assert holder["hypothesis_retry_attempts"] == 1
    assert holder["hypothesis_retry_status"] == "timeout"


def test_hypothesis_stream_budget_only_applies_after_hypothesis_writer_starts():
    assert traced._is_hypothesis_writer_stream_node(
        "tools > task > hypothesis_writer",
        "model",
    )
    assert traced._is_hypothesis_writer_stream_node("tools > task", "hypothesis_writer")
    assert not traced._is_hypothesis_writer_stream_node("report_writer", "summarizer")


def test_hypothesis_stream_budget_defaults_to_900(monkeypatch):
    monkeypatch.delenv("DRUG_TARGET_HYPOTHESIS_STREAM_BUDGET_SECONDS", raising=False)

    assert traced._hypothesis_stream_budget_seconds() == 900


def test_hypothesis_stream_budget_respects_env_override(monkeypatch):
    monkeypatch.setenv("DRUG_TARGET_HYPOTHESIS_STREAM_BUDGET_SECONDS", "1200")

    assert traced._hypothesis_stream_budget_seconds() == 1200


def test_hypothesis_stream_budget_invalid_env_falls_back_to_900(monkeypatch):
    monkeypatch.setenv("DRUG_TARGET_HYPOTHESIS_STREAM_BUDGET_SECONDS", "not-a-number")

    assert traced._hypothesis_stream_budget_seconds() == 900


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


def test_should_invoke_finalize_when_drug_md_predates_fresh_hypothesis_report(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    drug_md = tmp_path / "drug.md"
    hypothesis_report = evidence_dir / "hypothesis_report.json"
    drug_md.write_text("stale report", encoding="utf-8")
    hypothesis_report.write_text("{}", encoding="utf-8")
    run_started_at = 100.0
    os.utime(drug_md, (run_started_at - 10, run_started_at - 10))
    os.utime(hypothesis_report, (run_started_at + 10, run_started_at + 10))

    assert traced._should_invoke_finalize_report(tmp_path, run_started_at)


def test_should_not_invoke_finalize_when_drug_md_is_current(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    drug_md = tmp_path / "drug.md"
    hypothesis_report = evidence_dir / "hypothesis_report.json"
    target_assessment = tmp_path / "target_assessment.json"
    drug_html = tmp_path / "drug_report.html"
    report_validation = tmp_path / "report_validation.json"
    drug_md.write_text("fresh report", encoding="utf-8")
    hypothesis_report.write_text("{}", encoding="utf-8")
    target_assessment.write_text("{}", encoding="utf-8")
    drug_html.write_text("<html></html>", encoding="utf-8")
    report_validation.write_text('{"valid": true}', encoding="utf-8")
    run_started_at = 100.0
    os.utime(hypothesis_report, (run_started_at + 5, run_started_at + 5))
    os.utime(drug_md, (run_started_at + 10, run_started_at + 10))
    os.utime(target_assessment, (run_started_at + 10, run_started_at + 10))
    os.utime(drug_html, (run_started_at + 10, run_started_at + 10))
    os.utime(report_validation, (run_started_at + 10, run_started_at + 10))

    assert not traced._should_invoke_finalize_report(tmp_path, run_started_at)


def test_should_invoke_finalize_when_required_report_artifact_missing(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    drug_md = tmp_path / "drug.md"
    hypothesis_report = evidence_dir / "hypothesis_report.json"
    target_assessment = tmp_path / "target_assessment.json"
    report_validation = tmp_path / "report_validation.json"
    drug_md.write_text("fresh report", encoding="utf-8")
    hypothesis_report.write_text("{}", encoding="utf-8")
    target_assessment.write_text("{}", encoding="utf-8")
    report_validation.write_text('{"valid": true}', encoding="utf-8")
    run_started_at = 100.0
    os.utime(hypothesis_report, (run_started_at + 5, run_started_at + 5))
    os.utime(drug_md, (run_started_at + 10, run_started_at + 10))
    os.utime(target_assessment, (run_started_at + 10, run_started_at + 10))
    os.utime(report_validation, (run_started_at + 10, run_started_at + 10))

    assert traced._should_invoke_finalize_report(tmp_path, run_started_at)


def test_should_invoke_finalize_when_report_validation_predates_hypothesis(tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    drug_md = tmp_path / "drug.md"
    hypothesis_report = evidence_dir / "hypothesis_report.json"
    target_assessment = tmp_path / "target_assessment.json"
    drug_html = tmp_path / "drug_report.html"
    report_validation = tmp_path / "report_validation.json"
    drug_md.write_text("fresh report", encoding="utf-8")
    hypothesis_report.write_text("{}", encoding="utf-8")
    target_assessment.write_text("{}", encoding="utf-8")
    drug_html.write_text("<html></html>", encoding="utf-8")
    report_validation.write_text('{"valid": true}', encoding="utf-8")
    run_started_at = 100.0
    os.utime(report_validation, (run_started_at + 3, run_started_at + 3))
    os.utime(target_assessment, (run_started_at + 4, run_started_at + 4))
    os.utime(hypothesis_report, (run_started_at + 5, run_started_at + 5))
    os.utime(drug_html, (run_started_at + 10, run_started_at + 10))
    os.utime(drug_md, (run_started_at + 10, run_started_at + 10))

    assert traced._should_invoke_finalize_report(tmp_path, run_started_at)


def test_should_not_print_finalize_skip_note_when_finalize_ran():
    report_status = {"finalized": True}

    assert not traced._should_print_finalize_skip_note(
        report_status,
        pre_run_drug_md_exists=True,
        finalize_report_invoked=True,
    )


def test_should_print_finalize_skip_note_when_existing_report_was_reused():
    report_status = {"finalized": True}

    assert traced._should_print_finalize_skip_note(
        report_status,
        pre_run_drug_md_exists=True,
        finalize_report_invoked=False,
    )


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
    assert saved["host_finalized"] is True
    assert saved["fallback_quality"] == "degraded"
    assert "_FAILED" not in json.dumps(saved)
    assert len(saved["hypotheses"]) <= 6

    from src.agents.drug_target.tools.hypothesis_schema import (
        validate_hypothesis_report_quality,
    )

    quality = validate_hypothesis_report_quality(str(tmp_path))
    assert quality["valid"] is True, quality

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


def test_pre_quality_recovery_rewrites_fresh_invalid_native_report(
    tmp_path,
    monkeypatch,
):
    fixture_evidence = (
        Path(__file__).resolve().parent
        / "agents"
        / "drug_target"
        / "fixtures"
        / "baseline_hallucinated"
        / "evidence"
    )
    shutil.copytree(fixture_evidence, tmp_path / "evidence")
    report_path = tmp_path / "evidence" / "hypothesis_report.json"
    run_started_at = report_path.stat().st_mtime - 1
    trace_log = tmp_path / "trace.log"
    trace_log.write_text("", encoding="utf-8")
    monkeypatch.setenv("DRUG_TARGET_ENABLE_HOST_HYPOTHESIS_FALLBACK", "recovery")

    result = traced._maybe_run_host_hypothesis_fallback_before_quality(
        tmp_path,
        "idiopathic pulmonary fibrosis",
        trace_log,
        run_started_at,
    )

    assert result["host_hypothesis_fallback_used"] is True, result
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["host_finalized"] is True
    assert saved["fallback_quality"] == "degraded"
    assert "_FAILED" not in json.dumps(saved)
    assert "pre-quality validation failed" in trace_log.read_text(encoding="utf-8")


def test_host_hypothesis_fallback_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DRUG_TARGET_ENABLE_HOST_HYPOTHESIS_FALLBACK", raising=False)

    assert traced._host_hypothesis_fallback_enabled() is False


def test_runner_delegates_hypothesis_retry_to_graph_quality_gate():
    source = Path(traced.__file__).read_text(encoding="utf-8")

    assert "validate_and_maybe_retry_hypothesis" in source
    assert "_build_hypothesis_retry_message" not in source
    assert "_build_early_retry_message" not in source
    assert "[HYPOTHESIS-FIXUP]" not in source
    assert "[RETRY] Early termination" not in source


def test_check_hypothesis_completion_requires_retry_not_summarizer(tmp_path):
    from src.agents.drug_target.tools.evidence_loader import check_hypothesis_completion

    (tmp_path / "evidence").mkdir()
    result = json.loads(check_hypothesis_completion.invoke({"data_dir": str(tmp_path)}))

    assert result["hypothesis_complete"] is False
    assert "retry hypothesis_writer" in result["recommendation"]
    assert "Proceed to summarizer" not in result["recommendation"]


def test_template_expansion_fallback_uses_slot_specific_provenance(tmp_path):
    spec = {
        "schema_version": "report_expansions.v1",
        "required_slot_ids": [
            "section:preclinical|slot:screening",
            "section:clinical|slot:approved_drugs",
        ],
        "example_sentence": {
            "source_provenance": {
                "source_file": "evidence/ot_CD4.json",
                "source_field": "clinical_drugs",
                "source_class": "opentargets_clinical",
                "claim_type": "direct_value",
                "source_value": ["ibalizumab"],
            }
        },
        "valid_provenance_keys": [
            "evidence/ot_CD4.json::clinical_drugs",
            "evidence/stage3_CD4.json::preclinical_compounds",
        ],
    }
    (tmp_path / "drug_report_reference_card.json").write_text(
        json.dumps(
            {
                "provenance_index": {
                    "evidence/ot_CD4.json::clinical_drugs": {
                        "source_file": "evidence/ot_CD4.json",
                        "source_field": "clinical_drugs",
                        "source_class": "opentargets_clinical",
                        "source_value": ["ibalizumab"],
                    },
                    "evidence/stage3_CD4.json::preclinical_compounds": {
                        "source_file": "evidence/stage3_CD4.json",
                        "source_field": "preclinical_compounds",
                        "source_class": "chembl_preclinical",
                        "source_value": ["CHEMBL123"],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    spec_path = tmp_path / "expansion_schema_spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    payload = traced._build_template_expansions(spec_path)
    sentences = [slot["sentences"][0] for slot in payload["slots"]]

    assert {
        sentence["source_provenance"]["source_file"] for sentence in sentences
    } == {"evidence/ot_CD4.json", "evidence/stage3_CD4.json"}
    assert "[source: chembl_preclinical:preclinical_compounds]" in sentences[0]["text"]
    assert "[source: opentargets_clinical:clinical_drugs]" in sentences[1]["text"]
    assert all("fallback_quality" not in sentence for sentence in sentences)


def test_template_expansion_fallback_marks_degraded_without_slot_match(tmp_path):
    spec = {
        "schema_version": "report_expansions.v1",
        "required_slot_ids": ["section:hypothesis|slot:therapeutic_implications"],
        "example_sentence": {
            "source_provenance": {
                "source_file": "evidence/ot_CD4.json",
                "source_field": "clinical_drugs",
                "source_class": "opentargets_clinical",
                "claim_type": "direct_value",
                "source_value": ["ibalizumab"],
            }
        },
        "valid_provenance_keys": ["evidence/ot_CD4.json::clinical_drugs"],
    }
    (tmp_path / "drug_report_reference_card.json").write_text(
        json.dumps(
            {
                "expansion_slots": [
                    {
                        "slot_id": "section:hypothesis|slot:therapeutic_implications",
                        "section": "hypothesis",
                        "slot": "therapeutic_implications",
                    }
                ],
                "provenance_index": {
                    "evidence/ot_CD4.json::clinical_drugs": {
                        "source_file": "evidence/ot_CD4.json",
                        "source_field": "clinical_drugs",
                        "source_class": "opentargets_clinical",
                        "source_value": ["ibalizumab"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    spec_path = tmp_path / "expansion_schema_spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    payload = traced._build_template_expansions(spec_path)
    sentence = payload["slots"][0]["sentences"][0]

    assert sentence["fallback_quality"] == "degraded"
    assert sentence["fallback_reason"] == "no_slot_specific_provenance_match"


def test_inspect_report_outputs_rejects_unexpanded_drug_md(tmp_path):
    """drug.md with EXPAND markers is not finalized — artifact-existence check."""
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text("{}", encoding="utf-8")
    (tmp_path / "target_assessment.json").write_text("{}", encoding="utf-8")
    (tmp_path / "drug_report.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "drug.md").write_text("intro\n<!-- EXPAND: unfinished -->\n", encoding="utf-8")
    trace_log = tmp_path / "trace.log"
    trace_log.write_text("", encoding="utf-8")

    status = traced._inspect_report_outputs(tmp_path, trace_log)

    # drug.md exists but has EXPAND markers — not finalized
    assert status["drug_md_exists"] is True
    assert (tmp_path / "drug.md").exists()
    assert status["expand_marker_count"] == 1
    assert status["finalized"] is False
    assert "no EXPAND markers" in status["missing_requirements"]


def test_inspect_report_outputs_accepts_validated_final_report(tmp_path, monkeypatch):
    """drug.md without EXPAND markers + valid finalization = finalized."""
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text("{}", encoding="utf-8")
    (tmp_path / "target_assessment.json").write_text("{}", encoding="utf-8")
    (tmp_path / "drug.md").write_text("# Complete report\nNo placeholders.\n", encoding="utf-8")
    (tmp_path / "drug_report.html").write_text("<html></html>", encoding="utf-8")
    trace_log = tmp_path / "trace.log"
    trace_log.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        traced,
        "_validate_report_finalization",
        lambda data_dir: {"valid": True, "issue_count": 0, "issues": []},
        raising=False,
    )

    status = traced._inspect_report_outputs(tmp_path, trace_log)

    assert (tmp_path / "drug.md").exists()
    assert status["finalized"] is True
    assert status["report_finalization_valid"] is True
    assert status["missing_requirements"] == []


def test_inspect_report_outputs_rejects_when_finalization_invalid(
    tmp_path,
    monkeypatch,
):
    """drug.md exists but validate_drug_report_finalization=False → not finalized."""
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text("{}", encoding="utf-8")
    (tmp_path / "target_assessment.json").write_text("{}", encoding="utf-8")
    (tmp_path / "drug.md").write_text("# Complete report\nNo placeholders.\n", encoding="utf-8")
    (tmp_path / "drug_report.html").write_text("<html></html>", encoding="utf-8")
    trace_log = tmp_path / "trace.log"
    trace_log.write_text("", encoding="utf-8")
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

    assert (tmp_path / "drug.md").exists()
    assert status["report_finalization_valid"] is False
    assert status["finalized"] is False
    assert "validate_drug_report_finalization valid=true" in status["missing_requirements"]


# test_host_template_finalization_writes_valid_report_artifacts was deleted:
# _run_host_template_finalization was removed in Phase 3 (Decision 4 / Option A).
# finalize_report node in the super-graph is now the single source of truth for
# rendering drug.md + HTML + target_assessment.json.

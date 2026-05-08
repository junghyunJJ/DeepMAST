from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


_SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


def _module():
    return importlib.import_module("run_drug_target_hypothesis_summarizer_only")


def _write_json(path: Path, payload: str = "{}") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def test_parse_args_accepts_traced_command_compatibility_flags():
    mod = _module()

    args = mod.parse_args(
        [
            "--data-dir",
            "res_ipf_openai/",
            "--disease",
            "idiopathic pulmonary fibrosis",
            "--no-debug",
            "--census",
            "--provider",
            "openai",
        ]
    )

    assert args.data_dir == "res_ipf_openai/"
    assert args.disease == "idiopathic pulmonary fibrosis"
    assert args.provider == "openai"
    assert args.no_debug is True
    assert args.census is True
    assert args.phase == "both"


def test_parse_args_accepts_phase_selection():
    mod = _module()

    args = mod.parse_args(
        [
            "--data-dir",
            "res_ipf_openai/",
            "--disease",
            "idiopathic pulmonary fibrosis",
            "--phase",
            "summarizer",
        ]
    )

    assert args.phase == "summarizer"


def test_parse_args_accepts_ollama_port():
    mod = _module()

    args = mod.parse_args(
        [
            "--data-dir",
            "res_ipf_openai/",
            "--disease",
            "idiopathic pulmonary fibrosis",
            "--provider",
            "ollama",
            "--port",
            "6000",
        ]
    )

    assert args.provider == "ollama"
    assert args.port == 6000


def test_parse_args_accepts_ollama_openai_port():
    mod = _module()

    args = mod.parse_args(
        [
            "--data-dir",
            "res_ipf_openai/",
            "--disease",
            "idiopathic pulmonary fibrosis",
            "--provider",
            "ollama-openai",
            "--port",
            "6000",
        ]
    )

    assert args.provider == "ollama-openai"
    assert args.port == 6000


def test_parse_args_rejects_port_for_non_ollama_provider():
    mod = _module()

    with pytest.raises(SystemExit):
        mod.parse_args(
            [
                "--data-dir",
                "res_ipf_openai/",
                "--disease",
                "idiopathic pulmonary fibrosis",
                "--provider",
                "openai",
                "--port",
                "6000",
            ]
        )


def test_configure_ollama_port_override_sets_env(monkeypatch):
    mod = _module()
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    args = mod.parse_args(
        [
            "--data-dir",
            "res_ipf_openai/",
            "--disease",
            "idiopathic pulmonary fibrosis",
            "--provider",
            "ollama-openai",
            "--port",
            "5000",
        ]
    )

    base_url = mod.configure_ollama_port_override(args)

    assert base_url == "http://localhost:5000"
    assert mod.os.environ["OLLAMA_BASE_URL"] == "http://localhost:5000"
    assert mod.os.environ["OLLAMA_HOST"] == "http://localhost:5000"


def test_validate_precomputed_inputs_accepts_complete_cached_evidence(tmp_path):
    mod = _module()
    data_dir = tmp_path / "run"
    _write_json(data_dir / "lr_candidates.json")
    _write_json(data_dir / "evidence" / "assessment_results.json", '{"stage3_candidates": [{"gene": "TGFB1"}]}')
    _write_json(data_dir / "evidence" / "stage2_evidence.json")
    _write_json(data_dir / "evidence" / "stage1_filter_results.json", "[]")
    _write_json(data_dir / "evidence" / "stage1_TGFB1--TGFBR2.json")
    _write_json(data_dir / "evidence" / "stage3_TGFB1.json")

    assert mod.validate_precomputed_inputs(data_dir) == []


def test_validate_precomputed_inputs_reports_missing_stage_cache(tmp_path):
    mod = _module()
    data_dir = tmp_path / "run"
    _write_json(data_dir / "lr_candidates.json")
    (data_dir / "evidence").mkdir(parents=True)

    missing = mod.validate_precomputed_inputs(data_dir)

    assert "evidence/assessment_results.json" in missing
    assert "evidence/stage2_evidence.json" in missing
    assert "evidence/stage1_filter_results.json or evidence/stage1_filter_results.csv" in missing
    assert "at least one evidence/stage1_<LIGAND>--<RECEPTOR>.json" in missing
    assert "at least one evidence/stage3_<GENE>.json" in missing


def test_validate_precomputed_inputs_requires_hypothesis_for_summarizer(tmp_path):
    mod = _module()
    data_dir = tmp_path / "run"
    _write_json(data_dir / "lr_candidates.json")
    _write_json(data_dir / "evidence" / "assessment_results.json", '{"stage3_candidates": [{"gene": "TGFB1"}]}')
    _write_json(data_dir / "evidence" / "stage2_evidence.json")
    _write_json(data_dir / "evidence" / "stage1_filter_results.json", "[]")
    _write_json(data_dir / "evidence" / "stage1_TGFB1--TGFBR2.json")
    _write_json(data_dir / "evidence" / "stage3_TGFB1.json")

    missing = mod.validate_precomputed_inputs(data_dir, phase="summarizer")

    assert missing == ["evidence/hypothesis_report.json"]


def test_validate_precomputed_inputs_does_not_require_hypothesis_for_hypothesis_phase(tmp_path):
    mod = _module()
    data_dir = tmp_path / "run"
    _write_json(data_dir / "lr_candidates.json")
    _write_json(data_dir / "evidence" / "assessment_results.json", '{"stage3_candidates": [{"gene": "TGFB1"}]}')
    _write_json(data_dir / "evidence" / "stage2_evidence.json")
    _write_json(data_dir / "evidence" / "stage1_filter_results.json", "[]")
    _write_json(data_dir / "evidence" / "stage1_TGFB1--TGFBR2.json")
    _write_json(data_dir / "evidence" / "stage3_TGFB1.json")

    assert mod.validate_precomputed_inputs(data_dir, phase="hypothesis") == []

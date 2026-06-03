from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmarks import run_cci_production_handoff_validation as runner


def _write_cases(path: Path) -> None:
    cases = [
        {
            "case_id": "case-1",
            "category": "positive",
            "lr_pair": "CXCL12-CXCR4",
            "input_bundle": {
                "ligand": "CXCL12",
                "receptor": "CXCR4",
                "pathway_associations": ["chemokine signaling"],
                "ligand_cell_types": ["Fibroblast"],
                "receptor_cell_types": ["Tumor"],
                "tissue_context": "breast cancer microenvironment",
            },
        }
    ]
    path.write_text(json.dumps(cases), encoding="utf-8")


def _patch_fake_tools(monkeypatch, calls: dict[str, dict]) -> None:
    def fake_search(payload):
        calls["search"] = payload
        data_dir = Path(payload["data_dir"])
        (data_dir / payload["output_path"]).write_text(
            json.dumps({"papers": [{"pmid": "1", "title": "direct"}]}),
            encoding="utf-8",
        )

    def fake_handoff(payload):
        data_dir = Path(payload["data_dir"])
        (data_dir / payload["citation_candidates_path"]).write_text(
            json.dumps(
                {
                    "source": {"unique_papers": 1},
                    "counts": {
                        "direct_lr_evidence": 1,
                        "receptor_pathway_context_evidence": 0,
                        "disease_only_background": 0,
                        "rejected_weak_evidence": 0,
                    },
                }
            ),
            encoding="utf-8",
        )
        (data_dir / payload["output_path"]).write_text(
            json.dumps(
                {
                    "papers": [
                        {
                            "pmid": "1",
                            "title": "direct",
                            "evidence_bucket": "direct_lr_evidence",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(runner, "search_literature_dynamic", SimpleNamespace(invoke=fake_search))
    monkeypatch.setattr(runner, "create_literature_handoff", SimpleNamespace(invoke=fake_handoff))


def test_policy_knobs_are_forwarded_to_search_and_run_config(tmp_path, monkeypatch):
    cases_path = tmp_path / "cases.json"
    output_dir = tmp_path / "out"
    _write_cases(cases_path)
    calls: dict[str, dict] = {}
    _patch_fake_tools(monkeypatch, calls)

    exit_code = runner.main(
        [
            "--cases",
            str(cases_path),
            "--output-dir",
            str(output_dir),
            "--run-id",
            "policy-run",
            "--enforce-disease-match",
            "false",
            "--rerank-mode",
            "llm",
            "--sort-by-journal-quality",
            "false",
            "--coverage-weighted-sort",
            "false",
            "--enable-lr-pair-queries",
            "false",
        ]
    )

    run_config = json.loads((output_dir / "policy-run" / "run_config.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    expected_policy = {
        "enforce_disease_match": False,
        "rerank_mode": "llm",
        "sort_by_journal_quality": False,
        "coverage_weighted_sort": False,
        "enable_lr_pair_queries": False,
    }
    for key, value in expected_policy.items():
        assert calls["search"][key] == value
        assert run_config[key] == value


def test_default_policy_knobs_and_trimmed_provider_are_forwarded(tmp_path, monkeypatch):
    cases_path = tmp_path / "cases.json"
    output_dir = tmp_path / "out"
    _write_cases(cases_path)
    calls: dict[str, dict] = {}
    _patch_fake_tools(monkeypatch, calls)

    exit_code = runner.main(
        [
            "--cases",
            str(cases_path),
            "--output-dir",
            str(output_dir),
            "--run-id",
            "default-run",
            "--llm-provider",
            " ollama ",
        ]
    )

    run_config = json.loads((output_dir / "default-run" / "run_config.json").read_text(encoding="utf-8"))

    assert exit_code == 0
    expected_defaults = {
        "enforce_disease_match": True,
        "rerank_mode": "off",
        "sort_by_journal_quality": True,
        "coverage_weighted_sort": True,
        "enable_lr_pair_queries": True,
    }
    for key, value in expected_defaults.items():
        assert calls["search"][key] == value
        assert run_config[key] == value
    assert calls["search"]["llm_provider"] == "ollama"
    assert run_config["llm_provider"] == "ollama"


@pytest.mark.parametrize("value", ["true", "True", "1", "yes", "on", "t", "y"])
def test_parse_bool_arg_accepts_true_variants(value):
    assert runner._parse_bool_arg(value) is True


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "off", "f", "n"])
def test_parse_bool_arg_accepts_false_variants(value):
    assert runner._parse_bool_arg(value) is False


def test_parse_bool_arg_rejects_invalid_value():
    with pytest.raises(runner.argparse.ArgumentTypeError):
        runner._parse_bool_arg("maybe")

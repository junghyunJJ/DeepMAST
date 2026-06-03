from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace


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
        },
        {
            "case_id": "case-2",
            "category": "positive",
            "lr_pair": "TGFB1-TGFBR2",
            "input_bundle": {
                "ligand": "TGFB1",
                "receptor": "TGFBR2",
                "pathway_associations": ["TGF-beta signaling"],
                "ligand_cell_types": ["Macrophage"],
                "receptor_cell_types": ["Tumor"],
                "tissue_context": "breast cancer microenvironment",
            },
        },
    ]
    path.write_text(json.dumps(cases), encoding="utf-8")


def test_case_limit_one_writes_production_handoff_artifacts(tmp_path, monkeypatch):
    cases_path = tmp_path / "cases.json"
    output_dir = tmp_path / "out"
    _write_cases(cases_path)
    calls: dict[str, dict] = {}

    def fake_search(payload):
        calls["search"] = payload
        data_dir = Path(payload["data_dir"])
        (data_dir / payload["output_path"]).write_text(
            json.dumps({"papers": [{"pmid": "1", "title": "direct"}]}),
            encoding="utf-8",
        )
        return {"papers": [{"pmid": "1", "title": "direct"}]}

    def fake_handoff(payload):
        calls["handoff"] = payload
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

    exit_code = runner.main(
        [
            "--cases",
            str(cases_path),
            "--output-dir",
            str(output_dir),
            "--run-id",
            "run-1",
            "--case-limit",
            "1",
            "--llm-provider",
            "ollama",
            "--llm-model",
            "qwen3.5:35b",
            "--ollama-base-url",
            "http://localhost:7000",
            "--ollama-reasoning",
            "false",
        ]
    )

    run_dir = output_dir / "run-1"
    assert exit_code == 0
    for name in [
        "papers_raw.json",
        "citation_candidates.json",
        "papers.json",
        "summary.json",
        "RESULTS_KO.md",
    ]:
        assert (run_dir / name).exists()
    assert calls["search"]["output_path"] == "papers_raw.json"
    assert calls["search"]["max_results"] == 100
    assert calls["search"]["llm_provider"] == "ollama"
    assert calls["handoff"]["raw_papers_path"] == "papers_raw.json"
    assert calls["handoff"]["output_path"] == "papers.json"
    assert calls["handoff"]["citation_candidates_path"] == "citation_candidates.json"
    assert calls["handoff"]["cap"] == 40
    assert len(calls["handoff"]["lr_pairs"]) == 1
    run_config = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
    assert run_config["llm_provider"] == "ollama"
    assert run_config["llm_model"] == "qwen3.5:35b"
    assert run_config["ollama_base_url"] == "http://localhost:7000"
    assert run_config["ollama_reasoning"] == "false"


def test_invalid_filtered_handoff_returns_error(tmp_path, monkeypatch):
    cases_path = tmp_path / "cases.json"
    output_dir = tmp_path / "out"
    _write_cases(cases_path)

    def fake_search(payload):
        data_dir = Path(payload["data_dir"])
        (data_dir / payload["output_path"]).write_text(
            json.dumps({"papers": [{"pmid": "1", "title": "background"}]}),
            encoding="utf-8",
        )

    def fake_handoff(payload):
        data_dir = Path(payload["data_dir"])
        (data_dir / payload["citation_candidates_path"]).write_text(
            json.dumps(
                {
                    "source": {"unique_papers": 1},
                    "counts": {
                        "direct_lr_evidence": 0,
                        "receptor_pathway_context_evidence": 0,
                        "disease_only_background": 1,
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
                            "title": "background",
                            "evidence_bucket": "disease_only_background",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(runner, "search_literature_dynamic", SimpleNamespace(invoke=fake_search))
    monkeypatch.setattr(runner, "create_literature_handoff", SimpleNamespace(invoke=fake_handoff))

    exit_code = runner.main(
        [
            "--cases",
            str(cases_path),
            "--output-dir",
            str(output_dir),
            "--run-id",
            "bad-run",
            "--case-limit",
            "1",
        ]
    )

    summary = json.loads((output_dir / "bad-run" / "summary.json").read_text(encoding="utf-8"))
    assert exit_code == 1
    assert "excluded bucket" in summary["error"]

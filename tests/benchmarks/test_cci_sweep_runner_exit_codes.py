from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmarks import run_cci_retrieval_bucket_benchmark as per_lr_runner
from scripts.benchmarks import run_cci_unified_retrieval_bucket_benchmark as unified_runner


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


def test_per_lr_sweep_returns_nonzero_when_any_row_errors(tmp_path, monkeypatch):
    cases_path = tmp_path / "cases.json"
    output_dir = tmp_path / "out"
    _write_cases(cases_path)

    def failing_search(_payload):
        raise RuntimeError("search failed")

    monkeypatch.setattr(per_lr_runner, "_load_grader_module", lambda: SimpleNamespace())
    monkeypatch.setattr(
        per_lr_runner,
        "search_literature_dynamic",
        SimpleNamespace(invoke=failing_search),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_cci_retrieval_bucket_benchmark.py",
            "--cases",
            str(cases_path),
            "--output-dir",
            str(output_dir),
            "--run-id",
            "bad-run",
            "--max-results",
            "30",
        ],
    )

    exit_code = per_lr_runner.main()

    summary = json.loads((output_dir / "bad-run" / "summary.json").read_text(encoding="utf-8"))
    assert exit_code == 1
    assert summary["rows"][0]["error"] == "RuntimeError: search failed"


def test_unified_sweep_returns_nonzero_when_any_row_errors(tmp_path, monkeypatch):
    cases_path = tmp_path / "cases.json"
    output_dir = tmp_path / "out"
    _write_cases(cases_path)

    def failing_search(_payload):
        raise RuntimeError("search failed")

    monkeypatch.setattr(unified_runner, "_load_grader_module", lambda: SimpleNamespace())
    monkeypatch.setattr(
        unified_runner,
        "search_literature_dynamic",
        SimpleNamespace(invoke=failing_search),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_cci_unified_retrieval_bucket_benchmark.py",
            "--cases",
            str(cases_path),
            "--output-dir",
            str(output_dir),
            "--run-id",
            "bad-run",
            "--max-results",
            "30",
        ],
    )

    exit_code = unified_runner.main()

    summary = json.loads((output_dir / "bad-run" / "summary.json").read_text(encoding="utf-8"))
    assert exit_code == 1
    assert summary["rows"][0]["error"] == "RuntimeError: search failed"

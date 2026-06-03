from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmarks import run_cci_searcher_skill_onoff_benchmark as runner


def test_skill_onoff_parser_accepts_benchmark_mode_alias() -> None:
    args = runner.build_parser().parse_args(
        [
            "--cases",
            "cases.json",
            "--output-dir",
            "out",
            "--workspace-root",
            "workspaces",
            "--benchmark-mode",
            "retrieval_only",
        ]
    )

    assert args.mode == "retrieval_only"


def _write_cases(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
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
        ),
        encoding="utf-8",
    )


def test_skill_onoff_runner_writes_rows_and_summaries(tmp_path, monkeypatch) -> None:
    cases_path = tmp_path / "cases.json"
    output_dir = tmp_path / "out"
    workspace_root = tmp_path / "workspaces"
    _write_cases(cases_path)
    trial_calls: list[dict] = []
    handoff_calls: list[dict] = []

    def fake_run_single_trial(**kwargs):
        trial_calls.append(
            {
                "condition": kwargs["condition"]["condition"],
                "model": kwargs["condition"]["model"],
                "host": os.environ.get("OLLAMA_HOST"),
                "base_url": os.environ.get("OLLAMA_BASE_URL"),
                "ollama_model": os.environ.get("OLLAMA_MODEL"),
                "reasoning": os.environ.get("OLLAMA_REASONING"),
                "llm_provider": os.environ.get("LLM_PROVIDER"),
                "llm_model": os.environ.get("LLM_MODEL"),
                "temperature": kwargs["temperature"],
                "benchmark_mode": kwargs["benchmark_mode"],
                "cases_sha256": kwargs["cases_sha256"],
            }
        )
        workspace = workspace_root / f"trial_{kwargs['trial_index']:04d}"
        workspace.mkdir(parents=True, exist_ok=True)
        papers_path = workspace / "papers.json"
        papers_path.write_text(json.dumps({"papers": [{"pmid": "1"}]}), encoding="utf-8")
        return SimpleNamespace(
            case_id=kwargs["case"]["case_id"],
            category=kwargs["case"]["category"],
            lr_pair=kwargs["case"]["lr_pair"],
            condition=kwargs["condition"]["condition"],
            model=kwargs["condition"]["model"],
            model_strength=kwargs["condition"]["model_strength"],
            skill_on=kwargs["condition"]["skill_on"],
            repeat=1,
            trial_index=kwargs["trial_index"],
            total_papers=1,
            trial_workspace=str(workspace),
            papers_path=str(papers_path),
            error=None,
        )

    def fake_handoff(payload):
        handoff_calls.append(payload)
        data_dir = Path(payload["data_dir"])
        (data_dir / payload["citation_candidates_path"]).write_text(
            json.dumps(
                {
                    "source": {"unique_papers": 4},
                    "counts": {
                        "direct_lr_evidence": 1,
                        "receptor_pathway_context_evidence": 2,
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
                        {"pmid": "1", "evidence_bucket": "direct_lr_evidence"},
                        {
                            "pmid": "2",
                            "evidence_bucket": "receptor_pathway_context_evidence",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(runner, "run_single_trial", fake_run_single_trial)
    monkeypatch.setattr(runner, "create_literature_handoff", SimpleNamespace(invoke=fake_handoff))

    exit_code = runner.main(
        [
            "--cases",
            str(cases_path),
            "--output-dir",
            str(output_dir),
            "--workspace-root",
            str(workspace_root),
            "--case-limit",
            "1",
            "--conditions",
            "weak_on,weak_off",
            "--mode",
            "C",
        ]
    )

    assert exit_code == 0
    assert [call["condition"] for call in trial_calls] == ["weak_on", "weak_off"]
    assert all(call["host"] == "http://localhost:7000" for call in trial_calls)
    assert all(call["base_url"] == "http://localhost:7000" for call in trial_calls)
    assert all(call["ollama_model"] == "qwen3.5:35b" for call in trial_calls)
    assert all(call["reasoning"] == "false" for call in trial_calls)
    assert all(call["llm_provider"] == "ollama" for call in trial_calls)
    assert all(call["llm_model"] == "qwen3.5:35b" for call in trial_calls)
    assert all(call["temperature"] == 0.0 for call in trial_calls)
    assert all(call["benchmark_mode"] == "C" for call in trial_calls)
    assert all(call["cases_sha256"] for call in trial_calls)
    assert [call["raw_papers_path"] for call in handoff_calls] == ["papers.json", "papers.json"]
    assert [call["output_path"] for call in handoff_calls] == [
        "papers_filtered.json",
        "papers_filtered.json",
    ]

    rows = sorted((output_dir / "rows").glob("*.json"))
    assert len(rows) == 2
    first_row = json.loads(rows[0].read_text(encoding="utf-8"))
    assert first_row["candidate_unique_papers"] == 4
    assert first_row["direct_papers"] == 1
    assert first_row["context_papers"] == 2
    assert first_row["disease_only_papers"] == 1
    assert first_row["rejected_papers"] == 0
    assert first_row["handoff_papers"] == 2

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["trial_count"] == 2
    assert summary["error_count"] == 0
    assert summary["by_condition"]["weak_on"]["handoff_papers"] == 2
    assert (output_dir / "summary.csv").exists()
    assert "검색기 Skill ON/OFF 벤치마크 결과" in (output_dir / "RESULTS_KO.md").read_text(
        encoding="utf-8"
    )


def test_skill_onoff_runner_routes_strong_model_to_6000(tmp_path, monkeypatch) -> None:
    cases_path = tmp_path / "cases.json"
    output_dir = tmp_path / "out"
    workspace_root = tmp_path / "workspaces"
    _write_cases(cases_path)
    hosts: list[str | None] = []

    def fake_run_single_trial(**kwargs):
        hosts.append(os.environ.get("OLLAMA_HOST"))
        workspace = workspace_root / f"trial_{kwargs['trial_index']:04d}"
        workspace.mkdir(parents=True, exist_ok=True)
        papers_path = workspace / "papers.json"
        papers_path.write_text(json.dumps({"papers": [{"pmid": "1"}]}), encoding="utf-8")
        return SimpleNamespace(
            case_id=kwargs["case"]["case_id"],
            category=kwargs["case"]["category"],
            lr_pair=kwargs["case"]["lr_pair"],
            condition=kwargs["condition"]["condition"],
            model=kwargs["condition"]["model"],
            model_strength=kwargs["condition"]["model_strength"],
            skill_on=kwargs["condition"]["skill_on"],
            trial_index=kwargs["trial_index"],
            trial_workspace=str(workspace),
            papers_path=str(papers_path),
            error=None,
        )

    def fake_handoff(payload):
        data_dir = Path(payload["data_dir"])
        (data_dir / payload["citation_candidates_path"]).write_text(
            json.dumps({"source": {"unique_papers": 0}, "counts": {}}),
            encoding="utf-8",
        )
        (data_dir / payload["output_path"]).write_text(json.dumps({"papers": []}), encoding="utf-8")

    monkeypatch.setattr(runner, "run_single_trial", fake_run_single_trial)
    monkeypatch.setattr(runner, "create_literature_handoff", SimpleNamespace(invoke=fake_handoff))

    exit_code = runner.main(
        [
            "--cases",
            str(cases_path),
            "--output-dir",
            str(output_dir),
            "--workspace-root",
            str(workspace_root),
            "--case-limit",
            "1",
            "--conditions",
            "strong_on",
        ]
    )

    assert exit_code == 0
    assert hosts == ["http://localhost:6000"]


def test_skill_onoff_runner_uses_row_papers_path_for_handoff(tmp_path, monkeypatch) -> None:
    cases_path = tmp_path / "cases.json"
    output_dir = tmp_path / "out"
    workspace_root = tmp_path / "workspaces"
    _write_cases(cases_path)
    handoff_calls: list[dict] = []

    def fake_run_single_trial(**kwargs):
        workspace = workspace_root / f"trial_{kwargs['trial_index']:04d}" / "nested"
        workspace.mkdir(parents=True, exist_ok=True)
        papers_path = workspace / "raw_papers.json"
        papers_path.write_text(json.dumps({"papers": [{"pmid": "1"}]}), encoding="utf-8")
        return SimpleNamespace(
            case_id=kwargs["case"]["case_id"],
            category=kwargs["case"]["category"],
            lr_pair=kwargs["case"]["lr_pair"],
            condition=kwargs["condition"]["condition"],
            model=kwargs["condition"]["model"],
            model_strength=kwargs["condition"]["model_strength"],
            skill_on=kwargs["condition"]["skill_on"],
            trial_index=kwargs["trial_index"],
            trial_workspace=str(workspace_root / f"trial_{kwargs['trial_index']:04d}"),
            papers_path=str(papers_path),
            error=None,
        )

    def fake_handoff(payload):
        handoff_calls.append(payload)
        data_dir = Path(payload["data_dir"])
        (data_dir / payload["citation_candidates_path"]).write_text(
            json.dumps({"source": {"unique_papers": 0}, "counts": {}}),
            encoding="utf-8",
        )
        (data_dir / payload["output_path"]).write_text(json.dumps({"papers": []}), encoding="utf-8")

    monkeypatch.setattr(runner, "run_single_trial", fake_run_single_trial)
    monkeypatch.setattr(runner, "create_literature_handoff", SimpleNamespace(invoke=fake_handoff))

    exit_code = runner.main(
        [
            "--cases",
            str(cases_path),
            "--output-dir",
            str(output_dir),
            "--workspace-root",
            str(workspace_root),
            "--case-limit",
            "1",
            "--conditions",
            "weak_on",
        ]
    )

    assert exit_code == 0
    assert handoff_calls[0]["raw_papers_path"] == "raw_papers.json"
    assert Path(handoff_calls[0]["data_dir"]).name == "nested"


def test_skill_onoff_runner_missing_papers_file_returns_failure(tmp_path, monkeypatch) -> None:
    cases_path = tmp_path / "cases.json"
    output_dir = tmp_path / "out"
    workspace_root = tmp_path / "workspaces"
    _write_cases(cases_path)

    def fake_run_single_trial(**kwargs):
        workspace = workspace_root / f"trial_{kwargs['trial_index']:04d}"
        workspace.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            case_id=kwargs["case"]["case_id"],
            category=kwargs["case"]["category"],
            lr_pair=kwargs["case"]["lr_pair"],
            condition=kwargs["condition"]["condition"],
            model=kwargs["condition"]["model"],
            model_strength=kwargs["condition"]["model_strength"],
            skill_on=kwargs["condition"]["skill_on"],
            trial_index=kwargs["trial_index"],
            trial_workspace=str(workspace),
            papers_path=str(workspace / "papers.json"),
            error=None,
        )

    monkeypatch.setattr(runner, "run_single_trial", fake_run_single_trial)

    exit_code = runner.main(
        [
            "--cases",
            str(cases_path),
            "--output-dir",
            str(output_dir),
            "--workspace-root",
            str(workspace_root),
            "--case-limit",
            "1",
            "--conditions",
            "weak_on",
        ]
    )

    row_path = next((output_dir / "rows").glob("*.json"))
    row = json.loads(row_path.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert "missing papers file" in row["error"]


def test_skill_onoff_runner_does_not_recover_papers_raw_in_production_mode(
    tmp_path, monkeypatch
) -> None:
    cases_path = tmp_path / "cases.json"
    output_dir = tmp_path / "out"
    workspace_root = tmp_path / "workspaces"
    _write_cases(cases_path)
    handoff_calls: list[dict] = []

    def fake_run_single_trial(**kwargs):
        workspace = workspace_root / f"trial_{kwargs['trial_index']:04d}"
        workspace.mkdir(parents=True, exist_ok=True)
        raw_path = workspace / "papers_raw.json"
        raw_path.write_text(json.dumps({"papers": [{"pmid": "1"}]}), encoding="utf-8")
        return SimpleNamespace(
            case_id=kwargs["case"]["case_id"],
            category=kwargs["case"]["category"],
            lr_pair=kwargs["case"]["lr_pair"],
            condition=kwargs["condition"]["condition"],
            model=kwargs["condition"]["model"],
            model_strength=kwargs["condition"]["model_strength"],
            skill_on=kwargs["condition"]["skill_on"],
            trial_index=kwargs["trial_index"],
            total_papers=0,
            trial_workspace=str(workspace),
            papers_path=str(raw_path),
            error="FileNotFoundError: /workspace/papers_raw.json",
        )

    def fake_handoff(payload):
        handoff_calls.append(payload)
        data_dir = Path(payload["data_dir"])
        (data_dir / payload["citation_candidates_path"]).write_text(
            json.dumps(
                {
                    "source": {"unique_papers": 1},
                    "counts": {"direct_lr_evidence": 1},
                }
            ),
            encoding="utf-8",
        )
        (data_dir / payload["output_path"]).write_text(
            json.dumps({"papers": [{"pmid": "1", "evidence_bucket": "direct_lr_evidence"}]}),
            encoding="utf-8",
        )

    monkeypatch.setattr(runner, "run_single_trial", fake_run_single_trial)
    monkeypatch.setattr(runner, "create_literature_handoff", SimpleNamespace(invoke=fake_handoff))

    exit_code = runner.main(
        [
            "--cases",
            str(cases_path),
            "--output-dir",
            str(output_dir),
            "--workspace-root",
            str(workspace_root),
            "--case-limit",
            "1",
            "--conditions",
            "weak_on",
        ]
    )

    row_path = next((output_dir / "rows").glob("*.json"))
    row = json.loads(row_path.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert handoff_calls == []
    assert row["error"] == "FileNotFoundError: /workspace/papers_raw.json"
    assert row.get("agent_error") is None
    assert row.get("artifact_recovered") is not True
    assert row["total_papers"] == 0


def test_skill_onoff_runner_runs_posthoc_handoff_in_retrieval_only_mode(
    tmp_path, monkeypatch
) -> None:
    cases_path = tmp_path / "cases.json"
    output_dir = tmp_path / "out"
    workspace_root = tmp_path / "workspaces"
    _write_cases(cases_path)
    handoff_calls: list[dict] = []

    def fake_run_single_trial(**kwargs):
        workspace = workspace_root / f"trial_{kwargs['trial_index']:04d}"
        workspace.mkdir(parents=True, exist_ok=True)
        papers_path = workspace / "papers_raw.json"
        papers_path.write_text(json.dumps({"papers": [{"pmid": "1"}]}), encoding="utf-8")
        return SimpleNamespace(
            case_id=kwargs["case"]["case_id"],
            category=kwargs["case"]["category"],
            lr_pair=kwargs["case"]["lr_pair"],
            condition=kwargs["condition"]["condition"],
            model=kwargs["condition"]["model"],
            model_strength=kwargs["condition"]["model_strength"],
            skill_on=kwargs["condition"]["skill_on"],
            trial_index=kwargs["trial_index"],
            total_papers=1,
            trial_workspace=str(workspace),
            papers_path=str(papers_path),
            error=None,
        )

    def fake_handoff(payload):
        handoff_calls.append(payload)
        data_dir = Path(payload["data_dir"])
        (data_dir / payload["citation_candidates_path"]).write_text(
            json.dumps(
                {
                    "source": {"unique_papers": 3},
                    "counts": {
                        "direct_lr_evidence": 1,
                        "receptor_pathway_context_evidence": 1,
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
                        {"pmid": "1", "evidence_bucket": "direct_lr_evidence"},
                        {
                            "pmid": "2",
                            "evidence_bucket": "receptor_pathway_context_evidence",
                        },
                    ],
                    "policy": {
                        "included_buckets": [
                            "direct_lr_evidence",
                            "receptor_pathway_context_evidence",
                        ],
                        "cap": 40,
                    },
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(runner, "run_single_trial", fake_run_single_trial)
    monkeypatch.setattr(runner, "create_literature_handoff", SimpleNamespace(invoke=fake_handoff))

    exit_code = runner.main(
        [
            "--cases",
            str(cases_path),
            "--output-dir",
            str(output_dir),
            "--workspace-root",
            str(workspace_root),
            "--case-limit",
            "1",
            "--conditions",
            "weak_on",
            "--mode",
            "retrieval_only",
        ]
    )

    row_path = next((output_dir / "rows").glob("*.json"))
    row = json.loads(row_path.read_text(encoding="utf-8"))
    workspace = Path(row["trial_workspace"])
    assert exit_code == 0
    assert len(handoff_calls) == 1
    assert handoff_calls[0]["raw_papers_path"] == "papers_raw.json"
    assert handoff_calls[0]["output_path"] == "papers_filtered.json"
    assert handoff_calls[0]["citation_candidates_path"] == "citation_candidates.json"
    assert handoff_calls[0]["cap"] == 40
    assert row["papers_path"] == str(workspace / "papers_filtered.json")
    assert row["raw_papers_path"] == str(workspace / "papers_raw.json")
    assert row["filtered_papers_path"] == str(workspace / "papers_filtered.json")
    assert row["citation_candidates_path"] == str(workspace / "citation_candidates.json")
    assert row["candidate_unique_papers"] == 3
    assert row["direct_papers"] == 1
    assert row["context_papers"] == 1
    assert row["disease_only_papers"] == 1
    assert row["handoff_papers"] == 2
    assert (workspace / "citation_candidates.json").exists()
    assert (workspace / "papers_filtered.json").exists()


def test_skill_onoff_runner_skips_posthoc_handoff_for_failed_retrieval_only_rows(
    tmp_path, monkeypatch
) -> None:
    cases_path = tmp_path / "cases.json"
    output_dir = tmp_path / "out"
    workspace_root = tmp_path / "workspaces"
    _write_cases(cases_path)
    handoff_calls: list[dict] = []

    def fake_run_single_trial(**kwargs):
        workspace = workspace_root / f"trial_{kwargs['trial_index']:04d}"
        workspace.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            case_id=kwargs["case"]["case_id"],
            category=kwargs["case"]["category"],
            lr_pair=kwargs["case"]["lr_pair"],
            condition=kwargs["condition"]["condition"],
            model=kwargs["condition"]["model"],
            model_strength=kwargs["condition"]["model_strength"],
            skill_on=kwargs["condition"]["skill_on"],
            trial_index=kwargs["trial_index"],
            total_papers=0,
            trial_workspace=str(workspace),
            papers_path=str(workspace / "papers_raw.json"),
            error="papers_not_written",
        )

    def fake_handoff(payload):
        handoff_calls.append(payload)
        raise AssertionError("posthoc handoff should not run for failed raw rows")

    monkeypatch.setattr(runner, "run_single_trial", fake_run_single_trial)
    monkeypatch.setattr(runner, "create_literature_handoff", SimpleNamespace(invoke=fake_handoff))

    exit_code = runner.main(
        [
            "--cases",
            str(cases_path),
            "--output-dir",
            str(output_dir),
            "--workspace-root",
            str(workspace_root),
            "--case-limit",
            "1",
            "--conditions",
            "weak_on",
            "--mode",
            "retrieval_only",
        ]
    )

    row_path = next((output_dir / "rows").glob("*.json"))
    row = json.loads(row_path.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert handoff_calls == []
    assert row["error"] == "papers_not_written"
    assert row["papers_path"].endswith("papers_raw.json")
    assert row["candidate_unique_papers"] == 0
    assert row["handoff_papers"] == 0


def test_skill_onoff_runner_resume_skips_success_and_retries_errors(
    tmp_path, monkeypatch
) -> None:
    cases_path = tmp_path / "cases.json"
    output_dir = tmp_path / "out"
    rows_dir = output_dir / "rows"
    workspace_root = tmp_path / "workspaces"
    _write_cases(cases_path)
    rows_dir.mkdir(parents=True)
    cases_sha256 = runner.compute_cases_sha256(cases_path)

    completed_workspace = workspace_root / "trial_0001"
    completed_workspace.mkdir(parents=True)
    raw_path = completed_workspace / "papers_raw.json"
    filtered_path = completed_workspace / "papers_filtered.json"
    candidates_path = completed_workspace / "citation_candidates.json"
    raw_path.write_text(json.dumps({"papers": [{"pmid": "old-raw"}]}), encoding="utf-8")
    filtered_path.write_text(json.dumps({"papers": [{"pmid": "old-filtered"}]}), encoding="utf-8")
    candidates_path.write_text(json.dumps({"source": {"unique_papers": 1}, "counts": {}}), encoding="utf-8")
    (rows_dir / "row_0001_weak_on.json").write_text(
        json.dumps(
            {
                "trial_index": 1,
                "case_id": "case-1",
                "category": "positive",
                "lr_pair": "CXCL12-CXCR4",
                "condition": "weak_on",
                "model": "qwen3.5:35b",
                "model_strength": "weak",
                "skill_on": True,
                "repeat": 1,
                "benchmark_mode": "retrieval_only",
                "cases_sha256": cases_sha256,
                "trial_workspace": str(completed_workspace),
                "papers_path": str(filtered_path),
                "raw_papers_path": str(raw_path),
                "filtered_papers_path": str(filtered_path),
                "citation_candidates_path": str(candidates_path),
                "total_papers": 1,
                "candidate_unique_papers": 1,
                "handoff_papers": 1,
                "direct_papers": 0,
                "context_papers": 1,
                "disease_only_papers": 0,
                "rejected_papers": 0,
                "error": None,
            }
        ),
        encoding="utf-8",
    )
    (rows_dir / "row_0002_weak_on.json").write_text(
        json.dumps(
            {
                "trial_index": 2,
                "case_id": "case-1",
                "condition": "weak_on",
                "repeat": 2,
                "benchmark_mode": "retrieval_only",
                "cases_sha256": cases_sha256,
                "error": "papers_not_written",
            }
        ),
        encoding="utf-8",
    )

    trial_calls: list[int] = []

    def fake_run_single_trial(**kwargs):
        trial_calls.append(kwargs["trial_index"])
        workspace = workspace_root / f"trial_{kwargs['trial_index']:04d}"
        workspace.mkdir(parents=True, exist_ok=True)
        papers_path = workspace / "papers_raw.json"
        papers_path.write_text(json.dumps({"papers": [{"pmid": "new"}]}), encoding="utf-8")
        return SimpleNamespace(
            case_id=kwargs["case"]["case_id"],
            category=kwargs["case"]["category"],
            lr_pair=kwargs["case"]["lr_pair"],
            condition=kwargs["condition"]["condition"],
            model=kwargs["condition"]["model"],
            model_strength=kwargs["condition"]["model_strength"],
            skill_on=kwargs["condition"]["skill_on"],
            repeat=kwargs["repeat"],
            trial_index=kwargs["trial_index"],
            benchmark_mode=kwargs["benchmark_mode"],
            cases_sha256=kwargs["cases_sha256"],
            total_papers=1,
            trial_workspace=str(workspace),
            papers_path=str(papers_path),
            error=None,
        )

    def fake_handoff(payload):
        data_dir = Path(payload["data_dir"])
        (data_dir / payload["citation_candidates_path"]).write_text(
            json.dumps(
                {
                    "source": {"unique_papers": 1},
                    "counts": {"direct_lr_evidence": 1},
                }
            ),
            encoding="utf-8",
        )
        (data_dir / payload["output_path"]).write_text(
            json.dumps({"papers": [{"pmid": "new", "evidence_bucket": "direct_lr_evidence"}]}),
            encoding="utf-8",
        )

    monkeypatch.setattr(runner, "run_single_trial", fake_run_single_trial)
    monkeypatch.setattr(runner, "create_literature_handoff", SimpleNamespace(invoke=fake_handoff))

    exit_code = runner.main(
        [
            "--cases",
            str(cases_path),
            "--output-dir",
            str(output_dir),
            "--workspace-root",
            str(workspace_root),
            "--case-limit",
            "1",
            "--repeats",
            "2",
            "--conditions",
            "weak_on",
            "--mode",
            "retrieval_only",
            "--resume",
        ]
    )

    assert exit_code == 0
    assert trial_calls == [2]
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["trial_count"] == 2
    assert summary["error_count"] == 0
    assert summary["rows"][0]["handoff_papers"] == 1
    retried = json.loads((rows_dir / "row_0002_weak_on.json").read_text(encoding="utf-8"))
    assert retried["error"] is None
    assert retried["papers_path"].endswith("papers_filtered.json")


def test_skill_onoff_runner_trial_timeout_records_error(tmp_path, monkeypatch) -> None:
    cases_path = tmp_path / "cases.json"
    output_dir = tmp_path / "out"
    workspace_root = tmp_path / "workspaces"
    _write_cases(cases_path)

    def slow_run_single_trial(**_kwargs):
        time.sleep(5)

    monkeypatch.setattr(runner, "run_single_trial", slow_run_single_trial)

    started = time.perf_counter()
    exit_code = runner.main(
        [
            "--cases",
            str(cases_path),
            "--output-dir",
            str(output_dir),
            "--workspace-root",
            str(workspace_root),
            "--case-limit",
            "1",
            "--conditions",
            "weak_on",
            "--trial-timeout-s",
            "1",
        ]
    )

    elapsed = time.perf_counter() - started
    row = json.loads(next((output_dir / "rows").glob("*.json")).read_text(encoding="utf-8"))
    assert exit_code == 1
    assert elapsed < 3
    assert "TimeoutError: trial exceeded timeout of 1s" in row["error"]

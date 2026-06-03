from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmarks import run_cci_content_utility_from_skill_onoff as runner


def _write_cases(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "case_id": "cci_full_01_EGF_RACK1",
                    "category": "positive",
                    "lr_pair": "EGF-RACK1",
                    "input_bundle": {
                        "ligand": "EGF",
                        "receptor": "RACK1",
                        "pathway_associations": ["EGFR signaling"],
                        "ligand_cell_types": ["Tumor"],
                        "receptor_cell_types": ["Stromal"],
                        "tissue_context": "breast cancer microenvironment",
                    },
                }
            ]
        ),
        encoding="utf-8",
    )


def _write_skill_results(root: Path) -> None:
    rows = []
    for index, (condition, model_strength, skill_on) in enumerate(
        [
            ("weak_on", "weak", True),
            ("weak_off", "weak", False),
            ("strong_on", "strong", True),
            ("strong_off", "strong", False),
        ],
        start=1,
    ):
        workspace = root / "workspaces" / f"trial_{index:04d}_{condition}"
        workspace.mkdir(parents=True)
        papers_path = workspace / "papers.json"
        papers_path.write_text(
            json.dumps(
                {
                    "papers": [
                        {
                            "pmid": "1001",
                            "title": "EGF and RACK1 signaling in breast cancer",
                            "abstract": (
                                "EGF and RACK1 are discussed in breast cancer "
                                "with EGFR signaling context."
                            ),
                        },
                        {
                            "pmid": "1002",
                            "title": "EGFR pathway context in breast cancer",
                            "abstract": "EGFR signaling is relevant to breast cancer progression.",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        rows.append(
            {
                "case_id": "cci_full_01_EGF_RACK1",
                "category": "positive",
                "lr_pair": "EGF-RACK1",
                "condition": condition,
                "model": "qwen3.5:35b" if model_strength == "weak" else "qwen3.5:122b",
                "model_strength": model_strength,
                "skill_on": skill_on,
                "repeat": 1,
                "trial_index": index,
                "trial_workspace": str(workspace),
                "papers_path": str(papers_path),
                "total_papers": 2,
                "candidate_unique_papers": 2,
                "direct_papers": 1,
                "context_papers": 1,
                "disease_only_papers": 0,
                "rejected_papers": 0,
                "handoff_papers": 2,
                "error": "",
            }
        )
    (root / "summary.json").write_text(
        json.dumps({"rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_convert_skill_rows_to_content_utility_rows(tmp_path) -> None:
    cases = tmp_path / "cases.json"
    skill_results = tmp_path / "skill_results"
    _write_cases(cases)
    _write_skill_results(skill_results)

    rows = runner.convert_skill_rows_to_content_utility_rows(
        skill_results_dir=skill_results,
        cases_path=cases,
    )

    assert len(rows) == 4
    assert {row["schedule_block_id"] for row in rows} == {"cci_full_01_EGF_RACK1:r1"}
    assert {row["skill_arm"] for row in rows} == {"updated_skill", "no_skill"}
    assert {row["model_strength"] for row in rows} == {"weak", "strong"}
    assert all(row["disease"] == "breast cancer" for row in rows)
    assert all(Path(row["saved_full_json_path"]).exists() for row in rows)


def test_content_utility_default_cap_is_40() -> None:
    args = runner.build_parser().parse_args(
        [
            "--skill-results-dir",
            "skill_results",
            "--cases",
            "cases.json",
            "--output-root",
            "out",
        ]
    )

    assert runner.DEFAULT_CAP == 40
    assert args.cap == 40


def test_content_utility_runner_builds_dry_run_outputs(tmp_path) -> None:
    cases = tmp_path / "cases.json"
    skill_results = tmp_path / "skill_results"
    output_root = tmp_path / "content_utility"
    _write_cases(cases)
    _write_skill_results(skill_results)

    exit_code = runner.main(
        [
            "--skill-results-dir",
            str(skill_results),
            "--cases",
            str(cases),
            "--output-root",
            str(output_root),
            "--score-mode",
            "dry-run",
            "--overwrite",
            "--bootstrap-iterations",
            "10",
        ]
    )

    assert exit_code == 0
    assert (output_root / "converted_runner_rows.jsonl").exists()
    assert (output_root / "realuse" / "judge_rows_dry-run.jsonl").exists()
    assert (output_root / "matched" / "judge_rows_dry-run.jsonl").exists()
    analysis = json.loads((output_root / "analysis.json").read_text(encoding="utf-8"))
    summary = json.loads((output_root / "summary.json").read_text(encoding="utf-8"))
    realuse_manifest = json.loads(
        (output_root / "realuse" / "manifest.json").read_text(encoding="utf-8")
    )
    matched_manifest = json.loads(
        (output_root / "matched" / "manifest.json").read_text(encoding="utf-8")
    )
    assert summary["cap"] == 40
    assert summary["cap_rationale"] == ""
    assert realuse_manifest["cap"] == 40
    assert realuse_manifest["default_cap"] == 40
    assert realuse_manifest["cap_is_default"] is True
    assert realuse_manifest["cap_rationale"] == ""
    assert matched_manifest["cap"] == 40
    assert matched_manifest["default_cap"] == 40
    assert matched_manifest["cap_is_default"] is True
    assert matched_manifest["cap_rationale"] == ""
    assert analysis["primary"]["valid_task_count"] == 2
    assert analysis["sensitivity"]["valid_task_count"] == 2
    assert "Content-Utility Judge" in (output_root / "RESULTS_KO.md").read_text(
        encoding="utf-8"
    )


def test_content_utility_explicit_cap_override_keeps_rationale_behavior(tmp_path) -> None:
    cases = tmp_path / "cases.json"
    skill_results = tmp_path / "skill_results"
    output_root = tmp_path / "content_utility"
    _write_cases(cases)
    _write_skill_results(skill_results)

    exit_code = runner.main(
        [
            "--skill-results-dir",
            str(skill_results),
            "--cases",
            str(cases),
            "--output-root",
            str(output_root),
            "--score-mode",
            "none",
            "--cap",
            "30",
            "--overwrite",
        ]
    )

    assert exit_code == 0
    summary = json.loads((output_root / "summary.json").read_text(encoding="utf-8"))
    realuse_manifest = json.loads(
        (output_root / "realuse" / "manifest.json").read_text(encoding="utf-8")
    )
    assert summary["cap"] == 30
    assert summary["cap_rationale"] == "non-default cap supplied via CLI"
    assert realuse_manifest["cap"] == 30
    assert realuse_manifest["default_cap"] == 40
    assert realuse_manifest["cap_is_default"] is False
    assert realuse_manifest["cap_rationale"] == "non-default cap supplied via CLI"

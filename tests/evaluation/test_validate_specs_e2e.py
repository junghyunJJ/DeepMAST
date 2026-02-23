"""End-to-end validation tests for Core Suite specs."""

from __future__ import annotations

from pathlib import Path

import yaml

from evaluation.validate_specs import validate_all


def test_validate_all_passes_on_repository_specs():
    errors = validate_all(
        catalog_path="evaluation/datasets/catalog.yaml",
        evidence_dir="evaluation/evidence",
        suite_path="evaluation/core_suite/tasks_v1.yaml",
    )
    assert errors == []


def test_validate_all_reports_invalid_task_reference(tmp_path: Path):
    cat_dir = tmp_path / "evaluation" / "datasets"
    ev_dir = tmp_path / "evaluation" / "evidence"
    suite_dir = tmp_path / "evaluation" / "core_suite"
    cat_dir.mkdir(parents=True)
    ev_dir.mkdir(parents=True)
    suite_dir.mkdir(parents=True)

    catalog = {
        "datasets": [
            {
                "dataset_id": "d1",
                "modality": "st",
                "platform": "visium",
                "download_url": "https://example.org",
                "source_paper": "paper",
                "pmid_primary": "12345",
                "license": "terms",
                "local_path_hint": "x.h5ad",
            }
        ]
    }
    evidence = {
        "dataset_id": "d1",
        "claims": [
            {
                "claim_id": f"C{i}",
                "claim_text": "t",
                "claim_type": "spatial",
                "deep_interpreter_part": "part1" if i <= 3 else ("part2" if i <= 6 else "part3"),
                "entities": ["e"],
                "direction": "present_in",
                "pmid_primary": "12345",
                "pmid_support": "12345",
                "evidence_span_ref": "ref",
            }
            for i in range(1, 9)
        ],
    }
    suite = {
        "tasks": [
            {
                "task_id": f"T{i}",
                "dataset_id": "d1",
                "category": "known_biology" if i <= 12 else "literature_grounding",
                "input_contract": {},
                "expected_contract": {
                    "evidence_claim_id": "MISSING_CLAIM",
                },
                "scorer": {"name": "checklist_recall_precision"},
                "pass_threshold": 0.7,
            }
            for i in range(1, 25)
        ]
    }

    with (cat_dir / "catalog.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(catalog, f, sort_keys=False)
    with (ev_dir / "d1.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(evidence, f, sort_keys=False)
    with (suite_dir / "tasks_v1.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(suite, f, sort_keys=False)

    errors = validate_all(
        catalog_path=cat_dir / "catalog.yaml",
        evidence_dir=ev_dir,
        suite_path=suite_dir / "tasks_v1.yaml",
    )
    assert errors
    assert any("unknown evidence_claim_id" in e.lower() for e in errors)

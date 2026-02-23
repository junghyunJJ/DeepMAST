"""Contract tests for evaluation schema objects."""

from __future__ import annotations

import pytest

from evaluation.schema import (
    ValidationError,
    validate_dataset_catalog_payload,
    validate_task_suite_payload,
)


def test_dataset_catalog_requires_non_empty_dataset_list():
    with pytest.raises(ValidationError):
        validate_dataset_catalog_payload({"datasets": []})


def test_dataset_catalog_rejects_missing_required_fields():
    payload = {
        "datasets": [
            {
                "dataset_id": "d1",
                "modality": "st",
                "platform": "visium",
                "download_url": "https://example.org",
                "source_paper": "paper",
                "pmid_primary": "12345",
                "license": "terms",
                # local_path_hint intentionally missing
            }
        ]
    }
    with pytest.raises(ValidationError):
        validate_dataset_catalog_payload(payload)


def test_task_suite_rejects_missing_claim_link():
    payload = {
        "tasks": [
            {
                "task_id": "T1",
                "dataset_id": "d1",
                "category": "known_biology",
                "input_contract": {},
                "expected_contract": {},
                "scorer": {"name": "checklist_recall_precision"},
                "pass_threshold": 0.7,
            }
        ]
    }
    with pytest.raises(ValidationError):
        validate_task_suite_payload(
            payload,
            known_dataset_ids={"d1"},
            claim_ids_by_dataset={"d1": {"C1"}},
        )

"""Tests for dataset catalog integrity."""

from __future__ import annotations

import pytest

from evaluation.schema import ValidationError, load_yaml, validate_dataset_catalog_payload


CATALOG_PATH = "evaluation/datasets/catalog.yaml"


def test_dataset_catalog_loads_and_has_three_entries():
    payload = load_yaml(CATALOG_PATH)
    datasets = validate_dataset_catalog_payload(payload)
    assert len(datasets) == 3


def test_dataset_catalog_dataset_ids_are_unique():
    payload = load_yaml(CATALOG_PATH)
    datasets = validate_dataset_catalog_payload(payload)
    ids = [d.dataset_id for d in datasets]
    assert len(ids) == len(set(ids))


def test_dataset_catalog_rejects_duplicate_ids():
    payload = load_yaml(CATALOG_PATH)
    dup = payload["datasets"][0].copy()
    payload["datasets"].append(dup)
    with pytest.raises(ValidationError):
        validate_dataset_catalog_payload(payload)

"""Validate Core Suite catalog/evidence/task specs end-to-end."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from evaluation.schema import (
    EvidenceFile,
    ValidationError,
    load_yaml,
    validate_dataset_catalog_payload,
    validate_task_suite_payload,
)


def load_evidence_files(
    evidence_dir: str | Path,
    known_dataset_ids: set[str],
) -> tuple[list[EvidenceFile], dict[str, set[str]]]:
    evidence_path = Path(evidence_dir)
    files = sorted(p for p in evidence_path.glob("*.yaml") if p.name != "_template.yaml")
    if not files:
        raise ValidationError(f"No evidence files found in {evidence_path}")

    evidence_files: list[EvidenceFile] = []
    claim_ids_by_dataset: dict[str, set[str]] = {}
    for file_path in files:
        payload = load_yaml(file_path)
        ef = EvidenceFile.from_dict(payload, known_dataset_ids=known_dataset_ids)
        evidence_files.append(ef)
        if ef.dataset_id in claim_ids_by_dataset:
            raise ValidationError(f"Duplicate evidence file for dataset: {ef.dataset_id}")
        claim_ids_by_dataset[ef.dataset_id] = {claim.claim_id for claim in ef.claims}

    return evidence_files, claim_ids_by_dataset


def validate_all(
    catalog_path: str | Path = "evaluation/datasets/catalog.yaml",
    evidence_dir: str | Path = "evaluation/evidence",
    suite_path: str | Path = "evaluation/core_suite/tasks_v1.yaml",
) -> list[str]:
    errors: list[str] = []

    try:
        catalog = validate_dataset_catalog_payload(load_yaml(catalog_path))
        dataset_ids = {d.dataset_id for d in catalog}
    except Exception as exc:  # pragma: no cover - defensive path
        return [f"Catalog validation failed: {exc}"]

    try:
        evidence_files, claim_ids_by_dataset = load_evidence_files(evidence_dir, dataset_ids)
    except Exception as exc:
        errors.append(f"Evidence validation failed: {exc}")
        return errors

    evidence_dataset_ids = {ef.dataset_id for ef in evidence_files}
    missing_evidence = sorted(dataset_ids - evidence_dataset_ids)
    if missing_evidence:
        errors.append(f"Missing evidence files for datasets: {missing_evidence}")

    for ef in evidence_files:
        if len(ef.claims) != 8:
            errors.append(
                f"Dataset '{ef.dataset_id}' must have exactly 8 claims, got {len(ef.claims)}"
            )

    try:
        suite_payload = load_yaml(suite_path)
        tasks = validate_task_suite_payload(
            suite_payload,
            known_dataset_ids=dataset_ids,
            claim_ids_by_dataset=claim_ids_by_dataset,
        )
    except Exception as exc:
        errors.append(f"Task suite validation failed: {exc}")
        return errors

    if len(tasks) != 24:
        errors.append(f"Core suite must contain 24 tasks, got {len(tasks)}")

    counts = Counter(t.category for t in tasks)
    expected = {
        "known_biology": 12,
        "literature_grounding": 6,
        "hitl": 3,
        "failure_recovery": 3,
    }
    if dict(counts) != expected:
        errors.append(f"Category balance mismatch. Expected {expected}, got {dict(counts)}")

    return errors


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate DeepMAST evaluation specs")
    parser.add_argument(
        "--catalog",
        default="evaluation/datasets/catalog.yaml",
        help="Dataset catalog YAML path",
    )
    parser.add_argument(
        "--evidence",
        default="evaluation/evidence",
        help="Evidence directory",
    )
    parser.add_argument(
        "--suite",
        default="evaluation/core_suite/tasks_v1.yaml",
        help="Core suite YAML path",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    errors = validate_all(args.catalog, args.evidence, args.suite)
    if errors:
        print("Validation failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print("Validation passed: catalog/evidence/suite are consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

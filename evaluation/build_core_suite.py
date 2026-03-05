"""Build Core Suite tasks from catalog + evidence files."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

from evaluation.schema import (
    EvidenceFile,
    load_yaml,
    validate_dataset_catalog_payload,
)


def _load_catalog(catalog_path: str | Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    payload = load_yaml(catalog_path)
    datasets = validate_dataset_catalog_payload(payload)
    ordered = [d.__dict__ for d in datasets]
    index = {d["dataset_id"]: i for i, d in enumerate(ordered)}
    return ordered, index


def _load_evidence(evidence_dir: str | Path, known_dataset_ids: set[str]) -> list[EvidenceFile]:
    files = sorted(Path(evidence_dir).glob("*.yaml"))
    out: list[EvidenceFile] = []
    for path in files:
        if path.name == "_template.yaml":
            continue
        payload = load_yaml(path)
        out.append(EvidenceFile.from_dict(payload, known_dataset_ids=known_dataset_ids))
    return out


def _category_for_index(index_1based: int) -> str:
    if index_1based <= 4:
        return "known_biology"
    if index_1based <= 6:
        return "literature_grounding"
    if index_1based == 7:
        return "hitl"
    return "failure_recovery"


def _task_prefix(category: str) -> str:
    return {
        "known_biology": "KB",
        "literature_grounding": "LG",
        "hitl": "HI",
        "failure_recovery": "FR",
    }[category]


def _scorer_for_category(category: str) -> str:
    return {
        "known_biology": "checklist_recall_precision",
        "literature_grounding": "citation_alignment",
        "hitl": "hitl_trace_completeness",
        "failure_recovery": "fallback_recovery",
    }[category]


def _threshold_for_category(category: str) -> float:
    return {
        "known_biology": 0.7,
        "literature_grounding": 0.7,
        "hitl": 1.0,
        "failure_recovery": 1.0,
    }[category]


def _dataset_tag(dataset_id: str) -> str:
    return dataset_id.replace("-", "_").upper()


def _part_output_file(part: str) -> str:
    return {
        "part1": "/part1_final.md",
        "part2": "/part2_final.md",
        "part3": "/part3_final.md",
    }[part]


def _part_papers_file(part: str) -> str:
    return "/papers.json"


def build_core_suite(
    catalog_path: str | Path,
    evidence_dir: str | Path,
) -> dict[str, Any]:
    catalog_rows, dataset_order = _load_catalog(catalog_path)
    dataset_ids = {d["dataset_id"] for d in catalog_rows}
    evidence_files = _load_evidence(evidence_dir, known_dataset_ids=dataset_ids)
    evidence_files.sort(key=lambda ef: dataset_order.get(ef.dataset_id, 10_000))

    tasks: list[dict[str, Any]] = []
    for evidence in evidence_files:
        for idx, claim in enumerate(evidence.claims, start=1):
            category = _category_for_index(idx)
            prefix = _task_prefix(category)
            task_id = f"{prefix}_{_dataset_tag(evidence.dataset_id)}_{idx:03d}"

            expected_contract: dict[str, Any] = {
                "evidence_claim_id": claim.claim_id,
                "must_include_entities": list(claim.entities),
                "expected_relation": claim.direction,
                "required_pmids": [claim.pmid_primary, claim.pmid_support],
                "claim_type": claim.claim_type,
                "deep_interpreter_part": claim.deep_interpreter_part,
                "citation_source_file": _part_papers_file(claim.deep_interpreter_part),
            }
            if category == "failure_recovery":
                expected_contract["must_trigger_fallback"] = True
                expected_contract["must_complete_pipeline"] = True

            input_contract: dict[str, Any] = {
                "analysis_mode": "full",
                "requires_hitl": category == "hitl",
                "dataset_id": evidence.dataset_id,
                "target_part": claim.deep_interpreter_part,
                "required_part_output": _part_output_file(claim.deep_interpreter_part),
            }
            if category == "failure_recovery":
                input_contract["inject_failure"] = "mcp_timeout"

            tasks.append(
                {
                    "task_id": task_id,
                    "dataset_id": evidence.dataset_id,
                    "category": category,
                    "input_contract": input_contract,
                    "expected_contract": expected_contract,
                    "scorer": {
                        "name": _scorer_for_category(category),
                        "params": {},
                    },
                    "pass_threshold": _threshold_for_category(category),
                }
            )

    return {
        "suite_id": "core_suite_v1_1",
        "version": "1.1",
        "alignment_profile": "deep_interpreter_part_aligned",
        "generated_from": {
            "catalog": str(catalog_path),
            "evidence_dir": str(evidence_dir),
        },
        "tasks": tasks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build DeepMAST Core Suite YAML")
    parser.add_argument(
        "--catalog",
        default="evaluation/datasets/catalog.yaml",
        help="Dataset catalog YAML path",
    )
    parser.add_argument(
        "--evidence",
        default="evaluation/evidence",
        help="Evidence YAML directory",
    )
    parser.add_argument(
        "--output",
        default="evaluation/core_suite/tasks_v1.yaml",
        help="Output YAML path",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    suite = build_core_suite(args.catalog, args.evidence)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(suite, f, sort_keys=False, allow_unicode=False)

    print(f"Wrote {len(suite['tasks'])} tasks to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

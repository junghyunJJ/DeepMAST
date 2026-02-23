"""Schema contracts for DeepMAST evaluation assets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ALLOWED_CLAIM_TYPES = {"lr", "pathway", "spatial", "mechanism"}
ALLOWED_DEEP_INTERPRETER_PARTS = {"part1", "part2", "part3"}
ALLOWED_TASK_CATEGORIES = {
    "known_biology",
    "literature_grounding",
    "hitl",
    "failure_recovery",
}


class ValidationError(ValueError):
    """Raised when a spec violates the expected schema contract."""


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    modality: str
    platform: str
    download_url: str
    source_paper: str
    pmid_primary: str
    license: str
    local_path_hint: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DatasetSpec":
        return cls(
            dataset_id=_required_str(data, "dataset_id"),
            modality=_required_str(data, "modality"),
            platform=_required_str(data, "platform"),
            download_url=_required_str(data, "download_url"),
            source_paper=_required_str(data, "source_paper"),
            pmid_primary=_required_str(data, "pmid_primary"),
            license=_required_str(data, "license"),
            local_path_hint=_required_str(data, "local_path_hint"),
        )


@dataclass(frozen=True)
class EvidenceClaim:
    claim_id: str
    claim_text: str
    claim_type: str
    deep_interpreter_part: str
    entities: tuple[str, ...]
    direction: str
    pmid_primary: str
    pmid_support: str
    evidence_span_ref: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceClaim":
        claim_type = _required_str(data, "claim_type")
        if claim_type not in ALLOWED_CLAIM_TYPES:
            raise ValidationError(
                f"Invalid claim_type '{claim_type}'. Allowed: {sorted(ALLOWED_CLAIM_TYPES)}"
            )
        deep_interpreter_part = _required_str(data, "deep_interpreter_part")
        if deep_interpreter_part not in ALLOWED_DEEP_INTERPRETER_PARTS:
            raise ValidationError(
                "Invalid deep_interpreter_part "
                f"'{deep_interpreter_part}'. Allowed: {sorted(ALLOWED_DEEP_INTERPRETER_PARTS)}"
            )
        entities = _required_str_list(data, "entities")
        return cls(
            claim_id=_required_str(data, "claim_id"),
            claim_text=_required_str(data, "claim_text"),
            claim_type=claim_type,
            deep_interpreter_part=deep_interpreter_part,
            entities=tuple(entities),
            direction=_required_str(data, "direction"),
            pmid_primary=_required_str(data, "pmid_primary"),
            pmid_support=_required_str(data, "pmid_support"),
            evidence_span_ref=_required_str(data, "evidence_span_ref"),
        )


@dataclass(frozen=True)
class EvidenceFile:
    dataset_id: str
    claims: tuple[EvidenceClaim, ...]

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        known_dataset_ids: set[str] | None = None,
    ) -> "EvidenceFile":
        dataset_id = _required_str(data, "dataset_id")
        if known_dataset_ids is not None and dataset_id not in known_dataset_ids:
            raise ValidationError(f"Unknown dataset_id in evidence: {dataset_id}")

        raw_claims = data.get("claims")
        if not isinstance(raw_claims, list) or not raw_claims:
            raise ValidationError("Evidence file must contain non-empty 'claims' list")

        claims = tuple(EvidenceClaim.from_dict(c) for c in raw_claims)
        _assert_unique([c.claim_id for c in claims], "claim_id")
        return cls(dataset_id=dataset_id, claims=claims)


@dataclass(frozen=True)
class CoreTaskSpec:
    task_id: str
    dataset_id: str
    category: str
    input_contract: dict[str, Any]
    expected_contract: dict[str, Any]
    scorer: dict[str, Any]
    pass_threshold: float

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
        known_dataset_ids: set[str],
        claim_ids_by_dataset: dict[str, set[str]],
    ) -> "CoreTaskSpec":
        task_id = _required_str(data, "task_id")
        dataset_id = _required_str(data, "dataset_id")
        category = _required_str(data, "category")
        if category not in ALLOWED_TASK_CATEGORIES:
            raise ValidationError(
                f"Invalid category '{category}' for task '{task_id}'. "
                f"Allowed: {sorted(ALLOWED_TASK_CATEGORIES)}"
            )
        if dataset_id not in known_dataset_ids:
            raise ValidationError(f"Unknown dataset_id '{dataset_id}' for task '{task_id}'")

        input_contract = data.get("input_contract")
        expected_contract = data.get("expected_contract")
        scorer = data.get("scorer")
        if not isinstance(input_contract, dict):
            raise ValidationError(f"Task '{task_id}' requires dict 'input_contract'")
        if not isinstance(expected_contract, dict):
            raise ValidationError(f"Task '{task_id}' requires dict 'expected_contract'")
        if not isinstance(scorer, dict) or not scorer.get("name"):
            raise ValidationError(f"Task '{task_id}' requires scorer dict with non-empty 'name'")

        claim_id = _required_str(expected_contract, "evidence_claim_id")
        known_claims = claim_ids_by_dataset.get(dataset_id, set())
        if claim_id not in known_claims:
            raise ValidationError(
                f"Task '{task_id}' references unknown evidence_claim_id '{claim_id}' "
                f"for dataset '{dataset_id}'"
            )

        try:
            pass_threshold = float(data.get("pass_threshold"))
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"Task '{task_id}' has invalid pass_threshold") from exc
        if not 0.0 <= pass_threshold <= 1.0:
            raise ValidationError(f"Task '{task_id}' pass_threshold must be within [0, 1]")

        return cls(
            task_id=task_id,
            dataset_id=dataset_id,
            category=category,
            input_contract=input_contract,
            expected_contract=expected_contract,
            scorer=scorer,
            pass_threshold=pass_threshold,
        )


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        payload = yaml.safe_load(f)
    if not isinstance(payload, dict):
        raise ValidationError(f"YAML root must be a mapping: {path}")
    return payload


def validate_dataset_catalog_payload(payload: dict[str, Any]) -> tuple[DatasetSpec, ...]:
    raw = payload.get("datasets")
    if not isinstance(raw, list) or not raw:
        raise ValidationError("Catalog must contain non-empty 'datasets' list")
    datasets = tuple(DatasetSpec.from_dict(item) for item in raw)
    _assert_unique([d.dataset_id for d in datasets], "dataset_id")
    return datasets


def validate_task_suite_payload(
    payload: dict[str, Any],
    known_dataset_ids: set[str],
    claim_ids_by_dataset: dict[str, set[str]],
) -> tuple[CoreTaskSpec, ...]:
    raw = payload.get("tasks")
    if not isinstance(raw, list) or not raw:
        raise ValidationError("Task suite must contain non-empty 'tasks' list")

    tasks = tuple(
        CoreTaskSpec.from_dict(item, known_dataset_ids, claim_ids_by_dataset) for item in raw
    )
    _assert_unique([t.task_id for t in tasks], "task_id")
    return tasks


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"Missing or empty required string field '{key}'")
    return value.strip()


def _required_str_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or not value:
        raise ValidationError(f"Missing or empty required list field '{key}'")

    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValidationError(f"Field '{key}[{i}]' must be non-empty string")
        out.append(item.strip())
    return out


def _assert_unique(values: list[str], field_name: str) -> None:
    seen: set[str] = set()
    for v in values:
        if v in seen:
            raise ValidationError(f"Duplicate {field_name}: {v}")
        seen.add(v)

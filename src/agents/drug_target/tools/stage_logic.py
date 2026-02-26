"""Shared stage decision logic for the drug target pipeline."""

from __future__ import annotations

import re
from typing import Any


_ONCOLOGY_KEYWORDS = (
    "cancer",
    "carcinoma",
    "sarcoma",
    "lymphoma",
    "leukemia",
    "melanoma",
    "glioblastoma",
    "tumor",
    "tumour",
    "neoplasm",
    "oncology",
)


def _to_float(value: Any, default: float = 0.0) -> float:
    """Best-effort numeric conversion with [0,1] clamp for scoring fields."""
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(max(0.0, min(1.0, value)))

    text = str(value).strip().lower()
    if not text:
        return default

    # Common qualitative buckets.
    qualitative = {
        "very high": 0.95,
        "high": 0.85,
        "medium": 0.60,
        "low": 0.35,
        "very low": 0.15,
    }
    if text in qualitative:
        return qualitative[text]

    try:
        number = float(text)
        # If likely entered as percentage (0-100), normalize.
        if number > 1.0:
            number = number / 100.0
        return float(max(0.0, min(1.0, number)))
    except ValueError:
        return default


def normalize_st_colocalization_score(value: Any) -> float:
    """Normalize ST colocalization score to [0, 1]."""
    return _to_float(value, default=0.0)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("<"):
        text = text[1:]
    try:
        return float(text)
    except ValueError:
        return None


def infer_oncology_flag(disease: str) -> bool:
    """Infer whether disease context is oncology-related."""
    text = (disease or "").lower()
    return any(keyword in text for keyword in _ONCOLOGY_KEYWORDS)


def classify_disease_type(disease: str) -> str:
    """Classify disease type for stage gating."""
    if infer_oncology_flag(disease):
        return "oncology"
    if (disease or "").strip():
        return "non_oncology"
    return "unknown"


def _composite_priority_score(row: dict[str, Any]) -> float:
    """Base composite score used for featured ranking."""
    ot_score = _to_float(row.get("open_targets_score"), default=0.0)
    st_score = normalize_st_colocalization_score(
        row.get("st_colocalization_score", row.get("score"))
    )
    # Weight OpenTargets slightly higher than ST for therapeutic prioritization.
    return round(ot_score * 0.6 + st_score * 0.4, 4)


def _census_bonus_score(row: dict[str, Any]) -> float:
    """Auxiliary bonus from Census cross-validation evidence."""
    census = row.get("census_validation")
    if not isinstance(census, dict):
        return 0.0

    p_value = _safe_float(census.get("p_value"))
    diff = _safe_float(census.get("diff"))
    if p_value is None or diff is None:
        return 0.0

    if p_value < 1e-4 and diff >= 0.05:
        return 0.05
    if p_value < 0.05 and diff >= 0.02:
        return 0.02
    return 0.0


def rank_featured_candidates(
    druggability_matrix: list[dict[str, Any]],
    *,
    min_featured: int = 3,
    max_featured: int = 5,
    score_threshold: float = 0.55,
) -> list[dict[str, Any]]:
    """Rank candidates and dynamically mark top 3-5 as featured."""
    if not druggability_matrix:
        return []

    scored_rows: list[dict[str, Any]] = []
    for row in druggability_matrix:
        item = dict(row)
        base_score = _composite_priority_score(item)
        census_bonus = _census_bonus_score(item)
        item["priority_base_score"] = base_score
        item["census_bonus"] = census_bonus
        item["priority_score"] = round(min(1.0, base_score + census_bonus), 4)
        scored_rows.append(item)

    scored_rows.sort(
        key=lambda x: (
            x.get("priority_score", 0.0),
            _to_float(x.get("open_targets_score"), default=0.0),
            normalize_st_colocalization_score(x.get("st_colocalization_score")),
        ),
        reverse=True,
    )

    eligible = sum(1 for row in scored_rows if row["priority_score"] >= score_threshold)
    if len(scored_rows) < min_featured:
        featured_count = len(scored_rows)
    else:
        featured_count = max(min_featured, min(max_featured, eligible))

    ranked: list[dict[str, Any]] = []
    for idx, row in enumerate(scored_rows, start=1):
        row["rank"] = idx
        row["is_featured"] = idx <= featured_count
        ranked.append(row)
    return ranked


def should_run_vep(*, oncology_flag: bool, has_high_somatic_mutation: bool) -> bool:
    """Stage 2 VEP gate."""
    return bool(oncology_flag and has_high_somatic_mutation)


def should_run_pubmed(max_clinical_phase: str | int | None) -> bool:
    """Stage 3 PubMed gate."""
    if max_clinical_phase is None:
        return False
    if isinstance(max_clinical_phase, int):
        return max_clinical_phase >= 2

    text = str(max_clinical_phase).strip().lower()
    match = re.search(r"(\d+)", text)
    if not match:
        return False
    return int(match.group(1)) >= 2


def should_run_diffdock(tractability: str | None) -> bool:
    """Stage 4 DiffDock gate."""
    text = (tractability or "").strip().lower().replace("_", " ")
    return "small molecule" in text or "smallmolecule" in text

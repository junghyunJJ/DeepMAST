"""Validation boundary for the LLM-authored hybrid report sections payload."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from src.agents.drug_target.report_interpretations import validate_interpretation_text
from src.agents.drug_target.tools.hypothesis_schema import (
    canonicalize_hypothesis_report,
    validate_canonical_hypothesis_report,
)

REPORT_SECTIONS_FILENAME = "report_sections.json"


class PipelineRecommendation(BaseModel):
    text: str = Field(min_length=24, max_length=360)
    supporting_sources: list[str] = Field(min_length=1, max_length=3)


class ReportSectionsPayload(BaseModel):
    schema_version: Literal["hybrid_report_sections/v1"]
    hypothesis_report: dict[str, Any]
    pipeline_recommendations: list[PipelineRecommendation] = Field(
        min_length=2,
        max_length=4,
    )


_MARKDOWN_RECOMMENDATION_RE = re.compile(
    r"(^\s*(?:#{1,6}\s|[-*+]\s+|\d+[.)]\s|>\s)|"
    r"\[[^\]]+\]\([^)]*\)|\[source\s*:|\b[\w.-]+\.json\b)",
    re.IGNORECASE,
)
_FUTURE_ACTION_RE = re.compile(
    r"\b(?:prioritize|validate|evaluate|test|assess|investigate|compare|"
    r"review|monitor|advance|develop|consider|plan|pursue|confirm|measure|"
    r"characterize|stratify)\b",
    re.IGNORECASE,
)


def _recommendation_validation_card(
    report_data: Mapping[str, Any],
    source_paths: set[str],
) -> dict[str, Any]:
    genes: list[str] = []
    drugs: list[str] = []
    candidates = report_data.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            gene = candidate.get("gene")
            if isinstance(gene, str) and gene.strip() and gene not in genes:
                genes.append(gene)
            for field in ("drugs", "clinical_drugs", "preclinical_drugs"):
                entries = candidate.get(field)
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if isinstance(entry, str):
                        name = entry
                    elif isinstance(entry, Mapping):
                        name = (
                            entry.get("name")
                            or entry.get("drug_name")
                            or entry.get("pref_name")
                            or entry.get("molecule_pref_name")
                        )
                    else:
                        continue
                    if isinstance(name, str) and name.strip() and name not in drugs:
                        drugs.append(name)
    return {
        "id": "pipeline_recommendations",
        "allowed_genes": genes,
        "allowed_drugs": drugs,
        "allowed_terms": [],
        "allowed_numbers": [],
        "allowed_sources": sorted(source_paths),
    }


def canonicalize_report_sections(
    payload: Any,
    evidence_dir: Path,
    source_paths: Collection[str],
    report_data: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Return a canonical hybrid payload without persisting it."""
    try:
        parsed = ReportSectionsPayload.model_validate(payload)
    except ValidationError as exc:
        return None, [f"report_sections payload is invalid: {exc}"]

    canonical_hypotheses, errors, _ = canonicalize_hypothesis_report(
        parsed.hypothesis_report,
        evidence_dir,
        legacy_compat=False,
    )
    if canonical_hypotheses is None:
        return None, errors
    if errors:
        return None, errors

    errors = validate_canonical_hypothesis_report(canonical_hypotheses, evidence_dir)
    if errors:
        return None, errors

    known_sources = {
        source
        for source in source_paths
        if isinstance(source, str) and source.strip()
    }
    card = _recommendation_validation_card(report_data, known_sources)
    recommendations: list[dict[str, Any]] = []
    for index, recommendation in enumerate(parsed.pipeline_recommendations):
        text = recommendation.text.strip()
        sources = recommendation.supporting_sources
        if len(sources) != len(set(sources)):
            errors.append(
                f"pipeline_recommendations[{index}].supporting_sources must be unique."
            )
        unsupported_sources = sorted(set(sources) - known_sources)
        if unsupported_sources:
            errors.append(
                f"pipeline_recommendations[{index}].supporting_sources are not "
                f"deterministic evidence paths: {unsupported_sources}."
            )
        if "\n" in text or "\r" in text:
            errors.append(
                f"pipeline_recommendations[{index}].text must be a single line."
            )
        if text[-1:] not in {".", "!", "?"} or len(
            re.findall(r"[.!?]", text)
        ) != 1:
            errors.append(
                f"pipeline_recommendations[{index}].text must contain exactly one sentence."
            )
        if _MARKDOWN_RECOMMENDATION_RE.search(text):
            errors.append(
                f"pipeline_recommendations[{index}].text must not contain Markdown "
                "or source syntax."
            )
        if not _FUTURE_ACTION_RE.search(text):
            errors.append(
                f"pipeline_recommendations[{index}].text must state a future-directed "
                "action."
            )
        for issue in validate_interpretation_text(card, text):
            errors.append(
                f"pipeline_recommendations[{index}].text: {issue['message']}"
            )
        recommendations.append(
            {"text": text, "supporting_sources": sources}
        )

    if errors:
        return None, errors
    return {
        "schema_version": parsed.schema_version,
        "hypothesis_report": canonical_hypotheses,
        "pipeline_recommendations": recommendations,
    }, []

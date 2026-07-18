"""Validation boundary for the LLM-authored hybrid report sections payload."""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from src.agents.drug_target.report_interpretations import (
    build_interpretation_cards,
    validate_interpretation_text,
)
from src.agents.drug_target.tools.hypothesis_schema import (
    canonicalize_hypothesis_report,
    validate_canonical_hypothesis_report,
)

REPORT_SECTIONS_FILENAME = "report_sections.json"


class PipelineRecommendation(BaseModel):
    text: str = Field(min_length=24, max_length=360)
    supporting_sources: list[str] = Field(min_length=1, max_length=5)


class CandidateFollowup(BaseModel):
    gene: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=24, max_length=360)
    supporting_source: str = Field(min_length=1, max_length=240)


class ReportSectionsPayload(BaseModel):
    schema_version: Literal["hybrid_report_sections/v1"]
    hypothesis_report: dict[str, Any]
    candidate_followups: list[CandidateFollowup] = Field(
        default_factory=list,
        max_length=7,
    )
    pipeline_recommendations: list[PipelineRecommendation] = Field(
        min_length=2,
        max_length=4,
    )


class ReportRecommendationsPayload(BaseModel):
    schema_version: Literal["hybrid_report_sections/v1"]
    candidate_followups: list[CandidateFollowup] = Field(
        default_factory=list,
        max_length=7,
    )
    pipeline_recommendations: list[PipelineRecommendation] = Field(
        min_length=2,
        max_length=4,
    )


_MARKDOWN_RECOMMENDATION_RE = re.compile(
    r"(^\s*(?:#{1,6}\s|[-*+]\s+|\d+[.)]\s|>\s)|"
    r"\[[^\]]+\]\([^)]*\)|\[source\s*:|\b[\w.-]+\.json\b|"
    r"`|\*{1,3}|~~|<[/!]?[A-Za-z][^>\n]*>|"
    r"__[^_\n]+__|(?<![A-Za-z0-9])_[^_\n]+_(?![A-Za-z0-9]))",
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


def _ollama_featured_genes(evidence_dir: Path) -> list[str]:
    try:
        assessment = json.loads(
            (evidence_dir / "assessment_results.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read FEATURED genes: {exc}") from exc
    candidates = assessment.get("stage3_candidates") if isinstance(assessment, dict) else None
    if not isinstance(candidates, list):
        raise ValueError("assessment_results.json stage3_candidates must be a list")
    genes: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        gene = str(candidate.get("gene") or candidate.get("gene_symbol") or "").strip().upper()
        if gene and gene not in genes:
            genes.append(gene)
    if not genes:
        raise ValueError("assessment_results.json has no FEATURED genes")
    return genes


def _ollama_hypothesis_sources(
    evidence_dir: Path,
    hypothesis_report: Mapping[str, Any],
) -> list[str]:
    sources: list[str] = []
    hypotheses = hypothesis_report.get("hypotheses")
    if not isinstance(hypotheses, list):
        raise ValueError("hypothesis_report.json hypotheses must be a list")
    for hypothesis in hypotheses:
        if not isinstance(hypothesis, Mapping):
            continue
        references = hypothesis.get("evidence_references")
        if not isinstance(references, list):
            continue
        for reference in references:
            if not isinstance(reference, str):
                continue
            filename = Path(reference).name
            if (
                filename == reference
                and filename.endswith(".json")
                and (evidence_dir / filename).is_file()
            ):
                source = f"evidence/{filename}"
                if source not in sources:
                    sources.append(source)
    if not sources:
        raise ValueError("hypothesis_report.json has no existing evidence references")
    return sources


def _is_safe_ollama_recommendation(
    text: object,
    card: Mapping[str, Any],
) -> bool:
    return not _ollama_recommendation_errors(text, card)


def _ollama_recommendation_errors(
    text: object,
    card: Mapping[str, Any],
) -> list[str]:
    if not isinstance(text, str):
        return ["must be text."]
    stripped = text.strip()
    errors: list[str] = []
    if not 24 <= len(stripped) <= 360:
        errors.append("must contain 24-360 characters.")
    if "\n" in stripped or "\r" in stripped:
        errors.append("must be a single line.")
    if stripped[-1:] not in {".", "!", "?"} or len(
        re.findall(r"[.!?]", stripped)
    ) != 1:
        errors.append("must contain exactly one sentence.")
    if _MARKDOWN_RECOMMENDATION_RE.search(stripped):
        errors.append("must not contain Markdown or source syntax.")
    if not _FUTURE_ACTION_RE.search(stripped):
        errors.append("must state a future-directed action.")
    errors.extend(
        issue["message"] for issue in validate_interpretation_text(card, stripped)
    )
    return errors


def _candidate_followup_cards(
    specs: list[dict[str, str]],
) -> dict[str, dict[str, Any]]:
    cards = build_interpretation_cards(
        {
            "candidates": [
                {
                    "gene": spec["gene"],
                    "sources": [spec["supporting_source"]],
                    "stage3_candidate": True,
                }
                for spec in specs
            ]
        }
    )
    return {
        str(card["id"]): card
        for card in cards
        if isinstance(card.get("id"), str)
        and str(card["id"]).endswith(".recommendation")
    }


def build_ollama_candidate_followup_specs(
    data_dir: str | Path,
) -> list[dict[str, str]]:
    """Return up to seven featured candidates with deterministic evidence paths."""
    evidence_dir = Path(data_dir).expanduser().resolve() / "evidence"
    specs: list[dict[str, str]] = []
    for gene in _ollama_featured_genes(evidence_dir):
        source = next(
            (
                f"evidence/{filename}"
                for filename in (f"stage3_{gene}.json", f"ot_{gene}.json")
                if (evidence_dir / filename).is_file()
            ),
            None,
        )
        if source is not None:
            specs.append({"gene": gene, "supporting_source": source})
        if len(specs) == 7:
            break
    return specs


def build_ollama_candidate_followups(
    data_dir: str | Path,
    texts: Mapping[str, str],
) -> list[dict[str, str]]:
    """Return only locally valid Ollama candidate follow-ups."""
    specs = build_ollama_candidate_followup_specs(data_dir)
    cards = _candidate_followup_cards(specs)
    followups: list[dict[str, str]] = []
    for spec in specs:
        text = texts.get(spec["gene"])
        card = cards.get(f"candidate.{spec['gene']}.recommendation")
        if card is None or _ollama_recommendation_errors(text, card):
            continue
        followups.append(
            {
                "gene": spec["gene"],
                "text": text.strip(),
                "supporting_source": spec["supporting_source"],
            }
        )
    return followups


def build_ollama_report_recommendations(
    data_dir: str | Path,
    texts: Mapping[str, str],
) -> dict[str, object]:
    """Build the two source-bound Ollama recommendations for the report save tool."""
    base = Path(data_dir).expanduser().resolve()
    evidence_dir = base / "evidence"
    try:
        hypothesis_report = json.loads(
            (evidence_dir / "hypothesis_report.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read canonical hypothesis report: {exc}") from exc
    if not isinstance(hypothesis_report, Mapping):
        raise ValueError("hypothesis_report.json must be a JSON object")

    sources = _ollama_hypothesis_sources(evidence_dir, hypothesis_report)
    if len(sources) == 1:
        sources.append(sources[0])
    genes = _ollama_featured_genes(evidence_dir)
    card = _recommendation_validation_card(
        {"candidates": [{"gene": gene} for gene in genes]},
        set(sources),
    )
    fallbacks = (
        f"Prioritize {genes[0]} validation before advancing target selection.",
        f"Evaluate {genes[1] if len(genes) > 1 else genes[0]} evidence before planning follow-up studies.",
    )
    recommendations = []
    for index, label in enumerate(("primary", "secondary")):
        candidate = texts.get(label, "")
        text = candidate.strip() if _is_safe_ollama_recommendation(candidate, card) else fallbacks[index]
        recommendations.append({"text": text, "supporting_sources": [sources[index]]})
    return {
        "schema_version": "hybrid_report_sections/v1",
        "pipeline_recommendations": recommendations,
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
    candidate_cards = {
        str(card["id"]): card
        for card in build_interpretation_cards(report_data)
        if isinstance(card.get("id"), str)
        and str(card["id"]).endswith(".recommendation")
    }
    candidate_followups: list[dict[str, str]] = []
    seen_followup_genes: set[str] = set()
    for index, followup in enumerate(parsed.candidate_followups):
        gene = followup.gene.strip().upper()
        text = followup.text.strip()
        source = followup.supporting_source.strip()
        if gene in seen_followup_genes:
            errors.append(f"candidate_followups[{index}].gene must be unique.")
            continue
        seen_followup_genes.add(gene)
        card = candidate_cards.get(f"candidate.{gene}.recommendation")
        if card is None:
            errors.append(
                f"candidate_followups[{index}].gene is not a featured candidate."
            )
            continue
        allowed_sources = card.get("allowed_sources")
        allowed_sources = allowed_sources if isinstance(allowed_sources, list) else []
        if source not in allowed_sources:
            errors.append(
                f"candidate_followups[{index}].supporting_source is not allowed "
                f"for {gene}."
            )
        for issue in _ollama_recommendation_errors(text, card):
            errors.append(f"candidate_followups[{index}].text: {issue}")
        candidate_followups.append(
            {
                "gene": gene,
                "text": text,
                "supporting_source": source,
            }
        )

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
        "candidate_followups": candidate_followups,
        "pipeline_recommendations": recommendations,
    }, []

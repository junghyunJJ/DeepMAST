"""Deterministic Part 4 therapeutic synthesis artifact rendering."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


PART4_SYNTHESIS_SCHEMA_VERSION = "drug_target.part4_therapeutic_synthesis.v1"
PART4_SYNTHESIS_FILENAME = "part4_therapeutic_synthesis.md"

_MAX_FEATURED_CANDIDATES = 3
_MAX_HYPOTHESES = 5
_MAX_RENDER_TEXT_CHARS = 600
_MAX_RENDER_LIST_ITEM_CHARS = 120
_MAX_RENDER_LIST_ITEMS = 5
_EXPAND_MARKER_PATTERN = re.compile(
    r"<!--\s*EXPAND(?:\s*:|\s+).*?-->",
    flags=re.IGNORECASE | re.DOTALL,
)
_DISALLOWED_MARKDOWN_PHRASES = (
    ("patients should receive", "experimental studies should evaluate"),
    ("recommended therapy", "candidate therapy"),
    ("should treat", "should test experimentally"),
    ("clinical ready", "experimentally prioritized"),
    ("standard of care", "care guidance"),
    ("patients should", "experiments should"),
)


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _safe_text(item))]


def _limited_names(value: object, limit: int = 5) -> list[str]:
    if not isinstance(value, list):
        return []

    names: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            name = _safe_text(
                item.get("name")
                or item.get("title")
                or item.get("drug")
                or item.get("drug_name")
            )
        else:
            name = _safe_text(item)
        if name:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def _safe_text(value: object, default: str = "") -> str:
    text = "" if value is None else str(value).strip()
    return text if text else default


def _safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(value)
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _safe_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _candidate_score(candidate: Mapping[str, Any], key: str) -> int:
    scores = candidate.get("scores")
    if not isinstance(scores, Mapping):
        return 0
    return _safe_int(scores.get(key), 0)


def _candidate_score_profile(candidate: Mapping[str, Any]) -> dict[str, int]:
    return {
        "combined_total": _candidate_score(candidate, "combined_total"),
        "validated_total": _candidate_score(candidate, "validated_total"),
        "exploratory_total": _candidate_score(candidate, "exploratory_total"),
    }


def _evidence_track(candidate: Mapping[str, Any]) -> str:
    validated = _candidate_score(candidate, "validated_total")
    exploratory = _candidate_score(candidate, "exploratory_total")
    if validated >= 7 and exploratory >= 4:
        return "validated-and-exploratory"
    if validated >= 7:
        return "validated-dominant"
    if exploratory >= 4:
        return "exploratory-dominant"
    return "limited-evidence"


def _drug_signal_summary(candidate: Mapping[str, Any]) -> str:
    clinical_count = _safe_int(candidate.get("clinical_drug_count"), 0)
    preclinical_count = _safe_int(candidate.get("preclinical_drug_count"), 0)
    return (
        f"{clinical_count} clinical and {preclinical_count} preclinical "
        "structured drug signals"
    )


def _phase_text(value: object) -> str:
    if value is None:
        return "phase not recorded"
    phase = _safe_float(value, -1.0)
    if phase < 0:
        return "phase not recorded"
    if phase.is_integer():
        return f"phase {int(phase)}"
    return f"phase {phase:g}"


def _source_text(value: object) -> str:
    source = _safe_text(value)
    normalized = source.lower()
    if normalized == "opentargets":
        return "OpenTargets"
    if normalized == "chembl":
        return "ChEMBL"
    return source


def _drug_record_summary(record: Mapping[str, Any]) -> dict[str, str]:
    return {
        "name": _safe_text(
            record.get("name")
            or record.get("title")
            or record.get("drug")
            or record.get("drug_name"),
        ),
        "chembl_id": _safe_text(record.get("chembl_id")),
        "phase": _phase_text(record.get("phase")),
        "mechanism_of_action": _safe_text(record.get("mechanism_of_action")),
        "source": _source_text(record.get("source")),
    }


def _drug_record_summaries(value: object, limit: int = 3) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for item in _dict_list(value):
        summary = _drug_record_summary(item)
        if summary["name"]:
            records.append(summary)
        if len(records) >= limit:
            break
    return records


def _format_drug_record(record: Mapping[str, Any]) -> str:
    name = _bounded_text(record.get("name"), "unnamed compound", limit=90)
    parts = [
        _bounded_text(record.get("phase"), limit=40),
        _bounded_text(record.get("mechanism_of_action"), limit=110),
        _bounded_text(record.get("source"), limit=40),
    ]
    details = [part for part in parts if part]
    return f"{name} ({'; '.join(details)})" if details else name


def _format_drug_records(records: object) -> str:
    rendered = [
        _format_drug_record(record)
        for record in _dict_list(records)[:_MAX_RENDER_LIST_ITEMS]
    ]
    return ", ".join(rendered)


def _drug_target_evidence_summary(candidate: Mapping[str, Any]) -> str:
    clinical = _format_drug_records(candidate.get("clinical_drug_examples"))
    preclinical = _format_drug_records(candidate.get("preclinical_drug_examples"))
    segments: list[str] = []
    if clinical:
        segments.append(f"Clinical: {clinical}.")
    if preclinical:
        segments.append(f"Preclinical: {preclinical}.")
    if segments:
        return " ".join(segments)
    return "No named clinical or preclinical drug records were available."


def _drug_evidence_score(candidate: Mapping[str, Any]) -> int:
    clinical = min(_safe_int(candidate.get("clinical_drug_count"), 0), 5)
    preclinical = min(_safe_int(candidate.get("preclinical_drug_count"), 0), 5)
    return clinical * 2 + preclinical


def _therapeutic_rationale(candidate: Mapping[str, Any]) -> str:
    gene = _safe_text(candidate.get("gene"), "candidate").upper()
    classification = _safe_text(candidate.get("classification"), "unknown")
    priority = _safe_text(candidate.get("priority"), "unranked")
    track = _evidence_track(candidate).replace("-", " ")
    return (
        f"{gene} is prioritized as a {priority} {classification} candidate "
        f"with {track} support in the deterministic evidence model."
    )


def _score_profile(value: object) -> dict[str, int | float]:
    if not isinstance(value, Mapping):
        return {}
    profile: dict[str, int | float] = {}
    for key, raw_score in value.items():
        if (
            isinstance(key, str)
            and not isinstance(raw_score, bool)
            and isinstance(raw_score, int | float)
        ):
            profile[key] = raw_score
    return profile


def _candidate_summary(candidate: Mapping[str, Any]) -> dict[str, Any]:
    sources = _string_list(candidate.get("sources"))
    score_profile = _candidate_score_profile(candidate)
    clinical_drug_examples = _drug_record_summaries(candidate.get("clinical_drugs"))
    preclinical_drug_examples = _drug_record_summaries(
        candidate.get("preclinical_drugs"),
    )
    summary = {
        "gene": _safe_text(candidate.get("gene")).upper(),
        "classification": _safe_text(candidate.get("classification"), "unknown"),
        "priority": _safe_text(candidate.get("priority"), "unranked"),
        "stage3_candidate": _safe_bool(candidate.get("stage3_candidate")),
        "score_profile": score_profile,
        "combined_total": score_profile["combined_total"],
        "validated_total": score_profile["validated_total"],
        "exploratory_total": score_profile["exploratory_total"],
        "evidence_track": _evidence_track(candidate),
        "drug_signal_summary": _drug_signal_summary(candidate),
        "clinical_drugs": _limited_names(candidate.get("clinical_drugs")),
        "preclinical_drugs": _limited_names(candidate.get("preclinical_drugs")),
        "clinical_drug_examples": clinical_drug_examples,
        "preclinical_drug_examples": preclinical_drug_examples,
        "therapeutic_rationale": _therapeutic_rationale(candidate),
        "clinical_drug_count": _safe_int(candidate.get("clinical_drug_count"), 0),
        "preclinical_drug_count": _safe_int(
            candidate.get("preclinical_drug_count"),
            0,
        ),
        "source_count": len(sources),
        "evidence_sources": sources[:5],
    }
    summary["drug_target_evidence"] = _drug_target_evidence_summary(summary)
    return summary


def _candidate_hypothesis_context(
    candidate: Mapping[str, Any],
    hypotheses: list[dict[str, Any]],
) -> dict[str, Any]:
    gene = _safe_text(candidate.get("gene")).upper()
    linked = [
        hypothesis
        for hypothesis in hypotheses
        if gene in {_safe_text(item).upper() for item in hypothesis.get("genes", [])}
    ]
    ranks = [
        rank
        for hypothesis in linked
        if (rank := _safe_int(hypothesis.get("rank"), 0)) > 0
    ]
    composites = [
        composite
        for hypothesis in linked
        if (
            composite := _safe_float(
                (
                    hypothesis.get("score_profile", {})
                    if isinstance(hypothesis.get("score_profile"), Mapping)
                    else {}
                ).get("composite"),
                0.0,
            )
        )
        > 0
    ]
    best_rank = min(ranks) if ranks else 0
    best_composite = max(composites) if composites else 0.0
    linked_summary = [
        {
            "rank": _safe_int(hypothesis.get("rank"), 0),
            "title": _safe_text(hypothesis.get("title")),
            "category": _safe_text(hypothesis.get("category")),
            "drugs": _string_list(hypothesis.get("drugs"))[:3],
            "composite": _safe_float(
                (
                    hypothesis.get("score_profile", {})
                    if isinstance(hypothesis.get("score_profile"), Mapping)
                    else {}
                ).get("composite"),
                0.0,
            ),
        }
        for hypothesis in linked[:3]
    ]
    if linked_summary:
        lead = linked_summary[0]
        role_summary = (
            f"Linked to {_plural_phrase(len(linked), 'deterministic hypothesis', 'deterministic hypotheses')}, "
            f"including rank {lead['rank']}: {lead['title']}."
        )
    else:
        role_summary = (
            "No ranked mechanistic hypothesis explicitly linked this candidate "
            "in the deterministic hypothesis artifact."
        )
    return {
        "linked_hypotheses": linked_summary,
        "mechanistic_hypothesis_count": len(linked),
        "best_hypothesis_rank": best_rank,
        "best_hypothesis_composite": best_composite,
        "mechanistic_role_summary": role_summary,
    }


def _candidate_selection_sort_key(candidate: Mapping[str, Any]) -> tuple:
    best_rank = _safe_int(candidate.get("best_hypothesis_rank"), 0) or 10_000
    return (
        -_safe_int(candidate.get("mechanistic_hypothesis_count"), 0),
        -_safe_float(candidate.get("best_hypothesis_composite"), 0.0),
        best_rank,
        -_drug_evidence_score(candidate),
        -_safe_int(candidate.get("combined_total"), 0),
        _safe_text(candidate.get("gene")),
    )


def _primary_mechanistic_axis_genes(
    hypotheses: list[dict[str, Any]],
    candidate_genes: set[str],
) -> list[str]:
    for hypothesis in hypotheses:
        axis_genes = [
            gene
            for gene in _string_list(hypothesis.get("genes"))
            if gene.upper() in candidate_genes
        ]
        deduped_axis: list[str] = []
        seen: set[str] = set()
        for gene in axis_genes:
            normalized = gene.upper()
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped_axis.append(normalized)
        if len(deduped_axis) >= 2:
            return deduped_axis[:_MAX_FEATURED_CANDIDATES]
    return []


def _selected_candidates(report_data: Mapping[str, Any]) -> list[dict[str, Any]]:
    hypotheses = _hypotheses(report_data)
    candidates = [
        {
            **summary,
            **_candidate_hypothesis_context(summary, hypotheses),
        }
        for candidate in _dict_list(report_data.get("candidates"))
        if (summary := _candidate_summary(candidate))["gene"]
    ]
    featured = [
        candidate
        for candidate in candidates
        if candidate["stage3_candidate"]
    ]
    pool = featured or candidates
    by_gene = {candidate["gene"]: candidate for candidate in pool}
    selected: list[dict[str, Any]] = []
    selected_genes: set[str] = set()
    for gene in _primary_mechanistic_axis_genes(hypotheses, set(by_gene)):
        selected.append(by_gene[gene])
        selected_genes.add(gene)
        if len(selected) >= _MAX_FEATURED_CANDIDATES:
            return selected

    remaining = [
        candidate
        for candidate in pool
        if candidate["gene"] not in selected_genes
    ]
    selected.extend(
        sorted(remaining, key=_candidate_selection_sort_key)[
            : _MAX_FEATURED_CANDIDATES - len(selected)
        ],
    )
    return selected


def _interpretation_summary(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    summary = payload.get("summary") if isinstance(payload, Mapping) else None
    if not isinstance(summary, Mapping):
        summary = {}
    return {
        "accepted": _safe_int(summary.get("accepted"), 0),
        "rejected": _safe_int(summary.get("rejected"), 0),
        "missing": _safe_int(summary.get("missing"), 0),
        "provider_errors": _safe_int(summary.get("provider_errors"), 0),
        "criteria_met": _safe_bool(summary.get("criteria_met")),
    }


def _validation_issues(validation: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(validation, Mapping):
        return []
    return _dict_list(validation.get("issues"))


def _hypothesis_summary(hypothesis: Mapping[str, Any]) -> dict[str, Any]:
    entities = hypothesis.get("biological_entities")
    if not isinstance(entities, Mapping):
        entities = {}
    evidence_references = _string_list(hypothesis.get("evidence_references"))
    return {
        "rank": _safe_int(hypothesis.get("rank"), 0),
        "title": _safe_text(
            hypothesis.get("title")
            or hypothesis.get("hypothesis")
            or hypothesis.get("mechanism"),
            "Mechanistic hypothesis",
        ),
        "category": _safe_text(hypothesis.get("category"), "unspecified"),
        "genes": [gene.upper() for gene in _string_list(entities.get("genes"))],
        "drugs": _string_list(entities.get("drugs")),
        "pathways": _limited_names(entities.get("pathways")),
        "cell_types": _limited_names(entities.get("cell_types")),
        "core_claim": _safe_text(hypothesis.get("core_claim")),
        "falsifiable_prediction": _safe_text(
            hypothesis.get("falsifiable_prediction"),
        ),
        "validation_approach": _safe_text(hypothesis.get("validation_approach")),
        "score_profile": _score_profile(hypothesis.get("scores")),
        "evidence_references": evidence_references[:5],
        "source_count": len(evidence_references),
    }


def _hypotheses(report_data: Mapping[str, Any]) -> list[dict[str, Any]]:
    summaries = [
        _hypothesis_summary(hypothesis)
        for hypothesis in _dict_list(report_data.get("hypotheses"))
    ]
    return sorted(
        summaries,
        key=lambda item: (item["rank"] if item["rank"] else 10_000, item["title"]),
    )[:_MAX_HYPOTHESES]


def build_part4_therapeutic_synthesis(
    report_data: Mapping[str, Any],
    *,
    validation: Mapping[str, Any] | None,
    interpretations_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic Part 4 synthesis model from report_data."""

    candidates = _dict_list(report_data.get("candidates"))
    selected_candidates = _selected_candidates(report_data)
    return {
        "schema_version": PART4_SYNTHESIS_SCHEMA_VERSION,
        "disease": _safe_text(report_data.get("disease"), "unspecified disease"),
        "report_valid": (
            _safe_bool(validation.get("valid"))
            if isinstance(validation, Mapping)
            else False
        ),
        "validation_issues": _validation_issues(validation),
        "interpretation_summary": _interpretation_summary(interpretations_payload),
        "selection_strategy": "deterministic_mechanistic_axis_and_drug_evidence",
        "candidate_counts": {
            "total": len(candidates),
            "featured": len(selected_candidates),
            "stage3_total": len(
                [
                    candidate
                    for candidate in candidates
                    if _safe_bool(candidate.get("stage3_candidate"))
                ]
            ),
            "validated": len(
                [
                    candidate
                    for candidate in candidates
                    if _safe_text(candidate.get("classification"))
                    == "validated_target"
                ]
            ),
            "exploratory": len(
                [
                    candidate
                    for candidate in candidates
                    if (
                        classification := _safe_text(
                            candidate.get("classification"),
                        ).lower()
                    )
                    in {"exploratory_target", "novel_candidate"}
                    or "exploratory" in classification
                ]
            ),
        },
        "featured_candidates": selected_candidates,
        "hypotheses": _hypotheses(report_data),
    }


def _candidate_render_track(candidate: Mapping[str, Any]) -> str:
    track = _safe_text(candidate.get("evidence_track"))
    if track:
        return track

    validated = _candidate_render_score(candidate, "validated_total")
    exploratory = _candidate_render_score(candidate, "exploratory_total")
    if validated >= 7 and exploratory >= 4:
        return "validated-and-exploratory"
    if validated >= 7:
        return "validated-dominant"
    if exploratory >= 4:
        return "exploratory-dominant"
    return "limited-evidence"


def _candidate_render_score(candidate: Mapping[str, Any], key: str) -> int:
    score = candidate.get("score_profile")
    if isinstance(score, Mapping) and key in score:
        return _safe_int(score.get(key), 0)
    return _safe_int(candidate.get(key), 0)


def _candidate_discriminator(candidate: Mapping[str, Any]) -> str:
    gene = _safe_text(candidate.get("gene"), "the candidate")
    track = _candidate_render_track(candidate)
    if track == "validated-and-exploratory":
        return (
            f"Test whether {gene} shows disease-context target engagement "
            "and intervention directionality in disease-relevant cell states."
        )
    if track == "validated-dominant":
        return (
            f"Test whether existing {gene} target biology maps to disease-relevant "
            "cell states and ligand-receptor contexts in this dataset."
        )
    if track == "exploratory-dominant":
        return (
            f"Test {gene} tractability with perturbation evidence before "
            "advancing the candidate beyond exploratory prioritization."
        )
    return (
        f"Complete {gene} evidence coverage before prioritization, including "
        "source support, tractability, and disease-context perturbation data."
    )


def _candidate_section(candidate: Mapping[str, Any]) -> str:
    gene = _safe_text(candidate.get("gene"), "UNKNOWN")
    return "\n".join(
        [
            f"### Candidate: {gene}",
            (
                f"- Evidence track: {_candidate_render_track(candidate)} "
                "with combined score "
                f"{_candidate_render_score(candidate, 'combined_total')} "
                f"(validated {_candidate_render_score(candidate, 'validated_total')}, "
                "exploratory "
                f"{_candidate_render_score(candidate, 'exploratory_total')})."
            ),
            (
                "- Therapeutic rationale: "
                f"{_safe_text(candidate.get('therapeutic_rationale'))}"
            ),
            (
                "- Drug signal: "
                f"{_safe_text(candidate.get('drug_signal_summary'))}"
            ),
            (
                "- Drug-target evidence: "
                f"{_safe_text(candidate.get('drug_target_evidence'), 'No named clinical or preclinical drug records were available.')}"
            ),
            (
                "- Mechanistic synthesis role: "
                f"{_safe_text(candidate.get('mechanistic_role_summary'), 'No ranked mechanistic hypothesis explicitly linked this candidate in the deterministic hypothesis artifact.')}"
            ),
            (
                "- Experimental discriminator: "
                f"{_candidate_discriminator(candidate)}"
            ),
        ]
    )


def _integrated_thesis(synthesis: Mapping[str, Any]) -> str:
    disease = _safe_text(synthesis.get("disease"), "unspecified disease")
    counts = synthesis.get("candidate_counts")
    if not isinstance(counts, Mapping):
        counts = {}
    total_count = _safe_int(counts.get("total"), 0)
    validated_count = _safe_int(counts.get("validated"), 0)
    exploratory_count = _safe_int(counts.get("exploratory"), 0)
    candidates = _dict_list(synthesis.get("featured_candidates"))
    top_genes = [
        gene
        for candidate in candidates
        if (gene := _safe_text(candidate.get("gene")))
    ]
    candidate_clause = (
        f" The top triage set centers on {', '.join(top_genes)}."
        if top_genes
        else " No featured candidates were available for gene-level triage."
    )
    return (
        f"For {disease}, the deterministic therapeutic landscape contains "
        f"{_plural_phrase(total_count, 'candidate gene')}, including "
        f"{_plural_phrase(validated_count, 'validated-classified entry', 'validated-classified entries')} "
        "and "
        f"{_plural_phrase(exploratory_count, 'exploratory-classified entry', 'exploratory-classified entries')}. "
        "The synthesis treats these as evidence strata for "
        "experimental prioritization and mechanistic testing, not as "
        f"readiness for care decisions.{candidate_clause}"
    )


def _plural_phrase(count: int, singular: str, plural: str | None = None) -> str:
    label = singular if count == 1 else plural or f"{singular}s"
    return f"{count} {label}"


def _bounded_text(
    value: object,
    default: str = "",
    *,
    limit: int = _MAX_RENDER_TEXT_CHARS,
) -> str:
    text = re.sub(r"\s+", " ", _safe_text(value, default)).strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)].rstrip() + "..."


def _render_list_or_fallback(items: object, fallback: str) -> str:
    values = [
        _bounded_text(item, limit=_MAX_RENDER_LIST_ITEM_CHARS)
        for item in _string_list(items)[:_MAX_RENDER_LIST_ITEMS]
    ]
    return ", ".join(values) if values else fallback


def _hypothesis_section(hypothesis: Mapping[str, Any]) -> str:
    rank = _safe_int(hypothesis.get("rank"), 0)
    rank_text = str(rank) if rank else "unranked"
    title = _bounded_text(hypothesis.get("title"), "Mechanistic hypothesis")
    score_profile = hypothesis.get("score_profile")
    composite_score = (
        score_profile.get("composite")
        if isinstance(score_profile, Mapping)
        else None
    )
    score_line = (
        f"**Composite score:** {_bounded_text(composite_score)}"
        if _safe_text(composite_score)
        else "**Composite score:** No composite score was recorded."
    )
    evidence_references = [
        _bounded_text(reference, limit=_MAX_RENDER_LIST_ITEM_CHARS)
        for reference in _string_list(hypothesis.get("evidence_references"))[
            :_MAX_RENDER_LIST_ITEMS
        ]
    ]
    evidence_line = (
        ", ".join(evidence_references)
        if evidence_references
        else "No evidence references were recorded."
    )
    core_claim = _safe_text(
        _bounded_text(hypothesis.get("core_claim")),
        "No explicit core claim was available in the deterministic hypothesis artifact.",
    )
    prediction = _safe_text(
        _bounded_text(hypothesis.get("falsifiable_prediction")),
        "No explicit falsifiable prediction was available in the deterministic hypothesis artifact.",
    )
    validation_design = _safe_text(
        _bounded_text(hypothesis.get("validation_approach")),
        "No explicit validation design was available in the deterministic hypothesis artifact.",
    )
    return "\n".join(
        [
            f"### Hypothesis {rank_text}: {title}",
            f"**Category:** {_bounded_text(hypothesis.get('category'), 'unspecified')}",
            (
                "**Genes:** "
                f"{_render_list_or_fallback(hypothesis.get('genes'), 'No genes were recorded.')}"
            ),
            (
                "**Pathways:** "
                f"{_render_list_or_fallback(hypothesis.get('pathways'), 'No pathways were recorded.')}"
            ),
            (
                "**Cell types:** "
                f"{_render_list_or_fallback(hypothesis.get('cell_types'), 'No cell types were recorded.')}"
            ),
            (
                "**Candidate compounds:** "
                f"{_render_list_or_fallback(hypothesis.get('drugs'), 'No candidate compounds were recorded.')}"
            ),
            f"**Core claim:** {core_claim}",
            f"**Falsifiable prediction:** {prediction}",
            f"**Validation design:** {validation_design}",
            f"**Evidence anchors:** {evidence_line}",
            score_line,
        ]
    )


def _issue_bullet(issue: Mapping[str, Any]) -> str:
    code = _safe_text(issue.get("code"), "UNKNOWN_VALIDATION_ISSUE")
    severity = _safe_text(issue.get("severity"), "unspecified")
    message = _safe_text(issue.get("message"))
    suffix = f": {message}" if message else ""
    return f"- {code} ({severity}){suffix}"


def _scrub_disallowed_phrases(text: str) -> str:
    scrubbed = _EXPAND_MARKER_PATTERN.sub("artifact marker", text)
    for phrase, replacement in _DISALLOWED_MARKDOWN_PHRASES:
        escaped_phrase = re.escape(phrase).replace(r"\ ", r"\s+")
        pattern = re.compile(
            rf"(?<!\w){escaped_phrase}(?!\w)",
            flags=re.IGNORECASE,
        )
        scrubbed = re.sub(
            pattern,
            replacement,
            scrubbed,
        )
    return scrubbed


def render_part4_therapeutic_synthesis_markdown(
    synthesis: Mapping[str, Any],
) -> str:
    """Render deterministic Part 4 synthesis Markdown."""

    disease = _safe_text(synthesis.get("disease"), "unspecified disease")
    counts = synthesis.get("candidate_counts")
    if not isinstance(counts, Mapping):
        counts = {}
    candidates = _dict_list(synthesis.get("featured_candidates"))
    hypotheses = _dict_list(synthesis.get("hypotheses"))
    interpretation_summary = synthesis.get("interpretation_summary")
    if not isinstance(interpretation_summary, Mapping):
        interpretation_summary = {}
    validation_issues = _dict_list(synthesis.get("validation_issues"))
    report_valid = _safe_bool(synthesis.get("report_valid"))

    candidate_lines = "\n\n".join(
        _candidate_section(candidate)
        for candidate in candidates
    )
    if not candidate_lines:
        candidate_lines = (
            "- No featured therapeutic candidates were available in the "
            "deterministic report data."
        )

    hypothesis_lines = "\n\n".join(
        _hypothesis_section(hypothesis)
        for hypothesis in hypotheses
    )
    if not hypothesis_lines:
        hypothesis_lines = (
            "- No mechanistic hypotheses were available for intervention mapping."
        )

    issue_lines = "\n".join(
        _issue_bullet(issue)
        for issue in validation_issues[:5]
    )
    if not issue_lines:
        issue_lines = "- No blocking report validation issues were recorded."

    validation_sentence = (
        "The deterministic report validation status is valid."
        if report_valid
        else "The deterministic report validation status is invalid or unavailable."
    )
    caveat_section = ""
    if not report_valid:
        caveat_section = """
## Data Validity Caveat
The deterministic report validation status is invalid or unavailable. Candidate and hypothesis content below is retained only as a diagnostic synthesis of available artifacts and should not be treated as a completed prioritization.
"""

    markdown = f"""# Part 4: Therapeutic Synthesis

## Therapeutic Opportunity Landscape
The DrugTargetAgent assessment for {disease} evaluated {_safe_int(counts.get("total"), 0)} candidate genes. This Part 4 synthesis narrows the deterministic output to {_safe_int(counts.get("featured"), 0)} top triage candidates from {_safe_int(counts.get("stage3_total"), 0)} stage3 candidates, while keeping validated and exploratory evidence tracks separate.
{caveat_section}
## Integrated Therapeutic Thesis
{_integrated_thesis(synthesis)}

## Candidate Triage
{candidate_lines}

## Mechanistic Intervention Map
{hypothesis_lines}

## Validation Next Steps
- Confirm target localization and ligand-receptor context in the disease-relevant tissue and cell states.
- Run perturbation assays for the featured targets before interpreting intervention directionality.
- Measure target engagement markers and downstream pathway response in the implicated cell contexts.
- Review safety, tractability, and evidence-source coverage before moving beyond experimental prioritization.

## Confidence and Caveats
{validation_sentence}

Interpretation snippets: accepted={_safe_int(interpretation_summary.get("accepted"), 0)}, rejected={_safe_int(interpretation_summary.get("rejected"), 0)}, missing={_safe_int(interpretation_summary.get("missing"), 0)}, provider_errors={_safe_int(interpretation_summary.get("provider_errors"), 0)}, criteria_met={_safe_bool(interpretation_summary.get("criteria_met"))}.

Validation issues:
{issue_lines}

This section is a scientific therapeutic synthesis for experimental prioritization only. It is not care guidance.
"""
    return _scrub_disallowed_phrases(markdown).strip() + "\n"

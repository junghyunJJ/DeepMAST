#!/usr/bin/env python3
"""Grade saved PubMed papers into deterministic evidence buckets.

This script is intentionally stdlib-only. It reads the full JSON payload saved by
search_literature_dynamic, deduplicates papers in saved order, checks title and
abstract evidence, and writes citation_candidates.json plus a compact markdown
report for downstream interpretation.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "biomedical-literature-evidence-v1"
LR_BENCHMARK_REPORT_PROTOCOL = "bucket_synthesis_v2"
BUCKET_ORDER = [
    "direct_lr_evidence",
    "receptor_pathway_context_evidence",
    "disease_only_background",
    "rejected_weak_evidence",
]
BUCKET_SCORES = {
    "direct_lr_evidence": 100,
    "receptor_pathway_context_evidence": 70,
    "disease_only_background": 40,
    "rejected_weak_evidence": 0,
}


def _split_terms(values: list[str] | None) -> list[str]:
    terms: list[str] = []
    for raw in values or []:
        for item in raw.split(","):
            term = item.strip()
            if term:
                terms.append(term)
    return terms


def _normalize_text(value: Any) -> str:
    text = str(value or "").lower()
    text = text.replace("\u03b2", "beta")
    text = re.sub(r"\btgf\s*-?\s*beta\b", "tgf beta", text)
    text = re.sub(r"\btgfb\b", "tgf beta", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_doi(value: Any) -> str:
    doi = str(value or "").strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return doi.strip(" .,;")


def _normalize_title(value: Any) -> str:
    return _normalize_text(value)


def _dedup_key(paper: dict[str, Any]) -> str:
    pmid = str(paper.get("pmid") or "").strip()
    if pmid:
        return f"pmid:{pmid}"
    doi = _normalize_doi(paper.get("doi"))
    if doi:
        return f"doi:{doi}"
    title = _normalize_title(paper.get("title"))
    if title:
        return f"title:{title}"
    return ""


def _dedup_papers(papers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    duplicates = 0
    for paper in papers:
        key = _dedup_key(paper)
        if key and key in seen:
            duplicates += 1
            continue
        if key:
            seen.add(key)
        unique.append(paper)
    return unique, duplicates


def _evidence_text(paper: dict[str, Any]) -> tuple[str, bool, bool]:
    title = str(paper.get("title") or "").strip()
    abstract = str(paper.get("abstract") or "").strip()
    abstract_missing = not bool(abstract)
    if title and abstract:
        return f"{title} {abstract}", abstract_missing, False
    if title:
        return title, abstract_missing, False
    if abstract:
        return abstract, abstract_missing, False
    return "", abstract_missing, True


def _symbol_match(text: str, symbol: str) -> bool:
    if not symbol:
        return False
    pattern = re.compile(
        r"(?<![A-Za-z0-9])" + re.escape(symbol) + r"(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    return bool(pattern.search(text))


def _matched_phrases(text: str, terms: list[str]) -> list[str]:
    normalized_text = _normalize_text(text)
    matched: list[str] = []
    for term in terms:
        normalized_term = _normalize_text(term)
        if normalized_term and normalized_term in normalized_text:
            matched.append(term)
    return matched


def _classify_candidate(
    paper: dict[str, Any],
    *,
    ligand: str,
    receptor: str,
    disease: str,
    pathways: list[str],
    celltypes: list[str],
) -> dict[str, Any]:
    text, abstract_missing, evidence_missing = _evidence_text(paper)
    ligand_match = _symbol_match(text, ligand)
    receptor_match = _symbol_match(text, receptor)
    disease_matches = _matched_phrases(text, [disease] if disease else [])
    pathway_matches = _matched_phrases(text, pathways)
    celltype_matches = _matched_phrases(text, celltypes)
    disease_required = bool(disease)
    disease_match = bool(disease_matches) if disease_required else True

    reasons: list[str] = []
    if evidence_missing:
        bucket = "rejected_weak_evidence"
        reasons.append("evidence_text_missing")
    elif ligand_match and receptor_match and disease_match:
        bucket = "direct_lr_evidence"
        reasons.append("ligand_receptor_disease_co_mention")
    elif ligand_match and receptor_match and not disease_match:
        bucket = "rejected_weak_evidence"
        reasons.append("lr_match_without_disease_context")
    elif disease_match and (ligand_match or receptor_match or pathway_matches or celltype_matches):
        bucket = "receptor_pathway_context_evidence"
        reasons.append("disease_context_with_partial_lr_or_modifier")
    elif disease_match:
        bucket = "disease_only_background"
        reasons.append("disease_context_only")
    else:
        bucket = "rejected_weak_evidence"
        reasons.append("no_disease_anchored_evidence")

    if abstract_missing and not evidence_missing:
        reasons.append("title_only_evidence")

    return {
        "pmid": str(paper.get("pmid") or "").strip(),
        "title": str(paper.get("title") or "").strip(),
        "doi": str(paper.get("doi") or "").strip(),
        "dedup_key": _dedup_key(paper),
        "bucket": bucket,
        "score": BUCKET_SCORES[bucket],
        "matched_terms": {
            "ligand": ligand if ligand_match else "",
            "receptor": receptor if receptor_match else "",
            "disease": disease_matches,
            "pathways": pathway_matches,
            "celltypes": celltype_matches,
        },
        "abstract_missing": abstract_missing,
        "evidence_text_missing": evidence_missing,
        "reasons": reasons,
    }


def grade_papers(
    payload: dict[str, Any],
    *,
    papers_json: Path,
    ligand: str,
    receptor: str,
    disease: str,
    pathways: list[str],
    celltypes: list[str],
) -> dict[str, Any]:
    raw_papers = payload.get("papers", [])
    if not isinstance(raw_papers, list):
        raw_papers = []
    papers = [paper for paper in raw_papers if isinstance(paper, dict)]
    unique, duplicates = _dedup_papers(papers)
    buckets: dict[str, list[dict[str, Any]]] = {bucket: [] for bucket in BUCKET_ORDER}

    for paper in unique:
        candidate = _classify_candidate(
            paper,
            ligand=ligand,
            receptor=receptor,
            disease=disease,
            pathways=pathways,
            celltypes=celltypes,
        )
        buckets[candidate["bucket"]].append(candidate)

    return {
        "schema_version": SCHEMA_VERSION,
        "inputs": {
            "ligand": ligand,
            "receptor": receptor,
            "disease": disease,
            "pathways": pathways,
            "celltypes": celltypes,
        },
        "source": {
            "papers_json": str(papers_json),
            "total_papers": len(papers),
            "unique_papers": len(unique),
            "duplicates_dropped": duplicates,
        },
        "counts": {bucket: len(buckets[bucket]) for bucket in BUCKET_ORDER},
        "bucket_order": BUCKET_ORDER,
        "buckets": buckets,
    }


def _citation_line(candidate: dict[str, Any]) -> str:
    pmid = str(candidate.get("pmid") or "").strip()
    title = str(candidate.get("title") or "").strip()
    if pmid and title:
        return f"- PMID:{pmid} - {title}"
    return ""


def _claim_summary(result: dict[str, Any], candidate: dict[str, Any]) -> str:
    inputs = result.get("inputs", {})
    ligand = str(inputs.get("ligand") or "the ligand").strip()
    receptor = str(inputs.get("receptor") or "the receptor").strip()
    disease = str(inputs.get("disease") or "the disease context").strip()
    bucket = str(candidate.get("bucket") or "")
    if bucket == "direct_lr_evidence":
        return f"Direct title/abstract evidence co-mentions {ligand} and {receptor} in {disease}"
    if bucket == "receptor_pathway_context_evidence":
        matched = candidate.get("matched_terms", {})
        receptor_match = bool(matched.get("receptor"))
        pathway_match = bool(matched.get("pathways"))
        celltype_match = bool(matched.get("celltypes"))
        supports: list[str] = []
        if receptor_match:
            supports.append(f"{receptor} context")
        if pathway_match:
            supports.append("pathway context")
        if celltype_match:
            supports.append("celltype context")
        support_text = ", ".join(supports) if supports else "partial LR context"
        return f"Indirect {disease} evidence supports {support_text}"
    return f"Background {disease} evidence without direct {ligand}-{receptor} support"


def _benchmark_citation_line(result: dict[str, Any], candidate: dict[str, Any]) -> str:
    pmid = str(candidate.get("pmid") or "").strip()
    title = str(candidate.get("title") or "").strip()
    if pmid and title:
        return f"- PMID:{pmid} - {_claim_summary(result, candidate)} - {title}"
    return ""


def _numeric_pmid(candidate: dict[str, Any]) -> str:
    pmid = str(candidate.get("pmid") or "").strip()
    return pmid if pmid.isdigit() else ""


def _pmid_sort_key(candidate: dict[str, Any]) -> tuple[int, int | str]:
    pmid = str(candidate.get("pmid") or "").strip()
    if pmid.isdigit():
        return (0, int(pmid))
    if pmid:
        return (1, pmid)
    return (2, "")


def _matched_term_richness(candidate: dict[str, Any]) -> int:
    matched = candidate.get("matched_terms", {})
    if not isinstance(matched, dict):
        matched = {}
    return (
        int(bool(matched.get("ligand")))
        + int(bool(matched.get("receptor")))
        + len(matched.get("disease") or [])
        + len(matched.get("pathways") or [])
        + len(matched.get("celltypes") or [])
    )


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[int, int, int, tuple[int, int | str], str]:
    bucket = str(candidate.get("bucket") or "")
    abstract_present = not bool(candidate.get("abstract_missing"))
    return (
        -int(candidate.get("score") or BUCKET_SCORES.get(bucket, 0)),
        0 if abstract_present else 1,
        -_matched_term_richness(candidate),
        _pmid_sort_key(candidate),
        _normalize_title(candidate.get("title")),
    )


def _ordered_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(candidates, key=_candidate_sort_key)


def _select_lr_benchmark_candidates(
    direct: list[dict[str, Any]],
    context: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    citable_direct = [candidate for candidate in _ordered_candidates(direct) if _numeric_pmid(candidate)]
    citable_context = [candidate for candidate in _ordered_candidates(context) if _numeric_pmid(candidate)]
    uncitable = sum(1 for candidate in [*direct, *context] if not _numeric_pmid(candidate))

    if not citable_direct:
        return citable_context[:8], uncitable

    selected_direct = citable_direct[:3]
    selected_context = citable_context[:5]
    selected = [*selected_direct, *selected_context]
    remaining = 8 - len(selected)
    if remaining > 0:
        selected_ids = {id(candidate) for candidate in selected}
        fill_pool = [
            candidate
            for candidate in [*citable_context[5:], *citable_direct[3:]]
            if id(candidate) not in selected_ids
        ]
        selected.extend(fill_pool[:remaining])
    return selected[:8], uncitable


def write_report(result: dict[str, Any], report_path: Path) -> None:
    counts = result["counts"]
    direct = result["buckets"]["direct_lr_evidence"]
    context = result["buckets"]["receptor_pathway_context_evidence"]
    background = result["buckets"]["disease_only_background"]
    rejected = result["buckets"]["rejected_weak_evidence"]

    lines = [
        "retrieval_mode: evidence_retrieval",
        "",
        "## Summary",
        f"- source papers: {result['source']['total_papers']}",
        f"- unique papers: {result['source']['unique_papers']}",
        f"- duplicates dropped: {result['source']['duplicates_dropped']}",
        f"- direct LR evidence: {counts['direct_lr_evidence']}",
        f"- context evidence: {counts['receptor_pathway_context_evidence']}",
        f"- disease-only background: {counts['disease_only_background']}",
        f"- rejected / weak: {counts['rejected_weak_evidence']}",
        "",
        "## Direct LR Evidence",
    ]
    if direct:
        lines.extend(_citation_line(candidate) for candidate in direct if _citation_line(candidate))
    else:
        lines.append("No disease-anchored direct LR evidence candidates passed the title/abstract check.")

    lines.extend(["", "## Context Evidence"])
    if context:
        for candidate in context[:10]:
            pmid = candidate.get("pmid") or "no PMID"
            title = candidate.get("title") or "untitled"
            lines.append(f"- {pmid} - {title}")
    else:
        lines.append("No context evidence candidates.")

    lines.extend(["", "## Background"])
    if background:
        for candidate in background[:10]:
            pmid = candidate.get("pmid") or "no PMID"
            title = candidate.get("title") or "untitled"
            lines.append(f"- {pmid} - {title}")
    else:
        lines.append("No disease-only background candidates.")

    lines.extend(["", "## Rejected / Weak Evidence Notes"])
    if rejected:
        reason_counts: dict[str, int] = {}
        for candidate in rejected:
            for reason in candidate.get("reasons", []):
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
        for reason, count in sorted(reason_counts.items()):
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("No rejected or weak candidates.")

    lines.extend(["", "## Citations"])
    lines.extend(line for candidate in direct if (line := _citation_line(candidate)))
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_benchmark_report(result: dict[str, Any], report_path: Path) -> None:
    inputs = result.get("inputs", {})
    ligand = str(inputs.get("ligand") or "ligand").strip()
    receptor = str(inputs.get("receptor") or "receptor").strip()
    disease = str(inputs.get("disease") or "disease context").strip()
    counts = result["counts"]
    direct = result["buckets"]["direct_lr_evidence"]
    context = result["buckets"]["receptor_pathway_context_evidence"]
    background = result["buckets"]["disease_only_background"]
    rejected = result["buckets"]["rejected_weak_evidence"]
    citation_pool = direct if direct else context

    lines = [
        "## Interpretation",
        (
            f"The retrieved title/abstract evidence for {ligand}-{receptor} in "
            f"{disease} contains {counts['direct_lr_evidence']} direct LR "
            f"candidate(s), {counts['receptor_pathway_context_evidence']} "
            "context candidate(s), "
            f"{counts['disease_only_background']} disease-only background "
            f"candidate(s), and {counts['rejected_weak_evidence']} weak or "
            "rejected candidate(s)."
        ),
        "",
        "## Direct evidence",
    ]
    if direct:
        for candidate in direct[:5]:
            title = candidate.get("title") or "untitled"
            pmid = candidate.get("pmid") or "no PMID"
            lines.append(f"- PMID:{pmid} supports direct disease-anchored LR co-mention: {title}")
    else:
        lines.append(
            f"No retrieved title/abstract candidate directly co-mentions {ligand} "
            f"and {receptor} with the {disease} disease anchor."
        )

    lines.extend(["", "## Indirect/pathway evidence"])
    if context:
        for candidate in context[:8]:
            title = candidate.get("title") or "untitled"
            pmid = candidate.get("pmid") or "no PMID"
            lines.append(f"- PMID:{pmid} provides indirect or contextual support: {title}")
    else:
        lines.append("No indirect/pathway context candidates passed deterministic grading.")

    lines.extend(["", "## Limitations"])
    if background:
        lines.append(
            f"- {len(background)} disease-only background candidate(s) were retained "
            "for audit but excluded from the main synthesis context."
        )
    if rejected:
        lines.append(
            f"- {len(rejected)} weak/rejected candidate(s) were retained for audit "
            "but excluded from citations and main synthesis."
        )
    if not direct:
        lines.append("- Any interpretation should be labeled indirect because no direct LR citation passed.")
    if not background and not rejected and direct:
        lines.append("- The report is limited to title/abstract evidence; full text was not reviewed.")

    lines.extend(["", "## Citations"])
    if citation_pool:
        lines.extend(
            line for candidate in citation_pool[:5] if (line := _benchmark_citation_line(result, candidate))
        )
    else:
        lines.append("No citation candidates passed deterministic evidence grading.")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_lr_benchmark_report_v2(result: dict[str, Any], report_path: Path) -> None:
    inputs = result.get("inputs", {})
    ligand = str(inputs.get("ligand") or "ligand").strip()
    receptor = str(inputs.get("receptor") or "receptor").strip()
    disease = str(inputs.get("disease") or "disease context").strip()
    counts = result["counts"]
    direct = result["buckets"]["direct_lr_evidence"]
    context = result["buckets"]["receptor_pathway_context_evidence"]
    background = result["buckets"]["disease_only_background"]
    rejected = result["buckets"]["rejected_weak_evidence"]
    selected, uncitable = _select_lr_benchmark_candidates(direct, context)
    selected_direct = [
        candidate for candidate in selected if candidate.get("bucket") == "direct_lr_evidence"
    ]
    selected_context = [
        candidate
        for candidate in selected
        if candidate.get("bucket") == "receptor_pathway_context_evidence"
    ]

    lines = [
        "## Interpretation",
        (
            f"The retrieved title/abstract evidence for {ligand}-{receptor} in "
            f"{disease} contains {counts['direct_lr_evidence']} direct LR "
            f"candidate(s), {counts['receptor_pathway_context_evidence']} "
            "context candidate(s), "
            f"{counts['disease_only_background']} disease-only background "
            f"candidate(s), and {counts['rejected_weak_evidence']} weak or "
            "rejected candidate(s)."
        ),
        "",
        "## Direct evidence",
    ]
    if selected_direct:
        for candidate in selected_direct:
            title = candidate.get("title") or "untitled"
            pmid = _numeric_pmid(candidate)
            lines.append(f"- PMID:{pmid} supports direct disease-anchored LR co-mention: {title}")
    elif direct:
        lines.append(
            "Direct LR candidates passed deterministic grading, but none had a "
            "numeric PMID suitable for judge-visible citations."
        )
    else:
        lines.append(
            f"No retrieved title/abstract candidate directly co-mentions {ligand} "
            f"and {receptor} with the {disease} disease anchor."
        )

    lines.extend(["", "## Indirect/pathway evidence"])
    if selected_context:
        for candidate in selected_context:
            title = candidate.get("title") or "untitled"
            pmid = _numeric_pmid(candidate)
            lines.append(f"- PMID:{pmid} provides indirect or contextual support: {title}")
    elif context:
        lines.append(
            "Indirect/pathway context candidates passed deterministic grading, but "
            "none had a numeric PMID suitable for judge-visible citations."
        )
    else:
        lines.append("No indirect/pathway context candidates passed deterministic grading.")

    lines.extend(["", "## Limitations"])
    if background:
        lines.append(
            f"- {len(background)} disease-only background candidate(s) were retained "
            "for audit but excluded from the main synthesis context."
        )
    if rejected:
        lines.append(
            f"- {len(rejected)} weak/rejected candidate(s) were retained for audit "
            "but excluded from citations and main synthesis."
        )
    if uncitable:
        lines.append(
            f"- {uncitable} direct/context candidate(s) lacked a numeric PMID and were "
            "excluded from judge-visible citations."
        )
    if not direct:
        lines.append("- Any interpretation should be labeled indirect because no direct LR citation passed.")
    if not background and not rejected and direct:
        lines.append("- The report is limited to title/abstract evidence; full text was not reviewed.")

    lines.extend(["", "## Citations"])
    if selected:
        lines.extend(
            line for candidate in selected if (line := _benchmark_citation_line(result, candidate))
        )
    else:
        lines.append("No citation candidates passed deterministic evidence grading.")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Grade search_literature_dynamic papers into evidence buckets."
    )
    parser.add_argument("--papers-json", required=True, help="Saved papers.json path.")
    parser.add_argument("--ligand", required=True, help="Ligand gene symbol.")
    parser.add_argument("--receptor", required=True, help="Receptor gene symbol.")
    parser.add_argument("--disease", required=True, help="Disease anchor phrase.")
    parser.add_argument(
        "--pathways",
        action="append",
        default=[],
        help="Pathway modifier. May be repeated or comma-separated.",
    )
    parser.add_argument(
        "--celltypes",
        action="append",
        default=[],
        help="Celltype modifier. May be repeated or comma-separated.",
    )
    parser.add_argument("--output-json", required=True, help="Output citation_candidates.json path.")
    parser.add_argument("--report-md", required=True, help="Output final_report.md path.")
    parser.add_argument(
        "--report-style",
        choices=("operational", "benchmark", "lr-benchmark-v2"),
        default="operational",
        help=(
            "Markdown report style. Benchmark style uses neutral judge citation syntax; "
            "lr-benchmark-v2 uses LR-specific bucket synthesis."
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    papers_json = Path(args.papers_json).expanduser().resolve()
    output_json = Path(args.output_json).expanduser().resolve()
    report_md = Path(args.report_md).expanduser().resolve()

    payload = json.loads(papers_json.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("papers JSON must contain an object with a papers list")

    result = grade_papers(
        payload,
        papers_json=papers_json,
        ligand=args.ligand.strip().upper(),
        receptor=args.receptor.strip().upper(),
        disease=args.disease.strip(),
        pathways=_split_terms(args.pathways),
        celltypes=_split_terms(args.celltypes),
    )

    output_json.parent.mkdir(parents=True, exist_ok=True)
    report_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.report_style == "benchmark":
        write_benchmark_report(result, report_md)
    elif args.report_style == "lr-benchmark-v2":
        write_lr_benchmark_report_v2(result, report_md)
    else:
        write_report(result, report_md)
    print(json.dumps({"output_json": str(output_json), "report_md": str(report_md), "counts": result["counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

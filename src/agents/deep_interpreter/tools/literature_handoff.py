"""Build filtered literature handoff artifacts for Deep Interpreter.

SEARCHER retrieves a broad raw paper pool. This module grades papers into
direct/context/background/rejected buckets and writes the smaller
INTERPRETER-facing paper set.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


DIRECT_BUCKET = "direct_lr_evidence"
CONTEXT_BUCKET = "receptor_pathway_context_evidence"
BACKGROUND_BUCKET = "disease_only_background"
REJECTED_BUCKET = "rejected_weak_evidence"
ELIGIBLE_BUCKETS = {DIRECT_BUCKET, CONTEXT_BUCKET}
BUCKET_ORDER = [
    DIRECT_BUCKET,
    CONTEXT_BUCKET,
    BACKGROUND_BUCKET,
    REJECTED_BUCKET,
]
BUCKET_SCORE = {
    DIRECT_BUCKET: 100,
    CONTEXT_BUCKET: 70,
    BACKGROUND_BUCKET: 40,
    REJECTED_BUCKET: 0,
}
DEFAULT_HANDOFF_CAP = 40


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


def _dedup_key(paper: dict[str, Any]) -> str:
    pmid = str(paper.get("pmid") or "").strip()
    if pmid:
        return f"pmid:{pmid}"
    doi = _normalize_doi(paper.get("doi"))
    if doi:
        return f"doi:{doi}"
    title = _normalize_text(paper.get("title"))
    if title:
        return f"title:{title}"
    return ""


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


def _symbol_parts(symbol: str) -> list[str]:
    return [part.strip().upper() for part in str(symbol or "").split("_") if part.strip()]


def _symbol_match(text: str, symbol: str) -> bool:
    for part in _symbol_parts(symbol):
        pattern = re.compile(
            r"(?<![A-Za-z0-9])" + re.escape(part) + r"(?![A-Za-z0-9])",
            re.IGNORECASE,
        )
        if pattern.search(text):
            return True
    return False


def _matched_phrases(text: str, terms: list[str]) -> list[str]:
    normalized_text = _normalize_text(text)
    matched: list[str] = []
    for term in terms:
        normalized_term = _normalize_text(term)
        if normalized_term and normalized_term in normalized_text:
            matched.append(term)
    return matched


def _terms_from_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    else:
        try:
            values = list(value)
        except TypeError:
            values = [value]
    return [str(term).strip() for term in values if str(term).strip()]


def _classify_for_pair(
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
    disease_match = bool(disease_matches) if disease else True

    reasons: list[str] = []
    if evidence_missing:
        bucket = REJECTED_BUCKET
        reasons.append("evidence_text_missing")
    elif ligand_match and receptor_match and disease_match:
        bucket = DIRECT_BUCKET
        reasons.append("ligand_receptor_disease_co_mention")
    elif ligand_match and receptor_match and not disease_match:
        bucket = REJECTED_BUCKET
        reasons.append("lr_match_without_disease_context")
    elif disease_match and (
        ligand_match or receptor_match or pathway_matches or celltype_matches
    ):
        bucket = CONTEXT_BUCKET
        reasons.append("disease_context_with_partial_lr_or_modifier")
    elif disease_match:
        bucket = BACKGROUND_BUCKET
        reasons.append("disease_context_only")
    else:
        bucket = REJECTED_BUCKET
        reasons.append("no_disease_anchored_evidence")

    if abstract_missing and not evidence_missing:
        reasons.append("title_only_evidence")

    return {
        "bucket": bucket,
        "score": BUCKET_SCORE[bucket],
        "matched_terms": {
            "ligand": ligand if ligand_match else "",
            "receptor": receptor if receptor_match else "",
            "disease": disease_matches,
            "pathways": pathway_matches,
            "celltypes": celltype_matches,
        },
        "reasons": reasons,
        "abstract_missing": abstract_missing,
        "evidence_text_missing": evidence_missing,
    }


def _pair_label(pair: dict[str, Any]) -> str:
    label = str(pair.get("lr_pair") or "").strip()
    if label:
        return label
    ligand = str(pair.get("ligand") or "").strip()
    receptor = str(pair.get("receptor") or "").strip()
    return f"{ligand}-{receptor}" if ligand or receptor else ""


def _pair_metadata(pair: dict[str, Any]) -> dict[str, str]:
    return {
        "ligand": str(pair.get("ligand") or "").strip(),
        "receptor": str(pair.get("receptor") or "").strip(),
    }


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


def _sort_handoff_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = list(enumerate(papers))
    indexed.sort(
        key=lambda item: (
            0 if item[1].get("evidence_bucket") == DIRECT_BUCKET else 1,
            -len(item[1].get("supported_lr_pairs") or []),
            item[0],
        )
    )
    return [paper for _, paper in indexed]


def build_literature_handoff(
    raw_papers: list[dict[str, Any]],
    cap: int = DEFAULT_HANDOFF_CAP,
) -> dict[str, Any]:
    """Filter already-bucketed papers for INTERPRETER handoff.

    This is the small pure function used by unit tests and by the file-writing
    tool after pair-aware grading has attached `evidence_bucket` metadata.
    """
    unique, duplicates = _dedup_papers([p for p in raw_papers if isinstance(p, dict)])
    eligible = [
        paper
        for paper in unique
        if paper.get("evidence_bucket") in ELIGIBLE_BUCKETS
    ]
    selected = _sort_handoff_papers(eligible)[: max(0, int(cap))]
    counts = {bucket: 0 for bucket in BUCKET_ORDER}
    for paper in unique:
        bucket = str(paper.get("evidence_bucket") or REJECTED_BUCKET)
        counts[bucket if bucket in counts else REJECTED_BUCKET] += 1
    return {
        "schema_version": "deep_interpreter_literature_handoff_v1",
        "policy": {
            "included_buckets": [DIRECT_BUCKET, CONTEXT_BUCKET],
            "excluded_buckets": [BACKGROUND_BUCKET, REJECTED_BUCKET],
            "cap": cap,
        },
        "source": {
            "total_papers": len(raw_papers),
            "unique_papers": len(unique),
            "duplicates_dropped": duplicates,
        },
        "counts": counts,
        "papers": selected,
    }


def grade_lr_literature_candidates(
    payload: dict[str, Any],
    *,
    lr_pairs: list[dict[str, Any]],
    disease: str,
    pathways: list[str] | None = None,
    celltypes: list[str] | None = None,
) -> dict[str, Any]:
    """Grade raw papers against multiple LR pairs and collapse by best bucket."""
    raw_papers = payload.get("papers", []) if isinstance(payload, dict) else []
    papers, duplicates = _dedup_papers([p for p in raw_papers if isinstance(p, dict)])
    global_pathways = _terms_from_value(pathways)
    global_celltypes = _terms_from_value(celltypes)
    paper_records: list[dict[str, Any]] = []
    pair_results: list[dict[str, Any]] = []

    for paper in papers:
        best_bucket = REJECTED_BUCKET
        best_rank = BUCKET_SCORE[REJECTED_BUCKET]
        supported_pairs: list[dict[str, str]] = []
        direct_pairs: list[dict[str, str]] = []
        context_pairs: list[dict[str, str]] = []
        matched_terms_by_pair: dict[str, Any] = {}
        reasons_by_pair: dict[str, list[str]] = {}

        for pair in lr_pairs:
            pair_pathways = _terms_from_value(pair.get("pathways"))
            pair_celltypes = _terms_from_value(pair.get("celltypes"))
            classification = _classify_for_pair(
                paper,
                ligand=str(pair.get("ligand") or "").strip(),
                receptor=str(pair.get("receptor") or "").strip(),
                disease=disease,
                pathways=pair_pathways,
                celltypes=pair_celltypes,
            )
            bucket = classification["bucket"]
            rank = BUCKET_SCORE[bucket]
            label = _pair_label(pair)
            meta = _pair_metadata(pair)
            if bucket == DIRECT_BUCKET:
                direct_pairs.append(meta)
                supported_pairs.append(meta)
            elif bucket == CONTEXT_BUCKET:
                matched = classification["matched_terms"]
                has_pair_scoped_context = bool(
                    matched["ligand"]
                    or matched["receptor"]
                    or matched["pathways"]
                    or matched["celltypes"]
                )
                if has_pair_scoped_context:
                    context_pairs.append(meta)
                    supported_pairs.append(meta)
            if bucket in ELIGIBLE_BUCKETS and label:
                matched_terms_by_pair[label] = classification["matched_terms"]
            if label:
                reasons_by_pair[label] = classification["reasons"]
            if rank > best_rank:
                best_rank = rank
                best_bucket = bucket

        global_classification = _classify_for_pair(
            paper,
            ligand="",
            receptor="",
            disease=disease,
            pathways=global_pathways,
            celltypes=global_celltypes,
        )
        global_rank = BUCKET_SCORE[global_classification["bucket"]]
        if global_rank > best_rank:
            best_rank = global_rank
            best_bucket = global_classification["bucket"]

        enriched = dict(paper)
        enriched["evidence_bucket"] = best_bucket
        enriched["supported_lr_pairs"] = supported_pairs
        enriched["direct_lr_pairs"] = direct_pairs
        enriched["context_lr_pairs"] = context_pairs
        enriched["matched_terms_by_pair"] = matched_terms_by_pair
        enriched["bucket_reasons_by_pair"] = reasons_by_pair
        enriched["global_matched_terms"] = global_classification["matched_terms"]
        enriched["global_bucket_reasons"] = global_classification["reasons"]
        paper_records.append(enriched)

    counts = {bucket: 0 for bucket in BUCKET_ORDER}
    for paper in paper_records:
        counts[str(paper.get("evidence_bucket") or REJECTED_BUCKET)] += 1

    for pair in lr_pairs:
        meta = _pair_metadata(pair)
        direct_count = sum(meta in p.get("direct_lr_pairs", []) for p in paper_records)
        context_count = sum(meta in p.get("context_lr_pairs", []) for p in paper_records)
        pair_results.append({
            "lr_pair": _pair_label(pair),
            "ligand": meta["ligand"],
            "receptor": meta["receptor"],
            "direct_lr_evidence": direct_count,
            "receptor_pathway_context_evidence": context_count,
        })

    return {
        "schema_version": "deep_interpreter_literature_candidates_v1",
        "inputs": {
            "disease": disease,
            "lr_pairs": lr_pairs,
            "pathways": global_pathways,
            "celltypes": global_celltypes,
        },
        "source": {
            "total_papers": len(raw_papers),
            "unique_papers": len(papers),
            "duplicates_dropped": duplicates,
        },
        "bucket_order": BUCKET_ORDER,
        "counts": counts,
        "pair_results": pair_results,
        "papers": paper_records,
    }


def _resolve_data_file(data_dir: str, path: str) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    base = Path(data_dir or os.getenv("DEEP_INTERPRETER_DATA_DIR", "")).expanduser()
    if not str(base):
        base = Path.cwd()
    return (base / p).resolve()


@tool
def create_literature_handoff(
    raw_papers_path: str = "papers_raw.json",
    output_path: str = "papers.json",
    citation_candidates_path: str = "citation_candidates.json",
    data_dir: str = "",
    disease: str = "",
    lr_pairs: list[dict[str, Any]] | None = None,
    pathways: list[str] | None = None,
    celltypes: list[str] | None = None,
    cap: int = DEFAULT_HANDOFF_CAP,
) -> dict[str, Any]:
    """Create bucketed citation candidates and filtered papers.json handoff.

    Reads raw_papers_path from data_dir, writes citation_candidates_path and
    output_path in data_dir, and returns a compact summary.
    """
    raw_path = _resolve_data_file(data_dir, raw_papers_path)
    candidates_path = _resolve_data_file(data_dir, citation_candidates_path)
    handoff_path = _resolve_data_file(data_dir, output_path)
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("raw papers JSON must be an object")

    pairs = lr_pairs
    if not pairs:
        pair_file = _resolve_data_file(data_dir, "lr_pairs_search.json")
        if pair_file.exists():
            pair_payload = json.loads(pair_file.read_text(encoding="utf-8"))
            pairs = pair_payload.get("pairs", [])
    pairs = [pair for pair in pairs or [] if isinstance(pair, dict)]

    candidates = grade_lr_literature_candidates(
        payload,
        lr_pairs=pairs,
        disease=disease,
        pathways=pathways,
        celltypes=celltypes,
    )
    handoff = build_literature_handoff(candidates["papers"], cap=cap)
    handoff["source"]["raw_papers_path"] = str(raw_path)
    handoff["source"]["citation_candidates_path"] = str(candidates_path)
    handoff["search_method"] = payload.get("search_method", "")
    handoff["coverage"] = payload.get("coverage", {})

    candidates_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    candidates_path.write_text(
        json.dumps(candidates, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    handoff_path.write_text(
        json.dumps(handoff, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return {
        "saved_to": str(handoff_path),
        "citation_candidates": str(candidates_path),
        "raw_papers": str(raw_path),
        "total_raw_papers": candidates["source"]["total_papers"],
        "total_handoff_papers": len(handoff["papers"]),
        "counts": candidates["counts"],
        "policy": handoff["policy"],
    }

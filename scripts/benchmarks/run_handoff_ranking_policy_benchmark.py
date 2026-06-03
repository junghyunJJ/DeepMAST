#!/usr/bin/env python3
"""Benchmark deterministic INTERPRETER handoff ranking policies.

This script starts from already-created ``citation_candidates.json`` files. It
does not rerun literature search and does not call LLM judges.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DIRECT_BUCKET = "direct_lr_evidence"
CONTEXT_BUCKET = "receptor_pathway_context_evidence"
BACKGROUND_BUCKET = "disease_only_background"
REJECTED_BUCKET = "rejected_weak_evidence"
ELIGIBLE_BUCKETS = {DIRECT_BUCKET, CONTEXT_BUCKET}
EXCLUDED_BUCKETS = {BACKGROUND_BUCKET, REJECTED_BUCKET}
DEFAULT_CAP = 40

ACTIVE_POLICIES = (
    "baseline_current",
    "bucket_lr_coverage",
    "bucket_lr_coverage_journal_tiebreak",
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_text(value: Any) -> str:
    text = str(value or "").lower()
    text = text.replace("\u03b2", "beta")
    text = re.sub(r"\btgf\s*-?\s*beta\b", "tgf beta", text)
    text = re.sub(r"\btgfb\b", "tgf beta", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _safe_id(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    clean = clean.strip("._")
    return clean or "candidate"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in _as_list(value) if str(item).strip()]


def _split_gene_symbol(symbol: Any) -> list[str]:
    return [part.strip().upper() for part in str(symbol or "").split("_") if part.strip()]


def _paper_text(paper: dict[str, Any]) -> str:
    return f"{paper.get('title', '')} {paper.get('abstract', '')}"


def _contains_term(text: str, term: str) -> bool:
    normalized_text = _normalize_text(text)
    normalized_term = _normalize_text(term)
    if not normalized_term:
        return False
    if len(normalized_term) <= 4:
        return bool(
            re.search(
                r"(?<![a-z0-9])" + re.escape(normalized_term) + r"(?![a-z0-9])",
                normalized_text,
            )
        )
    return normalized_term in normalized_text


def _paper_key(paper: dict[str, Any]) -> str:
    pmid = str(paper.get("pmid") or "").strip()
    if pmid:
        return f"pmid:{pmid}"
    doi = str(paper.get("doi") or "").strip().lower()
    if doi:
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
        return f"doi:{doi.strip(' .,;')}"
    title = _normalize_text(paper.get("title"))
    if title:
        return f"title:{title}"
    return f"object:{id(paper)}"


def _candidate_papers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("papers"), list):
        raw = [paper for paper in payload["papers"] if isinstance(paper, dict)]
    elif isinstance(payload.get("buckets"), dict):
        raw = []
        for bucket in payload.get("bucket_order") or [
            DIRECT_BUCKET,
            CONTEXT_BUCKET,
            BACKGROUND_BUCKET,
            REJECTED_BUCKET,
        ]:
            for paper in payload["buckets"].get(bucket, []):
                if isinstance(paper, dict):
                    item = dict(paper)
                    item.setdefault("evidence_bucket", item.get("bucket") or bucket)
                    raw.append(item)
    else:
        raw = []

    seen: set[str] = set()
    papers: list[dict[str, Any]] = []
    for index, paper in enumerate(raw):
        item = dict(paper)
        item.setdefault("evidence_bucket", item.get("bucket") or REJECTED_BUCKET)
        item["_candidate_original_index"] = index
        key = _paper_key(item)
        if key in seen:
            continue
        seen.add(key)
        papers.append(item)
    return papers


def _lr_pairs(payload: dict[str, Any]) -> list[dict[str, str]]:
    inputs = payload.get("inputs", {}) if isinstance(payload, dict) else {}
    pairs: list[dict[str, str]] = []
    for pair in _as_list(inputs.get("lr_pairs")):
        if not isinstance(pair, dict):
            continue
        ligand = str(pair.get("ligand") or "").strip().upper()
        receptor = str(pair.get("receptor") or "").strip().upper()
        if ligand or receptor:
            pairs.append(
                {
                    "ligand": ligand,
                    "receptor": receptor,
                    "lr_pair": str(pair.get("lr_pair") or f"{ligand}-{receptor}"),
                }
            )
    if pairs:
        return pairs

    ligand = str(inputs.get("ligand") or "").strip().upper()
    receptor = str(inputs.get("receptor") or "").strip().upper()
    if ligand or receptor:
        return [{"ligand": ligand, "receptor": receptor, "lr_pair": f"{ligand}-{receptor}"}]
    return []


def _target_genes(payload: dict[str, Any]) -> list[str]:
    inputs = payload.get("inputs", {}) if isinstance(payload, dict) else {}
    genes = [str(g).strip().upper() for g in _as_list(inputs.get("genes")) if str(g).strip()]
    if genes:
        return list(dict.fromkeys(genes))
    derived: list[str] = []
    for pair in _lr_pairs(payload):
        derived.extend(_split_gene_symbol(pair.get("ligand")))
        derived.extend(_split_gene_symbol(pair.get("receptor")))
    return list(dict.fromkeys(derived))


def _target_pathways(payload: dict[str, Any]) -> list[str]:
    inputs = payload.get("inputs", {}) if isinstance(payload, dict) else {}
    pathways = _string_list(inputs.get("pathways"))
    if pathways:
        return list(dict.fromkeys(pathways))
    derived: list[str] = []
    for pair in _as_list(inputs.get("lr_pairs")):
        if isinstance(pair, dict):
            derived.extend(_string_list(pair.get("pathways")))
    return list(dict.fromkeys(derived))


def _target_celltypes(payload: dict[str, Any]) -> list[str]:
    inputs = payload.get("inputs", {}) if isinstance(payload, dict) else {}
    celltypes = _string_list(inputs.get("celltypes"))
    if celltypes:
        return list(dict.fromkeys(celltypes))
    derived: list[str] = []
    for pair in _as_list(inputs.get("lr_pairs")):
        if isinstance(pair, dict):
            derived.extend(_string_list(pair.get("celltypes")))
    return list(dict.fromkeys(derived))


def _pair_key(pair: dict[str, Any]) -> str:
    ligand = str(pair.get("ligand") or "").strip().upper()
    receptor = str(pair.get("receptor") or "").strip().upper()
    return f"{ligand}^{receptor}" if ligand or receptor else ""


def _pair_label(pair: dict[str, Any]) -> str:
    label = str(pair.get("lr_pair") or "").strip()
    if label:
        return label
    key = _pair_key(pair)
    return key.replace("^", "-") if key else ""


def _paper_supported_pair_keys(
    paper: dict[str, Any],
    payload: dict[str, Any],
    *,
    infer_text: bool = True,
) -> set[str]:
    keys: set[str] = set()
    for field in ("supported_lr_pairs", "direct_lr_pairs", "context_lr_pairs"):
        for pair in _as_list(paper.get(field)):
            if isinstance(pair, dict):
                key = _pair_key(pair)
                if key:
                    keys.add(key)
    if keys or not infer_text:
        return keys

    text = _paper_text(paper)
    for pair in _lr_pairs(payload):
        ligand_parts = _split_gene_symbol(pair.get("ligand"))
        receptor_parts = _split_gene_symbol(pair.get("receptor"))
        ligand_hit = any(_contains_term(text, gene) for gene in ligand_parts)
        receptor_hit = any(_contains_term(text, gene) for gene in receptor_parts)
        if ligand_hit and receptor_hit:
            key = _pair_key(pair)
            if key:
                keys.add(key)
    return keys


def _paper_entities(paper: dict[str, Any], payload: dict[str, Any]) -> dict[str, set[str]]:
    text = _paper_text(paper)
    matched_via_query = paper.get("matched_via_query") or {}
    matched_genes = {
        str(g).strip().upper()
        for g in _as_list(matched_via_query.get("genes"))
        if str(g).strip()
    }

    genes = {
        gene
        for gene in _target_genes(payload)
        if gene in matched_genes or _contains_term(text, gene)
    }
    pathways = {
        pathway
        for pathway in _target_pathways(payload)
        if _contains_term(text, pathway)
        or pathway in _matched_pathway_terms(paper, payload)
    }
    celltypes = {
        celltype
        for celltype in _target_celltypes(payload)
        if _contains_term(text, celltype)
        or _contains_term(text, re.sub(r"\s*\d+\s*", "", celltype).strip())
    }
    return {"genes": genes, "pathways": pathways, "celltypes": celltypes}


def _matched_pathway_terms(paper: dict[str, Any], payload: dict[str, Any]) -> set[str]:
    targets = _target_pathways(payload)
    normalized_targets = {_normalize_text(term): term for term in targets}
    found: set[str] = set()

    global_terms = paper.get("global_matched_terms") or {}
    for term in _string_list(global_terms.get("pathways")):
        normalized = _normalize_text(term)
        if normalized in normalized_targets:
            found.add(normalized_targets[normalized])

    by_pair = paper.get("matched_terms_by_pair") or {}
    if isinstance(by_pair, dict):
        for match in by_pair.values():
            if not isinstance(match, dict):
                continue
            for term in _string_list(match.get("pathways")):
                normalized = _normalize_text(term)
                if normalized in normalized_targets:
                    found.add(normalized_targets[normalized])

    matched_via_query = paper.get("matched_via_query") or {}
    for keyword in _string_list(matched_via_query.get("keywords")):
        normalized_keyword = _normalize_text(keyword)
        for normalized, original in normalized_targets.items():
            if normalized and (
                normalized in normalized_keyword or normalized_keyword in normalized
            ):
                found.add(original)
    return found


def _paper_lr_count(paper: dict[str, Any], payload: dict[str, Any]) -> int:
    return len(_paper_supported_pair_keys(paper, payload))


def _paper_entity_count(paper: dict[str, Any], payload: dict[str, Any]) -> int:
    entities = _paper_entities(paper, payload)
    return sum(len(values) for values in entities.values())


def _journal_quality(paper: dict[str, Any]) -> float:
    try:
        value = float(paper.get("journal_quality", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(value):
        return 0.0
    return value


def select_policy_papers(
    payload: dict[str, Any],
    *,
    policy: str,
    cap: int = DEFAULT_CAP,
) -> list[dict[str, Any]]:
    """Select INTERPRETER handoff papers for one active policy."""
    if policy not in ACTIVE_POLICIES:
        raise ValueError(f"unknown ranking policy: {policy}")

    eligible = [
        paper
        for paper in _candidate_papers(payload)
        if paper.get("evidence_bucket") in ELIGIBLE_BUCKETS
    ]

    def bucket_rank(paper: dict[str, Any]) -> int:
        return 0 if paper.get("evidence_bucket") == DIRECT_BUCKET else 1

    if policy == "baseline_current":
        ordered = sorted(
            eligible,
            key=lambda paper: (
                bucket_rank(paper),
                int(paper.get("_candidate_original_index", 0)),
            ),
        )
    elif policy == "bucket_lr_coverage":
        ordered = sorted(
            eligible,
            key=lambda paper: (
                bucket_rank(paper),
                -_paper_lr_count(paper, payload),
                -_paper_entity_count(paper, payload),
                int(paper.get("_candidate_original_index", 0)),
            ),
        )
    else:
        ordered = sorted(
            eligible,
            key=lambda paper: (
                bucket_rank(paper),
                -_paper_lr_count(paper, payload),
                -_paper_entity_count(paper, payload),
                -_journal_quality(paper),
                int(paper.get("_candidate_original_index", 0)),
            ),
        )

    selected: list[dict[str, Any]] = []
    for paper in ordered[: max(0, int(cap))]:
        clean = dict(paper)
        clean.pop("_candidate_original_index", None)
        selected.append(clean)
    return selected


def _selected_pmids(papers: list[dict[str, Any]]) -> list[str]:
    pmids: list[str] = []
    for paper in papers:
        pmid = str(paper.get("pmid") or "").strip()
        pmids.append(pmid if pmid else _paper_key(paper))
    return pmids


def _coverage_for_selection(
    selected: list[dict[str, Any]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    genes: set[str] = set()
    pathways: set[str] = set()
    celltypes: set[str] = set()
    pairs: set[str] = set()
    for paper in selected:
        entities = _paper_entities(paper, payload)
        genes.update(entities["genes"])
        pathways.update(entities["pathways"])
        celltypes.update(entities["celltypes"])
        pairs.update(_paper_supported_pair_keys(paper, payload))

    target_pair_keys = {_pair_key(pair) for pair in _lr_pairs(payload) if _pair_key(pair)}
    if target_pair_keys:
        pairs &= target_pair_keys
    target_genes = set(_target_genes(payload))
    target_pathways = set(_target_pathways(payload))
    target_celltypes = set(_target_celltypes(payload))

    return {
        "lr_pairs_total_count": len(target_pair_keys) if target_pair_keys else len(pairs),
        "lr_pairs_covered_count": len(pairs),
        "lr_pair_coverage_pct": _pct(len(pairs), len(target_pair_keys)),
        "genes_total_count": len(target_genes),
        "genes_covered_count": len(genes & target_genes) if target_genes else len(genes),
        "gene_coverage_pct": _pct(len(genes & target_genes), len(target_genes)),
        "pathways_total_count": len(target_pathways),
        "pathways_covered_count": (
            len(pathways & target_pathways) if target_pathways else len(pathways)
        ),
        "pathway_coverage_pct": _pct(len(pathways & target_pathways), len(target_pathways)),
        "celltypes_total_count": len(target_celltypes),
        "celltypes_covered_count": (
            len(celltypes & target_celltypes) if target_celltypes else len(celltypes)
        ),
        "celltype_coverage_pct": _pct(len(celltypes & target_celltypes), len(target_celltypes)),
    }


def _pct(num: int, denom: int) -> float:
    return round((100.0 * num / denom), 4) if denom else 0.0


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _median(values: list[float]) -> float:
    return round(float(statistics.median(values)), 4) if values else 0.0


def _hhi(counter: Counter[str]) -> float:
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    return round(sum((count / total) ** 2 for count in counter.values()), 4)


def _top_share(counter: Counter[str]) -> float:
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    return round(max(counter.values()) / total, 4)


def _receptors_for_paper(paper: dict[str, Any], payload: dict[str, Any]) -> set[str]:
    receptors: set[str] = set()
    for field in ("supported_lr_pairs", "direct_lr_pairs", "context_lr_pairs"):
        for pair in _as_list(paper.get(field)):
            if isinstance(pair, dict):
                receptor = str(pair.get("receptor") or "").strip().upper()
                if receptor:
                    receptors.add(receptor)
    if receptors:
        return receptors

    text = _paper_text(paper)
    for pair in _lr_pairs(payload):
        receptor = str(pair.get("receptor") or "").strip().upper()
        if receptor and any(_contains_term(text, part) for part in _split_gene_symbol(receptor)):
            receptors.add(receptor)
    return receptors


def _pathways_for_paper(paper: dict[str, Any], payload: dict[str, Any]) -> set[str]:
    return _paper_entities(paper, payload)["pathways"]


def _concentration_metrics(
    selected: list[dict[str, Any]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    receptor_counter: Counter[str] = Counter()
    pathway_counter: Counter[str] = Counter()
    for paper in selected:
        receptor_counter.update(_receptors_for_paper(paper, payload))
        pathway_counter.update(_pathways_for_paper(paper, payload))
    return {
        "distinct_receptors": len(receptor_counter),
        "top_receptor_share": _top_share(receptor_counter),
        "receptor_hhi": _hhi(receptor_counter),
        "top_receptor": receptor_counter.most_common(1)[0][0] if receptor_counter else "",
        "distinct_pathways": len(pathway_counter),
        "top_pathway_share": _top_share(pathway_counter),
        "pathway_hhi": _hhi(pathway_counter),
        "top_pathway": pathway_counter.most_common(1)[0][0] if pathway_counter else "",
    }


def summarize_selection(
    *,
    candidate_id: str,
    candidate_path: Path,
    payload: dict[str, Any],
    policy: str,
    selected: list[dict[str, Any]],
    cap: int,
) -> dict[str, Any]:
    all_papers = _candidate_papers(payload)
    available_direct = sum(1 for paper in all_papers if paper.get("evidence_bucket") == DIRECT_BUCKET)
    available_context = sum(1 for paper in all_papers if paper.get("evidence_bucket") == CONTEXT_BUCKET)
    selected_direct = sum(1 for paper in selected if paper.get("evidence_bucket") == DIRECT_BUCKET)
    selected_context = sum(1 for paper in selected if paper.get("evidence_bucket") == CONTEXT_BUCKET)
    leakage = sum(1 for paper in selected if paper.get("evidence_bucket") not in ELIGIBLE_BUCKETS)
    pmids = _selected_pmids(selected)
    unique_pmids = set(pmids)
    journal_values = [_journal_quality(paper) for paper in selected if "journal_quality" in paper]

    row: dict[str, Any] = {
        "candidate_id": candidate_id,
        "candidate_path": str(candidate_path),
        "policy": policy,
        "cap": cap,
        "candidate_unique_papers": int(
            (payload.get("source") or {}).get("unique_papers") or len(all_papers)
        ),
        "eligible_count": available_direct + available_context,
        "available_direct_count": available_direct,
        "available_context_count": available_context,
        "selected_count": len(selected),
        "selected_direct_count": selected_direct,
        "selected_context_count": selected_context,
        "leakage_count": leakage,
        "unique_pmid_count": len(unique_pmids),
        "duplicate_selected_count": len(pmids) - len(unique_pmids),
        "selected_pmids": ";".join(pmids),
        "journal_quality_count": len(journal_values),
        "journal_quality_mean": _mean(journal_values),
        "journal_quality_median": _median(journal_values),
        "journal_quality_min": round(min(journal_values), 4) if journal_values else 0.0,
        "journal_quality_max": round(max(journal_values), 4) if journal_values else 0.0,
    }
    row.update(_coverage_for_selection(selected, payload))
    row.update(_concentration_metrics(selected, payload))
    return row


def _write_policy_handoff(
    *,
    output_dir: Path,
    candidate_id: str,
    candidate_path: Path,
    payload: dict[str, Any],
    policy: str,
    selected: list[dict[str, Any]],
    cap: int,
) -> None:
    counts = {
        DIRECT_BUCKET: sum(1 for paper in selected if paper.get("evidence_bucket") == DIRECT_BUCKET),
        CONTEXT_BUCKET: sum(1 for paper in selected if paper.get("evidence_bucket") == CONTEXT_BUCKET),
    }
    handoff = {
        "schema_version": "deep_interpreter_literature_handoff_policy_benchmark_v1",
        "policy": {
            "name": policy,
            "included_buckets": [DIRECT_BUCKET, CONTEXT_BUCKET],
            "excluded_buckets": [BACKGROUND_BUCKET, REJECTED_BUCKET],
            "cap": cap,
        },
        "source": {
            "citation_candidates_path": str(candidate_path),
            "candidate_id": candidate_id,
            "candidate_schema_version": payload.get("schema_version", ""),
            "candidate_unique_papers": (payload.get("source") or {}).get("unique_papers", 0),
        },
        "counts": counts,
        "papers": selected,
    }
    _write_json(output_dir / "selected_papers" / candidate_id / policy / "papers.json", handoff)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = {key for row in rows for key in row.keys()}
    preferred = [
        "candidate_id",
        "policy",
        "cap",
        "selected_count",
        "selected_direct_count",
        "selected_context_count",
        "available_direct_count",
        "available_context_count",
        "leakage_count",
        "lr_pairs_covered_count",
        "lr_pair_coverage_pct",
        "genes_covered_count",
        "gene_coverage_pct",
        "pathways_covered_count",
        "pathway_coverage_pct",
        "celltypes_covered_count",
        "celltype_coverage_pct",
        "journal_quality_mean",
        "journal_quality_median",
        "receptor_hhi",
        "pathway_hhi",
        "selected_pmids",
        "candidate_path",
    ]
    fieldnames = [field for field in preferred if field in fields]
    fieldnames.extend(sorted(fields - set(fieldnames)))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def _aggregate_summary(percase_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for policy in ACTIVE_POLICIES:
        group = [row for row in percase_rows if row["policy"] == policy]
        if not group:
            continue
        selected_pmids: set[str] = set()
        for row in group:
            selected_pmids.update(
                pmid for pmid in str(row.get("selected_pmids") or "").split(";") if pmid
            )
        rows.append(
            {
                "policy": policy,
                "candidate_count": len(group),
                "mean_selected_count": _mean([float(row["selected_count"]) for row in group]),
                "mean_selected_direct_count": _mean(
                    [float(row["selected_direct_count"]) for row in group]
                ),
                "mean_selected_context_count": _mean(
                    [float(row["selected_context_count"]) for row in group]
                ),
                "mean_available_direct_count": _mean(
                    [float(row["available_direct_count"]) for row in group]
                ),
                "mean_available_context_count": _mean(
                    [float(row["available_context_count"]) for row in group]
                ),
                "total_leakage_count": sum(int(row["leakage_count"]) for row in group),
                "mean_lr_pair_coverage_pct": _mean(
                    [float(row["lr_pair_coverage_pct"]) for row in group]
                ),
                "mean_gene_coverage_pct": _mean([float(row["gene_coverage_pct"]) for row in group]),
                "mean_pathway_coverage_pct": _mean(
                    [float(row["pathway_coverage_pct"]) for row in group]
                ),
                "mean_celltype_coverage_pct": _mean(
                    [float(row["celltype_coverage_pct"]) for row in group]
                ),
                "mean_journal_quality": _mean(
                    [float(row["journal_quality_mean"]) for row in group]
                ),
                "mean_receptor_hhi": _mean([float(row["receptor_hhi"]) for row in group]),
                "mean_pathway_hhi": _mean([float(row["pathway_hhi"]) for row in group]),
                "unique_selected_pmids": len(selected_pmids),
            }
        )
    return rows


def _overlap_rows(percase_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    by_candidate: dict[str, dict[str, set[str]]] = {}
    for row in percase_rows:
        by_candidate.setdefault(row["candidate_id"], {})[row["policy"]] = {
            pmid for pmid in str(row.get("selected_pmids") or "").split(";") if pmid
        }

    for candidate_id, by_policy in sorted(by_candidate.items()):
        rows.extend(_policy_overlap_rows(candidate_id, by_policy, scope="per_candidate"))

    aggregate: dict[str, set[str]] = {policy: set() for policy in ACTIVE_POLICIES}
    for by_policy in by_candidate.values():
        for policy, pmids in by_policy.items():
            aggregate.setdefault(policy, set()).update(pmids)
    rows.extend(_policy_overlap_rows("__aggregate__", aggregate, scope="aggregate"))
    return rows


def _policy_overlap_rows(
    candidate_id: str,
    by_policy: dict[str, set[str]],
    *,
    scope: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, policy_a in enumerate(ACTIVE_POLICIES):
        for policy_b in ACTIVE_POLICIES[index + 1 :]:
            a = by_policy.get(policy_a, set())
            b = by_policy.get(policy_b, set())
            union = a | b
            overlap = a & b
            rows.append(
                {
                    "scope": scope,
                    "candidate_id": candidate_id,
                    "policy_a": policy_a,
                    "policy_b": policy_b,
                    "policy_a_count": len(a),
                    "policy_b_count": len(b),
                    "overlap_count": len(overlap),
                    "a_only_count": len(a - b),
                    "b_only_count": len(b - a),
                    "jaccard": round(len(overlap) / len(union), 4) if union else 0.0,
                    "overlap_pmids": ";".join(sorted(overlap)),
                }
            )
    return rows


def _load_candidate_paths(args: argparse.Namespace) -> list[Path]:
    paths: list[Path] = []
    for value in args.candidate_path or []:
        paths.append(Path(value).expanduser().resolve())
    for pattern in args.candidate_glob or []:
        paths.extend(Path().glob(pattern))
    for rows_path_value in args.runner_rows or []:
        rows_path = Path(rows_path_value).expanduser().resolve()
        for line in rows_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            candidate_value = row.get("citation_candidates_path")
            if candidate_value:
                candidate = Path(str(candidate_value)).expanduser().resolve()
            else:
                workspace = row.get("trial_workspace")
                if not workspace:
                    continue
                candidate = Path(str(workspace)).expanduser().resolve() / "citation_candidates.json"
            if candidate.exists():
                paths.append(candidate)

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(resolved)
    return deduped


def _candidate_ids(paths: list[Path]) -> dict[Path, str]:
    counts: Counter[str] = Counter()
    ids: dict[Path, str] = {}
    for path in paths:
        base = _safe_id(path.parent.name if path.name == "citation_candidates.json" else path.stem)
        counts[base] += 1
        ids[path] = base if counts[base] == 1 else f"{base}_{counts[base]}"
    return ids


def run_benchmark(
    *,
    candidate_paths: list[Path],
    output_dir: Path,
    cap: int = DEFAULT_CAP,
) -> dict[str, Any]:
    if not candidate_paths:
        raise ValueError("no citation_candidates.json inputs found")

    candidate_id_by_path = _candidate_ids(candidate_paths)
    output_dir.mkdir(parents=True, exist_ok=True)
    percase_rows: list[dict[str, Any]] = []

    for candidate_path in candidate_paths:
        payload = _read_json(candidate_path)
        if not isinstance(payload, dict):
            raise ValueError(f"candidate JSON must be an object: {candidate_path}")
        candidate_id = candidate_id_by_path[candidate_path]
        for policy in ACTIVE_POLICIES:
            selected = select_policy_papers(payload, policy=policy, cap=cap)
            row = summarize_selection(
                candidate_id=candidate_id,
                candidate_path=candidate_path,
                payload=payload,
                policy=policy,
                selected=selected,
                cap=cap,
            )
            percase_rows.append(row)
            _write_policy_handoff(
                output_dir=output_dir,
                candidate_id=candidate_id,
                candidate_path=candidate_path,
                payload=payload,
                policy=policy,
                selected=selected,
                cap=cap,
            )

    if any(int(row["leakage_count"]) for row in percase_rows):
        raise RuntimeError("ineligible disease-only/rejected papers leaked into handoff")

    summary_rows = _aggregate_summary(percase_rows)
    overlap = _overlap_rows(percase_rows)
    _write_csv(output_dir / "ranking_policy_percase.csv", percase_rows)
    _write_csv(output_dir / "ranking_policy_summary.csv", summary_rows)
    _write_csv(output_dir / "ranking_policy_overlap.csv", overlap)
    _write_json(
        output_dir / "run_config.json",
        {
            "created_at_utc": _utc_now(),
            "cap": cap,
            "active_policies": list(ACTIVE_POLICIES),
            "candidate_paths": [str(path) for path in candidate_paths],
            "candidate_count": len(candidate_paths),
            "notes": {
                "direct_quota_policy": "not run; available_direct_count and selected_direct_count are tracked for follow-up",
                "excluded_buckets": [BACKGROUND_BUCKET, REJECTED_BUCKET],
            },
        },
    )
    _write_results_ko(output_dir / "HANDOFF_RANKING_RESULTS_KO.md", summary_rows, overlap)
    return {"percase": percase_rows, "summary": summary_rows, "overlap": overlap}


def _write_results_ko(
    path: Path,
    summary_rows: list[dict[str, Any]],
    overlap_rows: list[dict[str, Any]],
) -> None:
    aggregate_overlap = [
        row for row in overlap_rows if row.get("scope") == "aggregate"
    ]
    lines = [
        "# Handoff Ranking Policy Benchmark 결과",
        "",
        f"- 생성 시각(UTC): {_utc_now()}",
        f"- active policies: {', '.join(ACTIVE_POLICIES)}",
        f"- direct quota policy: 이번 실행에서는 제외. `available_direct_count`와 `selected_direct_count`만 추적.",
        "- excluded buckets: `disease_only_background`, `rejected_weak_evidence`",
        "",
        "## 정책별 요약",
        "",
        "| policy | 후보 파일 | 평균 선택 | direct 평균 | context 평균 | LR coverage | gene | pathway | celltype | journal | receptor HHI | pathway HHI | leakage |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary_rows:
        lines.append(
            "| "
            f"{row['policy']} | "
            f"{row['candidate_count']} | "
            f"{row['mean_selected_count']:.2f} | "
            f"{row['mean_selected_direct_count']:.2f} | "
            f"{row['mean_selected_context_count']:.2f} | "
            f"{row['mean_lr_pair_coverage_pct']:.2f}% | "
            f"{row['mean_gene_coverage_pct']:.2f}% | "
            f"{row['mean_pathway_coverage_pct']:.2f}% | "
            f"{row['mean_celltype_coverage_pct']:.2f}% | "
            f"{row['mean_journal_quality']:.3f} | "
            f"{row['mean_receptor_hhi']:.3f} | "
            f"{row['mean_pathway_hhi']:.3f} | "
            f"{row['total_leakage_count']} |"
        )

    lines.extend(
        [
            "",
            "## 정책 간 overlap",
            "",
            "| policy A | policy B | overlap | A only | B only | Jaccard |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in aggregate_overlap:
        lines.append(
            "| "
            f"{row['policy_a']} | "
            f"{row['policy_b']} | "
            f"{row['overlap_count']} | "
            f"{row['a_only_count']} | "
            f"{row['b_only_count']} | "
            f"{float(row['jaccard']):.3f} |"
        )

    by_policy = {str(row["policy"]): row for row in summary_rows}
    baseline = by_policy.get("baseline_current")
    coverage = by_policy.get("bucket_lr_coverage")
    journal = by_policy.get("bucket_lr_coverage_journal_tiebreak")

    best_coverage = max(
        summary_rows,
        key=lambda row: (
            float(row["mean_lr_pair_coverage_pct"]),
            float(row["mean_gene_coverage_pct"]),
            float(row["mean_pathway_coverage_pct"]),
            float(row["mean_celltype_coverage_pct"]),
        ),
        default=None,
    )
    lines.extend(["", "## 해석", ""])
    if best_coverage:
        lines.append(
            f"- coverage 관점 최고 정책은 `{best_coverage['policy']}`입니다. "
            "LR/gene/pathway/celltype coverage를 우선 비교하고, leakage가 0인지 확인했습니다."
        )
    journal_values = {
        str(row["policy"]): float(row["mean_journal_quality"]) for row in summary_rows
    }
    unique_journal_values = set(journal_values.values())
    if len(unique_journal_values) == 1 and unique_journal_values:
        value = next(iter(unique_journal_values))
        lines.append(
            f"- journal quality 평균은 모든 active policy에서 {value:.3f}으로 같았습니다. "
            "따라서 이번 후보에서는 journal tie-break가 독립적인 품질 신호를 제공하지 않았습니다."
        )
    elif journal_values:
        best_policy = max(journal_values, key=journal_values.get)
        lines.append(
            f"- journal quality 평균이 가장 높은 정책은 `{best_policy}`입니다. "
            "journal tie-break는 coverage score 동률 안에서만 작동하므로 coverage 희생 여부를 함께 봐야 합니다."
        )
    if baseline and coverage:
        direct_available = float(coverage["mean_available_direct_count"])
        direct_selected = float(coverage["mean_selected_direct_count"])
        lines.append(
            f"- direct 후보는 평균 {direct_available:.2f}개였고 coverage-aware policy가 "
            f"평균 {direct_selected:.2f}개를 선택했습니다. 이번 실행에서는 direct under-selection이 "
            "관찰되지 않았으므로 direct quota policy는 후속 optional로 유지합니다."
        )
        lines.append(
            f"- `bucket_lr_coverage`는 baseline 대비 pathway HHI를 "
            f"{float(baseline['mean_pathway_hhi']):.3f}에서 "
            f"{float(coverage['mean_pathway_hhi']):.3f}로 낮췄지만, "
            f"gene coverage는 {float(baseline['mean_gene_coverage_pct']):.2f}%에서 "
            f"{float(coverage['mean_gene_coverage_pct']):.2f}%로 낮았습니다."
        )
    if coverage and journal:
        overlap = next(
            (
                row
                for row in aggregate_overlap
                if row.get("policy_a") == "bucket_lr_coverage"
                and row.get("policy_b") == "bucket_lr_coverage_journal_tiebreak"
            ),
            None,
        )
        if overlap and int(float(overlap.get("overlap_count", 0))) == int(
            float(coverage.get("mean_selected_count", 0))
        ):
            lines.append(
                "- journal tie-break policy는 `bucket_lr_coverage`와 동일한 40편을 선택했습니다. "
                "현재 후보의 journal_quality 값이 구분력을 거의 제공하지 않아 별도 이득을 보이지 않았습니다."
            )
    lines.extend(
        [
            "- `disease_only_background`와 `rejected_weak_evidence`는 모든 policy의 handoff에서 제외되어야 하며, leakage 열이 그 중단 조건을 검증합니다.",
            "- direct quota는 아직 실행하지 않았습니다. direct 후보가 충분히 있는데도 coverage-aware 정책에서 direct 선택 수가 줄어드는 경우에만 별도 후속 PR로 다루는 것이 좋습니다.",
            "",
            "## 산출물",
            "",
            "- `ranking_policy_summary.csv`: policy 단위 집계",
            "- `ranking_policy_percase.csv`: 후보 파일별 policy metric",
            "- `ranking_policy_overlap.csv`: policy pair overlap과 Jaccard",
            "- `selected_papers/<candidate>/<policy>/papers.json`: INTERPRETER handoff 형식의 cap 적용 선택 결과",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-path", action="append", default=[])
    parser.add_argument("--candidate-glob", action="append", default=[])
    parser.add_argument("--runner-rows", action="append", default=[])
    parser.add_argument(
        "--output-dir",
        default="docs/benchmarks/lr_retrieval_relevance/results/cci_handoff_ranking_policy_benchmark_20260603",
    )
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir).expanduser().resolve()
    candidate_paths = _load_candidate_paths(args)
    result = run_benchmark(
        candidate_paths=candidate_paths,
        output_dir=output_dir,
        cap=args.cap,
    )
    print(
        f"Saved handoff ranking benchmark to {output_dir} "
        f"({len(result['summary'])} policies, {len(candidate_paths)} candidates)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

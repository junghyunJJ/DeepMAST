"""Deterministic evidence scaffolding for bounded Ollama hypothesis cards."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, TypedDict

from src.agents.drug_target.tools.evidence_loader import (
    _celltype_contract_labels,
    _load_stage1_filter_results_status,
    _stage1_pair_usage_guidance,
)

CANONICAL_CATEGORIES = (
    "Mechanism of Action",
    "Therapeutic Strategy",
    "Cross-Target Interaction",
    "Novel Pathway",
)
_CARD_IDS = ("mechanism", "therapy", "cross_target", "novel_pathway")
_STAGE1_NAME_RE = re.compile(r"^stage1_([A-Za-z0-9-]+)--([A-Za-z0-9-]+)\.json$")
_FILENAME_RE = re.compile(r"\b[A-Za-z0-9_.-]+\.json\b", re.IGNORECASE)


class OllamaCardSpec(TypedDict):
    """The deterministic inputs and fallback for one bounded Ollama card."""

    id: str
    category: str
    genes: list[str]
    evidence_references: list[str]
    cell_anchor: str
    fallback_hypothesis: str
    known_genes: list[str]


def _read_assessment(evidence_dir: Path) -> dict[str, Any]:
    path = evidence_dir / "assessment_results.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("assessment_results.json must be a JSON object")
    return payload


def _featured_genes(evidence_dir: Path) -> list[str]:
    candidates = _read_assessment(evidence_dir).get("stage3_candidates")
    if not isinstance(candidates, list):
        raise ValueError("assessment_results.json stage3_candidates must be a list")
    genes: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        gene = str(candidate.get("gene") or candidate.get("gene_symbol") or "").strip().upper()
        if gene and gene not in genes:
            genes.append(gene)
    if not genes:
        raise ValueError("assessment_results.json has no FEATURED genes")
    return genes


def _intrinsic_stage1_files(evidence_dir: Path) -> list[str]:
    statuses, _ = _load_stage1_filter_results_status(evidence_dir)
    passed_files = [
        f"stage1_{pair_key}.json"
        for pair_key, passed in statuses.items()
        if passed is True and (evidence_dir / f"stage1_{pair_key}.json").is_file()
    ]
    guidance = _stage1_pair_usage_guidance(evidence_dir, sorted(passed_files))
    return list(guidance["interest_cell_intrinsic_stage1_pair_files"])


def _stage1_contains_gene(filename: str, genes: Iterable[str]) -> bool:
    match = _STAGE1_NAME_RE.match(filename)
    if not match:
        return False
    pair = {match.group(1).upper(), match.group(2).upper()}
    return bool(pair.intersection(genes))


def _known_gene_symbols(evidence_dir: Path) -> set[str]:
    symbols: set[str] = set()
    for path in evidence_dir.glob("ot_*.json"):
        symbols.add(path.stem.removeprefix("ot_").upper())
    for path in evidence_dir.glob("stage3_*.json"):
        symbols.add(path.stem.removeprefix("stage3_").upper())
    for path in evidence_dir.glob("stage1_*.json"):
        match = _STAGE1_NAME_RE.match(path.name)
        if match:
            symbols.update((match.group(1).upper(), match.group(2).upper()))
    return symbols


def is_ollama_card_text_safe(
    text: str,
    *,
    allowed_genes: Iterable[str],
    known_genes: Iterable[str],
) -> bool:
    """Return whether bounded model prose can enter a deterministic record."""
    if not text or len(text) >= 500 or "/" in text or "\\" in text:
        return False
    if _FILENAME_RE.search(text):
        return False
    allowed = tuple(gene.upper() for gene in allowed_genes)
    if not allowed:
        return False
    for gene in known_genes:
        if gene.upper() not in allowed and re.search(
            rf"(?<![A-Za-z0-9]){re.escape(gene)}(?![A-Za-z0-9])",
            text,
            re.IGNORECASE,
        ):
            return False
    return bool(
        re.fullmatch(
            rf"{re.escape(' and '.join(allowed))} are evidence-supported candidates "
            r"for validation in [A-Za-z][A-Za-z -]* context\.",
            text.strip(),
            re.IGNORECASE,
        )
    )


def _fallback_hypothesis(genes: list[str], cell_anchor: str) -> str:
    return (
        f"{' and '.join(genes)} are evidence-supported candidates for validation "
        f"in {cell_anchor} context."
    )


def build_ollama_card_specs(data_dir: str | Path) -> list[OllamaCardSpec]:
    """Build four deterministic, evidence-grounded input cards for Ollama."""
    evidence_dir = Path(data_dir).expanduser().resolve() / "evidence"
    genes = _featured_genes(evidence_dir)
    labels = _celltype_contract_labels(evidence_dir)
    cell_anchor = labels["required_cell_context_anchor"]
    if not cell_anchor:
        raise ValueError("celltype_resolution.json has no resolved cell-type anchor")
    intrinsic_stage1 = _intrinsic_stage1_files(evidence_dir)
    known_genes = sorted(_known_gene_symbols(evidence_dir))

    grouped = [[] for _ in CANONICAL_CATEGORIES]
    for index, gene in enumerate(genes):
        grouped[index % len(grouped)].append(gene)

    specs: list[OllamaCardSpec] = []
    for card_id, category, card_genes in zip(_CARD_IDS, CANONICAL_CATEGORIES, grouped):
        references = [
            filename
            for gene in card_genes
            for filename in (f"ot_{gene}.json", f"stage3_{gene}.json")
            if (evidence_dir / filename).is_file()
        ]
        references.extend(
            filename
            for filename in intrinsic_stage1
            if _stage1_contains_gene(filename, card_genes)
        )
        references = list(dict.fromkeys(references))
        specs.append(
            {
                "id": card_id,
                "category": category,
                "genes": card_genes,
                "evidence_references": references,
                "cell_anchor": cell_anchor,
                "fallback_hypothesis": _fallback_hypothesis(card_genes, cell_anchor),
                "known_genes": known_genes,
            }
        )
    return specs


def build_ollama_hypothesis_report(
    data_dir: str | Path,
    card_texts: Mapping[str, str],
) -> dict[str, object]:
    """Assemble a canonical report without admitting model-selected evidence."""
    base = Path(data_dir).expanduser().resolve()
    evidence_dir = base / "evidence"
    specs = build_ollama_card_specs(base)
    known_genes = _known_gene_symbols(evidence_dir)
    hypotheses: list[dict[str, object]] = []

    for rank, spec in enumerate(specs, start=1):
        genes = spec["genes"]
        card_id = spec["id"]
        candidate = card_texts.get(card_id, "")
        core_claim = (
            candidate
            if isinstance(candidate, str)
            and is_ollama_card_text_safe(
                candidate,
                allowed_genes=genes,
                known_genes=known_genes,
            )
            else spec["fallback_hypothesis"]
        )
        cell_anchor = spec["cell_anchor"]
        hypotheses.append(
            {
                "rank": rank,
                "title": (
                    f"{' and '.join(genes)} evidence-supported validation candidates "
                    f"in {cell_anchor} context"
                ),
                "category": spec["category"],
                "gap_type": "none",
                "core_claim": core_claim,
                "evidence_references": spec["evidence_references"],
                "evidence_reference_details": [
                    {"filename": filename, "usage": "primary"}
                    for filename in spec["evidence_references"]
                ],
                "contrast_references": [],
                "biological_entities": {
                    "genes": genes,
                    "pathways": [],
                    "cell_types": [cell_anchor],
                    "drugs": [],
                },
                "falsifiable_prediction": (
                    "Test whether separate perturbation of the listed candidates "
                    f"changes prespecified {cell_anchor} readouts."
                ),
                "validation_approach": (
                    "Evaluate separate perturbation readouts in "
                    f"{cell_anchor} context."
                ),
                "scores": {
                    "evidence_coverage": 0.5,
                    "specificity": 0.5,
                    "novelty": 0.5,
                    "actionability": 0.5,
                    "composite": 0.5,
                },
            }
        )
    return {"schema_version": "hypothesis_report.v2", "hypotheses": hypotheses, "gap_analysis": {"orphan_files": []}}

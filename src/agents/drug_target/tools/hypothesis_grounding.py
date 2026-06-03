"""Deterministic grounding checks for hypothesis_report.json."""

from __future__ import annotations

import json
import re
from itertools import combinations
from pathlib import Path
from typing import Any

_STAGE1_REF_RE = re.compile(r"^stage1_([A-Za-z0-9-]+)--([A-Za-z0-9-]+)\.json$")
_STAGE_GENE_REF_RE = re.compile(r"^stage[23]_([A-Za-z0-9-]+)\.json$")
_JSON_TOKEN_RE = re.compile(r"([A-Za-z0-9_.\-]+\.json)")
_PAIR_CUE_RE = re.compile(
    r"\b("
    r"axis|axes|interact(?:ion|s|ing)?|pair|pairs|ppi|string|census|"
    r"co-?express(?:ion|ed)?|ligand[-\s]?receptor|l-r|binding|binds|"
    r"coupl(?:e|es|ing)|complex|triad|hub"
    r")\b",
    re.IGNORECASE,
)
_GENE_SYMBOL_RE = r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)?"
_EXPLICIT_PAIR_RE = re.compile(
    rf"(?<![A-Za-z0-9])({_GENE_SYMBOL_RE})\s*(?:--|/|[–—])\s*"
    rf"({_GENE_SYMBOL_RE})(?![A-Za-z0-9])"
)
_EXPLICIT_SINGLE_HYPHEN_PAIR_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{1,11})-([A-Z][A-Z0-9]{1,11})"
    r"(?![A-Za-z0-9])"
)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _normal_gene(value: Any) -> str:
    return str(value or "").strip().upper()


def _normal_celltype(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return " ".join(text.split())


def _stage1_token(ref: Any) -> str | None:
    if not isinstance(ref, str):
        return None
    match = _JSON_TOKEN_RE.search(ref)
    if not match:
        return None
    token = match.group(1)
    return token if _STAGE1_REF_RE.match(token) else None


def _stage1_pair_from_filename(filename: str) -> tuple[str, str] | None:
    match = _STAGE1_REF_RE.match(filename)
    if not match:
        return None
    return _normal_gene(match.group(1)), _normal_gene(match.group(2))


def _stage1_filename(a: str, b: str) -> str:
    return f"stage1_{a}--{b}.json"


def _cited_stage1_refs(hypothesis: dict[str, Any]) -> list[str]:
    refs = hypothesis.get("evidence_references")
    if not isinstance(refs, list):
        return []
    tokens: list[str] = []
    for ref in refs:
        token = _stage1_token(ref)
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _cited_stage1_pairs(hypothesis: dict[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for token in _cited_stage1_refs(hypothesis):
        pair = _stage1_pair_from_filename(token)
        if not pair:
            continue
        pairs.add(pair)
        pairs.add((pair[1], pair[0]))
    return pairs


def _entity_genes(hypothesis: dict[str, Any]) -> list[str]:
    entities = hypothesis.get("biological_entities")
    if not isinstance(entities, dict):
        return []
    raw = entities.get("genes")
    if not isinstance(raw, list):
        return []
    genes: list[str] = []
    for value in raw:
        gene = _normal_gene(value)
        if gene and gene not in genes:
            genes.append(gene)
    return genes


def _known_gene_symbols(hypothesis: dict[str, Any]) -> set[str]:
    genes = set(_entity_genes(hypothesis))
    refs = hypothesis.get("evidence_references")
    if not isinstance(refs, list):
        return genes
    for ref in refs:
        token = _stage1_token(ref)
        if token:
            pair = _stage1_pair_from_filename(token)
            if pair:
                genes.update(pair)
            continue
        if not isinstance(ref, str):
            continue
        match = _JSON_TOKEN_RE.search(ref)
        if not match:
            continue
        stage_gene = _STAGE_GENE_REF_RE.match(match.group(1))
        if stage_gene:
            genes.add(_normal_gene(stage_gene.group(1)))
    return genes


def _pair_text(hypothesis: dict[str, Any]) -> str:
    fields = (
        hypothesis.get("title", ""),
        hypothesis.get("core_claim", ""),
        hypothesis.get("falsifiable_prediction", ""),
    )
    return "\n".join(str(field) for field in fields if field)


def _direct_pair_pattern(a: str, b: str) -> re.Pattern[str]:
    sep = r"(?:\s*(?:--|[-/–—])\s*|\s+)"
    return re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(a)}{sep}{re.escape(b)}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def _gene_occurs(gene: str, text: str) -> bool:
    return re.search(
        rf"(?<![A-Za-z0-9]){re.escape(gene)}(?![A-Za-z0-9])",
        text,
        re.IGNORECASE,
    ) is not None


def _explicit_direct_pairs(text: str, known_genes: set[str]) -> set[tuple[str, str]]:
    claimed: set[tuple[str, str]] = set()
    for match in _EXPLICIT_PAIR_RE.finditer(text):
        claimed.add((_normal_gene(match.group(1)), _normal_gene(match.group(2))))
    for match in _EXPLICIT_SINGLE_HYPHEN_PAIR_RE.finditer(text):
        if _normal_gene(match.group(0)) in known_genes:
            continue
        claimed.add((_normal_gene(match.group(1)), _normal_gene(match.group(2))))
    return claimed


def _claimed_direct_pairs(hypothesis: dict[str, Any]) -> set[tuple[str, str]]:
    genes = _entity_genes(hypothesis)
    text = _pair_text(hypothesis)
    if not text:
        return set()

    claimed = _explicit_direct_pairs(text, _known_gene_symbols(hypothesis))
    if len(genes) < 2:
        return claimed

    clauses = [clause.strip() for clause in re.split(r"[\n.;:]+", text) if clause.strip()]
    for a, b in combinations(genes, 2):
        direct = _direct_pair_pattern(a, b).search(text)
        reverse = _direct_pair_pattern(b, a).search(text)
        if direct:
            claimed.add((a, b))
            continue
        if reverse:
            claimed.add((b, a))
            continue
        if any(
            _gene_occurs(a, clause)
            and _gene_occurs(b, clause)
            and _PAIR_CUE_RE.search(clause)
            for clause in clauses
        ):
            claimed.add((a, b))
    return claimed


def _celltype_resolution_tokens(celltype_resolution: Any) -> set[str]:
    if not isinstance(celltype_resolution, dict):
        return set()

    tokens: set[str] = set()
    interest_tokens: set[str] = set()

    interest = celltype_resolution.get("interest_celltypes")
    if isinstance(interest, list):
        for value in interest:
            token = _normal_celltype(value)
            if token:
                tokens.add(token)
                interest_tokens.add(token)

    matches = celltype_resolution.get("matches")
    if isinstance(matches, list):
        for match in matches:
            if not isinstance(match, dict):
                continue
            token = _normal_celltype(match.get("input_celltype"))
            if token:
                tokens.add(token)
                interest_tokens.add(token)

    resolved = _normal_celltype(celltype_resolution.get("primary_resolved_celltype"))
    if resolved:
        tokens.add(resolved)

    if "at2" in interest_tokens:
        tokens.add("pulmonary alveolar type 2 cell")

    return tokens


def _hypothesis_celltype_tokens(hypothesis: dict[str, Any]) -> set[str]:
    entities = hypothesis.get("biological_entities")
    if not isinstance(entities, dict):
        return set()
    cell_types = entities.get("cell_types")
    if not isinstance(cell_types, list):
        return set()
    return {
        token
        for token in (_normal_celltype(value) for value in cell_types)
        if token
    }


def _contains_normalized_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def _negative_stage1_diffs(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    census_validation = payload.get("census_validation")
    if not isinstance(census_validation, dict):
        return []
    target_vs_rest = census_validation.get("target_vs_rest")
    if not isinstance(target_vs_rest, dict):
        return []

    values: list[tuple[str, float]] = []
    for key in ("gene_a", "gene_b", "coexpression"):
        item = target_vs_rest.get(key)
        if not isinstance(item, dict):
            continue
        diff = item.get("diff")
        if isinstance(diff, (int, float)):
            values.append((key, float(diff)))

    if values and all(diff < 0 for _, diff in values):
        return [key for key, _ in values]
    return []


def validate_hypothesis_grounding(parsed: dict[str, Any], evidence_dir: Path) -> list[str]:
    """Return deterministic grounding violations for a canonical hypothesis report."""
    hypotheses = parsed.get("hypotheses") if isinstance(parsed, dict) else None
    if not isinstance(hypotheses, list):
        return []

    errors: list[str] = []
    real = {path.name for path in evidence_dir.iterdir()} if evidence_dir.exists() else set()
    celltype_tokens = _celltype_resolution_tokens(
        _load_json(evidence_dir / "celltype_resolution.json")
    )
    for idx, hypothesis in enumerate(hypotheses):
        if not isinstance(hypothesis, dict):
            continue
        cited_stage1_refs = _cited_stage1_refs(hypothesis)
        cited_pairs = _cited_stage1_pairs(hypothesis)
        for a, b in sorted(_claimed_direct_pairs(hypothesis)):
            if (a, b) in cited_pairs:
                continue
            direct_name = _stage1_filename(a, b)
            reverse_name = _stage1_filename(b, a)
            available = [name for name in (direct_name, reverse_name) if name in real]
            available_text = ", ".join(available) if available else "no matching Stage 1 pair file exists"
            errors.append(
                f"hypotheses[{idx}] claims direct pair axis '{a}--{b}' "
                f"without citing a matching passed Stage 1 pair file. Expected "
                f"{direct_name} or {reverse_name}; available: {available_text}."
            )

        used_celltype_tokens = sorted(
            _hypothesis_celltype_tokens(hypothesis) & celltype_tokens
        )
        if not used_celltype_tokens or not cited_stage1_refs:
            continue

        validation_text = _normal_celltype(hypothesis.get("validation_approach"))
        if not any(
            _contains_normalized_phrase(validation_text, token)
            for token in celltype_tokens
        ):
            listed = ", ".join(used_celltype_tokens)
            errors.append(
                f"hypotheses[{idx}] lists interest/resolved cell type ({listed}) "
                "but validation_approach does not mention the original interest label "
                "or resolved Census cell type."
            )

        for ref in cited_stage1_refs:
            negative_keys = _negative_stage1_diffs(_load_json(evidence_dir / ref))
            if not negative_keys:
                continue
            keys_text = ", ".join(negative_keys)
            errors.append(
                f"hypotheses[{idx}] uses target-cell-depleted Stage 1 Census evidence "
                f"as interest-cell support: {ref} has negative target-vs-rest diff "
                f"values for [{keys_text}]."
            )
    return errors

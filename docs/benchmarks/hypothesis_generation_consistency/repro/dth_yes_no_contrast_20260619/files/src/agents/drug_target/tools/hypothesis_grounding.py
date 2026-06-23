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
_PAIR_CUE_NEGATION_PREFIX_RE = re.compile(
    r"\b("
    r"no|without|not|does\s+not|do\s+not|did\s+not|is\s+not|are\s+not|"
    r"was\s+not|were\s+not|isn't|aren't|cannot|can't|should\s+not|must\s+not"
    r")\b[\w\s/-]{0,80}$",
    re.IGNORECASE,
)
_NOT_ONLY_RE = re.compile(r"\bnot\s+only\b", re.IGNORECASE)
_NON_PAIR_GENE_LEVEL_CONTEXT_RE = re.compile(
    r"\b("
    r"independent|separate(?:ly)?|individual|gene[-\s]?level|"
    r"actionability[-\s]?only|not\s+a\s+pair|do\s+not\s+claim"
    r")\b",
    re.IGNORECASE,
)
_NON_PAIR_GENE_ALTERNATIVE_RE = re.compile(
    rf"\b(?:whether|either)\s+{_GENE_SYMBOL_RE}\s+or\s+{_GENE_SYMBOL_RE}\s+"
    r"(?:perturbation|perturbations|expression|inhibition|knockdown|blockade|targeting)\b",
    re.IGNORECASE,
)
_TARGET_CELL_INTRINSIC_RE = re.compile(
    r"\b("
    r"at2[-\s]?intrinsic|target[-\s]?cell[-\s]?intrinsic|same[-\s]?cell|"
    r"cell[-\s]?autonomous|co[-\s]?express(?:ion|ed|es|ing)?"
    r")\b",
    re.IGNORECASE,
)
_CROSS_CELL_FRAMING_RE = re.compile(
    r"\b("
    r"cross[-\s]?cell|non[-\s]?at2|non[-\s]?target[-\s]?cell|"
    r"spatial niche|paracrine|between cells"
    r")\b",
    re.IGNORECASE,
)
_INTRINSIC_NEGATION_RE = re.compile(
    r"\b("
    r"not|no|without|does not|do not|did not|should not|must not|cannot|"
    r"can not|can't|is not|isn't|are not|aren't|non"
    r")\b(?:\s+\w+){0,6}$",
    re.IGNORECASE,
)
_POST_INTRINSIC_NONCLAIM_RE = re.compile(
    r"^[\s-]*(?:(?:is|are|was|were)\s+)?(?:depleted|negative|low|reduced)\b",
    re.IGNORECASE,
)
_UNSUPPORTED_OVERCLAIM_RE = re.compile(
    r"\b("
    r"blockade\s+for\s+reducing|"
    r"dysregulation\s+via|"
    r"barrier\s+dysfunction|"
    r"complex\s+assembly|"
    r"activation\s+and\s+matrix\s+deposition|"
    r"restores\s+fibrosis\s+resolution|"
    r"blocks\s+fibrosis|"
    r"drives\s+(?:disease|fibrosis|fibrotic\s+\w+)"
    r")\b",
    re.IGNORECASE,
)
_FORBIDDEN_CONSERVATIVE_LANGUAGE_RE = re.compile(
    r"\b("
    r"therapeutic\s+intervention\s+candidate|"
    r"therapeutic\s+strategy|"
    r"synergistic\s+effects?|"
    r"(?:cd47\s+)?blockade\s+alters\s+fibrosis\s+resolution|"
    r"alters\s+fibrosis\s+resolution"
    r")\b",
    re.IGNORECASE,
)
_SPATIAL_NICHE_LABEL_RE = re.compile(r"\bspatial[-\s]+niche\b", re.IGNORECASE)
_UNSUPPORTED_STAGE1_CONTEXT_RE = re.compile(
    r"\b(?:appears\s+in\s+)?stage\s*1\s+pair\s+context\b",
    re.IGNORECASE,
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


def _stage1_pair_key(a: str, b: str) -> str:
    return f"{_normal_gene(a)}--{_normal_gene(b)}"


def _load_stage1_filter_status(evidence_dir: Path) -> dict[str, bool]:
    try:
        from src.agents.drug_target.tools.evidence_loader import (
            _load_stage1_filter_results_status,
        )

        results, _ = _load_stage1_filter_results_status(evidence_dir)
    except Exception:
        return {}
    return results


def _matching_stage1_details(
    a: str,
    b: str,
    *,
    real_files: set[str],
    filter_status: dict[str, bool],
) -> tuple[str, str, str | None, bool | None, list[str]]:
    direct_name = _stage1_filename(a, b)
    reverse_name = _stage1_filename(b, a)
    details: list[str] = []
    unknown_details: list[str] = []
    canonical_existing: str | None = None
    available_passed: bool | None = None
    for name, pair_key in (
        (direct_name, _stage1_pair_key(a, b)),
        (reverse_name, _stage1_pair_key(b, a)),
    ):
        if name not in real_files:
            continue
        passed = filter_status.get(pair_key)
        if passed is True:
            status = "passed=true"
            canonical_existing = canonical_existing or name
            available_passed = True
        elif passed is False:
            canonical_existing = canonical_existing or name
            available_passed = False if available_passed is None else available_passed
            continue
        else:
            canonical_existing = canonical_existing or name
            available_passed = available_passed if available_passed is not None else None
            unknown_details.append(f"{name} (passed=unknown)")
            continue
        details.append(f"{name} ({status})")
    return direct_name, reverse_name, canonical_existing, available_passed, details or unknown_details


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


def _policy_text(hypothesis: dict[str, Any]) -> str:
    fields = (
        hypothesis.get("title", ""),
        hypothesis.get("core_claim", ""),
        hypothesis.get("falsifiable_prediction", ""),
        hypothesis.get("validation_approach", ""),
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


def _has_unnegated_pair_cue(clause: str) -> bool:
    if _NON_PAIR_GENE_LEVEL_CONTEXT_RE.search(
        clause
    ) or _NON_PAIR_GENE_ALTERNATIVE_RE.search(clause):
        return False
    for match in _PAIR_CUE_RE.finditer(clause):
        prefix = clause[: match.start()]
        if _PAIR_CUE_NEGATION_PREFIX_RE.search(prefix) and not _NOT_ONLY_RE.search(prefix):
            continue
        return True
    return False


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
            and _has_unnegated_pair_cue(clause)
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


def _stage1_celltype_tokens(evidence_dir: Path) -> set[str]:
    if not evidence_dir.exists():
        return set()

    tokens: set[str] = set()
    for path in evidence_dir.glob("stage1_*.json"):
        payload = _load_json(path)
        census_validation = (
            payload.get("census_validation") if isinstance(payload, dict) else None
        )
        if not isinstance(census_validation, dict):
            continue
        for key in ("requested_cell_type", "resolved_cell_type", "target_cell_type"):
            token = _normal_celltype(census_validation.get(key))
            if token:
                tokens.add(token)
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


def _metric_direction(metric: Any) -> str:
    if not isinstance(metric, dict):
        return "not_determined"
    risk_ratio = metric.get("risk_ratio")
    if isinstance(risk_ratio, (int, float)):
        if risk_ratio > 1:
            return "enriched"
        if risk_ratio < 1:
            return "depleted"
    diff = metric.get("diff")
    if isinstance(diff, (int, float)):
        if diff > 0:
            return "enriched"
        if diff < 0:
            return "depleted"
    return "not_determined"


def _stage1_target_vs_rest(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    census_validation = payload.get("census_validation")
    if not isinstance(census_validation, dict):
        return {}
    target_vs_rest = census_validation.get("target_vs_rest")
    return target_vs_rest if isinstance(target_vs_rest, dict) else {}


def _stage1_gene_names(payload: Any, filename: str) -> dict[str, str]:
    pair = _stage1_pair_from_filename(filename) or ("", "")
    ligand = _normal_gene(
        payload.get("ligand") if isinstance(payload, dict) else ""
    ) or pair[0]
    receptor = _normal_gene(
        payload.get("receptor") if isinstance(payload, dict) else ""
    ) or pair[1]
    return {"gene_a": ligand, "gene_b": receptor}


def _claims_target_cell_intrinsic_pair(hypothesis: dict[str, Any]) -> bool:
    text = _pair_text(hypothesis)
    if not text:
        return False
    for match in _TARGET_CELL_INTRINSIC_RE.finditer(text):
        prefix = text[max(0, match.start() - 80) : match.start()]
        suffix = text[match.end() : match.end() + 40]
        if _INTRINSIC_NEGATION_RE.search(_normal_celltype(prefix)):
            continue
        if _POST_INTRINSIC_NONCLAIM_RE.search(suffix):
            continue
        return True
    return False


def _unsupported_overclaim_phrases(hypothesis: dict[str, Any]) -> list[str]:
    text = _pair_text(hypothesis)
    if not text:
        return []

    phrases: list[str] = []
    for clause in re.split(r"[\n.;]+", text):
        normalized = _normal_celltype(clause)
        if not normalized or "not yet established" in normalized:
            continue
        for match in _UNSUPPORTED_OVERCLAIM_RE.finditer(clause):
            phrase = " ".join(match.group(1).lower().split())
            if phrase not in phrases:
                phrases.append(phrase)
    return phrases


def _forbidden_conservative_language_phrases(
    hypothesis: dict[str, Any],
) -> list[str]:
    text = _policy_text(hypothesis)
    if not text:
        return []

    phrases: list[str] = []
    for match in _FORBIDDEN_CONSERVATIVE_LANGUAGE_RE.finditer(text):
        phrase = " ".join(match.group(1).lower().split())
        if phrase not in phrases:
            phrases.append(phrase)
    return phrases


def _unsupported_gene_level_spatial_language(
    hypothesis: dict[str, Any],
    *,
    cited_stage1_refs: list[str],
) -> list[str]:
    if cited_stage1_refs:
        return []

    text = _policy_text(hypothesis)
    if not text:
        return []

    violations: list[str] = []
    if _SPATIAL_NICHE_LABEL_RE.search(text):
        violations.append("spatial-niche label without Stage 1/spatial grounding")
    if _UNSUPPORTED_STAGE1_CONTEXT_RE.search(text):
        violations.append("Stage 1 pair context without cited Stage 1 reference")
    return violations


def _celltype_term_variants(tokens: set[str]) -> set[str]:
    terms = set(tokens)
    for token in list(tokens):
        if token.endswith(" cell"):
            terms.add(f"{token}s")
        if token == "at2":
            terms.update({"at2 cell", "at2 cells", "at2 epithelial cell", "at2 epithelial cells"})
        if token == "pulmonary alveolar type 2 cell":
            terms.add("pulmonary alveolar type 2 cells")
            terms.update({
                "at2",
                "at2 cell",
                "at2 cells",
                "at2 epithelial cell",
                "at2 epithelial cells",
                "alveolar epithelial cell",
                "alveolar epithelial cells",
                "alveolar type 2 cell",
                "alveolar type 2 cells",
                "pulmonary epithelial cell",
                "pulmonary epithelial cells",
            })
    return {term for term in terms if term}


def _claims_depleted_gene_on_target_cell(
    hypothesis: dict[str, Any],
    *,
    gene: str,
    celltype_tokens: set[str],
) -> bool:
    text = _normal_celltype(_pair_text(hypothesis))
    if not text or gene.lower() not in text:
        return False
    gene_pattern = re.escape(gene.lower())
    for term in _celltype_term_variants(celltype_tokens):
        term_pattern = re.escape(term)
        gene_to_cell = re.compile(
            rf"\b{gene_pattern}\b(?:\s+\w+){{0,8}}\s+"
            rf"(?:on|in|within|expressed|expression|localized|localised|present)"
            rf"(?:\s+\w+){{0,6}}\s+\b{term_pattern}\b"
        )
        cell_to_gene = re.compile(
            rf"\b{term_pattern}\b(?:\s+\w+){{0,8}}\s+"
            rf"(?:express(?:ed|es|ion)?|has|shows|contains|presents)"
            rf"(?:\s+\w+){{0,6}}\s+\b{gene_pattern}\b"
        )
        if gene_to_cell.search(text) or cell_to_gene.search(text):
            return True
    return False


def _mentions_interest_celltype(text: Any, celltype_tokens: set[str]) -> bool:
    normalized = _normal_celltype(text)
    if not normalized:
        return False
    return any(
        _contains_normalized_phrase(normalized, term)
        for term in _celltype_term_variants(celltype_tokens)
    )


def _declares_interest_celltype(
    hypothesis: dict[str, Any],
    celltype_tokens: set[str],
) -> bool:
    entities = hypothesis.get("biological_entities")
    if not isinstance(entities, dict):
        return False
    cell_types = entities.get("cell_types")
    if not isinstance(cell_types, list):
        return False
    return _mentions_interest_celltype(" ".join(str(value) for value in cell_types), celltype_tokens)


def _is_target_cell_intrinsic_stage1(payload: Any) -> bool:
    target_vs_rest = _stage1_target_vs_rest(payload)
    if _metric_direction(target_vs_rest.get("coexpression", {})) != "enriched":
        return False
    return all(
        _metric_direction(target_vs_rest.get(metric_key, {})) != "depleted"
        for metric_key in ("gene_a", "gene_b")
    )


def validate_hypothesis_grounding(parsed: dict[str, Any], evidence_dir: Path) -> list[str]:
    """Return deterministic grounding violations for a canonical hypothesis report."""
    hypotheses = parsed.get("hypotheses") if isinstance(parsed, dict) else None
    if not isinstance(hypotheses, list):
        return []

    errors: list[str] = []
    real = {path.name for path in evidence_dir.iterdir()} if evidence_dir.exists() else set()
    filter_status = _load_stage1_filter_status(evidence_dir)
    celltype_tokens = _celltype_resolution_tokens(
        _load_json(evidence_dir / "celltype_resolution.json")
    ) | _stage1_celltype_tokens(evidence_dir)
    for idx, hypothesis in enumerate(hypotheses):
        if not isinstance(hypothesis, dict):
            continue
        cited_stage1_refs = _cited_stage1_refs(hypothesis)
        cited_pairs = _cited_stage1_pairs(hypothesis)
        overclaim_phrases = _unsupported_overclaim_phrases(hypothesis)
        if overclaim_phrases:
            phrases_text = ", ".join(overclaim_phrases)
            errors.append(
                f"hypotheses[{idx}] uses unsupported causal or therapeutic-success "
                f"wording [{phrases_text}]. Reframe as a conservative follow-up "
                "`test whether` candidate unless the cited evidence directly "
                "establishes that mechanism."
            )
        forbidden_phrases = _forbidden_conservative_language_phrases(hypothesis)
        if forbidden_phrases:
            phrases_text = ", ".join(forbidden_phrases)
            errors.append(
                f"hypotheses[{idx}] uses non-conservative follow-up wording "
                f"[{phrases_text}]. Reframe as evidence-grounded perturbation, "
                "actionability, additive/non-additive, or readout-testing language."
            )
        gene_level_spatial_violations = _unsupported_gene_level_spatial_language(
            hypothesis,
            cited_stage1_refs=cited_stage1_refs,
        )
        if gene_level_spatial_violations:
            violations_text = ", ".join(gene_level_spatial_violations)
            errors.append(
                f"hypotheses[{idx}] labels gene-level evidence as spatial or "
                f"Stage 1 grounded without citing Stage 1/spatial evidence "
                f"[{violations_text}]. Use gene-level/actionability-only framing."
            )
        for a, b in sorted(_claimed_direct_pairs(hypothesis)):
            if (a, b) in cited_pairs:
                continue
            (
                direct_name,
                reverse_name,
                canonical_existing,
                available_passed,
                available,
            ) = _matching_stage1_details(
                a,
                b,
                real_files=real,
                filter_status=filter_status,
            )
            available_text = (
                ", ".join(available)
                if available
                else "no matching Stage 1 pair file exists"
            )
            canonical_text = canonical_existing or "none"
            passed_text = (
                "unknown" if available_passed is None else str(available_passed).lower()
            )
            errors.append(
                f"hypotheses[{idx}] claims direct pair axis '{a}--{b}' "
                f"without citing a matching passed Stage 1 pair file. Expected "
                f"direct={direct_name} or reverse={reverse_name}; "
                f"canonical_existing={canonical_text}; "
                f"available_passed={passed_text}; "
                f"available: {available_text}."
            )

        used_celltype_tokens = sorted(
            _hypothesis_celltype_tokens(hypothesis) & celltype_tokens
        )
        if not cited_stage1_refs:
            continue

        if used_celltype_tokens:
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

        claims_interest_cell_context = (
            _declares_interest_celltype(hypothesis, celltype_tokens)
            or _mentions_interest_celltype(_pair_text(hypothesis), celltype_tokens)
            or _mentions_interest_celltype(
                hypothesis.get("validation_approach"),
                celltype_tokens,
            )
            or _claims_target_cell_intrinsic_pair(hypothesis)
        )

        for ref in cited_stage1_refs:
            stage1_payload = _load_json(evidence_dir / ref)
            negative_keys = _negative_stage1_diffs(stage1_payload)
            target_vs_rest = _stage1_target_vs_rest(stage1_payload)
            if negative_keys and claims_interest_cell_context:
                keys_text = ", ".join(negative_keys)
                errors.append(
                    f"hypotheses[{idx}] uses target-cell-depleted Stage 1 Census evidence "
                    f"as interest-cell support: {ref} has negative target-vs-rest diff "
                    f"values for [{keys_text}]."
                )

            if _is_target_cell_intrinsic_stage1(stage1_payload):
                if not _declares_interest_celltype(hypothesis, celltype_tokens):
                    errors.append(
                        f"hypotheses[{idx}] cites target-cell-intrinsic Stage 1 "
                        f"evidence ({ref}) but biological_entities.cell_types does "
                        "not include the original interest label or resolved "
                        "Census cell type."
                    )
                if not _mentions_interest_celltype(
                    hypothesis.get("validation_approach"),
                    celltype_tokens,
                ):
                    errors.append(
                        f"hypotheses[{idx}] cites target-cell-intrinsic Stage 1 "
                        f"evidence ({ref}) but validation_approach does not test "
                        "the original interest label or resolved Census cell type."
                    )

            coexpression = target_vs_rest.get("coexpression", {})
            if (
                _metric_direction(coexpression) == "depleted"
                and _claims_target_cell_intrinsic_pair(hypothesis)
            ):
                errors.append(
                    f"hypotheses[{idx}] uses coexpression-depleted Stage 1 Census "
                    f"evidence as an interest-cell intrinsic same-cell claim: {ref}."
                )

            gene_names = _stage1_gene_names(stage1_payload, ref)
            for metric_key in ("gene_a", "gene_b"):
                gene = gene_names.get(metric_key, "")
                if not gene:
                    continue
                metric = target_vs_rest.get(metric_key, {})
                if _metric_direction(metric) != "depleted":
                    continue
                if _claims_depleted_gene_on_target_cell(
                    hypothesis,
                    gene=gene,
                    celltype_tokens=celltype_tokens,
                ):
                    errors.append(
                        f"hypotheses[{idx}] makes a target-cell-depleted gene "
                        f"expression claim for {gene}: {ref} shows {metric_key} "
                        "is depleted in target-vs-rest Census evidence."
                    )
    return errors

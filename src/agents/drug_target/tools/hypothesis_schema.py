"""Schema-aware hypothesis_report.json canonicalization and persistence."""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from src.agents.drug_target.tools.hypothesis_grounding import validate_hypothesis_grounding

_SCHEMA_VERSION = "hypothesis_report.v2"
_SCORE_KEYS = (
    "evidence_coverage",
    "specificity",
    "novelty",
    "actionability",
    "composite",
)
_ENTITY_KEYS = ("genes", "pathways", "cell_types", "drugs")
_CATEGORY_ALIASES = {
    "MoA": "Mechanism of Action",
    "MOA": "Mechanism of Action",
}
_CATEGORIES = {
    "Mechanism of Action",
    "Therapeutic Strategy",
    "Cross-Target Interaction",
    "Novel Pathway",
}
REQUIRED_HYPOTHESIS_CATEGORIES = set(_CATEGORIES)
_GAP_PREFIX_RE = re.compile(r"^\s*(\[(?:FEATURED-GAP|GAP)\])\s*(.*)$")
_JSON_REF_RE = re.compile(r"([A-Za-z0-9_.\-]+\.json)(?:_FAILED)?")
_STAGE1_REF_RE = re.compile(r"^stage1_([A-Za-z0-9-]+)--([A-Za-z0-9-]+)\.json$")
_EPITHELIAL_ANCHOR_RE = re.compile(
    r"\b(AT2|transitional\s+AT2|alveolar\s+type\s+2|alveolar\s+epithelial|pulmonary\s+epithelial|epithelial)\b",
    re.IGNORECASE,
)
_PRIMARY_EPITHELIAL_INTRINSIC_COVERAGE_MISSING = (
    "PRIMARY_EPITHELIAL_INTRINSIC_COVERAGE_MISSING"
)
_GENE_LEVEL_EVIDENCE_REFERENCE_MISSING = "GENE_LEVEL_EVIDENCE_REFERENCE_MISSING"
_EMPTY_STAGE3_MATCHED_DRUGS_WORDING = "EMPTY_STAGE3_MATCHED_DRUGS_WORDING"
_BIOLOGICAL_ENTITY_GENE_WITHOUT_CITED_SUPPORT = (
    "BIOLOGICAL_ENTITY_GENE_WITHOUT_CITED_SUPPORT"
)
_FIBROSIS_RESOLUTION_WORDING = "FIBROSIS_RESOLUTION_WORDING"
_CHEMBL_DRUG_WORDING_RE = re.compile(
    r"\b("
    r"ChEMBL\s+(?:drug|drugs|compound|compounds|matched[- ]drug|matched[- ]drugs|bioactivity)"
    r"|stage\s*3\s+(?:drug|drugs|compound|compounds|matched[- ]drug|matched[- ]drugs|ChEMBL)"
    r"|matched_drugs"
    r")\b",
    re.IGNORECASE,
)
_FIBROSIS_RESOLUTION_RE = re.compile(r"\bfibrosis resolution\b", re.IGNORECASE)
_HYPOTHESIS_REJECTION_FILENAME = "hypothesis_report_last_rejection.json"


def _hypothesis_rejection_path(evidence_dir: Path) -> Path:
    return evidence_dir / _HYPOTHESIS_REJECTION_FILENAME


def _write_hypothesis_rejection(
    evidence_dir: Path,
    result: dict,
    *,
    stage: str = "save_hypothesis_report",
) -> None:
    payload = {
        "saved": False,
        "stage": stage,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "errors": result.get("errors", []),
        "diagnostics": result.get("diagnostics", []),
        "topn_coverage": result.get("topn_coverage"),
        "failed_pair_violations": result.get("failed_pair_violations", []),
        "hypothesis_grounding_violations": result.get(
            "hypothesis_grounding_violations",
            [],
        ),
        "prediction_grounding_summary": result.get("prediction_grounding_summary"),
    }
    try:
        _hypothesis_rejection_path(evidence_dir).write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError:
        return


def _clear_hypothesis_rejection(evidence_dir: Path) -> None:
    try:
        _hypothesis_rejection_path(evidence_dir).unlink()
    except OSError:
        return


def _parse_report(report: Any) -> tuple[dict | None, list[str]]:
    if isinstance(report, dict):
        return copy.deepcopy(report), []
    if isinstance(report, str):
        try:
            parsed = json.loads(report)
        except json.JSONDecodeError as exc:
            return None, [f"report is not valid JSON: {exc}"]
        if isinstance(parsed, dict):
            return parsed, []
    return None, ["report must be a JSON object"]


def _stage1_status(filename: str, evidence_dir: Path) -> str:
    match = _STAGE1_REF_RE.match(filename)
    if not match:
        return "not_stage1"
    try:
        from src.agents.drug_target.tools.evidence_loader import (
            _load_stage1_filter_results,
        )

        results = _load_stage1_filter_results(evidence_dir)
    except Exception:
        return "unknown"
    pair_key = f"{match.group(1).upper()}--{match.group(2).upper()}"
    passed = results.get(pair_key)
    if passed is True:
        return "passed"
    if passed is False:
        return "failed"
    return "unknown"


def _canonical_gap_type(title: str, explicit: str | None) -> tuple[str, str, str | None]:
    label = None
    clean_title = title.strip()
    match = _GAP_PREFIX_RE.match(clean_title)
    if match:
        label = match.group(1)
        clean_title = match.group(2).strip()
    if explicit in {"none", "orphan_evidence", "featured_coverage"}:
        gap_type = explicit
    elif label == "[FEATURED-GAP]":
        gap_type = "featured_coverage"
    elif label == "[GAP]":
        gap_type = "orphan_evidence"
    else:
        gap_type = "none"
    return clean_title, gap_type, label


def _canonical_entities(raw: Any) -> dict[str, list[str]]:
    entities = raw if isinstance(raw, dict) else {}
    out: dict[str, list[str]] = {}
    for key in _ENTITY_KEYS:
        values = entities.get(key, [])
        if not isinstance(values, list):
            values = []
        cleaned = [str(v).strip() for v in values if str(v).strip()]
        if key == "genes":
            cleaned = [v.upper() for v in cleaned]
        out[key] = cleaned
    return out


def _load_featured_gene_symbols(evidence_dir: Path) -> tuple[set[str], list[str]]:
    path = evidence_dir / "assessment_results.json"
    if not path.exists():
        return set(), []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return set(), [
            f"{_GENE_LEVEL_EVIDENCE_REFERENCE_MISSING}: could not parse "
            f"assessment_results.json for FEATURED gene-level evidence "
            f"reference validation: {exc}"
        ]
    if not isinstance(payload, dict):
        return set(), [
            f"{_GENE_LEVEL_EVIDENCE_REFERENCE_MISSING}: assessment_results.json "
            "must be a JSON object for FEATURED gene-level evidence reference "
            "validation."
        ]
    if "stage3_candidates" not in payload:
        return set(), []
    candidates = payload["stage3_candidates"]
    if not isinstance(candidates, list):
        return set(), [
            f"{_GENE_LEVEL_EVIDENCE_REFERENCE_MISSING}: assessment_results.json "
            "stage3_candidates must be a list for FEATURED gene-level evidence "
            "reference validation."
        ]
    genes: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        gene = str(item.get("gene") or item.get("gene_symbol") or "").strip().upper()
        if gene:
            genes.add(gene)
    return genes, []


def _hypothesis_text_mentions_gene(hypothesis: dict[str, Any], gene: str) -> bool:
    text = " ".join(
        str(hypothesis.get(field) or "")
        for field in (
            "title",
            "core_claim",
            "falsifiable_prediction",
            "validation_approach",
        )
    )
    if not text:
        return False
    pattern = re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(gene)}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    return bool(pattern.search(text))


def _hypothesis_entity_gene_symbols(hypothesis: dict[str, Any]) -> set[str]:
    entities = hypothesis.get("biological_entities")
    genes = entities.get("genes") if isinstance(entities, dict) else []
    if not isinstance(genes, list):
        return set()
    return {gene for item in genes if (gene := str(item).strip().upper())}


def _hypothesis_reference_tokens(hypothesis: dict[str, Any]) -> set[str]:
    refs = hypothesis.get("evidence_references")
    if not isinstance(refs, list):
        return set()
    tokens: set[str] = set()
    for ref in refs:
        match = _JSON_REF_RE.search(str(ref))
        if match:
            tokens.add(match.group(1))
    return tokens


def _available_gene_level_references(evidence_dir: Path, gene: str) -> list[str]:
    return [
        filename
        for filename in (f"ot_{gene}.json", f"stage3_{gene}.json")
        if (evidence_dir / filename).exists()
    ]


def _hypothesis_semantic_text(hypothesis: dict[str, Any]) -> str:
    entities = hypothesis.get("biological_entities")
    entity_drugs: list[Any] = []
    if isinstance(entities, dict):
        raw_drugs = entities.get("drugs")
        if isinstance(raw_drugs, list):
            entity_drugs = raw_drugs
    return " ".join(
        str(value)
        for value in [
            hypothesis.get("title"),
            hypothesis.get("core_claim"),
            hypothesis.get("falsifiable_prediction"),
            hypothesis.get("validation_approach"),
            *entity_drugs,
        ]
        if value
    )


def _matched_drugs_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _stage3_matched_drug_count(evidence_dir: Path, gene: str) -> int | None:
    path = evidence_dir / f"stage3_{gene.upper()}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    chembl = payload.get("chembl")
    nested = chembl.get("matched_drugs") if isinstance(chembl, dict) else None
    return max(
        _matched_drugs_count(payload.get("matched_drugs")),
        _matched_drugs_count(nested),
    )


def _stage1_reference_contains_gene(filename: str, gene: str) -> bool:
    match = _STAGE1_REF_RE.match(filename)
    if not match:
        return False
    return gene.upper() in {match.group(1).upper(), match.group(2).upper()}


def _gene_has_cited_support(gene: str, cited_refs: set[str]) -> bool:
    gene = gene.upper()
    if f"ot_{gene}.json" in cited_refs or f"stage3_{gene}.json" in cited_refs:
        return True
    return any(_stage1_reference_contains_gene(ref, gene) for ref in cited_refs)


def _semantic_hypothesis_warnings(canonical: dict, evidence_dir: Path) -> list[dict]:
    warnings: list[dict] = []
    hypotheses = canonical.get("hypotheses")
    if not isinstance(hypotheses, list):
        return warnings

    for idx, hypothesis in enumerate(hypotheses):
        if not isinstance(hypothesis, dict):
            continue
        text = _hypothesis_semantic_text(hypothesis)
        cited_refs = _hypothesis_reference_tokens(hypothesis)
        entity_genes = _hypothesis_entity_gene_symbols(hypothesis)

        if _FIBROSIS_RESOLUTION_RE.search(text):
            warnings.append({
                "code": _FIBROSIS_RESOLUTION_WORDING,
                "hypothesis_index": idx,
                "message": (
                    "Use fibrosis-relevant, matrix-deposition, or macrophage-fibroblast "
                    "readouts instead of fibrosis-resolution outcome wording."
                ),
            })

        for gene in sorted(entity_genes):
            if not _gene_has_cited_support(gene, cited_refs):
                warnings.append({
                    "code": _BIOLOGICAL_ENTITY_GENE_WITHOUT_CITED_SUPPORT,
                    "hypothesis_index": idx,
                    "gene": gene,
                    "message": (
                        f"{gene} appears in biological_entities.genes but this "
                        "hypothesis does not cite an ot/stage3 gene file or a "
                        "Stage 1 pair containing that gene."
                    ),
                })

        if not _CHEMBL_DRUG_WORDING_RE.search(text):
            continue
        for ref in sorted(cited_refs):
            match = re.match(r"^stage3_([A-Za-z0-9-]+)\.json$", ref)
            if not match:
                continue
            gene = match.group(1).upper()
            if _stage3_matched_drug_count(evidence_dir, gene) == 0:
                warnings.append({
                    "code": _EMPTY_STAGE3_MATCHED_DRUGS_WORDING,
                    "hypothesis_index": idx,
                    "gene": gene,
                    "reference": ref,
                    "message": (
                        f"{ref} has empty matched_drugs; attribute known-drug "
                        "programs to ot_<GENE>.json/OpenTargets instead of "
                        "Stage 3 ChEMBL matched-drug evidence."
                    ),
                })

    return warnings


def _validate_featured_gene_level_references(
    canonical: dict,
    evidence_dir: Path,
) -> list[str]:
    featured_genes, errors = _load_featured_gene_symbols(evidence_dir)
    if errors:
        return errors
    if not featured_genes:
        return []

    hypotheses = canonical.get("hypotheses")
    if not isinstance(hypotheses, list):
        return errors

    for idx, hypothesis in enumerate(hypotheses):
        if not isinstance(hypothesis, dict):
            continue
        cited_refs = _hypothesis_reference_tokens(hypothesis)
        entity_genes = _hypothesis_entity_gene_symbols(hypothesis)
        missing_by_gene: dict[str, list[str]] = {}
        for gene in sorted(featured_genes & entity_genes):
            if not _hypothesis_text_mentions_gene(hypothesis, gene):
                continue
            available_refs = _available_gene_level_references(evidence_dir, gene)
            missing_refs = [ref for ref in available_refs if ref not in cited_refs]
            if missing_refs:
                missing_by_gene[gene] = missing_refs
        if missing_by_gene:
            grouped = "; ".join(
                f"{gene}: {', '.join(missing_refs)}"
                for gene, missing_refs in missing_by_gene.items()
            )
            errors.append(
                f"{_GENE_LEVEL_EVIDENCE_REFERENCE_MISSING}: hypotheses[{idx}] "
                f"missing available gene-level evidence references for FEATURED genes: "
                f"{grouped}"
            )

    return errors


def _canonical_reference_detail(
    ref: Any,
    evidence_dir: Path,
    *,
    allow_failed_marker_contrast: bool,
) -> dict | None:
    if isinstance(ref, dict):
        display = str(ref.get("display_reference") or ref.get("filename") or "").strip()
        usage = ref.get("usage")
    else:
        display = str(ref).strip()
        usage = None
    if not display:
        return None
    match = _JSON_REF_RE.search(display)
    if not match:
        return None
    filename = match.group(1)
    failed_marker = ".json_FAILED" in display
    status = _stage1_status(filename, evidence_dir)
    if usage not in {"primary", "supporting", "contrast"}:
        usage = "contrast" if failed_marker and allow_failed_marker_contrast else "primary"
    display_reference = filename
    if failed_marker and usage != "contrast":
        display_reference = f"{filename}_FAILED"
    return {
        "filename": filename,
        "usage": usage,
        "stage1_pair_status": status,
        "display_reference": display_reference,
    }


def _clean_contrast_reference(ref: Any) -> str | None:
    display = str(ref).strip()
    if not display:
        return None
    match = _JSON_REF_RE.search(display)
    if not match:
        return None
    return match.group(1)


def _validate_scores(hyp: dict, *, strict: bool, errors: list[str], index: int) -> dict:
    raw = hyp.get("scores")
    if not isinstance(raw, dict):
        raw = {}
    scores: dict[str, float | None] = {}
    for key in _SCORE_KEYS:
        value = raw.get(key)
        if isinstance(value, bool):
            value = None
        if isinstance(value, (int, float)) and 0.0 <= float(value) <= 1.0:
            scores[key] = float(value)
            continue
        if strict:
            errors.append(f"hypotheses[{index}].scores.{key} must be a number in [0.0, 1.0]")
        scores[key] = None
    return scores


def canonicalize_hypothesis_report(
    report: Any,
    evidence_dir: Path,
    *,
    legacy_compat: bool = True,
) -> tuple[dict | None, list[str], list[dict]]:
    """Return a canonical v2 report, validation errors, and diagnostics."""
    parsed, errors = _parse_report(report)
    diagnostics: list[dict] = []
    if parsed is None:
        return None, errors, diagnostics

    canonical = copy.deepcopy(parsed)
    canonical["schema_version"] = _SCHEMA_VERSION

    hypotheses = canonical.get("hypotheses")
    if not isinstance(hypotheses, list):
        return None, ["hypotheses must be a list"], diagnostics

    for idx, hyp in enumerate(hypotheses):
        if not isinstance(hyp, dict):
            errors.append(f"hypotheses[{idx}] must be an object")
            continue

        title, gap_type, label = _canonical_gap_type(
            str(hyp.get("title") or hyp.get("hypothesis") or ""),
            hyp.get("gap_type"),
        )
        hyp["title"] = title
        hyp["gap_type"] = gap_type
        if label:
            hyp["legacy_title_prefix"] = label

        category = hyp.get("category")
        if isinstance(category, str):
            category = _CATEGORY_ALIASES.get(category, category)
        if category not in _CATEGORIES:
            if legacy_compat:
                category = "Mechanism of Action"
                diagnostics.append({
                    "code": "LEGACY_CATEGORY_DEFAULTED",
                    "hypothesis_index": idx,
                })
            else:
                errors.append(f"hypotheses[{idx}].category is not canonical")
        hyp["category"] = category

        hyp["biological_entities"] = _canonical_entities(hyp.get("biological_entities"))
        hyp["scores"] = _validate_scores(hyp, strict=not legacy_compat, errors=errors, index=idx)
        existing_contrast = [
            cleaned
            for ref in hyp.get("contrast_references", [])
            if (cleaned := _clean_contrast_reference(ref)) is not None
        ]

        raw_details = hyp.get("evidence_reference_details")
        allow_failed_marker_contrast = isinstance(raw_details, list)
        if not allow_failed_marker_contrast:
            raw_details = hyp.get("evidence_references", [])
        if not isinstance(raw_details, list):
            raw_details = []
        details = [
            detail
            for ref in raw_details
            if (
                detail := _canonical_reference_detail(
                    ref,
                    evidence_dir,
                    allow_failed_marker_contrast=allow_failed_marker_contrast,
                )
            )
            is not None
        ]
        hyp["evidence_reference_details"] = details
        hyp["evidence_references"] = [
            d["display_reference"]
            for d in details
            if d["usage"] != "contrast"
        ]
        contrast = [
            d["display_reference"]
            for d in details
            if d["usage"] == "contrast" and d["display_reference"] not in existing_contrast
        ]
        hyp["contrast_references"] = existing_contrast + contrast

    gap_analysis = canonical.get("gap_analysis")
    if not isinstance(gap_analysis, dict):
        gap_analysis = {}
        canonical["gap_analysis"] = gap_analysis
    orphans = gap_analysis.get("orphan_files", [])
    if not isinstance(orphans, list):
        orphans = []
    gap_analysis["orphan_files"] = [
        entry[:-len("_FAILED")] if isinstance(entry, str) and entry.endswith("_FAILED") else entry
        for entry in orphans
    ]
    gap_analysis.setdefault("total_evidence_files", 0)
    gap_analysis.setdefault("referenced_files", 0)

    return canonical, errors, diagnostics


def _hypothesis_has_epithelial_anchor(hypothesis: dict[str, Any]) -> bool:
    fields = [
        hypothesis.get("title"),
        hypothesis.get("core_claim"),
        hypothesis.get("mechanism"),
        hypothesis.get("patient_context"),
        hypothesis.get("experimental_test"),
        hypothesis.get("falsifiable_prediction"),
    ]
    raw_cell_types = hypothesis.get("cell_types")
    cell_types: list[Any] = raw_cell_types if isinstance(raw_cell_types, list) else []
    entities = hypothesis.get("biological_entities")
    entity_cell_types: list[Any] = []
    if isinstance(entities, dict):
        raw_entity_cell_types = entities.get("cell_types")
        if isinstance(raw_entity_cell_types, list):
            entity_cell_types = raw_entity_cell_types
    text = " ".join(
        str(value)
        for value in [*fields, *cell_types, *entity_cell_types]
        if value
    )
    return bool(_EPITHELIAL_ANCHOR_RE.search(text))


def _normal_celltype(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return " ".join(text.split())


_LEGACY_AT2_TOKENS = {
    "at2",
    "transitional at2",
    "pulmonary alveolar type 2 cell",
    "alveolar type 2 cell",
    "alveolar epithelial",
    "pulmonary epithelial",
    "epithelial",
}


def _celltype_resolution_context(evidence_dir: Path) -> dict[str, Any]:
    try:
        celltype_resolution = json.loads(
            (evidence_dir / "celltype_resolution.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return {
            "branch": "unknown",
            "legacy_at2": False,
            "semantic_proxy": False,
            "anchor_tokens": set(),
            "match_modes": set(),
        }
    if not isinstance(celltype_resolution, dict):
        return {
            "branch": "unknown",
            "legacy_at2": False,
            "semantic_proxy": False,
            "anchor_tokens": set(),
            "match_modes": set(),
        }

    raw_tokens: list[str] = []
    match_modes: set[str] = set()
    for key in ("primary_input_celltype", "primary_resolved_celltype"):
        value = celltype_resolution.get(key)
        if isinstance(value, str):
            raw_tokens.append(value)

    interest_celltypes = celltype_resolution.get("interest_celltypes")
    if isinstance(interest_celltypes, list):
        raw_tokens.extend(
            value for value in interest_celltypes if isinstance(value, str)
        )

    matches = celltype_resolution.get("matches")
    if isinstance(matches, list):
        for match in matches:
            if not isinstance(match, dict):
                continue
            match_mode = str(match.get("match_mode") or "").strip()
            if match_mode:
                match_modes.add(match_mode)
            for key in ("input_celltype", "matched_celltype", "resolved_celltype"):
                value = match.get(key)
                if isinstance(value, str):
                    raw_tokens.append(value)

    anchor_tokens = {
        token
        for token in (_normal_celltype(value) for value in raw_tokens)
        if token
    }
    legacy_at2 = bool(anchor_tokens.intersection(_LEGACY_AT2_TOKENS))
    semantic_proxy = "semantic_proxy" in match_modes
    branch = (
        "legacy_at2"
        if legacy_at2
        else "semantic_proxy" if semantic_proxy else "dynamic"
    )
    return {
        "branch": branch,
        "legacy_at2": legacy_at2,
        "semantic_proxy": semantic_proxy,
        "anchor_tokens": anchor_tokens,
        "match_modes": match_modes,
    }


def _celltype_resolution_anchor_tokens(evidence_dir: Path) -> set[str]:
    context = _celltype_resolution_context(evidence_dir)
    tokens = context["anchor_tokens"]
    return set(tokens) if isinstance(tokens, set) else set()


def _celltype_anchor_variants(tokens: set[str]) -> set[str]:
    variants = set(tokens)
    for token in tokens:
        if token.endswith(" cell"):
            variants.add(f"{token}s")
    return variants


def _hypothesis_has_interest_cell_anchor(
    hypothesis: dict[str, Any],
    evidence_dir: Path,
) -> bool:
    if _hypothesis_has_epithelial_anchor(hypothesis):
        return True

    fields: list[Any] = [
        hypothesis.get("title"),
        hypothesis.get("core_claim"),
        hypothesis.get("mechanism"),
        hypothesis.get("patient_context"),
        hypothesis.get("experimental_test"),
        hypothesis.get("falsifiable_prediction"),
        hypothesis.get("validation_approach"),
    ]

    raw_cell_types = hypothesis.get("cell_types")
    if isinstance(raw_cell_types, list):
        fields.extend(raw_cell_types)

    entities = hypothesis.get("biological_entities")
    if isinstance(entities, dict):
        raw_entity_cell_types = entities.get("cell_types")
        if isinstance(raw_entity_cell_types, list):
            fields.extend(raw_entity_cell_types)

    text = _normal_celltype(" ".join(str(value) for value in fields if value))
    if not text:
        return False

    return any(
        f" {token} " in f" {text} "
        for token in _celltype_anchor_variants(
            _celltype_resolution_anchor_tokens(evidence_dir)
        )
    )


def _stage1_pair_files_for_intrinsic_coverage(
    canonical: dict[str, Any],
    evidence_dir: Path,
) -> list[str]:
    stage1_pair_files: set[str] = set()
    explicit = canonical.get("stage1_pair_files")
    if isinstance(explicit, list):
        stage1_pair_files.update(
            filename
            for item in explicit
            if _STAGE1_REF_RE.match(filename := str(item).strip())
        )

    from src.agents.drug_target.tools.evidence_loader import (
        _list_real_evidence_filenames,
        _load_stage1_filter_results_status,
    )

    filter_results, filter_err = _load_stage1_filter_results_status(evidence_dir)
    if filter_err:
        return sorted(stage1_pair_files)

    for filename in sorted(_list_real_evidence_filenames(evidence_dir)):
        match = _STAGE1_REF_RE.match(filename)
        if not match:
            continue
        pair_key = f"{match.group(1).upper()}--{match.group(2).upper()}"
        if filter_results.get(pair_key) is True:
            stage1_pair_files.add(filename)
    return sorted(stage1_pair_files)


def _validate_primary_epithelial_intrinsic_coverage(
    canonical: dict[str, Any],
    evidence_dir: str | Path,
) -> list[str]:
    from src.agents.drug_target.tools.evidence_loader import (
        _stage1_pair_usage_guidance,
    )

    evidence_path = Path(evidence_dir)
    guidance = _stage1_pair_usage_guidance(
        evidence_path,
        _stage1_pair_files_for_intrinsic_coverage(canonical, evidence_path),
    )
    intrinsic_files = set(
        guidance.get("interest_cell_intrinsic_stage1_pair_files") or []
    )
    if not intrinsic_files:
        return []

    for hypothesis in canonical.get("hypotheses") or []:
        if not isinstance(hypothesis, dict):
            continue
        refs = hypothesis.get("evidence_references")
        if not isinstance(refs, list):
            continue
        if intrinsic_files.intersection(str(ref) for ref in refs) and (
            _hypothesis_has_interest_cell_anchor(hypothesis, evidence_path)
        ):
            return []

    return [_PRIMARY_EPITHELIAL_INTRINSIC_COVERAGE_MISSING]


def persist_hypothesis_report(data_dir: str | Path, report: Any) -> dict:
    """Validate, canonicalize, and write evidence/hypothesis_report.json."""
    base = Path(data_dir).expanduser().resolve()
    evidence_dir = base / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    parsed, _ = _parse_report(report)
    legacy_compat = not (
        isinstance(parsed, dict) and parsed.get("schema_version") == _SCHEMA_VERSION
    )
    canonical, errors, diagnostics = canonicalize_hypothesis_report(
        report,
        evidence_dir,
        legacy_compat=legacy_compat,
    )
    result = {
        "saved": False,
        "path": str(evidence_dir / "hypothesis_report.json"),
        "errors": errors,
        "diagnostics": diagnostics,
    }
    if canonical is None:
        _write_hypothesis_rejection(evidence_dir, result)
        return result
    diagnostics.extend(_semantic_hypothesis_warnings(canonical, evidence_dir))

    from src.agents.drug_target.tools.evidence_loader import (
        _tag_hypothesis_prediction_grounding,
        _validate_hypothesis_report_references,
        _validate_hypothesis_report_topn_and_failed_pairs,
    )

    diag = _validate_hypothesis_report_topn_and_failed_pairs(canonical, evidence_dir)
    canonical["evidence_coverage_pct"] = diag["evidence_coverage_pct"]
    canonical["topn_coverage"] = diag["topn_coverage"]
    canonical["gap_analysis"] = diag["gap_analysis"]

    deterministic_errors: list[str] = []
    ref_errors = _validate_hypothesis_report_references(canonical, evidence_dir)
    deterministic_errors.extend(ref_errors)
    gene_ref_errors = _validate_featured_gene_level_references(canonical, evidence_dir)
    deterministic_errors.extend(gene_ref_errors)
    grounding_errors = validate_hypothesis_grounding(canonical, evidence_dir)
    deterministic_errors.extend(grounding_errors)
    primary_coverage_errors = _validate_primary_epithelial_intrinsic_coverage(
        canonical,
        evidence_dir,
    )
    deterministic_errors.extend(primary_coverage_errors)
    if diag["reject_reason"]:
        deterministic_errors.append(diag["reject_reason"])
    if deterministic_errors:
        result["errors"].extend(deterministic_errors)
        result["topn_coverage"] = diag["topn_coverage"]
        result["failed_pair_violations"] = diag["failed_pair_violations"]
        if grounding_errors:
            result["hypothesis_grounding_violations"] = grounding_errors
        _write_hypothesis_rejection(evidence_dir, result)
        return result

    prediction_grounding = _tag_hypothesis_prediction_grounding(
        canonical,
        evidence_dir=evidence_dir,
    )
    canonical["prediction_grounding_summary"] = prediction_grounding
    if prediction_grounding.get("grounded", 0) > 0:
        result["errors"].append(
            "One or more falsifiable predictions contain fabricated or "
            "non-evidence-derived numeric values. Use qualitative wording unless "
            "the numeric value appears in a cited evidence file."
        )
        result["prediction_grounding_summary"] = prediction_grounding
        _write_hypothesis_rejection(evidence_dir, result)
        return result
    if prediction_grounding.get("unverified", 0) > 0:
        result["errors"].append(
            "One or more falsifiable predictions contain unverified numeric values. "
            "Use qualitative wording unless the numeric value appears in a cited "
            "evidence file."
        )
        result["prediction_grounding_summary"] = prediction_grounding
        _write_hypothesis_rejection(evidence_dir, result)
        return result

    if result["errors"]:
        _write_hypothesis_rejection(evidence_dir, result)
        return result

    path = evidence_dir / "hypothesis_report.json"
    path.write_text(json.dumps(canonical, indent=2, ensure_ascii=False), encoding="utf-8")
    _clear_hypothesis_rejection(evidence_dir)
    result["saved"] = True
    result["diagnostics"] = diagnostics
    return result


def _quality_error(code: str, message: str, **details: Any) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if details:
        err["details"] = details
    return err


def _load_hypothesis_rejection(evidence_dir: Path) -> dict | None:
    path = _hypothesis_rejection_path(evidence_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "errors": [f"Could not parse {_HYPOTHESIS_REJECTION_FILENAME}: {exc}"],
        }
    return payload if isinstance(payload, dict) else {
        "errors": [f"{_HYPOTHESIS_REJECTION_FILENAME} did not contain a JSON object"],
    }


def _append_last_rejection_quality_error(result: dict, evidence_dir: Path) -> None:
    rejection = _load_hypothesis_rejection(evidence_dir)
    if not rejection:
        return
    errors = rejection.get("errors")
    if not isinstance(errors, list) or not errors:
        return
    details = dict(rejection)
    if "code" in details:
        details["sidecar_code"] = details.pop("code")
    if "message" in details:
        details["sidecar_message"] = details.pop("message")
    result["errors"].append(
        _quality_error(
            "HYPOTHESIS_LAST_SAVE_REJECTION",
            "The last save_hypothesis_report attempt was rejected; use these details for retry repair.",
            **details,
        )
    )


def validate_hypothesis_report_quality(
    data_dir: str | Path,
    *,
    run_started_at: float | None = None,
    min_hypotheses: int = 4,
    max_hypotheses: int = 6,
) -> dict:
    """Validate a saved hypothesis report for graph-level finalization gating."""
    base = Path(data_dir).expanduser().resolve()
    evidence_dir = base / "evidence"
    path = evidence_dir / "hypothesis_report.json"
    result: dict = {
        "valid": False,
        "errors": [],
        "warnings": [],
        "path": str(path),
        "hypothesis_count": None,
        "category_coverage": {
            "required": sorted(REQUIRED_HYPOTHESIS_CATEGORIES),
            "present": [],
            "missing": sorted(REQUIRED_HYPOTHESIS_CATEGORIES),
        },
        "topn_coverage": None,
        "evidence_coverage_pct": None,
    }

    if not path.exists():
        result["errors"].append(
            _quality_error(
                "HYPOTHESIS_REPORT_MISSING",
                "evidence/hypothesis_report.json is missing.",
            )
        )
        _append_last_rejection_quality_error(result, evidence_dir)
        return result

    try:
        mtime = path.stat().st_mtime
    except OSError as exc:
        result["errors"].append(
            _quality_error(
                "HYPOTHESIS_REPORT_STAT_FAILED",
                f"Could not inspect hypothesis_report.json: {exc}",
            )
        )
        _append_last_rejection_quality_error(result, evidence_dir)
        return result
    if run_started_at is not None and mtime < run_started_at:
        result["errors"].append(
            _quality_error(
                "HYPOTHESIS_REPORT_STALE",
                "hypothesis_report.json predates the current graph run.",
                report_mtime=mtime,
                run_started_at=run_started_at,
            )
        )
        _append_last_rejection_quality_error(result, evidence_dir)
        return result

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        result["errors"].append(
            _quality_error(
                "HYPOTHESIS_REPORT_INVALID_JSON",
                f"hypothesis_report.json is not valid JSON: {exc}",
            )
        )
        _append_last_rejection_quality_error(result, evidence_dir)
        return result

    canonical, errors, diagnostics = canonicalize_hypothesis_report(
        raw,
        evidence_dir,
        legacy_compat=False,
    )
    result["warnings"].extend(diagnostics)
    if canonical is None:
        result["errors"].append(
            _quality_error(
                "SCHEMA_VALIDATION_FAILED",
                "; ".join(errors) or "hypothesis_report.json failed schema validation.",
                errors=errors,
            )
        )
        _append_last_rejection_quality_error(result, evidence_dir)
        return result
    result["warnings"].extend(_semantic_hypothesis_warnings(canonical, evidence_dir))
    if errors:
        result["errors"].append(
            _quality_error(
                "SCHEMA_VALIDATION_FAILED",
                "; ".join(errors),
                errors=errors,
            )
        )

    from src.agents.drug_target.tools.evidence_loader import (
        _tag_hypothesis_prediction_grounding,
        _validate_hypothesis_report_references,
        _validate_hypothesis_report_topn_and_failed_pairs,
    )

    hypotheses = canonical.get("hypotheses", [])
    hypothesis_count = len(hypotheses) if isinstance(hypotheses, list) else 0
    result["hypothesis_count"] = hypothesis_count
    if hypothesis_count < min_hypotheses or hypothesis_count > max_hypotheses:
        result["errors"].append(
            _quality_error(
                "HYPOTHESIS_COUNT_OUT_OF_RANGE",
                f"Expected {min_hypotheses}-{max_hypotheses} hypotheses, found {hypothesis_count}.",
                min=min_hypotheses,
                max=max_hypotheses,
                found=hypothesis_count,
            )
        )

    present_categories: set[str] = set()
    for hyp in hypotheses:
        if not isinstance(hyp, dict):
            continue
        category = hyp.get("category")
        if isinstance(category, str) and category in REQUIRED_HYPOTHESIS_CATEGORIES:
            present_categories.add(category)
    missing_categories = sorted(REQUIRED_HYPOTHESIS_CATEGORIES - present_categories)
    result["category_coverage"] = {
        "required": sorted(REQUIRED_HYPOTHESIS_CATEGORIES),
        "present": sorted(present_categories),
        "missing": missing_categories,
    }
    if missing_categories:
        result["errors"].append(
            _quality_error(
                "MISSING_REQUIRED_CATEGORIES",
                "Hypothesis report is missing required thematic categories.",
                missing=missing_categories,
            )
        )

    diag = _validate_hypothesis_report_topn_and_failed_pairs(canonical, evidence_dir)
    result["topn_coverage"] = diag["topn_coverage"]
    result["evidence_coverage_pct"] = diag["evidence_coverage_pct"]
    ref_errors = _validate_hypothesis_report_references(canonical, evidence_dir)
    if ref_errors:
        result["errors"].append(
            _quality_error(
                "INVALID_EVIDENCE_REFERENCES",
                "; ".join(ref_errors),
                errors=ref_errors,
            )
        )
    gene_ref_errors = _validate_featured_gene_level_references(canonical, evidence_dir)
    if gene_ref_errors:
        result["errors"].append(
            _quality_error(
                _GENE_LEVEL_EVIDENCE_REFERENCE_MISSING,
                "; ".join(gene_ref_errors),
                errors=gene_ref_errors,
            )
        )
    grounding_errors = validate_hypothesis_grounding(canonical, evidence_dir)
    result["hypothesis_grounding_violations"] = grounding_errors
    if grounding_errors:
        result["errors"].append(
            _quality_error(
                "HYPOTHESIS_GROUNDING_VIOLATION",
                "; ".join(grounding_errors),
                errors=grounding_errors,
            )
        )
    primary_coverage_errors = _validate_primary_epithelial_intrinsic_coverage(
        canonical,
        evidence_dir,
    )
    for error_code in primary_coverage_errors:
        result["errors"].append(
            _quality_error(
                error_code,
                "At least one hypothesis must cite an intrinsic Stage 1 pair file "
                "and name the original interest cell label, resolved Census cell "
                "type, or legacy AT2/epithelial context.",
            )
        )
    if diag["failed_pair_violations"]:
        result["errors"].append(
            _quality_error(
                "FAILED_PAIR_VIOLATION",
                "; ".join(diag["failed_pair_violations"]),
                errors=diag["failed_pair_violations"],
            )
        )
    if diag["reject_reason"]:
        result["errors"].append(
            _quality_error(
                "TOPN_COVERAGE_MISSING",
                diag["reject_reason"],
                topn_coverage=diag["topn_coverage"],
            )
        )

    grounding = _tag_hypothesis_prediction_grounding(canonical, evidence_dir=evidence_dir)
    result["prediction_grounding_summary"] = grounding
    if grounding.get("grounded", 0) > 0:
        result["errors"].append(
            _quality_error(
                "NON_EVIDENCE_DERIVED_NUMERIC_PREDICTION",
                "One or more falsifiable predictions contain fabricated or "
                "non-evidence-derived numeric values. Use qualitative wording "
                "unless the numeric value appears in a cited evidence file.",
                grounded_indices=grounding.get("grounded_indices", []),
            )
        )
    if grounding.get("unverified", 0) > 0:
        result["errors"].append(
            _quality_error(
                "UNVERIFIED_NUMERIC_PREDICTION",
                "One or more falsifiable predictions contain unverified numeric values.",
                unverified_indices=grounding.get("unverified_indices", []),
            )
        )

    if result["errors"]:
        _append_last_rejection_quality_error(result, evidence_dir)

    result["valid"] = not result["errors"]
    return result


@tool
def save_hypothesis_report(data_dir: str, report: dict) -> str:
    """Save canonical schema-validated evidence/hypothesis_report.json."""
    return json.dumps(persist_hypothesis_report(data_dir, report), indent=2)

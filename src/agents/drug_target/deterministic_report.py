"""No-LLM deterministic report path for drug-target finalization."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment
from langchain_core.runnables import RunnableConfig

from src.agents.drug_target.tools.scoring_metadata import NOVELTY_OPPORTUNITY_LEGEND


_SCORE_FIELDS = (
    "existing_drug_evidence",
    "clinical_trial_activity",
    "safety_profile",
    "validated_total",
    "gwas_support",
    "tractability",
    "biological_plausibility",
    "novelty_opportunity",
    "exploratory_total",
    "combined_total",
)
_MARKDOWN_TEMPLATE_SUBPATH = (
    Path("skills")
    / "drug-target-reporting"
    / "templates"
    / "drug_report.md.j2"
)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PACKAGE_MARKDOWN_TEMPLATE = (
    Path(__file__).resolve().parent / "templates" / "drug_report.md.j2"
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_optional_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return _load_json(path)
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _required_evidence_paths(base: Path) -> dict[str, Path]:
    return {
        "assessment_results": base / "evidence" / "assessment_results.json",
        "hypothesis_report": base / "evidence" / "hypothesis_report.json",
    }


def _missing_required_evidence(base: Path) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for name, path in _required_evidence_paths(base).items():
        if not path.exists():
            issues.append(
                {
                    "code": "MISSING_REQUIRED_EVIDENCE",
                    "severity": "critical",
                    "message": (
                        "Required evidence file is missing: "
                        f"{path.relative_to(base)}"
                    ),
                    "path": str(path),
                    "evidence_key": name,
                }
            )
    return issues


def _invalid_report_data(
    base: Path,
    disease: str,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "drug_target.report_data.v1",
        "valid": False,
        "created_at": _utc_now(),
        "data_dir": str(base),
        "disease": disease,
        "issues": issues,
        "sections": {},
        "candidates": [],
        "hypotheses": [],
        "sources": {},
    }


def _invalid_required_json_issue(
    base: Path,
    evidence_key: str,
    path: Path,
    error: Exception,
) -> dict[str, Any]:
    return {
        "code": "INVALID_REQUIRED_EVIDENCE_JSON",
        "severity": "critical",
        "message": (
            "Required evidence file is not valid JSON: "
            f"{path.relative_to(base)}"
        ),
        "path": str(path.relative_to(base)),
        "evidence_key": evidence_key,
        "error": str(error),
    }


def _normalize_gene(value: object) -> str:
    return str(value or "").strip().upper()


def _assessment_rows(
    assessment: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = assessment.get("rubric_assessment")
    if not isinstance(rows, list):
        return [], [
            {
                "code": "INVALID_ASSESSMENT_SHAPE",
                "severity": "critical",
                "message": "assessment_results.json must include rubric_assessment as a list",
                "path": "evidence/assessment_results.json",
            }
        ]
    issues: list[dict[str, Any]] = []
    valid_rows: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if isinstance(row, dict):
            valid_rows.append(row)
            continue
        issues.append(
            {
                "code": "INVALID_ASSESSMENT_ROW",
                "severity": "critical",
                "message": "rubric_assessment rows must be JSON objects",
                "path": "evidence/assessment_results.json",
                "row_index": index,
            }
        )
    return valid_rows, issues


def _stage3_genes(assessment: dict[str, Any], rows: list[dict[str, Any]]) -> set[str]:
    stage3_candidates = assessment.get("stage3_candidates")
    genes: set[str] = set()
    if isinstance(stage3_candidates, list):
        for item in stage3_candidates:
            if isinstance(item, dict):
                gene = _normalize_gene(item.get("gene"))
                if gene:
                    genes.add(gene)
    if genes:
        return genes

    return {
        _normalize_gene(row.get("gene"))
        for row in rows
        if row.get("stage3_candidate")
    }


def _dedupe_strings(values: Sequence[object | None]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _safe_text(value: object, default: str = "not available") -> str:
    text = "" if value is None else str(value).strip()
    return text if text else default


def _markdown_template_path() -> Path:
    explicit_path = os.environ.get("DRUG_TARGET_REPORT_TEMPLATE_PATH")
    if explicit_path:
        path = Path(explicit_path).expanduser().resolve()
        if path.exists():
            return path
        raise FileNotFoundError(f"Missing markdown template: {path}")

    explicit_dir = os.environ.get("DRUG_TARGET_REPORT_TEMPLATE_DIR")
    if explicit_dir:
        path = Path(explicit_dir).expanduser().resolve() / "drug_report.md.j2"
        if path.exists():
            return path
        raise FileNotFoundError(f"Missing markdown template: {path}")

    for candidate in (
        _PROJECT_ROOT / _MARKDOWN_TEMPLATE_SUBPATH,
        _PACKAGE_MARKDOWN_TEMPLATE,
    ):
        if candidate.exists():
            return candidate

    for parent in Path(__file__).resolve().parents:
        candidate = parent / _MARKDOWN_TEMPLATE_SUBPATH
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Missing markdown template: {_MARKDOWN_TEMPLATE_SUBPATH}")


def _load_optional_dict(path: Path) -> dict[str, Any]:
    payload = _load_optional_json(path, {})
    return payload if isinstance(payload, dict) else {}


def _load_stage1_filter_results(base: Path) -> list[dict[str, Any]]:
    json_path = base / "evidence" / "stage1_filter_results.json"
    if json_path.exists():
        payload = _load_optional_json(json_path, [])
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]

    csv_path = base / "evidence" / "stage1_filter_results.csv"
    if csv_path.exists():
        import csv

        with csv_path.open(encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    return []


def _is_true(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def _float_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_pvalue(value: object) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "N/A"
    return f"{numeric:.2e}" if numeric < 0.001 else f"{numeric:.4f}"


def _format_rr(value: object) -> str:
    numeric = _float_or_none(value)
    if numeric is None or not (numeric < float("inf") and numeric > float("-inf")):
        return "N/A"
    return f"{numeric:.2f}"


def _format_float(value: object, digits: int = 4) -> str:
    numeric = _float_or_none(value)
    if numeric is None:
        return "N/A"
    return f"{numeric:.{digits}f}"


def _format_stage1_filter_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    formatted: list[dict[str, Any]] = []
    for row in rows:
        formatted.append(
            {
                **row,
                "_passed": _is_true(row.get("passed")),
                "_string": _format_float(row.get("string_combined")),
                "_coexpr_p": _format_pvalue(row.get("census_coexpr_pvalue")),
                "_gene_a_p": _format_pvalue(row.get("census_gene_a_pvalue")),
                "_gene_b_p": _format_pvalue(row.get("census_gene_b_pvalue")),
                "_gene_a_rr": _format_rr(row.get("gene_a_risk_ratio")),
                "_gene_b_rr": _format_rr(row.get("gene_b_risk_ratio")),
                "_coexpr_rr": _format_rr(row.get("coexpr_risk_ratio")),
                "_coexpr_tgt": _format_float(row.get("coexpr_target_pct"), 2),
            }
        )
    formatted.sort(key=lambda row: (not row["_passed"], str(row.get("ligand", ""))))
    return formatted


def _stage1_filter_lookup(rows: list[dict[str, Any]]) -> dict[tuple[str, str], bool]:
    lookup: dict[tuple[str, str], bool] = {}
    for row in rows:
        ligand = _normalize_gene(row.get("ligand"))
        receptor = _normalize_gene(row.get("receptor"))
        if ligand and receptor:
            lookup[(ligand, receptor)] = _is_true(row.get("passed"))
    return lookup


def _dict_list(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _indications_text(value: object) -> str:
    if not isinstance(value, list):
        return "N/A"
    values: list[object | None] = []
    for item in value:
        if isinstance(item, dict):
            values.append(item.get("name") or item.get("efo_term"))
        else:
            values.append(item)
    items = _dedupe_strings(values)
    return ", ".join(items) or "N/A"


def _template_drug(drug: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _safe_text(drug.get("name") or drug.get("drug_name"), "Unknown"),
        "chembl_id": _safe_text(
            drug.get("chembl_id") or drug.get("molecule_chembl_id"),
            "",
        ),
        "moa": _safe_text(
            drug.get("mechanism_of_action") or drug.get("moa"),
            "mechanism not available",
        ),
        "phase": _safe_text(
            drug.get("phase") or drug.get("max_phase"),
            "Preclinical",
        ),
        "indications": _indications_text(drug.get("indications")),
    }


def _split_template_drugs(
    drugs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    clinical: list[dict[str, Any]] = []
    preclinical: list[dict[str, Any]] = []
    for drug in drugs:
        formatted = _template_drug(drug)
        phase = _safe_text(drug.get("phase") or drug.get("max_phase"), "")
        if phase and phase not in {"0", "Preclinical"}:
            clinical.append(formatted)
        else:
            preclinical.append(formatted)
    return clinical, preclinical


def _pathway_parts(pathway_data: dict[str, Any]) -> list[dict[str, str]]:
    parts: list[dict[str, str]] = []
    for role, key in (
        ("ligand", "ligand_pathways"),
        ("receptor", "receptor_pathways"),
    ):
        pathways = pathway_data.get(key, [])
        if isinstance(pathways, list) and pathways:
            parts.append(
                {
                    "role": role,
                    "pathways": "; ".join(str(pathway) for pathway in pathways[:3]),
                }
            )
    return parts


def _pair_genes(pair_key: str, pair_data: dict[str, Any]) -> tuple[str, str]:
    ligand = _safe_text(pair_data.get("ligand"), "")
    receptor = _safe_text(pair_data.get("receptor"), "")
    if ligand and receptor:
        return ligand, receptor
    delimiter = "^" if "^" in pair_key else "--"
    parts = pair_key.split(delimiter, 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return ligand, receptor


def _template_pair(
    pair_key: str,
    pair_data: dict[str, Any],
    filter_lookup: dict[tuple[str, str], bool],
) -> dict[str, Any]:
    ligand, receptor = _pair_genes(pair_key, pair_data)
    ppi = pair_data.get("string_ppi", {})
    ppi = ppi if isinstance(ppi, dict) else {}
    census_validation = pair_data.get("census_validation", {})
    census_validation = census_validation if isinstance(census_validation, dict) else {}
    target_vs_rest = census_validation.get("target_vs_rest", {})
    target_vs_rest = target_vs_rest if isinstance(target_vs_rest, dict) else {}
    coexpression = target_vs_rest.get("coexpression", {})
    coexpression = coexpression if isinstance(coexpression, dict) else {}

    pair = {
        "ligand": ligand,
        "receptor": receptor,
        "pair_file": f"stage1_{ligand}--{receptor}.json",
        "score": ppi.get("max_combined_score", "N/A"),
        "interaction": (
            "confirmed" if _is_true(ppi.get("interaction_found")) else "not found"
        ),
        "kegg": _pathway_parts(
            pair_data.get("kegg_pathways", {})
            if isinstance(pair_data.get("kegg_pathways"), dict)
            else {}
        ),
        "reactome": _pathway_parts(
            pair_data.get("reactome_pathways", {})
            if isinstance(pair_data.get("reactome_pathways"), dict)
            else {}
        ),
        "census_rr": coexpression.get("risk_ratio"),
        "census_p": coexpression.get("p_value", "N/A"),
    }
    lookup_key = (_normalize_gene(ligand), _normalize_gene(receptor))
    if lookup_key in filter_lookup:
        pair["_passed"] = filter_lookup[lookup_key]
    return pair


def _template_pairs_for_gene(
    gene: str,
    stage1_pairs: dict[str, Any],
    filter_lookup: dict[tuple[str, str], bool],
) -> list[dict[str, Any]]:
    normalized_gene = _normalize_gene(gene)
    pairs: list[dict[str, Any]] = []
    for pair_key, pair_data in stage1_pairs.items():
        if not isinstance(pair_data, dict):
            continue
        ligand, receptor = _pair_genes(pair_key, pair_data)
        if normalized_gene not in {_normalize_gene(ligand), _normalize_gene(receptor)}:
            continue
        pairs.append(_template_pair(pair_key, pair_data, filter_lookup))
    return pairs


def _candidate_row(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "gene": candidate.get("gene"),
        **{
            field: _score(candidate, field)
            for field in _SCORE_FIELDS
        },
        "classification": candidate.get("classification", "unknown"),
        "priority": candidate.get("priority", "unranked"),
        "stage3_candidate": candidate.get("stage3_candidate", False),
    }


def _normalize_template_interpretations(
    interpretations: dict[str, Any],
) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key in (
        "executive_summary_opportunities",
        "scoring_landscape",
        "stage1_filter",
        "hypotheses_overview",
        "final_recommendations",
    ):
        value = interpretations.get(key)
        if isinstance(value, str) and value.strip():
            normalized[key] = value

    for key in ("candidates", "hypotheses"):
        value = interpretations.get(key)
        if isinstance(value, dict):
            normalized[key] = value

    return normalized


def _markdown_template_context(
    report_data: dict[str, Any],
    interpretations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    interpretations = interpretations if isinstance(interpretations, dict) else {}
    interpretations = _normalize_template_interpretations(interpretations)
    raw_candidates = report_data.get("candidates", [])
    candidates = _dict_list(raw_candidates)
    selected = [candidate for candidate in candidates if candidate.get("stage3_candidate")]
    selected = selected or candidates[:5]
    stage3_genes = [
        _safe_text(candidate.get("gene"), "")
        for candidate in selected
        if candidate.get("gene")
    ]

    template_context = report_data.get("template_context", {})
    template_context = template_context if isinstance(template_context, dict) else {}
    raw_stage1_rows = template_context.get("stage1_filter_results", [])
    stage1_rows = _dict_list(raw_stage1_rows)
    stage1_pairs = template_context.get("stage1_pairs", {})
    stage1_pairs = stage1_pairs if isinstance(stage1_pairs, dict) else {}
    filter_lookup = _stage1_filter_lookup(stage1_rows)

    featured_cards: list[dict[str, Any]] = []
    for candidate in selected:
        clinical = [
            _template_drug(drug)
            for drug in _dict_list(candidate.get("clinical_drugs", []))
        ]
        preclinical = [
            _template_drug(drug)
            for drug in _dict_list(candidate.get("preclinical_drugs", []))
        ]
        if not clinical and not preclinical:
            drugs = _dict_list(candidate.get("drugs", []))
            clinical, preclinical = _split_template_drugs(drugs)
        gene = _safe_text(candidate.get("gene"), "")
        card = {
            "gene": gene,
            "rubric": _candidate_row(candidate),
            "_clinical_drugs": clinical,
            "_preclinical_compounds": preclinical,
            "_pairs": _template_pairs_for_gene(gene, stage1_pairs, filter_lookup),
        }
        candidate_interpretations = interpretations.get("candidates", {})
        candidate_interpretations = (
            candidate_interpretations
            if isinstance(candidate_interpretations, dict)
            else {}
        )
        snippets = candidate_interpretations.get(gene.upper(), {})
        snippets = snippets if isinstance(snippets, dict) else {}
        card_interpretations = {
            key: snippets[key]
            for key in ("drug_profile", "biological_context", "recommendation")
            if isinstance(snippets.get(key), str) and snippets[key].strip()
        }
        if card_interpretations:
            card["_interpretations"] = card_interpretations
        featured_cards.append(card)

    hypothesis_data = template_context.get("hypothesis_data", {})
    hypothesis_data = hypothesis_data if isinstance(hypothesis_data, dict) else {}
    hypothesis_data = dict(hypothesis_data)
    hypotheses = hypothesis_data.get("hypotheses")
    if isinstance(hypotheses, list):
        hypothesis_interpretations = interpretations.get("hypotheses", {})
        hypothesis_interpretations = (
            hypothesis_interpretations
            if isinstance(hypothesis_interpretations, dict)
            else {}
        )
        rendered_hypotheses: list[Any] = []
        for hypothesis in hypotheses:
            if not isinstance(hypothesis, dict):
                rendered_hypotheses.append(hypothesis)
                continue
            rendered_hypothesis = dict(hypothesis)
            rank = str(rendered_hypothesis.get("rank") or "")
            snippets = hypothesis_interpretations.get(rank, {})
            snippets = snippets if isinstance(snippets, dict) else {}
            implication = snippets.get("implication")
            if isinstance(implication, str) and implication.strip():
                rendered_hypothesis["_interpretation"] = implication
            rendered_hypotheses.append(rendered_hypothesis)
        hypothesis_data["hypotheses"] = rendered_hypotheses
    return {
        "disease": _safe_text(report_data.get("disease"), "unspecified disease"),
        "n_genes": len(candidates),
        "n_featured": len(stage3_genes),
        "stage3_genes": stage3_genes,
        "featured_cards": featured_cards,
        "featured_rows": [_candidate_row(candidate) for candidate in selected],
        "other_rows": [
            _candidate_row(candidate)
            for candidate in candidates
            if candidate not in selected
        ],
        "stage1_filter_results": _format_stage1_filter_results(stage1_rows),
        "hypothesis_data": hypothesis_data,
        "disease_scope": {"requires_proxy_note": False},
        "data_limitations": [],
        "novelty_opportunity_legend": NOVELTY_OPPORTUNITY_LEGEND,
        "interpretations": interpretations,
    }


def _strip_expand_markers(markdown: str) -> str:
    stripped = re.sub(r"^[ \t]*<!--\s*EXPAND:.*?-->\s*$", "", markdown, flags=re.MULTILINE)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped.strip() + "\n"


def render_report_html(report_data: dict[str, Any], markdown: str) -> str:
    disease = _safe_text(report_data.get("disease"), "unspecified disease")
    title = f"Therapeutic Target Assessment Report - {disease}"
    sources = report_data.get("sources", {})
    source_count = len(sources) if isinstance(sources, dict) else 0
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1">',
            f"  <title>{escape(title)}</title>",
            (
                "  <style>"
                "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
                "line-height:1.5;margin:2rem;max-width:1100px}"
                "pre{white-space:pre-wrap;background:#fafafa;border:1px solid #ddd;"
                "padding:1rem;overflow:auto}"
                "code{background:#f3f3f3;padding:0.1rem 0.25rem}"
                "</style>"
            ),
            "</head>",
            "<body>",
            f"  <h1>{escape(title)}</h1>",
            (
                "  <p><strong>Schema:</strong> "
                f"{escape(str(report_data.get('schema_version', 'unknown')))}"
                f" | <strong>Sources:</strong> {source_count}</p>"
            ),
            f"  <pre>{escape(markdown)}</pre>",
            "</body>",
            "</html>",
            "",
        ]
    )


def _score(candidate: dict[str, Any], field: str) -> object:
    scores = candidate.get("scores", {})
    if isinstance(scores, dict):
        return scores.get(field, 0)
    return 0


def _drug_name(entry: dict[str, Any]) -> str:
    return str(
        entry.get("drug_name")
        or entry.get("name")
        or entry.get("pref_name")
        or entry.get("molecule_pref_name")
        or entry.get("chembl_id")
        or entry.get("molecule_chembl_id")
        or ""
    ).strip()


def _resolved_drug_lookup(base: Path) -> dict[tuple[str, str], dict[str, Any]]:
    path = base / "evidence" / "resolved_drugs.json"
    payload = _load_optional_json(path, [])
    if not isinstance(payload, list):
        return {}

    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        gene = _normalize_gene(row.get("gene"))
        chembl_id = _safe_text(row.get("chembl_id"), "").upper()
        if gene and chembl_id:
            lookup[(gene, chembl_id)] = row
    return lookup


def _disease_names(row: dict[str, Any]) -> list[str]:
    diseases = row.get("diseases")
    values: list[object | None] = []
    if isinstance(diseases, list):
        for item in diseases:
            if not isinstance(item, dict):
                continue
            disease = item.get("disease")
            if isinstance(disease, dict):
                values.append(disease.get("name"))
            values.append(item.get("diseaseFromSource"))
    return _dedupe_strings(values)


def _clinical_drugs_from_opentargets(
    base: Path,
    gene: str,
    resolved_lookup: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], bool]:
    path = base / "evidence" / f"ot_{gene}.json"
    sources = [f"evidence/ot_{gene}.json"] if path.exists() else []
    if not path.exists():
        return [], sources, False

    payload = _load_optional_json(path, {})
    if not isinstance(payload, dict):
        return [], sources, False
    target_drugs = payload.get("target_drugs")
    if not isinstance(target_drugs, dict):
        return [], sources, False
    rows = target_drugs.get("rows")
    if not isinstance(rows, list):
        return [], sources, False

    drugs: list[dict[str, Any]] = []
    seen: set[str] = set()
    used_resolved_drug = False
    normalized_gene = _normalize_gene(gene)
    for row in rows:
        if not isinstance(row, dict):
            continue
        drug = row.get("drug")
        if not isinstance(drug, dict):
            continue
        chembl_id = _safe_text(drug.get("id"), "").upper()
        if not chembl_id or chembl_id in seen:
            continue
        seen.add(chembl_id)
        resolved = resolved_lookup.get((normalized_gene, chembl_id), {})
        used_resolved_drug = used_resolved_drug or bool(resolved)
        drugs.append(
            {
                "name": _safe_text(
                    resolved.get("resolved_name") or drug.get("name"),
                    chembl_id,
                ),
                "chembl_id": chembl_id,
                "phase": row.get("maxClinicalStage")
                or drug.get("maximumClinicalStage"),
                "first_approval": resolved.get("first_approval"),
                "mechanism_of_action": resolved.get("mechanism_of_action"),
                "indications": _disease_names(row),
                "source": "opentargets",
            }
        )
    return drugs, sources, used_resolved_drug


def _drug_records_from_stage3(stage3: dict[str, Any]) -> list[dict[str, Any]]:
    containers: list[dict[str, Any]] = [stage3]
    chembl = stage3.get("chembl")
    if isinstance(chembl, dict):
        containers.append(chembl)

    raw_records: list[dict[str, Any]] = []
    for container in containers:
        for key in (
            "matched_drugs",
            "chembl_drugs",
            "preclinical_compounds",
            "chembl_records",
        ):
            value = container.get(key)
            if isinstance(value, dict):
                value = value.get("matched_drugs", [])
            if isinstance(value, list):
                raw_records.extend(item for item in value if isinstance(item, dict))

    drugs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in raw_records:
        name = _drug_name(record)
        if not name or name in seen:
            continue
        seen.add(name)
        indications = record.get("indications")
        if not isinstance(indications, list):
            indications = [record.get("indication")] if record.get("indication") else []
        drugs.append(
            {
                "name": name,
                "chembl_id": str(
                    record.get("chembl_id")
                    or record.get("molecule_chembl_id")
                    or ""
                ).strip(),
                "phase": record.get("max_phase"),
                "first_approval": record.get("first_approval"),
                "mechanism_of_action": record.get("mechanism_of_action"),
                "indications": _dedupe_strings(indications),
                "source": "chembl",
            }
        )
    return drugs


def _drop_preclinical_duplicates(
    clinical_drugs: list[dict[str, Any]],
    preclinical_drugs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    clinical_chembl_ids = {
        _safe_text(drug.get("chembl_id"), "").upper()
        for drug in clinical_drugs
        if _safe_text(drug.get("chembl_id"), "")
    }
    if not clinical_chembl_ids:
        return preclinical_drugs
    return [
        drug
        for drug in preclinical_drugs
        if _safe_text(drug.get("chembl_id"), "").upper() not in clinical_chembl_ids
    ]


def build_report_data(data_dir: str, disease: str) -> dict[str, Any]:
    base = Path(data_dir).expanduser().resolve()
    issues = _missing_required_evidence(base)
    if issues:
        return _invalid_report_data(base, disease, issues)

    paths = _required_evidence_paths(base)
    try:
        assessment = _load_json(paths["assessment_results"])
    except (json.JSONDecodeError, OSError) as exc:
        return _invalid_report_data(
            base,
            disease,
            [
                _invalid_required_json_issue(
                    base,
                    "assessment_results",
                    paths["assessment_results"],
                    exc,
                )
            ],
        )
    try:
        hypothesis = _load_json(paths["hypothesis_report"])
    except (json.JSONDecodeError, OSError) as exc:
        return _invalid_report_data(
            base,
            disease,
            [
                _invalid_required_json_issue(
                    base,
                    "hypothesis_report",
                    paths["hypothesis_report"],
                    exc,
                )
            ],
        )
    if not isinstance(assessment, dict):
        return _invalid_report_data(
            base,
            disease,
            [
                {
                    "code": "INVALID_ASSESSMENT_SHAPE",
                    "severity": "critical",
                    "message": "assessment_results.json must be a JSON object",
                    "path": "evidence/assessment_results.json",
                }
            ],
        )
    if not isinstance(hypothesis, dict):
        return _invalid_report_data(
            base,
            disease,
            [
                {
                    "code": "INVALID_HYPOTHESIS_SHAPE",
                    "severity": "critical",
                    "message": "hypothesis_report.json must be a JSON object",
                    "path": "evidence/hypothesis_report.json",
                }
            ],
        )
    rows, assessment_issues = _assessment_rows(assessment)
    if assessment_issues:
        return _invalid_report_data(base, disease, assessment_issues)
    selected_genes = _stage3_genes(assessment, rows)
    resolved_lookup = _resolved_drug_lookup(base)
    resolved_path = base / "evidence" / "resolved_drugs.json"
    stage1_filter_results = _load_stage1_filter_results(base)
    stage1_pairs = _load_optional_dict(base / "evidence" / "stage1_evidence.json")

    candidates: list[dict[str, Any]] = []
    for row in sorted(
        rows,
        key=lambda item: (
            -int(item.get("combined_total", item.get("validated_score", 0)) or 0),
            _normalize_gene(item.get("gene")),
        ),
    ):
        gene = _normalize_gene(row.get("gene"))
        if not gene:
            continue
        stage3_path = base / "evidence" / f"stage3_{gene}.json"
        sources = ["evidence/assessment_results.json"]
        (
            clinical_drugs,
            clinical_sources,
            used_resolved_drug,
        ) = _clinical_drugs_from_opentargets(
            base,
            gene,
            resolved_lookup,
        )
        for source in clinical_sources:
            if source not in sources:
                sources.append(source)
        if used_resolved_drug and resolved_path.exists():
            resolved_source = "evidence/resolved_drugs.json"
            if resolved_source not in sources:
                sources.append(resolved_source)
        preclinical_drugs: list[dict[str, Any]] = []
        if stage3_path.exists():
            sources.append(f"evidence/stage3_{gene}.json")
            stage3_payload = _load_optional_json(stage3_path, {})
            if isinstance(stage3_payload, dict):
                preclinical_drugs = _drug_records_from_stage3(stage3_payload)
        preclinical_drugs = _drop_preclinical_duplicates(
            clinical_drugs,
            preclinical_drugs,
        )
        drugs = clinical_drugs + preclinical_drugs
        candidates.append(
            {
                "gene": gene,
                "classification": row.get("classification", "unknown"),
                "priority": row.get("priority", "unranked"),
                "stage3_candidate": gene in selected_genes,
                "scores": {field: row.get(field, 0) for field in _SCORE_FIELDS},
                "clinical_drug_count": len(clinical_drugs),
                "preclinical_drug_count": len(preclinical_drugs),
                "drug_count": len(drugs),
                "clinical_drugs": clinical_drugs,
                "preclinical_drugs": preclinical_drugs,
                "drugs": drugs,
                "sources": sources,
            }
        )

    hypotheses = hypothesis.get("hypotheses")
    if not isinstance(hypotheses, list):
        hypotheses = []

    sections = {
        "executive_summary": {
            "title": "Executive Summary",
            "sources": ["evidence/assessment_results.json"],
        },
        "druggability_matrix": {
            "title": "Target Druggability Matrix",
            "sources": ["evidence/assessment_results.json"],
        },
        "candidate_deep_dives": {
            "title": "Candidate Deep Dives",
            "sources": sorted(
                {
                    source
                    for candidate in candidates
                    for source in candidate["sources"]
                }
            ),
        },
        "hypotheses": {
            "title": "Mechanistic Hypotheses",
            "sources": ["evidence/hypothesis_report.json"],
        },
    }

    cited_sources: set[str] = set()
    for section in sections.values():
        section_sources = section.get("sources", [])
        if isinstance(section_sources, list):
            cited_sources.update(
                source for source in section_sources if isinstance(source, str)
            )
    cited_sources.update(
        source
        for candidate in candidates
        for source in candidate["sources"]
        if isinstance(source, str)
    )
    cited_sources.update(str(path.relative_to(base)) for path in paths.values())
    for optional_source in (
        "evidence/stage1_filter_results.json",
        "evidence/stage1_filter_results.csv",
        "evidence/stage1_evidence.json",
    ):
        if (base / optional_source).exists():
            cited_sources.add(optional_source)

    return {
        "schema_version": "drug_target.report_data.v1",
        "valid": True,
        "created_at": _utc_now(),
        "data_dir": str(base),
        "disease": disease or assessment.get("disease") or hypothesis.get("disease") or "",
        "sections": sections,
        "candidates": candidates,
        "hypotheses": hypotheses,
        "sources": {
            source: {"sha256": _sha256_path(base / source)}
            for source in sorted(cited_sources)
            if (base / source).exists()
        },
        "template_context": {
            "stage1_filter_results": stage1_filter_results,
            "stage1_pairs": stage1_pairs,
            "hypothesis_data": hypothesis,
        },
        "issues": [],
    }


def validate_report_data(report_data: dict[str, Any]) -> list[dict[str, Any]]:
    issues = list(report_data.get("issues") or [])
    if report_data.get("schema_version") != "drug_target.report_data.v1":
        issues.append(
            {
                "code": "INVALID_SCHEMA_VERSION",
                "severity": "critical",
                "message": "report_data schema_version must be drug_target.report_data.v1",
            }
        )
    if not report_data.get("candidates"):
        issues.append(
            {
                "code": "NO_CANDIDATES",
                "severity": "critical",
                "message": "report_data must include at least one candidate",
            }
        )
    if not report_data.get("sections"):
        issues.append(
            {
                "code": "NO_SECTIONS",
                "severity": "critical",
                "message": "report_data must include sections metadata",
            }
        )
    return issues


def _target_assessment_inputs(
    report_data: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    rubric_by_gene: dict[str, dict[str, Any]] = {}
    stage3_data: dict[str, dict[str, Any]] = {}
    stage3_genes: list[str] = []

    for candidate in _dict_list(report_data.get("candidates", [])):
        gene = _normalize_gene(candidate.get("gene"))
        if not gene:
            continue

        scores = candidate.get("scores", {})
        scores = scores if isinstance(scores, dict) else {}
        rubric_by_gene[gene] = {
            **{field: scores.get(field, 0) for field in _SCORE_FIELDS},
            "classification": candidate.get("classification", "unknown"),
            "priority": candidate.get("priority", "unranked"),
            "stage3_candidate": candidate.get("stage3_candidate", False),
        }
        stage3_data[gene] = {
            "drugs": _dict_list(candidate.get("drugs", [])),
            "safety_summary": candidate.get("safety_summary")
            or "No safety data available",
        }
        if candidate.get("stage3_candidate"):
            stage3_genes.append(gene)

    return rubric_by_gene, stage3_data, stage3_genes


def _persist_target_assessment_if_applicable(
    base: Path,
    report_data: dict[str, Any],
) -> list[dict[str, Any]]:
    if not (base / "lr_candidates.json").exists():
        return []

    try:
        from src.agents.drug_target.tools.assessment_output import (
            validate_target_assessment_file,
        )
        from src.agents.drug_target.tools.stage_logic import (
            _prebuild_target_assessment,
        )

        rubric_by_gene, stage3_data, stage3_genes = _target_assessment_inputs(
            report_data
        )
        template_context = report_data.get("template_context", {})
        template_context = template_context if isinstance(template_context, dict) else {}
        stage1_data = template_context.get("stage1_pairs", {})
        stage1_data = stage1_data if isinstance(stage1_data, dict) else {}

        _prebuild_target_assessment(
            base,
            base / "evidence",
            str(report_data.get("disease") or ""),
            rubric_by_gene,
            stage3_data,
            stage1_data,
            stage3_genes,
        )
        validation = validate_target_assessment_file(base)
    except Exception as exc:  # pragma: no cover - defensive envelope
        return [
            {
                "code": "TARGET_ASSESSMENT_WRITE_FAILED",
                "severity": "critical",
                "message": f"target_assessment.json generation failed: {exc}",
                "path": "target_assessment.json",
            }
        ]

    if validation.get("valid"):
        return []
    return [
        {
            "code": "TARGET_ASSESSMENT_INVALID",
            "severity": "critical",
            "message": "target_assessment.json failed contract validation",
            "path": "target_assessment.json",
            "errors": validation.get("errors", []),
        }
    ]


def _artifact_validation(base: Path, report_data: dict[str, Any]) -> dict[str, Any]:
    issues = validate_report_data(report_data)
    artifacts: dict[str, dict[str, Any]] = {}
    required_artifacts = [
        "report_data.json",
        "drug.md",
        "drug_report.html",
    ]
    if (base / "lr_candidates.json").exists():
        required_artifacts.append("target_assessment.json")
    for name in required_artifacts:
        path = base / name
        metadata: dict[str, Any] = {
            "path": name,
            "exists": path.exists(),
        }
        if path.exists():
            metadata["size_bytes"] = path.stat().st_size
            metadata["sha256"] = _sha256_path(path)
        else:
            issues.append(
                {
                    "code": "MISSING_REQUIRED_ARTIFACT",
                    "severity": "critical",
                    "message": f"Required report artifact is missing: {name}",
                    "path": name,
                }
            )
        artifacts[name] = metadata

    for name in ("drug.md", "drug_report.html"):
        path = base / name
        if not path.exists():
            continue
        if "EXPAND" in path.read_text(encoding="utf-8"):
            issues.append(
                {
                    "code": "UNEXPANDED_PLACEHOLDER",
                    "severity": "critical",
                    "message": f"{name} must not contain EXPAND markers",
                    "path": name,
                }
            )

    return {
        "schema_version": "drug_target.report_validation.v1",
        "valid": not issues,
        "created_at": _utc_now(),
        "data_dir": str(base),
        "artifacts": artifacts,
        "issues": issues,
    }


def _add_self_validation_artifact(validation: dict[str, Any]) -> dict[str, Any]:
    artifacts = validation.setdefault("artifacts", {})
    if isinstance(artifacts, dict):
        artifacts["report_validation.json"] = {
            "path": "report_validation.json",
            "exists": True,
        }
    return validation


def render_report_markdown(
    report_data: dict[str, Any],
    interpretations: dict[str, Any] | None = None,
) -> str:
    template_str = _markdown_template_path().read_text(encoding="utf-8")
    env = Environment(
        loader=BaseLoader(),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    rendered = env.from_string(template_str).render(
        **_markdown_template_context(report_data, interpretations=interpretations)
    )
    return _strip_expand_markers(rendered)


async def finalize_report_mvp(state: dict, config: RunnableConfig) -> dict:
    base = Path(state["data_dir"]).expanduser().resolve()
    report_data = build_report_data(str(base), str(state.get("disease") or ""))
    _write_json(base / "report_data.json", report_data)

    issues = validate_report_data(report_data)
    if issues:
        validation = _artifact_validation(base, report_data)
        validation["valid"] = False
        validation["issues"] = issues
        _add_self_validation_artifact(validation)
        _write_json(base / "report_validation.json", validation)
        reason = issues[0].get("code", "UNKNOWN")
        return {
            "report_finalization_error": (
                f"deterministic_report_validation_failed: {reason}"
            ),
            "evidence_truncated": False,
        }

    interpretations: dict[str, Any] | None = None
    from src.agents.drug_target.report_interpretations import (
        generate_report_interpretations,
        interpretation_provider_from_config,
        report_interpretations_enabled,
        resolve_interpretation_max_attempts,
    )

    if report_interpretations_enabled(config):
        provider = interpretation_provider_from_config(config)
        if provider is not None:
            payload, interpretations = await generate_report_interpretations(
                report_data,
                provider,
                max_attempts=resolve_interpretation_max_attempts(config),
            )
        else:
            payload, interpretations = {}, {}
        _write_json(base / "report_interpretations.json", payload)

    markdown = render_report_markdown(report_data, interpretations=interpretations)
    (base / "drug.md").write_text(markdown, encoding="utf-8")
    (base / "drug_report.html").write_text(
        render_report_html(report_data, markdown),
        encoding="utf-8",
    )
    target_assessment_issues = _persist_target_assessment_if_applicable(
        base,
        report_data,
    )

    validation = _artifact_validation(base, report_data)
    if target_assessment_issues:
        validation["valid"] = False
        validation["issues"].extend(target_assessment_issues)
    _add_self_validation_artifact(validation)
    _write_json(base / "report_validation.json", validation)
    if not validation["valid"]:
        reason = validation["issues"][0].get("code", "UNKNOWN")
        return {
            "report_finalization_error": (
                f"deterministic_report_validation_failed: {reason}"
            ),
            "evidence_truncated": False,
        }

    return {
        "report_finalization_error": None,
        "evidence_truncated": False,
    }

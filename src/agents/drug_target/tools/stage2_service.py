"""Shared Stage 2 orchestration helpers for drug target evidence collection."""

from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).resolve().parents[4] / "skills"
_MODULE_CACHE: dict[tuple[str, str], Any] = {}


def _load_skill_module(skill_name: str, script_name: str, module_name: str) -> Any:
    cache_key = (skill_name, script_name)
    if cache_key in _MODULE_CACHE:
        return _MODULE_CACHE[cache_key]

    script_path = _SKILLS_DIR / skill_name / "scripts" / script_name
    if not script_path.exists():
        raise FileNotFoundError(f"Skill script not found: {script_path}")

    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec for {script_path}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _MODULE_CACHE[cache_key] = mod
    return mod


def _try_load_ot_module() -> tuple[Any, str]:
    try:
        mod = _load_skill_module(
            "opentargets-database", "opentargets_parquet.py", "opentargets_parquet"
        )
        if mod.is_available():
            return mod, "parquet"
    except Exception as exc:
        logger.debug("OpenTargets parquet unavailable: %s", exc)

    mod = _load_skill_module(
        "opentargets-database", "query_opentargets.py", "query_opentargets"
    )
    return mod, "api"


def _try_load_gwas_module() -> tuple[Any, str]:
    try:
        mod = _load_skill_module("gwas-database", "gwas_parquet.py", "gwas_parquet")
        if mod.is_available():
            return mod, "parquet"
    except Exception as exc:
        logger.debug("GWAS parquet unavailable: %s", exc)

    mod = _load_skill_module("gwas-database", "gwas_api.py", "gwas_api")
    return mod, "api"


def normalize_gene_symbols(gene_symbols: list[str] | tuple[str, ...] | str) -> list[str]:
    """Normalize gene symbols to sorted unique uppercase strings."""
    if isinstance(gene_symbols, str):
        raw_items = [part.strip() for part in gene_symbols.split(",")]
    else:
        raw_items = [str(item).strip() for item in gene_symbols]

    normalized = {item.upper() for item in raw_items if item}
    return sorted(normalized)


def _extract_pairs(lr_data: dict[str, Any]) -> list[dict[str, Any]]:
    return lr_data.get(
        "pairs",
        lr_data.get("lr_pairs", lr_data.get("candidates", lr_data.get("candidate_pairs", []))),
    )


def load_stage2_inputs(data_dir: str | Path) -> dict[str, Any]:
    """Load Stage 2 gene panel inputs from a workspace directory."""
    base = Path(data_dir).expanduser().resolve()
    lr_path = base / "lr_candidates.json"
    if not lr_path.exists():
        raise FileNotFoundError(f"lr_candidates.json not found at {lr_path}")

    lr_data = json.loads(lr_path.read_text(encoding="utf-8"))
    pairs = _extract_pairs(lr_data)

    genes: set[str] = set()
    for pair in pairs:
        ligand = str(pair.get("ligand", pair.get("source", ""))).strip()
        receptor = str(pair.get("receptor", pair.get("target", ""))).strip()
        if ligand:
            genes.add(ligand.upper())
        if receptor:
            genes.add(receptor.upper())

    selected_top3_genes: set[str] = set()
    top3_path = base / "selected_top3_lr.json"
    if top3_path.exists():
        top3_data = json.loads(top3_path.read_text(encoding="utf-8"))
        top3_pairs = (
            top3_data
            if isinstance(top3_data, list)
            else top3_data.get(
                "selected_pairs",
                top3_data.get("pairs", top3_data.get("selected", [])),
            )
        )
        for pair in top3_pairs:
            ligand = str(pair.get("ligand", pair.get("source", ""))).strip()
            receptor = str(pair.get("receptor", pair.get("target", ""))).strip()
            if ligand:
                selected_top3_genes.add(ligand.upper())
            if receptor:
                selected_top3_genes.add(receptor.upper())

    return {
        "data_dir": str(base),
        "disease": str(lr_data.get("disease", lr_data.get("disease_context", ""))),
        "pairs": pairs,
        "gene_symbols": sorted(genes),
        "selected_top3_genes": sorted(selected_top3_genes),
    }


def build_gene_manifest(
    gene_symbols: list[str] | tuple[str, ...] | str,
    selected_top3_genes: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Build the canonical gene manifest artifact."""
    selected = {str(g).strip().upper() for g in (selected_top3_genes or []) if str(g).strip()}
    return [
        {"symbol": gene, "is_selected_top3": gene in selected}
        for gene in normalize_gene_symbols(gene_symbols)
    ]


def _read_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_cached_stage2_bundle(
    gene_symbols: list[str] | tuple[str, ...] | str,
    disease: str,
    *,
    selected_top3_genes: list[str] | tuple[str, ...] | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any] | None:
    """Load a complete Stage 2 bundle from workspace evidence files if they match exactly."""
    if not data_dir:
        return None

    genes = normalize_gene_symbols(gene_symbols)
    evidence_dir = Path(data_dir).expanduser().resolve() / "evidence"
    if not evidence_dir.is_dir():
        return None

    required_paths = [
        evidence_dir / "stage2_evidence.json",
        evidence_dir / "known_drugs.json",
        evidence_dir / "gene_manifest.json",
        *[evidence_dir / f"ot_{gene}.json" for gene in genes],
    ]
    if any(not path.exists() for path in required_paths):
        return None

    try:
        stage2_evidence = _read_json_file(evidence_dir / "stage2_evidence.json")
        known_drugs = _read_json_file(evidence_dir / "known_drugs.json")
        gene_manifest = _read_json_file(evidence_dir / "gene_manifest.json")
        ot_payloads = {
            gene: _read_json_file(evidence_dir / f"ot_{gene}.json")
            for gene in genes
        }
    except Exception as exc:
        logger.debug("Stage 2 workspace cache parse failed: %s", exc)
        return None

    expected_manifest = build_gene_manifest(genes, selected_top3_genes)
    if gene_manifest != expected_manifest:
        return None
    if not isinstance(stage2_evidence, dict) or sorted(stage2_evidence) != genes:
        return None
    if not isinstance(known_drugs, dict) or known_drugs.get("disease") != disease:
        return None

    for gene in genes:
        payload = stage2_evidence.get(gene)
        if not isinstance(payload, dict):
            return None

        ot_payload = payload.get("opentargets")
        gwas_payload = payload.get("gwas")
        if not isinstance(ot_payload, dict) or not isinstance(gwas_payload, dict):
            return None
        if ot_payload.get("gene_symbol") != gene or gwas_payload.get("gene_symbol") != gene:
            return None
        if ot_payload.get("disease") != disease or gwas_payload.get("disease") != disease:
            return None
        if ot_payloads[gene] != ot_payload:
            return None

    logger.info("Stage 2 workspace cache hit for %s (%d genes)", disease, len(genes))
    return {
        "disease": disease,
        "gene_symbols": genes,
        "stage2_evidence": stage2_evidence,
        "known_drugs": known_drugs,
        "gene_manifest": gene_manifest,
        "source_modes": {
            "opentargets": "cache",
            "gwas": "cache",
        },
    }


def _build_ot_disease_context(mod: Any, disease: str) -> dict[str, Any]:
    hits = mod.search_entities(disease, entity_types=["disease"])
    efo_id = hits[0]["id"] if hits else None
    return {
        "disease": disease,
        "hits": hits,
        "efo_id": efo_id,
    }


def _build_gwas_disease_context(mod: Any, disease: str) -> dict[str, Any]:
    if hasattr(mod, "build_disease_context"):
        return mod.build_disease_context(disease)

    traits = mod.search_efo_traits(disease)
    synonyms = {"cancer": "carcinoma", "carcinoma": "cancer"}
    disease_lower = disease.lower()
    for old, new in synonyms.items():
        if old in disease_lower:
            alt = disease_lower.replace(old, new)
            alt_traits = mod.search_efo_traits(alt)
            seen_ids = {t.get("shortForm") for t in traits}
            for trait in alt_traits:
                if trait.get("shortForm") not in seen_ids and "error" not in trait:
                    traits.append(trait)

    traits = traits[:5]
    all_trait_assocs: list[dict[str, Any]] = []
    seen_rsids: set[str] = set()
    for trait in traits:
        if "error" in trait:
            continue
        efo_id = trait.get("shortForm", "")
        if not efo_id:
            continue
        for assoc in mod.get_trait_associations(efo_id, max_results=500):
            rsid = assoc.get("rsId", "")
            if rsid and rsid in seen_rsids:
                continue
            if rsid:
                seen_rsids.add(rsid)
            all_trait_assocs.append(assoc)

    return {
        "disease": disease,
        "efo_traits": traits,
        "trait_associations": all_trait_assocs,
    }


def query_opentargets_target_data(
    gene_symbol: str,
    disease: str,
    *,
    mod: Any | None = None,
    disease_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the canonical OpenTargets result payload for one gene."""
    result = {
        "gene_symbol": gene_symbol,
        "disease": disease,
        "executed": False,
        "ensembl_id": None,
        "target_info": {},
        "disease_evidence": [],
        "associations": [],
        "errors": [],
    }

    try:
        mod = mod or _try_load_ot_module()[0]
        disease_context = disease_context or _build_ot_disease_context(mod, disease)
        hits = mod.search_entities(gene_symbol, entity_types=["target"])
        if not hits:
            result["errors"].append(f"No OpenTargets target found for {gene_symbol}")
            return result

        ensembl_id = hits[0]["id"]
        result["ensembl_id"] = ensembl_id

        if hasattr(mod, "get_target_bundle"):
            bundle = mod.get_target_bundle(
                ensembl_id,
                efo_id=disease_context.get("efo_id"),
                min_score=0.1,
            )
            result["target_info"] = bundle.get("target_info", {})
            result["disease_evidence"] = bundle.get("disease_evidence", [])
            result["associations"] = bundle.get("associations", [])
        else:
            result["target_info"] = mod.get_target_info(ensembl_id, include_diseases=True)
            if disease_context.get("efo_id"):
                result["disease_evidence"] = mod.get_target_disease_evidence(
                    ensembl_id,
                    disease_context["efo_id"],
                )
            result["associations"] = mod.get_target_associations(ensembl_id, min_score=0.1)

        # Truncate large payloads to prevent token bloat
        if len(result["associations"]) > 20:
            result["associations"] = sorted(
                result["associations"], key=lambda x: x.get("score", 0), reverse=True
            )[:20]
            result["associations_truncated"] = True
        if len(result["disease_evidence"]) > 30:
            result["disease_evidence"] = result["disease_evidence"][:30]
            result["disease_evidence_truncated"] = True

        if disease_context.get("efo_id"):
            result["efo_id"] = disease_context["efo_id"]
        result["executed"] = True
    except Exception as exc:
        result["errors"].append(f"OpenTargets query failed: {exc}")

    return result


def query_opentargets_known_drugs_data(
    disease: str,
    *,
    mod: Any | None = None,
    disease_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the canonical known-drugs payload for one disease."""
    result = {
        "disease": disease,
        "executed": False,
        "efo_id": None,
        "drugs": {},
        "errors": [],
    }

    try:
        mod = mod or _try_load_ot_module()[0]
        disease_context = disease_context or _build_ot_disease_context(mod, disease)
        efo_id = disease_context.get("efo_id")
        if not efo_id:
            result["errors"].append(f"No disease found for '{disease}'")
            return result

        result["efo_id"] = efo_id
        result["drugs"] = mod.get_known_drugs_for_disease(efo_id)

        # Truncate large drug lists to prevent token bloat
        drugs = result["drugs"]
        if isinstance(drugs, dict):
            for target, drug_list in drugs.items():
                if isinstance(drug_list, list) and len(drug_list) > 10:
                    drugs[target] = drug_list[:10]
            result["drugs_truncated"] = True

        result["executed"] = True
    except Exception as exc:
        result["errors"].append(f"OpenTargets drug query failed: {exc}")

    return result


def _unavailable_opentargets_result(
    gene_symbol: str,
    disease: str,
    error_message: str,
) -> dict[str, Any]:
    return {
        "gene_symbol": gene_symbol,
        "disease": disease,
        "executed": False,
        "ensembl_id": None,
        "target_info": {},
        "disease_evidence": [],
        "associations": [],
        "errors": [error_message],
    }


def _unavailable_known_drugs_result(
    disease: str,
    error_message: str,
) -> dict[str, Any]:
    return {
        "disease": disease,
        "executed": False,
        "efo_id": None,
        "drugs": {},
        "errors": [error_message],
    }


def _unavailable_gwas_result(
    gene_symbol: str,
    disease: str,
    error_message: str,
) -> dict[str, Any]:
    return {
        "gene_symbol": gene_symbol,
        "disease": disease,
        "executed": False,
        "efo_traits": [],
        "trait_associations": [],
        "gene_associations": [],
        "errors": [error_message],
    }


def query_gwas_gene_trait_data(
    gene_symbol: str,
    disease: str,
    *,
    mod: Any | None = None,
    disease_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the canonical GWAS result payload for one gene."""
    result = {
        "gene_symbol": gene_symbol,
        "disease": disease,
        "executed": False,
        "efo_traits": [],
        "trait_associations": [],
        "gene_associations": [],
        "errors": [],
    }

    try:
        mod = mod or _try_load_gwas_module()[0]
        disease_context = disease_context or _build_gwas_disease_context(mod, disease)

        if hasattr(mod, "query_gene_trait_with_context"):
            result = mod.query_gene_trait_with_context(
                gene_symbol,
                disease,
                disease_context=disease_context,
            )
        else:
            result["efo_traits"] = disease_context.get("efo_traits", [])[:5]
            result["trait_associations"] = disease_context.get("trait_associations", [])
            result["gene_associations"] = mod.get_gene_associations(gene_symbol)

            trait_assocs = result["trait_associations"]
            gene_assocs = result["gene_associations"]
            gene_upper = gene_symbol.upper()
            gene_in_trait = [
                assoc
                for assoc in trait_assocs
                if gene_upper in [g.upper() for g in assoc.get("genes", [])]
            ]
            trait_rsids = {assoc["rsId"] for assoc in trait_assocs if assoc.get("rsId")}
            gene_snps_in_disease = [
                assoc for assoc in gene_assocs if assoc.get("rsId") in trait_rsids
            ]
            result["disease_specific_hits"] = {
                "gene_in_trait_associations": gene_in_trait,
                "gene_snps_in_disease": gene_snps_in_disease,
                "n_gene_in_trait": len(gene_in_trait),
                "n_gene_snps_in_disease": len(gene_snps_in_disease),
            }
            result["executed"] = True

        # Truncate large GWAS payloads to prevent token bloat
        if len(result["gene_associations"]) > 50:
            result["gene_associations"] = result["gene_associations"][:50]
            result["gene_associations_truncated"] = True
        if len(result["trait_associations"]) > 100:
            result["trait_associations"] = result["trait_associations"][:100]
            result["trait_associations_truncated"] = True

    except Exception as exc:
        result["errors"].append(f"GWAS query failed: {exc}")

    return result


def build_stage2_gene_panel(
    gene_symbols: list[str] | tuple[str, ...] | str,
    disease: str,
    *,
    selected_top3_genes: list[str] | tuple[str, ...] | None = None,
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Build the canonical Stage 2 result bundle for a disease/gene panel."""
    genes = normalize_gene_symbols(gene_symbols)
    cached = _load_cached_stage2_bundle(
        genes,
        disease,
        selected_top3_genes=selected_top3_genes,
        data_dir=data_dir,
    )
    if cached is not None:
        return cached

    ot_mod = None
    ot_disease_context = None
    ot_source = "unavailable"
    ot_error = None
    try:
        ot_mod, ot_source = _try_load_ot_module()
        ot_disease_context = _build_ot_disease_context(ot_mod, disease)
    except Exception as exc:
        ot_error = f"OpenTargets setup failed: {exc}"

    gwas_mod = None
    gwas_disease_context = None
    gwas_source = "unavailable"
    gwas_error = None
    try:
        gwas_mod, gwas_source = _try_load_gwas_module()
        gwas_disease_context = _build_gwas_disease_context(gwas_mod, disease)
    except Exception as exc:
        gwas_error = f"GWAS setup failed: {exc}"

    stage2_evidence: dict[str, dict[str, Any]] = {}
    for gene in genes:
        stage2_evidence[gene] = {
            "opentargets": (
                query_opentargets_target_data(
                    gene,
                    disease,
                    mod=ot_mod,
                    disease_context=ot_disease_context,
                )
                if ot_error is None
                else _unavailable_opentargets_result(gene, disease, ot_error)
            ),
            "gwas": (
                query_gwas_gene_trait_data(
                    gene,
                    disease,
                    mod=gwas_mod,
                    disease_context=gwas_disease_context,
                )
                if gwas_error is None
                else _unavailable_gwas_result(gene, disease, gwas_error)
            ),
        }

    return {
        "disease": disease,
        "gene_symbols": genes,
        "stage2_evidence": stage2_evidence,
        "known_drugs": (
            query_opentargets_known_drugs_data(
                disease,
                mod=ot_mod,
                disease_context=ot_disease_context,
            )
            if ot_error is None
            else _unavailable_known_drugs_result(disease, ot_error)
        ),
        "gene_manifest": build_gene_manifest(genes, selected_top3_genes),
        "source_modes": {
            "opentargets": ot_source,
            "gwas": gwas_source,
        },
    }


def summarize_stage2_bundle(result_bundle: dict[str, Any]) -> dict[str, Any]:
    """Create a compact summary of a Stage 2 bundle for tool output.

    Returns key stats per gene instead of the full payloads, keeping
    ToolMessage size small enough to avoid checkpoint bloat.
    """
    stage2_evidence = result_bundle.get("stage2_evidence", {})
    gene_summaries: dict[str, dict[str, Any]] = {}

    for gene, evidence in stage2_evidence.items():
        ot = evidence.get("opentargets", {})
        gwas = evidence.get("gwas", {})

        gene_summaries[gene] = {
            "has_ensembl_id": bool(ot.get("ensembl_id")),
            "ot_executed": ot.get("executed", False),
            "ot_disease_evidence_count": len(ot.get("disease_evidence", [])),
            "ot_associations_count": len(ot.get("associations", [])),
            "ot_errors": ot.get("errors", []),
            "gwas_executed": gwas.get("executed", False),
            "gwas_trait_associations_count": len(gwas.get("trait_associations", [])),
            "gwas_gene_associations_count": len(gwas.get("gene_associations", [])),
            "gwas_errors": gwas.get("errors", []),
        }

    known_drugs = result_bundle.get("known_drugs", {})
    drugs_payload = known_drugs.get("drugs", {})
    if isinstance(drugs_payload, dict):
        n_drugs = sum(len(v) if isinstance(v, list) else 1 for v in drugs_payload.values())
    elif isinstance(drugs_payload, list):
        n_drugs = len(drugs_payload)
    else:
        n_drugs = 0

    return {
        "disease": result_bundle.get("disease"),
        "gene_count": len(result_bundle.get("gene_symbols", [])),
        "gene_symbols": result_bundle.get("gene_symbols", []),
        "gene_summaries": gene_summaries,
        "known_drugs_count": n_drugs,
        "known_drugs_executed": known_drugs.get("executed", False),
        "source_modes": result_bundle.get("source_modes", {}),
        "gene_manifest": result_bundle.get("gene_manifest", []),
        "note": (
            "Full evidence data saved to evidence/ directory. "
            "Use load_evidence_files() to read detailed per-gene payloads."
        ),
    }


def write_stage2_artifacts(result_bundle: dict[str, Any], evidence_dir: str | Path) -> list[Path]:
    """Write canonical Stage 2 artifacts for downstream scripts and agents."""
    out_dir = Path(evidence_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written_paths: list[Path] = []
    stage2_evidence = result_bundle.get("stage2_evidence", {})

    def _write_json(path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        written_paths.append(path)

    _write_json(out_dir / "stage2_evidence.json", stage2_evidence)
    _write_json(out_dir / "known_drugs.json", result_bundle.get("known_drugs", {}))
    _write_json(out_dir / "gene_manifest.json", result_bundle.get("gene_manifest", []))

    for gene in result_bundle.get("gene_symbols", []):
        ot_payload = stage2_evidence.get(gene, {}).get("opentargets", {})
        _write_json(out_dir / f"ot_{gene}.json", ot_payload)

    return written_paths


__all__ = [
    "build_gene_manifest",
    "build_stage2_gene_panel",
    "load_stage2_inputs",
    "normalize_gene_symbols",
    "query_gwas_gene_trait_data",
    "query_opentargets_known_drugs_data",
    "query_opentargets_target_data",
    "summarize_stage2_bundle",
    "write_stage2_artifacts",
]

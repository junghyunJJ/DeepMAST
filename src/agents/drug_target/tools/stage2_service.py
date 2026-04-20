"""Shared Stage 2 orchestration helpers for drug target evidence collection."""

from __future__ import annotations

import json
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

from src.agents.drug_target.tools._skill_loader import load_skill_module as _load_skill_module

logger = logging.getLogger(__name__)


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


def extract_lr_pairs(lr_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract L-R pairs from lr_candidates.json data using the canonical 4-key fallback chain."""
    return lr_data.get(
        "pairs",
        lr_data.get("lr_pairs", lr_data.get("candidates", lr_data.get("candidate_pairs", []))),
    )


# Backward-compat alias
_extract_pairs = extract_lr_pairs


def load_stage2_inputs(data_dir: str | Path) -> dict[str, Any]:
    """Load Stage 2 gene panel inputs from a workspace directory."""
    base = Path(data_dir).expanduser().resolve()
    lr_path = base / "lr_candidates.json"
    if not lr_path.exists():
        raise FileNotFoundError(f"lr_candidates.json not found at {lr_path}")

    lr_data = json.loads(lr_path.read_text(encoding="utf-8"))
    pairs = extract_lr_pairs(lr_data)

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
    # Compare only gene keys (skip metadata keys like _disease)
    evidence_keys = sorted(k for k in stage2_evidence if not k.startswith("_"))
    if not isinstance(stage2_evidence, dict) or evidence_keys != genes:
        return None
    if not isinstance(known_drugs, dict) or known_drugs.get("disease") != disease:
        return None

    for gene in genes:
        payload = stage2_evidence.get(gene)
        if not isinstance(payload, dict):
            return None

        ot_payload = payload.get("opentargets")
        gwas_payload = payload.get("gwas")
        vep_payload = payload.get("vep")
        if not isinstance(ot_payload, dict) or not isinstance(gwas_payload, dict):
            return None
        # Require VEP data in cache (invalidate old caches without VEP)
        if not isinstance(vep_payload, dict):
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
        "stage2_evidence": {k: v for k, v in stage2_evidence.items() if not k.startswith("_")},
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

        # true_total captures the OT-reported count BEFORE any local
        # truncation. Sources in priority order:
        #   1. Parquet `get_target_bundle` -> bundle["associations_api_total_count"]
        #   2. GraphQL `get_target_associations` dict -> assocs["api_total_count"]
        #   3. len(associations) fallback with provenance = "list_length"
        # `associations_total_source` lets downstream scoring code (and
        # debugging) know which counter it is trusting.
        true_total: int | None = None
        true_total_source: str = "list_length"

        if hasattr(mod, "get_target_bundle"):
            bundle = mod.get_target_bundle(
                ensembl_id,
                efo_id=disease_context.get("efo_id"),
                min_score=0.1,
            )
            result["target_info"] = bundle.get("target_info", {})
            result["disease_evidence"] = bundle.get("disease_evidence", [])
            result["associations"] = bundle.get("associations", [])
            _tt = bundle.get("associations_api_total_count")
            if _tt is not None:
                true_total = int(_tt)
                true_total_source = "parquet_pre_head"
        else:
            result["target_info"] = mod.get_target_info(ensembl_id, include_diseases=True)
            if disease_context.get("efo_id"):
                result["disease_evidence"] = mod.get_target_disease_evidence(
                    ensembl_id,
                    disease_context["efo_id"],
                )
            assocs_payload = mod.get_target_associations(ensembl_id, min_score=0.1)
            # Accept both dict (post-A1) and list (legacy mock/test).
            if isinstance(assocs_payload, dict):
                result["associations"] = assocs_payload.get("associations", [])
                _tt = assocs_payload.get("api_total_count")
                if _tt is not None:
                    true_total = int(_tt)
                    true_total_source = "api_count"
            else:
                result["associations"] = assocs_payload or []

        # Persist the TRUE total BEFORE truncation — `_score_novelty_opportunity`
        # uses the capped list length today, which makes well-studied targets
        # (TGFB1, thousands of associations) look identical to nearly-novel
        # targets (CD99, ~20 associations). The score function will prefer
        # this field when present.
        if true_total is None:
            true_total = len(result["associations"])
        result["associations_total_count"] = true_total
        result["associations_total_source"] = true_total_source
        # Truncate large payloads to prevent token bloat
        if len(result["associations"]) > 20:
            result["associations"] = sorted(
                result["associations"], key=lambda x: x.get("score", 0), reverse=True
            )[:20]
            result["associations_truncated"] = True
        if len(result["disease_evidence"]) > 30:
            # Diversity-aware truncation: keep at least 1 entry per datatypeId
            by_type: dict[str, list] = {}
            for ev in result["disease_evidence"]:
                by_type.setdefault(ev.get("datatypeId", "unknown"), []).append(ev)
            kept: list[dict] = []
            n_types = max(len(by_type), 1)
            per_type_quota = max(1, 30 // n_types)
            for _dt, entries in by_type.items():
                entries.sort(key=lambda x: x.get("score", 0), reverse=True)
                kept.extend(entries[:min(per_type_quota, len(entries))])
            kept_ids = {id(e) for e in kept}
            remaining = [e for e in result["disease_evidence"] if id(e) not in kept_ids]
            remaining.sort(key=lambda x: x.get("score", 0), reverse=True)
            kept.extend(remaining[: max(0, 30 - len(kept))])
            result["disease_evidence"] = kept[:30]
            result["disease_evidence_truncated"] = True

        if disease_context.get("efo_id"):
            result["efo_id"] = disease_context["efo_id"]

        # Target-level drugs (across all diseases) for druggability scoring
        try:
            if hasattr(mod, "get_drugs_for_target"):
                result["target_drugs"] = mod.get_drugs_for_target(ensembl_id)
            else:
                result["target_drugs"] = {"count": 0, "rows": []}
        except Exception as drug_exc:
            result["target_drugs"] = {"count": 0, "rows": [], "error": str(drug_exc)}

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


def _query_vep_for_gene(gwas_data: dict[str, Any]) -> dict[str, Any]:
    """Extract rs IDs from GWAS gene_associations and query Ensembl VEP."""
    from src.agents.drug_target.tools.stage_logic import classify_vep_consequence

    result: dict[str, Any] = {
        "executed": False, "variants": [], "impact_summary": {}, "errors": [],
    }

    rs_ids = [
        assoc.get("rsId", "")
        for assoc in gwas_data.get("gene_associations", [])
        if assoc.get("rsId", "").startswith("rs")
    ]
    if not rs_ids:
        result["errors"].append("No rs IDs found in gene_associations")
        return result

    rs_ids = rs_ids[:50]  # Ensembl batch limit

    url = "https://rest.ensembl.org/vep/human/id"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    try:
        resp = requests.post(
            url, headers=headers,
            data=json.dumps({"ids": rs_ids}), timeout=90,
        )
        resp.raise_for_status()
        for row in resp.json():
            consequence = row.get("most_severe_consequence", "")
            result["variants"].append({
                "input": row.get("input"),
                "id": row.get("id"),
                "most_severe_consequence": consequence,
                "impact_class": classify_vep_consequence(consequence),
            })
        result["executed"] = True
        impacts = Counter(v["impact_class"] for v in result["variants"])
        result["impact_summary"] = dict(impacts)
    except Exception as exc:
        result["errors"].append(f"VEP query failed: {exc}")

    return result


def _proximity_match(
    gene_assocs: list[dict],
    trait_assocs: list[dict],
    window: int = 500_000,
) -> list[dict]:
    """Find trait SNPs within ±window bp of any gene-associated locus."""
    gene_regions: list[tuple[str, int]] = []
    for ga in gene_assocs:
        for loc in ga.get("locations", []):
            chrom = loc.get("chromosome") or loc.get("chromosomeName")
            pos = loc.get("position") or loc.get("chromosomePosition")
            if chrom and pos:
                gene_regions.append((str(chrom), int(pos)))
    if not gene_regions:
        return []

    nearby: list[dict] = []
    seen: set[str] = set()
    for ta in trait_assocs:
        rsid = ta.get("rsId", "")
        if rsid in seen:
            continue
        # Parse chr:pos format (e.g., "chr11:1219991")
        if ":" in rsid:
            raw = rsid.replace("chr", "")
            parts = raw.split(":")
            if len(parts) == 2:
                try:
                    t_chrom, t_pos = parts[0], int(parts[1])
                    for g_chrom, g_pos in gene_regions:
                        if str(t_chrom) == str(g_chrom) and abs(t_pos - g_pos) <= window:
                            nearby.append(ta)
                            seen.add(rsid)
                            break
                except (ValueError, TypeError):
                    pass
    return nearby


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
            # Parquet-path enrichment: `query_gene_trait_with_context` does NOT
            # compute proximity overlap between disease trait rsIds and the
            # gene's own cis-SNPs. Without this, `disease_specific_hits` only
            # reports `n_gene_in_trait` / `n_gene_snps_in_disease`, both of
            # which depend on the trait_associations[*].genes array — which
            # OT Genetics populates sparsely for most GWAS loci. The legacy
            # else-branch below already runs `_proximity_match`, so we mirror
            # that behaviour here.
            dsh = result.get("disease_specific_hits") or {}
            if "n_proximity_hits" not in dsh:
                _trait_assocs = result.get("trait_associations", []) or []
                _gene_assocs = result.get("gene_associations", []) or []
                _trait_rsids = {
                    a.get("rsId") for a in _trait_assocs if a.get("rsId")
                }
                if "gene_snps_in_disease" not in dsh:
                    _gene_snps = [
                        a for a in _gene_assocs if a.get("rsId") in _trait_rsids
                    ]
                    dsh["gene_snps_in_disease"] = _gene_snps
                    dsh["n_gene_snps_in_disease"] = len(_gene_snps)
                _proximity = _proximity_match(_gene_assocs, _trait_assocs)
                dsh["proximity_hits"] = _proximity
                dsh["n_proximity_hits"] = len(_proximity)
                result["disease_specific_hits"] = dsh
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
            proximity_hits = _proximity_match(gene_assocs, trait_assocs)
            result["disease_specific_hits"] = {
                "gene_in_trait_associations": gene_in_trait,
                "gene_snps_in_disease": gene_snps_in_disease,
                "proximity_hits": proximity_hits,
                "n_gene_in_trait": len(gene_in_trait),
                "n_gene_snps_in_disease": len(gene_snps_in_disease),
                "n_proximity_hits": len(proximity_hits),
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

    def _query_single_gene(gene: str) -> tuple[str, dict[str, Any]]:
        """Query OT + GWAS + VEP for a single gene (thread-safe)."""
        gwas_data = (
            query_gwas_gene_trait_data(
                gene,
                disease,
                mod=gwas_mod,
                disease_context=gwas_disease_context,
            )
            if gwas_error is None
            else _unavailable_gwas_result(gene, disease, gwas_error)
        )
        try:
            vep_data = _query_vep_for_gene(gwas_data)
        except Exception as vep_exc:
            logger.warning("VEP query failed for %s: %s", gene, vep_exc)
            vep_data = {"source": "ensembl_vep", "error": str(vep_exc), "variants": []}
        return gene, {
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
            "gwas": gwas_data,
            "vep": vep_data,
        }

    _MAX_CONCURRENT_GENES = 5
    stage2_evidence: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_GENES) as executor:
        futures = {executor.submit(_query_single_gene, gene): gene for gene in genes}
        for future in as_completed(futures):
            gene = futures[future]
            try:
                _, result = future.result()
                stage2_evidence[gene] = result
            except Exception as exc:
                logger.warning("Stage2 query failed for %s: %s", gene, exc)
                stage2_evidence[gene] = {
                    "opentargets": _unavailable_opentargets_result(
                        gene, disease, f"Thread error: {exc}"
                    ),
                    "gwas": _unavailable_gwas_result(gene, disease, f"Thread error: {exc}"),
                    "vep": {"source": "ensembl_vep", "error": str(exc), "variants": []},
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

    # Include disease metadata for downstream scoring
    stage2_with_meta = dict(stage2_evidence)
    stage2_with_meta["_disease"] = result_bundle.get("disease", "unknown")
    _write_json(out_dir / "stage2_evidence.json", stage2_with_meta)
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

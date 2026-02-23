"""Drug target discovery tools using Open Targets Platform API.

These tools wrap the OpenTargets GraphQL API helper functions from
skills/opentargets-database/scripts/query_opentargets.py to enable
REPORTER subagent to assess druggability of genes identified in CCI analysis.
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import pandas as pd
from langchain_core.tools import tool

# Add the skills script directory to sys.path so we can import query_opentargets
_SKILLS_SCRIPT_DIR = str(
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "skills"
    / "opentargets-database"
    / "scripts"
)
if _SKILLS_SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SKILLS_SCRIPT_DIR)

from query_opentargets import (
    execute_query,
    get_disease_info,
    get_drug_info,
    get_known_drugs_for_disease,
    get_target_disease_evidence,
    get_target_info,
    search_entities,
)

logger = logging.getLogger(__name__)


def _load_top_search_genes(data_dir: str) -> list[str]:
    """Load pre-computed hub genes from top_search_genes.json.

    Written by data_loader._extract_search_context() during PLANNER phase.
    Supports v1 (plain list) and v2 (object with 'genes' key) formats.

    Returns:
        List of gene symbols, or empty list if file not found/malformed.
    """
    top_genes_file = os.path.join(data_dir, "top_search_genes.json")
    if not os.path.exists(top_genes_file):
        return []
    try:
        with open(top_genes_file) as f:
            payload = json.load(f)

        # Legacy format (v1): ["TP53", "EGFR", ...]
        if isinstance(payload, list):
            return [g for g in payload if isinstance(g, str) and g]

        # Current format (v2): {"version": 2, "genes": [...], ...}
        if isinstance(payload, dict):
            genes = payload.get("genes")
            if isinstance(genes, list):
                return [g for g in genes if isinstance(g, str) and g]
    except Exception as e:
        logger.warning(f"Failed to load top_search_genes.json: {e}")
    return []


def _load_selected_top3_lr(data_dir: str) -> list[str]:
    """Load unique gene symbols from selected_top3_lr.json.

    Written by lr_prioritizer.save_selected_lr_pairs() during INTERPRETER phase.
    Extracts unique ligand and receptor gene symbols from the selected pairs.

    Returns:
        List of unique gene symbols, or empty list if file not found/malformed.
    """
    lr_file = os.path.join(data_dir, "selected_top3_lr.json")
    if not os.path.exists(lr_file):
        return []
    try:
        with open(lr_file) as f:
            payload = json.load(f)

        selected_pairs = payload.get("selected_pairs", [])
        seen: set[str] = set()
        genes: list[str] = []
        for pair in selected_pairs:
            for key in ("ligand", "receptor"):
                gene = pair.get(key, "")
                if isinstance(gene, str) and gene and gene not in seen:
                    seen.add(gene)
                    genes.append(gene)
        return genes
    except Exception as e:
        logger.warning(f"Failed to load selected_top3_lr.json: {e}")
    return []


def _load_lr_candidates_genes(data_dir: str, top_k_pairs: int = 15) -> list[str]:
    """Load unique gene symbols from lr_candidates.json candidate pairs.

    Reads candidate pairs written by lr_prioritizer.prioritize_top_lr_pairs()
    and extracts ligand/receptor genes from the top-N candidates.

    Args:
        data_dir: Analysis data directory
        top_k_pairs: Maximum number of candidate pairs to use

    Returns:
        List of unique gene symbols (order-preserving), or empty list on failure.
    """
    candidates_file = os.path.join(data_dir, "lr_candidates.json")
    if not os.path.exists(candidates_file):
        return []

    try:
        with open(candidates_file) as f:
            payload = json.load(f)

        candidate_pairs = payload.get("candidate_pairs", [])
        if not isinstance(candidate_pairs, list):
            return []

        # Prefer rank ordering if present; otherwise preserve file order.
        pairs_with_index: list[tuple[int, dict]] = []
        for idx, pair in enumerate(candidate_pairs):
            if isinstance(pair, dict):
                pairs_with_index.append((idx, pair))

        if any(isinstance(p.get("rank"), (int, float)) for _, p in pairs_with_index):
            pairs_with_index.sort(
                key=lambda item: (
                    item[1].get("rank")
                    if isinstance(item[1].get("rank"), (int, float))
                    else 10**9,
                    item[0],
                )
            )

        selected_pairs = [p for _, p in pairs_with_index[:top_k_pairs]]
        seen: set[str] = set()
        genes: list[str] = []
        for pair in selected_pairs:
            for key in ("ligand", "receptor"):
                gene = pair.get(key, "")
                if isinstance(gene, str) and gene and gene not in seen:
                    seen.add(gene)
                    genes.append(gene)
        return genes
    except Exception as e:
        logger.warning(f"Failed to load lr_candidates.json: {e}")
    return []


def _resolve_gene_to_ensembl(gene_symbol: str) -> Optional[str]:
    """Resolve a gene symbol to its Ensembl ID via OpenTargets search.

    Args:
        gene_symbol: Gene symbol (e.g., "BRCA1")

    Returns:
        Ensembl ID string, or None if not found
    """
    try:
        results = search_entities(gene_symbol, entity_types=["target"])
        if results:
            # Return the top hit's ID
            return results[0].get("id")
    except Exception as e:
        logger.warning(f"Failed to resolve gene {gene_symbol}: {e}")
    return None


def _resolve_disease_to_efo(disease: str) -> Optional[str]:
    """Resolve a disease name to its EFO ID via OpenTargets search.

    Args:
        disease: Disease name (e.g., "breast cancer")

    Returns:
        EFO ID string, or None if not found
    """
    try:
        results = search_entities(disease, entity_types=["disease"])
        if results:
            return results[0].get("id")
    except Exception as e:
        logger.warning(f"Failed to resolve disease {disease}: {e}")
    return None


def _summarize_tractability(tractability: list[dict]) -> dict:
    """Summarize tractability data into a readable format.

    Args:
        tractability: Raw tractability list from OpenTargets

    Returns:
        Dict with modality -> list of tractability labels
    """
    summary: dict[str, list[str]] = {}
    if not tractability:
        return summary
    for entry in tractability:
        modality = entry.get("modality", "unknown")
        label = entry.get("label", "")
        value = entry.get("value", False)
        if value and label:
            summary.setdefault(modality, []).append(label)
    return summary


def _summarize_safety(safety_liabilities: list[dict]) -> list[dict]:
    """Summarize safety liabilities into a readable format.

    Args:
        safety_liabilities: Raw safety data from OpenTargets

    Returns:
        List of simplified safety concern dicts
    """
    if not safety_liabilities:
        return []
    concerns = []
    for item in safety_liabilities:
        concern = {
            "event": item.get("event", ""),
            "effects": [],
            "tissues": [],
        }
        for effect in item.get("effects", []):
            if effect.get("dosing"):
                concern["effects"].append(effect["dosing"])
        for biosample in item.get("biosamples", []):
            tissue_label = biosample.get("tissueLabel", "")
            if tissue_label:
                concern["tissues"].append(tissue_label)
        concerns.append(concern)
    return concerns


def _compute_gwas_proxy_scores(
    evidence: list[dict],
    approved_symbol: str,
    ot_genetic_association_score: float,
    reported_weight: float = 1.0,
    nearest_weight: float = 0.6,
    consistency_delta: float = 0.35,
) -> dict:
    """Compute GWAS proxy metrics from OpenTargets evidence rows.

    This is a compatibility layer used when a dedicated GWAS datasource
    integration is not available locally. It uses OpenTargets genetic
    association evidence and separates "reported" vs "nearest/other" based
    on targetFromSourceId matching to the approved symbol.
    """
    approved_symbol = (approved_symbol or "").upper()
    genetic_evidence = [
        ev for ev in evidence
        if (ev.get("datatypeId") or "").lower() == "genetic_association"
    ]

    # Prefer explicitly GWAS-like datasource IDs; fallback to all genetic evidence.
    gwas_like = []
    for ev in genetic_evidence:
        ds = (ev.get("datasourceId") or "").lower()
        if "gwas" in ds or ds in {"ukbiobank", "finngen", "ot_genetics_portal"}:
            gwas_like.append(ev)
    if not gwas_like:
        gwas_like = genetic_evidence

    reported_scores: list[float] = []
    nearest_scores: list[float] = []
    for ev in gwas_like:
        try:
            score = float(ev.get("score", 0.0) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        source_target = str(ev.get("targetFromSourceId", "") or "").upper()

        # Missing mapping is treated as reported to avoid dropping valid signals.
        if not source_target:
            reported_scores.append(score)
        elif approved_symbol and source_target == approved_symbol:
            reported_scores.append(score)
        else:
            nearest_scores.append(score)

    reported_score = (
        sum(reported_scores) / len(reported_scores) if reported_scores else 0.0
    )
    nearest_score = (
        sum(nearest_scores) / len(nearest_scores) if nearest_scores else 0.0
    )
    denom = reported_weight + nearest_weight
    if denom <= 0:
        gwas_combined_score = 0.0
    else:
        gwas_combined_score = (
            (reported_weight * reported_score) + (nearest_weight * nearest_score)
        ) / denom

    # Flag major divergence between OT genetic aggregate and GWAS proxy score.
    has_signal = ot_genetic_association_score > 0 or gwas_combined_score > 0
    genetic_consistency_flag = (
        has_signal
        and abs(float(ot_genetic_association_score) - float(gwas_combined_score)) >= consistency_delta
    )

    return {
        "gwas_mapping_policy": "reported_plus_nearest_weighted",
        "gwas_weights": {
            "reported_gene": reported_weight,
            "nearest_gene": nearest_weight,
        },
        "ot_genetic_association_score": float(ot_genetic_association_score),
        "gwas_reported_hits_count": len(reported_scores),
        "gwas_nearest_hits_count": len(nearest_scores),
        "gwas_reported_score": float(reported_score),
        "gwas_nearest_score": float(nearest_score),
        "gwas_combined_score": float(gwas_combined_score),
        "genetic_consistency_flag": bool(genetic_consistency_flag),
    }


@tool
def search_drug_targets(
    gene_symbols: list[str],
    disease: str,
) -> str:
    """Search OpenTargets for drug target information on specified genes.

    Evaluates each gene's druggability by querying the Open Targets Platform
    for tractability, safety liabilities, and disease-specific evidence.

    Args:
        gene_symbols: List of gene symbols to evaluate (e.g., ["TGFB1", "CDH1"])
        disease: Disease context for evidence filtering (e.g., "breast cancer")

    Returns:
        JSON string with per-gene druggability assessment including
        tractability, safety, association scores, and evidence types
    """
    # Resolve disease to EFO ID
    efo_id = _resolve_disease_to_efo(disease)
    if not efo_id:
        return json.dumps({
            "error": f"Could not resolve disease '{disease}' to EFO ID",
            "genes_queried": gene_symbols,
        })

    results = {}
    failed_genes = []

    for gene in gene_symbols:
        try:
            # Resolve gene symbol to Ensembl ID
            ensembl_id = _resolve_gene_to_ensembl(gene)
            if not ensembl_id:
                failed_genes.append(gene)
                continue

            # Get target info with disease associations
            target_info = get_target_info(ensembl_id, include_diseases=True)
            if not target_info:
                failed_genes.append(gene)
                continue

            # Get disease-specific evidence
            evidence = []
            try:
                evidence = get_target_disease_evidence(ensembl_id, efo_id)
            except Exception:
                pass

            # Compute association score and datatype scores for this disease
            association_score = 0.0
            ot_genetic_association_score = 0.0
            associated_diseases = (
                target_info.get("associatedDiseases", {}).get("rows", [])
            )
            for assoc in associated_diseases:
                if assoc.get("disease", {}).get("id") == efo_id:
                    association_score = assoc.get("score", 0.0)
                    for ds in assoc.get("datatypeScores", []):
                        if (ds.get("id") or "").lower() == "genetic_association":
                            try:
                                ot_genetic_association_score = float(ds.get("score", 0.0) or 0.0)
                            except (TypeError, ValueError):
                                ot_genetic_association_score = 0.0
                            break
                    break

            # Summarize evidence types
            evidence_types = {}
            for ev in evidence:
                dtype = ev.get("datatypeId", "unknown")
                evidence_types[dtype] = evidence_types.get(dtype, 0) + 1

            approved_symbol = target_info.get("approvedSymbol", gene)
            gwas_proxy = _compute_gwas_proxy_scores(
                evidence=evidence,
                approved_symbol=approved_symbol,
                ot_genetic_association_score=ot_genetic_association_score,
            )

            results[gene] = {
                "ensembl_id": ensembl_id,
                "approved_symbol": approved_symbol,
                "approved_name": target_info.get("approvedName", ""),
                "biotype": target_info.get("biotype", ""),
                "function": (target_info.get("functionDescriptions") or [""])[0][:300],
                "tractability": _summarize_tractability(
                    target_info.get("tractability", [])
                ),
                "safety_liabilities": _summarize_safety(
                    target_info.get("safetyLiabilities", [])
                ),
                "genetic_constraint": target_info.get("geneticConstraint", []),
                "disease_association_score": association_score,
                "evidence_count": len(evidence),
                "evidence_types": evidence_types,
                **gwas_proxy,
            }
        except Exception as e:
            logger.warning(f"Error querying OpenTargets for {gene}: {e}")
            failed_genes.append(gene)

    return json.dumps({
        "disease": disease,
        "efo_id": efo_id,
        "genes_found": len(results),
        "genes_failed": failed_genes,
        "targets": results,
    }, indent=2)


@tool
def search_known_drugs(
    disease: str,
    gene_symbols: Optional[list[str]] = None,
) -> str:
    """Search OpenTargets for known drugs targeting a disease.

    Finds approved and clinical-stage drugs for the specified disease,
    optionally filtered to drugs targeting specific genes.

    Args:
        disease: Disease name (e.g., "breast cancer")
        gene_symbols: Optional list of gene symbols to filter drugs by target.
            If provided, only returns drugs targeting these genes.

    Returns:
        JSON string with drug list including name, phase, mechanism,
        and target genes
    """
    # Resolve disease
    efo_id = _resolve_disease_to_efo(disease)
    if not efo_id:
        return json.dumps({
            "error": f"Could not resolve disease '{disease}' to EFO ID",
        })

    # Get known drugs
    try:
        drugs_data = get_known_drugs_for_disease(efo_id)
    except Exception as e:
        return json.dumps({
            "error": f"Failed to query drugs for {disease}: {e}",
        })

    rows = drugs_data.get("rows", [])

    # Optionally filter by gene symbols
    if gene_symbols:
        gene_set = {g.upper() for g in gene_symbols}
        filtered_rows = []
        for row in rows:
            # API v4 returns singular "target" (dict), not plural "targets" (list)
            target_obj = row.get("target")
            if isinstance(target_obj, dict):
                target_list = [target_obj]
            elif isinstance(target_obj, list):
                target_list = target_obj
            else:
                target_list = row.get("targets", [])
                if isinstance(target_list, dict):
                    target_list = [target_list]
            target_symbols = {
                t.get("approvedSymbol", "").upper() for t in target_list
            }
            if target_symbols & gene_set:
                filtered_rows.append(row)
        rows = filtered_rows

    # Format results
    drugs = []
    seen_drug_ids = set()
    for row in rows:
        drug = row.get("drug", {})
        drug_id = drug.get("id", "")

        # Deduplicate by drug ID
        if drug_id in seen_drug_ids:
            continue
        seen_drug_ids.add(drug_id)

        # API v4 returns singular "target" (dict), not plural "targets" (list)
        target_obj = row.get("target")
        if isinstance(target_obj, dict):
            target_list = [target_obj]
        elif isinstance(target_obj, list):
            target_list = target_obj
        else:
            target_list = row.get("targets", [])
            if isinstance(target_list, dict):
                target_list = [target_list]
        target_symbols = [
            t.get("approvedSymbol", "") for t in target_list
        ]
        drugs.append({
            "drug_id": drug_id,
            "drug_name": drug.get("name", ""),
            "drug_type": drug.get("drugType", ""),
            "max_clinical_phase": drug.get("maximumClinicalTrialPhase", 0),
            "phase": row.get("phase", 0),
            "status": row.get("status", ""),
            "mechanism_of_action": row.get("mechanismOfAction", ""),
            "target_genes": target_symbols,
        })

    # Sort by phase descending
    drugs.sort(key=lambda d: d.get("phase", 0), reverse=True)

    return json.dumps({
        "disease": disease,
        "efo_id": efo_id,
        "total_unique_drugs": drugs_data.get("uniqueDrugs", 0),
        "total_unique_targets": drugs_data.get("uniqueTargets", 0),
        "filtered_by_genes": gene_symbols or [],
        "drugs_returned": len(drugs),
        "drugs": drugs[:50],  # Cap at 50 for context window
    }, indent=2)


@tool
def assess_therapeutic_potential(
    data_dir: str,
    disease: str,
) -> str:
    """Comprehensive therapeutic potential assessment for CCI analysis genes.

    One-stop tool that evaluates hub genes (from top_search_genes.json),
    selected novel L-R pair genes (from selected_top3_lr.json), and top
    candidate L-R genes (from lr_candidates.json) for druggability via
    the Open Targets Platform. Falls back to LIANA CSV ranking if no gene
    source file is available.

    Args:
        data_dir: Path to the analysis data directory
        disease: Disease context (e.g., "breast cancer")

    Returns:
        JSON string with ranked therapeutic targets, known drugs,
        and the path to the saved results file
    """
    # Load gene lists from upstream pipeline outputs
    hub_genes = _load_top_search_genes(data_dir)
    novel_genes = _load_selected_top3_lr(data_dir)
    candidate_genes = _load_lr_candidates_genes(data_dir, top_k_pairs=15)

    hub_set = set(hub_genes)
    novel_lr_set = set(novel_genes)
    lr_candidates_set = set(candidate_genes)

    # Source priority: selected_top3 -> lr_candidates(top15) -> top_search hub genes
    gene_list: list[str] = []
    seen: set[str] = set()
    for source_genes in (novel_genes, candidate_genes, hub_genes):
        for gene in source_genes:
            if gene not in seen:
                seen.add(gene)
                gene_list.append(gene)

    gene_source = (
        "selected_top3+lr_candidates+top_search"
        if candidate_genes
        else "top_search_genes+selected_top3_lr"
    )

    # Fallback: if both files missing, use LIANA CSV ranking
    if not gene_list:
        gene_source = "liana_csv_fallback"
        logger.info(
            "No selected_top3_lr.json, lr_candidates.json, or top_search_genes.json found; "
            "falling back to LIANA CSV ranking"
        )
        liana_path = os.path.join(data_dir, "interest_sig_liana.csv")
        if not os.path.exists(liana_path):
            return json.dumps({
                "error": (
                    "No gene source files found. Checked top_search_genes.json, "
                    f"selected_top3_lr.json, lr_candidates.json, and {liana_path}"
                ),
                "suggestion": "Ensure the wrapper agent completed Steps 1-11 before invoking drug target assessment.",
            })

        try:
            df = pd.read_csv(liana_path)
        except Exception as e:
            return json.dumps({"error": f"Failed to read {liana_path}: {e}"})

        # Extract unique ligand/receptor genes
        ligand_col = "ligand" if "ligand" in df.columns else None
        receptor_col = "receptor" if "receptor" in df.columns else None

        if not ligand_col or not receptor_col:
            for col in df.columns:
                if "ligand" in col.lower() and not ligand_col:
                    ligand_col = col
                elif "receptor" in col.lower() and not receptor_col:
                    receptor_col = col

        if not ligand_col or not receptor_col:
            return json.dumps({
                "error": "Could not find ligand/receptor columns in LIANA data",
                "columns": list(df.columns),
            })

        # Count gene frequency and get combined scores
        gene_scores: dict[str, dict] = {}

        for _, row in df.iterrows():
            for col, role in [(ligand_col, "ligand"), (receptor_col, "receptor")]:
                gene = str(row[col]).strip()
                if not gene or gene == "nan":
                    continue
                if gene not in gene_scores:
                    gene_scores[gene] = {
                        "frequency": 0,
                        "max_combinedscore": 0.0,
                        "roles": set(),
                    }
                gene_scores[gene]["frequency"] += 1
                gene_scores[gene]["roles"].add(role)

                for score_col in ["combinedscore", "combined_score", "score"]:
                    if score_col in df.columns:
                        try:
                            score = float(row[score_col])
                            if score > gene_scores[gene]["max_combinedscore"]:
                                gene_scores[gene]["max_combinedscore"] = score
                        except (ValueError, TypeError):
                            pass
                        break

        for gene, info in gene_scores.items():
            info["roles"] = list(info["roles"])
            info["rank_score"] = info["frequency"] * (1 + info["max_combinedscore"])

        ranked_genes = sorted(
            gene_scores.items(),
            key=lambda x: x[1]["rank_score"],
            reverse=True,
        )[:30]

        gene_list = [g[0] for g in ranked_genes]

    # Query OpenTargets for drug targets
    logger.info(f"Querying OpenTargets for {len(gene_list)} genes...")
    targets_result = json.loads(search_drug_targets.invoke({
        "gene_symbols": gene_list,
        "disease": disease,
    }))

    # Query known drugs
    logger.info(f"Querying known drugs for {disease}...")
    drugs_result = json.loads(search_known_drugs.invoke({
        "disease": disease,
        "gene_symbols": gene_list,
    }))

    # Combine results
    therapeutic_assessment = {
        "disease": disease,
        "efo_id": targets_result.get("efo_id", ""),
        "gene_source": gene_source,
        "hub_genes_count": len(hub_genes),
        "novel_lr_genes_count": len(novel_genes),
        "lr_candidates_genes_count": len(candidate_genes),
        "gene_ranking": {
            gene: {
                "druggability": targets_result.get("targets", {}).get(gene, {}),
                "from_hub_genes": gene in hub_set,
                "from_novel_lr": gene in novel_lr_set,
                "from_lr_candidates": gene in lr_candidates_set,
            }
            for gene in gene_list
        },
        "druggable_targets": [],
        "non_druggable_targets": [],
        "known_drugs": drugs_result.get("drugs", []),
        "novel_targets": [],
        "summary": {},
    }

    # Classify targets
    targets_data = targets_result.get("targets", {})
    for gene in gene_list:
        target = targets_data.get(gene)
        if not target:
            continue

        tractability = target.get("tractability", {})
        has_tractability = any(
            len(modalities) > 0 for modalities in tractability.values()
        )
        assoc_score = target.get("disease_association_score", 0.0)

        entry = {
            "gene": gene,
            "ensembl_id": target.get("ensembl_id", ""),
            "name": target.get("approved_name", ""),
            "tractability": tractability,
            "association_score": assoc_score,
            "evidence_count": target.get("evidence_count", 0),
            "safety_concerns": len(target.get("safety_liabilities", [])),
            "from_novel_lr_selection": gene in novel_lr_set,
            "from_lr_candidates": gene in lr_candidates_set,
            "ot_genetic_association_score": target.get("ot_genetic_association_score", 0.0),
            "gwas_mapping_policy": target.get("gwas_mapping_policy", "reported_plus_nearest_weighted"),
            "gwas_weights": target.get("gwas_weights", {"reported_gene": 1.0, "nearest_gene": 0.6}),
            "gwas_reported_hits_count": target.get("gwas_reported_hits_count", 0),
            "gwas_nearest_hits_count": target.get("gwas_nearest_hits_count", 0),
            "gwas_reported_score": target.get("gwas_reported_score", 0.0),
            "gwas_nearest_score": target.get("gwas_nearest_score", 0.0),
            "gwas_combined_score": target.get("gwas_combined_score", 0.0),
            "genetic_consistency_flag": target.get("genetic_consistency_flag", False),
        }

        if has_tractability:
            therapeutic_assessment["druggable_targets"].append(entry)
        else:
            therapeutic_assessment["non_druggable_targets"].append(entry)

        # Novel targets: druggable but no known disease association,
        # OR from novel L-R selection (these are explicitly novel candidates)
        if has_tractability and (assoc_score == 0.0 or gene in novel_lr_set):
            therapeutic_assessment["novel_targets"].append(entry)

    # Sort druggable targets by association score
    therapeutic_assessment["druggable_targets"].sort(
        key=lambda x: x["association_score"], reverse=True
    )

    # Summary statistics
    gwas_reported_hits_total = sum(
        int((targets_data.get(g, {}) or {}).get("gwas_reported_hits_count", 0) or 0)
        for g in gene_list
    )
    gwas_nearest_hits_total = sum(
        int((targets_data.get(g, {}) or {}).get("gwas_nearest_hits_count", 0) or 0)
        for g in gene_list
    )
    genes_with_gwas_signal = sum(
        1
        for g in gene_list
        if float((targets_data.get(g, {}) or {}).get("gwas_combined_score", 0.0) or 0.0) > 0
    )
    genes_with_genetic_conflict = sum(
        1
        for g in gene_list
        if bool((targets_data.get(g, {}) or {}).get("genetic_consistency_flag", False))
    )
    therapeutic_assessment["summary"] = {
        "total_genes_evaluated": len(gene_list),
        "hub_genes_count": len(hub_genes),
        "novel_lr_genes_count": len(novel_genes),
        "lr_candidates_genes_count": len(candidate_genes),
        "gene_source": gene_source,
        "genes_found_in_opentargets": targets_result.get("genes_found", 0),
        "genes_failed": targets_result.get("genes_failed", []),
        "druggable_count": len(therapeutic_assessment["druggable_targets"]),
        "non_druggable_count": len(therapeutic_assessment["non_druggable_targets"]),
        "novel_target_count": len(therapeutic_assessment["novel_targets"]),
        "known_drugs_count": len(therapeutic_assessment["known_drugs"]),
        "gwas_mapping_policy": "reported_plus_nearest_weighted",
        "gwas_weights": {"reported_gene": 1.0, "nearest_gene": 0.6},
        "gwas_reported_hits_total": gwas_reported_hits_total,
        "gwas_nearest_hits_total": gwas_nearest_hits_total,
        "genes_with_gwas_signal": genes_with_gwas_signal,
        "genes_with_genetic_conflict": genes_with_genetic_conflict,
        "top_druggable_genes": [
            t["gene"] for t in therapeutic_assessment["druggable_targets"][:5]
        ],
        "top_novel_genes": [
            t["gene"] for t in therapeutic_assessment["novel_targets"][:5]
        ],
    }

    # Save results to file
    output_path = os.path.join(data_dir, "therapeutic_targets.json")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(therapeutic_assessment, f, indent=2)
        therapeutic_assessment["saved_to"] = output_path
    except Exception as e:
        therapeutic_assessment["save_error"] = str(e)

    # Dual-write GWAS-focused outputs:
    # - therapeutic_targets_gwas.json (detail payload)
    # - synthesis_gwas.json (summary payload used by reporter synthesis step)
    gwas_genes = []
    for gene in gene_list:
        target = targets_data.get(gene, {})
        gwas_genes.append({
            "gene": gene,
            "ensembl_id": target.get("ensembl_id", ""),
            "approved_name": target.get("approved_name", ""),
            "ot_genetic_association_score": target.get("ot_genetic_association_score", 0.0),
            "gwas_reported_hits_count": target.get("gwas_reported_hits_count", 0),
            "gwas_nearest_hits_count": target.get("gwas_nearest_hits_count", 0),
            "gwas_reported_score": target.get("gwas_reported_score", 0.0),
            "gwas_nearest_score": target.get("gwas_nearest_score", 0.0),
            "gwas_combined_score": target.get("gwas_combined_score", 0.0),
            "genetic_consistency_flag": target.get("genetic_consistency_flag", False),
            "from_novel_lr_selection": gene in novel_lr_set,
            "from_lr_candidates": gene in lr_candidates_set,
        })

    gwas_detail_payload = {
        "disease": disease,
        "efo_id": targets_result.get("efo_id", ""),
        "mapping_policy": "reported_plus_nearest_weighted",
        "weights": {"reported_gene": 1.0, "nearest_gene": 0.6},
        "summary": {
            "total_genes_evaluated": len(gene_list),
            "gwas_reported_hits_total": gwas_reported_hits_total,
            "gwas_nearest_hits_total": gwas_nearest_hits_total,
            "genes_with_gwas_signal": genes_with_gwas_signal,
            "genes_with_genetic_conflict": genes_with_genetic_conflict,
        },
        "genes": gwas_genes,
    }
    gwas_summary_payload = {
        "disease": disease,
        "mapping_policy": "reported_plus_nearest_weighted",
        "weights": {"reported_gene": 1.0, "nearest_gene": 0.6},
        "summary": gwas_detail_payload["summary"],
        "top_genes_by_gwas": sorted(
            [
                {
                    "gene": row["gene"],
                    "gwas_combined_score": row["gwas_combined_score"],
                    "genetic_consistency_flag": row["genetic_consistency_flag"],
                }
                for row in gwas_genes
            ],
            key=lambda x: x["gwas_combined_score"],
            reverse=True,
        )[:20],
    }

    gwas_detail_path = os.path.join(data_dir, "therapeutic_targets_gwas.json")
    gwas_summary_path = os.path.join(data_dir, "synthesis_gwas.json")
    gwas_file_errors = {}
    try:
        with open(gwas_detail_path, "w", encoding="utf-8") as f:
            json.dump(gwas_detail_payload, f, indent=2)
    except Exception as e:
        gwas_file_errors["therapeutic_targets_gwas.json"] = str(e)
    try:
        with open(gwas_summary_path, "w", encoding="utf-8") as f:
            json.dump(gwas_summary_payload, f, indent=2)
    except Exception as e:
        gwas_file_errors["synthesis_gwas.json"] = str(e)

    therapeutic_assessment["gwas_files"] = {
        "detail": gwas_detail_path,
        "summary": gwas_summary_path,
    }
    if gwas_file_errors:
        therapeutic_assessment["gwas_file_errors"] = gwas_file_errors

    return json.dumps(therapeutic_assessment, indent=2)

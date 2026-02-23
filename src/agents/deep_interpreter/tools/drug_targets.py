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

            # Compute association score for this disease
            association_score = 0.0
            associated_diseases = (
                target_info.get("associatedDiseases", {}).get("rows", [])
            )
            for assoc in associated_diseases:
                if assoc.get("disease", {}).get("id") == efo_id:
                    association_score = assoc.get("score", 0.0)
                    break

            # Summarize evidence types
            evidence_types = {}
            for ev in evidence:
                dtype = ev.get("datatypeId", "unknown")
                evidence_types[dtype] = evidence_types.get(dtype, 0) + 1

            results[gene] = {
                "ensembl_id": ensembl_id,
                "approved_symbol": target_info.get("approvedSymbol", gene),
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

    One-stop tool that evaluates hub genes (from top_search_genes.json) and
    novel L-R pair genes (from selected_top3_lr.json) for druggability via
    the Open Targets Platform. Falls back to LIANA CSV ranking if neither
    file is available.

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

    hub_set = set(hub_genes)
    gene_list = hub_genes + [g for g in novel_genes if g not in hub_set]
    gene_source = "top_search_genes+selected_top3_lr"

    # Fallback: if both files missing, use LIANA CSV ranking
    if not gene_list:
        gene_source = "liana_csv_fallback"
        logger.info("No top_search_genes.json or selected_top3_lr.json found, falling back to LIANA CSV ranking")
        liana_path = os.path.join(data_dir, "interest_sig_liana.csv")
        if not os.path.exists(liana_path):
            return json.dumps({
                "error": f"No gene source files found. Checked top_search_genes.json, selected_top3_lr.json, and {liana_path}",
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
    novel_lr_set = set(novel_genes)
    therapeutic_assessment = {
        "disease": disease,
        "efo_id": targets_result.get("efo_id", ""),
        "gene_source": gene_source,
        "hub_genes_count": len(hub_genes),
        "novel_lr_genes_count": len(novel_genes),
        "gene_ranking": {
            gene: {
                "druggability": targets_result.get("targets", {}).get(gene, {}),
                "from_hub_genes": gene in hub_set,
                "from_novel_lr": gene in novel_lr_set,
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
    therapeutic_assessment["summary"] = {
        "total_genes_evaluated": len(gene_list),
        "hub_genes_count": len(hub_genes),
        "novel_lr_genes_count": len(novel_genes),
        "gene_source": gene_source,
        "genes_found_in_opentargets": targets_result.get("genes_found", 0),
        "genes_failed": targets_result.get("genes_failed", []),
        "druggable_count": len(therapeutic_assessment["druggable_targets"]),
        "non_druggable_count": len(therapeutic_assessment["non_druggable_targets"]),
        "novel_target_count": len(therapeutic_assessment["novel_targets"]),
        "known_drugs_count": len(therapeutic_assessment["known_drugs"]),
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

    return json.dumps(therapeutic_assessment, indent=2)

"""OpenTargets Platform tool wrappers.

Wraps skills/opentargets-database/scripts/query_opentargets.py functions
as LangChain @tool decorated functions for use by the Evidence Collector subagent.
"""

import importlib.util
import json
import logging
from pathlib import Path
from typing import Optional

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Dynamic import from skill script (hyphens in dir names prevent normal imports)
_SKILL_PATH = Path(__file__).resolve().parents[4] / "skills" / "opentargets-database" / "scripts" / "query_opentargets.py"


def _load_ot_module():
    """Dynamically load the OpenTargets skill module."""
    spec = importlib.util.spec_from_file_location("query_opentargets", _SKILL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ot = _load_ot_module()
search_entities = _ot.search_entities
get_target_info = _ot.get_target_info
get_target_disease_evidence = _ot.get_target_disease_evidence
get_target_associations = _ot.get_target_associations
get_known_drugs_for_disease = _ot.get_known_drugs_for_disease
get_drug_info = _ot.get_drug_info


def _resolve_gene_to_ensembl(gene_symbol: str) -> Optional[str]:
    """Resolve a gene symbol to its Ensembl ID via OpenTargets search."""
    try:
        results = search_entities(gene_symbol, entity_types=["target"])
        for hit in results:
            # Prefer exact symbol match
            if hit.get("name", "").upper() == gene_symbol.upper():
                return hit["id"]
        # Fall back to first result if no exact match
        if results:
            return results[0]["id"]
    except Exception as e:
        logger.warning(f"Failed to resolve gene {gene_symbol}: {e}")
    return None


def _resolve_disease_to_efo(disease: str) -> Optional[str]:
    """Resolve a disease name to its EFO ID via OpenTargets search."""
    try:
        results = search_entities(disease, entity_types=["disease"])
        if results:
            return results[0]["id"]
    except Exception as e:
        logger.warning(f"Failed to resolve disease {disease}: {e}")
    return None


@tool
def query_ot_target_info(gene_symbol: str, disease: str) -> str:
    """Query OpenTargets for comprehensive target information.

    Resolves gene symbol to Ensembl ID, then retrieves:
    - Target info (tractability, safety, genetic constraint)
    - Disease-specific evidence (if disease resolves to EFO ID)
    - All disease associations for the target

    Args:
        gene_symbol: Gene symbol (e.g., "TGFB1", "CD274")
        disease: Disease name for context (e.g., "breast cancer")

    Returns:
        JSON string with target_info, disease_evidence, and associations
    """
    result = {
        "gene_symbol": gene_symbol,
        "disease": disease,
        "ensembl_id": None,
        "efo_id": None,
        "target_info": {},
        "disease_evidence": [],
        "associations": [],
        "errors": [],
    }

    # Resolve gene to Ensembl ID
    ensembl_id = _resolve_gene_to_ensembl(gene_symbol)
    if not ensembl_id:
        result["errors"].append(f"Could not resolve {gene_symbol} to Ensembl ID")
        return json.dumps(result, indent=2)
    result["ensembl_id"] = ensembl_id

    # Get target info with disease associations
    try:
        info = get_target_info(ensembl_id, include_diseases=True)
        result["target_info"] = info
    except Exception as e:
        result["errors"].append(f"get_target_info failed: {e}")

    # Resolve disease and get disease-specific evidence
    efo_id = _resolve_disease_to_efo(disease)
    if efo_id:
        result["efo_id"] = efo_id
        try:
            evidence = get_target_disease_evidence(ensembl_id, efo_id)
            result["disease_evidence"] = evidence
        except Exception as e:
            result["errors"].append(f"get_target_disease_evidence failed: {e}")

    # Get all associations (min_score=0.1 to filter noise)
    try:
        associations = get_target_associations(ensembl_id, min_score=0.1)
        result["associations"] = associations[:20]  # Top 20 associations
    except Exception as e:
        result["errors"].append(f"get_target_associations failed: {e}")

    return json.dumps(result, indent=2)


@tool
def query_ot_known_drugs(disease: str) -> str:
    """Query OpenTargets for known drugs targeting a disease.

    Resolves disease name to EFO ID and retrieves all known drugs
    including their phase, status, mechanism of action, and targets.

    Args:
        disease: Disease name (e.g., "breast cancer", "alzheimer's disease")

    Returns:
        JSON string with drug list including phase, targets, and mechanisms
    """
    result = {
        "disease": disease,
        "efo_id": None,
        "unique_drugs": 0,
        "unique_targets": 0,
        "drugs": [],
        "errors": [],
    }

    efo_id = _resolve_disease_to_efo(disease)
    if not efo_id:
        result["errors"].append(f"Could not resolve '{disease}' to EFO ID")
        return json.dumps(result, indent=2)
    result["efo_id"] = efo_id

    try:
        drugs_data = get_known_drugs_for_disease(efo_id)
        result["unique_drugs"] = drugs_data.get("uniqueDrugs", 0)
        result["unique_targets"] = drugs_data.get("uniqueTargets", 0)
        result["drugs"] = drugs_data.get("rows", [])
    except Exception as e:
        result["errors"].append(f"get_known_drugs_for_disease failed: {e}")

    return json.dumps(result, indent=2)


@tool
def query_ot_drug_details(chembl_id: str) -> str:
    """Query OpenTargets for detailed drug information.

    Retrieves drug details including mechanisms of action, indications,
    warnings, and clinical trial phase information.

    Args:
        chembl_id: ChEMBL identifier (e.g., "CHEMBL25", "CHEMBL1201607")

    Returns:
        JSON string with drug name, type, mechanisms, indications, warnings
    """
    result = {
        "chembl_id": chembl_id,
        "drug_info": {},
        "errors": [],
    }

    try:
        info = get_drug_info(chembl_id)
        result["drug_info"] = info
    except Exception as e:
        result["errors"].append(f"get_drug_info failed: {e}")

    return json.dumps(result, indent=2)

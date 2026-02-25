"""ChEMBL database tool wrappers.

Wraps skills/chembl-database/scripts/example_queries.py functions
as LangChain @tool decorated functions for use by the Evidence Collector subagent.
"""

import importlib.util
import json
import logging
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Dynamic import from skill script (hyphens in dir names prevent normal imports)
_SKILL_PATH = Path(__file__).resolve().parents[4] / "skills" / "chembl-database" / "scripts" / "example_queries.py"


def _import_chembl():
    """Lazy import of chembl skill functions with graceful fallback."""
    try:
        spec = importlib.util.spec_from_file_location("example_queries", _SKILL_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.search_targets_by_name, mod.get_bioactivity_data, mod.get_drug_info
    except Exception as e:
        logger.warning(f"ChEMBL client not available: {e}")
        return None, None, None


@tool
def query_chembl_target_bioactivity(gene_symbol: str) -> str:
    """Query ChEMBL for target bioactivity data.

    Searches for the gene as a target in ChEMBL, then retrieves
    bioactivity data (IC50 values) for matching targets.

    Args:
        gene_symbol: Gene symbol to search (e.g., "EGFR", "TGFB1")

    Returns:
        JSON with target matches and top bioactivity records
    """
    result = {
        "gene_symbol": gene_symbol,
        "targets": [],
        "bioactivity_count": 0,
        "top_activities": [],
        "errors": [],
    }

    search_targets, get_bioactivity, _ = _import_chembl()
    if search_targets is None:
        result["errors"].append("chembl_webresource_client not installed")
        return json.dumps(result, indent=2)

    # Search for targets
    try:
        targets = search_targets(gene_symbol)
        # Limit and extract key fields
        for t in targets[:5]:
            result["targets"].append({
                "chembl_id": t.get("target_chembl_id"),
                "name": t.get("pref_name"),
                "organism": t.get("organism"),
                "target_type": t.get("target_type"),
            })
    except Exception as e:
        result["errors"].append(f"search_targets_by_name failed: {e}")
        return json.dumps(result, indent=2)

    # Get bioactivity for the first matching target
    if result["targets"]:
        target_id = result["targets"][0]["chembl_id"]
        try:
            activities = get_bioactivity(target_id, activity_type="IC50", max_value=1000)
            result["bioactivity_count"] = len(activities)
            # Return top 10 most potent
            for act in sorted(activities, key=lambda x: float(x.get("standard_value", 999999)))[:10]:
                result["top_activities"].append({
                    "molecule_chembl_id": act.get("molecule_chembl_id"),
                    "molecule_name": act.get("molecule_pref_name"),
                    "activity_type": act.get("standard_type"),
                    "value_nM": act.get("standard_value"),
                    "pchembl": act.get("pchembl_value"),
                })
        except Exception as e:
            result["errors"].append(f"get_bioactivity_data failed: {e}")

    return json.dumps(result, indent=2)


@tool
def query_chembl_drug_info(chembl_id: str) -> str:
    """Query ChEMBL for detailed drug information.

    Retrieves drug metadata, mechanisms of action, and indications
    for a given ChEMBL molecule ID.

    Args:
        chembl_id: ChEMBL molecule identifier (e.g., "CHEMBL25")

    Returns:
        JSON with drug info, mechanisms, and indications
    """
    result = {
        "chembl_id": chembl_id,
        "drug_info": {},
        "mechanisms": [],
        "indications": [],
        "errors": [],
    }

    _, _, get_drug = _import_chembl()
    if get_drug is None:
        result["errors"].append("chembl_webresource_client not installed")
        return json.dumps(result, indent=2)

    try:
        drug_info, mechanisms, indications = get_drug(chembl_id)

        if drug_info:
            result["drug_info"] = {
                "name": drug_info.get("pref_name"),
                "max_phase": drug_info.get("max_phase"),
                "first_approval": drug_info.get("first_approval"),
                "indication_class": drug_info.get("indication_class"),
                "molecule_type": drug_info.get("molecule_type"),
                "withdrawn": drug_info.get("withdrawn_flag", False),
            }

        for m in mechanisms[:10]:
            result["mechanisms"].append({
                "action_type": m.get("action_type"),
                "mechanism": m.get("mechanism_of_action"),
                "target_name": m.get("target_pref_name"),
                "target_chembl_id": m.get("target_chembl_id"),
            })

        for ind in indications[:10]:
            result["indications"].append({
                "mesh_heading": ind.get("mesh_heading"),
                "max_phase": ind.get("max_phase_for_ind"),
                "efo_term": ind.get("efo_term"),
            })
    except Exception as e:
        result["errors"].append(f"get_drug_info failed: {e}")

    return json.dumps(result, indent=2)

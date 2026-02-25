"""ClinicalTrials.gov tool wrappers.

Wraps skills/clinicaltrials-database/scripts/query_clinicaltrials.py functions
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
_SKILL_PATH = Path(__file__).resolve().parents[4] / "skills" / "clinicaltrials-database" / "scripts" / "query_clinicaltrials.py"


def _load_ct_module():
    spec = importlib.util.spec_from_file_location("query_clinicaltrials", _SKILL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_ct = _load_ct_module()
search_studies = _ct.search_studies
extract_study_summary = _ct.extract_study_summary


@tool
def search_clinical_trials(
    disease: str,
    drug_name: Optional[str] = None,
    gene_symbol: Optional[str] = None,
) -> str:
    """Search ClinicalTrials.gov for relevant clinical trials.

    Searches by disease condition, optionally filtered by drug name
    or gene symbol. Returns trial count, phase distribution, status
    breakdown, and top trial summaries with NCT IDs.

    Args:
        disease: Disease or condition (e.g., "breast cancer")
        drug_name: Optional drug name filter (e.g., "trastuzumab")
        gene_symbol: Optional gene symbol to include in search (e.g., "HER2")

    Returns:
        JSON with trial_count, phase_distribution, status_breakdown, and top_trials
    """
    result = {
        "disease": disease,
        "drug_name": drug_name,
        "gene_symbol": gene_symbol,
        "trial_count": 0,
        "phase_distribution": {},
        "status_breakdown": {},
        "top_trials": [],
        "errors": [],
    }

    # Build intervention query combining drug and gene if provided
    intervention = None
    if drug_name and gene_symbol:
        intervention = f"{drug_name} OR {gene_symbol}"
    elif drug_name:
        intervention = drug_name
    elif gene_symbol:
        intervention = gene_symbol

    try:
        response = search_studies(
            condition=disease,
            intervention=intervention,
            page_size=50,
        )

        studies = response.get("studies", [])
        total = response.get("totalCount")

        # API versions can omit totalCount; fall back to current page size.
        if isinstance(total, int):
            result["trial_count"] = total
        elif isinstance(total, str) and total.isdigit():
            result["trial_count"] = int(total)
        else:
            result["trial_count"] = len(studies)

        # Aggregate phase and status distributions
        phase_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}

        for study in studies:
            summary = extract_study_summary(study)

            # Phase distribution
            phases = summary.get("phase", [])
            for phase in phases:
                phase_counts[phase] = phase_counts.get(phase, 0) + 1

            # Status breakdown
            status = summary.get("status", "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1

            # Collect top trials (first 10)
            if len(result["top_trials"]) < 10:
                result["top_trials"].append({
                    "nct_id": summary.get("nct_id"),
                    "title": summary.get("title"),
                    "status": status,
                    "phase": phases,
                    "enrollment": summary.get("enrollment"),
                })

        result["phase_distribution"] = phase_counts
        result["status_breakdown"] = status_counts

    except Exception as e:
        result["errors"].append(f"search_studies failed: {e}")

    return json.dumps(result, indent=2)

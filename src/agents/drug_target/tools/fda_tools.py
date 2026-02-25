"""FDA openFDA API tool wrappers.

Wraps skills/fda-database/scripts/fda_query.py functions
as LangChain @tool decorated functions for use by the Evidence Collector subagent.
"""

import importlib.util
import json
import logging
import os
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Dynamic import from skill script (hyphens in dir names prevent normal imports)
_SKILL_PATH = Path(__file__).resolve().parents[4] / "skills" / "fda-database" / "scripts" / "fda_query.py"


def _load_fda_module():
    spec = importlib.util.spec_from_file_location("fda_query", _SKILL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_fda_mod = _load_fda_module()
FDAQuery = _fda_mod.FDAQuery

# Module-level FDA client (lazy init, no caching to avoid disk writes)
_fda_client: FDAQuery | None = None


def _get_fda_client() -> FDAQuery:
    """Get or create the FDA query client."""
    global _fda_client
    if _fda_client is None:
        api_key = os.environ.get("FDA_API_KEY")
        _fda_client = FDAQuery(api_key=api_key, use_cache=False)
    return _fda_client


@tool
def query_fda_drug_label(drug_name: str) -> str:
    """Query FDA for drug labeling information.

    Retrieves indications, warnings, contraindications, and adverse
    reactions from the FDA drug label for a given drug name.

    Args:
        drug_name: Drug name (brand or generic, e.g., "Herceptin", "trastuzumab")

    Returns:
        JSON with indications, warnings, contraindications, adverse_reactions
    """
    result = {
        "drug_name": drug_name,
        "label_found": False,
        "indications": "",
        "warnings": "",
        "contraindications": "",
        "adverse_reactions": "",
        "errors": [],
    }

    fda = _get_fda_client()

    # Try brand name first, then generic
    for brand in (True, False):
        try:
            data = fda.query_drug_label(drug_name, brand=brand)
            if "error" in data:
                continue

            results = data.get("results", [])
            if not results:
                continue

            label = results[0]
            result["label_found"] = True

            # Extract key sections (each is a list of strings)
            def _extract(field: str) -> str:
                values = label.get(field, [])
                if values:
                    return values[0][:2000]  # Truncate long text
                return ""

            result["indications"] = _extract("indications_and_usage")
            result["warnings"] = _extract("warnings")
            result["contraindications"] = _extract("contraindications")
            result["adverse_reactions"] = _extract("adverse_reactions")
            break

        except Exception as e:
            result["errors"].append(f"query_drug_label (brand={brand}) failed: {e}")

    return json.dumps(result, indent=2)


@tool
def query_fda_adverse_events(drug_name: str) -> str:
    """Query FDA for drug adverse event reports.

    Retrieves the top adverse reactions reported for a drug, with
    counts and patient outcome information.

    Args:
        drug_name: Drug name (e.g., "aspirin", "Keytruda")

    Returns:
        JSON with total_events and top_reactions (reaction name + count)
    """
    result = {
        "drug_name": drug_name,
        "total_events": 0,
        "top_reactions": [],
        "errors": [],
    }

    fda = _get_fda_client()

    try:
        # Get adverse event counts by reaction
        search = f"patient.drug.medicinalproduct:*{drug_name}*"
        data = fda.query(
            "drug", "event",
            search=search,
            count="patient.reaction.reactionmeddrapt.exact",
        )

        if "error" in data:
            result["errors"].append(data["error"])
            return json.dumps(result, indent=2)

        counts = data.get("results", [])
        result["total_events"] = sum(c.get("count", 0) for c in counts)

        # Top 20 reactions
        for item in counts[:20]:
            result["top_reactions"].append({
                "reaction": item.get("term"),
                "count": item.get("count"),
            })

    except Exception as e:
        result["errors"].append(f"query_drug_events failed: {e}")

    return json.dumps(result, indent=2)

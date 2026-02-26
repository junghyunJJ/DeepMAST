"""Tool wrappers for Drug Target Assessment Agent.

Each wrapper imports functions from skill Python scripts and exposes
them as @tool decorated functions. Skills are NOT modified - only
imported and wrapped.
"""

from src.agents.drug_target.tools.opentargets_tools import (
    query_ot_target_info,
    query_ot_known_drugs,
    query_ot_drug_details,
)
from src.agents.drug_target.tools.gwas_tools import (
    query_gwas_trait_associations,
    query_gwas_variant_details,
)
from src.agents.drug_target.tools.chembl_tools import (
    query_chembl_target_bioactivity,
    query_chembl_drug_info,
)
from src.agents.drug_target.tools.clinical_trials_tools import (
    search_clinical_trials,
)
from src.agents.drug_target.tools.fda_tools import (
    query_fda_drug_label,
    query_fda_adverse_events,
)
from src.agents.drug_target.tools.evidence_loader import (
    load_lr_candidates,
    load_evidence_files,
    save_evidence,
)
# Common tools use lazy imports to break circular dependency chain.
# sequential_thinking is defined in common.py; think_tool and validate_quality
# are lazy re-exports from deep_interpreter.
from src.agents.drug_target.tools.common import sequential_thinking  # noqa: F401


def __getattr__(name):
    """Lazy imports for think_tool and validate_quality to break circular chain."""
    if name == "think_tool":
        from src.agents.drug_target.tools.common import think_tool
        return think_tool
    if name == "validate_quality":
        from src.agents.drug_target.tools.common import validate_quality
        return validate_quality
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # OpenTargets
    "query_ot_target_info",
    "query_ot_known_drugs",
    "query_ot_drug_details",
    # GWAS
    "query_gwas_trait_associations",
    "query_gwas_variant_details",
    # ChEMBL
    "query_chembl_target_bioactivity",
    "query_chembl_drug_info",
    # Clinical Trials
    "search_clinical_trials",
    # FDA
    "query_fda_drug_label",
    "query_fda_adverse_events",
    # Evidence loader
    "load_lr_candidates",
    "load_evidence_files",
    "save_evidence",
    # Common
    "think_tool",
    "sequential_thinking",
    "validate_quality",
]

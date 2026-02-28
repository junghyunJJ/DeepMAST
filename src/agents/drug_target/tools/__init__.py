"""Tool wrappers for Drug Target Assessment Agent.

Infrastructure tools for evidence I/O, stage logic, and structural biology.
All database queries (including OpenTargets and GWAS) are wrapped as @tool
functions for consistent invocation by subagents.
"""

from src.agents.drug_target.tools.evidence_loader import (
    load_lr_candidates,
    load_evidence_files,
    save_evidence,
)
from src.agents.drug_target.tools.assessment_output import (
    save_target_assessment,
)
from src.agents.drug_target.tools.stage_domain_tools import (
    query_cellxgene_lr_context,
    query_kegg_pathways,
    query_reactome_pathways,
    query_string_ppi_pair,
    query_ensembl_vep_consequence,
    query_opentargets_target,
    query_opentargets_known_drugs,
    query_gwas_gene_trait,
    query_drugbank_target_profile,
    query_pubmed_clinical_limitations,
    query_alphafold_plddt,
    run_diffdock_screen,
)
from src.agents.drug_target.tools.census_lr_validation_tools import (
    run_compare_census_lr_pair,
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
    # Evidence loader
    "load_lr_candidates",
    "load_evidence_files",
    "save_evidence",
    # Stage-specific domain tools
    "query_cellxgene_lr_context",
    "query_kegg_pathways",
    "query_reactome_pathways",
    "query_string_ppi_pair",
    "query_ensembl_vep_consequence",
    "query_opentargets_target",
    "query_opentargets_known_drugs",
    "query_gwas_gene_trait",
    "query_drugbank_target_profile",
    "query_pubmed_clinical_limitations",
    "query_alphafold_plddt",
    "run_diffdock_screen",
    "run_compare_census_lr_pair",
    # Output contract
    "save_target_assessment",
    # Common
    "think_tool",
    "sequential_thinking",
    "validate_quality",
]

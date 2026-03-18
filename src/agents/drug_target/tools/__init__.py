"""Tool wrappers for Drug Target Assessment Agent.

Infrastructure tools for evidence I/O and stage logic.
All database queries (including OpenTargets and GWAS) are wrapped as @tool
functions for consistent invocation by subagents.
"""

from src.agents.drug_target.tools.evidence_loader import (
    load_lr_candidates,
    load_evidence_files,
    save_evidence,
    validate_evidence_completeness,
)
from src.agents.drug_target.tools.assessment_output import (
    save_target_assessment,
    save_drug_md,
)
from src.agents.drug_target.tools.stage1_normalization import (
    finalize_stage1_artifacts,
)
from src.agents.drug_target.tools.stage_domain_tools import (
    query_cellxgene_lr_context,
    list_census_diseases,
    query_kegg_pathways,
    query_reactome_pathways,
    query_string_ppi_pair,
    query_ensembl_vep_consequence,
    query_opentargets_target,
    query_opentargets_known_drugs,
    query_gwas_gene_trait,
    query_stage2_gene_panel,
    query_chembl_target_profile,
    query_pubmed_clinical_limitations,
)
from src.agents.drug_target.tools.census_lr_validation_tools import (
    run_compare_census_lr_pair,
)
from src.agents.drug_target.tools.skill_reader import (
    read_skill_file,
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
    "validate_evidence_completeness",
    # Stage-specific domain tools
    "query_cellxgene_lr_context",
    "list_census_diseases",
    "query_kegg_pathways",
    "query_reactome_pathways",
    "query_string_ppi_pair",
    "query_ensembl_vep_consequence",
    "query_opentargets_target",
    "query_opentargets_known_drugs",
    "query_gwas_gene_trait",
    "query_stage2_gene_panel",
    "query_chembl_target_profile",
    "query_pubmed_clinical_limitations",
    "run_compare_census_lr_pair",
    "read_skill_file",
    "finalize_stage1_artifacts",
    # Output contract
    "save_target_assessment",
    "save_drug_md",
    # Common
    "think_tool",
    "sequential_thinking",
    "validate_quality",
]

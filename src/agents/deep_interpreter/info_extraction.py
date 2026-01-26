"""Pydantic model for Deep Interpreter information extraction.

This module defines the tool schema used by the wrapper agent to collect
essential information from the user before invoking the Deep Agent.

The DeepInterpreterInfoExtraction model ensures that either clusters (Mode A)
or cell types (Mode B) are provided, but not both or neither.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class DeepInterpreterInfoExtraction(BaseModel):
    """Tool schema for collecting Deep Interpreter analysis information.

    This schema is bound to the LLM as a tool for structured extraction
    of analysis configuration from user input.

    Attributes:
        data_directory: Path to analysis results directory (res/ folder)
        analysis_mode: Analysis mode (cluster_to_celltype or celltype_to_cluster)
        interest_clusters: Clusters of interest for Mode A analysis
        interest_celltypes: Cell types of interest for Mode B analysis

    Validation:
        Exactly one of interest_clusters or interest_celltypes must be provided.
    """

    data_directory: str = Field(
        description=(
            "Path to CCI analysis results directory (res/ folder). "
            "This folder should contain figures (1.spatial.png, etc.) and CSV files "
            "(sig_liana.csv, res_nhood_enrichment.csv, etc.)."
        )
    )

    analysis_mode: Literal["cluster_to_celltype", "celltype_to_cluster"] = Field(
        description=(
            "Analysis mode selection: "
            "'cluster_to_celltype' (Mode A) starts from spatial clusters, derives cell type annotations. "
            "'celltype_to_cluster' (Mode B) starts from known cell types, identifies spatial organization."
        )
    )

    interest_clusters: Optional[list[str]] = Field(
        default=None,
        description=(
            "Clusters of interest for Mode A (cluster_to_celltype) analysis. "
            "Example: ['4', '16', '176']. "
            "Provide this when analysis_mode is 'cluster_to_celltype'."
        ),
    )

    interest_celltypes: Optional[list[str]] = Field(
        default=None,
        description=(
            "Cell types of interest for Mode B (celltype_to_cluster) analysis. "
            "Example: ['Invasive Tumor', 'Fibroblast', 'Macrophage']. "
            "Provide this when analysis_mode is 'celltype_to_cluster'."
        ),
    )

    @model_validator(mode="after")
    def validate_targets(self) -> "DeepInterpreterInfoExtraction":
        """Ensure targets are consistent with the selected analysis mode.

        Raises:
            ValueError: If targets don't match the selected mode
        """
        has_clusters = (
            self.interest_clusters is not None and len(self.interest_clusters) > 0
        )
        has_celltypes = (
            self.interest_celltypes is not None and len(self.interest_celltypes) > 0
        )

        if self.analysis_mode == "cluster_to_celltype":
            if not has_clusters:
                raise ValueError(
                    "Mode A (cluster_to_celltype) requires interest_clusters. "
                    "Provide a list of cluster IDs, e.g., ['4', '16', '176']."
                )
            if has_celltypes:
                # Clear celltypes for Mode A
                self.interest_celltypes = None
        else:  # celltype_to_cluster
            if not has_celltypes:
                raise ValueError(
                    "Mode B (celltype_to_cluster) requires interest_celltypes. "
                    "Provide a list of cell type names, e.g., ['Tumor', 'Fibroblast']."
                )
            if has_clusters:
                # Clear clusters for Mode B
                self.interest_clusters = None

        return self

    def to_targets_dict(self) -> dict:
        """Convert to targets.json format for Deep Agent consumption.

        Returns:
            Dictionary in the format expected by /targets.json
        """
        return {
            "analysis_mode": self.analysis_mode,
            "interest_clusters": self.interest_clusters,
            "interest_celltypes": self.interest_celltypes,
            "data_directory": self.data_directory,
            "user_confirmed": True,
        }


__all__ = ["DeepInterpreterInfoExtraction"]

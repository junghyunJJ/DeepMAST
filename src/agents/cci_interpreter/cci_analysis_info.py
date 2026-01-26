"""Pydantic model for CCI analysis information collection.

This module defines the tool schema used by the wrapper agent to collect
essential information from the user before invoking the Deep Agent.

The CCIAnalysisInfo model ensures that either clusters (Mode A) or
cell types (Mode B) are provided, but not both or neither.
"""

from typing import Optional

from pydantic import BaseModel, Field, model_validator


class CCIAnalysisInfo(BaseModel):
    """Tool schema for collecting CCI analysis information.

    This schema is bound to the LLM as a tool for structured extraction
    of analysis configuration from user input.

    Attributes:
        data_directory: Path to analysis results directory (res/ folder)
        interest_clusters: Clusters of interest for Mode A analysis
        interest_celltypes: Cell types of interest for Mode B analysis

    Validation:
        Exactly one of interest_clusters or interest_celltypes must be provided.
    """

    data_directory: str = Field(
        description=(
            "Path to analysis results directory containing figures and CSVs. "
            "This is typically the res/ folder with files like "
            "1.spatial.png, sig_liana.csv, etc."
        )
    )

    interest_clusters: Optional[list[str]] = Field(
        default=None,
        description=(
            "Clusters of interest for Mode A (cluster_to_celltype) analysis. "
            "Example: ['4', '16', '176']. "
            "Provide this OR interest_celltypes, not both."
        ),
    )

    interest_celltypes: Optional[list[str]] = Field(
        default=None,
        description=(
            "Cell types of interest for Mode B (celltype_to_cluster) analysis. "
            "Example: ['Invasive Tumor', 'Fibroblast', 'Macrophage']. "
            "Provide this OR interest_clusters, not both."
        ),
    )

    @model_validator(mode="after")
    def validate_targets(self) -> "CCIAnalysisInfo":
        """Ensure exactly one of clusters or celltypes is provided.

        Raises:
            ValueError: If both or neither targets are provided
        """
        has_clusters = (
            self.interest_clusters is not None and len(self.interest_clusters) > 0
        )
        has_celltypes = (
            self.interest_celltypes is not None and len(self.interest_celltypes) > 0
        )

        if has_clusters and has_celltypes:
            raise ValueError(
                "Provide either interest_clusters (Mode A) OR "
                "interest_celltypes (Mode B), not both."
            )

        if not has_clusters and not has_celltypes:
            raise ValueError(
                "Must provide either interest_clusters (Mode A) or "
                "interest_celltypes (Mode B)."
            )

        return self

    @property
    def analysis_mode(self) -> str:
        """Determine the analysis mode based on provided targets.

        Returns:
            'cluster_to_celltype' for Mode A (clusters provided)
            'celltype_to_cluster' for Mode B (cell types provided)
        """
        if self.interest_clusters is not None and len(self.interest_clusters) > 0:
            return "cluster_to_celltype"
        return "celltype_to_cluster"

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


__all__ = ["CCIAnalysisInfo"]

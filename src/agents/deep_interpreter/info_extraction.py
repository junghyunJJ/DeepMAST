"""Pydantic model for Deep Interpreter information extraction.

This module defines the tool schema used by the wrapper agent to collect
essential information from the user before running the spatial analysis pipeline.

The DeepInterpreterInfoExtraction model collects h5ad file paths, cluster/celltype
keys, sample information, and output directory configuration.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class DeepInterpreterInfoExtraction(BaseModel):
    """Tool schema for collecting Deep Interpreter configuration.

    This schema is bound to the LLM as a tool for structured extraction
    of analysis configuration from user input.

    Attributes:
        st_technology: ST platform (may come pre-populated from Supervisor)
        disease: Disease/phenotype being studied
        species: Organism species
        sample_count: Number of samples in dataset
        h5ad_files: Path(s) to .h5ad file(s)
        cluster_key: Column name in adata.obs for cluster assignments
        celltype_key: Column in adata.obs for cell type annotations
        sample_key: Column for sample ID (required if sample_count > 1)
        interest_sample: Specific sample to analyze in multi-sample datasets
        data_directory: Output directory for results (res/ folder)

    Validation:
        - sample_key required when sample_count > 1
        - celltype_key required for single-cell resolution platforms
    """

    # Shared fields (may come pre-populated from Supervisor)
    st_technology: Optional[str] = Field(
        default=None,
        description="ST platform (Visium, MERFISH, Xenium, CosMx, seqFISH, etc.)",
    )
    disease: Optional[str] = Field(
        default=None,
        description="Disease/phenotype being studied",
    )
    species: Optional[Literal["human", "mouse"]] = Field(
        default=None,
        description="Organism species",
    )
    sample_count: Optional[int] = Field(
        default=None,
        gt=0,
        description="Number of samples in dataset",
    )

    # Required fields
    h5ad_files: list[str] = Field(
        description=(
            "Path(s) to .h5ad file(s). "
            "Example: ['/path/to/n_adata.h5ad'] or ['/path/to/sample1.h5ad', '/path/to/sample2.h5ad']"
        ),
    )
    cluster_key: str = Field(
        description=(
            "Column name in adata.obs for cluster assignments. "
            "Example: 'leiden', 'louvain', 'clusters'"
        ),
    )
    celltype_key: Optional[str] = Field(
        default=None,
        description=(
            "Column in adata.obs for cell type annotations. "
            "Required for single-cell resolution platforms (MERFISH, Xenium, CosMx, seqFISH). "
            "Optional for Visium (spot-based)."
        ),
    )
    sample_key: Optional[str] = Field(
        default=None,
        description=(
            "Column for sample ID in adata.obs. "
            "Required when sample_count > 1. "
            "Example: 'sample', 'batch', 'sample_id'"
        ),
    )
    interest_sample: Optional[str] = Field(
        default=None,
        description=(
            "Specific sample to analyze in multi-sample datasets (for run_lianap Step 6). "
            "Example: 'sample_1', 'tumor_A'"
        ),
    )
    data_directory: str = Field(
        description=(
            "Output directory for analysis results (res/ folder). "
            "All figures, CSVs, and intermediate files will be saved here. "
            "Example: '/path/to/results/res'"
        ),
    )

    @model_validator(mode="after")
    def validate_multi_sample(self) -> "DeepInterpreterInfoExtraction":
        """Ensure sample_key is provided for multi-sample datasets."""
        if self.sample_count and self.sample_count > 1 and not self.sample_key:
            raise ValueError(
                "sample_key is required when sample_count > 1. "
                "Provide the column name in adata.obs that identifies samples."
            )
        return self

    @model_validator(mode="after")
    def validate_celltype_key(self) -> "DeepInterpreterInfoExtraction":
        """Ensure celltype_key is provided for single-cell resolution platforms."""
        single_cell_platforms = {"merfish", "xenium", "cosmx", "seqfish", "starmap"}
        if (
            self.st_technology
            and self.st_technology.lower() in single_cell_platforms
            and not self.celltype_key
        ):
            raise ValueError(
                f"celltype_key is required for single-cell resolution platform: {self.st_technology}. "
                "Provide the column name in adata.obs for cell type annotations."
            )
        return self


__all__ = ["DeepInterpreterInfoExtraction"]

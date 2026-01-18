"""Part 1 Analysis Tools for Biological Interpreter Agent.

Part 1 analyses use normalized adata (n_adata.h5ad) and can run in parallel.
These tools generate spatial and cell type composition analyses before CCI.

Tools:
1. tool_run_spatial_plot - Step 1: Spatial clustering visualization
2. tool_run_celltype_analysis - Step 2: Cell type composition heatmap
3. tool_run_neighborhood_enrichment - Step 3: Spatial neighborhood enrichment
4. tool_run_pathway_enrichment - Step 4: Pathway activity (decoupler)
5. tool_run_misty_analysis - Step 5: Spatial relationships (MISTy)
"""

import os
import sys
import logging
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Add mcp_servers to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))))


# =============================================================================
# Input Schemas
# =============================================================================

class SpatialPlotInput(BaseModel):
    """Input for spatial plot tool."""
    adata_path: str = Field(description="Path to normalized adata (n_adata.h5ad)")
    cluster_key: str = Field(default="celltype_niche", description="Cluster column name")
    results_dir: str = Field(default="res/", description="Output directory")


class CelltypeAnalysisInput(BaseModel):
    """Input for cell type analysis tool."""
    adata_path: str = Field(description="Path to normalized adata (n_adata.h5ad)")
    cluster_key: str = Field(default="celltype_niche", description="Cluster column name")
    celltype_key: str | None = Field(default=None, description="Cell type column (for single-cell data)")
    results_dir: str = Field(default="res/", description="Output directory")


class NeighborhoodEnrichmentInput(BaseModel):
    """Input for neighborhood enrichment tool."""
    adata_path: str = Field(description="Path to normalized adata (n_adata.h5ad)")
    cluster_key: str = Field(default="celltype_niche", description="Cluster column name")
    n_rings: int = Field(default=2, description="Number of spatial neighbor rings")
    results_dir: str = Field(default="res/", description="Output directory")


class PathwayEnrichmentInput(BaseModel):
    """Input for pathway enrichment tool."""
    adata_path: str = Field(description="Path to normalized adata (n_adata.h5ad)")
    cluster_key: str = Field(default="celltype_niche", description="Cluster column name")
    organism: Literal['human', 'mouse'] = Field(default='human', description="Organism")
    geneset: Literal['progeny', 'hallmark'] = Field(default='progeny', description="Pathway geneset")
    results_dir: str = Field(default="res/", description="Output directory")


class MistyAnalysisInput(BaseModel):
    """Input for MISTy analysis tool."""
    adata_path: str = Field(description="Path to normalized adata (n_adata.h5ad)")
    cluster_key: str = Field(default="celltype_niche", description="Cluster column name")
    organism: Literal['human', 'mouse'] = Field(default='human', description="Organism")
    geneset: Literal['progeny', 'hallmark'] = Field(default='progeny', description="Pathway geneset")
    results_dir: str = Field(default="res/", description="Output directory")


# =============================================================================
# Tool Implementations
# =============================================================================

@tool(args_schema=SpatialPlotInput)
def tool_run_spatial_plot(
    adata_path: str,
    cluster_key: str = "celltype_niche",
    results_dir: str = "res/"
) -> dict:
    """Run spatial clustering visualization (Step 1).

    Generates basic spatial plot showing cluster distribution across tissue.
    Output: 1.spatial.png

    This is Part 1 analysis that can run in parallel with other Part 1 tools.
    """
    try:
        from mcp_servers.runplot_basic import plot_cluster

        os.makedirs(results_dir, exist_ok=True)

        plot_cluster(
            filename=adata_path,
            cluster_key=cluster_key,
            save_path=results_dir
        )

        output_file = os.path.join(results_dir, "1.spatial.png")
        if os.path.exists(output_file):
            return {
                "success": True,
                "step": 1,
                "analysis": "spatial",
                "output_files": [output_file],
                "message": f"Spatial plot generated: {output_file}"
            }
        else:
            return {
                "success": False,
                "step": 1,
                "analysis": "spatial",
                "error": "Output file not created"
            }

    except Exception as e:
        logger.error(f"Spatial plot failed: {e}")
        return {
            "success": False,
            "step": 1,
            "analysis": "spatial",
            "error": str(e),
            "skipped": True,
            "message": "Analysis skipped due to error, continuing with available data"
        }


@tool(args_schema=CelltypeAnalysisInput)
def tool_run_celltype_analysis(
    adata_path: str,
    cluster_key: str = "celltype_niche",
    celltype_key: str | None = None,
    results_dir: str = "res/"
) -> dict:
    """Run cell type composition analysis (Step 2).

    Generates heatmap of cell type compositions within each cluster.
    Asterisks indicate significant enrichment (FDR < 0.05).

    Outputs:
    - 2.celltype_heatmap_analysis.png
    - sig_clusterwithcelltyp.csv

    This is Part 1 analysis that can run in parallel with other Part 1 tools.
    """
    try:
        from mcp_servers.runplot_basic import runplot_clusterwithcelltyp

        os.makedirs(results_dir, exist_ok=True)

        runplot_clusterwithcelltyp(
            filename=adata_path,
            cluster_key=cluster_key,
            celltype_key=celltype_key,
            save_path=results_dir
        )

        output_files = [
            os.path.join(results_dir, "2.celltype_heatmap_analysis.png"),
            os.path.join(results_dir, "sig_clusterwithcelltyp.csv"),
        ]

        existing_files = [f for f in output_files if os.path.exists(f)]

        if existing_files:
            return {
                "success": True,
                "step": 2,
                "analysis": "celltype",
                "output_files": existing_files,
                "message": f"Cell type analysis complete: {len(existing_files)} files generated"
            }
        else:
            return {
                "success": False,
                "step": 2,
                "analysis": "celltype",
                "error": "Output files not created"
            }

    except Exception as e:
        logger.error(f"Cell type analysis failed: {e}")
        return {
            "success": False,
            "step": 2,
            "analysis": "celltype",
            "error": str(e),
            "skipped": True,
            "message": "Analysis skipped due to error, continuing with available data"
        }


@tool(args_schema=NeighborhoodEnrichmentInput)
def tool_run_neighborhood_enrichment(
    adata_path: str,
    cluster_key: str = "celltype_niche",
    n_rings: int = 2,
    results_dir: str = "res/"
) -> dict:
    """Run neighborhood enrichment analysis (Step 3).

    Computes spatial neighborhood enrichment using Squidpy to identify
    clusters that share common spatial neighborhoods.

    Outputs:
    - 3.neighborhood_enrichment_squidpy.png
    - res_nhood_enrichment.csv

    This is Part 1 analysis that can run in parallel with other Part 1 tools.
    """
    try:
        from mcp_servers.runplot_NeighborEnrich import plot_neighborhood_enrichment

        os.makedirs(results_dir, exist_ok=True)

        plot_neighborhood_enrichment(
            filename=adata_path,
            cluster_key=cluster_key,
            n_rings=n_rings,
            save_path=results_dir
        )

        output_files = [
            os.path.join(results_dir, "3.neighborhood_enrichment_squidpy.png"),
            os.path.join(results_dir, "res_nhood_enrichment.csv"),
        ]

        existing_files = [f for f in output_files if os.path.exists(f)]

        if existing_files:
            return {
                "success": True,
                "step": 3,
                "analysis": "nhood",
                "output_files": existing_files,
                "message": f"Neighborhood enrichment complete: {len(existing_files)} files generated"
            }
        else:
            return {
                "success": False,
                "step": 3,
                "analysis": "nhood",
                "error": "Output files not created"
            }

    except Exception as e:
        logger.error(f"Neighborhood enrichment failed: {e}")
        return {
            "success": False,
            "step": 3,
            "analysis": "nhood",
            "error": str(e),
            "skipped": True,
            "message": "Analysis skipped due to error, continuing with available data"
        }


@tool(args_schema=PathwayEnrichmentInput)
def tool_run_pathway_enrichment(
    adata_path: str,
    cluster_key: str = "celltype_niche",
    organism: Literal['human', 'mouse'] = 'human',
    geneset: Literal['progeny', 'hallmark'] = 'progeny',
    results_dir: str = "res/"
) -> dict:
    """Run pathway enrichment analysis with decoupler (Step 4).

    Computes pathway activity scores per cluster using multivariate
    linear model (MLM) with PROGENy or Hallmark gene sets.

    Outputs:
    - 4.spatial_enrich_decoupler.png
    - sig_PathwayEnrich_decoupler.csv

    This is Part 1 analysis that can run in parallel with other Part 1 tools.
    """
    try:
        from mcp_servers.utils.run_decoupler import sp_enrich
        import scanpy as sc
        import pandas as pd
        import matplotlib.pyplot as plt

        os.makedirs(results_dir, exist_ok=True)

        # Load adata
        adata = sc.read_h5ad(adata_path)

        # Run pathway enrichment
        adata_dc = sp_enrich(
            adata,
            cluster_key=cluster_key,
            organism=organism,
            geneset=geneset,
            min_n=5
        )

        # Extract significant pathways per cluster
        # Get pathway scores from adata_dc.obsm
        if 'progeny_mlm_estimate' in adata_dc.obsm:
            pathway_scores = pd.DataFrame(
                adata_dc.obsm['progeny_mlm_estimate'],
                index=adata_dc.obs.index,
                columns=adata_dc.uns['progeny_mlm_estimate_names']
            )
        elif 'hallmark_mlm_estimate' in adata_dc.obsm:
            pathway_scores = pd.DataFrame(
                adata_dc.obsm['hallmark_mlm_estimate'],
                index=adata_dc.obs.index,
                columns=adata_dc.uns['hallmark_mlm_estimate_names']
            )
        else:
            # Fallback to generic approach
            pathway_keys = [k for k in adata_dc.obsm.keys() if 'mlm_estimate' in k]
            if pathway_keys:
                key = pathway_keys[0]
                pathway_scores = pd.DataFrame(
                    adata_dc.obsm[key],
                    index=adata_dc.obs.index
                )
            else:
                raise ValueError("No pathway scores found in adata")

        # Add cluster info
        pathway_scores[cluster_key] = adata_dc.obs[cluster_key].values

        # Calculate cluster medians
        cluster_medians = pathway_scores.groupby(cluster_key).median()

        # Create heatmap
        fig, ax = plt.subplots(figsize=(10, 8))
        import seaborn as sns
        sns.heatmap(cluster_medians.T, cmap='RdBu_r', center=0, ax=ax)
        ax.set_title(f'Pathway Activity by Cluster ({geneset})')
        plt.tight_layout()
        plt.savefig(os.path.join(results_dir, "4.spatial_enrich_decoupler.png"), dpi=300, bbox_inches='tight')
        plt.close()

        # Save significant results (pathways with high variance)
        pathway_var = cluster_medians.var()
        sig_pathways = pathway_var[pathway_var > pathway_var.median()].index.tolist()

        sig_results = cluster_medians[sig_pathways].reset_index()
        sig_results = sig_results.melt(id_vars=[cluster_key], var_name='name', value_name='score')
        sig_results.to_csv(os.path.join(results_dir, "sig_PathwayEnrich_decoupler.csv"), index=False)

        output_files = [
            os.path.join(results_dir, "4.spatial_enrich_decoupler.png"),
            os.path.join(results_dir, "sig_PathwayEnrich_decoupler.csv"),
        ]

        existing_files = [f for f in output_files if os.path.exists(f)]

        return {
            "success": True,
            "step": 4,
            "analysis": "decoupler",
            "output_files": existing_files,
            "message": f"Pathway enrichment complete: {len(existing_files)} files generated"
        }

    except Exception as e:
        logger.error(f"Pathway enrichment failed: {e}")
        return {
            "success": False,
            "step": 4,
            "analysis": "decoupler",
            "error": str(e),
            "skipped": True,
            "message": "Analysis skipped due to error, continuing with available data"
        }


@tool(args_schema=MistyAnalysisInput)
def tool_run_misty_analysis(
    adata_path: str,
    cluster_key: str = "celltype_niche",
    organism: Literal['human', 'mouse'] = 'human',
    geneset: Literal['progeny', 'hallmark'] = 'progeny',
    results_dir: str = "res/"
) -> dict:
    """Run MISTy spatial relationship analysis (Step 5).

    Computes spatial relationships between pathways and cell types
    using MISTy (Multiview Intercellular SpaTial modeling framework).

    Outputs:
    - 5.spatial_relation_MISTy.png
    - res_SpatialRelationship_MISTy.csv

    This is Part 1 analysis that can run in parallel with other Part 1 tools.

    Note: This analysis may require R with mistyR package installed.
    If R is not available, the tool will skip gracefully.
    """
    try:
        from mcp_servers.utils.run_misty import sp_relation
        import scanpy as sc
        import pandas as pd
        import matplotlib.pyplot as plt

        os.makedirs(results_dir, exist_ok=True)

        # Load adata
        adata = sc.read_h5ad(adata_path)

        # Run MISTy analysis
        misty_results = sp_relation(
            adata,
            cluster_key=cluster_key,
            organism=organism,
            geneset=geneset,
            model='rf',
            min_n=5
        )

        # Check if misty_results is a DataFrame or dict
        if isinstance(misty_results, pd.DataFrame):
            misty_df = misty_results
        elif isinstance(misty_results, dict) and 'results' in misty_results:
            misty_df = misty_results['results']
        else:
            # Try to extract from adata.uns
            if 'misty_results' in adata.uns:
                misty_df = pd.DataFrame(adata.uns['misty_results'])
            else:
                raise ValueError("MISTy results not found")

        # Save results
        misty_df.to_csv(os.path.join(results_dir, "res_SpatialRelationship_MISTy.csv"), index=False)

        # Create visualization
        if not misty_df.empty:
            fig, ax = plt.subplots(figsize=(10, 8))

            # Create pivot table for heatmap if possible
            if 'target' in misty_df.columns and 'predictor' in misty_df.columns:
                pivot_df = misty_df.pivot_table(
                    index='target',
                    columns='predictor',
                    values='importance' if 'importance' in misty_df.columns else misty_df.columns[-1],
                    aggfunc='mean'
                )
                import seaborn as sns
                sns.heatmap(pivot_df, cmap='RdBu_r', center=0, ax=ax)
                ax.set_title('MISTy Spatial Relationships')
            else:
                # Simple bar plot of importances
                if 'importance' in misty_df.columns:
                    misty_df.head(20).plot(kind='barh', ax=ax)
                    ax.set_title('MISTy Top Relationships')

            plt.tight_layout()
            plt.savefig(os.path.join(results_dir, "5.spatial_relation_MISTy.png"), dpi=300, bbox_inches='tight')
            plt.close()

        output_files = [
            os.path.join(results_dir, "5.spatial_relation_MISTy.png"),
            os.path.join(results_dir, "res_SpatialRelationship_MISTy.csv"),
        ]

        existing_files = [f for f in output_files if os.path.exists(f)]

        return {
            "success": True,
            "step": 5,
            "analysis": "misty",
            "output_files": existing_files,
            "message": f"MISTy analysis complete: {len(existing_files)} files generated"
        }

    except Exception as e:
        logger.error(f"MISTy analysis failed: {e}")
        return {
            "success": False,
            "step": 5,
            "analysis": "misty",
            "error": str(e),
            "skipped": True,
            "message": "Analysis skipped due to error (MISTy may require R), continuing with available data"
        }

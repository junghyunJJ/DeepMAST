"""Part 3 Analysis Tools for Biological Interpreter Agent.

Part 3 analyses are generated dynamically after the agent selects LR pairs.
These tools visualize the selected ligand-receptor interactions.

Tools:
1. tool_run_lr_spatial_plot - Step 10: Spatial LR interaction visualization
2. tool_run_lr_cluster_analysis - Step 11: Cluster-level LR interaction analysis

Dependencies:
- Both require lrdata.h5ad from Step 6
- Both require agent-selected LR pairs (sel_interactions)
"""

import os
import sys
import logging
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Add mcp_servers to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))))


# =============================================================================
# Input Schemas
# =============================================================================

class LRSpatialPlotInput(BaseModel):
    """Input for LR spatial plot tool."""
    lrdata_path: str = Field(description="Path to lrdata.h5ad")
    sel_interactions: list[str] = Field(description="Selected LR pair names")
    cluster_key: Optional[str] = Field(default="celltype_niche", description="Cluster column (optional)")
    show_cluster: bool = Field(default=True, description="Show cluster as first subplot")
    results_dir: str = Field(default="res/", description="Output directory")


class LRClusterAnalysisInput(BaseModel):
    """Input for LR cluster analysis tool."""
    lrdata_path: str = Field(description="Path to lrdata.h5ad")
    sel_interactions: list[str] = Field(description="Selected LR pair names")
    cluster_key: str = Field(default="celltype_niche", description="Cluster column name")
    p_th: float = Field(default=0.05, description="P-value threshold for significance")
    results_dir: str = Field(default="res/", description="Output directory")


# =============================================================================
# Tool Implementations
# =============================================================================

@tool(args_schema=LRSpatialPlotInput)
def tool_run_lr_spatial_plot(
    lrdata_path: str,
    sel_interactions: list[str],
    cluster_key: Optional[str] = "celltype_niche",
    show_cluster: bool = True,
    results_dir: str = "res/"
) -> dict:
    """Run spatial visualization of LR interaction scores (Step 10).

    Visualizes the spatial distribution of selected ligand-receptor
    interaction scores across tissue. Each LR pair is displayed as
    a separate spatial plot showing where interactions occur.

    Outputs:
    - 10.spatial_plot_interections.png

    This is Part 3 Step 10 - requires lrdata.h5ad from Step 6
    and agent-selected LR pairs.
    """
    try:
        from mcp_servers.runplot_LIANAp_NMF import plot_liana_spatial_interections

        # Check dependency
        if not os.path.exists(lrdata_path):
            return {
                "success": False,
                "step": 10,
                "analysis": "spatial_lr",
                "error": f"lrdata.h5ad not found at {lrdata_path}. Run Step 6 first."
            }

        if not sel_interactions:
            return {
                "success": False,
                "step": 10,
                "analysis": "spatial_lr",
                "error": "No LR interactions selected. Agent must select interactions."
            }

        os.makedirs(results_dir, exist_ok=True)

        plot_liana_spatial_interections(
            filename=lrdata_path,
            sel_interactions=sel_interactions,
            cluster_key=cluster_key,
            show_cluster=show_cluster,
            save_path=results_dir
        )

        output_file = os.path.join(results_dir, "10.spatial_plot_interections.png")

        if os.path.exists(output_file):
            return {
                "success": True,
                "step": 10,
                "analysis": "spatial_lr",
                "output_files": [output_file],
                "selected_interactions": sel_interactions,
                "message": f"LR spatial plot generated for {len(sel_interactions)} interactions"
            }
        else:
            return {
                "success": False,
                "step": 10,
                "analysis": "spatial_lr",
                "error": "Output file not created"
            }

    except Exception as e:
        logger.error(f"LR spatial plot failed: {e}")
        return {
            "success": False,
            "step": 10,
            "analysis": "spatial_lr",
            "error": str(e),
            "skipped": True,
            "message": "Analysis skipped due to error, continuing with available data"
        }


@tool(args_schema=LRClusterAnalysisInput)
def tool_run_lr_cluster_analysis(
    lrdata_path: str,
    sel_interactions: list[str],
    cluster_key: str = "celltype_niche",
    p_th: float = 0.05,
    results_dir: str = "res/"
) -> dict:
    """Run cluster-level LR interaction analysis (Step 11).

    Analyzes and visualizes LR interaction patterns at the cluster level.
    For each selected LR pair, generates visualization showing spatial
    distribution and cluster-level aggregated scores with statistical
    significance testing.

    Outputs:
    - 11.lr_interections.png

    This is Part 3 Step 11 - requires lrdata.h5ad from Step 6
    and agent-selected LR pairs. This is the final analysis step.
    """
    try:
        from mcp_servers.runplot_LIANAp_NMF import plot_liana_interections

        # Check dependency
        if not os.path.exists(lrdata_path):
            return {
                "success": False,
                "step": 11,
                "analysis": "lr_cluster",
                "error": f"lrdata.h5ad not found at {lrdata_path}. Run Step 6 first."
            }

        if not sel_interactions:
            return {
                "success": False,
                "step": 11,
                "analysis": "lr_cluster",
                "error": "No LR interactions selected. Agent must select interactions."
            }

        os.makedirs(results_dir, exist_ok=True)

        plot_liana_interections(
            filename=lrdata_path,
            cluster_key=cluster_key,
            sel_interactions=sel_interactions,
            p_th=p_th,
            save_path=results_dir
        )

        output_file = os.path.join(results_dir, "11.lr_interections.png")

        if os.path.exists(output_file):
            return {
                "success": True,
                "step": 11,
                "analysis": "lr_cluster",
                "output_files": [output_file],
                "selected_interactions": sel_interactions,
                "message": f"LR cluster analysis complete for {len(sel_interactions)} interactions. Analysis workflow complete!"
            }
        else:
            return {
                "success": False,
                "step": 11,
                "analysis": "lr_cluster",
                "error": "Output file not created"
            }

    except Exception as e:
        logger.error(f"LR cluster analysis failed: {e}")
        return {
            "success": False,
            "step": 11,
            "analysis": "lr_cluster",
            "error": str(e),
            "skipped": True,
            "message": "Analysis skipped due to error"
        }


# =============================================================================
# Part 3 Execution Helper
# =============================================================================

async def run_part3_with_selections(
    lrdata_path: str,
    sel_interactions: list[str],
    cluster_key: str = "celltype_niche",
    results_dir: str = "res/",
) -> dict:
    """Run Part 3 analyses with agent-selected LR interactions.

    This helper runs Steps 10 and 11 after the agent has selected
    which LR pairs to visualize.

    Args:
        lrdata_path: Path to lrdata.h5ad
        sel_interactions: List of selected LR pair names
        cluster_key: Cluster column name
        results_dir: Output directory

    Returns:
        Dict with results from each step
    """
    results = {}

    # Step 10: LR Spatial Plot
    step10_result = tool_run_lr_spatial_plot.invoke({
        "lrdata_path": lrdata_path,
        "sel_interactions": sel_interactions,
        "cluster_key": cluster_key,
        "results_dir": results_dir,
    })
    results["step10"] = step10_result

    # Step 11: LR Cluster Analysis
    step11_result = tool_run_lr_cluster_analysis.invoke({
        "lrdata_path": lrdata_path,
        "sel_interactions": sel_interactions,
        "cluster_key": cluster_key,
        "results_dir": results_dir,
    })
    results["step11"] = step11_result

    return results

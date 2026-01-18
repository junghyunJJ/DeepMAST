"""Part 2 Analysis Tools for Biological Interpreter Agent.

Part 2 analyses use lrdata.h5ad and must run sequentially.
These tools generate CCI analysis with LIANA+ and NMF factorization.

Tools:
1. tool_run_liana_cci - Step 6: LIANA+ bivariate + NMF
2. tool_run_factor_score - Step 7: Factor score visualization
3. tool_run_lr_loadings - Step 8: LR loadings + pathway enrichment
4. tool_run_quadrant_analysis - Step 9: ctSVG quadrant analysis

Dependencies:
- Step 6 must complete before Step 7
- Step 7 must complete before Step 8
- Step 8 must complete before Step 9
"""

import os
import sys
import logging
from typing import Literal, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Add mcp_servers to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))))


# =============================================================================
# Input Schemas
# =============================================================================

class LianaCCIInput(BaseModel):
    """Input for LIANA CCI analysis tool."""
    adata_path: str = Field(description="Path to normalized adata (n_adata.h5ad)")
    cluster_key: str = Field(default="celltype_niche", description="Cluster column name")
    organism: Literal['human', 'mouse'] = Field(default='human', description="Organism")
    n_perms: int = Field(default=1000, description="Permutations for Moran's R")
    max_iter_nmf: int = Field(default=200, description="Max iterations for NMF")
    results_dir: str = Field(default="res/", description="Output directory")


class FactorScoreInput(BaseModel):
    """Input for factor score visualization tool."""
    lrdata_path: str = Field(description="Path to lrdata.h5ad")
    cluster_key: str = Field(default="celltype_niche", description="Cluster column name")
    results_dir: str = Field(default="res/", description="Output directory")


class LRLoadingsInput(BaseModel):
    """Input for LR loadings analysis tool."""
    lrdata_path: str = Field(description="Path to lrdata.h5ad")
    organism: Literal['human', 'mouse'] = Field(default='human', description="Organism")
    geneset: Literal['progeny', 'hallmark'] = Field(default='progeny', description="Pathway geneset")
    th_morans: float = Field(default=0, description="Moran's R threshold")
    p_th: float = Field(default=0.05, description="P-value threshold")
    min_n: int = Field(default=5, description="Minimum targets per pathway")
    results_dir: str = Field(default="res/", description="Output directory")


class QuadrantAnalysisInput(BaseModel):
    """Input for quadrant analysis tool."""
    interest_celltypes: list[str] = Field(description="Cell types of interest")
    sel_factor: str = Field(description="Selected factor name (e.g., 'Factor_0')")
    n_top_label: int = Field(default=10, description="Number of top LR pairs to label")
    results_dir: str = Field(default="res/", description="Output directory")


# =============================================================================
# Tool Implementations
# =============================================================================

@tool(args_schema=LianaCCIInput)
def tool_run_liana_cci(
    adata_path: str,
    cluster_key: str = "celltype_niche",
    organism: Literal['human', 'mouse'] = 'human',
    n_perms: int = 1000,
    max_iter_nmf: int = 200,
    results_dir: str = "res/"
) -> dict:
    """Run LIANA+ CCI analysis with NMF (Step 6).

    Performs LIANA+ bivariate analysis to identify significant ligand-receptor
    pairs with spatial co-clustering patterns. Includes NMF factorization to
    discover intercellular communication patterns.

    Outputs:
    - lrdata.h5ad (AnnData with CCI results and NMF factors)
    - 6.liana_MoransR.png
    - sig_liana.csv

    This is Part 2 Step 6 - must complete before Steps 7-9.
    """
    try:
        from mcp_servers.runplot_LIANAp_NMF import run_lianap

        os.makedirs(results_dir, exist_ok=True)

        run_lianap(
            filename=adata_path,
            organism=organism,
            platform='auto',
            n_perms=n_perms,
            max_iter_nmf=max_iter_nmf,
            save_path=results_dir
        )

        lrdata_path = os.path.join(results_dir, "lrdata.h5ad")

        output_files = [
            lrdata_path,
            os.path.join(results_dir, "6.liana_MoransR.png"),
            os.path.join(results_dir, "sig_liana.csv"),
        ]

        existing_files = [f for f in output_files if os.path.exists(f)]

        if lrdata_path in existing_files:
            return {
                "success": True,
                "step": 6,
                "analysis": "liana",
                "output_files": existing_files,
                "lrdata_path": lrdata_path,
                "message": f"LIANA CCI analysis complete: {len(existing_files)} files generated"
            }
        else:
            return {
                "success": False,
                "step": 6,
                "analysis": "liana",
                "error": "lrdata.h5ad not created"
            }

    except Exception as e:
        logger.error(f"LIANA CCI analysis failed: {e}")
        return {
            "success": False,
            "step": 6,
            "analysis": "liana",
            "error": str(e),
            "skipped": True,
            "message": "Analysis skipped due to error. Part 2 cannot continue without lrdata.h5ad."
        }


@tool(args_schema=FactorScoreInput)
def tool_run_factor_score(
    lrdata_path: str,
    cluster_key: str = "celltype_niche",
    results_dir: str = "res/"
) -> dict:
    """Run NMF factor score visualization (Step 7).

    Visualizes NMF factor scores spatially and generates cluster-level
    factor median values. Factor scores represent the activation strength
    of intercellular communication patterns at each observation.

    Outputs:
    - 7.factor_spatial_NMF.png
    - res_liana_cluster_factor.csv

    This is Part 2 Step 7 - requires lrdata.h5ad from Step 6.
    """
    try:
        from mcp_servers.runplot_LIANAp_NMF import runplot_liana_factorscore

        # Check dependency
        if not os.path.exists(lrdata_path):
            return {
                "success": False,
                "step": 7,
                "analysis": "factor",
                "error": f"lrdata.h5ad not found at {lrdata_path}. Run Step 6 first."
            }

        os.makedirs(results_dir, exist_ok=True)

        runplot_liana_factorscore(
            filename=lrdata_path,
            cluster_key=cluster_key,
            save_path=results_dir
        )

        output_files = [
            os.path.join(results_dir, "7.factor_spatial_NMF.png"),
            os.path.join(results_dir, "res_liana_cluster_factor.csv"),
        ]

        existing_files = [f for f in output_files if os.path.exists(f)]

        if existing_files:
            return {
                "success": True,
                "step": 7,
                "analysis": "factor",
                "output_files": existing_files,
                "message": f"Factor score visualization complete: {len(existing_files)} files generated"
            }
        else:
            return {
                "success": False,
                "step": 7,
                "analysis": "factor",
                "error": "Output files not created"
            }

    except Exception as e:
        logger.error(f"Factor score visualization failed: {e}")
        return {
            "success": False,
            "step": 7,
            "analysis": "factor",
            "error": str(e),
            "skipped": True,
            "message": "Analysis skipped due to error, continuing with available data"
        }


@tool(args_schema=LRLoadingsInput)
def tool_run_lr_loadings(
    lrdata_path: str,
    organism: Literal['human', 'mouse'] = 'human',
    geneset: Literal['progeny', 'hallmark'] = 'progeny',
    th_morans: float = 0,
    p_th: float = 0.05,
    min_n: int = 5,
    results_dir: str = "res/"
) -> dict:
    """Run LR loadings and pathway enrichment analysis (Step 8).

    Analyzes NMF loadings to identify which LR pairs contribute to each
    factor. Includes pathway enrichment to characterize the biological
    processes associated with each factor.

    Outputs:
    - 8.pathway_factor_heatmap.png
    - sig_liana.csv (updated with loadings)
    - sig_liana_pathway_factor.csv

    This is Part 2 Step 8 - requires lrdata.h5ad from Step 6.
    """
    try:
        from mcp_servers.runplot_LIANAp_NMF import runplot_liana_loadings

        # Check dependency
        if not os.path.exists(lrdata_path):
            return {
                "success": False,
                "step": 8,
                "analysis": "loadings",
                "error": f"lrdata.h5ad not found at {lrdata_path}. Run Step 6 first."
            }

        os.makedirs(results_dir, exist_ok=True)

        runplot_liana_loadings(
            filename=lrdata_path,
            organism=organism,
            geneset=geneset,
            th_morans=th_morans,
            p_th=p_th,
            min_n=min_n,
            save_path=results_dir
        )

        output_files = [
            os.path.join(results_dir, "8.pathway_factor_heatmap.png"),
            os.path.join(results_dir, "sig_liana.csv"),
            os.path.join(results_dir, "sig_liana_pathway_factor.csv"),
        ]

        existing_files = [f for f in output_files if os.path.exists(f)]

        if existing_files:
            return {
                "success": True,
                "step": 8,
                "analysis": "loadings",
                "output_files": existing_files,
                "message": f"LR loadings analysis complete: {len(existing_files)} files generated"
            }
        else:
            return {
                "success": False,
                "step": 8,
                "analysis": "loadings",
                "error": "Output files not created"
            }

    except Exception as e:
        logger.error(f"LR loadings analysis failed: {e}")
        return {
            "success": False,
            "step": 8,
            "analysis": "loadings",
            "error": str(e),
            "skipped": True,
            "message": "Analysis skipped due to error, continuing with available data"
        }


@tool(args_schema=QuadrantAnalysisInput)
def tool_run_quadrant_analysis(
    interest_celltypes: list[str],
    sel_factor: str,
    n_top_label: int = 10,
    results_dir: str = "res/"
) -> dict:
    """Run quadrant analysis for interest clusters (Step 9).

    Generates quadrant plot combining NMF factor loadings with Bivariate
    Moran's R to prioritize LR pairs for interest cell types.

    Outputs:
    - 9.quadrant_analysis.png
    - interest_anno_sig_liana.csv

    This is Part 2 Step 9 - requires sig_liana.csv from Step 8.
    Requires agent to provide: interest_celltypes and sel_factor.
    """
    try:
        from mcp_servers.runplot_LIANAp_NMF import plot_liana_nmf

        # Check dependency
        sig_liana_path = os.path.join(results_dir, "anno_sig_liana.csv")
        if not os.path.exists(sig_liana_path):
            # Try alternative path
            sig_liana_path = os.path.join(results_dir, "sig_liana.csv")
            if not os.path.exists(sig_liana_path):
                return {
                    "success": False,
                    "step": 9,
                    "analysis": "quadrant",
                    "error": f"sig_liana.csv not found. Run Step 8 first."
                }

        os.makedirs(results_dir, exist_ok=True)

        plot_liana_nmf(
            interest_celltypes=interest_celltypes,
            sel_factor=sel_factor,
            n_top_label=n_top_label,
            save_path=results_dir
        )

        output_files = [
            os.path.join(results_dir, "9.quadrant_analysis.png"),
            os.path.join(results_dir, "interest_anno_sig_liana.csv"),
        ]

        existing_files = [f for f in output_files if os.path.exists(f)]

        if existing_files:
            return {
                "success": True,
                "step": 9,
                "analysis": "quadrant",
                "output_files": existing_files,
                "interest_celltypes": interest_celltypes,
                "selected_factor": sel_factor,
                "message": f"Quadrant analysis complete: {len(existing_files)} files generated"
            }
        else:
            return {
                "success": False,
                "step": 9,
                "analysis": "quadrant",
                "error": "Output files not created"
            }

    except Exception as e:
        logger.error(f"Quadrant analysis failed: {e}")
        return {
            "success": False,
            "step": 9,
            "analysis": "quadrant",
            "error": str(e),
            "skipped": True,
            "message": "Analysis skipped due to error, continuing with available data"
        }


# =============================================================================
# Sequential Execution Helper
# =============================================================================

async def run_part2_sequential(
    adata_path: str,
    cluster_key: str = "celltype_niche",
    organism: Literal['human', 'mouse'] = 'human',
    n_perms: int = 1000,
    max_iter_nmf: int = 200,
    results_dir: str = "res/",
    interest_celltypes: Optional[list[str]] = None,
    sel_factor: Optional[str] = None,
) -> dict:
    """Run Part 2 analyses in correct sequential order.

    This helper ensures proper dependency ordering:
    Step 6 → Step 7 → Step 8 → Step 9

    Args:
        adata_path: Path to normalized adata
        cluster_key: Cluster column name
        organism: Organism for LR database
        n_perms: Permutations for Moran's R
        max_iter_nmf: Max NMF iterations
        results_dir: Output directory
        interest_celltypes: Cell types for Step 9 (optional)
        sel_factor: Selected factor for Step 9 (optional)

    Returns:
        Dict with results from each step
    """
    results = {}
    lrdata_path = os.path.join(results_dir, "lrdata.h5ad")

    # Step 6: LIANA CCI
    step6_result = tool_run_liana_cci.invoke({
        "adata_path": adata_path,
        "cluster_key": cluster_key,
        "organism": organism,
        "n_perms": n_perms,
        "max_iter_nmf": max_iter_nmf,
        "results_dir": results_dir,
    })
    results["step6"] = step6_result

    if not step6_result.get("success", False):
        return results  # Cannot continue without lrdata.h5ad

    # Step 7: Factor Score
    step7_result = tool_run_factor_score.invoke({
        "lrdata_path": lrdata_path,
        "cluster_key": cluster_key,
        "results_dir": results_dir,
    })
    results["step7"] = step7_result

    # Step 8: LR Loadings
    step8_result = tool_run_lr_loadings.invoke({
        "lrdata_path": lrdata_path,
        "organism": organism,
        "results_dir": results_dir,
    })
    results["step8"] = step8_result

    # Step 9: Quadrant Analysis (optional, requires agent input)
    if interest_celltypes and sel_factor:
        step9_result = tool_run_quadrant_analysis.invoke({
            "interest_celltypes": interest_celltypes,
            "sel_factor": sel_factor,
            "results_dir": results_dir,
        })
        results["step9"] = step9_result

    return results

from typing import Optional, Literal, List

import scanpy as sc
import decoupler as dc
import liana as li
import os

import matplotlib.pyplot as plt

from utils.run_decoupler import sp_enrich, plot_pathway_enrich_matrixplot
from utils.run_decoupler import plot_pathway_spatial_violin


def runplot_pathway_enrich(
    filename: str,
    cluster_key: str,
    organism: Literal['human', 'mouse'] = 'human',
    geneset: Literal['progeny', 'hallmark'] = 'progeny',
    reference: str = 'rest',
    threshold: float = 0.05,
    n_markers: int = 3,
    min_n: int = 5,
    width: Optional[int] = None,
    height: Optional[int] = None,
    save_path: str = 'res/',
    ) -> None:
    """
    Part 1: Before CCI Analysis - Step 4. Spatial Pathway Enrichment Analysis (Decoupler)

    Performs pathway enrichment analysis using PROGENy geneset to identify pathways associated
    with specific spatial clusters. Uses Decoupler package to compute pathway activity scores
    and statistical significance across clusters.

    Methodology:
        - Tool: Decoupler (https://decoupler.readthedocs.io/en/latest/index.html)
        - Geneset: PROGENy (default) or Hallmark
        - Statistical Test: Wilcoxon rank-sum test with FDR correction
        - Comparison: Each cluster vs. rest (reference='rest')

    PROGENy Pathway Descriptions (14 pathways):
        - Androgen: Growth and development of male reproductive organs
        - EGFR: Growth, survival, migration, apoptosis, proliferation, differentiation
        - Estrogen: Growth and development of female reproductive organs
        - Hypoxia: Angiogenesis and metabolic reprogramming when O2 levels are low
        - JAK-STAT: Immunity, cell division, cell death, tumor formation
        - MAPK: Integrates external signals, promotes growth and proliferation
        - NFkB: Immune response, cytokine production, cell survival
        - p53: Cell cycle, apoptosis, DNA repair, tumor suppression
        - PI3K: Growth and proliferation
        - TGFb: Development, homeostasis, tissue repair
        - TNFa: Haematopoiesis, immune surveillance, tumour regression, infection protection
        - Trail: Apoptosis induction
        - VEGF: Angiogenesis, vascular permeability, cell migration
        - WNT: Organ morphogenesis during development and tissue repair

    Workflow Position:
        - Part 1 analysis (before CCI)
        - Step 4: Pathway identification for clusters of interest
        - Independent analysis result
        - Results inform cluster-pathway associations for downstream analysis
        - Recommended to repeat Part 1 analysis 3-5 times for consistent results

    Data Requirements:
        - Uses normalized n_adata.h5ad data
        - Requires cluster annotations in adata.obs[cluster_key]
        - Requires gene expression matrix in adata.X
        - Compatible with spot-based (Visium) and single-cell resolution (MERFISH, Xenium) data

    Args:
        filename (str): Path to the `.h5ad` file containing spatial transcriptomics data
        cluster_key (str): Column name in adata.obs for spatial cluster annotations
        organism (Literal['human', 'mouse']): Organism for geneset selection (default: 'human')
        geneset (Literal['progeny', 'hallmark']): Pathway geneset to use (default: 'progeny')
        reference (str): Reference group for comparison (default: 'rest' for all other clusters)
        threshold (float): FDR significance threshold for filtering results (default: 0.05)
        n_markers (int): Number of top markers to display in plot (default: 3)
        min_n (int): Minimum number of targets per source (pathway) required for analysis.
                     Default is 5. For single-cell resolution data with limited gene panels
                     (e.g., STARmap, MERFISH), use lower values like 1-3 to avoid
                     AssertionError when gene overlap is insufficient.
        width (int, optional): Figure width in inches. If None, auto-calculated based on
                               number of clusters (0.7 inch per cluster, min 5). Default: None
        height (int, optional): Figure height in inches. If None, auto-calculated based on
                                n_markers (0.5 inch per marker, min 4). Default: None
        save_path (str): Output directory for saving plots and results (default: 'res/')

    Outputs:
        - Image: {save_path}/4.spatial_enrich_decoupler.png
          Matrix plot showing pathway enrichment scores across clusters
          Top n_markers pathways per cluster displayed

        - CSV: {save_path}/sig_PathwayEnrich_decoupler.csv
          Columns:
            - group: Target cluster being analyzed
            - reference: Reference clusters used for comparison
            - name: Pathway name (from PROGENy or Hallmark geneset)
            - stat: Test statistic from enrichment analysis
            - meanchange: Mean change in pathway activity
            - pval: Raw p-value from statistical test
            - fdr: False Discovery Rate adjusted p-value

    Analysis Results:
        - Pathway identification: Determine which pathways are enriched in clusters of interest
        - Cluster characterization: Understand biological processes in spatial regions
        - Downstream selection: Use results to select pathways related to clusters of interest
        - Cross-validation: Compare with Part 1 Step 2 (cell type) results for validation

    Important Notes:
        - PROGENy geneset provides comprehensive pathway coverage (14 pathways)
        - Results should be used alongside cell type composition analysis
        - Selected pathways will inform Part 2 NMF and CCI analysis
        - Part 1 analysis variations may occur; recommended to run 3-5 times

    Returns:
        None
    """
    # Dynamic sizing constants
    BASE_WIDTH = 5
    BASE_HEIGHT = 4
    WIDTH_PER_CLUSTER = 0.7
    HEIGHT_PER_MARKER = 0.5

    adata = sc.read_h5ad(filename)

    # Calculate number of clusters for dynamic sizing
    n_clusters = adata.obs[cluster_key].nunique()

    # Auto-calculate dimensions if not specified
    fig_width = width if width is not None else max(BASE_WIDTH, n_clusters * WIDTH_PER_CLUSTER)
    fig_height = height if height is not None else max(BASE_HEIGHT, n_markers * HEIGHT_PER_MARKER)

    adata_dc = sp_enrich(adata, cluster_key, organism=organism, geneset=geneset, min_n=min_n)
    # sc.pl.spatial(adata_dc, color=adata_dc.var.index, cmap='RdBu_r', size=1.3)

    os.makedirs(save_path, exist_ok=True)
    
    # Call the plot function and get the matrixplot object
    result = plot_pathway_enrich_matrixplot(adata_dc, cluster_key, reference=reference, threshold=threshold, n_markers = n_markers)
    
    # Handle the return value - could be tuple or single value
    if isinstance(result, tuple):
        final_df, mp = result
        final_df.rename(columns={'padj': 'fdr'}, inplace=True)

        final_df.to_csv(f'{save_path}/sig_PathwayEnrich_decoupler.csv')


        # Save the matrixplot figure if available
        if mp is not None:
            plt.gcf().set_size_inches(fig_width, fig_height)
            save_path = f'{save_path}/4.spatial_enrich_decoupler.png'
            mp.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"Spatial Enrichment anaylsis (decoupler) plot saved to: {save_path}")
            # plt.show()
    else:
        # Fallback to previous method if function doesn't return matrixplot
        plt.tight_layout()
        save_path = f'{save_path}/4.spatial_enrich_decoupler.png'
        plt.gcf().set_size_inches(fig_width, fig_height)
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"Spatial Enrichment anaylsis (decoupler) plot saved to: {save_path}")
        # plt.show()

    return None



def highlight_pathway_enrich(
    filename: str,
    cluster_key: str,
    sel_pathway: List[str],
    organism: Literal['human', 'mouse'] = 'human',
    min_n: int = 5,
    width: int = 5,
    height: int = 5,
    save_path: str = 'res/',
    ) -> None:
    """
    Part 1: Supplementary Analysis - Detailed Pathway Visualization

    Creates detailed spatial and violin plots for selected pathways identified from the main
    pathway enrichment analysis (runplot_pathway_enrich). This function provides in-depth
    visualization to validate and explore specific pathways of interest.

    Purpose:
        - Follow-up visualization for pathways identified in Step 4 analysis
        - Spatial distribution of pathway activity across tissue
        - Cluster-wise pathway activity comparison via violin plots
        - Validation of pathway-cluster associations

    Workflow Position:
        - Part 1 supplementary analysis (before CCI)
        - Used after runplot_pathway_enrich() to explore selected pathways
        - Supports pathway selection for downstream Part 2 analysis
        - Provides detailed evidence for pathway-cluster relationships

    Data Requirements:
        - Uses normalized n_adata.h5ad data
        - Requires cluster annotations in adata.obs[cluster_key]
        - Requires gene expression matrix in adata.X
        - Compatible with spot-based (Visium) and single-cell resolution (MERFISH, Xenium) data

    Args:
        filename (str): Path to the `.h5ad` file containing spatial transcriptomics data
        cluster_key (str): Column name in adata.obs for spatial cluster annotations
        sel_pathway (List[str]): List of pathway names to visualize
                                 Example: ["MAPK", "p53", "VEGF"]
                                 Pathway names should match PROGENy or Hallmark geneset
        organism (Literal['human', 'mouse']): Organism for geneset selection (default: 'human')
        min_n (int): Minimum number of targets per source (pathway) required for analysis.
                     Default is 5. For single-cell resolution data with limited gene panels
                     (e.g., STARmap, MERFISH), use lower values like 1-3.
        width (int): Figure width in inches (default: 5)
        height (int): Figure height in inches (default: 5)
        save_path (str): Output directory for saving the plot (default: 'res/')

    Outputs:
        - Image: {save_path}/4.highlight_spatial_enrich_decoupler.png
          Combined visualization with two panels:
            1. Spatial plot: Pathway activity distribution across tissue
            2. Violin plot: Pathway activity distribution across clusters

    Use Cases:
        - Validate pathways identified in runplot_pathway_enrich()
        - Explore spatial patterns of specific biological processes
        - Compare pathway activity across different tissue regions
        - Generate publication-quality figures for selected pathways
        - Support pathway selection for Part 2 NMF analysis

    Analysis Results:
        - Visual confirmation of pathway-cluster associations
        - Spatial heterogeneity of pathway activity
        - Cluster-specific pathway activity patterns
        - Evidence for biological interpretation of clusters

    Important Notes:
        - Use this function after identifying pathways with runplot_pathway_enrich()
        - Select 2-4 pathways for optimal visualization clarity
        - Pathway names must exactly match geneset nomenclature
        - Results complement the main pathway enrichment analysis

    Returns:
        None
    """
    adata = sc.read_h5ad(filename)
    adata_dc = sp_enrich(adata, cluster_key, organism=organism, min_n=min_n)
    # sel_pathway = ["P53_PATHWAY", "MTORC1_SIGNALING"]
    # sc.pl.spatial(adata_dc, color=sel_pathway + [cluster_key], cmap="RdBu_r", vcenter=0, size=1.5)
    # sc.pl.violin(adata_dc, keys=sel_pathway, groupby=cluster_key, rotation=90)

    os.makedirs(save_path, exist_ok=True)

    fig, axes = plot_pathway_spatial_violin(
        adata_dc,
        pathways=sel_pathway,
        cluster_key=cluster_key
    )

    # Save the figure
    save_path = f'{save_path}/4.highlight_spatial_enrich_decoupler.png'
    fig.gcf().set_size_inches(width, height)
    fig.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"Highlight Spatial Enrichment anaylsis (decoupler) plot saved to: {save_path}")
    
    # Show the plot
    # plt.show()


    return None

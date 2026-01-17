import os

from typing import Optional, Literal, List

import scanpy as sc
import squidpy as sq
import liana as li
import matplotlib.pyplot as plt

from utils.run_celltype_heatmap_analysis import run_celltype_heatmap_analysis
from utils.utils import cluster_medians_to_long_full

def plot_cluster(
    filename: str,
    cluster_key: str,
    sample_key: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    save_path: str = 'res/',
    ) -> None:

    """
    Part 1: Before CCI Analysis - Step 1. Spatial Clustering Analysis

    Generates basic spatial visualization of observations (spots/cells) colored by cluster
    assignments. This is the initial visualization step in the CCI analysis workflow using
    normalized data (n_adata.h5ad).

    Workflow Position:
        - Part 1 analysis (before CCI)
        - First visualization in the analysis pipeline
        - Independent analysis result
        - Recommended to repeat Part 1 analysis 3-5 times for consistent results

    Data Requirements:
        - Uses normalized n_adata.h5ad data
        - Requires spatial coordinates in adata.obsm['spatial']
        - Requires cluster annotations in adata.obs[cluster_key]
        - Compatible with spot-based (Visium) and single-cell resolution (MERFISH, Xenium) data

    Args:
        filename (str): Path to the `.h5ad` file containing spatial transcriptomics data
        cluster_key (str): Column name in adata.obs containing cluster assignments
        sample_key (str, optional): Column name in adata.obs containing sample identifiers.
                                    If provided, creates separate subplots for each sample.
                                    Default: None (single plot for all data)
        width (int, optional): Figure width in inches. If None, automatically calculated
                               based on number of plots (5 inches per subplot). Default: None
        height (int, optional): Figure height in inches. If None, automatically set to 5.
                                Default: None
        save_path (str): Output directory for saving the plot (default: 'res/')

    Outputs:
        - Image: {save_path}/1.spatial.png
          Spatial plot showing spatial organization and cluster distribution
          When sample_key is provided, shows subplots for each sample with shared legend

    Analysis Results:
        - Visual confirmation of spatial clustering patterns
        - Initial assessment of spatial organization
        - Foundation for subsequent cluster-celltype association analysis
        - When sample_key provided: comparison of spatial patterns across samples

    Returns:
        None
    """

    # Base dimensions per subplot
    BASE_WIDTH = 4
    BASE_HEIGHT = 4
    HEIGHT_PER_CLUSTER = 0.4  # Additional height per cluster for legend

    adata = sc.read_h5ad(filename)
    os.makedirs(save_path, exist_ok=True)

    # Check if spatial image data exists
    has_spatial_img = 'spatial' in adata.uns

    # Determine palette based on number of unique cluster values
    n_clusters = adata.obs[cluster_key].nunique()

    # Calculate dynamic height based on cluster count (for legend space)
    dynamic_height = max(BASE_HEIGHT, n_clusters * HEIGHT_PER_CLUSTER)

    if n_clusters == 2:
        # Binary case: store colors in adata.uns for squidpy/scanpy to use
        # grey 60% for first value (e.g., 0), black for second value (e.g., 1)
        adata.uns[f'{cluster_key}_colors'] = ['#999999', '#000000']
        palette = None
    else:
        palette = 'tab20'

    if sample_key is None:
        # Calculate number of plots for single-sample mode
        n_plots = 2 if has_spatial_img else 1

        # Auto-calculate dimensions if not specified
        fig_width = width if width is not None else BASE_WIDTH * n_plots
        fig_height = height if height is not None else dynamic_height

        # Original single-sample behavior
        if has_spatial_img:
            sq.pl.spatial_scatter(adata, color=[None, cluster_key], size=1.3, palette=palette)
        else:
            sq.pl.spatial_scatter(adata, color=cluster_key, size=1.3, palette=palette, shape=None)
        plt.gcf().set_size_inches(fig_width, fig_height)
        plt.savefig(f'{save_path}/1.spatial.png', dpi=300, bbox_inches='tight')
        print(f"Spatial plot saved to: {save_path}/1.spatial.png")
    else:
        # Multi-sample behavior with subplots
        samples = adata.obs[sample_key].unique()
        n_samples = len(samples)

        # Legend width for extra space
        LEGEND_WIDTH = 1.0  # Base legend width in inches

        # Auto-calculate dimensions if not specified (add extra space for legend)
        fig_width = width if width is not None else BASE_WIDTH * n_samples + LEGEND_WIDTH
        fig_height = height if height is not None else dynamic_height

        # Create subplots with reduced spacing between plots
        fig, axes = plt.subplots(1, n_samples, figsize=(fig_width, fig_height))
        plt.subplots_adjust(wspace=0.1)  # Reduce horizontal spacing between plots

        # Handle single sample case
        if n_samples == 1:
            axes = [axes]

        for i, sample in enumerate(samples):
            adata_sub = adata[adata.obs[sample_key] == sample].copy()

            # Ensure color information is copied for binary clusters
            if n_clusters == 2 and f'{cluster_key}_colors' in adata.uns:
                adata_sub.uns[f'{cluster_key}_colors'] = adata.uns[f'{cluster_key}_colors']

            if has_spatial_img:
                sq.pl.spatial_scatter(
                    adata_sub,
                    color=cluster_key,
                    size=1.3,
                    palette=palette,
                    ax=axes[i]
                )
            else:
                sq.pl.spatial_scatter(
                    adata_sub,
                    color=cluster_key,
                    size=1.3,
                    palette=palette,
                    shape=None,
                    ax=axes[i]
                )
            axes[i].set_title(f'{sample_key}: {sample}')

            # Remove individual legends
            legend = axes[i].get_legend()
            if legend:
                legend.remove()

        # Add figure-level legend outside the plot area (closer to plots)
        handles, labels_leg = axes[0].get_legend_handles_labels()
        legend = fig.legend(
            handles, labels_leg,
            loc='center left',
            bbox_to_anchor=(1.01, 0.5),  # Slightly outside right edge
            title=cluster_key,
            frameon=False,
            labelspacing=0.3  # Reduce spacing between legend items
        )

        # Compact layout with minimal padding
        plt.tight_layout(pad=0.5)
        plt.savefig(f'{save_path}/1.spatial_by_{sample_key}.png', dpi=300, bbox_inches='tight')
        print(f"Spatial plot saved to: {save_path}/1.spatial_by_{sample_key}.png")
    
    # Show the plot
    # plt.show()

    # # Set figure size
    # plt.rcParams['figure.figsize'] = (width, height)
    # plt.rcParams['figure.dpi'] = 300

    # fig = sc.pl.spatial(
    #     adata, 
    #     color=[None, cluster_key], 
    #     size=1.3, 
    #     palette='tab20'
    # )
    # fig.savefig(f'{save_path}/1.spatial.png', dpi=300, bbox_inches='tight')
    # plt.show()

    return None


def runplot_clusterwithcelltyp(
    filename: str,
    cluster_key: str,
    celltype_key: Optional[str] = None,
    use_adjusted_pval: bool = True,
    p_th: float = 0.05,
    width: Optional[int] = None,
    height: Optional[int] = None,
    save_path: str = 'res/',
    ) -> None:
    """
    Part 1: Before CCI Analysis - Step 2. Cell Type Composition Analysis (ctanalysis)

    Generates heatmap visualization of scaled median cell-type compositions within each cluster.
    Asterisks indicate significantly increased composition of a cell type in a cluster compared
    with other clusters using one-sided Wilcoxon rank sum test with FDR adjustment (adj. P < 0.05).

    Supports two data types:
        1. Spot-based (Visium) with deconvolution results in adata.obsm['compositions']
        2. Single-cell resolution (MERFISH/Xenium) with cell type in adata.obs[celltype_key]

    Statistical Methodology:
        - One-sided Wilcoxon rank sum test
        - False Discovery Rate (FDR) correction for multiple testing
        - Significance threshold: adjusted P < 0.05 (default)

    Workflow Position:
        - Part 1 analysis (before CCI)
        - Step 2: Cell type identification and cluster characterization
        - Independent analysis result
        - Critical for selecting 2-3 clusters of interest for downstream analysis
        - Recommended to repeat Part 1 analysis 3-5 times for consistent results

    Data Requirements:
        - Uses normalized n_adata.h5ad data
        - For spot-based: Requires adata.obsm['compositions'] (deconvolution results)
        - For single-cell: Requires adata.obs[celltype_key] (cell type annotations)
        - Requires cluster annotations in adata.obs[cluster_key]

    Args:
        filename (str): Path to the `.h5ad` file containing spatial transcriptomics data
        cluster_key (str): Column name in adata.obs for spatial cluster annotations
        celltype_key (str, optional): Column name in adata.obs containing cell type annotations.
                                       Required for single-cell resolution data (MERFISH, Xenium).
                                       If None, uses adata.obsm['compositions'] (Visium).
                                       Example: 'sub_level_cell_type', 'celltype', 'cell_type'
        use_adjusted_pval (bool): Use FDR-adjusted p-values (True) or raw p-values (False).
                                   Default: True (recommended)
        p_th (float): Significance threshold for filtering results. Default: 0.05
        width (int, optional): Figure width in inches. If None, auto-calculated based on
                               number of clusters (0.8 inch per cluster, min 4). Default: None
        height (int, optional): Figure height in inches. If None, auto-calculated based on
                                number of cell types (0.4 inch per cell type, min 4). Default: None
        save_path (str): Output directory for saving plots and results (default: 'res/')

    Outputs:
        - Image: {save_path}/2.celltype_heatmap_analysis.png
          Heatmap showing scaled median cell-type compositions within each cluster
          Asterisks (*) indicate significant enrichment (adj. P < 0.05)

        - CSV: {save_path}/sig_clusterwithcelltyp.csv
          Columns:
            - cluster: Cluster name/identifier
            - celltype: Cell type name
            - cluster_medians: Scaled median composition value
            - fdr: False Discovery Rate adjusted p-value

    Analysis Results:
        - Cell type identification: Determine which cell types are enriched in each cluster
        - Cluster identification: Characterize clusters based on cell type composition
        - Downstream selection: Use results to select 2-3 clusters of interest
          (prioritize minimal selection for focused analysis)

    Important Notes:
        - This analysis identifies cluster-celltype associations for Part 2 analysis
        - For single-cell data, cell types are converted to one-hot encoding internally
        - Results should be used to select interest clusters and related cell types
        - Part 1 analysis variations may occur; recommended to run 3-5 times
        - Selected clusters will be used for subsequent pathway and CCI analysis

    Returns:
        None
    """
    adata = sc.read_h5ad(filename)

    # Calculate number of clusters and cell types for dynamic sizing
    n_clusters = adata.obs[cluster_key].nunique()

    if celltype_key is not None:
        n_celltypes = adata.obs[celltype_key].nunique()
    elif 'compositions' in adata.obsm:
        n_celltypes = adata.obsm['compositions'].shape[1]
    else:
        n_celltypes = 10  # fallback

    # Auto-calculate dimensions if not specified
    # Width: based on clusters (x-axis), Height: based on cell types (y-axis)
    BASE_WIDTH_PER_CLUSTER = 0.3
    BASE_HEIGHT_PER_CELLTYPE = 0.4
    MIN_WIDTH = 4
    MIN_HEIGHT = 4

    fig_width = width if width is not None else max(MIN_WIDTH, n_clusters * BASE_WIDTH_PER_CLUSTER + 2)
    fig_height = height if height is not None else max(MIN_HEIGHT, n_celltypes * BASE_HEIGHT_PER_CELLTYPE + 1)

    os.makedirs(save_path, exist_ok=True)
    results = run_celltype_heatmap_analysis(
        adata,
        cluster_key=cluster_key,
        celltype_key=celltype_key,
        use_adjusted_pval=use_adjusted_pval,
        output_file=f'{save_path}/2.celltype_heatmap_analysis.png',
        width=fig_width, height=fig_height,
        )

    if use_adjusted_pval:
        long_res = cluster_medians_to_long_full(results['cluster_medians'], results['fdr'])
        sig_res = long_res[long_res['pval'] < p_th]
        sig_res.columns = ['cluster', 'celltype', 'cluster_medians', 'fdr']
    else:
        long_res = cluster_medians_to_long_full(results['cluster_medians'], results['pval'])
        sig_res = long_res[long_res['pval'] < p_th]
        
    sig_res = sig_res.sort_values('cluster_medians', ascending=False)
    sig_res.to_csv(f'{save_path}/sig_clusterwithcelltyp.csv')

    return None




# @mcp.tool()
# def plot_celltype(
#     filename: str,
#     sel_celltype: Optional[List[str]] = None,
#     ) -> None:
#     """
#     Provides a basic spatial plot based on cell type.

#     Args:
#         filename: the directory with the `.h5ad` file
#         sel_celltype: celltype name
#     Returns:
#         None
#     """
#     adata = read_h5ad(filename)
#     celltype_compositions = li.ut.obsm_to_adata(adata, 'compositions')
    
#     os.makedirs('res', exist_ok=True)

#     if sel_celltype is None:
#         # Plot all cell types
#         sc.pl.spatial(celltype_compositions, color=celltype_compositions.var.index, size=1.3)
#     else:
#         # Plot specific cell type
#         sc.pl.spatial(celltype_compositions, color=sel_celltype, size=1.3)
        
#     # Save the figure
#     save_path = 'res/spatial_celltype.png'
#     plt.savefig(save_path, dpi=300, bbox_inches='tight')
#     print(f"Neighborhood enrichment plot saved to: {save_path}")
    
#     # Show the plot
#     plt.show()

#     return None

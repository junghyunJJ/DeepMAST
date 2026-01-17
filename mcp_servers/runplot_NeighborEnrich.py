from typing import Optional, Literal, List

import numpy as np
import pandas as pd

import scanpy as sc
import squidpy as sq

import matplotlib.pyplot as plt
import os
import matplotlib.pyplot as plt

from mcp_servers.runplot_LIANAp_NMF import detect_platform, expand_neighbors_n_rings, remove_long_links


def plot_neighborhood_enrichment(
    filename: str,
    cluster_key: str,
    n_rings: int = 2,
    distance_percentile: Optional[float] = 99.0,
    width: int = 5,
    height: int = 5,
    save_path: str = 'res/',
    ) -> None:
    """
    Part 1: Before CCI Analysis - Step 3. Neighborhood Enrichment Analysis (Squidpy)

    Computes neighborhood enrichment to identify clusters that share common neighborhood
    structure across the tissue. This analysis helps identify spatial relationships between
    clusters based on their proximity patterns.

    Concept:
        Computing neighborhood enrichment helps identify observation clusters (spots/cells)
        that share a common neighborhood structure across the tissue. This is an enrichment
        score based on spatial proximity of clusters:

        - **Enriched**: If observations from two different clusters are often close to each
          other, they will have a high z-score and are defined as spatially enriched
        - **Depleted**: If they are far apart and seldom neighbors, the z-score will be low
          and they are defined as spatially depleted

    Statistical Methodology:
        - Tool: Squidpy (squidpy.gr.nhood_enrichment())
        - Method: Permutation-based test
        - Metric: Z-score quantifying spatial proximity enrichment/depletion
        - Null model: Random spatial distribution of clusters

    Squidpy Configuration:
        - n_neighs = 6: Number of nearest neighbors to consider
        - n_rings = 2: Number of neighborhood rings to include in analysis
        - This creates a spatial graph connecting nearby observations

    Workflow Position:
        - Part 1 analysis (before CCI)
        - Step 3: Additional cluster identification
        - Independent analysis result
        - Identifies clusters spatially associated with clusters of interest (from Step 2)
        - Expands cluster selection for downstream pathway and CCI analysis
        - Recommended to repeat Part 1 analysis 3-5 times for consistent results

    Data Requirements:
        - Uses normalized n_adata.h5ad data
        - Requires spatial coordinates in adata.obsm['spatial']
        - Requires cluster annotations in adata.obs[cluster_key]
        - Compatible with spot-based (Visium) and single-cell resolution (MERFISH, Xenium) data

    Args:
        filename (str): Path to the `.h5ad` file containing spatial transcriptomics data
        cluster_key (str): Column name in adata.obs for spatial cluster annotations
        n_rings (int): Number of spatial neighbor rings to include (default: 2)
                       - For Visium: passed directly to sq.gr.spatial_neighbors(n_rings=n_rings)
                       - For single-cell (MERFISH, Xenium, STARmap): Delaunay triangulation provides
                         only 1-hop neighbors, which are then expanded using graph power (A^n)
                         to include n-hop neighbors. n_rings=2 is equivalent to Visium's default.
        distance_percentile (float | None): Percentile threshold for removing long edges from
                       Delaunay triangulation (default: 99.0). Only applied to non-Visium data.
                       - Removes edges longer than the specified percentile of all edge distances
                       - Prevents biologically meaningless long-range connections at tissue boundaries
                       - Set to None to disable long edge removal
                       - Reference: CellCharter remove_long_links() function
        width (int): Figure width in inches (default: 5)
        height (int): Figure height in inches (default: 5)
        save_path (str): Output directory for saving plots and results (default: 'res/')

    Outputs:
        - Image: {save_path}/3.neighborhood_enrichment_squidpy.png
          Heatmap showing z-scores of neighborhood enrichment between cluster pairs
          Positive z-scores (red): Spatial enrichment (clusters often neighbor each other)
          Negative z-scores (blue): Spatial depletion (clusters rarely neighbor each other)

        - CSV: {save_path}/res_nhood_enrichment.csv
          Filtered enrichment results (only positive z-scores, excluding self-interactions)
          Columns:
            - {cluster_key} (first column): Source cluster
            - {cluster_key} (second column): Target cluster
            - value: Z-score (only positive values showing enrichment)
          Note: Self-interactions (same cluster pairs) are excluded
          Note: Only enriched pairs (z-score > 0) are included

    Analysis Results:
        - Additional cluster identification: Identify clusters spatially related to
          clusters of interest from Step 2 (Cell Type Composition Analysis)
        - Spatial relationship mapping: Understand which clusters co-localize in tissue
        - Expanded cluster selection: Include spatially-associated clusters for
          downstream pathway enrichment and CCI analysis
        - Validation: Cross-validate with cell type composition results

    Important Notes:
        - This analysis identifies spatial neighbors that may not share cell type similarity
        - Results complement Step 2 (cell type) analysis with spatial proximity information
        - Use enriched cluster pairs to expand clusters of interest selection
        - Squidpy provides robust permutation-based statistical testing
        - Part 1 analysis variations may occur; recommended to run 3-5 times
        - Selected clusters (original + spatially-associated) inform Part 2 analysis

    Returns:
        None
    """

    adata = sc.read_h5ad(filename)

    # Create res directory if it doesn't exist
    os.makedirs(save_path, exist_ok=True)

    # Detect platform and compute spatial neighbors with appropriate method
    platform = detect_platform(adata)
    if platform == 'visium':
        sq.gr.spatial_neighbors(adata, n_neighs=6, n_rings=n_rings)
        print(f"   Platform: Visium | Spatial neighbors: n_neighs=6, n_rings={n_rings}")
    else:
        # Single-cell resolution (MERFISH, Xenium, STARmap, etc.)
        sq.gr.spatial_neighbors(adata, delaunay=True, coord_type="generic")
        # Remove long edges before expansion (only for non-Visium)
        if distance_percentile is not None:
            n_removed = remove_long_links(adata, distance_percentile=distance_percentile)
            print(f"   Removed {n_removed} long edges (>{distance_percentile}th percentile)")
        if n_rings > 1:
            expand_neighbors_n_rings(adata, n_rings=n_rings)
        print(f"   Platform: {platform} | Spatial neighbors: Delaunay + {n_rings}-ring expansion")

    sq.gr.nhood_enrichment(adata, cluster_key=cluster_key)
    # nhood_enrichment = pd.DataFrame(adata.uns[f'{cluster_key}_nhood_enrichment']['zscore'])
    nhood_enrichment = pd.DataFrame(np.triu(adata.uns[f'{cluster_key}_nhood_enrichment']['zscore']))
    nhood_enrichment.index = adata.obs[cluster_key].cat.categories
    nhood_enrichment.columns = adata.obs[cluster_key].cat.categories
    nhood_enrichment = nhood_enrichment.reset_index()
    m_nhood_enrichment = pd.melt(nhood_enrichment, id_vars=['index'], var_name=cluster_key, value_name='value')
    m_nhood_enrichment = m_nhood_enrichment.rename(columns={'index':cluster_key})
    m_nhood_enrichment = m_nhood_enrichment.sort_values('value', ascending=False)

    # we only focused on the differnet clusters
    m_nhood_enrichment = m_nhood_enrichment[m_nhood_enrichment['value'] > 0]
    m_nhood_enrichment = m_nhood_enrichment[m_nhood_enrichment.iloc[:, 0] != m_nhood_enrichment.iloc[:, 1]]
    m_nhood_enrichment.to_csv(f"{save_path}/res_nhood_enrichment.csv")


    sq.pl.nhood_enrichment(adata, cluster_key=cluster_key)
    
    # Save the figure
    plt.gcf().set_size_inches(width, height)

    save_path = f'{save_path}/3.neighborhood_enrichment_squidpy.png'
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"Neighborhood enrichment plot saved to: {save_path}")
    
    # Show the plot
    # plt.show()
    
    return None



# @mcp.tool()
# def plot_co_occurrence(
#     filename: str,
#     cluster_key: str,
#     source_cluster: List[str],
#     target_cluster: List[str]
#     ) -> None:
#     """
#     Plot cluster co-occurrence in spatial dimensions. 
#     This is a similar analysis of the 'plot_neighborhood_enrichment', 
#     yet it does not operate on the connectivity matrix, 
#     but on the original spatial coordinates.

#     Args:
#         filename: the directory with the `.h5ad` file
#         cluster_key: .obs column names for spatial cluster or cell tpye
#         source_cluster: target cluster name(s)
#         target_cluster: source cluster name(s)
        
#     Returns:
#         None
#     """
    
#     adata = sc.read_h5ad(filename)
#     sq.gr.co_occurrence(adata, cluster_key=cluster_key)
#     import matplotlib.pyplot as plt
#     sq.pl.co_occurrence(
#         adata,
#         cluster_key=cluster_key,
#         clusters=source_cluster + target_cluster
#     )
#     fig = plt.gcf()
#     axes = fig.get_axes()
#     for i, (ax, cluster) in enumerate(zip(axes, source_cluster + target_cluster)):
#         custom_title = f"Co-occurrence: {cluster}"
#         ax.set_title(custom_title)
#         plt.tight_layout()  

#     return None

#!/usr/bin/env python3
"""
Cell Type Composition Heatmap Analysis with Statistical Significance

Converts R pheatmap code to Python and adds statistical testing with asterisk annotations
for significant cell type enrichments in clusters.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats
from scipy.cluster import hierarchy
from scipy.spatial.distance import pdist, squareform
from statsmodels.stats.multitest import multipletests
import anndata as ad
import scanpy as sc
import warnings
warnings.filterwarnings('ignore')


# Color scheme for cell types (optional, can be customized)
COLORS_CELLTYPE = {
    'Epithelium': 'purple',
    'Mesenchyme': 'orange', 
    'Myeloid': 'firebrick',
    'Lymphoid': 'grey',
    'Endothelium': 'lightblue'
}


def calculate_cluster_medians(df_props, cluster_labels):
    """
    Calculate mean cell type proportions per cluster.

    Args:
        df_props: DataFrame with cell type proportions (samples x cell types)
        cluster_labels: Series or array with cluster assignments for each sample

    Returns:
        DataFrame with mean proportions (clusters x cell types)
    """
    df_props['cluster'] = cluster_labels
    cluster_stats = df_props.groupby('cluster').mean()
    return cluster_stats


def perform_statistical_tests(df_props, cluster_labels, alpha=0.05, use_adjusted=True):
    """
    Perform Wilcoxon rank sum tests to identify significant cell type enrichments.
    
    Args:
        df_props: DataFrame with cell type proportions (samples x cell types)
        cluster_labels: Series or array with cluster assignments
        alpha: Significance threshold after multiple testing correction
        use_adjusted: Whether to use FDR-adjusted p-values (default: True)
        
    Returns:
        Tuple of (p_values_df, significance_df)
        - p_values_df: DataFrame with p-values (adjusted if use_adjusted=True)
        - significance_df: Boolean DataFrame indicating significant enrichments
    """
    df_props['cluster'] = cluster_labels
    cell_types = [col for col in df_props.columns if col != 'cluster']
    
    # Store p-values
    p_values = pd.DataFrame(index=df_props['cluster'].unique(), columns=cell_types, dtype=float)
    
    for cluster in df_props['cluster'].unique():
        for cell_type in cell_types:
            # Get values for current cluster vs all others
            cluster_values = df_props[df_props['cluster'] == cluster][cell_type].values
            other_values = df_props[df_props['cluster'] != cluster][cell_type].values
            
            # Perform one-sided Wilcoxon rank sum test
            # Testing if cluster has higher values than others
            try:
                statistic, p_val = stats.mannwhitneyu(
                    cluster_values, other_values,
                    alternative='greater'
                )
                p_values.loc[cluster, cell_type] = p_val
            except:
                p_values.loc[cluster, cell_type] = 1.0
    
    if use_adjusted:
        # Apply multiple testing correction (FDR)
        p_values_flat = p_values.values.flatten()
        reject, p_adjusted, _, _ = multipletests(p_values_flat, alpha=alpha, method='fdr_bh')
        
        # Reshape adjusted p-values
        p_adjusted_df = pd.DataFrame(
            p_adjusted.reshape(p_values.shape),
            index=p_values.index,
            columns=p_values.columns,
            dtype=float
        )
        
        # Create significance matrix using adjusted p-values
        significance = p_adjusted_df < alpha
        return p_values, p_adjusted_df, significance
    else:
        # Use raw p-values without adjustment
        significance = p_values < alpha
        return p_values, significance


def hierarchical_clustering_with_svd(data_matrix, metric='cityblock'):
    """
    Perform hierarchical clustering with SVD-based reordering.
    
    Args:
        data_matrix: Matrix to cluster (features x samples)
        metric: Distance metric ('cityblock' for Manhattan distance)
        
    Returns:
        Reordered indices for rows and columns
    """
    # Calculate distance matrix
    row_dist = pdist(data_matrix, metric=metric)
    col_dist = pdist(data_matrix.T, metric=metric)
    
    # Perform hierarchical clustering
    row_linkage = hierarchy.linkage(row_dist, method='average')
    col_linkage = hierarchy.linkage(col_dist, method='average')
    
    # SVD-based reordering (similar to R callback function)
    U, s, Vt = np.linalg.svd(data_matrix.T)
    weights = Vt[0, :]  # First singular vector
    
    # Get dendrograms and reorder based on weights
    row_dendrogram = hierarchy.dendrogram(row_linkage, no_plot=True)
    col_dendrogram = hierarchy.dendrogram(col_linkage, no_plot=True)
    
    row_order = row_dendrogram['leaves']
    col_order = col_dendrogram['leaves']
    
    return row_order, col_order


def create_heatmap_with_significance(cluster_medians, significance,
                                    output_file='celltype_heatmap_with_significance.png',
                                    figsize=(12, 8), use_adjusted=True):
    """
    Create heatmap with significance asterisks.

    Args:
        cluster_medians: DataFrame with median proportions (clusters x cell types)
        significance: Boolean DataFrame indicating significant enrichments
        output_file: Output filename for the heatmap
        figsize: Figure size tuple
        use_adjusted: Whether adjusted p-values were used (affects title)
    """
    # Scale the data (z-score normalization)
    # Handle zero variance columns to avoid division by zero
    std_vals = cluster_medians.std()
    std_vals = std_vals.replace(0, 1)  # Replace 0 std with 1 to avoid NaN
    scaled_data = (cluster_medians - cluster_medians.mean()) / std_vals

    # Replace any remaining NaN/Inf values with 0
    scaled_data = scaled_data.replace([np.inf, -np.inf], np.nan).fillna(0)

    # Filter out columns with all zero values (no variance)
    non_zero_cols = scaled_data.columns[(scaled_data != 0).any()]
    if len(non_zero_cols) < len(scaled_data.columns):
        print(f"   Note: {len(scaled_data.columns) - len(non_zero_cols)} cell types with zero variance removed from clustering")
    scaled_data_filtered = scaled_data[non_zero_cols]
    significance_filtered = significance[non_zero_cols]

    # Perform hierarchical clustering (only if we have enough data)
    if scaled_data_filtered.shape[0] > 1 and scaled_data_filtered.shape[1] > 1:
        row_order, col_order = hierarchical_clustering_with_svd(scaled_data_filtered.values)
        scaled_data_ordered = scaled_data_filtered.iloc[row_order, col_order]
        significance_ordered = significance_filtered.iloc[row_order, col_order]
    else:
        # Not enough data for clustering, use original order
        scaled_data_ordered = scaled_data_filtered
        significance_ordered = significance_filtered

    # Create figure
    fig, ax = plt.subplots(figsize=figsize)
    
    # Create heatmap
    sns.heatmap(
        scaled_data_ordered.T,  # Transpose to have clusters on x-axis
        cmap='RdYlBu_r',
        center=0,
        cbar_kws={'label': 'Scaled comp.'},
        ax=ax,
        vmin=-4, vmax=4,
        linewidths=0.5,
        linecolor='white'
    )
    
    # Add significance asterisks
    for i, cell_type in enumerate(scaled_data_ordered.columns):
        for j, cluster in enumerate(scaled_data_ordered.index):
            if significance_ordered.loc[cluster, cell_type]:
                ax.text(j + 0.5, i + 0.5, '*', 
                       ha='center', va='center',
                       color='black', fontsize=12, fontweight='bold')
    
    # Customize labels
    ax.set_xlabel('Cluster', fontsize=12)
    ax.set_ylabel('Cell Type', fontsize=12)
    p_value_type = 'adj. P' if use_adjusted else 'P'
    # ax.set_title(f'Scaled Median Cell Type Compositions (n={len(cluster_medians)} clusters)\n'
    #             f'* indicates {p_value_type} < 0.05 (one-sided Wilcoxon rank sum test)',
    #             fontsize=14)
    
    # Rotate x-axis labels
    plt.xticks(rotation=45, ha='right')
    plt.yticks(rotation=0)
    
    # Adjust layout
    plt.tight_layout()
    
    # Save figure
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Heatmap saved to: {output_file}")
    
    return fig, ax


def run_celltype_heatmap_analysis(adata, cluster_key='celltype_niche',
                                 celltype_key=None,
                                 output_file='celltype_heatmap_analysis.png',
                                 width=10, height=5,
                                 use_adjusted_pval=True):
    """
    Run complete cell type composition heatmap analysis using anndata object.

    Supports two data types:
    1. Spot-based (Visium) with deconvolution: Uses adata.obsm['compositions']
    2. Single-cell resolution (MERFISH/Xenium): Uses adata.obs[celltype_key]

    Args:
        adata: AnnData object with compositions in obsm['compositions'] or
               cell type annotations in obs[celltype_key]
        cluster_key: Key in adata.obs containing cluster/region information
        celltype_key: Key in adata.obs containing cell type annotations (for single-cell data).
                      If None, will auto-detect: uses obsm['compositions'] if available,
                      otherwise raises an error.
        output_file: Output filename for the heatmap
        width: Figure width in inches
        height: Figure height in inches
        use_adjusted_pval: Whether to use FDR-adjusted p-values (default: True)

    Returns:
        Dictionary with analysis results
    """
    print("Starting cell type composition analysis...")

    # Step 1: Extract data from anndata (auto-detect data type)
    print("1. Extracting data from anndata...")

    # Determine data type: spot-based (compositions) or single-cell (celltype_key)
    has_compositions = 'compositions' in adata.obsm

    if celltype_key is not None:
        # Single-cell resolution data: use celltype_key from obs
        print(f"   Using single-cell mode with celltype_key='{celltype_key}'")
        if celltype_key not in adata.obs:
            raise ValueError(f"adata.obs['{celltype_key}'] not found")

        # Create one-hot encoding from cell type annotations
        celltypes = adata.obs[celltype_key].astype(str)
        df_props = pd.get_dummies(celltypes).astype(float)
        df_props.index = adata.obs.index
        print(f"   Detected {df_props.shape[1]} cell types from '{celltype_key}'")

    elif has_compositions:
        # Spot-based data: use compositions from obsm
        print("   Using spot-based mode with obsm['compositions']")
        df_props = pd.DataFrame(
            adata.obsm['compositions'],
            index=adata.obs.index
        )

        # Convert all columns to numeric, replacing non-numeric values with NaN
        for col in df_props.columns:
            df_props[col] = pd.to_numeric(df_props[col], errors='coerce')

        # Fill NaN values with 0 (appropriate for composition data)
        df_props = df_props.fillna(0)
        print(f"   Detected {df_props.shape[1]} cell types from compositions")

    else:
        raise ValueError(
            "No cell type data found. Either:\n"
            "  - Provide celltype_key parameter for single-cell data (e.g., celltype_key='sub_level_cell_type')\n"
            "  - Ensure adata.obsm['compositions'] exists for spot-based data"
        )

    # Step 2: Extract cluster labels
    print(f"2. Extracting cluster labels from adata.obs['{cluster_key}']...")
    if cluster_key not in adata.obs:
        print(f"   Warning: '{cluster_key}' not found in adata.obs, using sample names as clusters...")
        cluster_labels = pd.Series(
            df_props.index,
            index=df_props.index
        )
    else:
        cluster_labels = adata.obs[cluster_key]
    
    # Step 3: Calculate cluster mean proportions
    print("3. Calculating cluster mean proportions...")
    cluster_medians = calculate_cluster_medians(df_props.copy(), cluster_labels)
    
    # Step 4: Perform statistical tests
    p_value_type = "FDR-adjusted" if use_adjusted_pval else "raw"
    print(f"4. Performing statistical tests (using {p_value_type} p-values)...")

    if use_adjusted_pval:
        p_values, p_adjusted_df, significance = perform_statistical_tests(
            df_props.copy(), cluster_labels, alpha=0.05, use_adjusted=True
        )
    else:
        p_values, significance = perform_statistical_tests(
            df_props.copy(), cluster_labels, alpha=0.05, use_adjusted=False
        )
        p_adjusted_df = p_values  # Use raw p-values when adjusted is not requested
    
    # Step 5: Create heatmap
    print("5. Creating heatmap with significance markers...")
    fig, ax = create_heatmap_with_significance(
        cluster_medians, significance, output_file, figsize=(width, height), use_adjusted=use_adjusted_pval
    )
    
    print("\nAnalysis complete!")
    
    # Return results
    return {
        'cluster_medians': cluster_medians,
        'pval': p_values,
        'fdr': p_adjusted_df,
        'significance': significance,
        'figure': fig
    }


def create_example_anndata(n_samples=100, n_clusters=5):
    """
    Create example anndata object for demonstration.
    
    Returns:
        AnnData object with compositions and cluster information
    """
    np.random.seed(42)
    
    cell_types = ['Cycling', 'Mast', 'Lymphoid', 'Neuronal', 'Adipo', 
                  'Myeloid', 'Fibroblast', 'CM', 'Endo', 'PC', 'vSMCs']
    
    # Create random proportions that sum to 1
    compositions = []
    cluster_labels = []
    sample_names = []
    
    for i in range(n_samples):
        props = np.random.dirichlet(np.ones(len(cell_types)))
        cluster = f'Niche {i % n_clusters + 1}'
        
        # Add some cluster-specific enrichments
        if 'Niche 1' in cluster:
            props[0] *= 2  # Enrich Cycling
        elif 'Niche 2' in cluster:
            props[2] *= 1.5  # Enrich Lymphoid
        elif 'Niche 3' in cluster:
            props[5] *= 2  # Enrich Myeloid
            
        props = props / props.sum()  # Renormalize
        
        compositions.append(props)
        cluster_labels.append(cluster)
        sample_names.append(f'Sample_{i+1}')
    
    # Create AnnData object
    adata = ad.AnnData(X=np.random.randn(n_samples, 100))  # Dummy expression data
    adata.obs.index = sample_names
    adata.obs['celltype_niche'] = cluster_labels
    
    # Add compositions to obsm with column names
    compositions_df = pd.DataFrame(
        compositions,
        index=sample_names,
        columns=cell_types
    )
    adata.obsm['compositions'] = compositions_df.values
    
    # Store cell type names for reference
    adata.uns['celltype_names'] = cell_types
    
    return adata


if __name__ == "__main__":
    # Create example anndata (replace with your actual data)
    print("Creating example anndata...")
    adata = create_example_anndata(n_samples=100, n_clusters=5)
    
    # Run analysis
    results = run_celltype_heatmap_analysis(
        adata,
        cluster_key='celltype_niche',
        output_file='celltype_heatmap_with_asterisks.png'
    )
    
    # Print summary statistics
    print("\nSummary Statistics:")
    print(f"Number of clusters: {len(results['cluster_medians'])}")
    print(f"Number of cell types: {len(results['cluster_medians'].columns)}")
    print(f"Significant enrichments found: {results['significance'].sum().sum()}")
    
    # Show which cell types are enriched in which clusters
    print("\nSignificant Enrichments:")
    for cluster in results['significance'].index:
        enriched = results['significance'].loc[cluster]
        enriched_types = enriched[enriched].index.tolist()
        if enriched_types:
            print(f"  {cluster}: {', '.join(enriched_types)}")
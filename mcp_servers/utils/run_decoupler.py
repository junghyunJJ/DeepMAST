import sys

import numpy as np
import pandas as pd
import scanpy as sc
import squidpy as sq
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.gridspec import GridSpec

import decoupler as dc
import liana as li
from scipy.sparse import issparse
from utils.utils import cauchy_combination

def sp_enrich(adata, cluster_key, organism='human', geneset='progeny', min_n=5):
    """
    Compute pathway activity scores using multivariate linear model (MLM).

    Args:
        adata: AnnData object with gene expression data
        cluster_key: Key in adata.obs containing cluster annotations
        organism: 'human' or 'mouse' for geneset selection
        geneset: 'progeny' or 'hallmark' pathway geneset
        min_n: Minimum number of targets per source (pathway) required for analysis.
               Default is 5. For single-cell resolution data with limited gene panels
               (e.g., STARmap, MERFISH), use lower values like 1-3.
               Note: Requires decoupler >= 1.4.0. If older version, this parameter is ignored.

    Returns:
        AnnData object with pathway activity scores
    """
    # 1. use multivariate linear model to estimate activity using Hallmark/progeny gene set
    if geneset == 'progeny':
      #NOTE!!! we focus on the top=500
    #   dc_geneset  = dc.op.progeny(organism=organism, top=500)
      dc_geneset  = dc.op.progeny(organism=organism)

    elif geneset == 'hallmark':
       dc_geneset  = dc.op.hallmark(organism=organism)
    else :
      print('please set the geneset (progeny or hallmark)')
      sys.exit(1)

    dc.mt.mlm(
      adata,
      net=dc_geneset,
      verbose=False,
      raw=False,
      tmin=min_n  # tmin is the actual parameter name in decoupler
    )

    # 2. rank genes by t-test_overestim_var
    adata_dc = dc.pp.get_obsm(adata=adata, key="score_mlm")

    return adata_dc


def plot_pathway_enrich_matrixplot(adata_dc, cluster_key, reference='rest', threshold=0.05, n_markers = 3):

    df = dc.tl.rankby_group(adata=adata_dc, groupby=cluster_key, reference=reference)
    df = df[(df["padj"] < threshold) & (df["stat"] > 0)]
    final_df = df.groupby("group").head(n_markers)    

    source_markers = (
      df.groupby("group")
      .head(n_markers)
      .drop_duplicates("name")
      .groupby("group")["name"]
      .apply(lambda x: list(x))
      .to_dict()
    )
    # source_markers = [item for sublist in source_markers.values() for item in sublist]
    source_markers = sum(source_markers.values(), [])
    mp = sc.pl.matrixplot(
      adata=adata_dc,
      var_names=source_markers,
      groupby=cluster_key,
      dendrogram=True,
      standard_scale="var",
      colorbar_title="Z-scaled scores",
      cmap="RdBu_r",
      swap_axes=False,
      show=False,  # Don't show immediately
      return_fig=True  # Return figure object
    )
    return final_df, mp  # Return both dataframe and matrixplot object


def plot_pathway_spatial_violin(adata_dc, pathways, cluster_key='celltype_niche', 
                                figsize=(15, 5), cmap='RdBu_r', vcenter=0,
                                save_path=None, title=None):
    """
    Plot spatial distribution and violin plots for selected pathways.
    
    Parameters:
    -----------
    adata_dc : AnnData
        AnnData object with pathway scores
    pathways : list or str
        List of pathway names or single pathway name to plot
    cluster_key : str
        Key in adata.obs for cluster grouping (default: 'celltype_niche')
    figsize : tuple
        Base figure size for each pathway (default: (15, 5))
    cmap : str
        Colormap for spatial plot (default: 'RdBu_r')
    vcenter : float
        Center value for colormap (default: 0)
    save_path : str
        Path to save the figure (optional)
    title : str
        Custom title for the figure (optional)
        
    Returns:
    --------
    fig : matplotlib figure
        Figure object containing all plots
    axes : list
        List of axes objects
    """
    
    # Convert single pathway to list
    if isinstance(pathways, str):
        pathways = [pathways]
    
    # Filter pathways that exist in the data
    available_pathways = adata_dc.var_names.tolist() if hasattr(adata_dc, 'var_names') else []
    valid_pathways = []
    for pw in pathways:
        if pw in available_pathways:
            valid_pathways.append(pw)
        else:
            print(f"Warning: {pw} not found in data")
    
    if not valid_pathways:
        print("Error: No valid pathways found in data")
        return None, None
    
    # Create figure with custom grid
    n_pathways = len(valid_pathways)
    fig = plt.figure(figsize=(figsize[0], figsize[1] * n_pathways))
    gs = GridSpec(n_pathways, 3, figure=fig, width_ratios=[1.5, 1.5, 2])
    
    axes = []
    
    for i, pathway in enumerate(valid_pathways):
        # Spatial plot (larger, spans 2 columns)
        ax1 = fig.add_subplot(gs[i, :2])
        sc.pl.spatial(adata_dc, color=pathway, cmap=cmap, vcenter=vcenter,
                     size=1.5, ax=ax1, show=False, title='')
        ax1.set_title(f'{pathway} - Spatial Distribution', fontsize=12, fontweight='bold')
        axes.append(ax1)
        
        # Violin plot
        ax2 = fig.add_subplot(gs[i, 2])
        sc.pl.violin(adata_dc, keys=pathway, groupby=cluster_key,
                    rotation=90, ax=ax2, show=False)
        ax2.set_title(f'{pathway} - Expression by Cluster', fontsize=12, fontweight='bold')
        axes.append(ax2)
    
    # Add overall title
    if title:
        plt.suptitle(title, fontsize=16, y=1.02)
    else:
        plt.suptitle('Pathway Analysis: Spatial Distribution and Expression Levels',
                    fontsize=16, y=1.02)
    
    # Adjust layout
    plt.tight_layout()
    
    # Save figure if path provided
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"Figure saved to: {save_path}")
    
    return fig, axes


# def plot_pathway_comparison(adata_dc, pathways, cluster_key='celltype_niche',
#                            figsize=(16, 6), cmap='RdBu_r', save_path=None):
#     """
#     Create a comprehensive comparison plot for multiple pathways.
#     Includes spatial plots, violin plots, and correlation analysis.
    
#     Parameters:
#     -----------
#     adata_dc : AnnData
#         AnnData object with pathway scores
#     pathways : list
#         List of pathway names to compare
#     cluster_key : str
#         Key in adata.obs for cluster grouping
#     figsize : tuple
#         Figure size (default: (16, 6))
#     cmap : str
#         Colormap for spatial plots
#     save_path : str
#         Path to save the figure (optional)
        
#     Returns:
#     --------
#     fig : matplotlib figure
#     axes : dict
#         Dictionary of axes organized by plot type
#     """
    
#     # Validate pathways
#     if isinstance(pathways, str):
#         pathways = [pathways]
    
#     n_pathways = len(pathways)
    
#     # Create figure with subplots
#     fig = plt.figure(figsize=(figsize[0], figsize[1] * n_pathways))
#     gs = GridSpec(n_pathways + 1, 4, figure=fig, 
#                   height_ratios=[1] * n_pathways + [0.5],
#                   width_ratios=[1, 1, 1.5, 1])
    
#     axes = {'spatial': [], 'violin': [], 'stats': None}
    
#     # Plot each pathway
#     for i, pathway in enumerate(pathways):
#         # Spatial plot
#         ax_spatial = fig.add_subplot(gs[i, 0:2])
#         sc.pl.spatial(adata_dc, color=pathway, cmap=cmap, vcenter=0,
#                      size=1.5, ax=ax_spatial, show=False, title='')
#         ax_spatial.set_title(f'{pathway}', fontsize=11, fontweight='bold')
#         axes['spatial'].append(ax_spatial)
        
#         # Violin plot
#         ax_violin = fig.add_subplot(gs[i, 2])
#         sc.pl.violin(adata_dc, keys=pathway, groupby=cluster_key,
#                     rotation=45, ax=ax_violin, show=False)
#         ax_violin.set_title('By Cluster', fontsize=10)
#         axes['violin'].append(ax_violin)
        
#         # Statistics box
#         ax_stats = fig.add_subplot(gs[i, 3])
#         ax_stats.axis('off')
        
#         # Calculate statistics
#         expr_data = adata_dc[:, pathway].X
#         if hasattr(expr_data, 'toarray'):
#             expr_data = expr_data.toarray().flatten()
        
#         stats_text = f"Mean: {np.mean(expr_data):.3f}\n"
#         stats_text += f"Std: {np.std(expr_data):.3f}\n"
#         stats_text += f"Min: {np.min(expr_data):.3f}\n"
#         stats_text += f"Max: {np.max(expr_data):.3f}"
        
#         ax_stats.text(0.1, 0.5, stats_text, fontsize=9,
#                      verticalalignment='center', family='monospace')
    
#     # Add correlation heatmap in the last row
#     if n_pathways > 1:
#         ax_corr = fig.add_subplot(gs[n_pathways, :])
        
#         # Calculate correlation matrix
#         pathway_data = []
#         for pw in pathways:
#             expr = adata_dc[:, pw].X
#             if hasattr(expr, 'toarray'):
#                 expr = expr.toarray().flatten()
#             pathway_data.append(expr)
        
#         pathway_df = pd.DataFrame(pathway_data, index=pathways).T
#         corr_matrix = pathway_df.corr()
        
#         # Plot correlation
#         im = ax_corr.imshow(corr_matrix, cmap='coolwarm', vmin=-1, vmax=1, aspect='auto')
#         ax_corr.set_xticks(range(len(pathways)))
#         ax_corr.set_yticks(range(len(pathways)))
#         ax_corr.set_xticklabels(pathways, rotation=45, ha='right', fontsize=9)
#         ax_corr.set_yticklabels(pathways, fontsize=9)
#         ax_corr.set_title('Pathway Correlations', fontsize=10, fontweight='bold')
        
#         # Add correlation values
#         for i in range(len(pathways)):
#             for j in range(len(pathways)):
#                 text = ax_corr.text(j, i, f'{corr_matrix.iloc[i, j]:.2f}',
#                                    ha='center', va='center', fontsize=8)
        
#         # Add colorbar
#         cbar = plt.colorbar(im, ax=ax_corr, orientation='horizontal', 
#                            pad=0.1, shrink=0.8)
#         cbar.set_label('Correlation', fontsize=9)
        
#         axes['stats'] = ax_corr
    
#     # Overall title
#     plt.suptitle('Pathway Comparison Analysis', fontsize=14, fontweight='bold', y=1.02)
    
#     # Adjust layout
#     plt.tight_layout()
    
#     # Save if requested
#     if save_path:
#         plt.savefig(save_path, dpi=300, bbox_inches='tight')
#         print(f"Figure saved to: {save_path}")
    
#     return fig, axes


# def cauchy_combine_pathways(adata, cluster_key='celltype_niche', pval_key='padj_mlm', min_cells=10):
#     """
#     Combine pathway p-values by cluster using Cauchy combination.
    
#     Parameters:
#     -----------
#     adata : AnnData
#         AnnData object containing pathway p-values in obsm
#     cluster_key : str
#         Key in adata.obs for cluster grouping (default: 'celltype_niche')
#     pval_key : str
#         Key in adata.obsm containing p-values matrix (default: 'padj_mlm')
#     min_cells : int
#         Minimum number of cells required to include the result (default: 10)
#         Results with fewer cells will be filtered out after Cauchy combination
        
#     Returns:
#     --------
#     pd.DataFrame
#         DataFrame with columns: cluster, pathway, combined_pval, neg_log10_pval, n_cells
#         Only includes results where n_cells >= min_cells
        
#     Example:
#     --------
#     >>> result_df = cauchy_combine_pathways(adata_dc, cluster_key='celltype_niche')
#     >>> # Get results for specific pathway (with default min_cells=10)
#     >>> p53_results = result_df[result_df['pathway'] == 'P53_PATHWAY']
#     >>> # Get all results without filtering
#     >>> all_results = cauchy_combine_pathways(adata_dc, min_cells=0)
#     >>> # Get results with at least 50 cells
#     >>> robust_results = cauchy_combine_pathways(adata_dc, min_cells=50)
#     """
    
#     # Extract p-values matrix
#     pvals_matrix = adata.obsm[pval_key]
    
#     # Handle different data types
#     if isinstance(pvals_matrix, pd.DataFrame):
#         # If it's a DataFrame, use .values to get numpy array
#         pvals_array = pvals_matrix.values
#         # Get pathway names from DataFrame columns
#         pathway_names = pvals_matrix.columns.tolist()
#     else:
#         # Convert sparse to dense if needed
#         if issparse(pvals_matrix):
#             pvals_array = pvals_matrix.toarray()
#         else:
#             pvals_array = np.array(pvals_matrix)
#         # Get pathway names from adata.var.index
#         pathway_names = adata.var.index.tolist()
    
#     # Get cluster values
#     cluster_values = adata.obs[cluster_key].astype(str).values
#     unique_clusters = np.unique(cluster_values)
    
#     # Store results
#     results = []
    
#     # For each pathway
#     for pathway_idx, pathway_name in enumerate(pathway_names):
#         pathway_pvals = pvals_array[:, pathway_idx]
        
#         # Ensure it's a 1D array
#         if hasattr(pathway_pvals, 'flatten'):
#             pathway_pvals = pathway_pvals.flatten()
        
#         # For each cluster
#         for cluster in unique_clusters:
#             # Get cells in this cluster
#             cluster_mask = cluster_values == cluster
#             cluster_pvals = pathway_pvals[cluster_mask]
            
#             # Filter valid p-values
#             valid_pvals = []
#             for pval in cluster_pvals:
#                 if pd.notna(pval) and 0 < pval <= 1:
#                     valid_pvals.append(float(pval))
            
#             # Apply Cauchy combination
#             if valid_pvals:
#                 try:
#                     combined_pval = cauchy_combination(valid_pvals)
                    
#                     # Calculate -log10(p)
#                     if combined_pval > 0:
#                         neg_log10_pval = -np.log10(combined_pval)
#                     else:
#                         neg_log10_pval = 10  # Cap at 10 for p=0
                    
#                     results.append({
#                         'cluster': cluster,
#                         'pathway': pathway_name,
#                         'combined_pval': combined_pval,
#                         'neg_log10_pval': neg_log10_pval,
#                         'n_cells': len(valid_pvals)
#                     })
#                 except Exception as e:
#                     print(f"Error combining p-values for {cluster}, {pathway_name}: {e}")
#             else:
#                 # No valid p-values for this combination
#                 results.append({
#                     'cluster': cluster,
#                     'pathway': pathway_name,
#                     'combined_pval': 1.0,
#                     'neg_log10_pval': 0.0,
#                     'n_cells': 0
#                 })
    
#     # Create DataFrame with all results
#     results_df = pd.DataFrame(results)
    
#     # Filter by min_cells if specified
#     if min_cells > 0 and not results_df.empty:
#         filtered_df = results_df[results_df['n_cells'] >= min_cells].copy()
        
#         # Print filtering info
#         n_filtered = len(results_df) - len(filtered_df)
#         if n_filtered > 0:
#             print(f"Filtered out {n_filtered} cluster-pathway combinations with < {min_cells} cells")
        
#         return filtered_df
    
#     return results_df


# def plot_cauchy_pathways(results_df, figsize=(12, 7), save_path=None, show_summary=True):
#     """
#     Plot Cauchy-combined p-values as grouped barplot.
    
#     Parameters:
#     -----------
#     results_df : pd.DataFrame
#         Results from cauchy_combine_pathways function
#     figsize : tuple
#         Figure size (default: (12, 7))
#     save_path : str
#         Path to save the figure (optional)
#     show_summary : bool
#         Whether to print summary statistics (default: True)
        
#     Returns:
#     --------
#     fig : matplotlib figure
#     ax : matplotlib axes
#     pivot_df : pd.DataFrame
#         Pivoted DataFrame with clusters as index and pathways as columns
#     """
    
#     # Create pivot table
#     pivot_df = results_df.pivot(index='cluster', columns='pathway', values='neg_log10_pval')
    
#     # Create the plot
#     fig, ax = plt.subplots(figsize=figsize)
    
#     # Create grouped barplot
#     pivot_df.plot(kind='bar', ax=ax, width=0.7, colormap='tab10')
    
#     # Customize the plot
#     ax.set_xlabel('Cluster', fontsize=12)
#     ax.set_ylabel('-log10(Cauchy Combined P-value)', fontsize=12)
#     ax.set_title('Cauchy-Combined P-values by Cluster and Pathway', fontsize=14, fontweight='bold')
    
#     # Rotate x-axis labels for better readability
#     plt.xticks(rotation=45, ha='right')
    
#     # Add horizontal line at -log10(0.05) for significance threshold
#     ax.axhline(y=-np.log10(0.05), color='red', linestyle='--', alpha=0.5, label='p=0.05')
    
#     # Add grid for better readability
#     ax.grid(True, alpha=0.3, axis='y')
    
#     # Move legend to best position
#     ax.legend(title='Pathway', bbox_to_anchor=(1.05, 1), loc='upper left', ncol=2)
    
#     # Adjust layout to prevent label cutoff
#     plt.tight_layout()
    
#     # Save figure if path provided
#     if save_path:
#         plt.savefig(save_path, dpi=300, bbox_inches='tight')
#         print(f"Figure saved to: {save_path}")
    
#     # Print summary statistics if requested
#     if show_summary:
#         print("\nCauchy-Combined P-values Summary:")
#         print("="*70)
#         print("\n-log10(Combined P-value) by Cluster and Pathway:")
#         print(pivot_df.round(3))
        
#         # Create n_cells pivot table
#         pivot_n = results_df.pivot(index='cluster', columns='pathway', values='n_cells')
#         print("\nNumber of cells used for combination:")
#         print(pivot_n)
        
#         # Print significant combinations
#         print("\nSignificant combinations (p < 0.05, i.e., -log10(p) > 1.3):")
#         print("="*70)
#         significant = results_df[results_df['neg_log10_pval'] > -np.log10(0.05)]
#         if not significant.empty:
#             for _, row in significant.iterrows():
#                 print(f"{row['cluster']} - {row['pathway']}: -log10(p) = {row['neg_log10_pval']:.3f}")
#         else:
#             print("No significant combinations found")
    
#     return fig, ax, pivot_df


# def plot_cauchy_heatmap(results_df, figsize=(16, 10), cmap='RdYlBu_r', save_path=None, 
#                         max_pathways=30, annot=True):
#     """
#     Plot Cauchy-combined p-values as heatmap.
    
#     Parameters:
#     -----------
#     results_df : pd.DataFrame
#         Results from cauchy_combine_pathways function
#     figsize : tuple
#         Figure size (default: (16, 10))
#     cmap : str
#         Colormap for heatmap (default: 'RdYlBu_r')
#     save_path : str
#         Path to save the figure (optional)
#     max_pathways : int
#         Maximum number of pathways to display (default: 30)
#     annot : bool
#         Whether to annotate cells with values (default: True)
        
#     Returns:
#     --------
#     fig : matplotlib figure
#     axes : tuple of matplotlib axes
#     pivot_df : pd.DataFrame
#         Pivoted DataFrame with clusters as index and pathways as columns
#     """
    
#     # Filter to top pathways if necessary
#     if len(results_df['pathway'].unique()) > max_pathways:
#         # Get top pathways by mean -log10(p-value)
#         top_pathways = (results_df.groupby('pathway')['neg_log10_pval']
#                        .mean()
#                        .nlargest(max_pathways)
#                        .index.tolist())
#         results_df_filtered = results_df[results_df['pathway'].isin(top_pathways)].copy()
#         print(f"Showing top {max_pathways} pathways (out of {len(results_df['pathway'].unique())})")
#     else:
#         results_df_filtered = results_df.copy()
    
#     # Create pivot tables
#     pivot_df = results_df_filtered.pivot(index='cluster', columns='pathway', values='neg_log10_pval')
#     pivot_n = results_df_filtered.pivot(index='cluster', columns='pathway', values='n_cells')
    
#     # Fill NaN values with 0 (no data)
#     pivot_df = pivot_df.fillna(0)
#     pivot_n = pivot_n.fillna(0)
    
#     # Calculate figure size based on data dimensions
#     n_clusters = len(pivot_df.index)
#     n_pathways = len(pivot_df.columns)
    
#     # Adjust figsize if needed
#     if n_pathways > 20 or n_clusters > 10:
#         figsize = (max(16, n_pathways * 0.4), max(10, n_clusters * 0.5))
    
#     # Create the plot with two subplots
#     fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize)
    
#     # Determine annotation format based on data size
#     if n_pathways > 15 or n_clusters > 15:
#         annot_fmt = '.1f'
#         annot_size = 6
#     else:
#         annot_fmt = '.2f'
#         annot_size = 8
    
#     # Determine if we should annotate
#     show_annot = annot and (n_pathways <= 30 and n_clusters <= 15)
    
#     # Heatmap of -log10(p-values)
#     vmax_val = pivot_df.max().max()
#     if pd.isna(vmax_val) or vmax_val == 0:
#         vmax_val = 10
#     else:
#         vmax_val = max(vmax_val, -np.log10(0.001))
    
#     sns.heatmap(pivot_df, annot=show_annot, fmt=annot_fmt, cmap=cmap, ax=ax1,
#                 annot_kws={'size': annot_size},
#                 cbar_kws={'label': '-log10(p-value)'}, 
#                 vmin=0, vmax=vmax_val,
#                 linewidths=0.5, linecolor='gray')
    
#     ax1.set_title('Cauchy Combined P-values\n(-log10 scale)', fontsize=12, fontweight='bold')
#     ax1.set_xlabel('Pathway', fontsize=10)
#     ax1.set_ylabel('Cluster', fontsize=10)
    
#     # Rotate x-axis labels for better readability
#     ax1.set_xticklabels(ax1.get_xticklabels(), rotation=45, ha='right', fontsize=8)
#     ax1.set_yticklabels(ax1.get_yticklabels(), rotation=0, fontsize=9)
    
#     # Heatmap of cell counts
#     sns.heatmap(pivot_n, annot=show_annot, fmt='g', cmap='YlOrRd', ax=ax2,
#                 annot_kws={'size': annot_size},
#                 cbar_kws={'label': 'Number of cells'},
#                 linewidths=0.5, linecolor='gray')
    
#     ax2.set_title('Number of Cells\nper Combination', fontsize=12, fontweight='bold')
#     ax2.set_xlabel('Pathway', fontsize=10)
#     ax2.set_ylabel('')
    
#     # Rotate x-axis labels
#     ax2.set_xticklabels(ax2.get_xticklabels(), rotation=45, ha='right', fontsize=8)
#     ax2.set_yticklabels([])  # Hide y-axis labels for second plot
    
#     # Adjust layout
#     plt.tight_layout()
    
#     # Save figure if path provided
#     if save_path:
#         plt.savefig(save_path, dpi=300, bbox_inches='tight')
#         print(f"Figure saved to: {save_path}")
    
#     return fig, (ax1, ax2), pivot_df


# def plot_top_pathways(results_df, top_n=20, figsize=(10, 8), save_path=None):
#     """
#     Plot top N most significant cluster-pathway combinations.
    
#     Parameters:
#     -----------
#     results_df : pd.DataFrame
#         Results from cauchy_combine_pathways function
#     top_n : int
#         Number of top results to show (default: 20)
#     figsize : tuple
#         Figure size (default: (10, 8))
#     save_path : str
#         Path to save the figure (optional)
        
#     Returns:
#     --------
#     fig : matplotlib figure
#     ax : matplotlib axes
#     top_results : pd.DataFrame
#         Top N results
#     """
    
#     # Get top results
#     top_results = results_df.nlargest(top_n, 'neg_log10_pval').copy()
    
#     # Create labels
#     top_results['label'] = top_results['cluster'] + '\n' + top_results['pathway'].str[:20]
    
#     # Create the plot
#     fig, ax = plt.subplots(figsize=figsize)
    
#     # Create horizontal barplot
#     y_pos = np.arange(len(top_results))
#     colors = plt.cm.viridis(np.linspace(0, 1, len(top_results)))
    
#     bars = ax.barh(y_pos, top_results['neg_log10_pval'].values, color=colors)
    
#     # Customize
#     ax.set_yticks(y_pos)
#     ax.set_yticklabels(top_results['label'].values, fontsize=9)
#     ax.set_xlabel('-log10(p-value)', fontsize=12)
#     ax.set_title(f'Top {top_n} Most Significant Cluster-Pathway Combinations', 
#                  fontsize=14, fontweight='bold')
    
#     # Add significance threshold
#     ax.axvline(x=-np.log10(0.05), color='red', linestyle='--', 
#                alpha=0.5, label='p=0.05')
#     ax.axvline(x=-np.log10(0.01), color='orange', linestyle='--', 
#                alpha=0.5, label='p=0.01')
    
#     # Add value labels on bars
#     for i, (bar, n_cells) in enumerate(zip(bars, top_results['n_cells'].values)):
#         width = bar.get_width()
#         ax.text(width + 0.1, bar.get_y() + bar.get_height()/2, 
#                 f'n={n_cells}', ha='left', va='center', fontsize=8)
    
#     ax.legend()
#     ax.grid(True, alpha=0.3, axis='x')
    
#     # Adjust layout
#     plt.tight_layout()
    
#     # Save figure if path provided
#     if save_path:
#         plt.savefig(save_path, dpi=300, bbox_inches='tight')
#         print(f"Figure saved to: {save_path}")
    
#     return fig, ax, top_results
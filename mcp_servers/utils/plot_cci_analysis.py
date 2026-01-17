"""
Plotting utilities for Cell-Cell Interaction Analysis
Functions for visualizing CCI results with mean expression and p-values
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from typing import List, Optional, Tuple, Union

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


import numpy as np
import pandas as pd

# 1. Quadrant categorization function
def categorize_lr_pair(row, moran_threshold, sel_factor, factor_threshold):
    """
    Categorize L-R pairs into 4 quadrants based on Moran's R and sel_factor values

    Q1 (High-High): Spatially organized invasion signaling
    Q2 (Low-High): Cell-autonomous invasion signaling
    Q3 (High-Low): General spatial signaling
    Q4 (Low-Low): Low priority
    """
    if row['morans'] > moran_threshold and row[sel_factor] > factor_threshold:
        return 'Q1'
    elif row['morans'] <= moran_threshold and row[sel_factor] > factor_threshold:
        return 'Q2'
    elif row['morans'] > moran_threshold and row[sel_factor] <= factor_threshold:
        return 'Q3'
    else:
        return 'Q4'



def plot_quadrant(
    sig_liana,
    interest_sig_liana,
    sel_factor,
    n_top_label: int = 10,
    figsize: Tuple[int, int] = (14, 6),
    save_path: Optional[str] = None
) -> plt.Figure:

    # 2. Set thresholds (using median as cutoff)
    moran_threshold = sig_liana['morans'].median()
    factor_threshold = sig_liana[sel_factor].median()

    print(f"Thresholds:")
    print(f"  Moran's R: {moran_threshold:.4f}")
    print(f"  {sel_factor}: {factor_threshold:.4f}\n")

    # 3. Apply categorization
    sig_liana_quad = sig_liana.copy()
    sig_liana_quad['quadrant'] = sig_liana_quad.apply(
        lambda row: categorize_lr_pair(row, moran_threshold, sel_factor, factor_threshold), 
        axis=1
    )

    # 4. Summary statistics
    print("Quadrant Distribution:")
    print(sig_liana_quad['quadrant'].value_counts().sort_index())
    print(f"\nTotal L-R pairs: {len(sig_liana_quad)}")



    # Enhanced quadrant plot with annotations
    fig, ax = plt.subplots(figsize=figsize)

    # Define colors for each quadrant
    quadrant_colors = {
        'Q1': '#E74C3C',  # Red - Most important
        'Q2': '#F39C12',  # Orange
        'Q3': '#3498DB',  # Blue
        'Q4': '#95A5A6'   # Gray
    }

    # Define labels for legend
    quadrant_labels = {
        'Q1': 'Q1 Spatially co-localized + High factor',
        'Q2': 'Q2 Cell-autonomous (no spatial)',
        'Q3': 'Q3 Spatial but low factor',
        'Q4': 'Q4 Low priority'
    }

    # Get interest interaction indices
    interest_indices = set(interest_sig_liana.index)

    # Plot each quadrant with different colors and markers
    for quad, color in quadrant_colors.items():
        quad_data = sig_liana_quad[sig_liana_quad['quadrant'] == quad]

        # Skip if no data in this quadrant
        if len(quad_data) == 0:
            continue

        # Separate interest and non-interest interactions
        non_interest_data = quad_data[~quad_data.index.isin(interest_indices)]
        interest_data = quad_data[quad_data.index.isin(interest_indices)]

        # Prepare label for legend (will be added to first scatter only)
        label = f"{quadrant_labels[quad]} (n={len(quad_data)})"
        label_added = False

        # Plot non-interest interactions with circle marker
        if len(non_interest_data) > 0:
            ax.scatter(
                non_interest_data['morans'],
                non_interest_data[sel_factor],
                c=color,
                marker='o',
                s=80,
                alpha=0.6,
                edgecolors='black',
                linewidth=0.5,
                label=label
            )
            label_added = True

        # Plot interest interactions with star marker
        if len(interest_data) > 0:
            ax.scatter(
                interest_data['morans'],
                interest_data[sel_factor],
                c=color,
                marker='*',
                s=200,
                alpha=0.8,
                edgecolors='black',
                linewidth=0.8,
                label=label if not label_added else None
            )

    # Add threshold lines
    ax.axvline(x=moran_threshold, color='black', linestyle='--', linewidth=2, alpha=0.7, label='Thresholds')
    ax.axhline(y=factor_threshold, color='black', linestyle='--', linewidth=2, alpha=0.7)


    # Labels and title
    ax.set_xlabel('Moran\'s R (Bivariate Spatial Co-clustering)', fontsize=13, fontweight='bold')
    ax.set_ylabel(f'{sel_factor} (NMF Loading)', fontsize=13, fontweight='bold')
    # ax.set_title('Quadrant Analysis: Spatial Organization vs Invasion Program Association', 
    #             fontsize=15, fontweight='bold', pad=20)

    # Grid
    ax.grid(True, alpha=0.2, linestyle=':')

    # Legend
    legend1 = ax.legend(loc='lower right', frameon=True, fancybox=True, shadow=True, fontsize=10)

    # Add custom legend for star markers (interest interactions)
    star_marker = mpatches.Patch(color='gray', label=f'★ Interest celltypes (n={len(interest_indices)})')
    ax.add_artist(legend1)  # Keep the first legend
    ax.legend(handles=[star_marker], loc='upper left', frameon=True, fancybox=True, shadow=True, fontsize=10)

    # Add annotation for top Q1 candidates
    if len(interest_sig_liana) > 0:
        interest_sig_liana_copy = interest_sig_liana.copy()
        interest_sig_liana_copy['combined_score'] = interest_sig_liana_copy['morans'] * interest_sig_liana_copy[sel_factor]
        top_q1 = interest_sig_liana_copy.nlargest(n_top_label, 'combined_score')
        
        for idx, row in top_q1.iterrows():
            ax.annotate(
                idx,  # interaction name
                xy=(row['morans'], row[sel_factor]),
                xytext=(10, 10),
                textcoords='offset points',
                fontsize=8,
                bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.5, edgecolor='black'),
                arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0', color='black', lw=0.5)
            )

    plt.tight_layout()
    plt.savefig(f'{save_path}/9.quadrant_analysis.png', dpi=300, bbox_inches='tight')
    plt.show()

    print(f"Enhanced quadrant plot saved to: {save_path}/9.quadrant_analysis.png")


def old_plot_interaction(
    lrdata,
    sel_interactions: List[str],
    cluster_key: str = 'celltype_niche',
    p_th: float = 0.05,
    figsize: Tuple[int, int] = (14, 6),
    save_path: Optional[str] = None,
    filename_suffix: str = ''
) -> plt.Figure:

    # Combined plot - both interaction means and p-values in one figure
    import matplotlib.pyplot as plt
    from utils.plot_cci_analysis import plot_interaction_means, plot_interaction_pvals

    # Create figure with two subplots side by side
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize)

    # Plot 1: Interaction means (left)
    plt.sca(ax1)
    from utils.plot_cci_analysis import plot_interaction_means
    from scipy.sparse import issparse
    import numpy as np
    import pandas as pd

    # Extract data from 'cats' layer
    layer_data = lrdata.layers['cats']
    if issparse(layer_data):
        layer_data = layer_data.toarray()

    celltype_values = lrdata.obs[cluster_key].astype(str).values
    unique_celltypes = sorted(np.unique(celltype_values))

    # Prepare data for means plot
    plot_data_means = []
    for interaction in sel_interactions:
        if interaction in lrdata.var.index:
            idx = lrdata.var.index.get_loc(interaction)
            interaction_values = layer_data[:, idx]
            if hasattr(interaction_values, 'flatten'):
                interaction_values = interaction_values.flatten()
            
            for celltype in unique_celltypes:
                celltype_mask = celltype_values == celltype
                celltype_vals = interaction_values[celltype_mask]
                mean_value = np.nanmean(celltype_vals) if len(celltype_vals) > 0 else np.nan
                plot_data_means.append({
                    'celltype': celltype,
                    'interaction': interaction,
                    'mean': mean_value
                })

    plot_df_means = pd.DataFrame(plot_data_means)

    # Define consistent color palette
    colors = ['#5A9F8C', '#EC8B67', '#6B8FD4', '#D4A76A', '#8D6B94']

    # Plot bars for means
    x = np.arange(len(unique_celltypes))
    width = 0.35 if len(sel_interactions) == 2 else 0.8 / len(sel_interactions)

    for i, interaction in enumerate(sel_interactions):
        df_int = plot_df_means[plot_df_means['interaction'] == interaction].sort_values('celltype')
        offset = width * (i - len(sel_interactions)/2 + 0.5)
        bars = ax1.bar(x + offset, df_int['mean'].values, width, 
                    label=interaction, color=colors[i % len(colors)], alpha=0.8,
                    edgecolor='black', linewidth=0.8)

    # ax1.set_xlabel(cluster_key, fontsize=12)
    ax1.set_ylabel('Mean Expression Value', fontsize=12)
    ax1.set_title(f'Ligand-Receptor Interactions by {cluster_key} (Mean)', fontsize=14, fontweight='bold')
    ax1.set_xticks(x)
    ax1.set_xticklabels(unique_celltypes, rotation=45, ha='right')
    ax1.legend(title='Interaction', loc='upper right', frameon=True)
    ax1.grid(True, alpha=0.3, axis='y')
    ax1.axhline(y=0, color='black', linestyle='-', linewidth=0.5)

    # Plot 2: P-values (right)
    plt.sca(ax2)
    from utils.utils import cauchy_combination

    # Extract p-values from 'pvals' layer
    pvals_data = lrdata.layers['pvals']
    if issparse(pvals_data):
        pvals_data = pvals_data.toarray()

    # Debug: Check pvals data statistics
    print(f"\n   [DEBUG] pvals layer shape: {pvals_data.shape}")
    print(f"   [DEBUG] pvals non-NaN count: {np.sum(~np.isnan(pvals_data))}")
    print(f"   [DEBUG] pvals range: min={np.nanmin(pvals_data):.6f}, max={np.nanmax(pvals_data):.6f}")
    print(f"   [DEBUG] pvals == 0 count: {np.sum(pvals_data == 0)}")
    print(f"   [DEBUG] pvals in (0,1] count: {np.sum((pvals_data > 0) & (pvals_data <= 1))}")

    combined_results = []
    for interaction in sel_interactions:
        if interaction in lrdata.var.index:
            idx = lrdata.var.index.get_loc(interaction)
            interaction_pvals = pvals_data[:, idx]
            if hasattr(interaction_pvals, 'A1'):
                interaction_pvals = interaction_pvals.A1
            elif hasattr(interaction_pvals, 'flatten'):
                interaction_pvals = interaction_pvals.flatten()

            # Debug: Check interaction-specific pvals
            valid_count = np.sum((interaction_pvals > 0) & (interaction_pvals <= 1) & ~np.isnan(interaction_pvals))
            print(f"   [DEBUG] {interaction}: valid pvals count = {valid_count}")

            for celltype in unique_celltypes:
                celltype_mask = celltype_values == celltype
                celltype_pvals = interaction_pvals[celltype_mask]

                # Include p-values of 0 as well (very significant)
                valid_pvals = []
                for pval in celltype_pvals:
                    if pd.notna(pval) and 0 <= pval <= 1:  # Changed: 0 <= instead of 0 <
                        valid_pvals.append(pval)
                
                if valid_pvals:
                    try:
                        combined_pval = cauchy_combination(valid_pvals)
                        neg_log10_pval = -np.log10(combined_pval) if combined_pval > 0 else 10
                        combined_results.append({
                            cluster_key: celltype,
                            'interaction': interaction,
                            'neg_log10_pval': neg_log10_pval,
                            'pval': combined_pval,
                            'n_cells': len(valid_pvals)
                        })
                    except:
                        combined_results.append({
                            cluster_key: celltype,
                            'interaction': interaction,
                            'neg_log10_pval': 0,
                            'pval': 1.0,
                            'n_cells': 0
                        })
                else:
                    combined_results.append({
                        cluster_key: celltype,
                        'interaction': interaction,
                        'neg_log10_pval': 0,
                        'pval': 1.0,
                        'n_cells': 0
                    })

    results_df = pd.DataFrame(combined_results)
    pivot_df = results_df.pivot(index=cluster_key, columns='interaction', values='neg_log10_pval')

    # Create color mapping for interactions to ensure consistency
    interaction_colors = {interaction: colors[i % len(colors)] for i, interaction in enumerate(sel_interactions)}

    # Plot p-values with consistent colors
    x_pval = np.arange(len(pivot_df.index))
    width_pval = 0.35 if len(sel_interactions) == 2 else 0.8 / len(sel_interactions)

    for i, interaction in enumerate(sel_interactions):
        if interaction in pivot_df.columns:
            offset = width_pval * (i - len(sel_interactions)/2 + 0.5)
            ax2.bar(x_pval + offset, pivot_df[interaction].values, width_pval,
                    label=interaction, color=interaction_colors[interaction], alpha=0.8,
                    edgecolor='black', linewidth=0.8)

    # ax2.set_xlabel(cluster_key, fontsize=12)
    ax2.set_ylabel('-log10(Cauchy Combined P-value)', fontsize=12)
    ax2.set_title(f'Cauchy-Combined P-values by {cluster_key} and Interaction', fontsize=14, fontweight='bold')
    ax2.set_xticks(x_pval)
    ax2.set_xticklabels(pivot_df.index, rotation=45, ha='right')
    ax2.axhline(y=-np.log10(p_th), color='red', linestyle='--', alpha=1, label=f'p={p_th}')
    ax2.grid(True, alpha=0.3, axis='y')
    ax2.legend(title='Interaction', loc='upper right', frameon=True)

    # Overall title
    fig.suptitle('Mean Expression and Statistical Significance', fontsize=16, fontweight='bold', y=1.02)

    # Adjust layout
    plt.tight_layout()

    # Save combined figure
    plt.savefig(f'{save_path}/11.lr_interections{filename_suffix}.png', dpi=300, bbox_inches='tight')
    plt.show()

    print(f"Combined figure saved to: {save_path}/11.lr_interections{filename_suffix}.png")
    

def plot_interaction(
    lrdata,
    sel_interactions: List[str],
    cluster_key: str = 'celltype_niche',
    p_th: float = 0.05,
    figsize: Tuple[int, int] = (14, 6),
    save_path: Optional[str] = None,
    filename_suffix: str = ''
) -> plt.Figure:

    # Combined plot - both interaction means and p-values in one figure
    import matplotlib.pyplot as plt
    from utils.plot_cci_analysis import plot_interaction_means, plot_interaction_pvals

    # Create figure with two subplots side by side
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize)

    # Plot 1: Interaction means (left)
    plt.sca(ax1)
    from utils.plot_cci_analysis import plot_interaction_means
    from scipy.sparse import issparse
    import numpy as np
    import pandas as pd

    # Extract data from 'cats' layer
    layer_data = lrdata.layers['cats']
    if issparse(layer_data):
        layer_data = layer_data.toarray()

    celltype_values = lrdata.obs[cluster_key].astype(str).values
    unique_celltypes = sorted(np.unique(celltype_values))

    # Prepare data for means plot
    plot_data_means = []
    for interaction in sel_interactions:
        if interaction in lrdata.var.index:
            idx = lrdata.var.index.get_loc(interaction)
            interaction_values = layer_data[:, idx]
            if hasattr(interaction_values, 'flatten'):
                interaction_values = interaction_values.flatten()
            
            for celltype in unique_celltypes:
                celltype_mask = celltype_values == celltype
                celltype_vals = interaction_values[celltype_mask]
                mean_value = np.nanmean(celltype_vals) if len(celltype_vals) > 0 else np.nan
                plot_data_means.append({
                    'celltype': celltype,
                    'interaction': interaction,
                    'mean': mean_value
                })

    plot_df_means = pd.DataFrame(plot_data_means)

    # Define consistent color palette
    colors = ['#5A9F8C', '#EC8B67', '#6B8FD4', '#D4A76A', '#8D6B94']

    # Plot bars for means
    x = np.arange(len(unique_celltypes))
    width = 0.35 if len(sel_interactions) == 2 else 0.8 / len(sel_interactions)

    for i, interaction in enumerate(sel_interactions):
        df_int = plot_df_means[plot_df_means['interaction'] == interaction].sort_values('celltype')
        offset = width * (i - len(sel_interactions)/2 + 0.5)
        bars = ax1.bar(x + offset, df_int['mean'].values, width, 
                    label=interaction, color=colors[i % len(colors)], alpha=0.8,
                    edgecolor='black', linewidth=0.8)

    # ax1.set_xlabel(cluster_key, fontsize=12)
    ax1.set_ylabel('Mean Expression Value', fontsize=12)
    ax1.set_title(f'Ligand-Receptor Interactions by {cluster_key} (Mean)', fontsize=14, fontweight='bold')
    ax1.set_xticks(x)
    ax1.set_xticklabels(unique_celltypes, rotation=45, ha='right')
    ax1.legend(title='Interaction', loc='upper right', frameon=True)
    ax1.grid(True, alpha=0.3, axis='y')
    ax1.axhline(y=0, color='black', linestyle='-', linewidth=0.5)

    # Plot 2: P-values (right)
    plt.sca(ax2)
    from utils.utils import cauchy_combination

    # Extract p-values from 'pvals' layer
    pvals_data = lrdata.layers['pvals']
    if issparse(pvals_data):
        pvals_data = pvals_data.toarray()

    # Debug: Check pvals data statistics
    print(f"\n   [DEBUG] pvals layer shape: {pvals_data.shape}")
    print(f"   [DEBUG] pvals non-NaN count: {np.sum(~np.isnan(pvals_data))}")
    print(f"   [DEBUG] pvals range: min={np.nanmin(pvals_data):.6f}, max={np.nanmax(pvals_data):.6f}")
    print(f"   [DEBUG] pvals == 0 count: {np.sum(pvals_data == 0)}")
    print(f"   [DEBUG] pvals in (0,1] count: {np.sum((pvals_data > 0) & (pvals_data <= 1))}")

    combined_results = []
    for interaction in sel_interactions:
        if interaction in lrdata.var.index:
            idx = lrdata.var.index.get_loc(interaction)
            interaction_pvals = pvals_data[:, idx]
            if hasattr(interaction_pvals, 'A1'):
                interaction_pvals = interaction_pvals.A1
            elif hasattr(interaction_pvals, 'flatten'):
                interaction_pvals = interaction_pvals.flatten()

            # Debug: Check interaction-specific pvals
            valid_count = np.sum((interaction_pvals > 0) & (interaction_pvals <= 1) & ~np.isnan(interaction_pvals))
            print(f"   [DEBUG] {interaction}: valid pvals count = {valid_count}")

            for celltype in unique_celltypes:
                celltype_mask = celltype_values == celltype
                celltype_pvals = interaction_pvals[celltype_mask]

                # Filter valid p-values in range (0, 1)
                # Note: p=0 and p=1 are handled by cauchy_combination via epsilon replacement
                valid_pvals = []
                for pval in celltype_pvals:
                    if pd.notna(pval) and 0 <= pval <= 1:
                        valid_pvals.append(pval)
                
                if valid_pvals:
                    try:
                        combined_pval = cauchy_combination(valid_pvals)
                        neg_log10_pval = -np.log10(combined_pval) if combined_pval > 0 else 10
                        combined_results.append({
                            cluster_key: celltype,
                            'interaction': interaction,
                            'neg_log10_pval': neg_log10_pval,
                            'pval': combined_pval,
                            'n_cells': len(valid_pvals)
                        })
                    except:
                        combined_results.append({
                            cluster_key: celltype,
                            'interaction': interaction,
                            'neg_log10_pval': 0,
                            'pval': 1.0,
                            'n_cells': 0
                        })
                else:
                    combined_results.append({
                        cluster_key: celltype,
                        'interaction': interaction,
                        'neg_log10_pval': 0,
                        'pval': 1.0,
                        'n_cells': 0
                    })

    results_df = pd.DataFrame(combined_results)
    pivot_df = results_df.pivot(index=cluster_key, columns='interaction', values='neg_log10_pval')

    # Create color mapping for interactions to ensure consistency
    interaction_colors = {interaction: colors[i % len(colors)] for i, interaction in enumerate(sel_interactions)}

    # Plot p-values with consistent colors
    x_pval = np.arange(len(pivot_df.index))
    width_pval = 0.35 if len(sel_interactions) == 2 else 0.8 / len(sel_interactions)

    for i, interaction in enumerate(sel_interactions):
        if interaction in pivot_df.columns:
            offset = width_pval * (i - len(sel_interactions)/2 + 0.5)
            ax2.bar(x_pval + offset, pivot_df[interaction].values, width_pval,
                    label=interaction, color=interaction_colors[interaction], alpha=0.8,
                    edgecolor='black', linewidth=0.8)

    # ax2.set_xlabel(cluster_key, fontsize=12)
    ax2.set_ylabel('-log10(Cauchy Combined P-value)', fontsize=12)
    ax2.set_title(f'Cauchy-Combined P-values by {cluster_key} and Interaction', fontsize=14, fontweight='bold')
    ax2.set_xticks(x_pval)
    ax2.set_xticklabels(pivot_df.index, rotation=45, ha='right')
    ax2.axhline(y=-np.log10(p_th), color='red', linestyle='--', alpha=1, label=f'p={p_th}')
    ax2.grid(True, alpha=0.3, axis='y')
    ax2.legend(title='Interaction', loc='upper right', frameon=True)

    # Overall title
    fig.suptitle('Mean Expression and Statistical Significance', fontsize=16, fontweight='bold', y=1.02)

    # Adjust layout
    plt.tight_layout()

    # Save combined figure
    plt.savefig(f'{save_path}/11.lr_interections{filename_suffix}.png', dpi=300, bbox_inches='tight')
    plt.show()

    print(f"Combined figure saved to: {save_path}/11.lr_interections{filename_suffix}.png")


    

def plot_interaction_means(
    lrdata,
    interactions: List[str],
    celltype_column: str = 'celltype_niche',
    layer_name: str = 'cats',
    figsize: Tuple[int, int] = (12, 6),
    save_path: Optional[str] = None
) -> plt.Figure:
    """
    Plot mean expression values for specific interactions across all clusters.
    Directly uses lrdata.layers['cats'] to calculate means for each cluster.
    
    Parameters
    ----------
    lrdata : sc.AnnData
        AnnData object containing interaction data in layers
    interactions : List[str]
        List of interaction names to plot (e.g., ['MFGE8^ITGAV', 'S100A1^RYR2'])
    celltype_column : str
        Column name in lrdata.obs containing celltype/cluster information
    layer_name : str
        Name of the layer containing expression values (default: 'cats')
    figsize : Tuple[int, int]
        Figure size (width, height)
    save_path : Optional[str]
        Path to save the figure
    
    Returns
    -------
    plt.Figure
        The matplotlib figure object
    """
    from scipy.sparse import issparse
    
    # Extract data from specified layer
    layer_data = lrdata.layers[layer_name]
    
    # Convert sparse matrix to dense if needed
    if issparse(layer_data):
        layer_data = layer_data.toarray()
    
    # Get celltype information
    celltype_values = lrdata.obs[celltype_column].astype(str).values
    unique_celltypes = np.unique(celltype_values)
    
    # Sort celltypes for consistent ordering
    unique_celltypes = sorted(unique_celltypes)
    
    # Prepare data for plotting
    plot_data = []
    
    for interaction in interactions:
        # Find the index of this interaction in lrdata.var
        if interaction in lrdata.var.index:
            idx = lrdata.var.index.get_loc(interaction)
            
            # Extract values for this interaction
            interaction_values = layer_data[:, idx]
            if hasattr(interaction_values, 'flatten'):
                interaction_values = interaction_values.flatten()
            
            # Calculate mean for each celltype
            for celltype in unique_celltypes:
                # Get indices of cells belonging to this celltype
                celltype_mask = celltype_values == celltype
                celltype_vals = interaction_values[celltype_mask]
                
                # Calculate mean (handling NaN values)
                if len(celltype_vals) > 0:
                    mean_value = np.nanmean(celltype_vals)
                else:
                    mean_value = np.nan
                
                plot_data.append({
                    'celltype': celltype,
                    'interaction': interaction,
                    'mean': mean_value
                })
        else:
            print(f"Warning: Interaction '{interaction}' not found in lrdata.var.index")
            # Add NaN values for missing interaction
            for celltype in unique_celltypes:
                plot_data.append({
                    'celltype': celltype,
                    'interaction': interaction,
                    'mean': np.nan
                })
    
    if not plot_data:
        print(f"Error: No valid interactions found")
        print(f"Available interactions (first 10): {lrdata.var.index[:10].tolist()}")
        return None
    
    plot_df = pd.DataFrame(plot_data)
    
    # Create figure
    fig, ax = plt.subplots(figsize=figsize)
    
    # Set up the grouped bar plot
    x = np.arange(len(unique_celltypes))
    width = 0.35 if len(interactions) == 2 else 0.8 / len(interactions)
    
    # Define colors for each interaction
    colors = ['#5A9F8C', '#EC8B67', '#6B8FD4', '#D4A76A', '#8D6B94']  # Extended color palette
    
    # Plot bars for each interaction
    for i, interaction in enumerate(interactions):
        df_int = plot_df[plot_df['interaction'] == interaction]
        # Sort by celltype to ensure consistent ordering
        df_int = df_int.sort_values('celltype')
        
        # Calculate offset for grouped bars
        offset = width * (i - len(interactions)/2 + 0.5)
        
        # Plot bars
        bars = ax.bar(x + offset, df_int['mean'].values, width, 
                      label=interaction, color=colors[i % len(colors)], alpha=0.8)
        
        # Add value labels on top of bars
        for bar in bars:
            height = bar.get_height()
            if not np.isnan(height) and height != 0:  # Only show label if there's a valid value
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{height:.2f}' if abs(height) >= 0.01 else f'{height:.3f}',
                       ha='center', va='bottom' if height > 0 else 'top',
                       fontsize=9)
    
    # Customize plot
    ax.set_xlabel('Cell Type Niche', fontsize=12)
    ax.set_ylabel('Mean Expression Value', fontsize=12)
    ax.set_title('Ligand-Receptor Interactions by Cell Type Niche (Mean)', 
                fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(unique_celltypes, rotation=45, ha='right')
    ax.legend(title='Interaction', loc='upper right', frameon=True)
    ax.grid(True, alpha=0.3, axis='y')
    ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
    
    # Adjust y-axis limits to show all data clearly
    y_min, y_max = ax.get_ylim()
    y_range = y_max - y_min
    ax.set_ylim(y_min - 0.1 * y_range, y_max + 0.1 * y_range)
    
    # Adjust layout
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"Figure saved to: {save_path}")
    
    return fig


def plot_interaction_pvals(
    lrdata,
    interactions: List[str],
    celltype_column: str = 'celltype_niche',
    layer_name: str = 'pvals',
    figsize: Tuple[int, int] = (12, 7),
    save_path: Optional[str] = None
) -> plt.Figure:
    """
    Plot Cauchy-combined p-values for specific interactions across all clusters.
    Directly uses lrdata.layers['pvals'] to calculate combined p-values for each cluster.
    
    Parameters
    ----------
    lrdata : sc.AnnData
        AnnData object containing interaction data in layers
    interactions : List[str]
        List of interaction names to plot (e.g., ['TIMP1^CD63', 'VTN^ITGAV_ITGB5'])
    celltype_column : str
        Column name in lrdata.obs containing celltype/cluster information
    layer_name : str
        Name of the layer containing p-values (default: 'pvals')
    figsize : Tuple[int, int]
        Figure size (width, height)
    save_path : Optional[str]
        Path to save the figure
    
    Returns
    -------
    plt.Figure
        The matplotlib figure object
    """
    from scipy.sparse import issparse
    from .utils import cauchy_combination
    
    # Extract p-values from specified layer
    pvals_data = lrdata.layers[layer_name]
    
    # Convert sparse matrix to dense if needed
    if issparse(pvals_data):
        pvals_data = pvals_data.toarray()
    
    # Get celltype information
    celltype_values = lrdata.obs[celltype_column].astype(str).values
    unique_celltypes = np.unique(celltype_values)
    
    # Sort celltypes for consistent ordering
    unique_celltypes = sorted(unique_celltypes)
    
    # Store combined results
    combined_results = []
    
    for interaction in interactions:
        # Find the index of this interaction in lrdata.var
        if interaction in lrdata.var.index:
            idx = lrdata.var.index.get_loc(interaction)
            
            # Extract p-values for this interaction
            interaction_pvals = pvals_data[:, idx]
            if hasattr(interaction_pvals, 'A1'):  # If it's still a sparse matrix
                interaction_pvals = interaction_pvals.A1
            elif hasattr(interaction_pvals, 'flatten'):
                interaction_pvals = interaction_pvals.flatten()
            
            # For each celltype, combine p-values using Cauchy
            for celltype in unique_celltypes:
                # Get indices of cells belonging to this celltype
                celltype_mask = celltype_values == celltype
                celltype_pvals = interaction_pvals[celltype_mask]
                
                # Filter valid p-values in range [0, 1]
                # Note: p=0 and p=1 are handled by cauchy_combination via epsilon replacement
                valid_pvals = []
                for pval in celltype_pvals:
                    if pd.notna(pval) and 0 <= pval <= 1:
                        valid_pvals.append(pval)
                
                # Apply Cauchy combination if we have valid p-values
                if valid_pvals:
                    try:
                        combined_pval = cauchy_combination(valid_pvals)
                        # Apply -log10 transformation
                        if combined_pval > 0:
                            neg_log10_pval = -np.log10(combined_pval)
                        else:
                            # Handle p-value of 0 (set to a large value)
                            neg_log10_pval = 10  # or np.inf
                        
                        combined_results.append({
                            'celltype_niche': celltype,
                            'interaction': interaction,
                            'neg_log10_pval': neg_log10_pval,
                            'pval': combined_pval,
                            'n_cells': len(valid_pvals)
                        })
                    except Exception as e:
                        print(f"Error combining p-values for {celltype}, {interaction}: {e}")
                else:
                    # No valid p-values for this combination
                    combined_results.append({
                        'celltype_niche': celltype,
                        'interaction': interaction,
                        'neg_log10_pval': 0,
                        'pval': 1.0,
                        'n_cells': 0
                    })
        else:
            print(f"Warning: Interaction '{interaction}' not found in lrdata.var.index")
            # Add default values for missing interaction
            for celltype in unique_celltypes:
                combined_results.append({
                    'celltype_niche': celltype,
                    'interaction': interaction,
                    'neg_log10_pval': 0,
                    'pval': 1.0,
                    'n_cells': 0
                })
    
    # Create DataFrame
    results_df = pd.DataFrame(combined_results)
    
    if results_df.empty:
        print(f"Error: No valid data to plot")
        return None
    
    # Create the barplot
    fig, ax = plt.subplots(figsize=figsize)
    
    # Create pivot table for plotting
    pivot_df = results_df.pivot(index='celltype_niche', columns='interaction', values='neg_log10_pval')
    
    # Define colors for each interaction
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']  # Extended color palette
    
    # Create grouped barplot
    pivot_df.plot(kind='bar', ax=ax, color=colors[:len(interactions)], width=0.7)
    
    # Customize the plot
    ax.set_xlabel('Cell Type Niche', fontsize=12)
    ax.set_ylabel('-log10(Cauchy Combined P-value)', fontsize=12)
    ax.set_title('Cauchy-Combined P-values by Cell Type Niche and Interaction', 
                fontsize=14, fontweight='bold')
    
    # Rotate x-axis labels for better readability
    plt.xticks(rotation=45, ha='right')
    
    # Add horizontal line at -log10(0.05) for significance threshold
    ax.axhline(y=-np.log10(0.05), color='red', linestyle='--', alpha=0.5, label='p=0.05')
    
    # Add grid for better readability
    ax.grid(True, alpha=0.3, axis='y')
    
    # Move legend to best position
    ax.legend(title='Interaction', bbox_to_anchor=(1.05, 1), loc='upper left')
    
    # Adjust layout to prevent label cutoff
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"Figure saved to: {save_path}")
    
    # Print summary statistics
    print("\nCauchy-Combined P-values Summary:")
    print("="*70)
    print("\n-log10(Combined P-value) by Cell Type Niche and Interaction:")
    print(pivot_df.round(3))
    
    print("\nNumber of cells used for combination:")
    pivot_n = results_df.pivot(index='celltype_niche', columns='interaction', values='n_cells')
    print(pivot_n)
    
    # Print which combinations are significant (p < 0.05)
    print("\nSignificant combinations (p < 0.05, i.e., -log10(p) > 1.3):")
    print("="*70)
    significant = results_df[results_df['neg_log10_pval'] > -np.log10(0.05)]
    if not significant.empty:
        for _, row in significant.iterrows():
            print(f"{row['celltype_niche']} - {row['interaction']}: -log10(p) = {row['neg_log10_pval']:.3f}")
    else:
        print("No significant combinations found")
    
    return fig


def plot_interaction_heatmap(
    df: pd.DataFrame,
    interactions: List[str],
    value_column: str = 'source_mean',
    figsize: Tuple[int, int] = (10, 8),
    cmap: str = 'viridis',
    save_path: Optional[str] = None
) -> plt.Figure:
    """
    Plot heatmap of interaction values across cell type pairs.
    
    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with CCI results
    interactions : List[str]
        List of interaction names to include
    value_column : str
        Column to use for heatmap values ('source_mean', 'target_mean', 
        'source_combined_pval', 'target_combined_pval', etc.)
    figsize : Tuple[int, int]
        Figure size
    cmap : str
        Colormap name
    save_path : Optional[str]
        Path to save the figure
    
    Returns
    -------
    plt.Figure
        The matplotlib figure object
    """
    # Filter for specified interactions
    df_filtered = df[df['liana_interaction'].isin(interactions)].copy()
    
    if df_filtered.empty:
        print(f"Warning: No data found for interactions: {interactions}")
        return None
    
    # Create cell type pair column
    df_filtered['celltype_pair'] = df_filtered['source'] + ' → ' + df_filtered['target']
    
    # Pivot for heatmap
    pivot_df = df_filtered.pivot(
        index='celltype_pair',
        columns='liana_interaction',
        values=value_column
    )
    
    # Create figure
    fig, ax = plt.subplots(figsize=figsize)
    
    # Determine if we're plotting p-values (reverse colormap if so)
    if 'pval' in value_column:
        # For p-values, use reversed colormap (low values are significant)
        cmap = cmap + '_r' if not cmap.endswith('_r') else cmap[:-2]
        fmt = '.3f'
    else:
        fmt = '.2f'
    
    # Create heatmap
    sns.heatmap(pivot_df, annot=True, fmt=fmt, cmap=cmap, 
                cbar_kws={'label': value_column.replace('_', ' ').title()},
                ax=ax, linewidths=0.5, linecolor='gray')
    
    ax.set_title(f'Interaction Heatmap: {value_column.replace("_", " ").title()}', 
                fontsize=14, fontweight='bold')
    ax.set_xlabel('Interaction', fontsize=12)
    ax.set_ylabel('Cell Type Pair', fontsize=12)
    
    # Rotate labels for better readability
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    plt.setp(ax.get_yticklabels(), rotation=0)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"Figure saved to: {save_path}")
    
    return fig


def plot_mean_vs_significance(
    df: pd.DataFrame,
    interactions: Optional[List[str]] = None,
    figsize: Tuple[int, int] = (12, 10),
    save_path: Optional[str] = None
) -> plt.Figure:
    """
    Plot relationship between mean expression and statistical significance.
    
    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with mean and p-value columns
    interactions : Optional[List[str]]
        List of specific interactions to highlight (if None, plot all)
    figsize : Tuple[int, int]
        Figure size
    save_path : Optional[str]
        Path to save the figure
    
    Returns
    -------
    plt.Figure
        The matplotlib figure object
    """
    # Check required columns
    required_cols = ['source_mean', 'target_mean', 'neg_log10_source_pval', 'neg_log10_target_pval']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        print(f"Error: Missing required columns: {missing_cols}")
        return None
    
    fig, axes = plt.subplots(2, 2, figsize=figsize)
    
    # Prepare data
    if interactions:
        df_highlight = df[df['liana_interaction'].isin(interactions)].copy()
        df_other = df[~df['liana_interaction'].isin(interactions)].copy()
    else:
        df_highlight = pd.DataFrame()  # Empty
        df_other = df.copy()
    
    # 1. Source mean vs -log10(p-value)
    ax1 = axes[0, 0]
    ax1.scatter(df_other['source_mean'], df_other['neg_log10_source_pval'],
               alpha=0.3, s=10, c='gray', label='Other')
    if not df_highlight.empty:
        for interaction in interactions:
            df_int = df_highlight[df_highlight['liana_interaction'] == interaction]
            ax1.scatter(df_int['source_mean'], df_int['neg_log10_source_pval'],
                       s=50, label=interaction, alpha=0.8)
    
    ax1.axhline(y=-np.log10(0.05), color='red', linestyle='--', alpha=0.5, linewidth=1)
    ax1.text(ax1.get_xlim()[1]*0.95, -np.log10(0.05)+0.1, 'p=0.05', ha='right', fontsize=8)
    ax1.set_xlabel('Source Mean Expression')
    ax1.set_ylabel('-log10(Source P-value)')
    ax1.set_title('Source: Expression vs Significance')
    ax1.grid(True, alpha=0.3)
    if not df_highlight.empty:
        ax1.legend(fontsize=8)
    
    # 2. Target mean vs -log10(p-value)
    ax2 = axes[0, 1]
    ax2.scatter(df_other['target_mean'], df_other['neg_log10_target_pval'],
               alpha=0.3, s=10, c='gray', label='Other')
    if not df_highlight.empty:
        for interaction in interactions:
            df_int = df_highlight[df_highlight['liana_interaction'] == interaction]
            ax2.scatter(df_int['target_mean'], df_int['neg_log10_target_pval'],
                       s=50, label=interaction, alpha=0.8)
    
    ax2.axhline(y=-np.log10(0.05), color='red', linestyle='--', alpha=0.5, linewidth=1)
    ax2.text(ax2.get_xlim()[1]*0.95, -np.log10(0.05)+0.1, 'p=0.05', ha='right', fontsize=8)
    ax2.set_xlabel('Target Mean Expression')
    ax2.set_ylabel('-log10(Target P-value)')
    ax2.set_title('Target: Expression vs Significance')
    ax2.grid(True, alpha=0.3)
    if not df_highlight.empty:
        ax2.legend(fontsize=8)
    
    # 3. Source vs Target means
    ax3 = axes[1, 0]
    ax3.scatter(df_other['source_mean'], df_other['target_mean'],
               alpha=0.3, s=10, c='gray', label='Other')
    if not df_highlight.empty:
        for interaction in interactions:
            df_int = df_highlight[df_highlight['liana_interaction'] == interaction]
            ax3.scatter(df_int['source_mean'], df_int['target_mean'],
                       s=50, label=interaction, alpha=0.8)
    
    # Add diagonal line
    max_mean = max(df['source_mean'].max(), df['target_mean'].max())
    ax3.plot([0, max_mean], [0, max_mean], 'r--', alpha=0.3, linewidth=1)
    ax3.set_xlabel('Source Mean Expression')
    ax3.set_ylabel('Target Mean Expression')
    ax3.set_title('Source vs Target Mean Expression')
    ax3.grid(True, alpha=0.3)
    if not df_highlight.empty:
        ax3.legend(fontsize=8)
    
    # 4. Source vs Target p-values
    ax4 = axes[1, 1]
    ax4.scatter(df_other['neg_log10_source_pval'], df_other['neg_log10_target_pval'],
               alpha=0.3, s=10, c='gray', label='Other')
    if not df_highlight.empty:
        for interaction in interactions:
            df_int = df_highlight[df_highlight['liana_interaction'] == interaction]
            ax4.scatter(df_int['neg_log10_source_pval'], df_int['neg_log10_target_pval'],
                       s=50, label=interaction, alpha=0.8)
    
    # Add diagonal and significance lines
    max_pval = max(df['neg_log10_source_pval'].max(), df['neg_log10_target_pval'].max())
    ax4.plot([0, max_pval], [0, max_pval], 'r--', alpha=0.3, linewidth=1)
    ax4.axhline(y=-np.log10(0.05), color='gray', linestyle='--', alpha=0.3, linewidth=1)
    ax4.axvline(x=-np.log10(0.05), color='gray', linestyle='--', alpha=0.3, linewidth=1)
    ax4.set_xlabel('-log10(Source P-value)')
    ax4.set_ylabel('-log10(Target P-value)')
    ax4.set_title('Source vs Target Significance')
    ax4.grid(True, alpha=0.3)
    if not df_highlight.empty:
        ax4.legend(fontsize=8)
    
    plt.suptitle('Mean Expression and Statistical Significance Analysis', 
                fontsize=14, fontweight='bold')
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"Figure saved to: {save_path}")
    
    return fig


def plot_celltype_pair_summary(
    df: pd.DataFrame,
    top_n: int = 10,
    figsize: Tuple[int, int] = (14, 6),
    save_path: Optional[str] = None
) -> plt.Figure:
    """
    Plot summary statistics for cell type pairs.
    
    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with CCI results
    top_n : int
        Number of top cell type pairs to show
    figsize : Tuple[int, int]
        Figure size
    save_path : Optional[str]
        Path to save the figure
    
    Returns
    -------
    plt.Figure
        The matplotlib figure object
    """
    # Calculate summary statistics per cell type pair
    summary = df.groupby(['source', 'target']).agg({
        'liana_interaction': 'count',
        'source_mean': 'mean',
        'target_mean': 'mean'
    }).reset_index()
    
    summary.columns = ['source', 'target', 'n_interactions', 'avg_source_mean', 'avg_target_mean']
    summary['celltype_pair'] = summary['source'] + ' → ' + summary['target']
    
    # Add significance counts if p-values are available
    if 'source_combined_pval' in df.columns:
        sig_counts = df[df['source_combined_pval'] < 0.05].groupby(['source', 'target']).size()
        summary['n_sig_source'] = summary.apply(
            lambda x: sig_counts.get((x['source'], x['target']), 0), axis=1
        )
    
    if 'target_combined_pval' in df.columns:
        sig_counts = df[df['target_combined_pval'] < 0.05].groupby(['source', 'target']).size()
        summary['n_sig_target'] = summary.apply(
            lambda x: sig_counts.get((x['source'], x['target']), 0), axis=1
        )
    
    # Sort and get top N
    summary_top = summary.nlargest(top_n, 'n_interactions')
    
    # Create figure
    fig, axes = plt.subplots(1, 2, figsize=figsize)
    
    # 1. Bar plot of interaction counts
    ax1 = axes[0]
    x = np.arange(len(summary_top))
    bars = ax1.bar(x, summary_top['n_interactions'], color='steelblue', alpha=0.7)
    
    # Add significance counts if available
    if 'n_sig_source' in summary_top.columns and 'n_sig_target' in summary_top.columns:
        ax1.bar(x, summary_top['n_sig_source'], color='darkblue', alpha=0.9, label='Significant (Source)')
        ax1.bar(x, summary_top['n_sig_target'], bottom=summary_top['n_sig_source'],
               color='darkred', alpha=0.9, label='Significant (Target)')
        ax1.legend()
    
    ax1.set_xlabel('Cell Type Pair')
    ax1.set_ylabel('Number of Interactions')
    ax1.set_title(f'Top {top_n} Cell Type Pairs by Interaction Count')
    ax1.set_xticks(x)
    ax1.set_xticklabels(summary_top['celltype_pair'], rotation=45, ha='right')
    ax1.grid(True, alpha=0.3, axis='y')
    
    # 2. Scatter plot of mean expressions
    ax2 = axes[1]
    scatter = ax2.scatter(summary_top['avg_source_mean'], summary_top['avg_target_mean'],
                         s=summary_top['n_interactions']*10, alpha=0.6,
                         c=summary_top['n_interactions'], cmap='viridis')
    
    # Add labels for each point
    for idx, row in summary_top.iterrows():
        ax2.annotate(row['celltype_pair'], 
                    (row['avg_source_mean'], row['avg_target_mean']),
                    fontsize=8, alpha=0.7)
    
    # Add diagonal line
    max_val = max(summary_top['avg_source_mean'].max(), summary_top['avg_target_mean'].max())
    ax2.plot([0, max_val], [0, max_val], 'r--', alpha=0.3)
    
    ax2.set_xlabel('Average Source Mean Expression')
    ax2.set_ylabel('Average Target Mean Expression')
    ax2.set_title('Average Expression by Cell Type Pair')
    ax2.grid(True, alpha=0.3)
    
    # Add colorbar
    cbar = plt.colorbar(scatter, ax=ax2)
    cbar.set_label('Number of Interactions', rotation=270, labelpad=15)
    
    plt.suptitle('Cell Type Pair Summary Statistics', fontsize=14, fontweight='bold')
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"Figure saved to: {save_path}")
    
    return fig
import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt


def create_factor_loading_heatmap(
    nmfbulk,
    sample_col: str = 'label',
    group_col: str = None,
    cmap: str = 'Blues',
    figsize: tuple = (5, 5),
    cbar_label: str = 'Average Factor Loading',
    legend_title: str = 'Group\nAnnotations',
    save_path: str = 'res/',
    filename: str = 'factor_loading_heatmap.png'
):
    """
    Create a clustered heatmap for NMF factor loadings with group annotations.

    Generates a publication-ready heatmap showing factor loadings across samples,
    with hierarchical clustering on columns, group annotation colors, and properly
    positioned colorbar and legend that do not overlap.

    Layout Design:
        - Heatmap with dendrogram (top and left clustering)
        - Color annotation bar above heatmap showing group membership
        - Legend positioned at top-right corner (above colorbar)
        - Colorbar positioned on the right side, lower portion
        - Sufficient spacing to prevent overlap with axis labels

    Args:
        nmfbulk: AnnData object from decoupler pseudobulk with NMF factor scores
                 - X: Factor loading matrix (samples x factors)
                 - obs: Sample metadata including group annotations
                 - var: Factor names
        sample_col (str): Column name in nmfbulk.obs for sample labels (default: 'label')
        group_col (str, optional): Column name for group annotations. If None, uses sample_col.
                                   This column defines the color annotation bar.
        cmap (str): Colormap for heatmap values (default: 'Blues')
        figsize (tuple): Figure size in inches (width, height). Default: (5, 5)
                         Recommended to increase width if many samples.
        cbar_label (str): Label for colorbar (default: 'Average Factor Loading')
        legend_title (str): Title for group legend (default: 'Group\\nAnnotations')
        save_path (str): Output directory for saving the figure (default: 'res/')
        filename (str): Output filename (default: 'factor_loading_heatmap.png')

    Returns:
        sns.matrix.ClusterGrid: The seaborn clustermap object for further customization

    Example:
        >>> import decoupler as dc
        >>> nmfbulk = dc.pp.pseudobulk(nmfdata, sample_col='label', groups_col=None, mode='mean')
        >>> create_factor_loading_heatmap(nmfbulk, sample_col='label', group_col='patient_group')

    Notes:
        - The function automatically handles colorbar and legend positioning to prevent overlap
        - Group colors are assigned using seaborn's 'Dark2' palette
        - Factors are displayed on the y-axis, samples on the x-axis
        - Column clustering is enabled by default for sample ordering
    """
    import os

    # Use sample_col as group_col if not specified
    if group_col is None:
        group_col = sample_col

    # Get group annotations and create color mapping
    group_annotations = nmfbulk.obs[group_col].values
    group_labels = list(set(group_annotations))

    # Create color palette
    cmap_palette = sns.color_palette('Dark2', n_colors=len(group_labels))
    group_cmap = dict(zip(group_labels, cmap_palette))
    group_cols = [group_cmap[key] for key in group_labels]

    # Create clustermap without colorbar (we'll add it manually)
    chart = sns.clustermap(
        nmfbulk.X.T,  # Transpose: factors as rows, samples as columns
        cmap=cmap,
        cbar_kws={'orientation': 'vertical'},
        row_cluster=False,  # Don't cluster factors
        col_cluster=True,   # Cluster samples
        col_colors=[group_cmap[x] for x in group_annotations],
        figsize=figsize,
        xticklabels=nmfbulk.obs.index,
        yticklabels=nmfbulk.var.index,
        cbar_pos=None  # Disable default colorbar
    )

    # Customize tick labels
    chart.ax_heatmap.set_yticklabels(
        chart.ax_heatmap.get_ymajorticklabels(),
        rotation=0,
        fontdict={'fontsize': 11}
    )
    chart.ax_heatmap.set_xticklabels(
        chart.ax_heatmap.get_xmajorticklabels(),
        fontsize=8
    )

    # ===== COLORBAR POSITIONING (right side, lower portion) =====
    # Position: [left, bottom, width, height] in figure coordinates
    # Positioned lower to leave space for legend at top-right
    cbar_ax = chart.fig.add_axes([0.92, 0.15, 0.025, 0.4])
    cbar = plt.colorbar(chart.ax_heatmap.get_children()[0], cax=cbar_ax)
    cbar.set_label(cbar_label, size=10, loc='center')
    cbar.ax.tick_params(labelsize=8)

    # ===== LEGEND POSITIONING (top-right, above colorbar) =====
    # Create custom legend handles
    legend_handles = []
    for label, color in zip(group_labels, group_cols):
        legend_handles.append(
            plt.Line2D([0], [0], color=color, marker='o', linestyle='',
                      markersize=8, label=label)
        )

    # Add legend to figure at top-right corner
    legend = chart.fig.legend(
        handles=legend_handles,
        title=legend_title,
        loc='upper right',
        bbox_to_anchor=(1.12, 0.95),  # Top-right, outside heatmap area
        frameon=False,
        fontsize=9
    )
    plt.setp(legend.get_title(), fontsize=10)

    # Adjust figure layout to accommodate colorbar and legend
    plt.subplots_adjust(right=0.75, top=0.85)

    # Save figure
    os.makedirs(save_path, exist_ok=True)
    output_file = f'{save_path}/{filename}'
    chart.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"Factor loading heatmap saved to: {output_file}")

    plt.show()

    return chart


def create_heatmap(res, 
                      fill='estimate', 
                      index_key="factor",
                      column_key='pathway',
                      label='pval',
                      cbar_label=None,
                      max_value=None, 
                      significance_level=0.05,
                      filter_significant=True,
                      figsize=(4, 4),  # Adjusted for better visibility
                      cmap='RdBu_r',
                      move_labels=False,
                      group_annotations=None,  # Dictionary for column colors
                      save_path='res/'
                     ):
    res = res.copy()
    if max_value is not None:
        res.loc[res[fill] > max_value, fill] = max_value
        res.loc[res[fill] < -max_value, fill] = -max_value
    
    res['significant'] = res[label].apply(lambda x: '*' if x < significance_level else '')
    
    if filter_significant:
        sig_paths = res[res[label] <= significance_level][column_key].unique()
    else:
        sig_paths = res[column_key].unique()

    # Filter for significant pathways
    filtered_data = res[res[column_key].isin(sig_paths)]
    
    # Create pivot table for heatmap
    heatmap_data = filtered_data.pivot(index=index_key, columns=column_key, values=fill)
    heatmap_data.sort_index(inplace=True, ascending=False)
    
    # Prepare row colors
    if group_annotations:
        # Get unique labels from the index
        unique_labels = heatmap_data.columns.unique()
        # Map each label to a color
        col_colors = list(pd.Series(unique_labels, index=unique_labels).map(group_annotations).reindex(heatmap_data.columns))
    else:
        col_colors = None

    # Create clustermap
    g = sns.clustermap(heatmap_data,
                       figsize=figsize,
                       cmap=cmap,
                       cbar_kws={'label': cbar_label},
                       row_cluster=False,
                       col_cluster=False,
                       col_colors=col_colors,  # Set row_colors here
                       cbar_pos=(0.9, 0.2, 0.05, 0.6)  # Move colorbar to the right side  
                      )
    
    
    # Adding Text Annotations
    for y, row in enumerate(heatmap_data.index):
        for x, column in enumerate(heatmap_data.columns):
            value = filtered_data.loc[(filtered_data[index_key] == row) &
                                       (filtered_data[column_key] == column), 'significant'].values[0]
            
            g.ax_heatmap.text(x + 0.5, y + 0.6,
                            value,
                            horizontalalignment='center', 
                            verticalalignment='center',
                            color='white',
                            fontstyle='oblique',
                            fontsize=16  # Reduced from 30
                            )
    
    # Move x-labels to the top
    if move_labels:
        g.ax_heatmap.xaxis.tick_top()
        g.ax_heatmap.xaxis.set_label_position('top')
        g.ax_heatmap.tick_params(axis='x', which='both', pad=15, length=0)
        
    plt.setp(g.ax_heatmap.get_xticklabels(), fontsize=10, rotation=90)  # Reduced from 15
    g.ax_heatmap.yaxis.tick_left()
    g.ax_heatmap.yaxis.set_label_position('left')
    plt.setp(g.ax_heatmap.get_yticklabels(), fontsize=10, rotation=0)  # Reduced from 15
    # cbar text smaller
    g.ax_cbar.set_ylabel(cbar_label, fontsize=10, rotation=270, labelpad=10)  # Reduced from 15
    # cbar axis ticks smaller
    g.ax_cbar.yaxis.set_tick_params(labelsize=9)  # Reduced from 15
    
    g.ax_heatmap.set_xlabel('')
    g.ax_heatmap.set_ylabel('')
    
    # plt.figure(figsize=(figsize[0], 0.2))

    # save_path = f'{save_path}/8.pathway_factor_heatmap.png'
    # plt.savefig(save_path, dpi=300, bbox_inches='tight')
    # print(f"Pathway factor heatmap saved to: {save_path}")

    save_file = f'{save_path}/8.pathway_factor_heatmap.png'
    g.savefig(save_file, dpi=300, bbox_inches='tight')
    print(f"Pathway factor heatmap saved to: {save_file}")

    plt.show()
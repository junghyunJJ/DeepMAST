import numpy as np
import scanpy as sc
import pandas as pd

import liana as li
import decoupler as dc

import seaborn as sns
import matplotlib.pyplot as plt
from utils.utils import make_unique_by_interaction


def res_liana_factorscore(lrdata, cluster_key = "cluster"):
  factor_scores = li.ut.get_factor_scores(lrdata, obsm_key='NMF_W')
  factor_scores[cluster_key] = list(lrdata.obs[cluster_key])
  # Preserve cell/spot index for multi-sample subsetting
  factor_scores.index = lrdata.obs.index
  return(factor_scores)


# def plot_factorscore(factor_scores):
#   import pandas as pd
#   import matplotlib.pyplot as plt
#   import numpy as np
#   import seaborn as sns

#   # Get all Factor columns dynamically
#   factor_cols = [col for col in factor_scores.columns if col.startswith('Factor')]
  
#   # celltype_niche별로 모든 Factor columns의 평균값 계산
#   df_grouped = factor_scores.groupby('celltype_niche')[factor_cols].mean()
#   # 정렬 (ctniche 번호순)
#   df_grouped = df_grouped.sort_index(key=lambda x: x.str.extract('(\d+)')[0].astype(int))


#   # Figure 설정
#   fig, ax = plt.subplots(figsize=(12, 6))

#   # Bar plot 생성
#   x = np.arange(len(df_grouped.index))
#   n_factors = len(factor_cols)
#   width = 0.8 / n_factors  # Adjust width based on number of factors

#   # Color palette for factors
#   colors = plt.cm.tab10(np.linspace(0, 0.7, n_factors))
  
#   # 각 Factor에 대한 bar 그리기
#   bars = []
#   for i, factor in enumerate(factor_cols):
#     offset = width * (i - n_factors/2 + 0.5)
#     bar = ax.bar(x + offset, df_grouped[factor], width, 
#                   label=factor, alpha=0.8, color=colors[i])
#     bars.append(bar)

#   # 축 설정
#   # ax.set_xlabel('Celltype Niche', fontsize=12, fontweight='bold')
#   ax.set_ylabel('Factor Values (Mean)', fontsize=12, fontweight='bold')
#   ax.set_title('Factor Distribution across Celltype Niches', fontsize=14, fontweight='bold')
#   ax.set_xticks(x)
#   ax.set_xticklabels(df_grouped.index, rotation=45, ha='right')

#   # 범례 추가
#   ax.legend(frameon=True)

#   # Grid 설정
#   # ax.grid(True, alpha=0.3, linestyle='--')

#   # Y축 범위 조정
#   ax.set_ylim([0, max(df_grouped.max()) * 1.1])

#   plt.tight_layout()
#   # plt.show()
#   return plt


def plot_factorscore(lrdata, cluster_key="cluster", sample_key=None, width=None, height=None, save_path='res/', filename_suffix: str = ''):
    """
    Plot NMF factor scores spatially with multi-sample support.

    For multi-sample data, creates a grid layout:
    - Each row = one sample's spatial plots (factors + cluster)
    - Bottom row = single barplot of factor medians across all samples
    - Single shared colorbar for all factor plots (enables cross-factor/cross-sample comparison)

    Args:
        lrdata: LR data object with NMF results
        cluster_key: Column name for cluster annotations
        sample_key: Column name for sample identifiers. If None, auto-detects from .uns['spatial']
        width: Figure width in inches. If None, auto-calculated based on n_factors
        height: Figure height in inches per sample row. If None, auto-calculated
        save_path: Output directory
        filename_suffix: Suffix for output filename
    """
    import os
    from matplotlib.gridspec import GridSpec
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    # Get factor scores for barplot
    res_factorscore = res_liana_factorscore(lrdata, cluster_key)

    # Create NMF data
    lr_loadings = li.ut.get_variable_loadings(lrdata, varm_key='NMF_H').set_index('index')
    nmf = sc.AnnData(X=lrdata.obsm['NMF_W'],
                    obs=lrdata.obs,
                    var=pd.DataFrame(index=lr_loadings.columns),
                    uns=lrdata.uns,
                    obsm=lrdata.obsm)

    # Get factor columns
    factor_cols = [col for col in res_factorscore.columns if col.startswith('Factor')]
    n_factors = len(factor_cols)
    n_cols = n_factors + 1  # factors + cluster

    # Detect samples
    if sample_key is not None and sample_key in nmf.obs.columns:
        samples = list(nmf.obs[sample_key].unique())
    elif 'spatial' in nmf.uns and len(nmf.uns['spatial']) > 1:
        # Auto-detect from .uns['spatial'] keys (library_ids)
        samples = list(nmf.uns['spatial'].keys())
        # Try to find matching column in obs
        for potential_key in ['library_id', 'sample', 'sample_id', 'batch']:
            if potential_key in nmf.obs.columns:
                sample_key = potential_key
                samples = list(nmf.obs[sample_key].unique())
                break
    else:
        samples = ['all']  # Single sample mode
        sample_key = None

    n_samples = len(samples)
    print(f"   Detected {n_samples} sample(s): {samples}")

    # Get number of clusters for barplot width calculation
    n_clusters = res_factorscore[cluster_key].nunique()

    # Calculate global max y-value across ALL samples for unified y-axis (barplot)
    global_max_val = 0
    for sample in samples:
        if sample_key is not None and sample != 'all':
            mask = nmf.obs[sample_key] == sample
            sample_indices = nmf.obs.index[mask]
            sample_fs = res_factorscore[res_factorscore.index.isin(sample_indices)]
        else:
            sample_fs = res_factorscore
        df_grp = sample_fs.groupby(cluster_key)[factor_cols].median()
        sample_max = df_grp.max().max()
        if not pd.isna(sample_max) and sample_max > global_max_val:
            global_max_val = sample_max
    if global_max_val <= 0:
        global_max_val = 1  # Fallback

    # Calculate global min/max for factor scores (scatter plot colorbar)
    # This enables direct comparison across all factors and samples
    global_factor_min = 0  # NMF scores are non-negative
    global_factor_max = nmf.X.max()
    if pd.isna(global_factor_max) or global_factor_max <= 0:
        global_factor_max = 1  # Fallback
    print(f"   Factor score range: {global_factor_min:.4f} - {global_factor_max:.4f}")

    # Dynamic figure sizing
    # Layout: scatter row + barplot row per sample
    # Width: ~3.5 inches per column (factor + cluster) + extra for shared colorbar
    # Height: ~3.5 inches per scatter row, ~2.2 inches per barplot row (1.2x of 1.8)
    WIDTH_PER_COL = 3.5
    SCATTER_HEIGHT = 3.5
    BARPLOT_HEIGHT = 2.2
    COLORBAR_WIDTH = 0.6  # Extra width for shared colorbar

    fig_width = width if width is not None else max(10, n_cols * WIDTH_PER_COL + COLORBAR_WIDTH)
    scatter_h = height if height is not None else SCATTER_HEIGHT
    fig_height = (scatter_h + BARPLOT_HEIGHT) * n_samples

    print(f"   Figure size: {fig_width:.1f} x {fig_height:.1f} inches ({n_cols} cols × {n_samples} samples, {n_clusters} clusters)")

    fig = plt.figure(figsize=(fig_width, fig_height))

    # Create grid: 2 rows per sample (scatter + barplot) + extra column for shared colorbar
    # Total rows = n_samples * 2
    n_rows = n_samples * 2
    height_ratios = []
    for _ in range(n_samples):
        height_ratios.extend([1, 0.65])  # scatter row : barplot row ratio

    # Add extra column for shared colorbar (wider to avoid overlap with cluster colorbar)
    width_ratios = [1] * n_cols + [0.08]  # Last column for colorbar (increased from 0.03)
    gs = GridSpec(n_rows, n_cols + 1, figure=fig,
                  height_ratios=height_ratios,
                  width_ratios=width_ratios,
                  hspace=0.15, wspace=0.12)  # Increased wspace from 0.05 for colorbar spacing

    # Plot for each sample
    colors_to_plot = list(nmf.var.index) + [cluster_key]
    bar_colors = plt.cm.tab10(np.linspace(0, 0.7, n_factors))

    # Store one scatter plot for creating shared colorbar
    factor_scatter_for_cbar = None

    for sample_idx, sample in enumerate(samples):
        scatter_row = sample_idx * 2      # Row index for scatter plots
        barplot_row = sample_idx * 2 + 1  # Row index for barplot

        # Subset data for this sample
        if sample_key is not None and sample != 'all':
            mask = nmf.obs[sample_key] == sample
            nmf_sample = nmf[mask].copy()
            # Also subset factor scores for barplot
            factor_mask = res_factorscore.index.isin(nmf_sample.obs.index)
            sample_factorscore = res_factorscore[factor_mask]
        else:
            nmf_sample = nmf
            sample_factorscore = res_factorscore

        # ===== SCATTER PLOTS ROW =====
        for col_idx, color_var in enumerate(colors_to_plot):
            ax = fig.add_subplot(gs[scatter_row, col_idx])

            # Get spatial coordinates and flip Y-axis (multiply by -1)
            spatial_coords = nmf_sample.obsm['spatial'].copy()
            spatial_coords[:, 1] = -spatial_coords[:, 1]  # Flip Y-axis

            # Get color values
            if color_var == cluster_key:
                # Categorical coloring for clusters
                categories = nmf_sample.obs[color_var].astype('category')
                cat_codes = categories.cat.codes
                n_cats = len(categories.cat.categories)
                cmap = plt.cm.get_cmap('tab20', n_cats)
                scatter = ax.scatter(spatial_coords[:, 0], spatial_coords[:, 1],
                                    c=cat_codes, cmap=cmap, s=3, alpha=0.8)

                # Add colorbar with category labels (only for cluster plot)
                # Use shrink and pad to avoid overlap with shared Factor Score colorbar
                cbar = plt.colorbar(scatter, ax=ax, shrink=0.9, pad=0.02)
                cbar.set_ticks(np.arange(n_cats))
                cbar.set_ticklabels(categories.cat.categories)
                cbar.ax.tick_params(labelsize=7)
            else:
                # Continuous coloring for factors with SHARED vmin/vmax
                if color_var in nmf_sample.var.index:
                    var_idx = list(nmf_sample.var.index).index(color_var)
                    color_values = nmf_sample.X[:, var_idx]
                else:
                    color_values = np.zeros(nmf_sample.n_obs)

                # Use global min/max for consistent colorbar across all factor plots
                scatter = ax.scatter(spatial_coords[:, 0], spatial_coords[:, 1],
                                    c=color_values, cmap='viridis', s=3, alpha=0.8,
                                    vmin=global_factor_min, vmax=global_factor_max)

                # Store reference for shared colorbar (first factor plot only)
                if factor_scatter_for_cbar is None:
                    factor_scatter_for_cbar = scatter

            # Set title (only for first sample's scatter row)
            if sample_idx == 0:
                ax.set_title(color_var, fontsize=10, fontweight='bold')

            # Set y-label (sample name) for first column
            if col_idx == 0:
                ax.set_ylabel(str(sample), fontsize=9, fontweight='bold')

            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_aspect('equal')

        # ===== BARPLOT ROW (per sample) =====
        # Span center columns for barplot (avoid full width for centering)
        # Use middle 60% of columns
        margin_cols = max(1, n_cols // 4)  # ~25% margin on each side
        start_col = margin_cols
        end_col = n_cols - margin_cols
        if end_col <= start_col:  # Fallback if too few columns
            start_col, end_col = 0, n_cols
        ax_bar = fig.add_subplot(gs[barplot_row, start_col:end_col])

        # Calculate factor medians by cluster for THIS SAMPLE
        df_grouped = sample_factorscore.groupby(cluster_key)[factor_cols].median()

        # Bar plot
        x = np.arange(len(df_grouped.index))
        bar_width = 0.8 / n_factors

        for i, factor in enumerate(factor_cols):
            offset = bar_width * (i - n_factors/2 + 0.5)
            ax_bar.bar(x + offset, df_grouped[factor], bar_width,
                      label=factor, alpha=0.8, color=bar_colors[i])

        ax_bar.set_ylabel(f'{sample}\nMedian', fontsize=9, fontweight='bold')
        ax_bar.set_xticks(x)
        # Horizontal labels (no rotation)
        ax_bar.set_xticklabels(df_grouped.index, rotation=0, ha='center', fontsize=8)
        # Add padding on x-axis for better centering
        ax_bar.set_xlim(-0.8, len(df_grouped.index) - 0.2)
        # Add compact legend to each barplot for clarity
        ax_bar.legend(frameon=True, loc='upper right', fontsize=6, ncol=min(n_factors, 3),
                     handlelength=1.0, handletextpad=0.3, columnspacing=0.5)
        # Use global max for unified y-axis scale across all samples
        ax_bar.set_ylim([0, global_max_val * 1.15])
        ax_bar.grid(True, alpha=0.3, axis='y')
        ax_bar.tick_params(axis='y', labelsize=7)

    # Apply tight_layout first, leaving space on the right for colorbar
    plt.tight_layout(rect=[0, 0, 0.90, 1])  # Leave 10% on right for colorbar

    # ===== SHARED COLORBAR for all factor plots =====
    # Create a compact colorbar positioned in the right margin (after tight_layout)
    if factor_scatter_for_cbar is not None:
        # Create colorbar axes manually for better size control
        # Position: [left, bottom, width, height] in figure coordinates
        # Place it on the right side, vertically centered, with compact height (~30% of figure)
        cbar_height = 0.30  # 30% of figure height
        cbar_bottom = 0.5 - cbar_height / 2  # Center vertically
        cbar_left = 0.92  # Position on right side
        cbar_width = 0.015  # Thin colorbar

        cbar_ax = fig.add_axes([cbar_left, cbar_bottom, cbar_width, cbar_height])
        cbar = fig.colorbar(factor_scatter_for_cbar, cax=cbar_ax)
        cbar.set_label('Factor Score', fontsize=9, fontweight='bold')
        cbar.ax.tick_params(labelsize=7)

    # Save figure
    os.makedirs(save_path, exist_ok=True)
    output_filename = f'{save_path}/7.factor_spatial_NMF{filename_suffix}.png'
    plt.savefig(output_filename, dpi=300, bbox_inches='tight')
    print(f"   Figure saved as '{output_filename}'")

    plt.show()

# Interest clusters와 가장 관련이 높은 Factor 선정
# NOTE!! LMM이 선택 가능할것이라 판단
def sel_factor(res_factorscore, cluster_key, interest_clusters, width=10, height=6, save_path ='res/'):

    # Get all Factor columns dynamically
    factor_cols = [col for col in res_factorscore.columns if col.startswith('Factor')]

    # celltype_niche별로 모든 Factor columns의 평균값 계산
    df_grouped = res_factorscore.groupby(cluster_key)[factor_cols].mean()
    # 정렬 (ctniche 번호순)
    # df_grouped = df_grouped.sort_index(key=lambda x: x.str.extract('(\d+)')[0].astype(int))

    print("=" * 60)
    print(f"Interest Clusters: {interest_clusters}")
    print("=" * 60)

    # 1. Interest clusters에서의 평균값 기준
    print("\n1. Interest Clusters에서의 Factor 평균값")
    print("-" * 40)
    interest_means = df_grouped.loc[interest_clusters]
    print(interest_means)
    print(f"\nInterest clusters 전체 평균:")
    interest_avg = interest_means.mean()
    print(interest_avg)

    # 2. Interest clusters vs Others 비교
    print("\n" + "=" * 60)
    print("2. Interest Clusters vs Others 비교")
    print("-" * 40)
    other_clusters = [c for c in df_grouped.index if c not in interest_clusters]
    other_means = df_grouped.loc[other_clusters].mean()

    comparison_df = pd.DataFrame({
        'Interest_Clusters': interest_avg,
        'Other_Clusters': other_means,
        'Difference': interest_avg - other_means,
        'Fold_Change': interest_avg / other_means
    })
    comparison_df = comparison_df.sort_values('Fold_Change', ascending=False)
    print(comparison_df)

    # 3. Interest clusters 특이성 점수 (Specificity Score)
    print("\n" + "=" * 60)
    print("3. Interest Clusters Specificity Score")
    print("-" * 40)

    # Z-score 기반 특이성
    z_scores = (df_grouped - df_grouped.mean()) / df_grouped.std()
    interest_z_scores = z_scores.loc[interest_clusters].mean()
    specificity_scores = pd.DataFrame({
        'Factor': interest_z_scores.index,
        'Mean_Z_Score': interest_z_scores.values,
        'Mean_Value_Interest': interest_avg.values,
        'Mean_Value_Others': other_means.values,
        'Fold_Change': (interest_avg / other_means).values
    })
    specificity_scores = specificity_scores.sort_values('Mean_Z_Score', ascending=False)
    print(specificity_scores)

    # 4. 최종 선정
    print("\n" + "=" * 60)
    print("4. 최종 Factor 선정")
    print("=" * 60)

    # 종합 점수 계산 (Z-score와 Fold Change를 모두 고려)
    specificity_scores['Combined_Score'] = (
        specificity_scores['Mean_Z_Score'] * 0.5 + 
        (specificity_scores['Fold_Change'] - 1) * 0.5
    )
    specificity_scores = specificity_scores.sort_values('Combined_Score', ascending=False)

    best_factor = specificity_scores.iloc[0]['Factor']
    print(f"\n✅ Interest clusters ({interest_clusters})와 가장 관련이 높은 Factor:")
    print(f"   → {best_factor}")
    print(f"\n상위 3개 Factors:")
    for idx, row in specificity_scores.head(3).iterrows():
        print(f"   {idx+1}. {row['Factor']}: Z-score={row['Mean_Z_Score']:.3f}, Fold Change={row['Fold_Change']:.3f}")

    # 5. 시각화
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 5-1. Bar plot: Interest vs Others
    ax1 = axes[0, 0]
    x = np.arange(len(factor_cols))
    width = 0.35
    bars1 = ax1.bar(x - width/2, interest_avg, width, label='Interest Clusters', alpha=0.8, color='coral')
    bars2 = ax1.bar(x + width/2, other_means, width, label='Other Clusters', alpha=0.8, color='skyblue')
    ax1.set_xlabel('Factors')
    ax1.set_ylabel('Mean Value')
    ax1.set_title('Factor Means: Interest Clusters vs Others', fontweight='bold')
    ax1.set_xticks(x)
    ax1.set_xticklabels(factor_cols)
    ax1.legend()
    ax1.grid(True, alpha=0.3, axis='y')

    # 5-2. Fold Change plot
    ax2 = axes[0, 1]
    fold_changes = specificity_scores.set_index('Factor')['Fold_Change'].sort_values(ascending=True)
    colors = ['coral' if fc > 1.2 else 'gray' for fc in fold_changes]
    bars = ax2.barh(range(len(fold_changes)), fold_changes, color=colors, alpha=0.8)
    ax2.axvline(x=1, color='black', linestyle='--', alpha=0.5, label='No difference')
    ax2.set_yticks(range(len(fold_changes)))
    ax2.set_yticklabels(fold_changes.index)
    ax2.set_xlabel('Fold Change (Interest/Others)')
    ax2.set_title('Factor Enrichment in Interest Clusters', fontweight='bold')
    ax2.legend()
    ax2.grid(True, alpha=0.3, axis='x')

    # 5-3. Z-score plot
    ax3 = axes[1, 0]
    z_score_data = z_scores.loc[interest_clusters].T
    sns.heatmap(z_score_data, annot=True, fmt='.2f', cmap='RdBu_r', center=0, ax=ax3, 
                cbar_kws={'label': 'Z-Score'})
    ax3.set_title('Factor Z-scores in Interest Clusters', fontweight='bold')
    ax3.set_xlabel('Celltype Niche')
    ax3.set_ylabel('Factors')

    # 5-4. Combined score plot
    ax4 = axes[1, 1]
    combined_scores = specificity_scores.set_index('Factor')['Combined_Score'].sort_values(ascending=False)
    colors = ['coral' if i == 0 else 'lightcoral' if i < 3 else 'gray' 
            for i in range(len(combined_scores))]
    bars = ax4.bar(range(len(combined_scores)), combined_scores, color=colors, alpha=0.8)
    ax4.set_xticks(range(len(combined_scores)))
    ax4.set_xticklabels(combined_scores.index, rotation=45, ha='right')
    ax4.set_ylabel('Combined Score')
    ax4.set_title('Final Factor Ranking for Interest Clusters', fontweight='bold')
    ax4.grid(True, alpha=0.3, axis='y')

    # Add arrow to best factor
    best_idx = list(combined_scores.index).index(best_factor)
    ax4.annotate('Best Factor', xy=(best_idx, combined_scores.iloc[best_idx]), 
                xytext=(best_idx, combined_scores.iloc[best_idx] + 0.2),
                arrowprops=dict(arrowstyle='->', color='red', lw=2),
                fontsize=10, fontweight='bold', ha='center', color='red')

    plt.suptitle(f'Factor Analysis for Interest Clusters: {", ".join(interest_clusters)}', 
                fontsize=16, fontweight='bold')
    plt.tight_layout()
    plt.savefig(f'{save_path}/interest_cluster_factor_analysis.png', dpi=300, bbox_inches='tight')
    plt.show()

    print(f"\n분석 결과가 '{save_path}/interest_cluster_factor_analysis.png'에 저장되었습니다.")
    print(f"\n📊 결론: {best_factor}가 {interest_clusters}와 가장 관련이 높은 Factor입니다.")

    return(best_factor)


#########################################################################################################
#########################################################################################################
#########################################################################################################


def _get_sigliana(lrdata, th_morans=0, p_th=0.05):
  sig_liana = lrdata.var.query(f'morans > {th_morans} & morans_pvals < {p_th}')
  sig_liana = sig_liana.reset_index()
  sig_liana = sig_liana.rename(columns={'index': 'interaction'})
  print(f"Significant LR pairs: {sig_liana.shape[0]} / {lrdata.var.shape[0]} ({sig_liana.shape[0] / lrdata.var.shape[0] * 100:.1f}%)")
  return(sig_liana)


def _get_loadings(lrdata):
  lr_loadings = li.ut.get_variable_loadings(lrdata, varm_key='NMF_H').set_index('index')
  lr_loadings = lr_loadings.reset_index() 

  lr_loadings[['ligand', 'receptor']] = lr_loadings['index'].str.split('^', expand=True)
  # Get Factor columns dynamically
  factor_cols = [col for col in lr_loadings.columns if col.startswith('Factor')]
  # Reorder columns: interaction (renamed from index), ligand, then all Factor columns
  lr_loadings = lr_loadings[['index', 'ligand', 'receptor'] + factor_cols]
  # Rename 'index' to 'interaction'
  lr_loadings = lr_loadings.rename(columns={'index': 'interaction'})

  return(lr_loadings)


def _anno_lr_loadings(lr_loadings, interaction_col='interaction', organism='human', geneset='progeny'):

  # annotation with pathway geneset (progeny or hallmark)
  if geneset == 'progeny':
    pathway_db = dc.op.progeny(organism=organism)
    geneset_col_name = 'progeny'
    # progeny has weight column
    lr_pathway = li.rs.generate_lr_geneset(
      lr_loadings,
      pathway_db,
      lr_sep="^")[['source', 'interaction']]
  else:  # hallmark
    pathway_db = dc.op.hallmark(organism=organism)
    geneset_col_name = 'hallmark'
    # hallmark has no weight column, pass weight=None
    lr_pathway = li.rs.generate_lr_geneset(
      lr_loadings,
      pathway_db,
      lr_sep="^",
      weight=None)[['source', 'interaction']]
  lr_pathway_unique = make_unique_by_interaction(lr_pathway)
  lr_pathway_unique = lr_pathway_unique.rename(columns={'interaction': 'interaction', 'source': geneset_col_name})

  import omnipath as op
  diseases = op.requests.Annotations.get(resources = ['DisGeNet'])

  diseases = diseases[['genesymbol', 'label', 'value']]
  diseases = diseases.pivot_table(index='genesymbol',
                                    columns='label', values='value',
                                    aggfunc=lambda x: '; '.join(x)).reset_index()
  diseases = diseases[['genesymbol', 'disease']]
  diseases['disease'] = diseases['disease'].str.split('; ')
  diseases = diseases.explode('disease')

  # annotation disease (DisGeNet - human only)
  # Skip disease annotation for mouse as DisGeNet uses human gene symbols
  if organism != 'human':
    # if non human organism
    map_df = li.rs.get_hcop_orthologs(url=f'https://ftp.ebi.ac.uk/pub/databases/genenames/hcop/human_{organism}_hcop_fifteen_column.txt.gz',
                                    columns=['human_symbol', f'{organism}_symbol'],
                                    # NOTE: HCOP integrates multiple resource, so we can filter out mappings in at least 3 of them for confidence
                                    min_evidence=3
                                    )
    # rename the columns to source and target, respectively for the original organism and the target organism
    map_df = map_df.rename(columns={'human_symbol':'source', f'{organism}_symbol':'target'})
    # We will then translate
    diseases = li.rs.translate_resource(diseases,
                                    map_df=map_df,
                                    columns=['genesymbol'],
                                    replace=True,
                                    # Here, we will be harsher and only keep mappings that don't map to more than 1 mouse gene
                                    one_to_many=1
                                    )
    diseases


  # diseases
  lr_diseases = li.rs.generate_lr_geneset(
    lr_loadings,
    diseases,
    source='disease',
    target='genesymbol',
    weight=None)
  lr_diseases = lr_diseases.drop_duplicates().sort_values("interaction")
  lr_diseases_unique = make_unique_by_interaction(lr_diseases, interaction_col='interaction', source_col='disease')


  # merge1 - pathway geneset annotation
  anno = pd.merge(
    lr_loadings,
    lr_pathway_unique,
    left_on=interaction_col, right_on='interaction',
    how='left'
  )

  # merge2 - disease annotation
  anno = pd.merge(
    anno,
    lr_diseases_unique,
    left_on=interaction_col, right_on='interaction',
    how='left'
  )

  sel_colnames = list(lr_loadings.columns)
  sel_colnames.append(geneset_col_name)
  sel_colnames.append('disease')

  return(anno[sel_colnames])


def res_liana_loadings(lrdata, th_morans=0, p_th=0.05, organism='human', geneset='progeny', plot=True, save_path='res/'):

  sig_liana = _get_sigliana(lrdata, th_morans=th_morans, p_th=p_th)
  lr_loadings = _get_loadings(lrdata)
  anno_lr_loadings = _anno_lr_loadings(lr_loadings, organism=organism, geneset=geneset)
  # anno_sig_liana = pd.merge(sig_liana, anno_lr_loadings[['interaction', 'progeny', 'disease']])
  anno_sig_liana = pd.merge(sig_liana, anno_lr_loadings)

  anno_sig_liana = anno_sig_liana.sort_values(by='morans', ascending=False)

  print(f"Filtered from {lr_loadings.shape[0]} to {anno_sig_liana.shape[0]} significant interactions")
  print(f"th_morans={th_morans} / p_th={p_th}")

  if plot:
    import matplotlib.pyplot as plt
    import numpy as np

    res_liana = lrdata.var.sort_values("morans", ascending=False)
    sig_liana = res_liana.query(f'morans > {th_morans} & morans_pvals < {p_th}')

    fig, ax = plt.subplots(figsize=(8, 8))

    # Create boolean mask for sig_liana
    is_sig = res_liana.index.isin(sig_liana.index)

    # Plot non-significant points in gray
    ax.scatter(res_liana.loc[~is_sig, 'morans'], 
              res_liana.loc[~is_sig, 'mean'], 
              alpha=0.5, 
              color='gray', 
              s=30,
              label='Non-significant')

    # Plot significant points in red
    ax.scatter(res_liana.loc[is_sig, 'morans'], 
              res_liana.loc[is_sig, 'mean'], 
              alpha=0.6, 
              color='red', 
              s=50,
              label='sig_liana')

    # Add threshold lines
    ax.axvline(x=th_morans, color='black', linestyle='--', alpha=1, label=f'Morans threshold ({th_morans})')

    ax.set_xlabel('Moran’s R', fontsize=12)
    ax.set_ylabel('Mean', fontsize=12)
    ax.set_title('Ligand-Receptor Interactions', fontsize=14)
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(f"{save_path}/6.liana_MoransR.png", dpi=300, bbox_inches='tight') 

    plt.show()

  return(anno_sig_liana)



def enrich_pathway_factor(lr_loadings, organism='human', geneset='progeny', min_n=5):

  # Get pathway database based on geneset choice
  if geneset == 'progeny':
    pathway_db = dc.op.progeny(organism=organism)
  else:  # hallmark
    pathway_db = dc.op.hallmark(organism=organism)

  lr_loadings['ligand'] = list(lr_loadings['ligand'])
  lr_loadings['receptor'] = list(lr_loadings['receptor'])

  # Generate LR geneset - progeny has weight, hallmark does not
  if geneset == 'progeny':
    lr_pathway = li.rs.generate_lr_geneset(lr_loadings, pathway_db, lr_sep="^")
    lr_pathway.columns = ['source', 'target', 'weight']
  else:  # hallmark - no weight column
    lr_pathway = li.rs.generate_lr_geneset(lr_loadings, pathway_db, lr_sep="^", weight=None)
    lr_pathway.columns = ['source', 'target']
    # Add uniform weight for mlm (equal contribution)
    lr_pathway['weight'] = 1.0

  t_lr_loadings = lr_loadings.set_index('interaction')
  factor_cols = [col for col in t_lr_loadings.columns if col.startswith('Factor')]
  t_lr_loadings = t_lr_loadings[factor_cols].transpose()

  # run pathway enrichment analysis
  # Use mlm for progeny (14 pathways, dense), ulm for hallmark (50 pathways, sparse)
  # ulm is more robust to singular matrix issues with sparse gene overlap data
  if geneset == 'progeny':
    estimate, pvals = dc.mt.mlm(
      data=t_lr_loadings,
      net=lr_pathway,
      tmin=min_n
    )
  else:  # hallmark - use ulm for robustness with sparse data
    estimate, pvals = dc.mt.ulm(
      data=t_lr_loadings,
      net=lr_pathway,
      tmin=min_n
    )

  from statsmodels.stats.multitest import multipletests
  # Pivot and merge data
  estimate_long = estimate.melt(ignore_index=False, value_name='estimate', var_name='pathway').reset_index().rename(columns={'index':'factor'})
  pvals_long = pvals.melt(ignore_index=False, value_name='pval', var_name='pathway').reset_index().rename(columns={'index':'factor'})
  dc_res = estimate_long.merge(pvals_long, on=['factor', 'pathway'])
  _, adj_pval, _, _ = multipletests(dc_res['pval'], method='fdr_bh')
  dc_res['adj_pval'] = adj_pval

  return(dc_res)


#########################################################################################################
#########################################################################################################
#########################################################################################################

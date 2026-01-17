"""
Cell-Cell Interaction Analysis Utilities
Functions for processing and analyzing cell-cell interaction data from LIANA
"""

import pandas as pd
import numpy as np
from scipy.sparse import issparse
from typing import Dict, Tuple, Optional, List
import scanpy as sc
from .utils import cauchy_combination


def calculate_interaction_means_by_cluster(
    lrdata: sc.AnnData,
    celltype_column: str = 'celltype_niche',
    layer_name: str = 'cats'
) -> Dict[Tuple[str, str], float]:
    """
    Calculate mean values for each interaction per cluster from lrdata layers.
    
    Parameters
    ----------
    lrdata : sc.AnnData
        AnnData object containing interaction data in layers
    celltype_column : str
        Column name in lrdata.obs containing celltype/cluster information
    layer_name : str
        Name of the layer containing interaction values (default: 'cats')
    
    Returns
    -------
    Dict[Tuple[str, str], float]
        Dictionary with (interaction, cluster) as keys and mean values
    """
    # Extract data from specified layer
    layer_data = lrdata.layers[layer_name]
    
    # Convert sparse matrix to dense if needed
    if issparse(layer_data):
        layer_data = layer_data.toarray()
    
    # Get celltype information
    celltype_values = lrdata.obs[celltype_column].astype(str).values
    unique_celltypes = np.unique(celltype_values)
    
    # Get all interactions from var index
    interactions = lrdata.var.index.tolist()
    
    # Create dictionary to store mean values
    interaction_cluster_means = {}
    
    # Process each interaction
    for idx, interaction in enumerate(interactions):
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
            mean_value = np.nanmean(celltype_vals) if len(celltype_vals) > 0 else np.nan
            
            # Store in dictionary
            interaction_cluster_means[(interaction, celltype)] = mean_value
    
    return interaction_cluster_means


def add_cluster_means_to_cci(
    anno_sig_liana_cci: pd.DataFrame,
    lrdata: sc.AnnData,
    source_column: str = 'source',
    target_column: str = 'target',
    interaction_column: str = 'liana_interaction',
    celltype_column: str = 'celltype_niche',
    layer_name: str = 'cats'
) -> pd.DataFrame:
    """
    Add cluster-wise mean expression values to CCI annotation dataframe.
    
    Parameters
    ----------
    anno_sig_liana_cci : pd.DataFrame
        DataFrame containing CCI annotations with source, target, and interaction columns
    lrdata : sc.AnnData
        AnnData object containing interaction data in layers
    source_column : str
        Column name for source cluster in anno_sig_liana_cci
    target_column : str
        Column name for target cluster in anno_sig_liana_cci
    interaction_column : str
        Column name for interaction in anno_sig_liana_cci
    celltype_column : str
        Column name in lrdata.obs containing celltype/cluster information
    layer_name : str
        Name of the layer containing interaction values
    
    Returns
    -------
    pd.DataFrame
        Updated DataFrame with added columns:
        - source_mean: Mean expression in source cluster
        - target_mean: Mean expression in target cluster
        - mean_difference: target_mean - source_mean
        - mean_abs_difference: Absolute difference
    """
    # Make a copy to avoid modifying the original
    df = anno_sig_liana_cci.copy()
    
    # Calculate interaction means by cluster
    print("Calculating cluster-wise means...")
    interaction_cluster_means = calculate_interaction_means_by_cluster(
        lrdata, celltype_column, layer_name
    )
    
    # Extract unique interactions from the dataframe
    unique_interactions = df[interaction_column].unique()
    print(f"Processing {len(unique_interactions)} unique interactions...")
    
    # Map means to source and target columns
    source_means = []
    target_means = []
    
    for idx, row in df.iterrows():
        interaction = row[interaction_column]
        source = row[source_column]
        target = row[target_column]
        
        # Look up mean values
        source_key = (interaction, source)
        target_key = (interaction, target)
        
        # Get mean values from dictionary
        source_mean = interaction_cluster_means.get(source_key, np.nan)
        target_mean = interaction_cluster_means.get(target_key, np.nan)
        
        source_means.append(source_mean)
        target_means.append(target_mean)
    
    # Add new columns
    df['source_mean'] = source_means
    df['target_mean'] = target_means
    df['mean_difference'] = df['target_mean'] - df['source_mean']
    df['mean_abs_difference'] = df['mean_difference'].abs()
    
    # Print summary statistics
    print(f"\nSummary Statistics:")
    print(f"Source mean - Min: {df['source_mean'].min():.4f}, Max: {df['source_mean'].max():.4f}, Mean: {df['source_mean'].mean():.4f}")
    print(f"Target mean - Min: {df['target_mean'].min():.4f}, Max: {df['target_mean'].max():.4f}, Mean: {df['target_mean'].mean():.4f}")
    
    missing_source = df['source_mean'].isna().sum()
    missing_target = df['target_mean'].isna().sum()
    if missing_source > 0 or missing_target > 0:
        print(f"\nWarning: Missing values detected")
        print(f"  Source mean: {missing_source} missing values")
        print(f"  Target mean: {missing_target} missing values")
    
    return df


def get_top_differential_interactions(
    df: pd.DataFrame,
    n_top: int = 10,
    by: str = 'mean_abs_difference'
) -> pd.DataFrame:
    """
    Get top interactions based on differential expression between source and target.
    
    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with source_mean, target_mean columns (output from add_cluster_means_to_cci)
    n_top : int
        Number of top interactions to return
    by : str
        Column to sort by ('mean_abs_difference' or 'mean_difference')
    
    Returns
    -------
    pd.DataFrame
        Top n interactions sorted by specified criterion
    """
    if by not in ['mean_abs_difference', 'mean_difference']:
        raise ValueError("'by' must be either 'mean_abs_difference' or 'mean_difference'")
    
    if by not in df.columns:
        raise ValueError(f"Column '{by}' not found. Run add_cluster_means_to_cci first.")
    
    columns_to_show = ['source', 'target', 'liana_interaction', 
                       'source_mean', 'target_mean', 'mean_difference']
    
    # Filter columns that exist in the dataframe
    columns_to_show = [col for col in columns_to_show if col in df.columns]
    
    if by == 'mean_abs_difference':
        return df.nlargest(n_top, by)[columns_to_show]
    else:
        # For mean_difference, we might want both positive and negative top values
        top_positive = df.nlargest(n_top // 2, by)[columns_to_show]
        top_negative = df.nsmallest(n_top // 2, by)[columns_to_show]
        return pd.concat([top_positive, top_negative]).sort_values(by, ascending=False)


def summarize_interactions_by_celltype_pair(
    df: pd.DataFrame,
    source_column: str = 'source',
    target_column: str = 'target'
) -> pd.DataFrame:
    """
    Summarize interaction statistics for each celltype pair.
    
    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with cluster means (output from add_cluster_means_to_cci)
    source_column : str
        Column name for source cluster
    target_column : str
        Column name for target cluster
    
    Returns
    -------
    pd.DataFrame
        Summary statistics for each source-target pair
    """
    summary = df.groupby([source_column, target_column]).agg({
        'liana_interaction': 'count',
        'source_mean': 'mean',
        'target_mean': 'mean',
        'mean_difference': 'mean',
        'mean_abs_difference': 'mean'
    }).round(4)
    
    summary.columns = ['n_interactions', 'avg_source_mean', 'avg_target_mean', 
                       'avg_difference', 'avg_abs_difference']
    
    return summary.sort_values('n_interactions', ascending=False)


def calculate_interaction_pvals_by_cluster(
    lrdata: sc.AnnData,
    celltype_column: str = 'celltype_niche',
    layer_name: str = 'pvals'
) -> Dict[Tuple[str, str], float]:
    """
    Calculate combined p-values for each interaction per cluster using Cauchy combination.
    
    Parameters
    ----------
    lrdata : sc.AnnData
        AnnData object containing interaction data in layers
    celltype_column : str
        Column name in lrdata.obs containing celltype/cluster information
    layer_name : str
        Name of the layer containing p-values (default: 'pvals')
    
    Returns
    -------
    Dict[Tuple[str, str], float]
        Dictionary with (interaction, cluster) as keys and combined p-values
    """
    # Extract p-values from specified layer
    pvals_data = lrdata.layers[layer_name]
    
    # Convert sparse matrix to dense if needed
    if issparse(pvals_data):
        pvals_data = pvals_data.toarray()
    
    # Get celltype information
    celltype_values = lrdata.obs[celltype_column].astype(str).values
    unique_celltypes = np.unique(celltype_values)
    
    # Get all interactions from var index
    interactions = lrdata.var.index.tolist()
    
    # Create dictionary to store combined p-values
    interaction_cluster_pvals = {}
    
    # Process each interaction
    for idx, interaction in enumerate(interactions):
        # Extract p-values for this interaction
        interaction_pvals = pvals_data[:, idx]
        if hasattr(interaction_pvals, 'A1'):  # If it's still a sparse matrix
            interaction_pvals = interaction_pvals.A1
        elif hasattr(interaction_pvals, 'flatten'):
            interaction_pvals = interaction_pvals.flatten()
        
        # Calculate combined p-value for each celltype using Cauchy
        for celltype in unique_celltypes:
            # Get indices of cells belonging to this celltype
            celltype_mask = celltype_values == celltype
            celltype_pvals = interaction_pvals[celltype_mask]
            
            # Filter out NaN and invalid p-values
            valid_pvals = []
            for pval in celltype_pvals:
                if pd.notna(pval) and 0 < pval <= 1:
                    valid_pvals.append(pval)
            
            # Apply Cauchy combination if we have valid p-values
            if valid_pvals:
                try:
                    combined_pval = cauchy_combination(valid_pvals)
                    interaction_cluster_pvals[(interaction, celltype)] = combined_pval
                except Exception as e:
                    print(f"Warning: Error combining p-values for {interaction}, {celltype}: {e}")
                    interaction_cluster_pvals[(interaction, celltype)] = np.nan
            else:
                # No valid p-values for this interaction-celltype combination
                interaction_cluster_pvals[(interaction, celltype)] = np.nan
    
    return interaction_cluster_pvals


def add_cluster_combined_pvals_to_cci(
    anno_sig_liana_cci: pd.DataFrame,
    lrdata: sc.AnnData,
    source_column: str = 'source',
    target_column: str = 'target',
    interaction_column: str = 'liana_interaction',
    celltype_column: str = 'celltype_niche',
    layer_name: str = 'pvals'
) -> pd.DataFrame:
    """
    Add cluster-wise combined p-values to CCI annotation dataframe using Cauchy combination.
    
    Parameters
    ----------
    anno_sig_liana_cci : pd.DataFrame
        DataFrame containing CCI annotations with source, target, and interaction columns
    lrdata : sc.AnnData
        AnnData object containing interaction data in layers
    source_column : str
        Column name for source cluster in anno_sig_liana_cci
    target_column : str
        Column name for target cluster in anno_sig_liana_cci
    interaction_column : str
        Column name for interaction in anno_sig_liana_cci
    celltype_column : str
        Column name in lrdata.obs containing celltype/cluster information
    layer_name : str
        Name of the layer containing p-values
    
    Returns
    -------
    pd.DataFrame
        Updated DataFrame with added columns:
        - source_combined_pval: Cauchy-combined p-value for source cluster
        - target_combined_pval: Cauchy-combined p-value for target cluster
        - neg_log10_source_pval: -log10 transformation of source p-value
        - neg_log10_target_pval: -log10 transformation of target p-value
    """
    # Make a copy to avoid modifying the original
    df = anno_sig_liana_cci.copy()
    
    # Calculate combined p-values by cluster
    print("Calculating cluster-wise combined p-values using Cauchy method...")
    interaction_cluster_pvals = calculate_interaction_pvals_by_cluster(
        lrdata, celltype_column, layer_name
    )
    
    # Extract unique interactions from the dataframe
    unique_interactions = df[interaction_column].unique()
    print(f"Processing {len(unique_interactions)} unique interactions...")
    
    # Map combined p-values to source and target columns
    source_pvals = []
    target_pvals = []
    neg_log10_source = []
    neg_log10_target = []
    
    for idx, row in df.iterrows():
        interaction = row[interaction_column]
        source = row[source_column]
        target = row[target_column]
        
        # Look up combined p-values
        source_key = (interaction, source)
        target_key = (interaction, target)
        
        # Get combined p-values from dictionary
        source_pval = interaction_cluster_pvals.get(source_key, np.nan)
        target_pval = interaction_cluster_pvals.get(target_key, np.nan)
        
        source_pvals.append(source_pval)
        target_pvals.append(target_pval)
        
        # Calculate -log10 transformations
        if pd.notna(source_pval) and source_pval > 0:
            neg_log10_source.append(-np.log10(source_pval))
        else:
            neg_log10_source.append(np.nan)
            
        if pd.notna(target_pval) and target_pval > 0:
            neg_log10_target.append(-np.log10(target_pval))
        else:
            neg_log10_target.append(np.nan)
    
    # Add new columns
    df['source_combined_pval'] = source_pvals
    df['target_combined_pval'] = target_pvals
    df['neg_log10_source_pval'] = neg_log10_source
    df['neg_log10_target_pval'] = neg_log10_target
    
    # Print summary statistics
    print(f"\nSummary Statistics for Combined P-values:")
    print(f"Source p-val - Min: {df['source_combined_pval'].min():.6f}, Max: {df['source_combined_pval'].max():.6f}, Median: {df['source_combined_pval'].median():.6f}")
    print(f"Target p-val - Min: {df['target_combined_pval'].min():.6f}, Max: {df['target_combined_pval'].max():.6f}, Median: {df['target_combined_pval'].median():.6f}")
    
    # Check for significant interactions (p < 0.05)
    sig_threshold = 0.05
    source_sig = (df['source_combined_pval'] < sig_threshold).sum()
    target_sig = (df['target_combined_pval'] < sig_threshold).sum()
    both_sig = ((df['source_combined_pval'] < sig_threshold) & (df['target_combined_pval'] < sig_threshold)).sum()
    
    print(f"\nSignificant interactions (p < {sig_threshold}):")
    print(f"  Source cluster: {source_sig}/{len(df)} ({100*source_sig/len(df):.1f}%)")
    print(f"  Target cluster: {target_sig}/{len(df)} ({100*target_sig/len(df):.1f}%)")
    print(f"  Both clusters: {both_sig}/{len(df)} ({100*both_sig/len(df):.1f}%)")
    
    missing_source = df['source_combined_pval'].isna().sum()
    missing_target = df['target_combined_pval'].isna().sum()
    if missing_source > 0 or missing_target > 0:
        print(f"\nWarning: Missing values detected")
        print(f"  Source p-val: {missing_source} missing values")
        print(f"  Target p-val: {missing_target} missing values")
    
    return df


def get_top_significant_interactions(
    df: pd.DataFrame,
    n_top: int = 10,
    by: str = 'both',
    sig_threshold: float = 0.05
) -> pd.DataFrame:
    """
    Get top significant interactions based on combined p-values.
    
    Parameters
    ----------
    df : pd.DataFrame
        DataFrame with combined p-value columns (output from add_cluster_combined_pvals_to_cci)
    n_top : int
        Number of top interactions to return
    by : str
        How to select top interactions:
        - 'both': Both source and target must be significant
        - 'source': Sort by source p-value
        - 'target': Sort by target p-value
        - 'either': Either source or target is significant
    sig_threshold : float
        P-value threshold for significance
    
    Returns
    -------
    pd.DataFrame
        Top n significant interactions
    """
    required_cols = ['source_combined_pval', 'target_combined_pval']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Column '{col}' not found. Run add_cluster_combined_pvals_to_cci first.")
    
    columns_to_show = ['source', 'target', 'liana_interaction', 
                       'source_combined_pval', 'target_combined_pval',
                       'neg_log10_source_pval', 'neg_log10_target_pval']
    
    # Filter columns that exist in the dataframe
    columns_to_show = [col for col in columns_to_show if col in df.columns]
    
    if by == 'both':
        # Filter for both significant
        filtered = df[(df['source_combined_pval'] < sig_threshold) & 
                     (df['target_combined_pval'] < sig_threshold)].copy()
        # Sort by geometric mean of p-values
        filtered['geom_mean_pval'] = np.sqrt(filtered['source_combined_pval'] * filtered['target_combined_pval'])
        filtered = filtered.nsmallest(n_top, 'geom_mean_pval')
        return filtered[columns_to_show]
    
    elif by == 'source':
        filtered = df[df['source_combined_pval'] < sig_threshold]
        return filtered.nsmallest(n_top, 'source_combined_pval')[columns_to_show]
    
    elif by == 'target':
        filtered = df[df['target_combined_pval'] < sig_threshold]
        return filtered.nsmallest(n_top, 'target_combined_pval')[columns_to_show]
    
    elif by == 'either':
        # Filter for either significant
        filtered = df[(df['source_combined_pval'] < sig_threshold) | 
                     (df['target_combined_pval'] < sig_threshold)].copy()
        # Sort by minimum p-value
        filtered['min_pval'] = filtered[['source_combined_pval', 'target_combined_pval']].min(axis=1)
        filtered = filtered.nsmallest(n_top, 'min_pval')
        return filtered[columns_to_show]
    
    else:
        raise ValueError("'by' must be one of: 'both', 'source', 'target', 'either'")
import logging

import numpy as np
import pandas as pd
import scipy as sp

logger = logging.getLogger(__name__)

# def summary_lianap(lrdata, celltype_key='celltype_niche', aggregation='cauchy', 
#                    pval_threshold=0.05, output_file='summary_lianap.csv'):
#     """
#     Convert liana bivariate results to celltype-celltype interaction format
    
#     Parameters:
#     -----------
#     lrdata : AnnData object
#         Result from liana bivariate analysis
#     celltype_key : str
#         Key in lrdata.obs containing celltype information (default: 'celltype_niche')
#     aggregation : str
#         Method to aggregate p-values: 'cauchy', 'median', 'min' (default: 'cauchy')
#     pval_threshold : float
#         Only include interactions with aggregated p-value < threshold (default: 0.05)
#     output_file : str
#         Output filename for summary CSV
        
#     Returns:
#     --------
#     pd.DataFrame : DataFrame with columns [source, target, ligand, receptor, pval]
#     """
#     import scipy.sparse as sp_sparse
    
#     # Get celltype information and p-values matrix
#     celltypes = lrdata.obs[celltype_key].values
#     pvals_matrix = lrdata.layers['pvals']
#     if sp_sparse.issparse(pvals_matrix):
#         pvals_matrix = pvals_matrix.toarray()
    
#     # Get interaction names and unique celltypes
#     interactions = lrdata.var.index.tolist()
#     unique_celltypes = np.unique(celltypes)
    
#     # Dictionary to store p-values for aggregation
#     celltype_interactions = {}
    
#     # For each celltype pair
#     for source_ct in unique_celltypes:
#         # Get indices of cells belonging to source celltype
#         source_indices = np.where(celltypes == source_ct)[0]
        
#         for target_ct in unique_celltypes:
#             # For each interaction
#             for idx, interaction in enumerate(interactions):
#                 # Collect p-values from source celltype cells
#                 pvals = []
#                 for i in source_indices:
#                     pval = pvals_matrix[i, idx]
#                     if not np.isnan(pval):
#                         pvals.append(pval)
                
#                 # Store for aggregation if we have p-values
#                 if pvals:
#                     key = (source_ct, target_ct, interaction)
#                     celltype_interactions[key] = pvals
    
#     # Aggregate p-values and create result DataFrame
#     result = []
#     for (source, target, interaction), pvals in celltype_interactions.items():
#         if len(pvals) == 0:
#             continue
            
#         # Split interaction into ligand and receptor
#         if '^' in interaction:
#             parts = interaction.split('^')
#             ligand = parts[0]
#             receptor = parts[1] if len(parts) > 1 else ''
#         else:
#             parts = interaction.split('_')
#             ligand = parts[0] if len(parts) > 0 else interaction
#             receptor = '_'.join(parts[1:]) if len(parts) > 1 else ''
        
#         # Aggregate p-values
#         if aggregation == 'cauchy':
#             agg_pval = cauchy_combination(pvals)
#         elif aggregation == 'median':
#             agg_pval = np.median(pvals)
#         elif aggregation == 'min':
#             agg_pval = np.min(pvals)
#         else:
#             raise ValueError(f"Unknown aggregation method: {aggregation}")
        
#         # Apply threshold filter
#         if agg_pval < pval_threshold:
#             result.append({
#                 'source': source,
#                 'target': target,
#                 'ligand': ligand,
#                 'receptor': receptor,
#                 'pval': agg_pval
#             })
    
#     # Create DataFrame and sort by p-value
#     result_df = pd.DataFrame(result)
#     if not result_df.empty:
#         result_df = result_df.sort_values('pval').reset_index(drop=True)
    
#     # Save to file if requested
#     if output_file and not result_df.empty:
#         result_df.to_csv(output_file, index=False)
#         print(f"Saved {len(result_df)} celltype interactions to '{output_file}'")
#         print(f"Aggregation method: {aggregation}")
    
#     return result_df



# def convert_pvals_to_long(lrdata, save=True, output_file='pvalues_long_form.csv'):
#     """
#     Convert p-values matrix from AnnData object to long-form DataFrame
    
#     Parameters:
#     -----------
#     lrdata : AnnData object
#         Result from liana bivariate analysis
#     save : bool
#         Whether to save the result to CSV file
#     output_file : str
#         Output filename for CSV (only used if save=True)
        
#     Returns:
#     --------
#     pd.DataFrame : Long-form DataFrame with columns [cell, interaction, pvalue]
#     """
    
#     # Extract the p-values matrix (convert from sparse to dense)
#     pvals_matrix = lrdata.layers['pvals'].toarray()
    
#     # Get cell and interaction names
#     cell_names = lrdata.obs.index.tolist()
#     interaction_names = lrdata.var.index.tolist()
    
#     # Create a DataFrame with cells as rows and interactions as columns
#     pvals_df = pd.DataFrame(pvals_matrix, 
#                             index=cell_names, 
#                             columns=interaction_names)
    
#     # Convert to long format
#     pvals_long = pvals_df.reset_index().melt(id_vars='index', 
#                                              var_name='interaction', 
#                                              value_name='pvalue')
    
#     # Rename the index column to 'cell'
#     pvals_long.rename(columns={'index': 'cell'}, inplace=True)
    
#     # Save to CSV if requested
#     if save:
#         pvals_long.to_csv(output_file, index=False)
#         print(f"Original matrix shape: {pvals_matrix.shape}")
#         print(f"Long format shape: {pvals_long.shape}")
#         print(f"Saved to '{output_file}'")
    
#     return pvals_long
# # Example usage:
# # pvals_long = convert_pvals_to_long(lrdata, 'pvalues_long_form.csv')


def old_cauchy_combination(pvalues, weights=None):
    """
    Aggregated Cauchy Association Test (ACAT)
    Combines p-values using the Cauchy distribution.
    
    Parameters:
    -----------
    pvalues : array-like
        P-values to combine (between 0 and 1)
    weights : array-like, optional
        Weights for each p-value (default: equal weights)
        
    Returns:
    --------
    float : Combined p-value
    """
    pvalues = np.asarray(pvalues)
    
    # Validation
    if np.any(np.isnan(pvalues)):
        raise ValueError("P-values cannot contain NaN")
    if np.any((pvalues < 0) | (pvalues > 1)):
        raise ValueError("P-values must be between 0 and 1")
    
    # Handle edge cases
    if np.any(pvalues == 0):
        return 0.0
    if np.any(pvalues == 1):
        return 1.0
    
    # Set weights
    if weights is None:
        weights = np.ones(len(pvalues)) / len(pvalues)
    else:
        weights = np.asarray(weights)
        if len(weights) != len(pvalues):
            raise ValueError("Weights and p-values must have same length")
        if np.any(weights < 0):
            raise ValueError("Weights must be positive")
        weights = weights / np.sum(weights)
    
    # Calculate Cauchy statistic
    small_mask = pvalues < 1e-15
    if np.any(small_mask):
        stat = np.sum(weights[small_mask] / (pvalues[small_mask] * np.pi))
        stat += np.sum(weights[~small_mask] * np.tan((0.5 - pvalues[~small_mask]) * np.pi))
    else:
        stat = np.sum(weights * np.tan((0.5 - pvalues) * np.pi))
    
    # Calculate p-value
    if stat > 1e15:
        return 1.0 / (stat * np.pi)
    else:
        return 1.0 - sp.stats.cauchy.cdf(stat)
        
def cauchy_combination(pvalues, weights=None, min_pvalue=1e-10, n_permutations=None):
    """
    Aggregated Cauchy Association Test (ACAT)
    Combines p-values using the Cauchy distribution.

    Reference: Liu Y, Xie J. (2020) ACAT: A Fast and Powerful p Value
    Combination Method for Rare-Variant Analysis in Sequencing Studies.
    AJHG 106(4):534-544.

    Parameters:
    -----------
    pvalues : array-like
        P-values to combine (between 0 and 1)
    weights : array-like, optional
        Weights for each p-value (default: equal weights)
    min_pvalue : float, optional
        Minimum p-value floor for p=0 replacement (default: 1e-10).
        This corresponds to -log10(p) = 10, which is highly significant.
        Choose based on your experimental resolution:
        - 1e-2 for ~100 permutations
        - 1e-3 for ~1,000 permutations
        - 1e-4 for ~10,000 permutations
        - 1e-10 for general use (default, conservative)
    n_permutations : int, optional
        Number of permutations used to generate p-values.
        If provided, overrides min_pvalue with 1/(n_permutations + 1).
        This follows the ACAT paper recommendation.

    Returns:
    --------
    float : Combined p-value

    Notes:
    ------
    Following the ACAT methodology:
    - p=0 is replaced with min_pvalue (or 1/(n_permutations+1) if provided)
    - p=1 is replaced with 1 - min_pvalue

    The default min_pvalue=1e-10 gives -log10(p) = 10 for extremely
    significant results, which is interpretable and appropriate for
    most biological applications.
    """
    pvalues = np.asarray(pvalues, dtype=float)

    # Validation
    if len(pvalues) == 0:
        return 1.0  # No evidence

    if np.any(np.isnan(pvalues)):
        raise ValueError("P-values cannot contain NaN")
    if np.any((pvalues < 0) | (pvalues > 1)):
        raise ValueError("P-values must be between 0 and 1")

    # Calculate effective min_pvalue based on n_permutations if provided
    if n_permutations is not None:
        if n_permutations < 1:
            raise ValueError("n_permutations must be >= 1")
        min_pvalue = 1.0 / (n_permutations + 1)

    # Ensure min_pvalue is within valid bounds
    min_pvalue = max(min_pvalue, np.finfo(float).tiny)  # At least machine minimum
    min_pvalue = min(min_pvalue, 0.5)  # At most 0.5

    # Handle edge cases with epsilon replacement (ACAT methodology)
    # Count zeros for logging
    n_zeros = np.sum(pvalues == 0)
    n_ones = np.sum(pvalues == 1)

    if n_zeros > 0:
        logger.debug(f"Cauchy combination: {n_zeros} p-values equal to 0, "
                    f"replaced with {min_pvalue:.2e} (-log10 = {-np.log10(min_pvalue):.1f})")
    if n_ones > 0:
        logger.debug(f"Cauchy combination: {n_ones} p-values equal to 1, "
                    f"replaced with {1 - min_pvalue:.10f}")

    # p = 0: extremely significant - replace with min_pvalue
    pvalues = np.where(pvalues == 0, min_pvalue, pvalues)
    # p = 1: no evidence from this test - replace with 1 - min_pvalue
    # This avoids -infinity in tan() while preserving the "no evidence" interpretation
    pvalues = np.where(pvalues == 1, 1 - min_pvalue, pvalues)

    # Set weights
    if weights is None:
        weights = np.ones(len(pvalues)) / len(pvalues)
    else:
        weights = np.asarray(weights)
        if len(weights) != len(pvalues):
            raise ValueError("Weights and p-values must have same length")
        if np.any(weights < 0):
            raise ValueError("Weights must be positive")
        weights = weights / np.sum(weights)

    # Calculate Cauchy statistic
    # For very small p-values, use approximation: tan((0.5-p)*pi) ~ 1/(p*pi)
    small_mask = pvalues < 1e-15
    if np.any(small_mask):
        stat = np.sum(weights[small_mask] / (pvalues[small_mask] * np.pi))
        stat += np.sum(weights[~small_mask] * np.tan((0.5 - pvalues[~small_mask]) * np.pi))
    else:
        stat = np.sum(weights * np.tan((0.5 - pvalues) * np.pi))

    # Calculate combined p-value
    # For very large stat, use approximation: 1 - CDF(stat) ~ 1/(pi*stat)
    if stat > 1e15:
        return 1.0 / (stat * np.pi)
    else:
        return 1.0 - sp.stats.cauchy.cdf(stat)


def cellphonedb_pvals_to_long_simple(pvalues_df, pval_threshold=0.05, output_file=None):
    """
    Convert CellPhoneDB pvalues matrix to long format
    
    Parameters:
    -----------
    pvalues_df : pd.DataFrame
        P-values DataFrame from res_CellPhoneDB["pvalues"]
        - Index: tuples of (ligand, receptor) or ligand_receptor strings
        - Columns: tuples of (source, target) or source|target strings
        - Values: p-values
    pval_threshold : float
        Only include interactions with p-value < threshold (default: 0.05)
    output_file : str, optional
        Output CSV filename
        
    Returns:
    --------
    pd.DataFrame with columns: source, target, ligand, receptor, pval
    """
    result = []
    
    # Iterate through all cells in the matrix
    for lr_pair in pvalues_df.index:
        # Handle different index formats
        if isinstance(lr_pair, tuple):
            # Index is already a tuple (ligand, receptor)
            if len(lr_pair) >= 2:
                ligand = lr_pair[0]
                receptor = '_'.join(lr_pair[1:]) if len(lr_pair) > 2 else lr_pair[1]
            else:
                continue
        else:
            # Index is a string, split by underscore
            parts = str(lr_pair).split('_')
            if len(parts) >= 2:
                ligand = parts[0]
                receptor = '_'.join(parts[1:])
            else:
                continue
            
        for cell_pair in pvalues_df.columns:
            # Handle different column formats
            if isinstance(cell_pair, tuple):
                # Column is already a tuple (source, target)
                if len(cell_pair) >= 2:
                    source = cell_pair[0]
                    target = cell_pair[1]
                else:
                    continue
            elif '|' in str(cell_pair):
                # Column is a string with pipe separator
                source, target = str(cell_pair).split('|')
                source = source.strip()
                target = target.strip()
            else:
                continue
            
            # Get the p-value
            pval = pvalues_df.loc[lr_pair, cell_pair]
            
            # Only include non-NaN values
            if pd.notna(pval):
                result.append({
                    'source': source,
                    'target': target,
                    'ligand': ligand,
                    'receptor': receptor,
                    'pval': pval
                })
    
    # Create DataFrame
    long_df = pd.DataFrame(result)
    
    # Filter by p-value threshold
    if not long_df.empty:
        long_df = long_df[long_df['pval'] < pval_threshold]
        # Sort by p-value for better readability
        long_df = long_df.sort_values('pval').reset_index(drop=True)
    
    # Save if requested
    if output_file:
        long_df.to_csv(output_file, index=False)
        print(f"Converted {len(pvalues_df.index)} interactions x {len(pvalues_df.columns)} cell pairs")
        print(f"Filtered to {len(long_df)} rows with p-value < {pval_threshold}")
        print(f"Saved to {output_file}")
    
    return long_df


def cellphonedb_pvals_to_long(res_cellphonedb, pval_threshold=0.05, include_metadata=True, output_file=None):
    """
    Convert CellPhoneDB results to long format with optional metadata and p-value filtering
    
    Parameters:
    -----------
    res_cellphonedb : dict
        Complete CellPhoneDB result dictionary with 'pvalues', 'metadata', 'means'
    pval_threshold : float
        Only include interactions with p-value < threshold (default: 0.05)
    include_metadata : bool
        Whether to include metadata columns (default: True)
    output_file : str, optional
        Output CSV filename
        
    Returns:
    --------
    pd.DataFrame with columns: source, target, ligand, receptor, mean, log10_pval, pval, [metadata columns...]
    """
    # Extract pvalues and means DataFrames
    pvalues_df = res_cellphonedb['pvalues']
    means_df = res_cellphonedb['means']
    
    # Validation checks
    if pvalues_df.shape != means_df.shape:
        raise ValueError(f"Shape mismatch: pvalues {pvalues_df.shape} != means {means_df.shape}")
    
    if not pvalues_df.index.equals(means_df.index):
        raise ValueError("Index mismatch between pvalues and means DataFrames")
    
    if not pvalues_df.columns.equals(means_df.columns):
        raise ValueError("Column mismatch between pvalues and means DataFrames")
    
    result = []
    
    # Iterate through all cells in the matrix
    for lr_pair in pvalues_df.index:
        # Handle different index formats
        if isinstance(lr_pair, tuple):
            # Index is already a tuple (ligand, receptor)
            if len(lr_pair) >= 2:
                ligand = lr_pair[0]
                receptor = '_'.join(lr_pair[1:]) if len(lr_pair) > 2 else lr_pair[1]
            else:
                continue
        else:
            # Index is a string, split by underscore
            parts = str(lr_pair).split('_')
            if len(parts) >= 2:
                ligand = parts[0]
                receptor = '_'.join(parts[1:])
            else:
                continue
            
        for cell_pair in pvalues_df.columns:
            # Handle different column formats
            if isinstance(cell_pair, tuple):
                # Column is already a tuple (source, target)
                if len(cell_pair) >= 2:
                    source = cell_pair[0]
                    target = cell_pair[1]
                else:
                    continue
            elif '|' in str(cell_pair):
                # Column is a string with pipe separator
                source, target = str(cell_pair).split('|')
                source = source.strip()
                target = target.strip()
            else:
                continue
            
            # Get the p-value and mean
            pval = pvalues_df.loc[lr_pair, cell_pair]
            mean = means_df.loc[lr_pair, cell_pair]
            
            # Apply p-value filtering and check for NaN
            if pd.notna(pval) and pval < pval_threshold:
                # Calculate -log10(pval), handling zeros by capping at 1e-100
                log10_pval = -np.log10(np.maximum(pval, 1e-100))
                
                result.append({
                    'source': source,
                    'target': target,
                    'ligand': ligand,
                    'receptor': receptor,
                    'mean': mean,
                    'log10_pval': log10_pval,
                    'pval': pval,
                    'lr_pair': lr_pair  # Keep original tuple for merging with metadata
                })
    
    # Create DataFrame
    long_df = pd.DataFrame(result)
    
    if long_df.empty:
        print(f"No interactions found with p-value < {pval_threshold}")
        return long_df
    
    # Add metadata if requested
    if include_metadata and 'metadata' in res_cellphonedb:
        metadata_df = res_cellphonedb['metadata'].copy()
        
        # The metadata index is a MultiIndex with (ligand, receptor) tuples
        # Convert it to a regular column for merging
        metadata_df['lr_pair'] = metadata_df.index.to_list()
        metadata_df = metadata_df.reset_index(drop=True)
        
        # Now merge on the lr_pair column
        long_df = long_df.merge(
            metadata_df,
            on='lr_pair',
            how='left'
        )
        
        # Drop the temporary lr_pair column
        long_df = long_df.drop(columns=['lr_pair'])
    else:
        # Drop the temporary lr_pair column if metadata not included
        long_df = long_df.drop(columns=['lr_pair'])
    
    # Sort by p-value for better readability
    long_df = long_df.sort_values('pval').reset_index(drop=True)
    
    # Save if requested
    if output_file:
        long_df.to_csv(output_file, index=False)
        print(f"Converted {len(pvalues_df.index)} interactions x {len(pvalues_df.columns)} cell pairs")
        print(f"Filtered to {len(long_df)} rows with p-value < {pval_threshold}")
        print(f"Saved to {output_file}")
        
        # Check for many zero p-values
        if not long_df.empty:
            n_zeros = (long_df['pval'] == 0.0).sum()
            if n_zeros > len(long_df) * 0.1:  # More than 10% are zeros
                print(f"Note: {n_zeros}/{len(long_df)} ({100*n_zeros/len(long_df):.1f}%) p-values are 0.0")
                print("      This is normal for strong interactions with n_perms=100.")
    
    return long_df


def merge_cci_results(cellphonedb_df, cellchat_df, suffixes=('_cpdb', '_cellchat')):
    """
    Merge CellPhoneDB and CellChat results using outer join (union)
    with Cauchy combination of p-values
    
    Parameters:
    -----------
    cellphonedb_df : pd.DataFrame
        CellPhoneDB results with columns [source, target, ligand, receptor, pval, ...]
    cellchat_df : pd.DataFrame
        CellChat results with columns [source, target, ligand, receptor, pval, ...]
    suffixes : tuple
        Suffixes for overlapping columns from each method (default: ('_cpdb', '_cellchat'))
        
    Returns:
    --------
    pd.DataFrame : Merged results with all interactions from both methods and combined p-values
    """
    
    # Define key columns for merging
    key_columns = ['source', 'target', 'ligand', 'receptor']
    
    # Outer join based on source, target, ligand, receptor
    merged_results = pd.merge(
        cellphonedb_df,
        cellchat_df,
        on=key_columns,
        how='outer',
        suffixes=suffixes,
        indicator=True  # Shows which dataset each row came from
    )
    
    # Check the source of each interaction
    merged_results['data_source'] = merged_results['_merge'].map({
        'left_only': 'CellPhoneDB_only',
        'right_only': 'CellChat_only',
        'both': 'Both'
    })
    
    # Drop the _merge column
    merged_results = merged_results.drop('_merge', axis=1)
    
    # Add combined p-value using Cauchy combination
    # Check if p-value columns exist
    pval_cpdb_col = f'pval{suffixes[0]}'
    pval_cellchat_col = f'pval{suffixes[1]}'
    
    # Initialize combined p-value column
    merged_results['pval_combined'] = np.nan
    
    # For each row, calculate combined p-value
    for idx in merged_results.index:
        if merged_results.loc[idx, 'data_source'] == 'Both':
            # Both methods have p-values - combine them
            pval_cpdb = merged_results.loc[idx, pval_cpdb_col]
            pval_cellchat = merged_results.loc[idx, pval_cellchat_col]
            
            # Collect non-NaN p-values
            pvals = []
            if pd.notna(pval_cpdb):
                pvals.append(pval_cpdb)
            if pd.notna(pval_cellchat):
                pvals.append(pval_cellchat)
            
            # Apply Cauchy combination if we have p-values
            if pvals:
                merged_results.loc[idx, 'pval_combined'] = cauchy_combination(pvals)
                
        elif merged_results.loc[idx, 'data_source'] == 'CellPhoneDB_only':
            # Only CellPhoneDB has p-value
            if pval_cpdb_col in merged_results.columns:
                merged_results.loc[idx, 'pval_combined'] = merged_results.loc[idx, pval_cpdb_col]
                
        elif merged_results.loc[idx, 'data_source'] == 'CellChat_only':
            # Only CellChat has p-value
            if pval_cellchat_col in merged_results.columns:
                merged_results.loc[idx, 'pval_combined'] = merged_results.loc[idx, pval_cellchat_col]
    
    # Sort by key columns
    merged_results = merged_results.sort_values(['data_source', 'pval_combined'], ascending=[False, True]) 
    
    return merged_results


def cluster_medians_to_long(cluster_medians_df, output_file=None):
    """
    Convert cluster_medians DataFrame to long-form DataFrame.

    Parameters:
    -----------
    cluster_medians_df : pd.DataFrame or dict
        DataFrame with clusters as index and celltypes as columns containing p-values,
        or a dictionary that needs to be converted
    output_file : str, optional
        Path to save the resulting CSV file

    Returns:
    --------
    pd.DataFrame : Long-form DataFrame with columns [cluster, celltype, pval]
    """
    result = []

    # Handle if it's a dictionary with a single DataFrame
    if isinstance(cluster_medians_df, dict):
        # If it's a dict, assume it contains the DataFrame we need
        if 'cluster_medians' in cluster_medians_df:
            cluster_medians_df = cluster_medians_df['cluster_medians']
        else:
            # Get the first DataFrame value from the dict
            cluster_medians_df = list(cluster_medians_df.values())[0]

    # Now handle the DataFrame structure
    if isinstance(cluster_medians_df, pd.DataFrame):
        # Iterate through rows (clusters) and columns (celltypes)
        for cluster in cluster_medians_df.index:
            for celltype in cluster_medians_df.columns:
                pval = cluster_medians_df.loc[cluster, celltype]
                result.append({
                    'cluster': cluster,
                    'celltype': celltype,
                    'pval': pval
                })
    elif isinstance(cluster_medians_df, pd.Series):
        # If it's a Series, use the index and values
        for idx, pval in cluster_medians_df.items():
            # Try to split the index if it contains both cluster and celltype info
            if isinstance(idx, tuple) and len(idx) == 2:
                result.append({
                    'cluster': idx[0],
                    'celltype': idx[1],
                    'pval': pval
                })
            else:
                # Assume index is celltype and series name is cluster
                result.append({
                    'cluster': cluster_medians_df.name if cluster_medians_df.name else 'unknown',
                    'celltype': idx,
                    'pval': pval
                })

    # Create DataFrame
    long_df = pd.DataFrame(result)

    # Sort by cluster and p-value
    if not long_df.empty:
        long_df = long_df.sort_values(['cluster', 'pval']).reset_index(drop=True)

    # Save if requested
    if output_file and not long_df.empty:
        long_df.to_csv(output_file, index=False)
        print(f"Saved {len(long_df)} cluster-celltype combinations to {output_file}")

    return long_df


def cluster_medians_to_long_full(cluster_medians_df, fdr_df, output_file=None):
    """
    Convert cluster_medians and fdr DataFrames to combined long-form DataFrame.

    Parameters:
    -----------
    cluster_medians_df : pd.DataFrame
        DataFrame with clusters as index and celltypes as columns containing median values
    fdr_df : pd.DataFrame
        DataFrame with clusters as index and celltypes as columns containing p-values
    output_file : str, optional
        Path to save the resulting CSV file

    Returns:
    --------
    pd.DataFrame : Long-form DataFrame with columns [cluster, celltype, cluster_medians, pval]
    """
    # Validation checks
    if not isinstance(cluster_medians_df, pd.DataFrame) or not isinstance(fdr_df, pd.DataFrame):
        raise ValueError("Both inputs must be pandas DataFrames")

    # Convert cluster_medians to long format using melt
    # Get the index name, or use 'cluster' if None
    cluster_medians_reset = cluster_medians_df.reset_index()
    index_col = cluster_medians_reset.columns[0]

    medians_long = cluster_medians_reset.melt(
        id_vars=index_col,
        var_name='celltype',
        value_name='cluster_medians'
    )
    medians_long.rename(columns={index_col: 'cluster'}, inplace=True)

    # Ensure cluster_medians column is numeric
    medians_long['cluster_medians'] = pd.to_numeric(medians_long['cluster_medians'], errors='coerce')

    # Convert fdr to long format using melt
    fdr_reset = fdr_df.reset_index()
    index_col = fdr_reset.columns[0]

    fdr_long = fdr_reset.melt(
        id_vars=index_col,
        var_name='celltype',
        value_name='pval'
    )
    fdr_long.rename(columns={index_col: 'cluster'}, inplace=True)

    # Ensure pval column is numeric (float) to prevent comparison errors
    fdr_long['pval'] = pd.to_numeric(fdr_long['pval'], errors='coerce')

    # Merge the two DataFrames
    long_df = pd.merge(
        medians_long,
        fdr_long,
        on=['cluster', 'celltype'],
        how='inner'
    )

    # Ensure numeric columns are properly typed after merge (safety measure)
    long_df['cluster_medians'] = pd.to_numeric(long_df['cluster_medians'], errors='coerce')
    long_df['pval'] = pd.to_numeric(long_df['pval'], errors='coerce')

    # Check if merge resulted in data loss
    expected_rows = len(cluster_medians_df.index) * len(cluster_medians_df.columns)
    if len(long_df) < expected_rows:
        logger.warning(f"Merged DataFrame has {len(long_df)} rows, expected {expected_rows}. "
                      f"Some cluster-celltype combinations may not match between the two inputs.")

    # Sort by cluster and p-value
    if not long_df.empty:
        long_df = long_df.sort_values(['cluster', 'pval']).reset_index(drop=True)

    # Save if requested
    if output_file and not long_df.empty:
        long_df.to_csv(output_file, index=False)
        print(f"Saved {len(long_df)} cluster-celltype combinations to {output_file}")

    return long_df


def commot_pvals_to_long(res_p, res_score, pathway_names, pval_threshold=0.05, output_file=None):
    """
    Convert COMMOT results to long format matching CellPhoneDB output structure
    
    Parameters:
    -----------
    res_p : list of pd.DataFrame
        List of p-value matrices from COMMOT analysis
        # NOTE!! row: source, column: target
    res_score : list of pd.DataFrame  
        List of communication score matrices from COMMOT analysis
    pathway_names : list of str
        List of pathway names in "Ligand^Receptor" format
    pval_threshold : float
        Only include interactions with p-value < threshold (default: 0.05)
    output_file : str, optional
        Output CSV filename
        
    Returns:
    --------
    pd.DataFrame with columns: source, target, ligand, receptor, mean, pval
    """
    
    # Validation checks
    if len(res_p) != len(res_score):
        raise ValueError(f"Length mismatch: res_p has {len(res_p)} matrices, res_score has {len(res_score)}")
    
    if len(res_p) != len(pathway_names):
        raise ValueError(f"Length mismatch: {len(res_p)} matrices but {len(pathway_names)} pathway names")
    
    result = []
    
    # Process each pathway
    for idx, pathway_name in enumerate(pathway_names):
        # Parse ligand and receptor from pathway name
        if '^' in pathway_name:
            parts = pathway_name.split('^')
            ligand = parts[0]
            receptor = parts[1] if len(parts) > 1 else ''
        else:
            # Fallback for other formats (underscore separated)
            parts = pathway_name.split('_')
            ligand = parts[0] if len(parts) > 0 else pathway_name
            receptor = '_'.join(parts[1:]) if len(parts) > 1 else ''
        
        # Get the corresponding matrices
        pval_matrix = res_p[idx]
        score_matrix = res_score[idx]
        
        # Check if matrices are DataFrames
        if not isinstance(pval_matrix, pd.DataFrame) or not isinstance(score_matrix, pd.DataFrame):
            logger.warning(f"Skipping pathway {pathway_name}: matrices are not DataFrames")
            continue
        
        # Verify matrix shapes match
        if pval_matrix.shape != score_matrix.shape:
            logger.warning(f"Skipping pathway {pathway_name}: shape mismatch between p-value and score matrices")
            continue
        
        # Verify indices and columns match
        if not pval_matrix.index.equals(score_matrix.index) or not pval_matrix.columns.equals(score_matrix.columns):
            logger.warning(f"Skipping pathway {pathway_name}: index/column mismatch between matrices")
            continue
        
        # Extract cell type names
        source_celltypes = pval_matrix.index.tolist()
        target_celltypes = pval_matrix.columns.tolist()
        
        # Iterate through all source-target combinations
        for source in source_celltypes:
            for target in target_celltypes:
                # Get p-value and score
                pval = pval_matrix.loc[source, target]
                mean = score_matrix.loc[source, target]
                
                # Apply p-value filtering and check for NaN
                if pd.notna(pval) and pval < pval_threshold:
                    result.append({
                        'source': source,
                        'target': target,
                        'ligand': ligand,
                        'receptor': receptor,
                        'mean': mean,
                        'pval': pval
                    })
    
    # Create DataFrame
    long_df = pd.DataFrame(result)
    
    if long_df.empty:
        print(f"No interactions found with p-value < {pval_threshold}")
        return long_df
    
    # Sort by p-value for consistency with CellPhoneDB functions
    long_df = long_df.sort_values('pval').reset_index(drop=True)
    
    # Save if requested
    if output_file:
        long_df.to_csv(output_file, index=False)
        print(f"Converted {len(pathway_names)} pathways with {len(source_celltypes)} x {len(target_celltypes)} cell pairs")
        print(f"Filtered to {len(long_df)} rows with p-value < {pval_threshold}")
        print(f"Saved to {output_file}")
        
        # Check for many zero p-values
        n_zeros = (long_df['pval'] == 0.0).sum()
        if n_zeros > len(long_df) * 0.1:  # More than 10% are zeros
            print(f"Note: {n_zeros}/{len(long_df)} ({100*n_zeros/len(long_df):.1f}%) p-values are 0.0")
            print("      This is normal for strong interactions with low n_permutations.")
    
    return long_df


def merge_liana_with_cci(filtered_df, sig_liana):
    """
    Merge LIANA+ global interaction results with celltype-specific CCI results
    
    Parameters:
    -----------
    filtered_df : pd.DataFrame
        Celltype-specific interactions with columns [source, target, ligand, receptor, ...]
        (e.g., filtered merged results from CellPhoneDB/CellChat)
    sig_liana : pd.DataFrame
        LIANA+ significant interactions from lrdata.var with global spatial patterns
        Index contains interaction names (e.g., "LIGAND^RECEPTOR")
        
    Returns:
    --------
    pd.DataFrame : Merged results with both celltype-specific and global spatial information
    """
    
    # Create a copy to avoid modifying original
    result_df = filtered_df.copy()
    
    # Parse sig_liana index to extract ligand and receptor
    liana_interactions = {}
    for interaction in sig_liana.index:
        if '^' in interaction:
            parts = interaction.split('^')
            ligand = parts[0]
            receptor = parts[1] if len(parts) > 1 else ''
        else:
            # Handle other formats (e.g., underscore separated)
            parts = interaction.split('_')
            ligand = parts[0] if len(parts) > 0 else interaction
            receptor = '_'.join(parts[1:]) if len(parts) > 1 else ''
        
        # Store LIANA data by ligand-receptor pair
        key = (ligand, receptor)
        liana_interactions[key] = {
            'morans': sig_liana.loc[interaction, 'morans'] if 'morans' in sig_liana.columns else np.nan,
            'morans_pvals': sig_liana.loc[interaction, 'morans_pvals'] if 'morans_pvals' in sig_liana.columns else np.nan,
            'interaction_name': interaction
        }
    
    # Add LIANA information to filtered_df
    result_df['morans'] = np.nan
    result_df['morans_pvals'] = np.nan
    result_df['liana_interaction'] = ''
    result_df['has_spatial_pattern'] = False
    
    # For each row in filtered_df, check if interaction exists in sig_liana
    for idx in result_df.index:
        ligand = result_df.loc[idx, 'ligand']
        receptor = result_df.loc[idx, 'receptor']
        key = (ligand, receptor)
        
        if key in liana_interactions:
            # Add LIANA data
            result_df.loc[idx, 'morans'] = liana_interactions[key]['morans']
            result_df.loc[idx, 'morans_pvals'] = liana_interactions[key]['morans_pvals']
            result_df.loc[idx, 'liana_interaction'] = liana_interactions[key]['interaction_name']
            result_df.loc[idx, 'has_spatial_pattern'] = True
    
    # Sort by has_spatial_pattern (True first), then by combined p-value or pval
    if 'pval_combined' in result_df.columns:
        sort_col = 'pval_combined'
    elif 'pval' in result_df.columns:
        sort_col = 'pval'
    else:
        sort_col = None
    
    if sort_col:
        result_df = result_df.sort_values(
            ['has_spatial_pattern', sort_col],
            ascending=[False, True]
        ).reset_index(drop=True)
    
    return result_df

def make_unique_by_interaction(df, interaction_col='interaction', source_col='source'):
    """
    Make DataFrame unique by interaction, concatenating sources.
    
    Parameters:
    -----------
    df : pd.DataFrame
        Input dataframe
    interaction_col : str
        Column name for interactions
    source_col : str
        Column name for sources to concatenate
    
    Returns:
    --------
    pd.DataFrame : Unique dataframe
    """

    # Check if columns exist
    if interaction_col not in df.columns:
        raise ValueError(f"Column '{interaction_col}' not found")
    if source_col not in df.columns:
        raise ValueError(f"Column '{source_col}' not found")

    # Group and aggregate
    result = df.groupby(interaction_col).agg({
        source_col: lambda x: ';'.join(x.dropna().astype(str).unique())
    })

    # Add other columns if they exist
    for col in df.columns:
        if col not in [interaction_col, source_col]:
            if col not in result.columns:
                if df[col].dtype == 'object':
                    result[col] = df.groupby(interaction_col)[col].apply(
                        lambda x: ';'.join(x.dropna().astype(str).unique()) if
len(x.dropna().unique()) > 1 else x.iloc[0]
                    )
                else:
                    result[col] = df.groupby(interaction_col)[col].first()

    return result.reset_index()




def make_lrdb_commot(anno_sig_liana, interest_pathways):
    sel_pathway_filtereds = []
    for pathway in interest_pathways:
        sel_pathway_filtered = anno_sig_liana[anno_sig_liana['progeny'].str.contains(pathway, na=False)].copy()

        sel_pathway_filtered['pathway'] = pathway
        sel_pathway_filtered = sel_pathway_filtered[['ligand', 'receptor', 'pathway']]
        sel_pathway_filtereds.append(sel_pathway_filtered)

    result = pd.concat(sel_pathway_filtereds, ignore_index=True)

    # 결과 확인
    print(f"Total rows: {len(result)}")
    print(f"\nPathway counts:")
    print(result['pathway'].value_counts())

    # 중복 확인 (같은 ligand-receptor가 여러 pathway에 속하는 경우)
    duplicates = result.groupby(['ligand', 'receptor']).size()
    multi_pathway_pairs = duplicates[duplicates > 1]
    if len(multi_pathway_pairs) > 0:
        print(f"\n{len(multi_pathway_pairs)} ligand-receptor pairs belong to multiple pathways")

    return(result)
from typing import Literal

import scanpy as sc
import pandas as pd

import liana as li
import omnipath as op


def get_lr_database(organism: Literal['human', 'mouse'] = 'human'):
    """
    Get ligand-receptor database for the specified organism.

    Args:
        organism: 'human' or 'mouse'. For mouse, human LR pairs are translated
                  using HCOP orthologs.

    Returns:
        DataFrame with 'ligand' and 'receptor' columns
    """
    # Import human LR database from OmniPath
    inter_db = op.interactions.import_intercell_network(
        interactions_params={'license': 'commercial'},
        transmitter_params={'database': ['CellChatDB', 'CellPhoneDB', 'connectomeDB2020', 'CellTalkDB']},
        receiver_params={'database': ['CellChatDB', 'CellPhoneDB', 'connectomeDB2020', 'CellTalkDB']},
    )
    inter_db = inter_db.rename(columns={'genesymbol_intercell_source': 'ligand', 'genesymbol_intercell_target': 'receptor'})
    inter_db = inter_db[['ligand', 'receptor']].drop_duplicates()

    if organism == 'mouse':
        print("   Translating human LR database to mouse orthologs...")
        # Get human-mouse ortholog mapping from HCOP
        map_df = li.rs.get_hcop_orthologs(
            url='https://ftp.ebi.ac.uk/pub/databases/genenames/hcop/human_mouse_hcop_fifteen_column.txt.gz',
            columns=['human_symbol', 'mouse_symbol'],
            # HCOP integrates multiple resources, filter for confidence
            min_evidence=3
        )
        # Rename columns for translation
        map_df = map_df.rename(columns={'human_symbol': 'source', 'mouse_symbol': 'target'})

        # Translate LR pairs to mouse
        inter_db = li.rs.translate_resource(
            inter_db,
            map_df=map_df,
            columns=['ligand', 'receptor'],
            replace=True,
            # Only keep mappings that don't map to more than 1 mouse gene
            one_to_many=1
        )
        # Remove duplicates after translation
        inter_db = inter_db[['ligand', 'receptor']].drop_duplicates()
        print(f"   Translated LR database: {len(inter_db)} pairs")

    return inter_db


def run_liana_bivariate(adata, organism: Literal['human', 'mouse'] = 'human', n_perms_bivariate=1000):
    """
    Run LIANA+ bivariate analysis only (without NMF).

    Use this function for multi-sample workflows where bivariate is run per-sample
    and NMF is run on concatenated results.

    Args:
        adata: AnnData object with spatial transcriptomics data (must have spatial neighbors computed)
        organism: 'human' or 'mouse' for LR database selection (default: 'human')
        n_perms_bivariate: Number of permutations for p-value calculation (default: 1000)

    Returns:
        LR data object with bivariate results (no NMF factors)
    """
    adata_liana = adata.copy()

    # Get LR database for the specified organism
    inter_db = get_lr_database(organism=organism)

    lrdata = li.mt.bivariate(adata_liana,
                resource=inter_db,
                local_name='cosine',
                global_name="morans",
                n_perms=n_perms_bivariate,
                mask_negatives=False,
                add_categories=True,
                use_raw=False,
                verbose=True,
                seed=12345
                )

    # Copy spatial information from original adata to lrdata
    # This is required for sc.pl.spatial() to work correctly
    if 'spatial' in adata_liana.obsm:
        lrdata.obsm['spatial'] = adata_liana.obsm['spatial']
    if 'spatial' in adata_liana.uns:
        lrdata.uns['spatial'] = adata_liana.uns['spatial']

    return lrdata


def _estimate_n_components(lrdata, k_range=range(1, 11), max_iter=200):
    """
    Estimate optimal number of NMF components using elbow method.

    This is a wrapper around LIANA's estimate_elbow that handles the case
    where elbow detection fails (returns None).

    Args:
        lrdata: LR data object from run_liana_bivariate
        k_range: Range of component numbers to test (default: 1-10)
        max_iter: Maximum iterations for NMF (default: 200)

    Returns:
        int: Estimated number of components (default: 5 if elbow detection fails)
    """
    from sklearn.decomposition import NMF
    import numpy as np

    try:
        import kneed
    except ImportError:
        print("   Warning: kneed not installed, using default n_components=5")
        return 5

    X = lrdata.X
    if hasattr(X, 'toarray'):
        X = X.toarray()

    # Calculate reconstruction errors for each k
    errors = []
    for k in k_range:
        nmf = NMF(n_components=k, random_state=0, max_iter=max_iter)
        W = nmf.fit_transform(X)
        H = nmf.components_
        Xhat = np.dot(W, H)
        error = np.mean(np.abs(X - Xhat))
        errors.append(error)

    # Find elbow point
    kneedle = kneed.KneeLocator(
        x=list(k_range),
        y=errors,
        direction='decreasing',
        curve='convex',
        interp_method='interp1d',
        S=1
    )

    n_components = kneedle.knee

    # Handle case where elbow detection fails
    if n_components is None:
        # Use default value or middle of range
        n_components = 5
        print(f"   Warning: Elbow detection failed, using default n_components={n_components}")
    else:
        print(f"   Estimated optimal n_components={n_components} using elbow method")

    return n_components


def run_liana_nmf(lrdata, max_iter_nmf=200, n_components=None):
    """
    Run NMF on LIANA+ bivariate results.

    Use this function after run_liana_bivariate, especially for multi-sample
    workflows where NMF should be run on concatenated data from all samples.

    Args:
        lrdata: LR data object from run_liana_bivariate (or concatenated lrdata)
        max_iter_nmf: Maximum iterations for NMF (default: 200)
        n_components: Number of NMF components. If None, uses custom elbow
                      detection that handles edge cases gracefully (default: None)

    Returns:
        LR data object with NMF factors added (modified in-place)
    """
    # If n_components not specified, use custom elbow detection
    # This avoids the plotnine error when LIANA's internal _plot_elbow()
    # is called with n_components=None (which can fail if elbow detection returns None)
    if n_components is None:
        n_components = _estimate_n_components(lrdata, max_iter=max_iter_nmf)

    # Now call li.multi.nmf with explicit n_components to skip internal elbow plot
    li.multi.nmf(lrdata, n_components=n_components, inplace=True, random_state=0, max_iter=max_iter_nmf, verbose=False)
    return lrdata


def run_liana(adata, organism: Literal['human', 'mouse'] = 'human', n_perms_bivariate=1000, max_iter_nmf=200):
    """
    Run LIANA+ bivariate analysis with NMF (single sample workflow).

    This is a convenience wrapper that runs both bivariate and NMF for single-sample data.
    For multi-sample data, use run_liana_bivariate per sample, concatenate, then run_liana_nmf.

    Args:
        adata: AnnData object with spatial transcriptomics data
        organism: 'human' or 'mouse' for LR database selection (default: 'human')
        n_perms_bivariate: Number of permutations for p-value calculation (default: 1000)
        max_iter_nmf: Maximum iterations for NMF (default: 200)

    Returns:
        LR data object with NMF results
    """
    lrdata = run_liana_bivariate(adata, organism=organism, n_perms_bivariate=n_perms_bivariate)
    run_liana_nmf(lrdata, max_iter_nmf=max_iter_nmf)
    return lrdata

# def ori_run_liana(adata, n_perms_bivariate = 1000, max_iter_nmf=200):

#   adata_liana = adata.copy()
#   inter_db = op.interactions.import_intercell_network(
#       interactions_params={'license':'commercial'},
#       transmitter_params={'database':['CellChatDB', 'CellPhoneDB', 'connectomeDB2020', 'CellTalkDB']},
#       receiver_params={'database':['CellChatDB', 'CellPhoneDB', 'connectomeDB2020', 'CellTalkDB']},
#   )
#   inter_db = inter_db.rename(columns={'genesymbol_intercell_source':'ligand', 'genesymbol_intercell_target':'receptor'})
#   inter_db = inter_db[['ligand', 'receptor', 'references']].drop_duplicates()
#   inter_db

#   lrdata = li.mt.bivariate(adata_liana,
#                 # resource_name='consensus', # NOTE: uses HUMAN gene symbols!
#                 resource = inter_db,
#                 local_name='cosine', # Name of the function
#                 global_name="morans", # Name global function
#                 n_perms=n_perms_bivariate, # Number of permutations to calculate a p-value
#                 mask_negatives=False, # Whether to mask LowLow/NegativeNegative interactions
#                 add_categories=True, # Whether to add local categories to the results
#                 use_raw=False,
#                 verbose=True,
#                 seed=12345
#                 )
#   li.multi.nmf(lrdata, n_components=None, inplace=True, random_state=0, max_iter=max_iter_nmf, verbose=True)
#   return(lrdata)
import numpy as np
import pandas as pd
import scanpy as sc
import squidpy as sq
import omnipath as op

import liana as li
from matplotlib import pyplot as plt

from utils.utils import *


# 1.CellPhoneDB
def run_cellphonedb(adata_sq, cluster_key, th_mim_mean_cellphonedb = 2, save=False, n_perms=1000, p_th = 0.05, save_path='res'):
    """
    Run CellPhoneDB analysis for cell-cell interaction inference.
    
    Parameters:
    -----------
    adata_sq : AnnData
        Annotated data object with spatial information
    cluster_key : str
        Key in adata.obs containing cluster/celltype information
    save : bool
        Whether to save significant results to CSV (default: False)
    save_fig : bool
        Whether to save visualization figure (default: False)
    n_perms : int
        Number of permutations for statistical testing (default: 10000)
    use_raw : bool
        Whether to use raw data for analysis (default: False)
        
    Returns:
    --------
    tuple : (res_cellphonedb, res_cellphonedb_simple)
        res_cellphonedb: Full results with metadata
        res_cellphonedb_simple: Simplified results with key columns only
    """

    sq.gr.ligrec(
        adata_sq,
        n_perms=n_perms,
        cluster_key=cluster_key,
        use_raw=False,
        seed = 12345,
        interactions_params={'license':'commercial'},
        transmitter_params={'database':['CellChatDB', 'CellPhoneDB', 'connectomeDB2020', 'CellTalkDB']},
        receiver_params={'database':['CellChatDB', 'CellPhoneDB', 'connectomeDB2020', 'CellTalkDB']},
    )
    raw_res_cellphonedb = adata_sq.uns['celltype_niche_ligrec']

    # sig_cellphonedb = cellphonedb_pvals_to_long(
    #     raw_res_cellphonedb, 
    #     pval_threshold=p_th, 
    #     include_metadata=True
    # )
    # sig_cellphonedb.to_csv("res/cellphonedb/cellphomnedb.csv")
    # sig_cellphonedb_simple = sig_cellphonedb[['source', 'target', 'ligand', 'receptor','pval']]
    # sig_cellphonedb_simple
    
    sig_cellphonedb_simple = cellphonedb_pvals_to_long_simple(
        raw_res_cellphonedb["pvalues"],
        pval_threshold=p_th
    )
    
    if save:
        sig_cellphonedb_simple.to_csv(f'{save_path}/sig_cellphonedb.csv')
        print(f"Saved {len(sig_cellphonedb_simple)} significant interactions to {save_path}/sig_cellphonedb.csv")


    sq.pl.ligrec(
        adata_sq,
        cluster_key=cluster_key,
        # source_groups=list(set(adata_sq.obs['celltype_niche'])),
        # target_groups=list(set(adata_sq.obs['celltype_niche'])),
        means_range=(th_mim_mean_cellphonedb, np.inf),
        pvalue_threshold=p_th,
        dendrogram='both',
        alpha=1e-4,
        swap_axes=False,
        # dpi=300,
        # save=f'{save_path}/cellphonedb.png'
    )
    plt.savefig(f'{save_path}/cellphonedb.png', dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Saved CellPhoneDB figure to {save_path}/cellphonedb.png")
    
    return sig_cellphonedb_simple



# 2.LIANA+
def run_liana(adata_liana, save=False, n_perms=1000, p_th = 0.05, th_moransr = 0.05, th_min_mean_moransr = 1, save_path='res'):
    """
    Run LIANA+ for spatial cell-cell interaction analysis with spatial patterns.
    
    Parameters:
    -----------
    adata_liana : AnnData
        Annotated data object with spatial information
    cluster_key : str
        Key in adata.obs containing cluster/celltype information
    save : bool
        Whether to save significant results to CSV (default: False)
    use_raw : bool
        Whether to use raw data for analysis (default: False)
    n_perms : int
        Number of permutations for statistical testing (default: 100)
        
    Returns:
    --------
    pd.DataFrame : LIANA results sorted by Moran's I statistic
    """

    inter_db = op.interactions.import_intercell_network(
        interactions_params={'license':'commercial'},
        transmitter_params={'database':['CellChatDB', 'CellPhoneDB', 'connectomeDB2020', 'CellTalkDB']},
        receiver_params={'database':['CellChatDB', 'CellPhoneDB', 'connectomeDB2020', 'CellTalkDB']},
    )

    inter_db = inter_db.rename(columns={'genesymbol_intercell_source':'ligand', 'genesymbol_intercell_target':'receptor'})
    inter_db = inter_db[['ligand', 'receptor', 'references']].drop_duplicates()
    inter_db


    # run LIANA
    lrdata = li.mt.bivariate(adata_liana,
                    # resource_name='consensus', # NOTE: uses HUMAN gene symbols!
                    resource = inter_db,
                    local_name='cosine', # Name of the function
                    global_name="morans", # Name global function
                    n_perms=n_perms, # Number of permutations to calculate a p-value
                    mask_negatives=False, # Whether to mask LowLow/NegativeNegative interactions
                    add_categories=True, # Whether to add local categories to the results
                    use_raw=False,
                    verbose=True
                    )
    lrdata.write_h5ad(f'{save_path}/lrdata.h5ad')
    
    # sig filtering and sorting
    res_liana = lrdata.var.sort_values("morans", ascending=False)
    sig_liana = res_liana.query(f'morans > {th_moransr} & mean < {th_min_mean_moransr} & morans_pvals < {p_th}')

    # if you want to save the sig results
    if save:
        sig_liana.to_csv(f'{save_path}/sig_liana.csv')
        print(f"Saved {len(sig_liana)} significant LIANA interactions to res/sig_liana.csv")


    # save moran's R plot
    fig, ax = plt.subplots(figsize=(6, 6))

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
            alpha=0.8, 
            color='red', 
            s=50,
            label='sig_liana')

    # Add threshold lines
    ax.axvline(x=th_moransr, color='black', linestyle='--', alpha=1, label=f'Morans threshold ({th_moransr})')
    ax.axhline(y=th_min_mean_moransr, color='blue', linestyle='--', alpha=1, label=f'Mean threshold ({th_min_mean_moransr})')

    ax.set_xlabel('Moran’s R', fontsize=12)
    ax.set_ylabel('Mean', fontsize=12)
    ax.set_title('Ligand-Receptor Interactions', fontsize=14)
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig("res/MoransR.png", dpi=300) 

    plt.show()

    return sig_liana


# def cci_annotation(res_cellphonedb_simple, res_liana, p_th = 0.05, save=True):



def summary_cci(res_cellphonedb_simple, res_liana, p_th = 0.05, save=True, save_path='res'):
    """
    Merge and summarize CellPhoneDB and LIANA results to identify
    spatially organized cell-cell interactions.
    
    Parameters:
    -----------
    res_cellphonedb_simple : pd.DataFrame
        Simplified CellPhoneDB results with columns [source, target, ligand, receptor, pval]
    res_liana : pd.DataFrame
        LIANA results with spatial pattern information (Moran's R statistics)
    save : bool
        Whether to save spatially organized interactions to CSV (default: True)
        
    Returns:
    --------
    pd.DataFrame : Spatially organized interactions sorted by Moran's R statistic
    """
    # 3. Merge the dataframes
    combined_df = merge_liana_with_cci(res_cellphonedb_simple, res_liana)

    spatially_organized = combined_df[combined_df['has_spatial_pattern'] == True]
    spatially_organized = spatially_organized.sort_values("morans", ascending=False)

    sig_spatially_organized = spatially_organized.query(f'pval < {p_th} & morans > 0 & morans_pvals < {p_th}')


    if save:
        sig_spatially_organized.to_csv(f'{save_path}/sig_liana_CCI.csv')
        print(f"Saved {len(spatially_organized)} spatially organized interactions to res/sig_liana_CCI.csv")
    
    return sig_spatially_organized
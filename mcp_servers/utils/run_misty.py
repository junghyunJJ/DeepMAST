import sys

import scanpy as sc
import decoupler as dc
import plotnine as p9
import liana as li
import pandas as pd
import anndata as ad

from liana.method import MistyData, genericMistyData, lrMistyData
from liana.method.sp import RandomForestModel, LinearModel, RobustLinearModel

from utils.run_decoupler import sp_enrich


def sp_relation(adata, cluster_key, organism='human', geneset='progeny', model='rf', celltype_key=None, min_n=5):
    """
    Compute spatial relationships between cell types and pathways using MISTy.

    Supports two data types:
    1. Spot-based (Visium) with deconvolution: Uses adata.obsm['compositions']
    2. Single-cell resolution (MERFISH/Xenium): Uses adata.obs[celltype_key]

    Args:
        adata: AnnData object with spatial data
        cluster_key: Key in adata.obs containing cluster annotations
        organism: 'human' or 'mouse' for geneset selection
        geneset: 'progeny' or 'hallmark' pathway geneset
        model: 'rf' for Random Forest, 'linear' for Linear regression
        celltype_key: Key in adata.obs containing cell type annotations (for single-cell data).
                      If None, will use adata.obsm['compositions'] (Visium).
        min_n: Minimum number of targets per source (pathway) required for pathway enrichment.
               Default is 5. For single-cell resolution data with limited gene panels
               (e.g., STARmap, MERFISH), use lower values like 1-3.

    Returns:
        MISTy object with computed interactions
    """
    # Determine data type and create cell type composition AnnData
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

        # Create AnnData for compositions (similar to li.ut.obsm_to_adata output)
        comps = ad.AnnData(
            X=df_props.values,
            obs=adata.obs.copy(),
            var=pd.DataFrame(index=df_props.columns)
        )
        # Copy spatial coordinates
        if 'spatial' in adata.obsm:
            comps.obsm['spatial'] = adata.obsm['spatial']

        print(f"   Detected {df_props.shape[1]} cell types from '{celltype_key}'")

    elif has_compositions:
        # Spot-based data: use compositions from obsm
        print("   Using spot-based mode with obsm['compositions']")
        comps = li.ut.obsm_to_adata(adata, 'compositions')
        print(f"   Detected {comps.n_vars} cell types from compositions")

    else:
        raise ValueError(
            "No cell type data found. Either:\n"
            "  - Provide celltype_key parameter for single-cell data (e.g., celltype_key='sub_level_cell_type')\n"
            "  - Ensure adata.obsm['compositions'] exists for spot-based data"
        )

    # Compute pathway enrichment
    res_sp_enrich = sp_enrich(adata, cluster_key, organism=organism, geneset=geneset, min_n=min_n)

    # Create MISTy model
    misty = genericMistyData(intra=comps, extra=res_sp_enrich, cutoff=0.05, bandwidth=200, n_neighs=6)

    if model == 'rf':
        misty(model=RandomForestModel, n_jobs=-1, verbose=False)
    elif model == 'linear':
        # NOTE: we need to set k_cv=10, seed=1337 parameter
        misty(model=LinearModel, k_cv=10, seed=1337, bypass_intra=False, verbose=False)
    else:
        print('please set the model (rf or linear)')
        sys.exit(1)

    return misty


def plot_sp_relation(misty, row=7, height=5):
  # mp = (
  mp = li.pl.interactions(misty, view='juxta', return_fig=True, figure_size=(row, height))
  #   p9.scale_fill_gradient2(low = "blue", mid = "white", high = "red", midpoint = 0)
  # )
  
  return mp

import anndata as ad
import scanpy as sc
import squidpy as sq
import pandas as pd

from typing import Optional, Literal, List

import glob

def prep_scref(sel_colnames: List['str'], indir: str, savedir: str):
    indir = '/Users/jungj2/Dropbox/Metadata/mcp/sp_enrich_mcp/data/crc/sc_crc.h5ad'
    savedir = '/Users/jungj2/Dropbox/Metadata/mcp/sp_enrich_mcp/data/crc/'
    sel_colnames = ['Patient', 'Level2']

    adata = sc.read_h5ad(indir)
    # counts = pd.DataFrame(adata.layers['counts'].toarray().T)
    counts = pd.DataFrame(adata.X.toarray().T)
    counts.index=adata.var.index
    counts.columns=adata.obs.index
    # counts.to_csv(f'{savedir}/matrix_counts_sc.csv')
    counts.to_parquet(f'{savedir}/matrix_counts_sc.parquet', compression='snappy')
    counts = pd.read_parquet(f'{savedir}/matrix_counts_sc.parquet')


    meta = adata.obs[sel_colnames]
    meta = meta.reset_index()
    meta
    meta.columns = ['barcode','cellType','sampleID']
    meta.to_csv(f'{savedir}/meta_sc.csv')
    
    return None


def prep_10xvisium(df_meta: pd.DataFrame, indir: str, savedir: str):

    # check df_meta
    # Normalize column names: lowercase
    df_meta.columns = df_meta.columns.str.lower()

    # Convert plural to singular if exists
    if 'dataset_names' in df_meta.columns:
        df_meta.rename(columns={'dataset_names': 'dataset_name'}, inplace=True)
    if 'sample_ids' in df_meta.columns:
        df_meta.rename(columns={'sample_ids': 'sample_id'}, inplace=True)
    if 'groups' in df_meta.columns:
        df_meta.rename(columns={'groups': 'group'}, inplace=True)

    # Validate required columns
    required_columns = ['dataset_name', 'sample_id', 'group']
    missing_columns = [col for col in required_columns if col not in df_meta.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns in df_meta: {missing_columns}")


    for dataset_name, sample_id, group_id in zip(df_meta['dataset_name'], df_meta['sample_id'], df_meta['group']):
        print(f"dataset_name:{dataset_name} / sample_id:{sample_id} / group:{group_id}")

        # read visum raw data using "filtered_feature_bc_matrix.h5" pattern
        pattern = f"{indir}/{dataset_name}/*filtered_feature_bc_matrix.h5"
        h5_files = glob.glob(pattern)

        if len(h5_files) == 0:
            print(f"Warning: No h5 file found for {dataset_name}")
            continue
        elif len(h5_files) > 1:
            print(f"Warning: Multiple h5 files found for {dataset_name}, using first one: {h5_files[0]}")

        counts_file = h5_files[0].split('/')[-1]  # Extract filename from path

        adata = sq.read.visium(f"{indir}/{dataset_name}", counts_file=counts_file)
        adata.var_names_make_unique()
        adata.obs['dataset_name']  = dataset_name
        adata.obs['sample_id']  = sample_id
        adata.obs['group_id']  = group_id
        adata.write_h5ad(f'{savedir}/adata_{dataset_name}.h5ad')

        # # save spatial location and counts using matrix format
        # location = pd.DataFrame(adata.obsm['spatial'])
        # location.columns = ['x','y']
        # location.index=adata.obs.index
        # location.to_csv(f'{savedir}/matrix_location_{dataset_name}.csv')

        # counts = pd.DataFrame(adata.X.toarray().T)
        # counts.shape
        # counts.index=adata.var.index
        # counts.columns=adata.obs.index
        # counts.to_csv(f'{savedir}/matrix_counts_{dataset_name}.csv')

        # normalization
        adata.layers['counts'] = adata.X.copy()
        # sc.pp.filter_cells(adata, min_genes=200)
        sc.pp.filter_genes(adata, min_cells=5)
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)

        # NOTE!! we calculate the spatial_neighbors using sq
        # li.ut.spatial_neighbors(adata, bandwidth=150, set_diag=True, cutoff=0.1)
        sq.gr.spatial_neighbors(adata, n_neighs = 6, n_rings = 2)
        adata.write_h5ad(f'{savedir}/n_adata_{dataset_name}.h5ad')

        # adata_liana = adata.copy()
        # lrdata = li.mt.bivariate(adata_liana,
        #                 # resource_name='consensus', # NOTE: uses HUMAN gene symbols!
        #                 resource = inter_db,
        #                 local_name='cosine', # Name of the function
        #                 global_name="morans", # Name global function
        #                 n_perms=n_perms, # Number of permutations to calculate a p-value
        #                 mask_negatives=False, # Whether to mask LowLow/NegativeNegative interactions
        #                 add_categories=True, # Whether to add local categories to the results
        #                 use_raw=False,
        #                 verbose=True,
        #                 seed = 12345
        #                 )
        # lrdatas[sample_id] = lrdata
        # # li.multi.nmf(lrdata, n_components=None, inplace=True, random_state=0, max_iter=200, verbose=True)
        # lrdata.write_h5ad(f'{savedir}/lrdata_{dataset_name}.h5ad')
    return None

# def run_liana_bivariate()



def read_10x_mtx(filename: str) -> ad.AnnData:

  adata = sc.read_10x_mtx(
      filename,  # the directory with the `.mtx` file
      var_names="gene_symbols",  # use gene symbols for the variable names (variables-axis index)
  )
  # 기본 정보 출력
  print("데이터 모양:", adata.shape)
  print(f"관측값 수: {adata.n_obs}, 변수 수: {adata.n_vars}")

  adata.var_names_make_unique()
  adata.var["mt"] = adata.var_names.str.startswith("MT-")
  sc.pp.calculate_qc_metrics(
      adata, qc_vars=["mt"], percent_top=None, log1p=False, inplace=True
  )
  
  return adata


def qc_violin(adata: ad.AnnData):

  print("plot vioin...")
  sc.pl.violin(
    adata,
    ["n_genes_by_counts", "total_counts", "pct_counts_mt"],
    jitter=0.4,
    multi_panel=True,
    save="_qc.png"
  )

  return None


def filtering(adata: ad.AnnData, n_genes_by_counts: int=2500, pct_counts_mt: int=5) -> ad.AnnData:

  adata = adata[adata.obs.n_genes_by_counts < n_genes_by_counts, :]
  adata = adata[adata.obs.pct_counts_mt < pct_counts_mt, :].copy()

  return adata
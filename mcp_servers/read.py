import scanpy as sc
import pandas as pd

from utils.read import prep_10xvisium


def check_csv(
  filename: str,
) -> dict:
  """
  Read CSV file and return column names

  Args:
    filename: path to the CSV file

  Returns:
    dict with column names and row count
  """
  try:
    pd_csv = pd.read_csv(filename)
    return {
      "columns": list(pd_csv.columns),
      "row_count": len(pd_csv)
    }
  except FileNotFoundError:
    return {"error": f"File not found: {filename}"}
  except Exception as e:
    return {"error": str(e)}


def prep_visium(
  in_path: str,
  save_path: str = 'data/',
) -> str:
  """
  Process 10x Visium spatial transcriptomics data

  Reads 10x Visium raw data (filtered_feature_bc_matrix.h5), performs normalization,
  calculates spatial neighbors, and saves processed data as h5ad files and CSV matrices.

  Args:
    meta_csv: Path to metadata CSV file with required columns:
      - dataset_name: Name of the dataset
      - sample_id: Sample identifier
      - group: Group identifier
      Column names will be automatically normalized (lowercase, singular form).
    in_path: Input directory containing 10x Visium raw data folders
    save_path: Output directory for processed files (default: 'data/')

  Returns:
    Success message string

  Output files per dataset:
    - adata_{dataset_name}.h5ad: Raw AnnData with metadata
    - n_adata_{dataset_name}.h5ad: Normalized AnnData with spatial neighbors
    - matrix_location_{dataset_name}.csv: Spatial coordinates
    - matrix_counts_{dataset_name}.csv: Gene expression counts
  """
  df_meta = pd.read_csv(f'{in_path}/df_meta.csv')
  prep_10xvisium(df_meta, indir = in_path, savedir = save_path)
  return f"Successfully processed {len(df_meta)} datasets"


def obs_names_h5ad(
  filename: str, 
) -> list:
  """
  Read .h5ad file and return adata.obs.columns

  Args:
    filename: the directory with the `.h5ad` file

  Returns:
    adata.obs.columns
  """
  adata = sc.read_h5ad(filename)
  
  return list(adata.obs.columns)


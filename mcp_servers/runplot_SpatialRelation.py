import os

from typing import Optional, Literal, List

import scanpy as sc
import decoupler as dc
import liana as li

from utils.run_misty import sp_relation, plot_sp_relation


def runplot_spatial_relationship(
    filename: str,
    cluster_key: str,
    celltype_key: Optional[str] = None,
    organism: Literal['human', 'mouse'] = 'human',
    geneset: Literal['progeny', 'hallmark'] = 'progeny',
    model: Literal['rf', 'liner'] = 'rf',
    view: Literal['juxta', 'para'] = 'juxta',
    min_n: int = 5,
    width: Optional[int] = None,
    height: Optional[int] = None,
    save_path: str = 'res/',
    ) -> None:
    """
    Part 1: Before CCI Analysis - Step 5. Spatial Pathway Enrichment Analysis (MISTy)

    Analyzes spatial relationships between pathway activities (predictors) and cell type
    distributions (targets) using MISTy framework. This analysis quantifies how molecular
    signaling environments (pathways) determine the spatial distribution of specific cell types.

    Core Question:
        "Which molecular signaling environment (pathway) determines the spatial distribution
        of a specific cell type?"

        The target-predictor relationship shows how pathway activity patterns predict the
        spatial localization of different cell types across the tissue.

    MISTy Framework:
        - MISTy: Multiview Intercellular SpaTial modeling framework
        - Tool: LIANA-py (https://liana-py.readthedocs.io/en/latest/notebooks/misty.html)
        - Approach: Machine learning models predict cell type spatial distribution from
          pathway activity in neighboring regions
        - Target: Cell type (the spatial distribution being predicted)
        - Predictor: Pathway activity (the features used for prediction)

    Methodology:
        - Models: Random Forest (default) or Linear regression
        - Geneset: PROGENy (default, 14 pathways) or Hallmark
        - Views:
          * juxta (juxtacrine): Direct cell-cell contact signaling
          * para (paracrine): Diffusion-mediated signaling across distances
        - Feature Importance: Quantifies contribution of each pathway to predicting
          cell type spatial distribution

    Feature Importance Interpretation:
        - Random Forest (rf): Mean decrease in Gini impurity
          Higher importance = pathway is more informative for predicting cell type location
        - Linear (liner): Regression coefficients
          Higher magnitude = stronger association between pathway and cell type distribution

    Workflow Position:
        - Part 1 analysis (before CCI)
        - Step 5: Pathway-celltype relationship identification
        - Independent analysis result
        - Identifies which pathways are associated with specific cell types
        - Complements Step 4 (cluster-pathway) with spatial context
        - Recommended to repeat Part 1 analysis 3-5 times for consistent results

    Supports two data types:
        1. Spot-based (Visium) with deconvolution results in adata.obsm['compositions']
        2. Single-cell resolution (MERFISH/Xenium) with cell type in adata.obs[celltype_key]

    Data Requirements:
        - Uses normalized n_adata.h5ad data
        - For spot-based: Requires adata.obsm['compositions'] (deconvolution results)
        - For single-cell: Requires adata.obs[celltype_key] (cell type annotations)
        - Requires cluster annotations in adata.obs[cluster_key]
        - Requires spatial coordinates in adata.obsm['spatial']

    Args:
        filename (str): Path to the `.h5ad` file containing spatial transcriptomics data
        cluster_key (str): Column name in adata.obs for spatial cluster annotations
        celltype_key (str, optional): Column name in adata.obs containing cell type annotations.
                                       Required for single-cell resolution data (MERFISH, Xenium).
                                       If None, uses adata.obsm['compositions'] (Visium).
                                       Example: 'sub_level_cell_type', 'celltype', 'cell_type'
        organism (Literal['human', 'mouse']): Organism for geneset selection (default: 'human')
        geneset (Literal['progeny', 'hallmark']): Pathway geneset to use (default: 'progeny')
        model (Literal['rf', 'liner']): Prediction model - 'rf' for Random Forest,
                                        'liner' for Linear regression (default: 'rf')
        view (Literal['juxta', 'para']): Signaling view to analyze (default: 'juxta')
                                         - 'juxta': Juxtacrine (direct contact) signaling
                                         - 'para': Paracrine (diffusion-mediated) signaling
        min_n (int): Minimum number of targets per source (pathway) required for pathway
                     enrichment analysis. Default is 5. For single-cell resolution data
                     with limited gene panels (e.g., STARmap, MERFISH), use lower values
                     like 1-3 to avoid AssertionError when gene overlap is insufficient.
        width (int, optional): Figure width in inches. If None, auto-calculated based on
                               number of pathways (default: None)
        height (int, optional): Figure height in inches. If None, auto-calculated based on
                                number of cell types (default: None)
        save_path (str): Output directory for saving plots and results (default: 'res/')

    Outputs:
        - Image: {save_path}/5.spatial_relation_MISTy.png
          Heatmap showing feature importance of pathway-celltype relationships
          Rows: Cell types (targets)
          Columns: Pathways (predictors)
          Values: Importance scores (how well pathway predicts cell type distribution)

        - CSV: {save_path}/res_SpatialRelationship_MISTy.csv
          Filtered results for selected view (juxta or para)
          Columns:
            - target: Cell type name
            - predictor: Pathway name (from PROGENy or Hallmark geneset)
            - view: Signaling view ('juxta' or 'para')
            - importances: Feature importance score (interpretation depends on model)

    Analysis Results:
        - Identification of pathway-celltype relationships: Determine which pathways
          are associated with the spatial distribution of specific cell types
        - Spatial signaling environment characterization: Understand molecular signals
          that organize tissue spatial structure
        - Pathway-celltype association validation: Cross-validate with Part 1 Step 4
          (cluster-pathway associations)
        - Downstream selection: Use results to connect pathways with cell types for
          Part 2 CCI analysis

    Important Notes:
        - MISTy analyzes spatial relationships, not just enrichment
        - Results show predictive power, not just correlation
        - Each target (cell type) is predicted independently
        - Feature importance interpretation depends on model choice
        - Juxtacrine (juxta) view captures direct cell-cell interactions
        - Paracrine (para) view captures diffusion-mediated signaling
        - Results complement cluster-pathway (Step 4) and cell type-cluster (Step 2) analyses
        - Part 1 analysis variations may occur; recommended to run 3-5 times
        - Selected pathway-celltype relationships inform Part 2 NMF and CCI analysis

    Returns:
        None
    """
    # Dynamic sizing constants
    BASE_WIDTH = 7
    BASE_HEIGHT = 5
    WIDTH_PER_PATHWAY = 0.5
    HEIGHT_PER_CELLTYPE = 0.4

    adata = sc.read_h5ad(filename)

    # Calculate number of cell types for dynamic sizing
    if celltype_key is not None:
        n_celltypes = adata.obs[celltype_key].nunique()
    elif 'compositions' in adata.obsm:
        n_celltypes = adata.obsm['compositions'].shape[1]
    else:
        n_celltypes = 10  # fallback

    # Number of pathways based on geneset
    n_pathways = 14 if geneset == 'progeny' else 50  # progeny=14, hallmark≈50

    # Auto-calculate dimensions if not specified
    fig_width = width if width is not None else max(BASE_WIDTH, n_pathways * WIDTH_PER_PATHWAY)
    fig_height = height if height is not None else max(BASE_HEIGHT, n_celltypes * HEIGHT_PER_CELLTYPE)

    misty = sp_relation(adata, cluster_key, organism=organism, geneset=geneset, model=model, celltype_key=celltype_key, min_n=min_n)

    os.makedirs(save_path, exist_ok=True)

    df = misty.uns['interactions']
    
    # NOTE!! we only focused on the juxta and para
    save_df = df[df['view'] == view]
    # save_df.to_csv(f'{save_path}/res_SpatialRelationship_MISTy.csv')
 
    # filteirng using median value of importances
    # median_value = save_df['importances'].median()
    percentile_90 = save_df['importances'].quantile(0.9)
    f_save_df = save_df[save_df['importances'] > percentile_90]
    f_save_df  = f_save_df.sort_values('importances', ascending=False)
    f_save_df.to_csv(f'{save_path}/res_SpatialRelationship_MISTy.csv')

    mp=plot_sp_relation(misty)
    mp
    save=f'{save_path}/5.spatial_relation_MISTy.png'
    mp.save(save, dpi=300, width=fig_width, height=fig_height)
    print(f"Spatial relationship (MISTy) plot saved to: {save}")
    
    from IPython.display import Image, display
    display(Image(save))
    
    return None

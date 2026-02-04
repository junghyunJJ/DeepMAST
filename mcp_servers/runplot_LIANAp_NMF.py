import os
import pickle
import logging
import warnings
from threading import Lock

from typing import Optional, Literal, List

import anndata
import numpy as np
import pandas as pd
import scanpy as sc
import squidpy as sq
import matplotlib.pyplot as plt
from sklearn.metrics.pairwise import cosine_similarity

from utils.run_liana import run_liana, run_liana_bivariate, run_liana_nmf
from utils.download_genept import ensure_genept_embeddings, DEFAULT_EMBEDDINGS_PATH

# GenePT Embeddings Configuration
GENEPT_EMBEDDINGS_ENV_VAR = "GENEPT_EMBEDDINGS_PATH"

logger = logging.getLogger(__name__)


class _GenePTScorer:
    """Lightweight GenePT scorer for L-R pair similarity.

    Singleton with lazy loading. Only loads embeddings when scoring is called.
    Automatically downloads embeddings from Zenodo if not found.
    Designed to be self-contained (no external DeepMAST imports).

    Path Resolution Priority:
        1. Custom path parameter (if provided)
        2. GENEPT_EMBEDDINGS_PATH environment variable (if set)
        3. ~/.cache/genept/embeddings.pickle (auto-download if needed)

    GenePT Reference:
        Chen & Zou (2024). GenePT: A Simple But Effective Foundation Model
        for Genes and Cells Built From ChatGPT. Nature Biomedical Engineering.
        https://doi.org/10.1038/s41551-024-01284-6
    """

    _instance = None
    _lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._embeddings = None
        self._embeddings_path = None
        self._load_attempted = False
        self._initialized = True

    def _get_embeddings_path(self, custom_path=None):
        """Resolve embeddings path from custom, env var, or default with auto-download.

        Args:
            custom_path: Optional explicit path to embeddings file

        Returns:
            Path to embeddings file, or None if unavailable
        """
        # Priority 1: Custom path parameter
        if custom_path:
            if os.path.exists(custom_path):
                return custom_path
            logger.warning(f"Custom embeddings path not found: {custom_path}")
            return None

        # Priority 2: Environment variable
        env_path = os.environ.get(GENEPT_EMBEDDINGS_ENV_VAR)
        if env_path:
            if os.path.exists(env_path):
                return env_path
            logger.warning(
                f"GENEPT_EMBEDDINGS_PATH points to non-existent file: {env_path}. "
                f"Falling back to default location with auto-download."
            )

        # Priority 3: Default location with auto-download
        result = ensure_genept_embeddings()
        return str(result) if result else None

    def _load_embeddings(self, embeddings_path=None):
        """Load embeddings lazily. Returns True if loaded, False otherwise."""
        if self._embeddings is not None:
            return True

        if self._load_attempted:
            return False

        self._load_attempted = True
        path = self._get_embeddings_path(embeddings_path)

        if path is None:
            logger.warning(
                "GenePT embeddings unavailable. "
                "Check network connection or set GENEPT_EMBEDDINGS_PATH manually. "
                "Skipping GenePT scoring."
            )
            return False

        try:
            logger.info(f"Loading GenePT embeddings from {path}")
            with open(path, "rb") as f:
                raw_embeddings = pickle.load(f)

            # Normalize gene names to uppercase
            self._embeddings = {
                gene.upper(): np.array(embedding)
                for gene, embedding in raw_embeddings.items()
            }
            self._embeddings_path = path
            logger.info(f"Loaded {len(self._embeddings)} gene embeddings")
            return True
        except Exception as e:
            logger.warning(f"Failed to load GenePT embeddings: {e}. Skipping GenePT scoring.")
            return False

    def get_embedding(self, gene):
        """Get embedding for a gene. Returns None if not found."""
        if self._embeddings is None:
            return None
        return self._embeddings.get(gene.upper())

    def score_lr_pair(self, ligand, receptor):
        """Calculate cosine similarity between ligand and receptor.

        Returns:
            float (0-1 range) or None if either gene not found
        """
        if self._embeddings is None:
            return None

        ligand_emb = self.get_embedding(ligand)
        receptor_emb = self.get_embedding(receptor)

        if ligand_emb is None or receptor_emb is None:
            return None

        similarity = cosine_similarity(
            ligand_emb.reshape(1, -1),
            receptor_emb.reshape(1, -1)
        )[0, 0]

        # Normalize from [-1, 1] to [0, 1]
        return float((similarity + 1) / 2)

    def score_dataframe(self, df, ligand_col="ligand", receptor_col="receptor",
                        score_col="genept_score", embeddings_path=None):
        """Add GenePT scores to a DataFrame.

        Args:
            df: DataFrame with ligand and receptor columns
            ligand_col: Name of ligand column
            receptor_col: Name of receptor column
            score_col: Name for output score column
            embeddings_path: Optional custom path to embeddings

        Returns:
            DataFrame with added score column (NaN for missing genes)
        """
        result_df = df.copy()

        # Attempt to load embeddings (triggers auto-download if needed)
        if not self._load_embeddings(embeddings_path):
            # Add NaN column if embeddings not available
            result_df[score_col] = np.nan
            return result_df

        scores = []
        for _, row in result_df.iterrows():
            ligand = str(row[ligand_col])
            receptor = str(row[receptor_col])

            # Handle complex receptor names (e.g., "ITGA3_ITGB1")
            if "_" in receptor and self.get_embedding(receptor) is None:
                receptor_parts = receptor.split("_")
                receptor = receptor_parts[0]

            score = self.score_lr_pair(ligand, receptor)
            scores.append(score)

        result_df[score_col] = scores
        return result_df


def _get_genept_scorer():
    """Factory function for GenePT scorer singleton."""
    return _GenePTScorer()


def detect_platform(adata) -> str:
    """
    Detect spatial transcriptomics platform type from AnnData structure.

    Detection logic:
        - Visium: adata.uns['spatial'] contains library_id with 'images' or 'scalefactors'
        - Single-cell resolution: All other cases (MERFISH, Xenium, STARmap, etc.)

    Args:
        adata: AnnData object with spatial transcriptomics data

    Returns:
        'visium' for spot-based 10x Visium data
        'single_cell' for single-cell resolution data
    """
    if 'spatial' in adata.uns:
        spatial_uns = adata.uns['spatial']
        if isinstance(spatial_uns, dict):
            for key in spatial_uns.keys():
                if isinstance(spatial_uns[key], dict):
                    if 'images' in spatial_uns[key] or 'scalefactors' in spatial_uns[key]:
                        return 'visium'
    return 'single_cell'


def expand_neighbors_n_rings(adata, n_rings: int = 2):
    """
    Expand Delaunay-based 1-hop neighbors to n-rings using graph power.

    For non-grid spatial data (MERFISH, Xenium, STARmap), Squidpy's n_rings
    parameter is not available with Delaunay triangulation. This function
    computes multi-hop neighbors by raising the adjacency matrix to successive
    powers, providing equivalent functionality to Visium's n_rings parameter.

    Graph Power Concept:
        - A^1 = 1-hop neighbors (direct Delaunay neighbors)
        - A^2 = 2-hop neighbors (neighbors of neighbors)
        - A^n = n-hop reachable neighbors
        - Combined = A^1 + A^2 + ... + A^n (binary connectivity)

    Args:
        adata: AnnData object with spatial_connectivities already computed
               (from sq.gr.spatial_neighbors with delaunay=True)
        n_rings: Number of neighbor rings to include (default: 2)
                 - n_rings=1: Only direct neighbors (no expansion)
                 - n_rings=2: Direct + 2-hop neighbors (equivalent to Visium n_rings=2)
                 - n_rings=3: Direct + 2-hop + 3-hop neighbors

    Returns:
        adata: Modified in-place with updated spatial_connectivities

    Note:
        - Higher n_rings values increase connectivity density significantly
        - For dense single-cell data, n_rings=2 is recommended (matches Visium default)
        - n_rings=3+ may result in most cells being connected (use with caution)
    """
    import numpy as np
    from scipy import sparse

    if 'spatial_connectivities' not in adata.obsp:
        raise ValueError("spatial_connectivities not found. Run sq.gr.spatial_neighbors first.")

    adj = adata.obsp['spatial_connectivities'].copy()
    if not sparse.issparse(adj):
        adj = sparse.csr_matrix(adj)

    # Start with 1-hop neighbors
    combined = adj.copy()
    adj_power = adj.copy()

    # Add higher-order neighbors (2-hop, 3-hop, ...)
    for ring in range(2, n_rings + 1):
        adj_power = adj_power @ adj  # matrix multiplication for n-hop
        adj_power.setdiag(0)         # remove self-loops
        combined = combined + adj_power

    # Convert to binary connectivity (1 = connected, 0 = not)
    combined.data[:] = 1.0
    combined.eliminate_zeros()

    # Update adata in-place
    adata.obsp['spatial_connectivities'] = combined

    return adata


def remove_long_links(adata, distance_percentile: float = 99.0) -> int:
    """
    Remove edges longer than the specified percentile threshold from spatial graph.

    Delaunay triangulation can create very long edges at tissue boundaries or in
    sparse regions that don't represent biologically meaningful neighbor relationships.
    This function removes such outlier edges based on a distance percentile threshold.

    This step should be performed AFTER computing Delaunay-based spatial neighbors
    but BEFORE expanding to multi-ring neighbors.

    Algorithm:
        1. Calculate the distance threshold as the Nth percentile of all edge distances
        2. Remove edges with distance > threshold from both connectivity and distance matrices
        3. Preserve the sparse matrix structure

    Args:
        adata: AnnData object with spatial_connectivities and spatial_distances computed
               (from sq.gr.spatial_neighbors with delaunay=True)
        distance_percentile: Percentile threshold for edge removal (default: 99.0)
                             - 99.0: Remove top 1% longest edges (recommended)
                             - 95.0: More aggressive removal (top 5%)
                             - 99.5: Conservative removal (top 0.5%)

    Returns:
        int: Number of edges removed

    Note:
        - This function modifies adata in-place
        - Only applicable to single-cell resolution data (not Visium)
        - Recommended to use default 99.0 percentile (CellCharter default)

    Reference:
        CellCharter: https://cellcharter.readthedocs.io/en/latest/generated/cellcharter.gr.remove_long_links.html
    """
    import numpy as np
    from scipy import sparse

    if 'spatial_distances' not in adata.obsp:
        raise ValueError("spatial_distances not found. Run sq.gr.spatial_neighbors first.")
    if 'spatial_connectivities' not in adata.obsp:
        raise ValueError("spatial_connectivities not found. Run sq.gr.spatial_neighbors first.")

    # Get matrices
    distances = adata.obsp['spatial_distances'].copy()
    connectivities = adata.obsp['spatial_connectivities'].copy()

    if sparse.issparse(distances):
        distances = distances.tocsr()
    if sparse.issparse(connectivities):
        connectivities = connectivities.tocsr()

    # Calculate threshold from non-zero distances
    nonzero_distances = distances.data
    if len(nonzero_distances) == 0:
        return 0

    threshold = np.percentile(nonzero_distances, distance_percentile)

    # Count edges before removal
    n_edges_before = connectivities.nnz

    # Create mask for edges to keep (distance <= threshold)
    mask = distances.data <= threshold

    # Apply mask to both matrices
    connectivities.data = connectivities.data * mask.astype(float)
    connectivities.eliminate_zeros()

    distances.data = distances.data * mask.astype(float)
    distances.eliminate_zeros()

    # Count edges after removal
    n_edges_after = connectivities.nnz
    n_removed = n_edges_before - n_edges_after

    # Update adata in-place
    adata.obsp['spatial_connectivities'] = connectivities
    adata.obsp['spatial_distances'] = distances

    return n_removed


def compute_spatial_neighbors_by_sample(
    adata, sample_key: str, platform: str, n_rings: int = 2, distance_percentile: Optional[float] = 99.0
) -> dict:
    """
    Compute spatial neighbors separately for each sample in multi-sample data.

    Spatial neighbors should be computed WITHIN each sample separately because
    spots/cells from different tissue sections should not be considered neighbors.
    This function splits data by sample_key, computes spatial neighbors for each,
    and returns a dictionary of AnnData objects.

    For non-Visium data (MERFISH, Xenium, STARmap), Delaunay triangulation provides
    only 1-hop neighbors. This function:
        1. Computes Delaunay-based 1-hop neighbors
        2. Removes long edges (based on distance_percentile threshold)
        3. Expands to multi-ring neighbors using graph power

    Args:
        adata: AnnData object with multi-sample spatial data
        sample_key: Column name in adata.obs containing sample identifiers
        platform: 'visium' or 'single_cell' for spatial neighbors method
        n_rings: Number of neighbor rings (default: 2)
                 - For Visium: passed directly to sq.gr.spatial_neighbors
                 - For single-cell: Delaunay 1-hop expanded using graph power
        distance_percentile: Percentile threshold for removing long edges (default: 99.0)
                             - Only applied to single-cell data (not Visium)
                             - Set to None to skip long edge removal
                             - 99.0 removes top 1% longest edges (CellCharter default)

    Returns:
        Dictionary mapping sample names to AnnData objects with spatial neighbors computed
    """
    samples = adata.obs[sample_key].unique()
    print(f"   Processing {len(samples)} samples separately: {list(samples)}")

    adata_dict = {}
    for sample in samples:
        adata_sample = adata[adata.obs[sample_key] == sample].copy()

        # Apply platform-specific spatial neighbors
        if platform == 'visium':
            sq.gr.spatial_neighbors(adata_sample, n_neighs=6, n_rings=n_rings)
        else:
            # Single-cell: Delaunay → remove long links → expand to n-rings
            sq.gr.spatial_neighbors(adata_sample, delaunay=True, coord_type="generic")

            # Remove long edges before expansion (if percentile specified)
            if distance_percentile is not None:
                n_removed = remove_long_links(adata_sample, distance_percentile=distance_percentile)
                print(f"      Sample '{sample}': removed {n_removed} long edges (>{distance_percentile}th percentile)")

            # Expand to multi-ring neighbors
            if n_rings > 1:
                expand_neighbors_n_rings(adata_sample, n_rings=n_rings)

        adata_dict[sample] = adata_sample
        print(f"      Sample '{sample}': {adata_sample.n_obs} observations, n_rings={n_rings}")

    return adata_dict


from utils.run_nmf import plot_factorscore, res_liana_factorscore, sel_factor, res_liana_loadings, enrich_pathway_factor

from utils.plots import create_heatmap, create_factor_loading_heatmap
from utils.plot_cci_analysis import plot_quadrant, plot_interaction


def run_lianap(
    filename: str,
    organism: Literal['human', 'mouse'] = 'human',
    platform: Literal['visium', 'single_cell', 'auto'] = 'auto',
    sample_key: Optional[str] = None,
    interest_sample: Optional[str] = None,
    n_rings: int = 2,
    distance_percentile: Optional[float] = 99.0,
    n_perms: int = 1000,
    max_iter_nmf: int = 200,
    save_path: str = 'res/',
    ) -> None:
    """
    Part 2: CCI Analysis with NMF - Step 6. Cell-Cell Interaction (CCI) Analysis (LIANA using Omnipath)

    Performs LIANA+ bivariate analysis to identify significant ligand-receptor pairs with
    spatial co-clustering patterns using Bivariate Moran's R. Includes NMF (Non-negative
    Matrix Factorization) to identify intercellular communication patterns.

    Methodology:
        - Spatial Neighbors: Squidpy (platform-specific, auto-detected)
        - CCI Database: LIANA+ with Omnipath (supports human and mouse)
        - Spatial Statistics: Bivariate Moran's R
        - Pattern Discovery: NMF factorization
        - Permutation Testing: n_perms permutations

    Platform Support:
        - visium: Spot-based 10x Visium data
          Uses sq.gr.spatial_neighbors(adata, n_neighs=6, n_rings=1) for grid-based neighbors
        - single_cell: Single-cell resolution data (MERFISH, Xenium, STARmap, etc.)
          Uses sq.gr.spatial_neighbors(adata, delaunay=True, coord_type="generic") for
          Delaunay triangulation-based neighbors (optimal for irregular cell coordinates)
        - auto: Automatically detects platform from adata.uns['spatial'] structure

    Multi-Sample Support:
        - When sample_key is provided, spatial neighbors are computed SEPARATELY for each sample
        - This prevents spots/cells from different tissue sections being considered neighbors
        - Critical for multi-sample datasets (e.g., multiple Visium slides, multiple FOVs)
        - Connectivity matrices become block-diagonal after per-sample computation

    Organism Support:
        - human: Uses human LR database from OmniPath directly
        - mouse: Translates human LR database to mouse orthologs using HCOP
                 (Human and mouse Comparison of Orthologous Predictions)

    Bivariate Moran's R Interpretation:
        - Near 0: Spatial independence (ligand-receptor pair not co-localized)
        - Positive values: Spatial co-clustering (ligand-receptor pair co-localized)
        - Significant: Moran's R > 0 & pval < 0.05 (red dots in plot)

    Workflow Position:
        - Part 2 analysis (CCI, Morans R, NMF results)
        - Step 6: CCI analysis and pattern identification
        - Uses lrdata.h5ad for all downstream Part 2 and Part 3 analysis
        - Prerequisite for Steps 7-11

    Data Requirements:
        - Uses normalized n_adata.h5ad data
        - Requires spatial coordinates in adata.obsm['spatial']
        - Requires spatial neighbor graph (automatically computed)
        - Compatible with spot-based (Visium) and single-cell resolution (MERFISH, Xenium) data

    Args:
        filename (str): Path to the `.h5ad` file containing spatial transcriptomics data
        organism (Literal['human', 'mouse']): Organism for LR database selection (default: 'human')
                                              For mouse, human LR pairs are translated using HCOP orthologs.
        platform (Literal['visium', 'single_cell', 'auto']): Platform type for spatial neighbors
                                                              computation (default: 'auto')
            - 'visium': Use grid-based neighbors (n_neighs=6, n_rings=1)
            - 'single_cell': Use Delaunay triangulation (delaunay=True, coord_type="generic")
            - 'auto': Auto-detect from adata.uns['spatial'] structure
        sample_key (str, optional): Column name in adata.obs containing sample identifiers.
                                    If provided, spatial neighbors are computed separately for each sample.
                                    Essential for multi-sample datasets to prevent cross-sample neighbors.
                                    Example: 'sample_id', 'library_id', 'batch'
                                    Default: None (single sample, compute neighbors on entire dataset)
        interest_sample (str, optional): Specific sample to analyze. If provided, subsets adata
                                         to only this sample before analysis. Requires sample_key.
                                         Saves subset as {save_path}/adata_{interest_sample}.h5ad
                                         Default: None (analyze all samples)
        n_rings (int): Number of spatial neighbor rings to include (default: 2)
                       - For Visium: passed directly to sq.gr.spatial_neighbors(n_rings=n_rings)
                       - For single-cell (MERFISH, Xenium, STARmap): Delaunay triangulation provides
                         only 1-hop neighbors, which are then expanded using graph power (A^n)
                         to include n-hop neighbors. n_rings=2 is equivalent to Visium's default.
                       Recommended values:
                         - n_rings=1: Direct neighbors only (minimal spatial context)
                         - n_rings=2: Direct + 2-hop neighbors (default, matches Visium)
                         - n_rings=3: Wider neighborhood (use with caution for dense data)
        distance_percentile (float, optional): Percentile threshold for removing long edges from
                       Delaunay triangulation (default: 99.0). Only applied to single-cell data.
                       - Removes edges longer than the Nth percentile of all edge distances
                       - Applied AFTER Delaunay triangulation but BEFORE multi-ring expansion
                       - Prevents biologically meaningless long-distance connections at tissue
                         boundaries or sparse regions from affecting analysis
                       Recommended values:
                         - 99.0: Remove top 1% longest edges (default, CellCharter recommended)
                         - 95.0: More aggressive removal (top 5%)
                         - None: Skip long edge removal (not recommended for most cases)
                       Reference: CellCharter remove_long_links()
        n_perms (int): Number of permutations for Moran's R significance testing (default: 1000)
        max_iter_nmf (int): Maximum iterations for NMF factorization (default: 200)
        save_path (str): Output directory for saving results (default: 'res/')

    Outputs:
        - File: {save_path}/lrdata.h5ad
          AnnData object containing:
            - CCI results (ligand-receptor pairs)
            - Bivariate Moran's R values and p-values
            - NMF factor scores (observations × factors)
            - NMF loadings (ligand-receptor pairs × factors)

    Analysis Results:
        - Identification of significant ligand-receptor pairs
        - Spatial co-clustering patterns via Moran's R
        - Intercellular communication patterns via NMF
        - Foundation for downstream factor, pathway, and ctSVG analysis

    Important Notes:
        - lrdata.h5ad is the primary data object for Part 2 and Part 3
        - Higher n_perms improves statistical robustness but increases computation time
        - NMF discovers latent communication patterns across tissue
        - Significant pairs (Moran's R > 0, p < 0.05) are prioritized in downstream analysis
        - For mouse data, HCOP ortholog translation may reduce number of LR pairs
        - Platform auto-detection checks for Visium-specific structure in adata.uns['spatial']
        - For multi-sample data, ALWAYS provide sample_key to ensure correct spatial neighbors

    Returns:
        None
    """
    adata = sc.read_h5ad(filename)
    os.makedirs(save_path, exist_ok=True)

    # Save interest sample adata separately (for downstream analysis)
    if interest_sample is not None:
        if sample_key is None:
            raise ValueError("sample_key must be specified when using interest_sample")
        adata_interest = adata[adata.obs[sample_key] == interest_sample].copy()
        adata_interest.write_h5ad(f'{save_path}/adata_{interest_sample}.h5ad')
        print(f"   Saved interest sample: {save_path}/adata_{interest_sample}.h5ad ({adata_interest.n_obs} observations)")

    # Detect or use specified platform
    if platform == 'auto':
        detected_platform = detect_platform(adata)
        print(f"   Auto-detected platform: {detected_platform}")
    else:
        detected_platform = platform
        print(f"   Using specified platform: {detected_platform}")

    # Compute spatial neighbors (per-sample if sample_key provided)
    if sample_key is not None:
        # Multi-sample workflow:
        # 1. Compute spatial neighbors per sample
        # 2. Run bivariate per sample
        # 3. Concatenate lrdata
        # 4. Run NMF once on concatenated data (discovers patterns across ALL samples)
        print(f"   Multi-sample mode: splitting by '{sample_key}'")
        adata_dict = compute_spatial_neighbors_by_sample(
            adata, sample_key, detected_platform, n_rings=n_rings, distance_percentile=distance_percentile
        )

        if detected_platform == 'visium':
            print(f"   Spatial neighbors: n_neighs=6, n_rings={n_rings} (Visium grid-based, per-sample)")
        else:
            pct_str = f", long edges removed (>{distance_percentile}th pct)" if distance_percentile else ""
            print(f"   Spatial neighbors: Delaunay + {n_rings}-ring expansion{pct_str} (single-cell, per-sample)")

        # Step 1: Run bivariate analysis for each sample separately
        lrdata_list = []
        for sample_name, adata_sample in adata_dict.items():
            print(f"\n   Running LIANA+ bivariate for sample '{sample_name}'...")
            lrdata = run_liana_bivariate(adata_sample, organism=organism, n_perms_bivariate=n_perms)
            lrdata_list.append(lrdata)
            print(f"      {sample_name}: {lrdata.n_obs} observations, bivariate complete")

        # Step 2: Store per-sample bivariate stats before concat (will be restored later)
        sample_names = list(adata_dict.keys())
        bivariate_stats_dict = {}
        for i, sample_name in enumerate(sample_names):
            bivariate_stats_dict[sample_name] = lrdata_list[i].var.copy()
        print(f"   Stored bivariate stats for {len(sample_names)} samples")

        # Step 3: Concatenate for combined NMF
        print(f"\n   Concatenating {len(lrdata_list)} samples for unified NMF...")
        lrdata_combined = anndata.concat(lrdata_list, join='outer')
        print(f"   Combined lrdata: {lrdata_combined.n_obs} total observations, {lrdata_combined.n_vars} LR pairs")

        # Step 4: Run NMF once on concatenated data
        print(f"\n   Running NMF on combined data (discovers patterns across all samples)...")
        run_liana_nmf(lrdata_combined, max_iter_nmf=max_iter_nmf)

        # Step 5: Save individual sample files by subsetting from combined
        # This ensures var (LR pairs) and NMF results are consistent
        print(f"\n   Creating individual sample files with NMF + bivariate stats...")

        # Need to track which obs belong to which sample
        # Reconstruct sample assignment from original lrdata_list
        sample_assignment = []
        for i, sample_name in enumerate(sample_names):
            sample_assignment.extend([sample_name] * lrdata_list[i].n_obs)
        lrdata_combined.obs['_sample_for_split'] = sample_assignment

        for sample_name in sample_names:
            # Subset combined data for this sample
            mask = lrdata_combined.obs['_sample_for_split'] == sample_name
            lrdata_sample = lrdata_combined[mask].copy()

            # Copy varm (NMF_H) - subsetting doesn't copy varm automatically
            # NMF_H is variable loadings, same for all samples (shared factors)
            for key in lrdata_combined.varm.keys():
                lrdata_sample.varm[key] = lrdata_combined.varm[key].copy()

            # Restore sample-specific bivariate stats
            # Only restore for LR pairs that exist in both (intersection)
            sample_bivar = bivariate_stats_dict[sample_name]
            common_vars = lrdata_sample.var.index.intersection(sample_bivar.index)
            for col in sample_bivar.columns:
                # Initialize with NaN, then fill in available values
                lrdata_sample.var[col] = float('nan')
                lrdata_sample.var.loc[common_vars, col] = sample_bivar.loc[common_vars, col].values

            # Remove temporary column
            if '_sample_for_split' in lrdata_sample.obs.columns:
                del lrdata_sample.obs['_sample_for_split']

            # Save
            individual_path = f'{save_path}/lrdata_{sample_name}.h5ad'
            lrdata_sample.write_h5ad(individual_path)
            print(f"      Saved: {individual_path} (bivariate + NMF, {lrdata_sample.n_obs} obs, varm: {list(lrdata_sample.varm.keys())})")

        # Clean up combined
        if '_sample_for_split' in lrdata_combined.obs.columns:
            del lrdata_combined.obs['_sample_for_split']

        # Save combined result
        lrdata_combined.write_h5ad(f'{save_path}/lrdata.h5ad')
        print(f"\n   Saved: {save_path}/lrdata.h5ad")
        print(f"   Completed: {len(lrdata_list)} samples processed with unified NMF")
        print(f"   ✅ Individual files ready for sample-specific loadings analysis")
        return None

    else:
        # Single sample: compute spatial neighbors on entire dataset
        if detected_platform == 'visium':
            sq.gr.spatial_neighbors(adata, n_neighs=6, n_rings=n_rings)
            print(f"   Spatial neighbors: n_neighs=6, n_rings={n_rings} (Visium grid-based)")
        else:
            sq.gr.spatial_neighbors(adata, delaunay=True, coord_type="generic")
            # Remove long edges before expansion (only for non-Visium)
            if distance_percentile is not None:
                n_removed = remove_long_links(adata, distance_percentile=distance_percentile)
                print(f"   Removed {n_removed} long edges (>{distance_percentile}th percentile)")
            if n_rings > 1:
                expand_neighbors_n_rings(adata, n_rings=n_rings)
            print(f"   Spatial neighbors: Delaunay + {n_rings}-ring expansion (single-cell resolution)")

        adata_liana = adata.copy()
        lrdata = run_liana(adata_liana, organism=organism, n_perms_bivariate=n_perms, max_iter_nmf=max_iter_nmf)
        lrdata.write_h5ad(f'{save_path}/lrdata.h5ad')

        return None



def runplot_liana_factorscore(
    filename: str,
    cluster_key: str,
    sample_key: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    save_path: str = 'res/',
    ) -> None:
    """
    Part 2: CCI Analysis with NMF - Step 7. Intercellular Pattern Analysis (Factor Score; NMF)

    Visualizes NMF factor scores spatially and generates cluster-level factor median values.
    Factor scores represent the activation strength of intercellular communication patterns
    (factors) at each observation (spot/cell). Higher factor scores indicate stronger
    activation of that specific communication pattern.

    NMF Factor Scores Concept:
        - Matrix Dimensions: Observations (spots/cells) × Factors
        - Factor Score = Activation strength of intercellular pattern at each spot
        - Spatial Plot: Visualizes factor activation across tissue spatial coordinates
        - Cluster Median: Aggregates factor scores by cluster for pattern characterization

    Factor Interpretation:
        - Each factor represents a distinct intercellular communication pattern
        - Factor scores quantify how strongly each pattern is activated at each location
        - Cluster-level medians identify which clusters are enriched for specific patterns
        - Used to select ONE factor of interest for downstream ligand-receptor analysis

    Multi-Sample Support:
        - For multi-sample data, creates a grid layout with each sample in its own row
        - Each row shows all factors and cluster annotation for that sample
        - Bottom row contains single barplot of factor medians across all samples
        - sample_key specifies which column identifies samples (auto-detected if None)

    Workflow Position:
        - Part 2 analysis (CCI with NMF)
        - Step 7: Factor score visualization and cluster association
        - Follows Step 6 (LIANA+ CCI analysis and NMF factorization)
        - Prerequisite for Step 8 (ligand-receptor loadings analysis)
        - Critical decision point: Must select ONE factor before proceeding to Step 8

    Data Requirements:
        - Uses lrdata.h5ad from Step 6 (run_lianap)
        - Requires NMF factor scores in lrdata
        - Requires cluster annotations in lrdata.obs[cluster_key]
        - Requires spatial coordinates in lrdata.obsm['spatial']

    Args:
        filename (str): Path to lrdata.h5ad file (output from run_lianap)
        cluster_key (str): Column name in lrdata.obs containing cluster assignments
        sample_key (str, optional): Column name identifying samples for multi-sample data.
                                    If None, auto-detects from .uns['spatial'] keys.
                                    Default: None
        width (int, optional): Figure width in inches. If None, auto-calculated based on
                               number of factors (~2.5 inches per column). Default: None
        height (int, optional): Figure height per sample row in inches. If None, auto-calculated
                                (~3 inches per sample row). Default: None
        save_path (str): Output directory for saving plots and results (default: 'res/')

    Outputs:
        - Image: {save_path}/7.factor_spatial_NMF.png
          Grid layout figure with:
            - Rows: Each sample's spatial plots (factors + cluster)
            - Bottom: Single barplot of factor medians across all samples
        - CSV: {save_path}/res_liana_cluster_factor.csv
          Cluster-level factor median values

    Analysis Results:
        - Identification of intercellular communication patterns: Visualize spatial
          distribution of NMF factors representing distinct communication programs
        - Cluster-factor associations: Determine which clusters are enriched for
          specific intercellular patterns
        - Factor selection guidance: Use cluster median values to select ONE factor
          of interest for downstream ligand-receptor analysis (Step 8)
        - Spatial pattern validation: Confirm factor scores show biologically
          meaningful spatial organization

    Important Notes:
        - Factor selection is CRITICAL - choose ONE factor that best represents
          interest clusters and communication patterns
        - Selected factor will be used in Step 8 to identify specific ligand-receptor
          pairs driving that intercellular pattern
        - Cluster medians help identify which factor best captures interest cluster biology
        - Factor scores are derived from NMF factorization in Step 6

    Returns:
        None
    """
    lrdata = sc.read_h5ad(filename)
    os.makedirs(save_path, exist_ok=True)

    # 1. factor score (combined across all samples)
    res_factorscore = res_liana_factorscore(lrdata, cluster_key=cluster_key)

    factor_cols = [col for col in res_factorscore.columns if col.startswith('Factor')]
    factor_median_by_cluster = res_factorscore.groupby(cluster_key)[factor_cols].median()
    factor_median_by_cluster['Total'] = factor_median_by_cluster.sum(axis=1)
    factor_median_by_cluster = factor_median_by_cluster.sort_values('Total', ascending=False)

    factor_median_by_cluster = factor_median_by_cluster.drop('Total', axis=1)
    factor_median_by_cluster.to_csv(f"{save_path}/res_liana_cluster_factor.csv")

    # 2. Spatial plots - grid layout with each sample in its own row, one barplot at bottom
    plot_factorscore(lrdata, cluster_key=cluster_key, sample_key=sample_key,
                     width=width, height=height, save_path=save_path)

    return None


def runplot_liana_factor_loading_heatmap(
    filename: str,
    sample_key: str = 'label',
    group_key: Optional[str] = None,
    width: Optional[float] = None,
    height: Optional[float] = None,
    save_path: str = 'res/',
    ) -> None:
    """
    Part 2: CCI Analysis with NMF - Step 7.1. Factor Loading Heatmap (Sample-Level Aggregation)

    Generates a clustered heatmap showing average NMF factor loadings aggregated by sample.
    This visualization complements the spatial factor score plot (Step 7) by providing a
    compact summary of factor activation patterns across experimental conditions/groups.

    Pseudobulk Aggregation Concept:
        - Aggregates spot/cell-level NMF factor scores to sample level using mean
        - Each row = NMF Factor, Each column = Sample
        - Values = Average factor loading (mean of factor scores across all spots in sample)
        - Clustering: Hierarchical clustering on columns (samples) to reveal sample groupings

    Visualization Features:
        - Clustered heatmap with dendrogram (top and left)
        - Color annotation bar showing sample group membership
        - Legend positioned at top-right (no overlap with axis labels)
        - Colorbar showing average factor loading scale
        - Auto-sizing based on number of samples and factors

    Use Cases:
        - Compare factor activation across experimental conditions (e.g., disease vs control)
        - Identify condition-specific intercellular communication patterns
        - Validate factor-cluster associations observed in spatial plots
        - Summarize multi-sample data for publication figures

    Workflow Position:
        - Part 2 analysis (CCI with NMF)
        - Step 7.1: Sample-level factor aggregation and visualization
        - Follows Step 7 (spatial factor score visualization)
        - Prerequisite for Step 8 (ligand-receptor loadings analysis)
        - Provides overview before detailed per-sample analysis

    Data Requirements:
        - Uses lrdata.h5ad from Step 6 (run_lianap)
        - Requires NMF factor scores in lrdata.obsm['NMF_W']
        - Requires NMF loadings in lrdata.varm['NMF_H']
        - Requires sample identifiers in lrdata.obs[sample_key]

    Args:
        filename (str): Path to lrdata.h5ad file (output from run_lianap)
        sample_key (str): Column name in lrdata.obs for sample identifiers used for
                         pseudobulk aggregation. Default: 'label'
        group_key (str, optional): Column name for group annotations in the heatmap.
                                   If None, uses sample_key for both aggregation and annotation.
                                   Use this to color samples by experimental condition.
                                   Default: None
        width (float, optional): Figure width in inches. If None, auto-calculated as:
                                 max(4, n_samples * 1.2 + 2) inches
                                 Default: None
        height (float, optional): Figure height in inches. If None, auto-calculated as:
                                  max(4, n_factors * 0.8 + 2) inches
                                  Default: None
        save_path (str): Output directory for saving the heatmap (default: 'res/')

    Outputs:
        - Image: {save_path}/7_0.factor_loading_heatmap.png
          Clustered heatmap with:
            - Rows: NMF Factors (Factor1, Factor2, ..., FactorN)
            - Columns: Samples (hierarchically clustered)
            - Color bar: Group annotations above heatmap
            - Legend: Group labels at top-right
            - Colorbar: Average factor loading scale

    Analysis Results:
        - Sample grouping patterns: Hierarchical clustering reveals which samples have
          similar intercellular communication profiles
        - Condition-specific factors: Identify factors that are preferentially activated
          in specific experimental conditions
        - Factor prioritization: Use condition-specific activation to select factors
          for downstream analysis (Step 8)
        - Quality control: Verify samples cluster by expected biological groups

    Important Notes:
        - This is a pseudobulk summary - for spatial detail, use Step 7 (runplot_liana_factorscore)
        - Sample clustering may reveal batch effects or unexpected sample groupings
        - group_key allows flexible annotation independent of aggregation
        - Auto-sizing ensures readable figures regardless of sample/factor count
        - Complements spatial visualization with quantitative sample-level comparison

    Returns:
        None
    """
    import liana as li
    import decoupler as dc

    lrdata = sc.read_h5ad(filename)
    os.makedirs(save_path, exist_ok=True)

    # Extract NMF loadings (LR pairs x Factors)
    lr_loadings = li.ut.get_variable_loadings(lrdata, varm_key='NMF_H').set_index('index')

    # Create AnnData with NMF factor scores (Observations x Factors)
    nmfdata = sc.AnnData(
        X=lrdata.obsm['NMF_W'].copy(),
        obs=lrdata.obs,
        var=pd.DataFrame(index=lr_loadings.columns),
        uns=lrdata.uns,
        obsm={'spatial': lrdata.obsm['spatial']}
    )

    # Pseudobulk aggregation: aggregate factor scores by sample (mean)
    nmfbulk = dc.pp.pseudobulk(
        nmfdata,
        sample_col=sample_key,
        groups_col=None,
        mode='mean',
    )

    # Auto-calculate figure dimensions based on data
    n_samples = nmfbulk.n_obs
    n_factors = nmfbulk.n_vars

    # Width: base + per-sample width
    BASE_WIDTH = 2.5
    WIDTH_PER_SAMPLE = 1.0
    MIN_WIDTH = 4

    # Height: base + per-factor height
    BASE_HEIGHT = 2.5
    HEIGHT_PER_FACTOR = 0.7
    MIN_HEIGHT = 4

    fig_width = width if width is not None else max(MIN_WIDTH, BASE_WIDTH + n_samples * WIDTH_PER_SAMPLE)
    fig_height = height if height is not None else max(MIN_HEIGHT, BASE_HEIGHT + n_factors * HEIGHT_PER_FACTOR)

    print(f"   Creating factor loading heatmap...")
    print(f"   Data: {n_samples} samples × {n_factors} factors")
    print(f"   Figure size: {fig_width:.1f} × {fig_height:.1f} inches")

    # Use group_key for annotations if specified, otherwise use sample_key
    annotation_key = group_key if group_key is not None else sample_key

    # Create heatmap
    create_factor_loading_heatmap(
        nmfbulk,
        sample_col=sample_key,
        group_col=annotation_key,
        figsize=(fig_width, fig_height),
        save_path=save_path,
        filename='7_0.factor_loading_heatmap.png'
    )

    return None


def runplot_liana_loadings(
    filename: str,
    organism: Literal['human', 'mouse'] = 'human',
    geneset: Literal['progeny', 'hallmark'] = 'progeny',
    th_morans:int = 0,
    p_th:float = 0.05,
    min_n: int = 5,
    width: Optional[int] = None,
    height: Optional[int] = None,
    save_path: str = 'res/',
    genept_embeddings_path: Optional[str] = None,
    ) -> None:
    """
    Part 2: CCI Analysis with NMF - Step 8. Ligand-Receptor Pattern Analysis (Loadings; NMF)

    Analyzes NMF loadings to identify which ligand-receptor (LR) pairs contribute to each
    intercellular communication pattern (factor). Loadings represent the importance of each
    LR interaction for a specific factor. This step also performs pathway enrichment analysis
    to characterize the biological processes associated with each factor.

    NMF Loadings Concept:
        - Matrix Dimensions: Ligand-Receptor Pairs × Factors
        - Loading = Importance of LR pair for that factor (higher = more important)
        - Filtered by Bivariate Moran's R significance (spatial co-localization)
        - Annotated with cell type-specific spatially variable genes (ctSVG)

    Filtering Criteria (Significant LIANA):
        - morans > th_morans (default: >0)
          Overall spatial co-clustering score (positive = co-localized)
        - pval < p_th (default: <0.05)
          Statistical significance of spatial co-localization

    Pathway Enrichment Analysis:
        - Uses filtered significant LR pairs for each factor
        - Identifies enriched biological pathways (PROGENy, Reactome, etc.)
        - Provides biological interpretation of intercellular patterns
        - Significance threshold: adj_pval < 0.05

    Workflow Position:
        - Part 2 analysis (CCI with NMF)
        - Step 8: Ligand-receptor loadings and pathway enrichment
        - Follows Step 7 (factor score visualization and factor selection)
        - Prerequisite for Step 9 (quadrant plot and interest cluster analysis)
        - Requires ONE selected factor from Step 7

    Data Requirements:
        - Uses lrdata.h5ad from Step 6 (run_lianap)
        - Requires NMF loadings matrix in lrdata
        - Requires Bivariate Moran's R results in lrdata
        - Requires ctSVG annotations for ligands and receptors

    Args:
        filename (str): Path to lrdata.h5ad file (output from run_lianap)
        organism (Literal['human', 'mouse']): Organism for pathway annotation (default: 'human')
        geneset (Literal['progeny', 'hallmark']): Pathway geneset to use for enrichment analysis
                                                   (default: 'progeny')
            - 'progeny': 14 signaling pathways (Androgen, EGFR, Estrogen, Hypoxia, JAK-STAT,
                         MAPK, NFkB, p53, PI3K, TGFb, TNFa, Trail, VEGF, WNT)
            - 'hallmark': 50 hallmark gene sets from MSigDB (broader biological processes)
        th_morans (float): Minimum Moran's R threshold (default: 0)
        p_th (float): P-value significance threshold (default: 0.05)
        min_n (int): Minimum number of targets per source (pathway) required for analysis.
                     Default is 5. For single-cell resolution data with limited gene panels
                     or hallmark geneset with small LR overlap, use lower values like 1-3 to avoid
                     AssertionError when gene overlap is insufficient.
        width (int, optional): Figure width in inches for heatmap. If None, auto-calculated
                               based on number of pathways (~0.5 inch per pathway). Default: None
        height (int, optional): Figure height in inches for heatmap. If None, auto-calculated
                                based on number of factors (~0.5 inch per factor). Default: None
        save_path (str): Output directory for saving plots and results (default: 'res/')
        genept_embeddings_path (str, optional): Path to GenePT embeddings pickle file.
            Path resolution priority:
            1. This parameter (if provided)
            2. GENEPT_EMBEDDINGS_PATH environment variable (if set)
            3. ~/.cache/genept/embeddings.pickle (auto-downloaded from Zenodo if needed)

            GenePT provides semantic similarity scores between ligand-receptor pairs
            based on gene embeddings trained on NCBI/UniProt descriptions.
            Reference: Chen & Zou (2024) GenePT, Nature Biomedical Engineering.
            Default: None (uses auto-download to default location)

    Outputs:
        - Image: {save_path}/8.loadings_NMF.png
          Heatmap showing NMF loadings (LR pairs × Factors)
          Higher values indicate greater importance of LR pair for that factor

        - CSV: {save_path}/sig_liana.csv
          Filtered significant ligand-receptor interactions
          Columns:
            - interaction: Ligand-receptor pair name (e.g., "Ligand_Receptor")
            - ligand: Ligand gene name
            - receptor: Receptor gene name
            - ligand_ctSVG: Cell types where ligand is spatially variable
            - receptor_ctSVG: Cell types where receptor is spatially variable
            - morans: Bivariate Moran's R value (spatial co-clustering score)
            - pval: P-value for spatial significance
            - min_mean_moransr: Minimum mean Moran's R across spots
            - Factor_0, Factor_1, ..., Factor_N: NMF loading values per factor
            - genept_score: GenePT embedding cosine similarity (0-1, higher = more similar)
                           NaN if embeddings not available or gene not found.
                           Auto-downloaded from Zenodo on first use if needed.

        - CSV: {save_path}/sig_liana_pathway_factor.csv
          Significant pathway enrichments for each factor (adj_pval < 0.05)
          Columns:
            - factor: Factor identifier (e.g., "Factor_0")
            - pathway: Pathway name (PROGENy, Reactome, etc.)
            - pval: Raw p-value
            - adj_pval: FDR-adjusted p-value
          Rows sorted by adj_pval (most significant first)

        - Image: {save_path}/8.pathway_heatmap.png
          Heatmap showing pathway enrichment scores across factors
          Rows: Pathways
          Columns: Factors
          Values: -log10(p-value) with significance markers

    Analysis Results:
        - Identification of LR pairs driving intercellular patterns: Determine which
          ligand-receptor interactions are most important for each NMF factor
        - Spatial co-localization validation: Filter LR pairs by Moran's R significance
          to ensure spatial relevance
        - Cell type association: Annotate LR pairs with ctSVG to identify which cell
          types are involved in signaling
        - Biological interpretation: Pathway enrichment provides functional context
          for intercellular communication patterns
        - Foundation for interest cluster analysis: Filtered sig_liana.csv used in
          Step 9 for quadrant plot and interest cluster identification

    Important Notes:
        - Moran's R filtering ensures only spatially co-localized LR pairs are included
        - ctSVG annotations help identify cell type-specific signaling
        - Pathway enrichment uses LR pairs from each factor independently
        - sig_liana.csv is the primary output for downstream analysis (Step 9)
        - Higher loadings indicate greater contribution to that factor's pattern
        - Multiple filters ensure high-quality, biologically relevant interactions

    Returns:
        None
    """

    # Dynamic sizing constants for pathway heatmap
    BASE_WIDTH = 4
    BASE_HEIGHT = 3
    WIDTH_PER_PATHWAY = 0.2
    HEIGHT_PER_FACTOR = 0.5

    lrdata = sc.read_h5ad(filename)
    os.makedirs(save_path, exist_ok=True)

    # 2. lr_loadings and sig_liana
    anno_sig_liana = res_liana_loadings(lrdata, th_morans=th_morans, p_th=p_th, organism=organism, geneset=geneset, plot=True, save_path=save_path)

    # 2.5. Add GenePT embedding-based L-R similarity scores
    scorer = _get_genept_scorer()
    anno_sig_liana = scorer.score_dataframe(
        anno_sig_liana,
        ligand_col="ligand",
        receptor_col="receptor",
        score_col="genept_score",
        embeddings_path=genept_embeddings_path,
    )

    anno_sig_liana.to_csv(f"{save_path}/sig_liana.csv")

    # 3. enrich_pathway_factor
    res_factor_pathway = enrich_pathway_factor(anno_sig_liana, organism=organism, geneset=geneset, min_n=min_n)
    # res_factor_pathway.to_csv(f"{save_path}/res_liana_pathway_factor.csv")
    sig_factor_pathway = res_factor_pathway.query('adj_pval < 0.05')
    sig_factor_pathway = sig_factor_pathway.sort_values('adj_pval')
    sig_factor_pathway.to_csv(f"{save_path}/sig_liana_pathway_factor.csv")

    # Calculate number of factors and pathways for dynamic sizing
    n_factors = res_factor_pathway['factor'].nunique()
    n_pathways = res_factor_pathway['pathway'].nunique()

    # Auto-calculate dimensions if not specified
    fig_width = width if width is not None else max(BASE_WIDTH, n_pathways * WIDTH_PER_PATHWAY)
    fig_height = height if height is not None else max(BASE_HEIGHT, n_factors * HEIGHT_PER_FACTOR)

    create_heatmap(res_factor_pathway,
               index_key="factor",
               column_key='pathway',
               label='pval',
               figsize=(fig_width, fig_height),
               cbar_label='Enrichment Score',
               significance_level=p_th,
               max_value=10,
               save_path = save_path)

    return None


def plot_liana_nmf(
    interest_celltypes: list,
    sel_factor: str,
    n_top_label: int = 10,
    width: Optional[int] = None,
    height: Optional[int] = None,
    save_path: str = 'res/',
    ) -> None:
    """
    Part 2: CCI Analysis with NMF - Step 9. Interest Cluster Analysis (Quadrant Plot)

    Generates quadrant plot to identify ligand-receptor (LR) pairs most relevant to
    interest clusters. Combines NMF factor loadings (factor importance) with Bivariate
    Moran's R (spatial co-localization) to prioritize LR interactions involving
    interest cell types.

    Quadrant Plot Concept:
        - X-axis: Selected factor loading (NMF importance for chosen factor)
        - Y-axis: Bivariate Moran's R (spatial co-localization strength)
        - Combined Score: factor_loading × morans_R (prioritizes LR pairs)
        - Top-right quadrant: High factor importance AND high spatial co-localization
          (most biologically relevant LR pairs)

    Interest Cluster Filtering:
        - Filters LR pairs where ligand_ctSVG OR receptor_ctSVG contains interest cell types
        - ctSVG = cell type-specific spatially variable genes
        - Ensures LR pairs are relevant to biological question (interest clusters)
        - Combined score ranks filtered pairs by biological importance

    Quadrant Interpretation:
        - Top-right (high loading, high Moran's R): High-confidence LR pairs with
          strong factor contribution and spatial co-localization
        - Top-left (low loading, high Moran's R): Spatially co-localized but not
          important for selected factor
        - Bottom-right (high loading, low Moran's R): Important for factor but
          spatially independent
        - Bottom-left (low loading, low Moran's R): Low relevance for selected factor

    Workflow Position:
        - Part 2 analysis (CCI with NMF)
        - Step 9: Interest cluster analysis and LR pair prioritization
        - Follows Step 8 (ligand-receptor loadings and pathway enrichment)
        - Prerequisite for Step 10-11 (spatial and cluster-level LR pair visualization)
        - Requires ONE selected factor and interest cell types

    Data Requirements:
        - Uses sig_liana.csv from Step 8 (runplot_liana_loadings)
        - Requires selected factor from Step 7 (runplot_liana_factorscore)
        - Requires interest cell types identified from Part 1 analysis
        - Requires ctSVG annotations in sig_liana.csv

    Args:
        interest_celltypes (list): List of cell type names to focus on
                                   (e.g., ['Macrophage', 'Epithelial', 'Fibroblast'])
        sel_factor (str): Selected factor name (e.g., 'Factor_0', 'Factor_1')
                         Must match column name in sig_liana.csv
        n_top_label (int): Number of top LR pairs to label on quadrant plot (default: 10)
        width (int, optional): Figure width in inches. If None, auto-calculated based on
                               number of data points and labels (~10 base + adjustments).
                               Default: None
        height (int, optional): Figure height in inches. If None, auto-calculated based on
                                number of data points and labels (~8 base + adjustments).
                                Default: None
        save_path (str): Output directory for saving plots and results (default: 'res/')

    Outputs:
        - Image: {save_path}/9.quadrant_plot_NMF.png
          Quadrant plot showing relationship between factor loading and Moran's R
          Points: All significant LR pairs (gray)
          Highlighted points: Interest cluster LR pairs (colored)
          Labels: Top N LR pairs by combined score (factor × morans)
          Quadrant lines: Median values of factor loading and Moran's R

        - CSV: {save_path}/interest_anno_sig_liana.csv
          Filtered LR pairs involving interest cell types
          Columns:
            - All columns from sig_liana.csv (Step 8)
            - Sorted by combined score (descending)
          Combined score = sel_factor × morans (not saved as column, used for sorting)

    Analysis Results:
        - Prioritization of LR pairs: Identify most relevant ligand-receptor interactions
          for interest clusters using combined factor and spatial scores
        - Interest cluster validation: Confirm selected factor captures biology of
          interest clusters through ctSVG filtering
        - Spatial relevance confirmation: High Moran's R ensures LR pairs are spatially
          co-localized, not just transcriptionally correlated
        - Top candidate identification: Top N labeled pairs represent highest-confidence
          interactions for downstream validation (Steps 10-11)
        - Foundation for visualization: interest_anno_sig_liana.csv used in Steps 10-11
          for spatial and cluster-level LR pair plots

    Important Notes:
        - Interest cell types should come from Part 1 analysis (Steps 2, 4, 5)
        - Selected factor should be chosen from Step 7 based on cluster association
        - Combined score (factor × morans) prioritizes LR pairs holistically
        - Top-right quadrant LR pairs are highest confidence for validation
        - ctSVG filtering ensures biological relevance to interest clusters
        - n_top_label controls how many LR pairs are labeled (avoid overcrowding)

    Returns:
        None
    """

    sig_liana = pd.read_csv(f'{save_path}/anno_sig_liana.csv', index_col = 0)

    pattern = '|'.join(interest_celltypes)

    interest_sig_liana = sig_liana[
        sig_liana['ligand_ctSVG'].str.contains(pattern, na=False) | 
        sig_liana['receptor_ctSVG'].str.contains(pattern, na=False)
    ]
    
    interest_sig_liana['combinedscore'] = interest_sig_liana[sel_factor] * interest_sig_liana['morans']
    interest_sig_liana = interest_sig_liana.sort_values('combinedscore', ascending=False)
    interest_sig_liana = interest_sig_liana.drop('combinedscore', axis=1)
    # interest_sig_liana.to_csv(f'{save_path}/full_interest_anno_sig_liana.csv')

    save_interest_sig_liana = interest_sig_liana.iloc[0:20]
    # save_interest_sig_liana.to_csv(f'{save_path}/interest_anno_sig_liana.csv')

    # Auto-calculate figure dimensions if not specified
    BASE_WIDTH = 10
    BASE_HEIGHT = 8
    LABEL_WIDTH_FACTOR = 0.3   # Additional width per label beyond 10
    LABEL_HEIGHT_FACTOR = 0.2  # Additional height per label beyond 10
    POINTS_THRESHOLD = 500     # Data points threshold for size increase

    n_points = len(sig_liana)

    if width is None:
        width = BASE_WIDTH + max(0, (n_top_label - 10) * LABEL_WIDTH_FACTOR)
        if n_points > POINTS_THRESHOLD:
            width += 2

    if height is None:
        height = BASE_HEIGHT + max(0, (n_top_label - 10) * LABEL_HEIGHT_FACTOR)
        if n_points > POINTS_THRESHOLD:
            height += 1

    plot_quadrant(
        sig_liana,
        interest_sig_liana,
        sel_factor = sel_factor,
        n_top_label = n_top_label,
        figsize=(width, height),
        save_path=save_path
    )

    return None


def plot_liana_spatial_interections(
    filename: str,
    sel_interactions: List[str],
    cluster_key: Optional[str] = None,
    show_cluster: bool = True,
    sample_key: Optional[str] = None,
    width: int=6,
    height: int=6,
    save_path: str = 'res/',
    ) -> None:
    """
    Part 3: LR Pair Plots - Step 10. Spatial Visualization of LR Interaction Scores

    Visualizes the spatial distribution of ligand-receptor (LR) interaction scores across
    tissue observations (spots/cells). Each selected LR pair is displayed as a separate
    spatial plot showing where interactions are predicted to occur based on LIANA scores.

    LR Interaction Score Concept:
        - Score Range: 0-1 (normalized LIANA interaction score)
        - Higher values: Stronger predicted ligand-receptor interaction at that location
        - Spatial Pattern: Reveals where in the tissue LR communication is most active
        - Multiple LR Pairs: Side-by-side comparison of different interaction patterns

    Visualization Details:
        - Color Map: 'magma' (dark = low score, bright = high score)
        - Value Range: 0-1 (vmax=1) for consistent comparison across LR pairs
        - Point Size: 1.4 (optimized for spatial resolution)
        - Layout: Grid with ncols = number of selected interactions

    Multi-Sample Support:
        - When sample_key is provided, generates separate plots for each sample
        - Output filenames include sample identifier (e.g., 10.spatial_plot_interections_{sample}.png)
        - When sample_key is None, uses original single-sample behavior

    Workflow Position:
        - Part 3 analysis (LR pair plots)
        - Step 10: Spatial visualization of LR interaction patterns
        - Follows Step 9 (quadrant plot and interest cluster filtering)
        - Parallel with Step 11 (cluster-level LR interaction analysis)
        - Uses top candidates from interest_anno_sig_liana.csv

    Data Requirements:
        - Uses lrdata.h5ad from Step 6 (run_lianap)
        - Requires LR interaction scores stored as observations in lrdata
        - Requires spatial coordinates in lrdata.obsm['spatial']
        - Selected interactions must exist as columns/observations in lrdata

    Args:
        filename (str): Path to lrdata.h5ad file (output from run_lianap)
        sel_interactions (List[str]): List of LR interaction names to visualize
                                      (e.g., ["TGFB1_TGFBR1", "VEGFA_FLT1"])
                                      Names must match lrdata observation names
        cluster_key (str, optional): Column name in lrdata.obs containing cluster/region assignments.
                                     Used when show_cluster=True to display cluster as first subplot.
                                     Default: None
        show_cluster (bool): If True and cluster_key is provided, displays cluster/region annotation
                             as the first subplot before LR interaction plots. Useful for
                             spatial context when viewing interaction patterns. Default: True
        sample_key (str, optional): Column name in lrdata.obs containing sample identifiers.
                                    If provided, generates separate plots for each sample.
                                    Default: None (single sample mode)
        width (int): Figure width in inches (default: 6)
        height (int): Figure height in inches (default: 6)
        save_path (str): Output directory for saving the plot (default: 'res/')

    Outputs:
        Single sample mode (sample_key=None):
            - Image: {save_path}/10.spatial_plot_interections.png

        Multi-sample mode (sample_key provided):
            - Image: {save_path}/10.spatial_plot_interections_{sample_name}.png (per sample)

    Analysis Results:
        - Spatial pattern identification: Visualize where LR interactions occur in tissue
        - Regional specificity: Identify tissue regions with high interaction activity
        - Spatial co-localization validation: Confirm predictions from Bivariate Moran's R
        - Multi-LR comparison: Compare spatial patterns across different LR pairs
        - Biological validation target: High-score regions represent areas for
          experimental validation (e.g., IF, ISH, spatial proteomics)

    Important Notes:
        - Selected interactions should come from Step 9 top candidates
        - Interaction names must exactly match lrdata observation names
        - Spatial patterns should align with tissue biology and histology
        - High-score regions indicate predicted active LR communication
        - Use with Step 11 for comprehensive LR pair characterization
        - Multiple LR pairs allow pattern comparison and validation

    Returns:
        None
    """

    lrdata = sc.read_h5ad(filename)
    os.makedirs(save_path, exist_ok=True)

    # Set figure size
    plt.rcParams['figure.figsize'] = (width, height)
    plt.rcParams['figure.dpi'] = 300

    # Flip y-axis for correct spatial orientation
    import numpy as np
    lrdata.obsm['spatial_plot'] = lrdata.obsm['spatial'].copy()
    lrdata.obsm['spatial_plot'][:, 1] = -1 * lrdata.obsm['spatial_plot'][:, 1]

    # Determine plot colors: add cluster as first subplot if show_cluster is True
    if show_cluster and cluster_key is not None:
        plot_colors = [cluster_key] + sel_interactions
    else:
        plot_colors = sel_interactions

    if sample_key is not None and sample_key in lrdata.obs.columns:
        # Multi-sample mode: plot each sample separately
        samples = lrdata.obs[sample_key].unique()
        print(f"   Multi-sample mode: plotting {len(samples)} samples separately")

        for sample_name in samples:
            lrdata_sample = lrdata[lrdata.obs[sample_key] == sample_name].copy()
            print(f"      Plotting sample '{sample_name}': {lrdata_sample.n_obs} observations")

            # Use sc.pl.embedding instead of sc.pl.spatial for better compatibility
            # sc.pl.spatial requires uns['spatial'] with library_id structure (Visium-specific)
            # sc.pl.embedding only requires obsm['spatial'] coordinates
            fig = sc.pl.embedding(
                lrdata_sample,
                basis='spatial_plot',
                color=plot_colors,
                size=70,
                vmax=1,
                cmap='magma',
                ncols=len(plot_colors),
                show=False,
                return_fig=True
            )
            output_filename = f'{save_path}/10.spatial_plot_interections_{sample_name}.png'
            fig.savefig(output_filename, dpi=300, bbox_inches='tight')
            print(f'      Saved: {output_filename}')
            plt.close(fig)
    else:
        # Single sample mode
        # Use sc.pl.embedding instead of sc.pl.spatial for better compatibility
        fig = sc.pl.embedding(
            lrdata,
            basis='spatial_plot',
            color=plot_colors,
            size=70,
            vmax=1,
            cmap='magma',
            ncols=len(plot_colors),
            show=False,
            return_fig=True
        )
        output_filename = f'{save_path}/10.spatial_plot_interections.png'
        fig.savefig(output_filename, dpi=300, bbox_inches='tight')
        print(f'{output_filename}')

        plt.show()



def plot_liana_interections(
    filename: str,
    cluster_key: str,
    sel_interactions: List[str],
    sample_key: Optional[str] = None,
    p_th: float = 0.05,
    width: int=14,
    height: int=6,
    save_path: str = 'res/',
    ) -> None:
    """
    Part 3: LR Pair Plots - Step 11. Cluster-Level LR Interaction Analysis

    Analyzes and visualizes ligand-receptor (LR) interaction patterns at the cluster level.
    For each selected LR pair, generates comprehensive visualization showing:
    1) Spatial distribution of interaction scores
    2) Cluster-level aggregated scores
    3) Statistical significance of cluster enrichment

    This final step provides both spatial context (where interactions occur) and
    cluster-level quantification (which clusters show significant LR activity).

    Cluster-Level Analysis:
        - Aggregates LR interaction scores by cluster (e.g., median or mean)
        - Tests for significant enrichment in specific clusters
        - Provides statistical validation of predicted LR communication patterns
        - Links LR pairs to specific tissue regions/cell populations

    Statistical Testing:
        - Significance Threshold: p_th (default: 0.05)
        - Test: Cluster enrichment for LR interaction scores
        - Purpose: Identify clusters with significantly elevated LR activity
        - Interpretation: Low p-value indicates cluster-specific LR communication

    Multi-Sample Support:
        - When sample_key is provided, generates separate plots for each sample
        - Output filenames include sample identifier (e.g., 11.lr_interections_{sample}.png)
        - When sample_key is None, uses original single-sample behavior

    Workflow Position:
        - Part 3 analysis (LR pair plots)
        - Step 11: Final cluster-level LR interaction characterization
        - Follows Step 10 (spatial visualization of LR pairs)
        - Completes the full CCI analysis workflow
        - Uses top candidates from interest_anno_sig_liana.csv (Step 9)

    Data Requirements:
        - Uses lrdata.h5ad from Step 6 (run_lianap)
        - Requires LR interaction scores in lrdata
        - Requires cluster annotations in lrdata.obs[cluster_key]
        - Requires spatial coordinates in lrdata.obsm['spatial']
        - Selected interactions must exist in lrdata

    Args:
        filename (str): Path to lrdata.h5ad file (output from run_lianap)
        cluster_key (str): Column name in lrdata.obs containing cluster assignments
        sel_interactions (List[str]): List of LR interaction names to analyze
                                      (e.g., ["TGFB1_TGFBR1", "VEGFA_FLT1"])
                                      Names must match lrdata observation names
        sample_key (str, optional): Column name in lrdata.obs containing sample identifiers.
                                    If provided, generates separate plots for each sample.
                                    Default: None (single sample mode)
        p_th (float): P-value significance threshold for cluster enrichment (default: 0.05)
        width (int): Figure width in inches (default: 14)
        height (int): Figure height in inches (default: 6)
        save_path (str): Output directory for saving plots (default: 'res/')

    Outputs:
        Single sample mode (sample_key=None):
            - Image: {save_path}/11.lr_interections.png

        Multi-sample mode (sample_key provided):
            - Image: {save_path}/11.lr_interections_{sample_name}.png (per sample)

    Analysis Results:
        - Cluster-specific LR activity: Identify which clusters exhibit significant
          LR communication for each selected interaction
        - Spatial-cluster integration: Link spatial patterns (Step 10) with cluster
          identities for biological interpretation
        - Statistical validation: Confirm predicted LR interactions are significantly
          enriched in biologically relevant clusters
        - Experimental validation targets: Significant cluster-LR pairs represent
          high-confidence targets for validation experiments
        - Comprehensive LR characterization: Combines spatial, cluster, and
          statistical information for complete LR pair profiling

    Important Notes:
        - Selected interactions should be top candidates from Step 9 quadrant plot
        - Cluster-level analysis validates spatial predictions from Step 10
        - Significance testing ensures LR patterns are not random
        - Results integrate all previous analysis steps (Parts 1-3)
        - High-confidence LR pairs: Significant in cluster analysis AND high spatial
          co-localization (Moran's R) AND high NMF factor loading
        - This is the final analysis step - results inform biological interpretation
          and experimental design

    Workflow Summary (All 11 Steps):
        Part 1 (Before CCI):
          - Step 1: Spatial clustering visualization
          - Step 2: Cell type composition analysis
          - Step 3: Neighborhood enrichment
          - Step 4: Pathway enrichment by cluster
          - Step 5: Spatial pathway-celltype relationships (MISTy)

        Part 2 (CCI with NMF):
          - Step 6: LIANA+ CCI analysis and NMF factorization
          - Step 7: Factor score visualization (select ONE factor)
          - Step 8: Ligand-receptor loadings and pathway enrichment
          - Step 9: Interest cluster quadrant plot

        Part 3 (LR Pair Plots):
          - Step 10: Spatial LR interaction visualization
          - Step 11: Cluster-level LR interaction analysis (THIS STEP)

    Returns:
        None
    """

    lrdata = sc.read_h5ad(filename)
    os.makedirs(save_path, exist_ok=True)

    if sample_key is not None and sample_key in lrdata.obs.columns:
        # Multi-sample mode: plot each sample separately
        samples = lrdata.obs[sample_key].unique()
        print(f"   Multi-sample mode: plotting {len(samples)} samples separately")

        for sample_name in samples:
            lrdata_sample = lrdata[lrdata.obs[sample_key] == sample_name].copy()
            print(f"      Plotting sample '{sample_name}': {lrdata_sample.n_obs} observations")

            plot_interaction(
                lrdata_sample,
                sel_interactions=sel_interactions,
                cluster_key=cluster_key,
                p_th=p_th,
                figsize=(width, height),
                save_path=save_path,
                filename_suffix=f"_{sample_name}"
            )
    else:
        # Single sample mode: original behavior
        plot_interaction(
            lrdata,
            sel_interactions=sel_interactions,
            cluster_key=cluster_key,
            p_th=p_th,
            figsize=(width, height),
            save_path=save_path
        )


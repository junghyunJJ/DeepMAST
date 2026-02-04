# GenePT Scoring Integration Plan for runplot_LIANAp_NMF.py

## Context

### Original Request
Integrate GenePT embedding-based scoring into `runplot_LIANAp_NMF.py` to add a `genept_score` column to `sig_liana.csv`, providing a semantic similarity score between ligand-receptor pairs based on GenePT gene embeddings.

### User Requirements (Confirmed)
1. **Integration Point**: `runplot_liana_loadings()` function (Step 8) - where sig_liana.csv is generated
2. **Path Management**: Environment variable `GENEPT_EMBEDDINGS_PATH` (optional override)
3. **Code Location**: Write new GenePT scorer code directly in runplot_LIANAp_NMF.py (simplified, self-contained version)
4. **Auto-Download**: Automatically download embeddings from Zenodo when not found on first use
5. **Default Cache Location**: `~/.cache/genept/embeddings.pickle`
6. **Download Utility**: New file `mcp_servers/utils/download_genept.py`

### Research Findings

**Target File**: `/Users/jungj2/Dropbox/Metadata/aiagent/DeepMAST/mcp_servers/runplot_LIANAp_NMF.py`

**Key Function** (`runplot_liana_loadings`, lines 777-926):
- Generates `sig_liana.csv` at line 915
- Currently: `anno_sig_liana.to_csv(f"{save_path}/sig_liana.csv")`
- DataFrame has columns: interaction, ligand, receptor, ligand_ctSVG, receptor_ctSVG, morans, pval, min_mean_moransr, Factor_0, Factor_1, ...

**Reference Implementation**: `src/agents/deep_interpreter/tools/genept_scorer.py`
- Singleton pattern with lazy loading
- `score_lr_pairs_batch()` method for batch scoring
- Uses sklearn cosine_similarity
- Normalizes scores to 0-1 range: `(similarity + 1) / 2`
- Handles complex receptor names like "ITGA3_ITGB1" by taking first component

**Reference Download Script**: `scripts/download_genept_embeddings.py`
- Downloads from Zenodo record 10833191
- Zip file: `GenePT_emebdding_v2.zip` (~575MB)
- Target file: `GenePT_gene_protein_embedding_model_3_text.pickle.` (trailing dot in original)
- Extracts and saves as `embeddings.pickle`

---

## Work Objectives

### Core Objective
Add GenePT-based semantic similarity scoring to the LIANA pipeline output with automatic download capability, enabling downstream analysis to leverage gene embedding similarity as an additional prioritization metric without manual setup.

### Deliverables
1. **New file**: `mcp_servers/utils/download_genept.py` - download utility with progress reporting
2. Self-contained GenePT scorer class in `runplot_LIANAp_NMF.py`
3. Modified `runplot_liana_loadings()` function with GenePT scoring integration
4. Updated `sig_liana.csv` output with `genept_score` column

### Definition of Done
- [ ] `mcp_servers/utils/download_genept.py` created with `ensure_genept_embeddings()` function
- [ ] `sig_liana.csv` includes `genept_score` column (0-1 range)
- [ ] Auto-download triggers when embeddings not found at default location
- [ ] Download shows progress (~575MB zip file)
- [ ] Temp files cleaned up after extraction
- [ ] No external DeepMAST imports required
- [ ] Lazy loading prevents slowdown when GenePT not used
- [ ] Missing genes handled gracefully (NaN values)
- [ ] Function parameter allows custom embeddings path

---

## Guardrails

### Must Have
- Automatic download from Zenodo when embeddings not found
- Default cache location: `~/.cache/genept/embeddings.pickle`
- Progress reporting during download (~575MB)
- Cleanup of temp files after extraction
- Idempotent download (skip if file exists and valid)
- Lazy loading of embeddings (only load when scoring is called)
- Environment variable `GENEPT_EMBEDDINGS_PATH` for path override
- Graceful fallback with warning (not error) if download fails
- NaN for missing gene pairs (not median - keeps data honest)
- Handle complex receptor names (e.g., "ITGA3_ITGB1")
- Thread-safe singleton pattern

### Must NOT Have
- No imports from DeepMAST src/ directory
- No hard errors when embeddings unavailable or download fails
- No modification of existing sig_liana.csv column order (add genept_score at end)
- No performance regression for users who don't use GenePT
- No leftover temp files after download

---

## Path Resolution Priority

The `_GenePTScorer` class resolves embeddings path in this order:

1. **Custom path parameter** (if provided to function)
2. **`GENEPT_EMBEDDINGS_PATH` environment variable** (if set)
3. **Default location**: `~/.cache/genept/embeddings.pickle` (auto-download if needed)

---

## Task Flow

```
[Task 1: Create download_genept.py utility]
        |
        v
[Task 2: Add imports to runplot_LIANAp_NMF.py]
        |
        v
[Task 3: Add GenePT scorer class with auto-download]
        |
        v
[Task 4: Modify runplot_liana_loadings() signature]
        |
        v
[Task 5: Add GenePT scoring logic to function body]
        |
        v
[Task 6: Update docstring]
        |
        v
[Task 7: Test manually]
```

---

## Detailed TODOs

### Task 1: Create Download Utility

**File**: `mcp_servers/utils/download_genept.py` (NEW)

**Implementation**:
```python
#!/usr/bin/env python3
"""GenePT embeddings download utility.

Downloads GenePT gene embeddings from Zenodo automatically when needed.

Reference:
    Chen & Zou (2024). GenePT: A Simple But Effective Foundation Model
    for Genes and Cells Built From ChatGPT. Nature Biomedical Engineering.
    https://doi.org/10.1038/s41551-024-01284-6

Source:
    https://zenodo.org/records/10833191
"""

import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlretrieve

logger = logging.getLogger(__name__)

# Zenodo download configuration
ZENODO_RECORD_ID = "10833191"
ZENODO_ZIP_NAME = "GenePT_emebdding_v2.zip"  # Note: typo in original filename
ZENODO_URL = f"https://zenodo.org/records/{ZENODO_RECORD_ID}/files/{ZENODO_ZIP_NAME}?download=1"

# Target file inside the zip (note trailing dot in original filename)
TARGET_PICKLE_NAME = "GenePT_gene_protein_embedding_model_3_text.pickle."

# Expected file size for progress reporting
EXPECTED_SIZE_MB = 575

# Default cache location
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "genept"
DEFAULT_EMBEDDINGS_PATH = DEFAULT_CACHE_DIR / "embeddings.pickle"


def _download_with_progress(url: str, output_path: Path) -> None:
    """Download file with progress reporting.

    Args:
        url: URL to download from
        output_path: Path to save the file
    """
    logger.info(f"Downloading GenePT embeddings from Zenodo...")
    logger.info(f"URL: {url}")
    logger.info(f"Expected size: ~{EXPECTED_SIZE_MB} MB")

    def report_progress(block_num: int, block_size: int, total_size: int) -> None:
        if total_size > 0:
            downloaded = block_num * block_size
            percent = min(100, downloaded * 100 / total_size)
            mb_downloaded = downloaded / (1024 * 1024)
            mb_total = total_size / (1024 * 1024)
            print(f"\rDownloading: {percent:.1f}% ({mb_downloaded:.1f}/{mb_total:.1f} MB)", end="", flush=True)

    urlretrieve(url, output_path, reporthook=report_progress)
    print()  # New line after progress
    logger.info("Download completed!")


def _extract_embeddings(zip_path: Path, output_path: Path) -> None:
    """Extract embeddings pickle from downloaded zip.

    Args:
        zip_path: Path to downloaded zip file
        output_path: Path to save extracted embeddings
    """
    logger.info("Extracting embeddings from zip archive...")

    with zipfile.ZipFile(zip_path, 'r') as zf:
        # Find the target file in the zip
        zip_contents = zf.namelist()
        target_in_zip = None
        for name in zip_contents:
            if name.endswith(TARGET_PICKLE_NAME):
                target_in_zip = name
                break

        if target_in_zip is None:
            raise FileNotFoundError(
                f"Target file '{TARGET_PICKLE_NAME}' not found in zip. "
                f"Zip contents: {zip_contents}"
            )

        # Extract to temp location then move
        with tempfile.TemporaryDirectory() as extract_dir:
            zf.extract(target_in_zip, extract_dir)
            extracted_path = Path(extract_dir) / target_in_zip
            shutil.move(str(extracted_path), str(output_path))

    logger.info(f"Extracted embeddings to: {output_path}")


def _verify_embeddings(path: Path) -> bool:
    """Verify the embeddings file is valid.

    Args:
        path: Path to embeddings file

    Returns:
        True if file appears valid
    """
    if not path.exists():
        return False

    # Check file size (should be around 50MB after extraction)
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb < 10:  # Too small
        logger.warning(f"Embeddings file size ({size_mb:.1f} MB) seems too small")
        return False

    # Try to load and verify structure
    try:
        import pickle
        with open(path, "rb") as f:
            data = pickle.load(f)

        if not isinstance(data, dict):
            logger.warning("Embeddings file doesn't contain expected dict structure")
            return False

        # Check for expected genes
        sample_genes = ["TP53", "BRCA1", "EGFR", "MYC"]
        found = sum(1 for g in sample_genes if g in data or g.upper() in data)
        if found < 2:
            logger.warning(f"Only {found}/4 expected genes found in embeddings")
            return False

        logger.info(f"Verified: {len(data)} gene embeddings available")
        return True

    except Exception as e:
        logger.warning(f"Error verifying embeddings: {e}")
        return False


def ensure_genept_embeddings(cache_dir: Path | str | None = None) -> Path | None:
    """Ensure GenePT embeddings are available, downloading if necessary.

    This function checks if embeddings exist at the specified location.
    If not found, it automatically downloads them from Zenodo.

    Args:
        cache_dir: Optional custom cache directory. If None, uses
                   ~/.cache/genept/embeddings.pickle

    Returns:
        Path to embeddings file if available, None if download failed

    Example:
        >>> path = ensure_genept_embeddings()
        >>> if path:
        ...     with open(path, "rb") as f:
        ...         embeddings = pickle.load(f)
    """
    # Resolve cache directory
    if cache_dir is None:
        cache_path = DEFAULT_EMBEDDINGS_PATH
    else:
        cache_path = Path(cache_dir) / "embeddings.pickle"

    # Check if already exists and valid
    if cache_path.exists():
        if _verify_embeddings(cache_path):
            logger.debug(f"Using cached embeddings: {cache_path}")
            return cache_path
        else:
            logger.warning("Existing embeddings file appears corrupted, re-downloading...")
            cache_path.unlink()

    # Create cache directory
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    # Download and extract
    logger.info("GenePT embeddings not found. Starting automatic download...")
    logger.info(f"Cache location: {cache_path}")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_zip = Path(temp_dir) / ZENODO_ZIP_NAME

        try:
            # Download zip
            _download_with_progress(ZENODO_URL, temp_zip)

            # Extract embeddings
            _extract_embeddings(temp_zip, cache_path)

        except HTTPError as e:
            logger.error(f"HTTP Error downloading embeddings: {e.code} {e.reason}")
            return None
        except URLError as e:
            logger.error(f"Network error downloading embeddings: {e.reason}")
            return None
        except zipfile.BadZipFile as e:
            logger.error(f"Downloaded file is not a valid zip: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to download/extract embeddings: {e}")
            return None

    # Verify downloaded file
    if _verify_embeddings(cache_path):
        logger.info("GenePT embeddings ready to use!")
        return cache_path
    else:
        logger.error("Downloaded embeddings failed verification")
        if cache_path.exists():
            cache_path.unlink()
        return None
```

**Acceptance Criteria**:
- [ ] File created at `mcp_servers/utils/download_genept.py`
- [ ] `ensure_genept_embeddings()` returns Path on success, None on failure
- [ ] Progress is displayed during download
- [ ] Temp files are cleaned up
- [ ] Existing valid files are not re-downloaded
- [ ] Corrupted files trigger re-download

---

### Task 2: Add Required Imports

**Location**: Top of `runplot_LIANAp_NMF.py` (after line 10)

**Changes**:
```python
import pickle
import logging
import warnings
from threading import Lock

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

# Import download utility (relative import within mcp_servers/)
from utils.download_genept import ensure_genept_embeddings, DEFAULT_EMBEDDINGS_PATH
```

**Note**: `numpy` and `pandas` are already imported. `sklearn` is a dependency via liana.

**Acceptance Criteria**:
- [ ] All imports added without conflicts
- [ ] No duplicate imports
- [ ] Download utility imported correctly

---

### Task 3: Add GenePT Scorer Class (Updated with Auto-Download)

**Location**: After imports, before first function definition (around line 13)

**Implementation**:
```python
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
```

**Acceptance Criteria**:
- [ ] Class is self-contained (minimal external imports)
- [ ] Singleton pattern implemented correctly
- [ ] Auto-download triggered when embeddings not found
- [ ] Path resolution follows documented priority
- [ ] Lazy loading works (embeddings only loaded on first score call)
- [ ] Missing file results in warning, not error
- [ ] Complex receptor names handled

---

### Task 4: Modify Function Signature

**Location**: `runplot_liana_loadings()` function definition (line 777)

**Current**:
```python
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
    ) -> None:
```

**Modified**:
```python
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
```

**Acceptance Criteria**:
- [ ] New parameter added with `Optional[str] = None` default
- [ ] Parameter position is at end (before closing paren)
- [ ] Type hint is correct

---

### Task 5: Add GenePT Scoring Logic

**Location**: After line 914 (after `anno_sig_liana = res_liana_loadings(...)`)

**Current** (lines 913-915):
```python
    # 2. lr_loadings and sig_liana
    anno_sig_liana = res_liana_loadings(lrdata, th_morans=th_morans, p_th=p_th, organism=organism, geneset=geneset, plot=True, save_path=save_path)
    anno_sig_liana.to_csv(f"{save_path}/sig_liana.csv")
```

**Modified**:
```python
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
```

**Acceptance Criteria**:
- [ ] GenePT scoring called before CSV save
- [ ] Uses the new `genept_embeddings_path` parameter
- [ ] Column name is `genept_score`
- [ ] Graceful handling if embeddings not available

---

### Task 6: Update Docstring

**Location**: Docstring of `runplot_liana_loadings()` (lines 788-901)

**Additions**:

1. Add to Args section (after `save_path`):
```python
        genept_embeddings_path (str, optional): Path to GenePT embeddings pickle file.
            Path resolution priority:
            1. This parameter (if provided)
            2. GENEPT_EMBEDDINGS_PATH environment variable (if set)
            3. ~/.cache/genept/embeddings.pickle (auto-downloaded from Zenodo if needed)

            GenePT provides semantic similarity scores between ligand-receptor pairs
            based on gene embeddings trained on NCBI/UniProt descriptions.
            Default: None (uses auto-download to default location)
```

2. Update CSV output description (around line 852):
```python
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
                           NaN if embeddings not available or gene not found
                           Auto-downloaded from Zenodo on first use if needed
```

**Acceptance Criteria**:
- [ ] New parameter documented in Args
- [ ] Path resolution priority documented
- [ ] Auto-download behavior documented
- [ ] Output column documented
- [ ] GenePT reference included

---

### Task 7: Manual Testing

**Test Scenarios**:

1. **First run (auto-download)**:
   ```bash
   # Clear any existing cache
   rm -rf ~/.cache/genept/
   unset GENEPT_EMBEDDINGS_PATH
   # Run LIANA pipeline - should auto-download embeddings
   # Verify: download progress shown, genept_score column populated
   ```

2. **Subsequent run (cached)**:
   ```bash
   # Run again - should use cached embeddings (no download)
   # Verify: no download messages, genept_score column populated
   ```

3. **With environment variable override**:
   ```bash
   export GENEPT_EMBEDDINGS_PATH=/custom/path/embeddings.pickle
   # Run LIANA pipeline - should use env var path
   ```

4. **With custom path parameter**:
   ```python
   runplot_liana_loadings(
       filename="lrdata.h5ad",
       genept_embeddings_path="/custom/path/embeddings.pickle"
   )
   ```

5. **Network failure graceful handling**:
   ```bash
   # Simulate no network (disconnect or block zenodo.org)
   rm -rf ~/.cache/genept/
   # Run LIANA pipeline - should warn and add NaN column
   # Verify: warning logged, genept_score column is all NaN
   ```

6. **Verify output CSV**:
   - Check `sig_liana.csv` has `genept_score` column
   - Verify scores are in 0-1 range
   - Verify missing genes have NaN

**Acceptance Criteria**:
- [ ] Auto-download works on first run
- [ ] Cached embeddings used on subsequent runs
- [ ] Env var override works
- [ ] Custom path parameter works
- [ ] Network failure handled gracefully
- [ ] Scores are reasonable (0-1 range)
- [ ] Pipeline completes successfully in all scenarios

---

## Commit Strategy

### Commit 1: Add download utility
```
feat(mcp): add GenePT embeddings download utility

- Create mcp_servers/utils/download_genept.py
- Downloads from Zenodo record 10833191 (~575MB zip)
- Extracts embeddings to ~/.cache/genept/embeddings.pickle
- Shows download progress, verifies file integrity
- Idempotent: skips download if valid file exists
```

### Commit 2: Integrate GenePT scoring with auto-download
```
feat(mcp): add GenePT scoring with auto-download to sig_liana.csv

- Add self-contained _GenePTScorer class with lazy loading
- Integrate auto-download when embeddings not found
- Add genept_score column to sig_liana.csv (0-1 cosine similarity)
- Path resolution: custom param > env var > default with auto-download
- Graceful skip with warning if download fails
- Handle complex receptor names (e.g., "ITGA3_ITGB1")

Reference: Chen & Zou (2024) GenePT, Nature Biomedical Engineering
```

---

## Success Criteria

| Criterion | Measurement |
|-----------|-------------|
| Auto-Download | Embeddings download automatically on first use |
| Caching | Downloaded embeddings reused on subsequent runs |
| Functional | `sig_liana.csv` contains `genept_score` column |
| Graceful Degradation | Pipeline runs without error when download fails |
| Performance | No slowdown when GenePT not configured (lazy loading) |
| Code Quality | Self-contained, minimal external imports |
| Documentation | Docstring updated with new parameter and auto-download |
| Testable | Manual test scenarios documented and executable |

---

## Implementation Notes

### Why Automatic Download?
- Zero-configuration experience for users
- Eliminates setup friction (no manual download step)
- Embeddings are publicly available on Zenodo
- ~575MB is acceptable for one-time download

### Why ~/.cache/genept/?
- Standard location for user-level cache on Unix/macOS
- Persists across project directories
- User-writable without elevated permissions
- Easy to clear if needed

### Why Keep Environment Variable?
- Backward compatibility with existing setups
- Allows system administrators to pre-provision embeddings
- Supports shared storage in HPC environments
- Allows custom paths for testing

### Download Safety
- Uses HTTPS to Zenodo (trusted source)
- Verifies file integrity after download
- Cleans up temp files on failure
- Idempotent: won't re-download if file exists and valid

### Why Singleton Pattern?
- Embeddings file can be large (~100MB+ after extraction)
- Loading once and reusing prevents memory waste
- Thread-safe for potential parallel use

### Why Lazy Loading?
- Most MCP tool calls don't need GenePT scoring
- Only load when `score_dataframe()` is actually called
- Keeps startup time fast

### Why NaN Instead of Median for Missing Genes?
- Keeps data honest - user knows which scores are real
- Median would falsely suggest a computed score
- Downstream analysis can filter or impute as needed

### Complex Receptor Handling
- LIANA sometimes has complex receptors like "ITGA3_ITGB1"
- Try full name first, fall back to first component
- Matches behavior of existing `genept_scorer.py`

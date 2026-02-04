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
    logger.info("Downloading GenePT embeddings from Zenodo...")
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

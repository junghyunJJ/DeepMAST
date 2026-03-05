#!/usr/bin/env python3
"""Download GWAS Catalog bulk TSV and convert to Parquet.

Downloads the 'alternative' (all associations) TSV from the GWAS Catalog,
normalises key columns, and saves as two Parquet files under gwas_data/:

    gwas_data/associations.parquet  – main association table
    gwas_data/traits.parquet        – unique EFO ID → trait name mapping

Usage:
    python skills/gwas-database/scripts/download_gwas_bulk.py
"""

from __future__ import annotations

import io
import logging
import re
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "gwas_data"

# FTP bulk download – ontology-annotated version includes MAPPED_TRAIT_URI
ASSOCIATIONS_URL = (
    "https://ftp.ebi.ac.uk/pub/databases/gwas/releases/latest/"
    "gwas-catalog-associations_ontology-annotated-full.zip"
)
TIMEOUT = 600  # 10 minutes for ~58 MB zip


def download_tsv(url: str = ASSOCIATIONS_URL) -> pd.DataFrame:
    """Download GWAS Catalog associations zip and extract TSV into a DataFrame."""
    print(f"Downloading GWAS Catalog associations from:\n  {url}")
    t0 = time.time()
    resp = requests.get(url, timeout=TIMEOUT, stream=True)
    resp.raise_for_status()

    raw = resp.content
    elapsed = time.time() - t0
    size_mb = len(raw) / 1024 / 1024
    print(f"  Downloaded {size_mb:.1f} MB in {elapsed:.1f}s")

    # Extract TSV from zip
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        tsv_names = [n for n in zf.namelist() if n.endswith(".tsv")]
        if not tsv_names:
            raise FileNotFoundError(f"No TSV file found in zip. Contents: {zf.namelist()}")
        tsv_name = tsv_names[0]
        print(f"  Extracting: {tsv_name}")
        tsv_bytes = zf.read(tsv_name)

    df = pd.read_csv(
        io.BytesIO(tsv_bytes),
        sep="\t",
        low_memory=False,
        dtype=str,  # read everything as string first, convert later
    )
    print(f"  Parsed {len(df):,} rows × {len(df.columns)} columns")
    return df


def _parse_pvalue(row: pd.Series) -> float | None:
    """Parse p-value from the TSV row, trying multiple column strategies."""
    # Strategy 1: direct P-VALUE column
    pv = row.get("P-VALUE")
    if pd.notna(pv):
        try:
            val = float(pv)
            if val > 0:
                return val
        except (ValueError, TypeError):
            pass

    # Strategy 2: mantissa × 10^exponent
    mantissa = row.get("PVALUE_MANT")
    exponent = row.get("PVALUE_EXPONENT")
    if pd.notna(mantissa) and pd.notna(exponent):
        try:
            return float(mantissa) * (10 ** int(float(exponent)))
        except (ValueError, TypeError):
            pass

    return None


def _extract_efo_short(uri_str: str) -> list[str]:
    """Extract EFO/MONDO/Orphanet shortForms from MAPPED_TRAIT_URI.

    The URI column may contain multiple comma-separated URIs like:
        http://www.ebi.ac.uk/efo/EFO_0001360, http://purl.obolibrary.org/obo/MONDO_0007254
    """
    if not isinstance(uri_str, str) or not uri_str.strip():
        return []
    ids = []
    for uri in uri_str.split(","):
        uri = uri.strip()
        # Extract the last path segment (EFO_0001360, MONDO_0007254, etc.)
        match = re.search(r"[/]([A-Za-z]+_\d+)$", uri)
        if match:
            ids.append(match.group(1))
    return ids


def _split_genes(gene_str: str) -> list[str]:
    """Split reported genes string into a clean list.

    GWAS Catalog uses ', ' or ' - ' as delimiters.  Also handles
    'NR' (not reported) and similar placeholders.
    """
    if not isinstance(gene_str, str) or not gene_str.strip():
        return []
    # Split on comma, semicolon, or ' - '
    parts = re.split(r"\s*[,;]\s*|\s+-\s+", gene_str)
    genes = []
    for g in parts:
        g = g.strip().upper()
        if g and g not in ("NR", "N/A", "NA", "NAN", "INTERGENIC", ""):
            genes.append(g)
    return genes


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise raw TSV DataFrame into the target parquet schema.

    One row per (association × EFO ID) — associations mapped to multiple
    traits are expanded into separate rows.
    """
    print("Normalising columns...")

    records = []
    for _, row in df.iterrows():
        # rsId
        rs_id = row.get("SNP_ID_CURRENT", "")
        if not isinstance(rs_id, str) or not rs_id.strip():
            rs_id = row.get("SNPS", "")
        rs_id = str(rs_id).strip()
        # Ensure rs prefix
        if rs_id and rs_id.isdigit():
            rs_id = f"rs{rs_id}"

        # p-value
        pvalue = _parse_pvalue(row)

        # Genes
        genes_str = str(row.get("REPORTED GENE(S)", ""))
        genes_list = _split_genes(genes_str)

        # Trait
        trait = str(row.get("DISEASE/TRAIT", "")).strip()

        # EFO IDs (may be multiple)
        efo_uri_raw = str(row.get("MAPPED_TRAIT_URI", ""))
        efo_ids = _extract_efo_short(efo_uri_raw)

        # OR / BETA
        or_beta = None
        or_val = row.get("OR or BETA")
        if pd.notna(or_val):
            try:
                or_beta = float(or_val)
            except (ValueError, TypeError):
                pass

        # Risk allele
        risk_allele = str(row.get("STRONGEST SNP-RISK ALLELE", "")).strip()

        # Study
        study_acc = str(row.get("STUDY ACCESSION", "")).strip()

        # Location
        chromosome = str(row.get("CHR_ID", "")).strip()
        position = None
        pos_raw = row.get("CHR_POS")
        if pd.notna(pos_raw):
            try:
                position = int(float(pos_raw))
            except (ValueError, TypeError):
                pass

        # Context (intron, intergenic, etc.)
        context = str(row.get("CONTEXT", "")).strip()

        # Mapped trait name
        mapped_trait = str(row.get("MAPPED_TRAIT", "")).strip()

        # Create one record per EFO ID (or one with empty efoId if no mapping)
        if not efo_ids:
            efo_ids = [""]

        for efo_id in efo_ids:
            efo_uri = ""
            if efo_id:
                # Reconstruct a canonical URI
                efo_uri = f"http://www.ebi.ac.uk/efo/{efo_id}"

            records.append({
                "rsId": rs_id if rs_id else None,
                "pvalue": pvalue,
                "genes": genes_str.strip() if genes_str.strip() else None,
                "genes_list": genes_list,
                "trait": trait if trait else None,
                "efoId": efo_id if efo_id else None,
                "efoUri": efo_uri if efo_uri else None,
                "mappedTrait": mapped_trait if mapped_trait else None,
                "orBeta": or_beta,
                "riskAllele": risk_allele if risk_allele else None,
                "studyAccession": study_acc if study_acc else None,
                "chromosome": chromosome if chromosome else None,
                "position": position,
                "context": context if context else None,
            })

    out = pd.DataFrame(records)
    print(f"  Normalised to {len(out):,} rows (expanded by multi-EFO mappings)")
    return out


def build_traits_table(assoc_df: pd.DataFrame) -> pd.DataFrame:
    """Build a deduplicated traits lookup table from associations."""
    traits = (
        assoc_df[assoc_df["efoId"].notna() & (assoc_df["efoId"] != "")]
        .groupby("efoId")
        .agg(
            trait=("mappedTrait", "first"),
            efoUri=("efoUri", "first"),
        )
        .reset_index()
    )
    # Fill missing trait names with the disease/trait column
    mask = traits["trait"].isna() | (traits["trait"] == "")
    if mask.any():
        fallback = (
            assoc_df[assoc_df["efoId"].notna()]
            .groupby("efoId")["trait"]
            .first()
        )
        traits.loc[mask, "trait"] = traits.loc[mask, "efoId"].map(fallback)
    print(f"  Traits table: {len(traits):,} unique EFO IDs")
    return traits


def save_parquet(assoc_df: pd.DataFrame, traits_df: pd.DataFrame) -> None:
    """Save DataFrames to parquet files."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    assoc_path = DATA_DIR / "associations.parquet"
    traits_path = DATA_DIR / "traits.parquet"

    assoc_df.to_parquet(assoc_path, index=False, engine="pyarrow")
    traits_df.to_parquet(traits_path, index=False, engine="pyarrow")

    assoc_mb = assoc_path.stat().st_size / 1024 / 1024
    traits_mb = traits_path.stat().st_size / 1024 / 1024
    print(f"\nSaved:")
    print(f"  {assoc_path}  ({assoc_mb:.1f} MB)")
    print(f"  {traits_path} ({traits_mb:.2f} MB)")


def main() -> None:
    t_total = time.time()

    raw_df = download_tsv()
    assoc_df = normalise(raw_df)
    traits_df = build_traits_table(assoc_df)
    save_parquet(assoc_df, traits_df)

    elapsed = time.time() - t_total
    print(f"\nDone in {elapsed:.1f}s")
    print(f"  Associations: {len(assoc_df):,} rows")
    print(f"  Traits:       {len(traits_df):,} unique EFO IDs")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()

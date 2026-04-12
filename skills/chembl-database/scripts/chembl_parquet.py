#!/usr/bin/env python3
"""Local parquet reader for ChEMBL subset data."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.getenv("CHEMBL_DATA_DIR") or (PROJECT_ROOT / "data" / "chembl"))

_manifest: dict[str, Any] | None = None
_target_lookup_df: pd.DataFrame | None = None
_targets_df: pd.DataFrame | None = None
_molecules_df: pd.DataFrame | None = None
_activities_df: pd.DataFrame | None = None
_mechanisms_df: pd.DataFrame | None = None
_indications_df: pd.DataFrame | None = None
_TARGET_TYPE_PRIORITY = {
    "SINGLE PROTEIN": 0,
    "PROTEIN FAMILY": 1,
    "PROTEIN COMPLEX": 2,
}


def _normalize_organism(organism: str | None) -> str:
    text = (organism or "human").strip().lower().replace("_", " ")
    if text in {"human", "homo sapiens"}:
        return "human"
    if text in {"mouse", "mus musculus"}:
        return "mouse"
    return text


def _normalize_term(term: str | None) -> str:
    return " ".join((term or "").strip().lower().split())


def _load_manifest() -> dict[str, Any]:
    global _manifest
    if _manifest is not None:
        return _manifest
    manifest_path = DATA_DIR / "manifest.json"
    _manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return _manifest


def is_available() -> bool:
    try:
        manifest = _load_manifest()
        required_files = manifest.get("required_files", [])
        return all((DATA_DIR / name).is_file() for name in required_files)
    except Exception:
        return False


def _load_target_lookup() -> pd.DataFrame:
    global _target_lookup_df
    if _target_lookup_df is None:
        _target_lookup_df = pd.read_parquet(DATA_DIR / "target_lookup.parquet")
    return _target_lookup_df


def _load_targets() -> pd.DataFrame:
    global _targets_df
    if _targets_df is None:
        _targets_df = pd.read_parquet(DATA_DIR / "targets.parquet")
    return _targets_df


def _load_molecules() -> pd.DataFrame:
    global _molecules_df
    if _molecules_df is None:
        _molecules_df = pd.read_parquet(DATA_DIR / "molecules.parquet")
    return _molecules_df


def _load_activities() -> pd.DataFrame:
    global _activities_df
    if _activities_df is None:
        _activities_df = pd.read_parquet(DATA_DIR / "activities.parquet")
    return _activities_df


def _load_mechanisms() -> pd.DataFrame:
    global _mechanisms_df
    if _mechanisms_df is None:
        _mechanisms_df = pd.read_parquet(DATA_DIR / "mechanisms.parquet")
    return _mechanisms_df


def _load_indications() -> pd.DataFrame:
    global _indications_df
    if _indications_df is None:
        _indications_df = pd.read_parquet(DATA_DIR / "indications.parquet")
    return _indications_df


def search_targets_by_name(target_name: str, organism: str = "human") -> list[dict]:
    """Search local ChEMBL target subset by gene symbol, alias, or name."""
    lookup_df = _load_target_lookup()
    targets_df = _load_targets()
    organism_key = _normalize_organism(organism)
    query = (target_name or "").strip()
    if not query:
        return []

    query_norm = _normalize_term(query)
    query_upper = query.upper()

    rows = lookup_df[lookup_df["organism"] == organism_key].copy()
    if rows.empty:
        return []

    rows["_normalized"] = rows["lookup_term"].map(_normalize_term)
    exact = rows[rows["lookup_term"].fillna("").str.upper() == query_upper].copy()
    if not exact.empty:
        exact["_query_bucket"] = exact["lookup_kind"].fillna("").map(
            lambda kind: 0 if str(kind).upper() == "GENE_SYMBOL" else 1
        )
        matched = exact
    else:
        normalized = rows[rows["_normalized"] == query_norm].copy()
        if normalized.empty:
            # Prevent gene-symbol false positives such as CD4 -> CD44.
            is_gene_like = query.isupper() and " " not in query and len(query) <= 6
            if is_gene_like:
                return []
            normalized = rows[rows["_normalized"].str.contains(query_norm, na=False)].copy()
            normalized["_query_bucket"] = 3
        else:
            normalized["_query_bucket"] = 2
        matched = normalized

    if matched.empty:
        return []

    merged = matched.merge(
        targets_df,
        on=["target_chembl_id", "organism"],
        how="left",
        suffixes=("", "_target"),
    )
    merged["match_priority"] = pd.to_numeric(merged["match_priority"], errors="coerce").fillna(9999)
    merged["_target_type_rank"] = merged["target_type"].map(_TARGET_TYPE_PRIORITY).fillna(9999)
    merged = merged.sort_values(
        by=["_query_bucket", "match_priority", "_target_type_rank", "pref_name", "target_chembl_id"],
        kind="stable",
    )
    merged = merged.drop_duplicates(subset=["target_chembl_id"], keep="first")
    records = merged[
        ["target_chembl_id", "pref_name", "target_type", "organism"]
    ].to_dict("records")
    return records


def get_bioactivity_data(
    target_chembl_id: str,
    activity_type: str = "IC50",
    max_value: float = 100,
) -> list[dict]:
    """Return local bioactivities for one target and activity type."""
    activities_df = _load_activities().copy()
    activities_df["standard_value"] = pd.to_numeric(
        activities_df["standard_value"], errors="coerce"
    )
    activities_df["pchembl_value"] = pd.to_numeric(
        activities_df["pchembl_value"], errors="coerce"
    )

    filtered = activities_df[
        (activities_df["target_chembl_id"] == target_chembl_id)
        & (activities_df["standard_type"] == activity_type)
        & (activities_df["standard_units"].fillna("").str.lower() == "nm")
        & (activities_df["standard_value"].notna())
        & (activities_df["standard_value"] <= float(max_value))
    ].copy()
    if filtered.empty:
        return []

    filtered["_pchembl_sort"] = filtered["pchembl_value"].fillna(float("-inf"))
    filtered = filtered.sort_values(
        by=["standard_value", "_pchembl_sort", "molecule_chembl_id"],
        ascending=[True, False, True],
        kind="stable",
    )
    filtered = filtered.drop(columns=["_pchembl_sort"])
    return filtered.to_dict("records")


def get_molecule_info(chembl_id: str) -> dict[str, Any] | None:
    """Resolve one ChEMBL molecule identifier from local subset data."""
    molecules_df = _load_molecules()
    matched = molecules_df[molecules_df["molecule_chembl_id"] == chembl_id]
    if matched.empty:
        return None
    row = matched.iloc[0]
    return {
        "molecule_chembl_id": row.get("molecule_chembl_id"),
        "pref_name": row.get("pref_name"),
        "molecule_type": row.get("molecule_type"),
        "first_approval": row.get("first_approval"),
        "max_phase": row.get("max_phase"),
    }


def get_drug_info(molecule_chembl_id: str):
    """Return tuple of molecule info, mechanisms, and indications."""
    drug_info = get_molecule_info(molecule_chembl_id)

    mechanisms_df = _load_mechanisms()
    indications_df = _load_indications()

    mechanisms = mechanisms_df[
        mechanisms_df["molecule_chembl_id"] == molecule_chembl_id
    ].to_dict("records")
    indications = indications_df[
        indications_df["molecule_chembl_id"] == molecule_chembl_id
    ].to_dict("records")
    return drug_info, mechanisms, indications

"""Local cache helpers for drug mechanism-of-action enrichment."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "drug_moa_cache"
ENTRIES_FILENAME = "entries.parquet"
MANIFEST_FILENAME = "manifest.json"

_cache_dir: Path | None = None
_cache_mtime: float | None = None
_cache_df: pd.DataFrame | None = None


def get_cache_dir() -> Path:
    value = os.getenv("DRUG_MOA_CACHE_DIR")
    return Path(value).expanduser() if value else DEFAULT_CACHE_DIR


def _entries_path() -> Path:
    return get_cache_dir() / ENTRIES_FILENAME


def _manifest_path() -> Path:
    return get_cache_dir() / MANIFEST_FILENAME


def is_available() -> bool:
    return _entries_path().is_file()


def _normalize_key(chembl_id: str, target_gene: str) -> tuple[str, str]:
    return chembl_id.strip().upper(), target_gene.strip().upper()


def _empty_entries() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "chembl_id",
            "target_gene",
            "status",
            "mechanism_of_action",
            "source",
            "source_target",
            "retrieved_at",
        ]
    )


def _load_entries() -> pd.DataFrame:
    global _cache_df, _cache_dir, _cache_mtime

    entries_path = _entries_path()
    if not entries_path.is_file():
        _cache_df = None
        _cache_dir = None
        _cache_mtime = None
        return _empty_entries()

    current_dir = entries_path.parent
    current_mtime = entries_path.stat().st_mtime
    if (
        _cache_df is None
        or _cache_dir != current_dir
        or _cache_mtime != current_mtime
    ):
        df = pd.read_parquet(entries_path)
        if df.empty:
            df = _empty_entries()
        for col in _empty_entries().columns:
            if col not in df.columns:
                df[col] = None
        df["chembl_id"] = df["chembl_id"].fillna("").astype(str).str.upper()
        df["target_gene"] = df["target_gene"].fillna("").astype(str).str.upper()
        _cache_df = df
        _cache_dir = current_dir
        _cache_mtime = current_mtime

    return _cache_df.copy()


def get_cache_entry(chembl_id: str, target_gene: str) -> dict[str, Any] | None:
    chembl_key, gene_key = _normalize_key(chembl_id, target_gene)
    df = _load_entries()
    matched = df[
        (df["chembl_id"] == chembl_key) & (df["target_gene"] == gene_key)
    ]
    if matched.empty:
        return None
    row = matched.iloc[-1].to_dict()
    return {str(key): value for key, value in row.items()}


def get_cached_moa(chembl_id: str, target_gene: str) -> str | None:
    entry = get_cache_entry(chembl_id, target_gene)
    if not entry:
        return None
    if str(entry.get("status", "")).strip().lower() != "resolved":
        return None
    moa = entry.get("mechanism_of_action")
    if moa is None:
        return None
    text = str(moa).strip()
    return text or None


def _build_manifest(df: pd.DataFrame, source_versions: dict[str, Any] | None = None) -> dict[str, Any]:
    status_counts = df["status"].fillna("unknown").astype(str).value_counts().to_dict()
    resolved = int(status_counts.get("resolved", 0))
    row_count = int(len(df))
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "row_count": row_count,
        "resolved_count": resolved,
        "unresolved_count": row_count - resolved,
        "source_versions": source_versions or {},
    }


def write_entries(
    entries: list[dict[str, Any]],
    *,
    source_versions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cache_dir = get_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    current = _load_entries() if _entries_path().is_file() else _empty_entries()
    incoming = pd.DataFrame(entries)
    if incoming.empty:
        incoming = _empty_entries()
    for col in _empty_entries().columns:
        if col not in incoming.columns:
            incoming[col] = None

    incoming = incoming[_empty_entries().columns].copy()
    incoming["chembl_id"] = incoming["chembl_id"].fillna("").astype(str).str.upper()
    incoming["target_gene"] = incoming["target_gene"].fillna("").astype(str).str.upper()
    incoming = incoming[
        (incoming["chembl_id"] != "") & (incoming["target_gene"] != "")
    ].copy()

    combined = pd.concat([current, incoming], ignore_index=True)
    combined = combined.drop_duplicates(
        subset=["chembl_id", "target_gene"],
        keep="last",
    ).sort_values(
        by=["chembl_id", "target_gene"],
        kind="stable",
    )

    combined.to_parquet(_entries_path(), index=False)
    manifest = _build_manifest(combined, source_versions=source_versions)
    _manifest_path().write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    global _cache_df, _cache_dir, _cache_mtime
    _cache_df = combined
    _cache_dir = cache_dir
    _cache_mtime = _entries_path().stat().st_mtime
    return manifest

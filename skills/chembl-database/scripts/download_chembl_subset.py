#!/usr/bin/env python3
"""Download or transform a local ChEMBL SQLite dump into parquet subset data."""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sqlite3
import tarfile
import tempfile
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests


logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "chembl"
LATEST_RELEASE_URLS = (
    "http://ftp.ebi.ac.uk/pub/databases/chembl/ChEMBLdb/latest/",
    "https://ftp.ebi.ac.uk/pub/databases/chembl/ChEMBLdb/latest/",
)
TARGET_TYPES = ("SINGLE PROTEIN", "PROTEIN COMPLEX", "PROTEIN FAMILY")
ACTIVITY_TYPES = ("IC50", "Ki", "EC50")
SUPPORTED_SPECIES = {"human": "Homo sapiens", "mouse": "Mus musculus"}
TEMP_MOLREGNO_TABLE = "subset_molregnos"
TEMP_INSERT_CHUNK_SIZE = 50_000
TARGET_TYPE_PRIORITY = {
    "SINGLE PROTEIN": 0,
    "PROTEIN FAMILY": 1,
    "PROTEIN COMPLEX": 2,
}


def _normalize_organism_name(organism: str | None) -> str | None:
    text = (organism or "").strip().lower().replace("_", " ")
    if text in {"human", "homo sapiens"}:
        return "human"
    if text in {"mouse", "mus musculus"}:
        return "mouse"
    return None


def _match_priority_for_lookup(kind: str | None) -> int:
    normalized = (kind or "").strip().upper()
    if normalized == "GENE_SYMBOL":
        return 0
    if "ACCESSION" in normalized:
        return 1
    if normalized in {"ALIAS", "SYNONYM"}:
        return 2
    if normalized == "PREF_NAME":
        return 3
    return 5


def _placeholders(values: Iterable[object]) -> str:
    return ", ".join("?" for _ in values)


def _write_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _drop_temp_molregno_table(conn: sqlite3.Connection) -> None:
    conn.execute(f"DROP TABLE IF EXISTS temp.{TEMP_MOLREGNO_TABLE}")


def _load_temp_molregno_table(conn: sqlite3.Connection, molregnos: list[int]) -> None:
    _drop_temp_molregno_table(conn)
    if not molregnos:
        return

    conn.execute(
        f"CREATE TEMP TABLE {TEMP_MOLREGNO_TABLE} (molregno INTEGER PRIMARY KEY)"
    )
    insert_query = f"INSERT INTO {TEMP_MOLREGNO_TABLE} (molregno) VALUES (?)"
    for start in range(0, len(molregnos), TEMP_INSERT_CHUNK_SIZE):
        chunk = [(molregno,) for molregno in molregnos[start : start + TEMP_INSERT_CHUNK_SIZE]]
        conn.executemany(insert_query, chunk)

    logger.info(
        "Loaded %d molecule ids into temp table %s",
        len(molregnos),
        TEMP_MOLREGNO_TABLE,
    )


def _extract_targets(conn: sqlite3.Connection, species_filter: tuple[str, ...]) -> pd.DataFrame:
    query = f"""
        SELECT
            td.tid,
            td.chembl_id AS target_chembl_id,
            td.pref_name,
            td.target_type,
            td.organism
        FROM target_dictionary td
        WHERE td.target_type IN ({_placeholders(TARGET_TYPES)})
    """
    targets = pd.read_sql_query(query, conn, params=TARGET_TYPES)
    targets["organism"] = targets["organism"].map(_normalize_organism_name)
    targets = targets[targets["organism"].isin(species_filter)].copy()
    targets = targets.drop_duplicates(subset=["target_chembl_id"]).sort_values(
        by=["organism", "pref_name", "target_chembl_id"],
        kind="stable",
    )
    return targets


def _extract_target_lookup(conn: sqlite3.Connection, targets: pd.DataFrame) -> pd.DataFrame:
    if targets.empty:
        return pd.DataFrame(
            columns=["organism", "lookup_term", "lookup_kind", "target_chembl_id", "match_priority"]
        )

    tid_list = targets["tid"].tolist()
    query = f"""
        SELECT
            tc.tid,
            cs.component_synonym AS lookup_term,
            cs.syn_type AS lookup_kind
        FROM target_components tc
        JOIN component_synonyms cs
          ON tc.component_id = cs.component_id
        WHERE tc.tid IN ({_placeholders(tid_list)})
    """
    synonyms = pd.read_sql_query(query, conn, params=tid_list)
    synonym_rows = synonyms.merge(targets[["tid", "target_chembl_id", "organism"]], on="tid", how="inner")
    synonym_rows = synonym_rows[
        ["organism", "lookup_term", "lookup_kind", "target_chembl_id"]
    ]

    pref_rows = targets[["organism", "pref_name", "target_chembl_id"]].rename(
        columns={"pref_name": "lookup_term"}
    )
    pref_rows["lookup_kind"] = "PREF_NAME"

    lookup = pd.concat([synonym_rows, pref_rows], ignore_index=True)
    lookup["lookup_term"] = lookup["lookup_term"].fillna("").astype(str).str.strip()
    lookup = lookup[lookup["lookup_term"] != ""].copy()
    lookup["match_priority"] = lookup["lookup_kind"].map(_match_priority_for_lookup)
    lookup = lookup.drop_duplicates(
        subset=["organism", "lookup_term", "lookup_kind", "target_chembl_id"],
        keep="first",
    ).sort_values(by=["organism", "match_priority", "lookup_term", "target_chembl_id"], kind="stable")
    return lookup


def _extract_activities(conn: sqlite3.Connection, targets: pd.DataFrame) -> pd.DataFrame:
    if targets.empty:
        return pd.DataFrame(
            columns=[
                "target_chembl_id",
                "molecule_chembl_id",
                "molecule_pref_name",
                "standard_type",
                "standard_value",
                "standard_units",
                "pchembl_value",
            ]
        )
    tid_list = targets["tid"].tolist()
    query = f"""
        SELECT
            td.chembl_id AS target_chembl_id,
            md.chembl_id AS molecule_chembl_id,
            md.pref_name AS molecule_pref_name,
            a.standard_type,
            a.standard_value,
            a.standard_units,
            a.pchembl_value,
            a.molregno
        FROM activities a
        JOIN assays ass
          ON a.assay_id = ass.assay_id
        JOIN target_dictionary td
          ON ass.tid = td.tid
        JOIN molecule_dictionary md
          ON a.molregno = md.molregno
        WHERE ass.tid IN ({_placeholders(tid_list)})
          AND a.standard_type IN ({_placeholders(ACTIVITY_TYPES)})
    """
    params = [*tid_list, *ACTIVITY_TYPES]
    activities = pd.read_sql_query(query, conn, params=params)
    if activities.empty:
        return activities
    activities["standard_units"] = activities["standard_units"].fillna("")
    activities = activities[activities["standard_units"].str.lower() == "nm"].copy()
    activities["standard_value"] = pd.to_numeric(activities["standard_value"], errors="coerce")
    activities["pchembl_value"] = pd.to_numeric(activities["pchembl_value"], errors="coerce")
    activities = activities[activities["standard_value"].notna()].copy()
    activities = activities.sort_values(
        by=["target_chembl_id", "standard_type", "standard_value", "molecule_chembl_id"],
        kind="stable",
    )
    return activities


def _collect_molregnos(conn: sqlite3.Connection, activities: pd.DataFrame) -> list[int]:
    activity_molregnos = set(pd.to_numeric(activities.get("molregno"), errors="coerce").dropna().astype(int).tolist())
    clinical = pd.read_sql_query(
        "SELECT molregno FROM molecule_dictionary WHERE COALESCE(max_phase, 0) > 0",
        conn,
    )
    clinical_molregnos = set(pd.to_numeric(clinical["molregno"], errors="coerce").dropna().astype(int).tolist())
    return sorted(activity_molregnos | clinical_molregnos)


def _extract_molecules(conn: sqlite3.Connection, molregnos: list[int]) -> pd.DataFrame:
    if not molregnos:
        return pd.DataFrame(
            columns=["molecule_chembl_id", "pref_name", "molecule_type", "first_approval", "max_phase"]
        )

    synonym_join = ""
    synonym_expr = "NULL"
    if _table_exists(conn, "molecule_synonyms"):
        synonym_join = f"""
        LEFT JOIN (
            SELECT
                ms.molregno,
                COALESCE(
                    MAX(CASE WHEN UPPER(ms.syn_type) = 'INN' THEN ms.synonyms END),
                    MAX(CASE WHEN UPPER(ms.syn_type) IN ('USAN', 'BAN', 'JAN', 'OTHER', 'TRADE_NAME') THEN ms.synonyms END),
                    MAX(ms.synonyms)
                ) AS synonym_name
            FROM molecule_synonyms ms
            JOIN {TEMP_MOLREGNO_TABLE} sm
              ON ms.molregno = sm.molregno
            GROUP BY ms.molregno
        ) syn
          ON md.molregno = syn.molregno
        """
        synonym_expr = "syn.synonym_name"

    compound_join = ""
    compound_expr = "NULL"
    if _table_exists(conn, "compound_records"):
        compound_join = f"""
        LEFT JOIN (
            SELECT
                cr.molregno,
                MIN(cr.compound_name) AS compound_name
            FROM compound_records cr
            JOIN {TEMP_MOLREGNO_TABLE} sm
              ON cr.molregno = sm.molregno
            WHERE cr.compound_name IS NOT NULL
              AND TRIM(cr.compound_name) != ''
            GROUP BY cr.molregno
        ) cr
          ON md.molregno = cr.molregno
        """
        compound_expr = "cr.compound_name"

    query = f"""
        SELECT
            md.molregno,
            md.chembl_id AS molecule_chembl_id,
            COALESCE(md.pref_name, {synonym_expr}, {compound_expr}, md.chembl_id) AS pref_name,
            md.molecule_type,
            md.first_approval,
            md.max_phase
        FROM molecule_dictionary md
        JOIN {TEMP_MOLREGNO_TABLE} sm
          ON md.molregno = sm.molregno
        {synonym_join}
        {compound_join}
    """
    molecules = pd.read_sql_query(query, conn)
    molecules["max_phase"] = pd.to_numeric(molecules["max_phase"], errors="coerce")
    return molecules.sort_values(by=["molecule_chembl_id"], kind="stable")


def _extract_mechanisms(conn: sqlite3.Connection, molregnos: list[int]) -> pd.DataFrame:
    if not molregnos:
        return pd.DataFrame(columns=["molecule_chembl_id", "mechanism_of_action"])
    query = f"""
        SELECT
            md.chembl_id AS molecule_chembl_id,
            dm.mechanism_of_action
        FROM drug_mechanism dm
        JOIN molecule_dictionary md
          ON dm.molregno = md.molregno
        JOIN {TEMP_MOLREGNO_TABLE} sm
          ON dm.molregno = sm.molregno
    """
    mechanisms = pd.read_sql_query(query, conn)
    mechanisms = mechanisms.drop_duplicates(
        subset=["molecule_chembl_id", "mechanism_of_action"],
        keep="first",
    )
    return mechanisms.sort_values(by=["molecule_chembl_id", "mechanism_of_action"], kind="stable")


def _extract_indications(conn: sqlite3.Connection, molregnos: list[int]) -> pd.DataFrame:
    if not molregnos:
        return pd.DataFrame(columns=["molecule_chembl_id", "efo_term", "mesh_heading", "max_phase_for_ind"])
    query = f"""
        SELECT
            md.chembl_id AS molecule_chembl_id,
            di.efo_term,
            di.mesh_heading,
            di.max_phase_for_ind
        FROM drug_indication di
        JOIN molecule_dictionary md
          ON di.molregno = md.molregno
        JOIN {TEMP_MOLREGNO_TABLE} sm
          ON di.molregno = sm.molregno
    """
    indications = pd.read_sql_query(query, conn)
    indications["max_phase_for_ind"] = pd.to_numeric(
        indications["max_phase_for_ind"], errors="coerce"
    )
    indications = indications.drop_duplicates(
        subset=["molecule_chembl_id", "efo_term", "mesh_heading", "max_phase_for_ind"],
        keep="first",
    )
    return indications.sort_values(
        by=["molecule_chembl_id", "max_phase_for_ind", "efo_term"],
        ascending=[True, False, True],
        kind="stable",
    )


def build_subset_from_sqlite(
    sqlite_path: Path | str,
    out_dir: Path | str = DEFAULT_OUT_DIR,
    species: tuple[str, ...] = ("human", "mouse"),
) -> dict[str, object]:
    """Build the local ChEMBL subset from a SQLite database file."""
    sqlite_path = Path(sqlite_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    species_filter = tuple(sorted({_normalize_organism_name(item) for item in species if _normalize_organism_name(item)}))
    if not species_filter:
        raise ValueError("At least one supported species is required")

    with sqlite3.connect(sqlite_path) as conn:
        logger.info("Building ChEMBL subset from %s", sqlite_path)
        targets = _extract_targets(conn, species_filter)
        logger.info("Extracted %d targets for species=%s", len(targets), ",".join(species_filter))
        target_lookup = _extract_target_lookup(conn, targets)
        activities = _extract_activities(conn, targets)
        logger.info("Extracted %d filtered bioactivities", len(activities))
        molregnos = _collect_molregnos(conn, activities)
        logger.info("Collected %d unique molecule ids", len(molregnos))
        _load_temp_molregno_table(conn, molregnos)
        try:
            molecules = _extract_molecules(conn, molregnos)
            mechanisms = _extract_mechanisms(conn, molregnos)
            indications = _extract_indications(conn, molregnos)
        finally:
            _drop_temp_molregno_table(conn)

    targets_write = targets[["target_chembl_id", "pref_name", "target_type", "organism"]].reset_index(drop=True)
    activities_write = activities[
        [
            "target_chembl_id",
            "molecule_chembl_id",
            "molecule_pref_name",
            "standard_type",
            "standard_value",
            "standard_units",
            "pchembl_value",
        ]
    ].reset_index(drop=True)
    molecules_write = molecules[
        ["molecule_chembl_id", "pref_name", "molecule_type", "first_approval", "max_phase"]
    ].reset_index(drop=True)
    activities_write = activities_write.merge(
        molecules_write[["molecule_chembl_id", "pref_name"]].rename(
            columns={"pref_name": "_molecule_pref_fallback"}
        ),
        on="molecule_chembl_id",
        how="left",
    )
    activities_write["molecule_pref_name"] = activities_write["molecule_pref_name"].fillna(
        activities_write["_molecule_pref_fallback"]
    )
    activities_write = activities_write.drop(columns=["_molecule_pref_fallback"])

    _write_parquet(target_lookup.reset_index(drop=True), out_dir / "target_lookup.parquet")
    _write_parquet(targets_write, out_dir / "targets.parquet")
    _write_parquet(molecules_write, out_dir / "molecules.parquet")
    _write_parquet(activities_write, out_dir / "activities.parquet")
    _write_parquet(mechanisms.reset_index(drop=True), out_dir / "mechanisms.parquet")
    _write_parquet(indications.reset_index(drop=True), out_dir / "indications.parquet")
    logger.info("Wrote parquet subset files to %s", out_dir)

    manifest = {
        "release_id": sqlite_path.stem,
        "built_at": pd.Timestamp.utcnow().isoformat(),
        "species": list(species_filter),
        "filters": {
            "target_types": list(TARGET_TYPES),
            "activity_types": list(ACTIVITY_TYPES),
            "standard_units": "nM",
        },
        "required_files": [
            "target_lookup.parquet",
            "targets.parquet",
            "molecules.parquet",
            "activities.parquet",
            "mechanisms.parquet",
            "indications.parquet",
        ],
        "row_counts": {
            "target_lookup": int(len(target_lookup)),
            "targets": int(len(targets_write)),
            "molecules": int(len(molecules_write)),
            "activities": int(len(activities_write)),
            "mechanisms": int(len(mechanisms)),
            "indications": int(len(indications)),
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Wrote manifest to %s", out_dir / "manifest.json")
    return manifest


def _download_latest_sqlite_archive(temp_dir: Path) -> Path:
    last_error: Exception | None = None
    for base_url in LATEST_RELEASE_URLS:
        try:
            logger.info("Checking ChEMBL release index: %s", base_url)
            response = requests.get(base_url, timeout=120)
            response.raise_for_status()
            match = re.search(r'href="([^"]*sqlite[^"]*\.tar\.gz)"', response.text, flags=re.IGNORECASE)
            if not match:
                raise FileNotFoundError(f"Could not find sqlite archive in {base_url}")
            archive_name = Path(match.group(1)).name
            archive_url = f"{base_url}{archive_name}"
            archive_path = temp_dir / archive_name
            logger.info("Downloading archive: %s", archive_url)
            with requests.get(archive_url, timeout=600, stream=True) as stream:
                stream.raise_for_status()
                with archive_path.open("wb") as handle:
                    for chunk in stream.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            return archive_path
        except Exception as exc:
            logger.warning("Failed using %s: %s", base_url, exc)
            last_error = exc

    if last_error is not None:
        raise last_error
    raise RuntimeError("No ChEMBL release URL candidates configured")


def _extract_sqlite_from_archive(archive_path: Path, extract_dir: Path) -> Path:
    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(extract_dir)

    candidates = sorted(
        p for p in extract_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in {".db", ".sqlite", ".sqlite3"}
    )
    if not candidates:
        raise FileNotFoundError(f"No SQLite file found in archive {archive_path}")
    return candidates[0]


def _resolve_sqlite_path(source_sqlite: str | None, temp_dir: Path) -> tuple[Path, bool]:
    if source_sqlite:
        source_path = Path(source_sqlite).expanduser().resolve()
        if source_path.suffixes[-2:] == [".tar", ".gz"]:
            sqlite_path = _extract_sqlite_from_archive(source_path, temp_dir)
            return sqlite_path, False
        return source_path, False

    archive_path = _download_latest_sqlite_archive(temp_dir)
    sqlite_path = _extract_sqlite_from_archive(archive_path, temp_dir)
    return sqlite_path, True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--source-sqlite", default=None)
    parser.add_argument("--keep-raw", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    with tempfile.TemporaryDirectory(prefix="chembl_subset_") as temp_root:
        temp_dir = Path(temp_root)
        sqlite_path, downloaded = _resolve_sqlite_path(args.source_sqlite, temp_dir)
        manifest = build_subset_from_sqlite(sqlite_path, Path(args.out_dir))
        logger.info("Built ChEMBL subset at %s", args.out_dir)
        logger.info("Manifest: %s", json.dumps(manifest, indent=2))
        if args.keep_raw:
            raw_copy = Path(args.out_dir) / sqlite_path.name
            shutil.copy2(sqlite_path, raw_copy)
            logger.info("Copied raw SQLite to %s", raw_copy)
        elif downloaded:
            logger.info("Raw SQLite removed with temporary workspace cleanup")


if __name__ == "__main__":
    main()

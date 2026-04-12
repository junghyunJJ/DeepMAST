import importlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_script_module(relative_path: str, module_name: str):
    path = PROJECT_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module at {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _reset_skill_loader_cache():
    from src.agents.drug_target.tools import _skill_loader

    _skill_loader._module_cache.clear()


def _write_moa_cache(cache_dir: Path, entries: list[dict]):
    cache_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(entries).to_parquet(cache_dir / "entries.parquet", index=False)
    (cache_dir / "manifest.json").write_text(
        json.dumps({"row_count": len(entries)}),
        encoding="utf-8",
    )


def _build_minimal_chembl_sqlite(sqlite_path: Path) -> Path:
    conn = sqlite3.connect(sqlite_path)
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE target_dictionary (
            tid INTEGER PRIMARY KEY,
            chembl_id TEXT,
            pref_name TEXT,
            target_type TEXT,
            organism TEXT
        );
        CREATE TABLE target_components (
            tid INTEGER,
            component_id INTEGER
        );
        CREATE TABLE component_synonyms (
            component_id INTEGER,
            component_synonym TEXT,
            syn_type TEXT
        );
        CREATE TABLE assays (
            assay_id INTEGER PRIMARY KEY,
            tid INTEGER
        );
        CREATE TABLE molecule_dictionary (
            molregno INTEGER PRIMARY KEY,
            chembl_id TEXT,
            pref_name TEXT,
            molecule_type TEXT,
            max_phase INTEGER,
            first_approval INTEGER
        );
        CREATE TABLE molecule_synonyms (
            molregno INTEGER,
            syn_type TEXT,
            molsyn_id INTEGER,
            synonyms TEXT
        );
        CREATE TABLE compound_records (
            record_id INTEGER,
            molregno INTEGER,
            doc_id INTEGER,
            compound_key TEXT,
            compound_name TEXT,
            src_id INTEGER,
            src_compound_id TEXT,
            cidx TEXT
        );
        CREATE TABLE activities (
            activity_id INTEGER PRIMARY KEY,
            assay_id INTEGER,
            molregno INTEGER,
            standard_type TEXT,
            standard_value REAL,
            standard_units TEXT,
            pchembl_value REAL
        );
        CREATE TABLE drug_mechanism (
            molregno INTEGER,
            mechanism_of_action TEXT
        );
        CREATE TABLE drug_indication (
            molregno INTEGER,
            efo_term TEXT,
            mesh_heading TEXT,
            max_phase_for_ind INTEGER
        );
        """
    )

    cur.executemany(
        "INSERT INTO target_dictionary VALUES (?, ?, ?, ?, ?)",
        [
            (1, "CHEMBL_T_ICAM1_H", "Intercellular adhesion molecule 1", "SINGLE PROTEIN", "Homo sapiens"),
            (2, "CHEMBL_T_ICAM1_M", "Intercellular adhesion molecule 1", "SINGLE PROTEIN", "Mus musculus"),
            (3, "CHEMBL_T_ICAM1_COMPLEX", "Intercellular adhesion molecule (ICAM-1), Integrin alpha-L/beta-2", "PROTEIN COMPLEX", "Homo sapiens"),
            (4, "CHEMBL_T_CD44_M", "CD44 antigen", "SINGLE PROTEIN", "Mus musculus"),
        ],
    )
    cur.executemany(
        "INSERT INTO target_components VALUES (?, ?)",
        [(1, 101), (2, 102), (3, 103), (4, 104)],
    )
    cur.executemany(
        "INSERT INTO component_synonyms VALUES (?, ?, ?)",
        [
            (101, "ICAM1", "GENE_SYMBOL"),
            (101, "CD54", "ALIAS"),
            (102, "ICAM1", "GENE_SYMBOL"),
            (102, "Icam1", "GENE_SYMBOL"),
            (103, "ICAM1", "GENE_SYMBOL"),
            (104, "CD44", "GENE_SYMBOL"),
        ],
    )
    cur.executemany(
        "INSERT INTO assays VALUES (?, ?)",
        [(11, 1), (12, 2), (13, 3)],
    )
    cur.executemany(
        "INSERT INTO molecule_dictionary VALUES (?, ?, ?, ?, ?, ?)",
        [
            (201, "CHEMBL_PRE_HUMAN", None, "Antibody", 0, None),
            (202, "CHEMBL_PRE_MOUSE", None, "Antibody", 0, None),
            (203, "CHEMBL2108326", "CAROTEGRAST", "Small molecule", 3, None),
            (204, "CHEMBL2109482", "ALICAFORSEN", "Oligonucleotide", 2, None),
            (205, "CHEMBL_COMPLEX_ONLY", None, "Antibody", 0, None),
        ],
    )
    cur.executemany(
        "INSERT INTO molecule_synonyms VALUES (?, ?, ?, ?)",
        [
            (201, "INN", 1, "BIOMAB"),
        ],
    )
    cur.executemany(
        "INSERT INTO compound_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (1, 202, 1, "A", "MOUSEMAB", 1, None, "X"),
            (2, 205, 1, "B", "COMPLEXMAB", 1, None, "Y"),
        ],
    )
    cur.executemany(
        "INSERT INTO activities VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1001, 11, 201, "IC50", 50.0, "nM", 7.3),
            (1002, 12, 202, "IC50", 25.0, "nM", 7.6),
            (1003, 13, 205, "IC50", 10.0, "nM", 8.0),
        ],
    )
    cur.executemany(
        "INSERT INTO drug_mechanism VALUES (?, ?)",
        [
            (201, "blocks ICAM1"),
            (203, "integrin antagonist"),
        ],
    )
    cur.executemany(
        "INSERT INTO drug_indication VALUES (?, ?, ?, ?)",
        [
            (201, "ulcerative colitis", "ulcerative colitis", 4),
            (203, "ulcerative colitis", "ulcerative colitis", 3),
            (204, "multiple myeloma", "multiple myeloma", 2),
        ],
    )

    conn.commit()
    conn.close()
    return sqlite_path


@pytest.fixture
def chembl_subset_dir(tmp_path, monkeypatch):
    sqlite_path = _build_minimal_chembl_sqlite(tmp_path / "chembl_test.db")
    downloader = _load_script_module(
        "skills/chembl-database/scripts/download_chembl_subset.py",
        "download_chembl_subset",
    )
    out_dir = tmp_path / "chembl_data"
    downloader.build_subset_from_sqlite(sqlite_path, out_dir)

    activities = pd.read_parquet(out_dir / "activities.parquet")
    activities.loc[
        activities["molecule_chembl_id"] == "CHEMBL_PRE_HUMAN",
        "molecule_pref_name",
    ] = None
    activities.to_parquet(out_dir / "activities.parquet", index=False)

    monkeypatch.setenv("CHEMBL_DATA_DIR", str(out_dir))
    _reset_skill_loader_cache()
    return out_dir


def test_build_subset_from_sqlite_writes_expected_artifacts(tmp_path):
    sqlite_path = _build_minimal_chembl_sqlite(tmp_path / "chembl_test.db")
    downloader = _load_script_module(
        "skills/chembl-database/scripts/download_chembl_subset.py",
        "download_chembl_subset",
    )
    out_dir = tmp_path / "chembl_data"

    manifest = downloader.build_subset_from_sqlite(sqlite_path, out_dir)

    expected_files = {
        "manifest.json",
        "target_lookup.parquet",
        "targets.parquet",
        "molecules.parquet",
        "activities.parquet",
        "mechanisms.parquet",
        "indications.parquet",
    }
    assert expected_files == {path.name for path in out_dir.iterdir()}
    assert set(manifest["species"]) == {"human", "mouse"}

    molecules = pd.read_parquet(out_dir / "molecules.parquet")
    assert {"CHEMBL_PRE_HUMAN", "CHEMBL2108326", "CHEMBL2109482"}.issubset(
        set(molecules["molecule_chembl_id"])
    )


def test_chembl_parquet_supports_species_lookup_and_molecule_info(chembl_subset_dir):
    chembl_parquet = _load_script_module(
        "skills/chembl-database/scripts/chembl_parquet.py",
        "chembl_parquet",
    )

    human_targets = chembl_parquet.search_targets_by_name("ICAM1", organism="human")
    mouse_targets = chembl_parquet.search_targets_by_name("ICAM1", organism="mouse")
    mouse_cd4_targets = chembl_parquet.search_targets_by_name("CD4", organism="mouse")
    molecule = chembl_parquet.get_molecule_info("CHEMBL2108326")
    mouse_molecule = chembl_parquet.get_molecule_info("CHEMBL_PRE_MOUSE")

    assert human_targets[0]["target_chembl_id"] == "CHEMBL_T_ICAM1_H"
    assert mouse_targets[0]["target_chembl_id"] == "CHEMBL_T_ICAM1_M"
    assert mouse_cd4_targets == []
    assert molecule["pref_name"] == "CAROTEGRAST"
    assert molecule["molecule_type"] == "Small molecule"
    assert mouse_molecule["pref_name"] == "MOUSEMAB"


def test_query_chembl_target_profile_prefers_local_data_and_supports_mouse(chembl_subset_dir):
    from src.agents.drug_target.tools import stage_domain_tools

    raw_human = stage_domain_tools.query_chembl_target_profile.invoke(
        {"gene_symbol": "ICAM1", "max_drugs": 5, "organism": "human"}
    )
    raw_mouse = stage_domain_tools.query_chembl_target_profile.invoke(
        {"gene_symbol": "ICAM1", "max_drugs": 5, "organism": "mouse"}
    )

    human = json.loads(raw_human)
    mouse = json.loads(raw_mouse)

    assert human["executed"] is True
    assert human["matched_drugs"][0]["drug_name"] == "BIOMAB"
    assert human["matched_drugs"][0]["chembl_id"] == "CHEMBL_PRE_HUMAN"
    assert human["matched_drugs"][0]["mechanism_of_action"] == "blocks ICAM1"
    assert mouse["executed"] is True
    assert mouse["matched_drugs"][0]["drug_name"] == "MOUSEMAB"


def test_query_chembl_target_profile_mouse_requires_local_data(monkeypatch):
    from src.agents.drug_target.tools import stage_domain_tools

    monkeypatch.setenv("CHEMBL_DATA_DIR", str(PROJECT_ROOT / "data" / "chembl_data_missing"))
    _reset_skill_loader_cache()
    stage_domain_tools._chembl_consecutive_failures = 0

    raw = stage_domain_tools.query_chembl_target_profile.invoke(
        {"gene_symbol": "ICAM1", "organism": "mouse"}
    )
    result = json.loads(raw)

    assert result["executed"] is False
    assert any("local-data-required" in err for err in result["errors"])


def test_resolve_chembl_drug_prefers_local_molecule_lookup(chembl_subset_dir):
    from src.agents.drug_target.tools import stage_logic

    stage_logic._chembl_drug_cache.clear()

    resolved = stage_logic._resolve_chembl_drug("CHEMBL2108326")

    assert resolved["name"] == "CAROTEGRAST"
    assert resolved["molecule_type"] == "Small molecule"


def test_drug_moa_cache_returns_resolved_only(tmp_path, monkeypatch):
    cache_dir = tmp_path / "drug_moa_cache"
    _write_moa_cache(
        cache_dir,
        [
            {
                "chembl_id": "CHEMBL_RESOLVED",
                "target_gene": "ICAM1",
                "status": "resolved",
                "mechanism_of_action": "cache-backed moa",
                "source": "opentargets",
                "source_target": "ICAM1",
                "retrieved_at": "2026-04-10T00:00:00+00:00",
            },
            {
                "chembl_id": "CHEMBL_EMPTY",
                "target_gene": "ICAM1",
                "status": "no_authoritative_moa",
                "mechanism_of_action": None,
                "source": None,
                "source_target": None,
                "retrieved_at": "2026-04-10T00:00:00+00:00",
            },
        ],
    )
    monkeypatch.setenv("DRUG_MOA_CACHE_DIR", str(cache_dir))

    from src.agents.drug_target.tools import drug_moa_cache

    importlib.reload(drug_moa_cache)

    assert drug_moa_cache.is_available() is True
    assert drug_moa_cache.get_cached_moa("CHEMBL_RESOLVED", "ICAM1") == "cache-backed moa"
    assert drug_moa_cache.get_cached_moa("CHEMBL_EMPTY", "ICAM1") is None


def test_query_chembl_target_profile_uses_local_moa_cache_when_chembl_missing(
    chembl_subset_dir,
    tmp_path,
    monkeypatch,
):
    mechanisms = pd.read_parquet(chembl_subset_dir / "mechanisms.parquet")
    mechanisms = mechanisms[mechanisms["molecule_chembl_id"] != "CHEMBL_PRE_HUMAN"].copy()
    mechanisms.to_parquet(chembl_subset_dir / "mechanisms.parquet", index=False)

    cache_dir = tmp_path / "drug_moa_cache"
    _write_moa_cache(
        cache_dir,
        [
            {
                "chembl_id": "CHEMBL_PRE_HUMAN",
                "target_gene": "ICAM1",
                "status": "resolved",
                "mechanism_of_action": "cache-backed ICAM1 inhibitor",
                "source": "opentargets",
                "source_target": "ICAM1",
                "retrieved_at": "2026-04-10T00:00:00+00:00",
            }
        ],
    )
    monkeypatch.setenv("DRUG_MOA_CACHE_DIR", str(cache_dir))
    _reset_skill_loader_cache()

    from src.agents.drug_target.tools import chembl_resolver, stage_domain_tools

    importlib.reload(chembl_resolver)
    importlib.reload(stage_domain_tools)
    stage_domain_tools._chembl_consecutive_failures = 0

    raw_human = stage_domain_tools.query_chembl_target_profile.invoke(
        {"gene_symbol": "ICAM1", "max_drugs": 5, "organism": "human"}
    )
    human = json.loads(raw_human)

    assert human["executed"] is True
    assert human["matched_drugs"][0]["chembl_id"] == "CHEMBL_PRE_HUMAN"
    assert human["matched_drugs"][0]["mechanism_of_action"] == "cache-backed ICAM1 inhibitor"


def test_refresh_drug_moa_cache_scans_stage3_and_writes_manifest(tmp_path, monkeypatch):
    cache_dir = tmp_path / "drug_moa_cache"
    monkeypatch.setenv("DRUG_MOA_CACHE_DIR", str(cache_dir))

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "stage3_ICAM1.json").write_text(
        json.dumps(
            {
                "gene_symbol": "ICAM1",
                "matched_drugs": [
                    {
                        "chembl_id": "CHEMBL_CACHE_ME",
                        "target_gene": "ICAM1",
                        "mechanism_of_action": None,
                        "indications": [],
                    },
                    {
                        "chembl_id": "CHEMBL_SKIP",
                        "target_gene": "ICAM1",
                        "mechanism_of_action": "already there",
                        "indications": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    refresh_mod = _load_script_module(
        "scripts/refresh_drug_moa_cache.py",
        "refresh_drug_moa_cache",
    )
    monkeypatch.setattr(
        refresh_mod,
        "fetch_opentargets_rows",
        lambda chembl_id: [{"mechanism_of_action": "cache moa", "targets": ["ICAM1"]}],
    )
    monkeypatch.setattr(refresh_mod, "fetch_chembl_rows", lambda chembl_id, target_lookup: [])

    manifest = refresh_mod.refresh_cache_from_stage3_files(
        [evidence_dir / "stage3_ICAM1.json"]
    )

    assert manifest["row_count"] == 1
    assert manifest["resolved_count"] == 1

    from src.agents.drug_target.tools import drug_moa_cache

    importlib.reload(drug_moa_cache)
    assert drug_moa_cache.get_cached_moa("CHEMBL_CACHE_ME", "ICAM1") == "cache moa"

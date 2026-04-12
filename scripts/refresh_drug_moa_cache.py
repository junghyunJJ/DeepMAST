#!/usr/bin/env python3
"""Refresh the local stage3 mechanism-of-action cache."""

from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]

OPEN_TARGETS_URL = "https://api.platform.opentargets.org/api/v4/graphql"
CHEMBL_MECHANISM_URL = "https://www.ebi.ac.uk/chembl/api/data/mechanism.json"
CHEMBL_MANIFEST_PATH = PROJECT_ROOT / "data" / "chembl" / "manifest.json"
TARGET_LOOKUP_PATH = PROJECT_ROOT / "data" / "chembl" / "target_lookup.parquet"


def _load_cache_module():
    module_path = PROJECT_ROOT / "src" / "agents" / "drug_target" / "tools" / "drug_moa_cache.py"
    spec = importlib.util.spec_from_file_location("drug_moa_cache", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load cache module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_gene(value: str | None) -> str:
    return (value or "").strip().upper()


def _iter_stage3_files(evidence_dir: Path) -> list[Path]:
    return sorted(
        path for path in evidence_dir.glob("stage3_*.json")
        if path.name != "stage3_deep_dive.json"
    )


def collect_missing_pairs(stage3_files: list[Path]) -> list[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for stage3_path in stage3_files:
        payload = json.loads(stage3_path.read_text(encoding="utf-8"))
        gene_symbol = _normalize_gene(payload.get("gene_symbol"))
        for drug in payload.get("matched_drugs", []) or []:
            chembl_id = str(drug.get("chembl_id", "")).strip().upper()
            if not chembl_id:
                continue
            if drug.get("mechanism_of_action"):
                continue
            target_gene = _normalize_gene(drug.get("target_gene")) or gene_symbol
            if not target_gene:
                continue
            pairs.add((chembl_id, target_gene))
    return sorted(pairs)


def load_target_lookup() -> dict[str, set[str]]:
    if not TARGET_LOOKUP_PATH.is_file():
        return {}
    df = pd.read_parquet(TARGET_LOOKUP_PATH)
    gene_rows = df[df["lookup_kind"] == "GENE_SYMBOL"].copy()
    mapping: dict[str, set[str]] = {}
    for _, row in gene_rows.iterrows():
        target_chembl_id = str(row.get("target_chembl_id", "")).strip().upper()
        lookup_term = _normalize_gene(row.get("lookup_term"))
        if not target_chembl_id or not lookup_term:
            continue
        mapping.setdefault(target_chembl_id, set()).add(lookup_term)
    return mapping


def fetch_opentargets_rows(chembl_id: str) -> list[dict[str, Any]]:
    query = """
    query DrugInfo($chemblId: String!) {
      drug(chemblId: $chemblId) {
        mechanismsOfAction {
          rows {
            mechanismOfAction
            targets { approvedSymbol }
          }
        }
      }
    }
    """
    response = requests.post(
        OPEN_TARGETS_URL,
        json={"query": query, "variables": {"chemblId": chembl_id}},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    drug_payload = payload.get("data", {}).get("drug") or {}
    rows = (
        drug_payload.get("mechanismsOfAction", {})
        .get("rows", [])
    )
    normalized = []
    for row in rows or []:
        moa = row.get("mechanismOfAction")
        targets = [
            _normalize_gene(target.get("approvedSymbol"))
            for target in row.get("targets", []) or []
            if _normalize_gene(target.get("approvedSymbol"))
        ]
        if moa:
            normalized.append({"mechanism_of_action": str(moa).strip(), "targets": targets})
    return normalized


def fetch_chembl_rows(chembl_id: str, target_lookup: dict[str, set[str]]) -> list[dict[str, Any]]:
    response = requests.get(
        CHEMBL_MECHANISM_URL,
        params={"molecule_chembl_id": chembl_id, "limit": 100},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    normalized = []
    for row in payload.get("mechanisms", []) or []:
        moa = row.get("mechanism_of_action")
        target_chembl_id = str(row.get("target_chembl_id", "")).strip().upper()
        targets = sorted(target_lookup.get(target_chembl_id, set()))
        if moa:
            normalized.append({"mechanism_of_action": str(moa).strip(), "targets": targets})
    return normalized


def _dedupe_moas(rows: list[dict[str, Any]]) -> list[str]:
    seen: list[str] = []
    for row in rows:
        moa = str(row.get("mechanism_of_action", "")).strip()
        if moa and moa not in seen:
            seen.append(moa)
    return seen


def select_moa(
    chembl_id: str,
    target_gene: str,
    ot_rows: list[dict[str, Any]],
    chembl_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    gene_key = _normalize_gene(target_gene)

    ot_target_rows = [row for row in ot_rows if gene_key in row.get("targets", [])]
    if ot_target_rows:
        moas = _dedupe_moas(ot_target_rows)
        return {
            "chembl_id": chembl_id,
            "target_gene": gene_key,
            "status": "resolved",
            "mechanism_of_action": " | ".join(moas),
            "source": "opentargets",
            "source_target": gene_key,
            "retrieved_at": datetime.now(UTC).isoformat(),
        }

    chembl_target_rows = [row for row in chembl_rows if gene_key in row.get("targets", [])]
    if chembl_target_rows:
        moas = _dedupe_moas(chembl_target_rows)
        return {
            "chembl_id": chembl_id,
            "target_gene": gene_key,
            "status": "resolved",
            "mechanism_of_action": " | ".join(moas),
            "source": "chembl",
            "source_target": gene_key,
            "retrieved_at": datetime.now(UTC).isoformat(),
        }

    ot_global = _dedupe_moas(ot_rows)
    if len(ot_global) == 1:
        return {
            "chembl_id": chembl_id,
            "target_gene": gene_key,
            "status": "resolved",
            "mechanism_of_action": ot_global[0],
            "source": "opentargets",
            "source_target": None,
            "retrieved_at": datetime.now(UTC).isoformat(),
        }

    chembl_global = _dedupe_moas(chembl_rows)
    if len(chembl_global) == 1:
        return {
            "chembl_id": chembl_id,
            "target_gene": gene_key,
            "status": "resolved",
            "mechanism_of_action": chembl_global[0],
            "source": "chembl",
            "source_target": None,
            "retrieved_at": datetime.now(UTC).isoformat(),
        }

    status = "not_found" if not ot_rows and not chembl_rows else "no_authoritative_moa"
    return {
        "chembl_id": chembl_id,
        "target_gene": gene_key,
        "status": status,
        "mechanism_of_action": None,
        "source": None,
        "source_target": None,
        "retrieved_at": datetime.now(UTC).isoformat(),
    }


def _source_versions() -> dict[str, Any]:
    versions: dict[str, Any] = {
        "opentargets_graphql": OPEN_TARGETS_URL,
        "chembl_rest": CHEMBL_MECHANISM_URL,
    }
    if CHEMBL_MANIFEST_PATH.is_file():
        try:
            manifest = json.loads(CHEMBL_MANIFEST_PATH.read_text(encoding="utf-8"))
            versions["chembl_local"] = {
                "release_id": manifest.get("release_id"),
                "built_at": manifest.get("built_at"),
            }
        except json.JSONDecodeError:
            pass
    return versions


def refresh_cache_from_stage3_files(stage3_files: list[Path]) -> dict[str, Any]:
    cache_module = _load_cache_module()
    target_lookup = load_target_lookup()
    entries: list[dict[str, Any]] = []
    for chembl_id, target_gene in collect_missing_pairs(stage3_files):
        ot_rows = fetch_opentargets_rows(chembl_id)
        chembl_rows = fetch_chembl_rows(chembl_id, target_lookup=target_lookup)
        entries.append(select_moa(chembl_id, target_gene, ot_rows, chembl_rows))
    return cache_module.write_entries(entries, source_versions=_source_versions())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        help="Directory containing stage3_*.json files.",
    )
    parser.add_argument(
        "--stage3-file",
        dest="stage3_files",
        action="append",
        type=Path,
        default=[],
        help="Specific stage3 file to scan. Repeatable.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    stage3_files = list(args.stage3_files)
    if args.evidence_dir:
        stage3_files.extend(_iter_stage3_files(args.evidence_dir))
    if not stage3_files:
        raise SystemExit("Provide --evidence-dir or at least one --stage3-file.")

    manifest = refresh_cache_from_stage3_files(stage3_files)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

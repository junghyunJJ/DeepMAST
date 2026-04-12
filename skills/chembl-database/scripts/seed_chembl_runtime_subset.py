#!/usr/bin/env python3
"""Seed a runtime-sized local ChEMBL subset from workspace Open Targets evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd
from chembl_webresource_client.new_client import new_client


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "chembl"
TARGET_TYPES = {"SINGLE PROTEIN", "PROTEIN COMPLEX", "PROTEIN FAMILY"}
ACTIVITY_TYPES = ("IC50", "Ki", "EC50")
ORGANISMS = ("human", "mouse")


def _load_example_queries():
    import importlib.util

    path = Path(__file__).resolve().parent / "example_queries.py"
    spec = importlib.util.spec_from_file_location("chembl_workspace_seed_runtime", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _extract_stage3_candidate_genes(assessment_payload) -> list[str]:
    if not isinstance(assessment_payload, dict):
        return []
    payload = assessment_payload.get("stage3_candidates", [])
    if not isinstance(payload, list):
        return []
    genes: list[str] = []
    for item in payload:
        if isinstance(item, dict):
            gene = item.get("gene") or item.get("gene_symbol") or item.get("symbol")
        else:
            gene = item
        if gene:
            genes.append(str(gene).upper())
    return genes


def _discover_workspace_seeds(root: Path, data_dir: Path | None = None) -> tuple[list[str], list[str]]:
    genes: set[str] = set()
    clinical_ids: set[str] = set()
    candidate_dirs: list[Path]
    if data_dir is not None:
        candidate_dirs = [data_dir]
    else:
        candidate_dirs = sorted(p for p in root.glob("res_*") if p.is_dir())

    for base_dir in candidate_dirs:
        evidence_dir = base_dir / "evidence"
        assessment_path = evidence_dir / "assessment_results.json"
        if assessment_path.exists():
            try:
                genes.update(_extract_stage3_candidate_genes(json.loads(assessment_path.read_text())))
            except Exception:
                pass
        ot_paths = evidence_dir.glob("ot_*.json")
        for ot_path in ot_paths:
            match = re.match(r"ot_(.+)\.json$", ot_path.name)
            if match and data_dir is None:
                genes.add(match.group(1).upper())
            try:
                data = json.loads(ot_path.read_text())
            except Exception:
                continue
            rows = data.get("target_drugs", {})
            if isinstance(rows, dict):
                rows = rows.get("rows", [])
            if not isinstance(rows, list):
                rows = []
            for row in rows:
                chembl_id = row.get("drug", {}).get("id")
                if chembl_id:
                    clinical_ids.add(chembl_id)
    return sorted(genes), sorted(clinical_ids)


def build_runtime_subset(
    *,
    out_dir: Path,
    activity_limit: int = 25,
    data_dir: Path | None = None,
) -> dict[str, object]:
    root = PROJECT_ROOT
    mod = _load_example_queries()
    genes, clinical_ids = _discover_workspace_seeds(root, data_dir=data_dir)

    target_rows: list[dict] = []
    lookup_rows: list[dict] = []
    activity_rows: list[dict] = []
    molecule_ids = set(clinical_ids)
    seen_targets: set[tuple[str, str]] = set()
    seen_lookup: set[tuple[str, str, str, str]] = set()
    seen_target_activities: set[tuple[str, str]] = set()
    seen_activity_rows: set[tuple[str, str, str, str, str]] = set()

    for gene in genes:
        for organism in ORGANISMS:
            try:
                targets = mod.search_targets_by_name(gene, organism=organism)
            except Exception:
                continue
            for target in targets:
                if target.get("target_type") not in TARGET_TYPES:
                    continue
                target_id = target.get("target_chembl_id")
                if not target_id:
                    continue
                target_key = (organism, target_id)
                if target_key not in seen_targets:
                    seen_targets.add(target_key)
                    target_rows.append(
                        {
                            "target_chembl_id": target_id,
                            "pref_name": target.get("pref_name"),
                            "target_type": target.get("target_type"),
                            "organism": organism,
                        }
                    )

                lookup_terms = [(gene, "GENE_SYMBOL", 0), (target.get("pref_name") or "", "PREF_NAME", 3)]
                for comp in target.get("target_components", []) or []:
                    for syn in comp.get("target_component_synonyms", []) or []:
                        term = str(syn.get("component_synonym") or "").strip()
                        kind = str(syn.get("syn_type") or "SYNONYM").strip() or "SYNONYM"
                        if term:
                            priority = 0 if kind.upper() == "GENE_SYMBOL" else 2
                            lookup_terms.append((term, kind, priority))
                for term, kind, priority in lookup_terms:
                    term = str(term).strip()
                    if not term:
                        continue
                    lookup_key = (organism, term, kind, target_id)
                    if lookup_key in seen_lookup:
                        continue
                    seen_lookup.add(lookup_key)
                    lookup_rows.append(
                        {
                            "organism": organism,
                            "lookup_term": term,
                            "lookup_kind": kind,
                            "target_chembl_id": target_id,
                            "match_priority": priority,
                        }
                    )

                if target_key in seen_target_activities:
                    continue
                seen_target_activities.add(target_key)
                selected_activities: list[dict] = []
                for activity_type in ACTIVITY_TYPES:
                    query = new_client.activity.filter(
                        target_chembl_id=target_id,
                        standard_type=activity_type,
                        standard_value__lte=10000,
                        standard_units="nM",
                    )
                    selected_activities = list(query[:activity_limit])
                    if selected_activities:
                        break
                for act in selected_activities:
                    mol_id = act.get("molecule_chembl_id")
                    if not mol_id:
                        continue
                    row_key = (
                        target_id,
                        mol_id,
                        str(act.get("standard_type") or ""),
                        str(act.get("standard_value") or ""),
                        str(act.get("activity_id") or act.get("record_id") or ""),
                    )
                    if row_key in seen_activity_rows:
                        continue
                    seen_activity_rows.add(row_key)
                    molecule_ids.add(mol_id)
                    activity_rows.append(
                        {
                            "target_chembl_id": target_id,
                            "molecule_chembl_id": mol_id,
                            "molecule_pref_name": act.get("molecule_pref_name"),
                            "standard_type": act.get("standard_type"),
                            "standard_value": pd.to_numeric(act.get("standard_value"), errors="coerce"),
                            "standard_units": act.get("standard_units"),
                            "pchembl_value": pd.to_numeric(act.get("pchembl_value"), errors="coerce"),
                        }
                    )

    molecule_rows: list[dict] = []
    mechanism_rows: list[dict] = []
    indication_rows: list[dict] = []
    seen_mech: set[tuple[str, str]] = set()
    seen_ind: set[tuple[str, str, str, str]] = set()

    for chembl_id in sorted(molecule_ids):
        try:
            mol = mod.get_molecule_info(chembl_id) or {}
        except Exception:
            mol = {}
        molecule_rows.append(
            {
                "molecule_chembl_id": chembl_id,
                "pref_name": mol.get("pref_name"),
                "molecule_type": mol.get("molecule_type"),
                "first_approval": mol.get("first_approval"),
                "max_phase": pd.to_numeric(mol.get("max_phase"), errors="coerce"),
            }
        )
        try:
            _drug_info, mechanisms, indications = mod.get_drug_info(chembl_id)
        except Exception:
            mechanisms, indications = [], []
        for mech in mechanisms or []:
            moa = mech.get("mechanism_of_action")
            if not moa:
                continue
            key = (chembl_id, moa)
            if key in seen_mech:
                continue
            seen_mech.add(key)
            mechanism_rows.append({"molecule_chembl_id": chembl_id, "mechanism_of_action": moa})
        for ind in indications or []:
            efo = ind.get("efo_term")
            mesh = ind.get("mesh_heading")
            phase = ind.get("max_phase_for_ind")
            key = (chembl_id, str(efo or ""), str(mesh or ""), str(phase or ""))
            if key in seen_ind:
                continue
            seen_ind.add(key)
            indication_rows.append(
                {
                    "molecule_chembl_id": chembl_id,
                    "efo_term": efo,
                    "mesh_heading": mesh,
                    "max_phase_for_ind": pd.to_numeric(phase, errors="coerce"),
                }
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    lookup_df = pd.DataFrame(lookup_rows).drop_duplicates().sort_values(
        ["organism", "match_priority", "lookup_term", "target_chembl_id"], kind="stable"
    )
    targets_df = pd.DataFrame(target_rows).drop_duplicates().sort_values(
        ["organism", "pref_name", "target_chembl_id"], kind="stable"
    )
    activities_df = pd.DataFrame(activity_rows).drop_duplicates().sort_values(
        ["target_chembl_id", "standard_type", "standard_value", "molecule_chembl_id"],
        kind="stable",
    )
    molecules_df = pd.DataFrame(molecule_rows).drop_duplicates().sort_values(
        ["molecule_chembl_id"], kind="stable"
    )
    mechanisms_df = pd.DataFrame(mechanism_rows).drop_duplicates().sort_values(
        ["molecule_chembl_id", "mechanism_of_action"], kind="stable"
    )
    indications_df = pd.DataFrame(indication_rows).drop_duplicates().sort_values(
        ["molecule_chembl_id", "max_phase_for_ind", "efo_term"],
        ascending=[True, False, True],
        kind="stable",
    )

    lookup_df.to_parquet(out_dir / "target_lookup.parquet", index=False)
    targets_df.to_parquet(out_dir / "targets.parquet", index=False)
    activities_df.to_parquet(out_dir / "activities.parquet", index=False)
    molecules_df.to_parquet(out_dir / "molecules.parquet", index=False)
    mechanisms_df.to_parquet(out_dir / "mechanisms.parquet", index=False)
    indications_df.to_parquet(out_dir / "indications.parquet", index=False)

    manifest = {
        "release_id": "workspace_api_seed_runtime",
        "built_at": pd.Timestamp.utcnow().isoformat(),
        "species": list(ORGANISMS),
        "filters": {
            "target_types": sorted(TARGET_TYPES),
            "activity_types": list(ACTIVITY_TYPES),
            "standard_units": "nM",
            "activity_limit_per_target": activity_limit,
            "activity_selection": "first non-empty of IC50, Ki, EC50",
            "seed_gene_count": len(genes),
            "clinical_chembl_id_count": len(clinical_ids),
            "seed_data_dir": str(data_dir) if data_dir is not None else None,
            "source": "chembl_webresource_client seeded from res_*/evidence/ot_*.json",
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
            "target_lookup": int(len(lookup_df)),
            "targets": int(len(targets_df)),
            "molecules": int(len(molecules_df)),
            "activities": int(len(activities_df)),
            "mechanisms": int(len(mechanisms_df)),
            "indications": int(len(indications_df)),
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--activity-limit", type=int, default=25)
    parser.add_argument("--data-dir", default=None)
    args = parser.parse_args()

    manifest = build_runtime_subset(
        out_dir=Path(args.out_dir),
        activity_limit=args.activity_limit,
        data_dir=Path(args.data_dir).expanduser().resolve() if args.data_dir else None,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()

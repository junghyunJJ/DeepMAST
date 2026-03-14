#!/usr/bin/env python3
"""Re-run Stage 1 with Census coexpression + CellXGene for all L-R pairs."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.drug_target.tools.census_lr_validation_tools import (
    run_compare_census_lr_pair,
)
from src.agents.drug_target.tools.stage_domain_tools import (
    query_cellxgene_lr_context,
)
from src.agents.drug_target.tools.stage1_normalization import (
    finalize_stage1_workspace,
    load_stage1_json,
    normalize_stage1_record,
    resolve_stage1_context,
)


DELAY = 1.0


def _call_tool(tool_fn, **kwargs):
    raw = tool_fn.invoke(kwargs)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {"raw": str(raw), "errors": ["parse_failed"]}


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"  Saved -> {path.name}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "data_dir",
        nargs="?",
        default="res_bc_ollama",
        help="Data directory that contains lr_candidates.json and evidence/",
    )
    parser.add_argument(
        "--disease",
        help="Census disease label to query",
    )
    parser.add_argument(
        "--target-cell-type",
        help="Target cell type for compare_census runs",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    data_dir = (PROJECT_ROOT / args.data_dir).resolve()
    evidence_dir = data_dir / "evidence"
    context = resolve_stage1_context(
        data_dir,
        disease=args.disease,
        target_cell_type=args.target_cell_type,
        allow_existing_evidence_fallback=False,
    )
    census_disease = context["disease"]
    target_cell_type = context["requested_target_cell_type"]

    lr_data = json.loads((data_dir / "lr_candidates.json").read_text())
    pairs = lr_data.get("pairs", lr_data.get("candidate_pairs", []))
    print(f"Loaded {len(pairs)} L-R candidate pairs")
    print(
        f"Census disease: {census_disease} "
        f"(source={context['disease_source']})"
    )
    print(
        f"Target cell type: {target_cell_type} "
        f"(source={context['requested_target_cell_type_source']})"
    )

    print("\n" + "=" * 70)
    print("PHASE 1: CellXGene Gene Availability")
    print("=" * 70)

    cellxgene_all_path = evidence_dir / "stage1_cellxgene_all_pairs.json"
    cellxgene_data = {}
    if cellxgene_all_path.exists():
        cellxgene_data = json.loads(cellxgene_all_path.read_text())
        print(
            "Loaded existing CellXGene data: "
            f"all_genes_available={cellxgene_data.get('all_genes_available')}"
        )

    cellxgene_per_pair = {}
    all_genes = {
        gene.upper()
        for pair in pairs
        for gene in (pair["ligand"], pair["receptor"])
    }

    if cellxgene_data.get("all_genes_available"):
        print(f"All {len(all_genes)} genes confirmed available in CellXGene Census")
        for pair in pairs:
            key = f"{pair['ligand']}_{pair['receptor']}"
            cellxgene_per_pair[key] = {
                "available_genes": [pair["ligand"].upper(), pair["receptor"].upper()],
                "executed": True,
            }
    else:
        for i, pair in enumerate(pairs, start=1):
            lig, rec = pair["ligand"], pair["receptor"]
            key = f"{lig}_{rec}"
            print(f"  [{i}/{len(pairs)}] CellXGene {lig}^{rec} ...", end=" ", flush=True)
            result = _call_tool(
                query_cellxgene_lr_context,
                ligand=lig,
                receptor=rec,
                disease=census_disease,
            )
            cellxgene_per_pair[key] = result
            print(f"genes={result.get('available_genes', [])}")
            time.sleep(0.5)

    print("\n" + "=" * 70)
    print("PHASE 2: Census Coexpression Analysis (ALL pairs)")
    print("=" * 70)

    census_results = {}
    for i, pair in enumerate(pairs, start=1):
        lig, rec = pair["ligand"], pair["receptor"]
        key = f"{lig}_{rec}"
        print(f"\n[{i}/{len(pairs)}] Census {lig}^{rec}")
        print("  -> Running compare_census ...", end=" ", flush=True)
        result = _call_tool(
            run_compare_census_lr_pair,
            data_dir=str(data_dir),
            disease=census_disease,
            gene_a=lig,
            gene_b=rec,
            target_cell_type=target_cell_type,
            timeout_sec=180,
        )
        census_results[key] = result

        coexpr = (result.get("target_vs_rest") or {}).get("coexpression") or {}
        print(
            f"executed={result.get('executed', False)}, "
            f"p={coexpr.get('p_value', 'N/A')}, RR={coexpr.get('risk_ratio', 'N/A')}",
            end="",
        )
        if result.get("errors"):
            print(f", errors={result['errors']}", end="")
        print()
        time.sleep(DELAY)

    print("\n" + "=" * 70)
    print("PHASE 3: Merge Evidence & Recompute Confidence")
    print("=" * 70)

    stage1_confidence = {}
    for pair in pairs:
        lig, rec = pair["ligand"], pair["receptor"]
        key = f"{lig}_{rec}"
        pair_key = f"{lig}^{rec}"
        ev_path = evidence_dir / f"stage1_{key}.json"

        if ev_path.exists():
            evidence, _ = load_stage1_json(ev_path)
        else:
            print(f"  WARNING: No existing evidence for {pair_key}, creating new")
            evidence = {"ligand": lig, "receptor": rec}

        census = census_results.get(key, {})
        if census.get("executed"):
            evidence["census_validation"] = {
                "disease": census.get("disease", census_disease),
                "requested_cell_type": census.get("requested_cell_type", target_cell_type),
                "resolved_cell_type": census.get("resolved_cell_type", target_cell_type),
                "resolution_mode": census.get("resolution_mode", "exact"),
                "target_vs_rest": census.get("target_vs_rest", {}),
                "executed": True,
            }
        elif "census_validation" not in evidence:
            evidence["census_validation"] = {
                "executed": False,
                "errors": census.get("errors", ["Census query did not execute"]),
            }

        cxg = cellxgene_per_pair.get(key, {})
        evidence["cellxgene"] = {
            "available_genes": cxg.get("available_genes", []),
            "executed": cxg.get("executed", False),
        }

        normalized, _ = normalize_stage1_record(
            evidence,
            ligand=lig,
            receptor=rec,
            evidence_dir=evidence_dir,
            requested_target_cell_type=target_cell_type,
            resolved_target_cell_type=census.get("resolved_cell_type", target_cell_type),
            csv_target_cell_type=target_cell_type,
            disease=census_disease,
            disease_source=context["disease_source"],
            target_cell_type_source=context["requested_target_cell_type_source"],
        )
        conf = normalized["stage1_confidence"]
        stage1_confidence[pair_key] = conf
        _save_json(ev_path, normalized)
        print(
            f"  {pair_key}: confidence={conf['confidence']:.4f} "
            f"(STRING={conf['string_score']:.3f}, "
            f"census={conf['census_score']:.3f}, "
            f"pathway={conf['pathway_score']:.1f}, "
            f"expr={conf['expression_score']:.2f})"
        )

    final_result = finalize_stage1_workspace(
        data_dir,
        disease=census_disease,
        target_cell_type=target_cell_type,
        rerun_missing_census=False,
    )
    if not final_result["success"]:
        print("\nStage1 finalization failed:")
        for err in final_result["post_validation"]["errors"]:
            print(f"  - {err}")
        raise SystemExit(1)

    print(f"\n{'=' * 70}")
    print("STAGE 1 RE-RUN WITH CENSUS COMPLETE")
    print(f"{'=' * 70}")

    n_census_ok = sum(1 for result in census_results.values() if result.get("executed"))
    n_census_coexpr = sum(
        1
        for result in census_results.values()
        if (result.get("target_vs_rest") or {}).get("coexpression") is not None
    )
    n_high_conf = sum(
        1
        for conf in stage1_confidence.values()
        if conf.get("confidence", 0) >= 0.7
    )
    avg_conf = (
        sum(conf.get("confidence", 0) for conf in stage1_confidence.values())
        / len(stage1_confidence)
        if stage1_confidence else 0
    )

    print(f"  Total pairs: {len(pairs)}")
    print(f"  Census executed: {n_census_ok}/{len(pairs)}")
    print(f"  Census coexpression found: {n_census_coexpr}/{len(pairs)}")
    print(f"  High confidence (>=0.7): {n_high_conf}/{len(pairs)}")
    print(f"  Average confidence: {avg_conf:.3f}")
    print("  Canonical outputs: stage1_evidence.json, stage1_confidence.json, stage1_audit.json")

    print("\n-- Confidence Ranking --")
    for rank, (pair_key, conf) in enumerate(
        sorted(
            stage1_confidence.items(),
            key=lambda item: item[1].get("confidence", 0),
            reverse=True,
        ),
        start=1,
    ):
        print(
            f"  {rank:2d}. {pair_key:25s} {conf['confidence']:.4f} "
            f"(S={conf['string_score']:.3f} C={conf['census_score']:.3f} "
            f"P={conf['pathway_score']:.1f} E={conf['expression_score']:.2f})"
        )


if __name__ == "__main__":
    main()

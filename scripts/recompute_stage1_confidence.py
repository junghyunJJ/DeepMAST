#!/usr/bin/env python3
"""Recompute Stage 1 confidence scores from individual stage1_*.json files."""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.drug_target.tools.stage1_normalization import finalize_stage1_workspace


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "data_dir",
        nargs="?",
        default="res_bc_ollama",
        help="Data directory that contains the evidence/ folder",
    )
    parser.add_argument(
        "--disease",
        default=None,
        help="Optional disease override. If omitted, metadata/evidence context is used.",
    )
    parser.add_argument(
        "--target-cell-type",
        default=None,
        help="Optional primary target cell type override. If omitted, metadata/evidence context is used.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    data_dir = (PROJECT_ROOT / args.data_dir).resolve()

    print(f"Finalizing Stage1 artifacts under {data_dir}")
    result = finalize_stage1_workspace(
        data_dir,
        disease=args.disease,
        target_cell_type=args.target_cell_type,
        rerun_missing_census=True,
    )
    if not result["success"]:
        print("Stage1 finalization failed:")
        for err in result["post_validation"]["errors"]:
            print(f"  - {err}")
        raise SystemExit(1)

    rebuilt = json.loads((data_dir / "evidence" / "stage1_confidence.json").read_text())
    audit = json.loads((data_dir / "evidence" / "stage1_audit.json").read_text())

    context = result["context"]
    print(
        "Resolved context: "
        f"disease={context['disease']} [{context['disease_source']}], "
        f"requested_target={context['requested_target_cell_type']} "
        f"[{context['requested_target_cell_type_source']}], "
        f"resolved_target={context['resolved_target_cell_type']} "
        f"[{context['resolved_target_cell_type_source']}]"
    )

    print(f"Found {len(result['rebuild']['stage1_files'])} individual stage1 files")
    for pair_key, conf in sorted(rebuilt.items()):
        print(
            f"  {pair_key}: confidence {conf['confidence']:.4f} "
            f"(str={conf['string_score']:.3f} cen={conf['census_score']:.3f} "
            f"path={conf['pathway_score']:.3f} expr={conf['expression_score']:.3f})"
        )

    repaired = {
        pair_key: details.get("repairs", [])
        for pair_key, details in audit.items()
        if details.get("repairs")
    }
    if repaired:
        print("\nRepairs:")
        for pair_key, repairs in sorted(repaired.items()):
            print(f"  {pair_key}: {', '.join(repairs)}")

    reruns = [item for item in result["rerun_results"] if item.get("executed")]
    if reruns:
        print("\nRerun Census CSVs:")
        for item in reruns:
            print(
                f"  {item['csv_file']}: resolved_cell_type={item.get('resolved_cell_type')} "
                f"disease={item.get('disease')}"
            )

    print("\nWrote:")
    print(f"  {data_dir / 'evidence' / 'stage1_evidence.json'}")
    print(f"  {data_dir / 'evidence' / 'stage1_confidence.json'}")
    print(f"  {data_dir / 'evidence' / 'stage1_audit.json'}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Aggregate LLM entity-coverage labels into arm-level coverage_pct (ON vs OFF).

Per (case, arm), coverage_pct = |union of covered entities across the arm's papers|
/ |case entities|, mirroring regex `_calculate_coverage` but using LLM labels.
Computes both RAW (all retrieved) and FILTERED (direct+context handoff) coverage so
the regex headline can be validated directly.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path


def _load_labels(path: Path) -> dict[tuple[str, str], dict[str, list[str]]]:
    labels: dict[tuple[str, str], dict[str, list[str]]] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if not obj.get("ok"):
            continue
        labels[(str(obj["case_id"]), str(obj["pmid"]))] = {
            "pathways": obj.get("pathways_covered") or [],
            "celltypes": obj.get("celltypes_covered") or [],
        }
    return labels


def _pmids(path: Path) -> list[str]:
    if not path.exists():
        return []
    papers = json.loads(path.read_text()).get("papers", [])
    return [str(p.get("pmid", "")).strip() for p in papers if str(p.get("pmid", "")).strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner-rows", required=True)
    parser.add_argument("--labels", required=True)
    args = parser.parse_args()

    labels = _load_labels(Path(args.labels))
    rows = [json.loads(line) for line in Path(args.runner_rows).read_text().splitlines() if line.strip()]

    # per condition: list of per-case coverage_pct for pathways/celltypes, raw & filtered
    cov: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        ws = row.get("trial_workspace")
        if not ws:
            continue
        ctx_path = Path(ws) / "search_context.json"
        ctx = json.loads(ctx_path.read_text()) if ctx_path.exists() else {}
        case_pathways = list(ctx.get("pathways") or row.get("pathways") or [])
        case_celltypes = list(ctx.get("celltypes") or row.get("celltypes") or [])
        raw_pmids = _pmids(Path(ws) / "papers_raw.json")
        filt_pmids = set(_pmids(Path(ws) / "papers_filtered.json"))
        cond = row["condition"]

        for setname, pmid_set in (("raw", set(raw_pmids)), ("filtered", filt_pmids)):
            union_p: set[str] = set()
            union_c: set[str] = set()
            for pmid in pmid_set:
                lab = labels.get((row["case_id"], pmid))
                if not lab:
                    continue
                union_p.update(lab["pathways"])
                union_c.update(lab["celltypes"])
            if case_pathways:
                cov[cond][f"{setname}_path"].append(100 * len(union_p & set(case_pathways)) / len(case_pathways))
            if case_celltypes:
                cov[cond][f"{setname}_cell"].append(100 * len(union_c & set(case_celltypes)) / len(case_celltypes))

    def m(cond: str, key: str) -> float:
        v = cov[cond][key]
        return st.mean(v) if v else float("nan")

    print(f"{'arm':22}{'raw_path':>10}{'filt_path':>11}{'raw_cell':>10}{'filt_cell':>11}")
    for cond in ("strong_updated_skill", "strong_no_skill", "weak_updated_skill", "weak_no_skill"):
        print(f"{cond:22}{m(cond,'raw_path'):>10.1f}{m(cond,'filtered_path'):>11.1f}"
              f"{m(cond,'raw_cell'):>10.1f}{m(cond,'filtered_cell'):>11.1f}")

    print("\nON-OFF Δ (LLM coverage):")
    for strength in ("strong", "weak"):
        on, off = f"{strength}_updated_skill", f"{strength}_no_skill"
        print(f"  {strength}: pathways raw Δ={m(on,'raw_path')-m(off,'raw_path'):+.1f}pp "
              f"filt Δ={m(on,'filtered_path')-m(off,'filtered_path'):+.1f}pp  |  "
              f"celltypes raw Δ={m(on,'raw_cell')-m(off,'raw_cell'):+.1f}pp "
              f"filt Δ={m(on,'filtered_cell')-m(off,'filtered_cell'):+.1f}pp")


if __name__ == "__main__":
    main()

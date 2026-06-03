#!/usr/bin/env python3
"""Combine 122b gene + entity (pathway/celltype) coverage labels into final tables.

Per (case, arm), coverage_pct = |union covered entities across arm's papers| / |case entities|.
Reports genes, pathways, celltypes for RAW (all retrieved) and FILTERED (direct+context),
plus the number of papers checked per arm.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

ARMS = ("strong_updated_skill", "strong_no_skill", "weak_updated_skill", "weak_no_skill")


def _load(path: Path, key: str) -> dict[tuple[str, str], list[str]]:
    out: dict[tuple[str, str], list[str]] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if not obj.get("ok"):
            continue
        out[(str(obj["case_id"]), str(obj["pmid"]))] = obj.get(key) or []
    return out


def _load_entities(path: Path) -> dict[tuple[str, str], dict[str, list[str]]]:
    out: dict[tuple[str, str], dict[str, list[str]]] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if not obj.get("ok"):
            continue
        out[(str(obj["case_id"]), str(obj["pmid"]))] = {
            "pathways": obj.get("pathways_covered") or [],
            "celltypes": obj.get("celltypes_covered") or [],
        }
    return out


def _pmids(path: Path) -> list[str]:
    if not path.exists():
        return []
    papers = json.loads(path.read_text()).get("papers", [])
    return [str(p.get("pmid", "")).strip() for p in papers if str(p.get("pmid", "")).strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runner-rows", required=True)
    ap.add_argument("--gene-labels", required=True)
    ap.add_argument("--entity-labels", required=True)
    args = ap.parse_args()

    genes = _load(Path(args.gene_labels), "genes_covered")
    ents = _load_entities(Path(args.entity_labels))

    rows = [json.loads(l) for l in Path(args.runner_rows).read_text().splitlines() if l.strip()]

    # cov[arm][f"{set}_{metric}"] = list of per-case pct ; npapers[arm][set] = list of per-case counts
    cov: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    npapers: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))

    for row in rows:
        ws = row.get("trial_workspace")
        if not ws:
            continue
        ctx_path = Path(ws) / "search_context.json"
        ctx = json.loads(ctx_path.read_text()) if ctx_path.exists() else {}
        case_genes = [g for g in (row.get("ligand"), row.get("receptor")) if g]
        case_paths = list(ctx.get("pathways") or row.get("pathways") or [])
        case_cells = list(ctx.get("celltypes") or row.get("celltypes") or [])
        cond, cid = row["condition"], row["case_id"]

        for setname, pmids in (("raw", _pmids(Path(ws) / "papers_raw.json")),
                               ("filt", _pmids(Path(ws) / "papers_filtered.json"))):
            npapers[cond][setname].append(len(pmids))
            ug, up, uc = set(), set(), set()
            for pmid in set(pmids):
                ug.update(genes.get((cid, pmid), []))
                e = ents.get((cid, pmid), {})
                up.update(e.get("pathways", []))
                uc.update(e.get("celltypes", []))
            if case_genes:
                cov[cond][f"{setname}_gene"].append(100 * len(ug & set(case_genes)) / len(case_genes))
            if case_paths:
                cov[cond][f"{setname}_path"].append(100 * len(up & set(case_paths)) / len(case_paths))
            if case_cells:
                cov[cond][f"{setname}_cell"].append(100 * len(uc & set(case_cells)) / len(case_cells))

    def m(cond: str, key: str) -> float:
        v = cov[cond][key]
        return st.mean(v) if v else float("nan")

    def npap(cond: str, s: str) -> tuple[int, float]:
        v = npapers[cond][s]
        return sum(v), (st.mean(v) if v else 0.0)

    for setname, label in (("raw", "ALL retrieved (raw)"), ("filt", "direct/context only (filtered)")):
        print(f"\n================ 122b LLM coverage — {label} ================")
        print(f"{'지표':18}{'strong ON':>10}{'strong OFF':>11}{'Δ':>8}{'weak ON':>9}{'weak OFF':>10}{'Δ':>8}")
        for metric, name in (("gene", "genes_coverage"), ("path", "pathways_coverage"), ("cell", "celltypes_coverage")):
            son, sof = m("strong_updated_skill", f"{setname}_{metric}"), m("strong_no_skill", f"{setname}_{metric}")
            won, wof = m("weak_updated_skill", f"{setname}_{metric}"), m("weak_no_skill", f"{setname}_{metric}")
            print(f"{name:18}{son:>10.1f}{sof:>11.1f}{son-sof:>+8.1f}{won:>9.1f}{wof:>10.1f}{won-wof:>+8.1f}")
        # papers checked
        print("-" * 74)
        line = f"{'N papers (총/평균)':18}"
        for cond in ("strong_updated_skill", "strong_no_skill", None, "weak_updated_skill", "weak_no_skill", None):
            if cond is None:
                line += f"{'':>8}"
                continue
            tot, mean = npap(cond, setname)
            line += f"{f'{tot}/{mean:.0f}':>11}" if "updated" not in cond else f"{f'{tot}/{mean:.0f}':>10}"
        print(line)


if __name__ == "__main__":
    main()

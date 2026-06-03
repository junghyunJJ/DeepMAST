#!/usr/bin/env python3
"""Export tidy coverage data + group summaries + paired significance for the R figure.

Writes into <results_dir>/manuscript/tables/:
  - coverage_percase.csv     (case_id, set, metric, strength, arm, coverage_pct)
  - coverage_group_summary.csv (set, strength, metric, arm, mean, ci_lo, ci_hi, n)
  - coverage_sig.csv         (set, strength, metric, n_pairs, mean_delta, wilcoxon_p, sig)
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

RNG = np.random.default_rng(20260602)
SETS = (("raw", "papers_raw.json"), ("filtered", "papers_filtered.json"))
METRICS = ("genes", "pathways", "celltypes")


def _load(path: Path, key: str) -> dict[tuple[str, str], list[str]]:
    out: dict[tuple[str, str], list[str]] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and (o := json.loads(line)).get("ok"):
            out[(str(o["case_id"]), str(o["pmid"]))] = o.get(key) or []
    return out


def _pmids(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [str(p.get("pmid", "")).strip()
            for p in json.loads(path.read_text()).get("papers", [])
            if str(p.get("pmid", "")).strip()]


def _boot_ci(vals: list[float], n: int = 10000) -> tuple[float, float]:
    a = np.asarray(vals, dtype=float)
    if len(a) == 0:
        return float("nan"), float("nan")
    means = a[RNG.integers(0, len(a), size=(n, len(a)))].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _sig(p: float) -> str:
    if p != p:
        return "ns"
    return "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", required=True)
    args = ap.parse_args()
    root = Path(args.results_dir)

    genes = _load(root / "gene_coverage_labels_122b.jsonl", "genes_covered")
    paths = _load(root / "entity_coverage_labels_122b.jsonl", "pathways_covered")
    cells = _load(root / "entity_coverage_labels_122b.jsonl", "celltypes_covered")
    rows = [json.loads(l) for l in (root / "converted_runner_rows.jsonl").read_text().splitlines() if l.strip()]

    # percase[(set, metric, strength, arm)][case_id] = pct
    percase: dict[tuple, dict[str, float]] = defaultdict(dict)
    for row in rows:
        ws = row.get("trial_workspace")
        if not ws:
            continue
        ctx_path = Path(ws) / "search_context.json"
        ctx = json.loads(ctx_path.read_text()) if ctx_path.exists() else {}
        entdef = {
            "genes": ([g for g in (row.get("ligand"), row.get("receptor")) if g], genes),
            "pathways": (list(ctx.get("pathways") or row.get("pathways") or []), paths),
            "celltypes": (list(ctx.get("celltypes") or row.get("celltypes") or []), cells),
        }
        strength = row["model_strength"]
        arm = "ON" if row["skill_arm"] == "updated_skill" else "OFF"
        cid = row["case_id"]
        for setname, fname in SETS:
            pmid_set = set(_pmids(Path(ws) / fname))
            for metric, (case_ents, labelmap) in entdef.items():
                if not case_ents:
                    continue
                union: set[str] = set()
                for pmid in pmid_set:
                    union.update(labelmap.get((cid, pmid), []))
                percase[(setname, metric, strength, arm)][cid] = 100 * len(union & set(case_ents)) / len(case_ents)

    tdir = root / "manuscript" / "tables"
    tdir.mkdir(parents=True, exist_ok=True)

    # 1) per-case tidy
    with (tdir / "coverage_percase.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["case_id", "set", "metric", "strength", "arm", "coverage_pct"])
        for (setname, metric, strength, arm), d in percase.items():
            for cid, pct in d.items():
                w.writerow([cid, setname, metric, strength, arm, f"{pct:.4f}"])

    # 2) group summary (mean + bootstrap CI)
    with (tdir / "coverage_group_summary.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["set", "strength", "metric", "arm", "mean", "ci_lo", "ci_hi", "n"])
        for setname, _ in SETS:
            for strength in ("strong", "weak"):
                for metric in METRICS:
                    for arm in ("ON", "OFF"):
                        vals = list(percase[(setname, metric, strength, arm)].values())
                        if not vals:
                            continue
                        lo, hi = _boot_ci(vals)
                        w.writerow([setname, strength, metric, arm,
                                    f"{np.mean(vals):.4f}", f"{lo:.4f}", f"{hi:.4f}", len(vals)])

    # 3) paired significance (per strength + pooled)
    with (tdir / "coverage_sig.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["set", "strength", "metric", "n_pairs", "mean_delta", "wilcoxon_p", "sig"])
        for setname, _ in SETS:
            for metric in METRICS:
                for strata, sl in (("strong", ["strong"]), ("weak", ["weak"]), ("pooled", ["strong", "weak"])):
                    diffs = []
                    for s in sl:
                        on = percase[(setname, metric, s, "ON")]
                        off = percase[(setname, metric, s, "OFF")]
                        diffs += [on[c] - off[c] for c in on.keys() & off.keys()]
                    d = np.asarray(diffs, dtype=float)
                    nz = d[d != 0]
                    p = float("nan")
                    if len(nz) >= 1:
                        try:
                            p = float(stats.wilcoxon(d, alternative="two-sided", zero_method="wilcox").pvalue)
                        except ValueError:
                            p = float("nan")
                    w.writerow([setname, strata, metric, len(d),
                                f"{d.mean():.3f}" if len(d) else "nan",
                                f"{p:.5f}", _sig(p)])

    print("wrote:", tdir / "coverage_percase.csv", tdir / "coverage_group_summary.csv", tdir / "coverage_sig.csv", sep="\n  ")


if __name__ == "__main__":
    main()

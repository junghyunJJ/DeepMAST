#!/usr/bin/env python3
"""Paired statistical tests on 122b coverage (ON vs OFF), per case.

For each (set, metric, strength) builds per-case paired coverage_pct (skill ON vs OFF),
then tests the per-case difference (ON-OFF) with:
  - Wilcoxon signed-rank (two-sided)
  - exact sign test (binomial on non-zero pairs)
  - bootstrap 95% CI on the mean difference
Reports strong, weak, and pooled (both strengths).
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

RNG = np.random.default_rng(20260602)


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


def _boot_ci(diffs: np.ndarray, n: int = 10000) -> tuple[float, float]:
    if len(diffs) == 0:
        return float("nan"), float("nan")
    idx = RNG.integers(0, len(diffs), size=(n, len(diffs)))
    means = diffs[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _test(diffs: list[float]) -> dict[str, float]:
    d = np.array(diffs, dtype=float)
    nz = d[d != 0]
    out = {"n": len(d), "n_nonzero": len(nz), "mean": float(d.mean()) if len(d) else float("nan"),
           "wilcoxon_p": float("nan"), "sign_p": float("nan")}
    out["ci_lo"], out["ci_hi"] = _boot_ci(d)
    if len(nz) >= 1:
        pos = int((nz > 0).sum())
        out["pos"], out["neg"] = pos, len(nz) - pos
        out["sign_p"] = float(stats.binomtest(pos, len(nz), 0.5, alternative="two-sided").pvalue)
    if len(nz) >= 1:
        try:
            out["wilcoxon_p"] = float(stats.wilcoxon(d, alternative="two-sided", zero_method="wilcox").pvalue)
        except ValueError:
            out["wilcoxon_p"] = float("nan")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runner-rows", required=True)
    ap.add_argument("--gene-labels", required=True)
    ap.add_argument("--entity-labels", required=True)
    args = ap.parse_args()

    genes = _load(Path(args.gene_labels), "genes_covered")
    ents_p = _load(Path(args.entity_labels), "pathways_covered")
    ents_c = _load(Path(args.entity_labels), "celltypes_covered")
    rows = [json.loads(l) for l in Path(args.runner_rows).read_text().splitlines() if l.strip()]

    # cov[(set, metric, strength, arm)][case_id] = pct
    cov: dict[tuple, dict[str, float]] = defaultdict(dict)
    for row in rows:
        ws = row.get("trial_workspace")
        if not ws:
            continue
        ctx = json.loads((Path(ws) / "search_context.json").read_text()) if (Path(ws) / "search_context.json").exists() else {}
        ents = {
            "gene": ([g for g in (row.get("ligand"), row.get("receptor")) if g], genes),
            "path": (list(ctx.get("pathways") or row.get("pathways") or []), ents_p),
            "cell": (list(ctx.get("celltypes") or row.get("celltypes") or []), ents_c),
        }
        strength = row["model_strength"]
        arm = "ON" if row["skill_arm"] == "updated_skill" else "OFF"
        cid = row["case_id"]
        for setname, pf in (("raw", Path(ws) / "papers_raw.json"), ("filt", Path(ws) / "papers_filtered.json")):
            pmid_set = set(_pmids(pf))
            for metric, (case_ents, labelmap) in ents.items():
                if not case_ents:
                    continue
                union: set[str] = set()
                for pmid in pmid_set:
                    union.update(labelmap.get((cid, pmid), []))
                cov[(setname, metric, strength, arm)][cid] = 100 * len(union & set(case_ents)) / len(case_ents)

    def paired(setname: str, metric: str, strengths: list[str]) -> list[float]:
        diffs: list[float] = []
        for strength in strengths:
            on = cov[(setname, metric, strength, "ON")]
            off = cov[(setname, metric, strength, "OFF")]
            for cid in on.keys() & off.keys():
                diffs.append(on[cid] - off[cid])
        return diffs

    def star(p: float) -> str:
        if p != p:
            return ""
        return "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"

    for setname, label in (("raw", "ALL retrieved (raw)"), ("filt", "direct/context (filtered)")):
        print(f"\n================ paired stats — {label} ================")
        print(f"{'metric':10}{'strata':8}{'n':>4}{'meanΔ':>8}{'95% CI':>18}{'Wilcoxon':>11}{'sign':>9}")
        for metric, name in (("gene", "genes"), ("path", "pathways"), ("cell", "celltypes")):
            for strata, sl in (("strong", ["strong"]), ("weak", ["weak"]), ("pooled", ["strong", "weak"])):
                r = _test(paired(setname, metric, sl))
                ci = f"[{r['ci_lo']:+.1f},{r['ci_hi']:+.1f}]"
                wp = f"{r['wilcoxon_p']:.4f}{star(r['wilcoxon_p'])}"
                sp = f"{r['sign_p']:.3f}" if r["sign_p"] == r["sign_p"] else "—"
                print(f"{name:10}{strata:8}{r['n']:>4}{r['mean']:>+8.1f}{ci:>18}{wp:>11}{sp:>9}")


if __name__ == "__main__":
    main()

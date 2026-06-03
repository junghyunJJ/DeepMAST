#!/usr/bin/env python3
"""Aggregate graded per-paper LR-relevance labels into skill ON/OFF precision.

Joins (case_id, pmid) -> score labels back to every arm occurrence in the runner
rows, then reports per-paper mean relevance (precision) and the relevance-grade
distribution for skill ON vs OFF, split by model strength. Per-paper mean
relevance controls for the volume differences between arms.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load_labels(path: Path) -> dict[tuple[str, str], int]:
    labels: dict[tuple[str, str], int] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if obj.get("score") is None:
            continue
        labels[(str(obj["case_id"]), str(obj["pmid"]))] = int(obj["score"])
    return labels


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner-rows", required=True)
    parser.add_argument("--labels", required=True)
    args = parser.parse_args()

    labels = _load_labels(Path(args.labels))
    rows = [json.loads(line) for line in Path(args.runner_rows).read_text().splitlines() if line.strip()]

    # Per-arm occurrence scores (a paper counts once per arm it appears in).
    per_cond: dict[str, list[int]] = defaultdict(list)
    missing = 0
    for row in rows:
        ws = row.get("trial_workspace")
        if not ws:
            continue
        raw_path = Path(ws) / "papers_raw.json"
        if not raw_path.exists():
            continue
        papers = json.loads(raw_path.read_text()).get("papers", [])
        cond = row["condition"]
        for paper in papers:
            pmid = str(paper.get("pmid", "")).strip()
            if not pmid:
                continue
            key = (row["case_id"], pmid)
            if key not in labels:
                missing += 1
                continue
            per_cond[cond].append(labels[key])

    def stats(scores: list[int]) -> dict[str, Any]:
        n = len(scores)
        if not n:
            return {}
        dist = {g: scores.count(g) for g in (0, 1, 2, 3)}
        return {
            "n": n,
            "mean": st.mean(scores),
            "pct_relevant_ge2": 100 * sum(1 for s in scores if s >= 2) / n,
            "pct_direct_eq3": 100 * sum(1 for s in scores if s == 3) / n,
            "pct_offtopic_eq0": 100 * sum(1 for s in scores if s == 0) / n,
            "dist": dist,
        }

    print(f"missing labels (unscored papers): {missing}\n")
    header = f"{'arm':22}{'n':>6}{'mean':>7}{'%rel(>=2)':>11}{'%direct(3)':>12}{'%offtopic(0)':>14}"
    print(header)
    rollup: dict[str, list[int]] = defaultdict(list)
    for cond in ("strong_updated_skill", "strong_no_skill", "weak_updated_skill", "weak_no_skill"):
        s = stats(per_cond.get(cond, []))
        if not s:
            continue
        print(f"{cond:22}{s['n']:>6}{s['mean']:>7.2f}{s['pct_relevant_ge2']:>10.1f}%"
              f"{s['pct_direct_eq3']:>11.1f}%{s['pct_offtopic_eq0']:>13.1f}%")
        arm = "ON" if cond.endswith("updated_skill") else "OFF"
        rollup[arm].extend(per_cond.get(cond, []))

    print("\nON vs OFF per-paper mean relevance (precision):")
    for strength in ("strong", "weak"):
        on = stats(per_cond.get(f"{strength}_updated_skill", []))
        off = stats(per_cond.get(f"{strength}_no_skill", []))
        if on and off:
            print(f"  {strength:6}: ON mean={on['mean']:.2f} (rel%={on['pct_relevant_ge2']:.1f}) "
                  f"vs OFF mean={off['mean']:.2f} (rel%={off['pct_relevant_ge2']:.1f})  "
                  f"Δmean={on['mean']-off['mean']:+.2f}  Δrel%={on['pct_relevant_ge2']-off['pct_relevant_ge2']:+.1f}pp")
    on_all, off_all = stats(rollup["ON"]), stats(rollup["OFF"])
    if on_all and off_all:
        print(f"  pooled: ON mean={on_all['mean']:.2f} vs OFF mean={off_all['mean']:.2f}  "
              f"Δ={on_all['mean']-off_all['mean']:+.2f}")


if __name__ == "__main__":
    main()

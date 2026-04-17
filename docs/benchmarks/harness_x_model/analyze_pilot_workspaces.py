"""Post-hoc analyzer for harness_x_model pilot workspaces.

Goal: the gene_coverage_pct endpoint saturated at 100% across all 48 pilot
trials (Gate A FAIL), so the planned GLMM has no variance to model. This
script re-reads each trial's workspace ``papers.json`` and computes a
battery of alternate endpoints to find which metrics actually discriminate
between the four conditions.

Outputs (to ``docs/benchmarks/harness_x_model/results/pilot_posthoc/``):
    per_trial.csv      — one row per trial with all alt endpoints
    cross_arm.json     — per-case cross-condition deltas (Jaccard, novelty)
    summary.json       — aggregated per-condition statistics
    stdout             — human-readable variance ranking

Run:
    python docs/benchmarks/harness_x_model/analyze_pilot_workspaces.py
"""

from __future__ import annotations

import csv
import json
import re
import statistics
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from docs.benchmarks.harness_x_model.common import (
    load_cases,
    load_trial_rows,
    normalize_case,
)


WORKSPACES_ROOT = Path("docs/benchmarks/harness_x_model/workspaces/pilot")
RESULTS_ROOT = Path("docs/benchmarks/harness_x_model/results/pilot")
OUTPUT_ROOT = Path("docs/benchmarks/harness_x_model/results/pilot_posthoc")
CASES_PATH = Path("docs/benchmarks/cci_skill_ablation/cases/cci_full_cases.json")


@dataclass
class TrialMetrics:
    trial_index: int
    case_id: str
    condition: str
    model_strength: str
    skill_on: bool
    ligand: str
    receptor: str
    n_papers: int
    unique_pmids: int
    n_generated_queries: int
    n_unique_query_types: int
    iterations: int
    genes_coverage_pct: float
    celltypes_coverage_pct: float
    pathways_coverage_pct: float | None
    journal_quality_mean: float
    journal_quality_median: float
    lr_cooccurrence_count: int
    lr_title_cooccurrence_count: int
    ligand_only_count: int
    receptor_only_count: int
    mean_abstract_length: float
    latency_s: float
    biomcp_latency_ms: float
    # Reframe B' proxy: did the LLM activate enable_lr_pair_queries?
    n_deterministic_queries: int
    n_llm_queries: int
    used_lr_pair_queries: bool
    # Reframe C: L-R co-occurrence rate (count/total_papers)
    lr_cooccurrence_rate: float


def _word_boundary_pattern(term: str) -> re.Pattern[str] | None:
    term = term.strip()
    if not term:
        return None
    return re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)


def _mentions(pattern: re.Pattern[str] | None, text: str) -> bool:
    return bool(pattern and pattern.search(text))


def _compute_trial_metrics(
    trial_row: dict[str, Any],
    case: dict[str, Any],
    papers_json: dict[str, Any],
) -> TrialMetrics:
    normalized = normalize_case(case)
    ligand = str(case.get("input_bundle", {}).get("ligand", "")).strip()
    receptor = str(case.get("input_bundle", {}).get("receptor", "")).strip()

    papers = papers_json.get("papers") or []
    queries = papers_json.get("generated_queries") or []
    cov = papers_json.get("coverage") or {}

    pmids = {str(p.get("pmid")) for p in papers if p.get("pmid")}

    # journal quality (SJR proxy)
    jq_values = [float(p.get("journal_quality", 0.0) or 0.0) for p in papers]
    jq_mean = sum(jq_values) / len(jq_values) if jq_values else 0.0
    jq_median = statistics.median(jq_values) if jq_values else 0.0

    # L-R co-occurrence: requires BOTH ligand AND receptor mentioned in the
    # title or abstract (stricter than gene coverage, doesn't saturate).
    lig_pat = _word_boundary_pattern(ligand)
    rec_pat = _word_boundary_pattern(receptor)

    lr_cooccur = 0
    lr_title_cooccur = 0
    lig_only = 0
    rec_only = 0
    abstract_lens: list[int] = []

    for p in papers:
        title = str(p.get("title") or "")
        abstract = str(p.get("abstract") or "")
        combined = f"{title}\n{abstract}"
        abstract_lens.append(len(abstract))

        lig_in_combined = _mentions(lig_pat, combined)
        rec_in_combined = _mentions(rec_pat, combined)

        if lig_in_combined and rec_in_combined:
            lr_cooccur += 1
        elif lig_in_combined:
            lig_only += 1
        elif rec_in_combined:
            rec_only += 1

        lig_in_title = _mentions(lig_pat, title)
        rec_in_title = _mentions(rec_pat, title)
        if lig_in_title and rec_in_title:
            lr_title_cooccur += 1

    mean_abs_len = sum(abstract_lens) / len(abstract_lens) if abstract_lens else 0.0

    # Query diversity
    query_types = {q.get("query_type") for q in queries if isinstance(q, dict)}
    query_types.discard(None)

    iterations = int(papers_json.get("iterations") or 0)

    # Reframe B' proxy: count deterministic singleton gene queries.
    input_genes = {g.upper() for g in normalized["genes"]}
    n_deterministic = 0
    n_llm = 0
    for q in queries:
        if not isinstance(q, dict):
            continue
        q_genes = q.get("genes") or []
        q_keywords = q.get("keywords") or []
        if len(q_genes) == 1 and not q_keywords and str(q_genes[0]).upper() in input_genes:
            n_deterministic += 1
        else:
            n_llm += 1
    used_kwarg = (
        len(input_genes) > 0
        and n_deterministic >= len(input_genes)
        and n_llm >= 1
    )

    # Reframe C: L-R co-occurrence — reuse the first-loop count computed above
    # at line ~132 (title+abstract with mutual exclusion against lig_only/rec_only).
    # The prior second-loop variant (different text separator, no mutual-exclusion)
    # overwrote lr_cooccur with inconsistent semantics and produced a zero value
    # when lig_pat/rec_pat happened to be None even though the first loop had a
    # valid count — P0.2 fix.
    lr_cooccur_rate = round(lr_cooccur / len(papers), 4) if papers else 0.0

    return TrialMetrics(
        trial_index=int(trial_row["trial_index"]),
        case_id=str(trial_row["case_id"]),
        condition=str(trial_row["condition"]),
        model_strength=str(trial_row.get("model_strength", "")),
        skill_on=bool(trial_row["skill_on"]),
        ligand=ligand,
        receptor=receptor,
        n_papers=len(papers),
        unique_pmids=len(pmids),
        n_generated_queries=len(queries),
        n_unique_query_types=len(query_types),
        iterations=iterations,
        genes_coverage_pct=float(cov.get("genes_coverage_pct", 0.0) or 0.0),
        celltypes_coverage_pct=float(cov.get("celltypes_coverage_pct", 0.0) or 0.0),
        pathways_coverage_pct=(
            None
            if not normalized["pathways"]
            else float(cov.get("pathways_coverage_pct", 0.0) or 0.0)
        ),
        journal_quality_mean=round(jq_mean, 4),
        journal_quality_median=round(jq_median, 4),
        lr_cooccurrence_count=lr_cooccur,
        lr_title_cooccurrence_count=lr_title_cooccur,
        ligand_only_count=lig_only,
        receptor_only_count=rec_only,
        mean_abstract_length=round(mean_abs_len, 1),
        latency_s=float(trial_row.get("latency_s", 0.0) or 0.0),
        biomcp_latency_ms=float(trial_row.get("biomcp_latency_ms", 0.0) or 0.0),
        n_deterministic_queries=n_deterministic,
        n_llm_queries=n_llm,
        used_lr_pair_queries=used_kwarg,
        lr_cooccurrence_rate=lr_cooccur_rate,
    )


def _workspace_for_trial(trial_row: dict[str, Any]) -> Path:
    case_id = trial_row["case_id"]
    condition = trial_row["condition"]
    idx = int(trial_row["trial_index"])
    return WORKSPACES_ROOT / f"trial_{idx:04d}_{case_id}_{condition}" / "papers.json"


def _jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


@dataclass
class CrossArmDelta:
    case_id: str
    comparison: str
    n_a: int
    n_b: int
    jaccard: float
    intersection: int
    novelty_a_over_b: int
    novelty_b_over_a: int


def _compute_cross_arm(
    per_trial: list[tuple[TrialMetrics, set[str]]],
) -> list[CrossArmDelta]:
    by_case: dict[str, dict[str, tuple[TrialMetrics, set[str]]]] = {}
    for tm, pmids in per_trial:
        by_case.setdefault(tm.case_id, {})[tm.condition] = (tm, pmids)

    deltas: list[CrossArmDelta] = []
    pairs = [
        ("strong_on", "strong_off"),
        ("weak_on", "weak_off"),
        ("strong_on", "weak_on"),
        ("strong_off", "weak_off"),
    ]
    for case_id, conds in by_case.items():
        for a_name, b_name in pairs:
            a = conds.get(a_name)
            b = conds.get(b_name)
            if not a or not b:
                continue
            _, a_pmids = a
            _, b_pmids = b
            deltas.append(
                CrossArmDelta(
                    case_id=case_id,
                    comparison=f"{a_name}_vs_{b_name}",
                    n_a=len(a_pmids),
                    n_b=len(b_pmids),
                    jaccard=round(_jaccard(a_pmids, b_pmids), 4),
                    intersection=len(a_pmids & b_pmids),
                    novelty_a_over_b=len(a_pmids - b_pmids),
                    novelty_b_over_a=len(b_pmids - a_pmids),
                )
            )
    return deltas


def _summary_by_condition(
    trials: list[TrialMetrics],
) -> dict[str, dict[str, Any]]:
    by_cond: dict[str, list[TrialMetrics]] = {}
    for t in trials:
        by_cond.setdefault(t.condition, []).append(t)

    summary: dict[str, dict[str, Any]] = {}
    for cond, rows in by_cond.items():

        def _stat(attr: str) -> dict[str, float] | None:
            vals = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
            if not vals:
                return None
            return {
                "n": len(vals),
                "mean": round(sum(vals) / len(vals), 3),
                "median": round(statistics.median(vals), 3),
                "stdev": round(statistics.stdev(vals), 3) if len(vals) > 1 else 0.0,
                "min": round(min(vals), 3),
                "max": round(max(vals), 3),
            }

        summary[cond] = {
            "n_trials": len(rows),
            "genes_coverage_pct": _stat("genes_coverage_pct"),
            "celltypes_coverage_pct": _stat("celltypes_coverage_pct"),
            "lr_cooccurrence_count": _stat("lr_cooccurrence_count"),
            "lr_title_cooccurrence_count": _stat("lr_title_cooccurrence_count"),
            "ligand_only_count": _stat("ligand_only_count"),
            "receptor_only_count": _stat("receptor_only_count"),
            "unique_pmids": _stat("unique_pmids"),
            "n_generated_queries": _stat("n_generated_queries"),
            "n_unique_query_types": _stat("n_unique_query_types"),
            "iterations": _stat("iterations"),
            "journal_quality_mean": _stat("journal_quality_mean"),
            "mean_abstract_length": _stat("mean_abstract_length"),
            "latency_s": _stat("latency_s"),
            "n_deterministic_queries": _stat("n_deterministic_queries"),
            "n_llm_queries": _stat("n_llm_queries"),
            "lr_cooccurrence_rate": _stat("lr_cooccurrence_rate"),
        }
        # Reframe B' proxy rate: fraction of trials in this arm that activated
        # the advanced kwargs (used_lr_pair_queries == True).
        kwarg_activations = sum(1 for r in rows if r.used_lr_pair_queries)
        summary[cond]["used_lr_pair_queries_rate"] = round(
            kwarg_activations / len(rows), 4
        ) if rows else 0.0
        summary[cond]["used_lr_pair_queries_n"] = kwarg_activations
    return summary


def _variance_ranking(
    summary: dict[str, dict[str, Any]],
) -> list[tuple[str, float, float, float]]:
    """Return (metric_name, between_cond_range, mean_within_stdev, ratio)."""
    metrics = [
        "genes_coverage_pct",
        "celltypes_coverage_pct",
        "lr_cooccurrence_count",
        "lr_title_cooccurrence_count",
        "ligand_only_count",
        "receptor_only_count",
        "unique_pmids",
        "n_generated_queries",
        "n_unique_query_types",
        "n_deterministic_queries",
        "n_llm_queries",
        "lr_cooccurrence_rate",
        "iterations",
        "journal_quality_mean",
        "mean_abstract_length",
        "latency_s",
    ]
    ranking: list[tuple[str, float, float, float]] = []
    for m in metrics:
        means = [
            summary[c][m]["mean"]
            for c in summary
            if summary[c].get(m) is not None
        ]
        stds = [
            summary[c][m]["stdev"]
            for c in summary
            if summary[c].get(m) is not None
        ]
        if not means:
            continue
        between_range = max(means) - min(means)
        mean_within_stdev = sum(stds) / len(stds) if stds else 0.0
        ratio = between_range / mean_within_stdev if mean_within_stdev > 0 else float("inf") if between_range > 0 else 0.0
        ranking.append((m, round(between_range, 3), round(mean_within_stdev, 3), round(ratio, 3)))
    ranking.sort(key=lambda x: x[3], reverse=True)
    return ranking


def main() -> int:
    if not WORKSPACES_ROOT.exists():
        raise SystemExit(f"Workspaces dir not found: {WORKSPACES_ROOT}")
    if not RESULTS_ROOT.exists():
        raise SystemExit(f"Results dir not found: {RESULTS_ROOT}")

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    trial_rows = load_trial_rows(RESULTS_ROOT)
    cases_by_id = {c["case_id"]: c for c in load_cases(CASES_PATH)}

    per_trial: list[TrialMetrics] = []
    per_trial_with_pmids: list[tuple[TrialMetrics, set[str]]] = []
    missing: list[str] = []

    for row in trial_rows:
        if row.get("error"):
            continue
        papers_path = _workspace_for_trial(row)
        if not papers_path.exists():
            missing.append(str(papers_path))
            continue
        case = cases_by_id.get(row["case_id"])
        if case is None:
            missing.append(f"case {row['case_id']}")
            continue
        papers_json = json.loads(papers_path.read_text(encoding="utf-8"))
        tm = _compute_trial_metrics(row, case, papers_json)
        per_trial.append(tm)
        pmids = {
            str(p.get("pmid"))
            for p in (papers_json.get("papers") or [])
            if p.get("pmid")
        }
        per_trial_with_pmids.append((tm, pmids))

    if missing:
        print(f"[warn] {len(missing)} trials missing workspace/case — excluded", file=sys.stderr)
        for m in missing[:5]:
            print(f"   {m}", file=sys.stderr)

    # Write per_trial.csv
    csv_path = OUTPUT_ROOT / "per_trial.csv"
    if per_trial:
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(asdict(per_trial[0]).keys()))
            writer.writeheader()
            for tm in per_trial:
                writer.writerow(asdict(tm))

    # Compute cross-arm deltas
    deltas = _compute_cross_arm(per_trial_with_pmids)
    (OUTPUT_ROOT / "cross_arm.json").write_text(
        json.dumps([asdict(d) for d in deltas], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Summary by condition
    summary = _summary_by_condition(per_trial)
    (OUTPUT_ROOT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Variance ranking
    ranking = _variance_ranking(summary)

    # --- stdout human report ------------------------------------------------
    print(f"\n=== Pilot Post-Hoc Analysis ({len(per_trial)} trials) ===\n")
    print("Per-condition summary (mean ± std):")
    metric_cols = [
        "genes_coverage_pct",
        "celltypes_coverage_pct",
        "lr_cooccurrence_count",
        "lr_title_cooccurrence_count",
        "unique_pmids",
        "n_generated_queries",
        "n_unique_query_types",
        "n_deterministic_queries",
        "n_llm_queries",
        "lr_cooccurrence_rate",
        "iterations",
        "journal_quality_mean",
        "mean_abstract_length",
        "latency_s",
    ]
    hdr = f"{'metric':<28}" + "".join(f" {c:>18}" for c in sorted(summary))
    print(hdr)
    print("-" * len(hdr))
    for m in metric_cols:
        line = f"{m:<28}"
        for c in sorted(summary):
            stat = summary[c].get(m)
            if stat is None:
                cell = "nan"
            else:
                cell = f"{stat['mean']:.2f}±{stat['stdev']:.2f}"
            line += f" {cell:>18}"
        print(line)

    print("\n=== Variance ranking (between-cond range / within-cond stdev) ===")
    print(f"{'metric':<28} {'range':>10} {'mean_stdev':>12} {'ratio':>10}")
    print("-" * 64)
    for name, rng, std, ratio in ranking:
        marker = "  <<< strong signal" if ratio >= 1.0 else ""
        print(f"{name:<28} {rng:>10.3f} {std:>12.3f} {ratio:>10.3f}{marker}")

    print("\n=== Cross-arm (skill ON vs OFF) per model ===")
    print(f"{'comparison':<28} {'n_cases':>8} {'jaccard_mean':>14} {'novelty_a_mean':>16} {'novelty_b_mean':>16}")
    print("-" * 82)
    by_comp: dict[str, list[CrossArmDelta]] = {}
    for d in deltas:
        by_comp.setdefault(d.comparison, []).append(d)
    for comp in sorted(by_comp):
        ds = by_comp[comp]
        jm = sum(d.jaccard for d in ds) / len(ds)
        nam = sum(d.novelty_a_over_b for d in ds) / len(ds)
        nbm = sum(d.novelty_b_over_a for d in ds) / len(ds)
        print(f"{comp:<28} {len(ds):>8} {jm:>14.3f} {nam:>16.2f} {nbm:>16.2f}")

    print("\n=== Reframe B': skill-gated kwarg activation (used_lr_pair_queries) ===")
    print(f"{'condition':<16} {'n_trials':>10} {'n_activated':>12} {'rate':>8}")
    print("-" * 50)
    for cond in sorted(summary):
        n = summary[cond]["n_trials"]
        n_act = summary[cond].get("used_lr_pair_queries_n", 0)
        rate = summary[cond].get("used_lr_pair_queries_rate", 0.0)
        print(f"{cond:<16} {n:>10} {n_act:>12} {rate:>8.3f}")

    print(f"\nWrote:")
    print(f"  {csv_path}")
    print(f"  {OUTPUT_ROOT / 'cross_arm.json'}")
    print(f"  {OUTPUT_ROOT / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

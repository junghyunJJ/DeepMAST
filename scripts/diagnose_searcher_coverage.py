#!/usr/bin/env python
"""SEARCHER coverage diagnostic (Option D).

Empirically tests whether DeepMAST's SEARCHER 60% gene-coverage ceiling is a
biological limit (genes with no PubMed papers) or a code artifact (regex
mismatch, hub/novel conflation, max_results truncation, genes[:5] cap).

Runs four diagnostics on a completed SEARCHER run:

1. Per-gene PubMed singleton hit (achievable ceiling) — calls BioMCP
   article_searcher with each gene + disease, page_size=5. Establishes how
   many of the input genes actually have retrievable literature at all.

2. Alias-aware re-coverage — re-runs gene matching on the existing papers
   with BioMCP gene_getter aliases OR'd into the pattern set. Quantifies
   how much of the missing-gene set is recoverable purely by fixing the
   alias regex.

3. Coverage-history pattern analysis — reads the coverage_history field
   already saved in the papers JSON and classifies the iteration loop
   behaviour (slow convergence, early max_results break, LLM gap-fill miss).

4. Hub vs novel breakdown — splits missing genes into hub (top_search_genes)
   vs novel (lr_candidates) groups and compares miss rates.

Outputs:
    {data_dir}/diagnostic/per_gene_hit_count.json
    {data_dir}/diagnostic/alias_recoverage.json
    {data_dir}/diagnostic/coverage_diagnostic.md

Usage:
    python scripts/diagnose_searcher_coverage.py \\
        --data-dir res_bc_ollama \\
        --papers-file liana_papers.json \\
        --disease "breast cancer"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from src.agents.deep_interpreter.tools.literature import (  # noqa: E402
    _calculate_coverage,
    _generate_gene_patterns,
    _normalize_text_for_matching,
    _fetch_gene_aliases_from_biomcp,
    _search_with_biomcp,
)
from src.agents.deep_interpreter.tools.mcp_clients import DEFAULT_BIOMCP_URL  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("diagnose_searcher_coverage")
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Local utilities
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def _save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _classify_history_pattern(history: list[dict], iterations: int) -> str:
    """Classify the iteration loop behaviour from coverage_history."""
    if not history:
        return "no_history"
    if len(history) < 2:
        return "single_iteration"

    deltas = []
    paper_growth = []
    for prev, curr in zip(history, history[1:]):
        deltas.append(curr.get("gene_coverage", 0) - prev.get("gene_coverage", 0))
        paper_growth.append(curr.get("papers", 0) - prev.get("papers", 0))

    final_cov = history[-1].get("gene_coverage", 0)
    monotone = all(d >= 0 for d in deltas)
    stagnant_papers = all(g == 0 for g in paper_growth)
    plateau = all(abs(d) < 0.05 for d in deltas[-2:]) if len(deltas) >= 2 else False

    if stagnant_papers and final_cov < 0.5:
        return "B_max_papers_early_termination"
    if not monotone:
        return "C_llm_skipped_missing"
    if plateau and final_cov < 0.5:
        return "A_slow_convergence_iter_cap"
    if final_cov >= 0.6:
        return "converged_ok"
    return "A_slow_convergence_general"


# ---------------------------------------------------------------------------
# Diagnostic 4 — hub vs novel breakdown (local only)
# ---------------------------------------------------------------------------

def diagnostic_4_hub_vs_novel(
    hub_genes: list[str],
    lr_candidates: dict,
    missing_genes: list[str],
) -> dict:
    """Split missing genes into hub vs novel groups and compute miss rates."""
    hub_set = set(hub_genes)
    novel_set: set[str] = set()
    for pair in lr_candidates.get("pairs", []):
        for key in ("ligand", "receptor"):
            raw = pair.get(key, "")
            for token in raw.split("_"):
                token = token.strip()
                if token:
                    novel_set.add(token)
    novel_only = novel_set - hub_set

    hub_missing = [g for g in missing_genes if g in hub_set]
    novel_missing = [g for g in missing_genes if g in novel_only]
    other_missing = [g for g in missing_genes if g not in hub_set and g not in novel_only]

    return {
        "n_hub": len(hub_set),
        "n_novel_only": len(novel_only),
        "novel_only_set": sorted(novel_only),
        "hub_missing": hub_missing,
        "novel_missing": novel_missing,
        "other_missing": other_missing,
        "hub_miss_rate": len(hub_missing) / len(hub_set) if hub_set else 0.0,
        "novel_miss_rate": len(novel_missing) / len(novel_only) if novel_only else 0.0,
    }


# ---------------------------------------------------------------------------
# Diagnostic 3 — coverage history (local only)
# ---------------------------------------------------------------------------

def diagnostic_3_history(papers_data: dict) -> dict:
    """Read and classify the coverage_history field."""
    history = papers_data.get("coverage_history", [])
    iterations = papers_data.get("iterations", len(history))
    pattern = _classify_history_pattern(history, iterations)

    iter_to_iter = []
    for i, entry in enumerate(history):
        iter_to_iter.append({
            "iter": entry.get("iteration", i),
            "papers": entry.get("papers", 0),
            "gene_cov_pct": round(entry.get("gene_coverage", 0) * 100, 2),
            "pathway_cov_pct": round(entry.get("pathway_coverage", 0) * 100, 2),
        })

    return {
        "iterations_recorded": iterations,
        "history": iter_to_iter,
        "pattern_classification": pattern,
        "coverage_sufficient": papers_data.get("coverage_sufficient"),
        "filter_stage": papers_data.get("filter_stage"),
    }


# ---------------------------------------------------------------------------
# Diagnostic 2 — alias-aware re-coverage
# ---------------------------------------------------------------------------

async def _fetch_aliases_for_genes(genes: list[str], biomcp_url: str) -> dict[str, list[str]]:
    """Fetch BioMCP aliases for a gene list (parallel)."""
    tasks = [_fetch_gene_aliases_from_biomcp(g, biomcp_url) for g in genes]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: dict[str, list[str]] = {}
    for gene, result in zip(genes, results):
        if isinstance(result, Exception):
            logger.warning("alias fetch failed for %s: %s", gene, result)
            out[gene] = []
        else:
            out[gene] = list(result) if result else []
    return out


def _match_papers_with_patterns(
    papers: list[dict],
    gene_patterns: dict[str, list[str]],
) -> tuple[list[str], dict[str, str]]:
    """Re-implementation of _calculate_coverage gene matching with custom patterns.

    Mirrors the logic at literature.py:1609-1626 exactly, but uses the
    caller-supplied per-gene pattern list (which can include BioMCP aliases).
    """
    import re as _re

    covered: list[str] = []
    matched_by: dict[str, str] = {}
    genes = list(gene_patterns.keys())

    for paper in papers:
        text = _normalize_text_for_matching(
            paper.get("abstract", "") + " " + paper.get("title", "")
        )
        for gene in genes:
            if gene in covered:
                continue
            for pattern in gene_patterns[gene]:
                if not pattern:
                    continue
                if len(pattern) <= 3:
                    if _re.search(rf"\b{_re.escape(pattern)}\b", text):
                        covered.append(gene)
                        matched_by[gene] = pattern
                        break
                else:
                    if pattern in text:
                        covered.append(gene)
                        matched_by[gene] = pattern
                        break
    return covered, matched_by


def diagnostic_2_alias_recoverage(
    papers: list[dict],
    hub_genes: list[str],
    alias_map: dict[str, list[str]],
) -> dict:
    """Re-compute gene coverage with BioMCP aliases OR'd into the pattern set."""
    base_patterns = {g: list(_generate_gene_patterns(g)) for g in hub_genes}

    aug_patterns: dict[str, list[str]] = {}
    for g in hub_genes:
        merged = set(base_patterns[g])
        for alias in alias_map.get(g, []):
            for p in _generate_gene_patterns(alias, include_biomcp_aliases=False):
                merged.add(p)
        aug_patterns[g] = list(merged)

    base_covered, base_matched = _match_papers_with_patterns(papers, base_patterns)
    aug_covered, aug_matched = _match_papers_with_patterns(papers, aug_patterns)

    base_set = set(base_covered)
    aug_set = set(aug_covered)
    recovered = sorted(aug_set - base_set)
    still_missing = sorted(set(hub_genes) - aug_set)

    return {
        "base_covered": sorted(base_set),
        "base_n": len(base_set),
        "base_pct": round(len(base_set) / len(hub_genes) * 100, 2),
        "aug_covered": sorted(aug_set),
        "aug_n": len(aug_set),
        "aug_pct": round(len(aug_set) / len(hub_genes) * 100, 2),
        "recovered_by_alias": recovered,
        "delta": len(recovered),
        "still_missing_after_alias": still_missing,
        "matched_pattern_examples": {g: aug_matched[g] for g in list(aug_set)[:10]},
    }


# ---------------------------------------------------------------------------
# Diagnostic 1 — per-gene PubMed singleton hit count
# ---------------------------------------------------------------------------

async def diagnostic_1_per_gene_hits(
    genes: list[str],
    disease: str,
    biomcp_url: str,
    page_size: int = 5,
    sleep_s: float = 0.3,
    enforce_disease_match: bool = False,
) -> dict[str, int]:
    """Run a single-gene PubMed search per gene, return article count (capped).

    When enforce_disease_match=True, mirrors production SEARCHER's strict
    post-filter (organ-cancer mismatch rejection) for parity measurement.
    """
    counts: dict[str, int] = {}
    for i, gene in enumerate(genes, 1):
        try:
            articles = await _search_with_biomcp(
                genes=[gene],
                diseases=[disease] if disease else None,
                page_size=page_size,
                biomcp_url=biomcp_url,
                enforce_disease_match=enforce_disease_match,
            )
            counts[gene] = len(articles)
            logger.info("[%d/%d] %s -> %d papers", i, len(genes), gene, counts[gene])
        except Exception as e:
            logger.warning("singleton search failed for %s: %s", gene, e)
            counts[gene] = -1
        await asyncio.sleep(sleep_s)
    return counts


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------

def _format_md_table(rows: list[dict], headers: list[str]) -> str:
    out = ["| " + " | ".join(headers) + " |"]
    out.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        out.append("| " + " | ".join(str(row.get(h, "")) for h in headers) + " |")
    return "\n".join(out)


def write_report(
    output_path: Path,
    config: dict,
    diag1: dict,
    diag2: dict,
    diag3: dict,
    diag4: dict,
) -> None:
    lines: list[str] = []
    lines.append("# SEARCHER Coverage Diagnostic Report")
    lines.append("")
    lines.append(f"- Data dir: `{config['data_dir']}`")
    lines.append(f"- Papers file: `{config['papers_file']}`")
    lines.append(f"- Disease: `{config['disease']}`")
    lines.append(f"- Hub genes (n={len(config['hub_genes'])}): {', '.join(config['hub_genes'])}")
    lines.append(f"- Novel-only genes (n={diag4['n_novel_only']}): {', '.join(diag4['novel_only_set'])}")
    lines.append("")

    # ---- TL;DR ----
    lines.append("## TL;DR")
    lines.append("")
    achievable = diag1["achievable_pct"]
    delta = diag2["delta"]
    pattern = diag3["pattern_classification"]
    hub_miss = diag4["hub_miss_rate"] * 100
    novel_miss = diag4["novel_miss_rate"] * 100
    strict_mode = diag1.get("enforce_disease_match", False)
    n_errored = diag1.get("n_errored", 0)
    n_valid = diag1.get("n_valid", len(diag1["per_gene_counts"]))
    mode_label = "STRICT (enforce_disease_match=True, production-equivalent)" if strict_mode else "LOOSE (enforce_disease_match=False)"
    lines.append(f"- **Disease filter mode**: {mode_label}")
    lines.append(
        f"- **Achievable ceiling (PubMed singleton hits)**: {achievable:.1f}% of input genes "
        f"have ≥1 retrievable paper for {config['disease']!r} (n_valid={n_valid}/{len(diag1['per_gene_counts'])})."
    )
    if n_errored > 0:
        lines.append(
            f"- **WARNING — Probe errors**: {n_errored} gene(s) failed BioMCP probe (recorded as -1, excluded from bucket math). "
            f"Bucket statistics may be incomplete; investigate before relying on this report."
        )
    lines.append(
        f"- **Alias-only fix recovers**: {delta} of the missing genes (base "
        f"{diag2['base_pct']}% → alias-augmented {diag2['aug_pct']}%)."
    )
    lines.append(f"- **Coverage history pattern**: `{pattern}`")
    lines.append(
        f"- **Hub miss rate**: {hub_miss:.1f}% — **Novel miss rate**: {novel_miss:.1f}%"
    )
    lines.append("")
    lines.append(_render_recommendation(diag1, diag2, diag3, diag4))
    lines.append("")

    # ---- Diagnostic 1 ----
    lines.append("## Diagnostic 1 — Achievable ceiling (per-gene PubMed singleton)")
    lines.append("")
    lines.append(
        f"For each of the {len(diag1['per_gene_counts'])} genes, called BioMCP "
        f"`article_searcher(genes=[gene], diseases=[{config['disease']!r}], "
        f"page_size={diag1['page_size']})`. The returned count is capped at "
        f"`page_size`, so values of 5 mean ≥5 (likely many more)."
    )
    lines.append("")
    lines.append(f"- **Genes with 0 papers** (true biological limit): {diag1['n_zero']}")
    lines.append(f"- **Genes with 1-4 papers** (rare): {diag1['n_rare']}")
    lines.append(f"- **Genes with ≥5 papers** (well-studied): {diag1['n_well_studied']}")
    lines.append(
        f"- **Achievable ceiling**: {diag1['achievable_pct']:.1f}% "
        f"({diag1['n_with_any']}/{len(diag1['per_gene_counts'])})"
    )
    lines.append("")
    rows = []
    for gene, cnt in sorted(diag1["per_gene_counts"].items(), key=lambda x: (-x[1], x[0])):
        bucket = "0" if cnt == 0 else ("rare" if cnt < 5 else "≥5")
        was_missing = "yes" if gene in diag1["missing_genes_set"] else "no"
        rows.append({"gene": gene, "PubMed hit (capped)": cnt, "bucket": bucket, "was_missing": was_missing})
    lines.append(_format_md_table(rows, ["gene", "PubMed hit (capped)", "bucket", "was_missing"]))
    lines.append("")
    lines.append("**Interpretation**:")
    if diag1["n_zero"] == 0:
        lines.append(
            "- All input genes have at least one retrievable paper. The achievable "
            "ceiling is **100%**. Any miss in the actual SEARCHER run is therefore "
            "a **code artifact**, not a biological limit."
        )
    else:
        lines.append(
            f"- {diag1['n_zero']} genes have zero papers and define a true biological floor. "
            f"The achievable ceiling is {diag1['achievable_pct']:.1f}%."
        )
    lines.append("")

    # ---- Diagnostic 2 ----
    lines.append("## Diagnostic 2 — Alias-aware re-coverage")
    lines.append("")
    lines.append(
        f"Re-ran the gene-matching regex on the same {config['n_papers']} papers "
        f"in `{config['papers_file']}`, but with BioMCP `gene_getter` aliases "
        f"merged into each gene's pattern set."
    )
    lines.append("")
    lines.append(f"- Base coverage (current implementation): **{diag2['base_n']}/{len(config['hub_genes'])} = {diag2['base_pct']}%**")
    lines.append(f"- Alias-augmented coverage: **{diag2['aug_n']}/{len(config['hub_genes'])} = {diag2['aug_pct']}%**")
    lines.append(f"- **Genes recovered by alias fix only**: {diag2['delta']}")
    if diag2["recovered_by_alias"]:
        lines.append(f"  - Recovered: {', '.join(diag2['recovered_by_alias'])}")
    if diag2["still_missing_after_alias"]:
        lines.append(
            f"- Still missing after alias fix (true SEARCHER misses, not regex misses): "
            f"{', '.join(diag2['still_missing_after_alias'])}"
        )
    lines.append("")
    lines.append("**Interpretation**:")
    if diag2["delta"] >= 5:
        lines.append(
            f"- Alias-only fix is a **major** lever: recovers {diag2['delta']} genes from "
            f"the same paper set. The current `_generate_gene_patterns` does not consult "
            f"BioMCP `gene_getter` at runtime (the `include_biomcp_aliases` flag at "
            f"`literature.py:1429` is vestigial)."
        )
    elif diag2["delta"] >= 1:
        lines.append(
            f"- Alias-only fix is a **minor** lever: recovers {diag2['delta']} gene(s). "
            f"Most missing genes are missing because the underlying papers don't mention "
            f"them at all, not because of alias regex misses."
        )
    else:
        lines.append(
            "- Alias-only fix recovers **0** genes. The regex matching is not the "
            "bottleneck — the missing genes really aren't in the retrieved paper set."
        )
    lines.append("")

    # ---- Diagnostic 3 ----
    lines.append("## Diagnostic 3 — Coverage history pattern")
    lines.append("")
    lines.append(f"- Iterations recorded: {diag3['iterations_recorded']}")
    lines.append(f"- Pattern: **{diag3['pattern_classification']}**")
    lines.append(f"- Coverage sufficient: {diag3['coverage_sufficient']}")
    lines.append(f"- Filter stage: {diag3['filter_stage']}")
    lines.append("")
    if diag3["history"]:
        lines.append(_format_md_table(
            diag3["history"],
            ["iter", "papers", "gene_cov_pct", "pathway_cov_pct"],
        ))
    lines.append("")
    lines.append("**Interpretation**:")
    pat = diag3["pattern_classification"]
    if pat == "B_max_papers_early_termination":
        lines.append(
            "- The paper count stops growing across iterations even though gene "
            "coverage is below 50%. This is the `len(all_papers) >= max_results` "
            "early break at `literature.py:2315`. Gap-filling never gets to run "
            "because the paper budget is already full."
        )
    elif pat.startswith("A_"):
        lines.append(
            "- Coverage improves slowly across iterations and never converges to 60% "
            "before max_iterations. This is gap-fill loop fatigue: each iteration adds "
            "only a few new gene mentions because of the genes[:5] cap and the "
            "60/40 gene/pathway slot allocation."
        )
    elif pat == "C_llm_skipped_missing":
        lines.append(
            "- Coverage went *backwards* between iterations. The LLM is dropping "
            "previously-covered genes when generating gap-fill queries, or the "
            "post-iteration SJR truncation is removing rare-gene papers."
        )
    else:
        lines.append(f"- Pattern `{pat}` — see history table above for raw numbers.")
    lines.append("")

    # ---- Diagnostic 4 ----
    lines.append("## Diagnostic 4 — Hub vs novel breakdown")
    lines.append("")
    lines.append(f"- Hub genes (top_search_genes.json): n={diag4['n_hub']}")
    lines.append(f"- Novel-only genes (lr_candidates, excluding hub overlap): n={diag4['n_novel_only']}")
    lines.append("")
    lines.append(f"- **Hub miss rate**: {diag4['hub_miss_rate']*100:.1f}% ({len(diag4['hub_missing'])}/{diag4['n_hub']})")
    if diag4["hub_missing"]:
        lines.append(f"  - Missing hubs: {', '.join(diag4['hub_missing'])}")
    lines.append(f"- **Novel miss rate**: {diag4['novel_miss_rate']*100:.1f}% ({len(diag4['novel_missing'])}/{max(diag4['n_novel_only'],1)})")
    if diag4["novel_missing"]:
        lines.append(f"  - Missing novels: {', '.join(diag4['novel_missing'])}")
    if diag4["other_missing"]:
        lines.append(f"- Other missing (not in hub or novel sets): {', '.join(diag4['other_missing'])}")
    lines.append("")
    lines.append("**Interpretation**:")
    if diag4["hub_miss_rate"] > 0.3:
        lines.append(
            f"- Hub miss rate is {diag4['hub_miss_rate']*100:.1f}% — well-studied hub "
            "genes are being dropped despite having ample literature. This points "
            "directly at the genes[:5] cap, the SJR truncation, or both."
        )
    if diag4["novel_miss_rate"] > diag4["hub_miss_rate"] + 0.1:
        lines.append(
            f"- Novel miss rate ({diag4['novel_miss_rate']*100:.1f}%) is materially higher "
            "than hub miss rate. The hub/novel input split (architect's recommended "
            "fix) is likely to help."
        )
    elif diag4["novel_miss_rate"] < diag4["hub_miss_rate"] + 0.05:
        lines.append(
            "- Novel and hub miss rates are similar. The hub/novel input split "
            "would not help much; the bottleneck is upstream of input shape."
        )
    lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines))
    logger.info("Wrote report: %s", output_path)


def _render_recommendation(diag1: dict, diag2: dict, diag3: dict, diag4: dict) -> str:
    """Map diagnostic results to fix scope (A/B/C)."""
    achievable_high = diag1["achievable_pct"] >= 90
    alias_helps = diag2["delta"] >= 5
    hub_biased = diag4["hub_miss_rate"] >= 0.3
    novel_biased = diag4["novel_miss_rate"] - diag4["hub_miss_rate"] >= 0.1
    pattern = diag3["pattern_classification"]
    early_term = pattern == "B_max_papers_early_termination"

    notes = []
    if achievable_high and alias_helps and hub_biased:
        scope = "Fix A (cheap tactical) — high confidence"
        notes.append(
            "Achievable ceiling is high, hub miss rate is significant, alias fix "
            "alone recovers a chunk. Cheap fix is sufficient: enable "
            "`coverage_weighted_sort=True`, add per-gene minimum retrieval, wire "
            "BioMCP gene_getter into `_generate_gene_patterns`."
        )
    elif novel_biased or not alias_helps:
        scope = "Fix B/C (structural refactor)"
        notes.append(
            "Novel genes are systematically under-retrieved (or alias fix doesn't help) — "
            "the hub/novel input shape needs to be split, and the coverage metric "
            "should be replaced with an evidence manifest."
        )
    elif early_term:
        scope = "Fix A+ (cheap tactical, plus loop fix)"
        notes.append(
            "Coverage history shows max_results early termination. Beyond Fix A, "
            "run the gap-filling iterations BEFORE the SJR truncation, or raise "
            "max_results internally and only truncate at the very end."
        )
    else:
        scope = "Inconclusive — needs an additional probe"
        notes.append(
            "The diagnostics don't clearly map to A/B/C. Recommend a follow-up: "
            "re-run search_literature_dynamic with coverage_weighted_sort=True on "
            "the same input and compare coverage delta directly."
        )

    body = ["**Recommendation**: " + scope, ""]
    body.extend("- " + n for n in notes)
    return "\n".join(body)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main_async(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir).resolve()
    diagnostic_dir = data_dir / "diagnostic"
    diagnostic_dir.mkdir(parents=True, exist_ok=True)

    papers_path = data_dir / args.papers_file
    top_genes_path = data_dir / "top_search_genes.json"
    lr_candidates_path = data_dir / "lr_candidates.json"

    for p in (papers_path, top_genes_path, lr_candidates_path):
        if not p.exists():
            print(f"[ERROR] missing required file: {p}", file=sys.stderr)
            return 2

    papers_data = _load_json(papers_path)
    papers = papers_data.get("papers", [])
    top_genes_doc = _load_json(top_genes_path)
    hub_genes: list[str] = list(top_genes_doc.get("genes", []))
    lr_candidates = _load_json(lr_candidates_path)

    if not papers:
        print("[ERROR] no papers found in", papers_path, file=sys.stderr)
        return 2
    if not hub_genes:
        print("[ERROR] no hub genes in", top_genes_path, file=sys.stderr)
        return 2

    saved_coverage = papers_data.get("coverage", {})
    missing_genes = saved_coverage.get("genes_missing", [])
    logger.info("Loaded %d papers, %d hub genes, %d missing genes (per saved coverage)",
                len(papers), len(hub_genes), len(missing_genes))

    # Build the union of hub + novel genes for Diagnostic 1
    novel_set: set[str] = set()
    for pair in lr_candidates.get("pairs", []):
        for key in ("ligand", "receptor"):
            for token in pair.get(key, "").split("_"):
                token = token.strip()
                if token:
                    novel_set.add(token)
    novel_only = sorted(novel_set - set(hub_genes))
    all_test_genes = list(hub_genes) + novel_only
    logger.info("Diagnostic 1 will probe %d genes (%d hub + %d novel-only)",
                len(all_test_genes), len(hub_genes), len(novel_only))

    biomcp_url = args.biomcp_url or DEFAULT_BIOMCP_URL

    # Diagnostic 4 — local only
    diag4 = diagnostic_4_hub_vs_novel(hub_genes, lr_candidates, missing_genes)

    # Diagnostic 3 — local only
    diag3 = diagnostic_3_history(papers_data)

    # Sanity check vs saved coverage (re-run _calculate_coverage on same papers).
    # F2: pass use_retrieval_tags=True so the sanity coverage reflects the
    # SEARCHER-mode two-tier provenance from the saved papers.json.
    sanity = _calculate_coverage(
        papers, hub_genes, [], [], use_retrieval_tags=True,
    )
    logger.info("Sanity check: re-computed gene coverage = %d/%d (saved=%d)",
                len(sanity["genes_covered"]), len(hub_genes), len(missing_genes) and (len(hub_genes) - len(missing_genes)))

    # F2 step 8 — Three-tier provenance TL;DR from genes_matched_by.
    # Classifier: "biomcp_tag+text_confirmed" → N (auditable citations),
    #             "biomcp_tag_only"           → M (alias-only — review carefully),
    #             anything else               → K (regex_only legacy path).
    matched_by = sanity.get("genes_matched_by", {}) or {}
    tier_n = sum(1 for v in matched_by.values() if v == "biomcp_tag+text_confirmed")
    tier_m = sum(1 for v in matched_by.values() if v == "biomcp_tag_only")
    tier_k = sum(
        1 for v in matched_by.values()
        if v not in ("biomcp_tag+text_confirmed", "biomcp_tag_only")
    )
    logger.info(
        "F2 provenance breakdown: biomcp_tag+text_confirmed=%d  biomcp_tag_only=%d  regex_only=%d",
        tier_n, tier_m, tier_k,
    )
    print(
        "\n=== F2 Evidence Manifest — Provenance Tiers ===\n"
        f"  biomcp_tag+text_confirmed: {tier_n} (auditable citations)\n"
        f"  biomcp_tag_only:           {tier_m} (alias-only retrieval — review carefully)\n"
        f"  regex_only:                {tier_k} (legacy backward-compat path)\n"
    )

    # Diagnostic 1 — per-gene singleton search (API)
    print("\n[1/2] Running per-gene PubMed singleton search...")
    t0 = time.time()
    per_gene_counts = await diagnostic_1_per_gene_hits(
        all_test_genes,
        disease=args.disease,
        biomcp_url=biomcp_url,
        page_size=args.page_size,
        sleep_s=args.sleep,
        enforce_disease_match=args.strict_disease_filter,
    )
    print(f"    done in {time.time()-t0:.1f}s")

    # Exclude error sentinel (-1) from bucket math (Step 0a, Codex Finding 2 patch).
    valid = {g: c for g, c in per_gene_counts.items() if c >= 0}
    n_errored = len(per_gene_counts) - len(valid)
    n_zero = sum(1 for c in valid.values() if c == 0)
    n_rare = sum(1 for c in valid.values() if 0 < c < 5)
    n_well = sum(1 for c in valid.values() if c >= 5)
    n_with_any = sum(1 for c in valid.values() if c >= 1)
    achievable_pct = 100.0 * n_with_any / len(valid) if valid else 0.0
    diag1 = {
        "per_gene_counts": per_gene_counts,
        "page_size": args.page_size,
        "enforce_disease_match": args.strict_disease_filter,
        "n_zero": n_zero,
        "n_rare": n_rare,
        "n_well_studied": n_well,
        "n_with_any": n_with_any,
        "n_errored": n_errored,
        "n_valid": len(valid),
        "achievable_pct": achievable_pct,
        "missing_genes_set": list(missing_genes),
    }
    suffix = "_strict" if args.strict_disease_filter else "_loose"
    _save_json(diagnostic_dir / f"per_gene_hit_count{suffix}.json", diag1)
    # Also write the canonical filename for the active run (latest wins).
    _save_json(diagnostic_dir / "per_gene_hit_count.json", diag1)

    # Diagnostic 2 — alias re-coverage (API)
    print("\n[2/2] Fetching BioMCP aliases for hub genes...")
    t0 = time.time()
    alias_map = await _fetch_aliases_for_genes(hub_genes, biomcp_url)
    print(f"    aliases fetched in {time.time()-t0:.1f}s "
          f"({sum(1 for v in alias_map.values() if v)} of {len(alias_map)} genes have aliases)")
    diag2 = diagnostic_2_alias_recoverage(papers, hub_genes, alias_map)
    diag2["alias_map"] = alias_map
    _save_json(diagnostic_dir / "alias_recoverage.json", diag2)

    # Report — write both a mode-suffixed file (loose vs strict comparison)
    # and the canonical name (latest wins, used by Step 0b cross-check).
    output_path = diagnostic_dir / f"coverage_diagnostic{suffix}.md"
    write_report(
        output_path,
        config={
            "data_dir": str(data_dir),
            "papers_file": args.papers_file,
            "disease": args.disease,
            "hub_genes": hub_genes,
            "n_papers": len(papers),
        },
        diag1=diag1,
        diag2=diag2,
        diag3=diag3,
        diag4=diag4,
    )
    print(f"\nReport written: {output_path}")
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SEARCHER coverage diagnostic")
    p.add_argument("--data-dir", required=True)
    p.add_argument("--papers-file", default="liana_papers.json")
    p.add_argument("--disease", default="breast cancer")
    p.add_argument("--biomcp-url", default="")
    p.add_argument("--page-size", type=int, default=5)
    p.add_argument("--sleep", type=float, default=0.3)
    p.add_argument(
        "--strict-disease-filter",
        action="store_true",
        help="Pass enforce_disease_match=True to Diagnostic 1 (production-equivalent). "
             "Default False = loose ceiling for raw retrievability.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())

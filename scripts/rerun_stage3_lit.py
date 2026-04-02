#!/usr/bin/env python3
"""Re-run stage3 literature search for 7 IPF FEATURED genes.

Uses the exact same parameters as the original drug_target pipeline
(see src/agents/drug_target/subagents/prompts.py:232-241).

Usage:
    python scripts/rerun_stage3_lit.py
"""
from __future__ import annotations

import json
import sys
import time

from src.agents.deep_interpreter.tools.literature import search_literature_dynamic

GENES = ["CD74", "CXCR4", "GPC3", "ICAM1", "MUC1", "SFTPD", "TGFB1"]
DISEASE = "idiopathic pulmonary fibrosis"
DATA_DIR = "res_ipf_qwen"


def main() -> None:
    results = {}
    for gene in GENES:
        print(f"\n{'='*60}")
        print(f"  Searching literature for {gene} + {DISEASE}")
        print(f"{'='*60}")
        t0 = time.time()

        result = search_literature_dynamic.invoke({
            "genes": [gene],
            "pathways": [],
            "celltypes": [],
            "disease": DISEASE,
            "max_results": 10,
            "max_iterations": 2,
            "output_path": f"evidence/stage3_lit_{gene}.json",
            "data_dir": DATA_DIR,
        })

        elapsed = time.time() - t0
        total = result.get("total_papers", len(result.get("papers", [])))
        gene_cov = result.get("coverage", {}).get("genes_coverage_pct", 0)
        sufficient = result.get("coverage_sufficient", False)

        results[gene] = {
            "papers": total,
            "gene_coverage_pct": gene_cov,
            "coverage_sufficient": sufficient,
            "elapsed_sec": round(elapsed, 1),
        }
        print(f"  -> {gene}: {total} papers, gene_cov={gene_cov}%, sufficient={sufficient} ({elapsed:.1f}s)")

    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    for gene, info in results.items():
        status = "OK" if info["papers"] > 0 else "FAIL"
        print(f"  [{status}] {gene}: {info['papers']} papers, {info['gene_coverage_pct']}% gene coverage ({info['elapsed_sec']}s)")

    failed = [g for g, i in results.items() if i["papers"] == 0]
    if failed:
        print(f"\n  WARNING: {len(failed)} genes still have 0 papers: {failed}")
        sys.exit(1)
    else:
        print(f"\n  All {len(GENES)} genes have literature results.")


if __name__ == "__main__":
    main()

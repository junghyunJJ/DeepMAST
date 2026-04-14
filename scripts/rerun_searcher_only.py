#!/usr/bin/env python
"""Re-run only SEARCHER on res_bc_ollama to produce a fresh liana_papers.json.

Used for Fix A* coverage verification — bypasses PLANNER/INTERPRETER/REPORTER
and exercises only `search_literature_dynamic` with SEARCHER's exact arguments
on the existing `res_bc_ollama/` fixtures (top_search_genes.json + the original
pathways/celltypes captured from the previous SEARCHER run).

Acceptance gate context: the diagnostic at `scripts/diagnose_searcher_coverage.py`
should report hub gene coverage >= 80% on the new liana_papers.json after Fix A*.

Usage:
    python scripts/rerun_searcher_only.py
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Project bootstrap (canonical pattern from scripts/run_drug_target_e2e.py:32-38)
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

# Imports must come AFTER sys.path manipulation
from src.agents.deep_interpreter.tools.literature import search_literature_dynamic  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATA_DIR = (PROJECT_ROOT / "res_bc_ollama").resolve()
DISEASE = "breast cancer"
OUTPUT_FILE = "liana_papers.json"

# Pathways and celltypes captured from the existing res_bc_ollama/liana_papers.json
# `coverage` block (covered + missing — what SEARCHER originally received).
PATHWAYS = [
    "Estrogen", "TGFb", "MAPK", "PI3K", "JAK-STAT", "EGFR", "NFkB",
    "Androgen", "p53", "Hypoxia", "VEGF", "TNFa", "Trail",
]
CELLTYPES = [
    "Fibroblast", "Tumor", "T Cells", "Macrophages", "Endothelial",
    "B Cells", "Dendritic Cells", "DCIS", "Myoepithelial",
]


def main() -> int:
    top_genes_path = DATA_DIR / "top_search_genes.json"
    if not top_genes_path.exists():
        print(f"[ERROR] missing {top_genes_path}", file=sys.stderr)
        return 2

    with open(top_genes_path) as f:
        hub_doc = json.load(f)
    hub_genes = list(hub_doc.get("genes", []))
    if not hub_genes:
        print(f"[ERROR] no hub genes in {top_genes_path}", file=sys.stderr)
        return 2

    print(f"Running SEARCHER on {DATA_DIR}")
    print(f"  hub genes: {len(hub_genes)} ({', '.join(hub_genes[:5])}, ...)")
    print(f"  pathways:  {len(PATHWAYS)}")
    print(f"  celltypes: {len(CELLTYPES)}")
    print(f"  disease:   {DISEASE}")
    print(f"  output:    {DATA_DIR}/{OUTPUT_FILE}")
    print()

    # NOTE: `search_literature_dynamic` is a LangChain @tool. Outside the agent
    # runtime, call it via `.invoke({...})` with the full kwargs dict.
    # `enable_lr_pair_queries=True` triggers the SEARCHER-mode sentinel that
    # auto-enables `coverage_weighted_sort` and the L-R pair query injection.
    # We also pass `coverage_weighted_sort=True` explicitly as belt-and-suspenders.
    result = search_literature_dynamic.invoke({
        "genes": hub_genes,
        "pathways": PATHWAYS,
        "celltypes": CELLTYPES,
        "disease": DISEASE,
        "output_path": OUTPUT_FILE,
        "data_dir": str(DATA_DIR),
        "enable_lr_pair_queries": True,
        "coverage_weighted_sort": True,
    })

    print("\n=== SEARCHER result (compact summary) ===")
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

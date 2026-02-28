#!/usr/bin/env python3
"""CLI wrapper for Deep Interpreter's search_literature_dynamic tool.

Run from the skill directory:
    python scripts/search_literature_dynamic.py --help
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _parse_csv_list(raw: str) -> list[str]:
    """Parse comma-separated CLI input into a clean string list."""
    if not raw.strip():
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _find_repo_root() -> Path:
    """Find repository root containing src/agents/deep_interpreter/tools/literature.py."""
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        tool_file = candidate / "src/agents/deep_interpreter/tools/literature.py"
        if tool_file.exists():
            return candidate
    raise RuntimeError(
        "Could not locate repository root. Run from inside DeepMAST or set PYTHONPATH."
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run src.agents.deep_interpreter.tools.literature.search_literature_dynamic "
            "with CLI arguments."
        )
    )
    parser.add_argument(
        "--genes",
        default="",
        help="Comma-separated genes (e.g., CDH1,TGFB1,VIM).",
    )
    parser.add_argument(
        "--pathways",
        default="",
        help="Comma-separated pathways (e.g., EMT,TGFb,Hypoxia).",
    )
    parser.add_argument(
        "--celltypes",
        default="",
        help="Comma-separated cell types (e.g., Tumor,Fibroblast,Macrophages).",
    )
    parser.add_argument(
        "--disease",
        required=True,
        help="Disease context (e.g., breast cancer).",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=30,
        help="Maximum number of papers to return (default: 30).",
    )
    parser.add_argument(
        "--target-gene-coverage",
        type=float,
        default=0.6,
        help="Target gene coverage ratio in [0,1] (default: 0.6).",
    )
    parser.add_argument(
        "--target-pathway-coverage",
        type=float,
        default=0.5,
        help="Target pathway coverage ratio in [0,1] (default: 0.5).",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="Maximum dynamic-search iterations (default: 3).",
    )
    parser.add_argument(
        "--enforce-disease-match",
        dest="enforce_disease_match",
        action="store_true",
        default=True,
        help="Require disease-context match when filtering results (default: enabled).",
    )
    parser.add_argument(
        "--no-enforce-disease-match",
        dest="enforce_disease_match",
        action="store_false",
        help="Disable disease-context post-filtering.",
    )
    parser.add_argument(
        "--output-path",
        default="",
        help="Relative output JSON filename for auto-save (e.g., part1_papers.json).",
    )
    parser.add_argument(
        "--data-dir",
        default="",
        help="Directory used with output_path. Overrides DEEP_INTERPRETER_DATA_DIR if provided.",
    )
    parser.add_argument(
        "--rerank-mode",
        choices=["off", "llm"],
        default="off",
        help="Optional disease relevance rerank mode (default: off).",
    )
    parser.add_argument(
        "--rerank-top-n",
        type=int,
        default=12,
        help="Maximum boundary papers for reranking (default: 12).",
    )
    parser.add_argument(
        "--rerank-min-confidence",
        type=float,
        default=0.70,
        help="Minimum rerank confidence threshold (default: 0.70).",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    repo_root = _find_repo_root()
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)

    from src.agents.deep_interpreter.tools.literature import search_literature_dynamic

    payload = {
        "genes": _parse_csv_list(args.genes),
        "pathways": _parse_csv_list(args.pathways),
        "celltypes": _parse_csv_list(args.celltypes),
        "disease": args.disease,
        "max_results": args.max_results,
        "target_gene_coverage": args.target_gene_coverage,
        "target_pathway_coverage": args.target_pathway_coverage,
        "max_iterations": args.max_iterations,
        "enforce_disease_match": args.enforce_disease_match,
        "output_path": args.output_path,
        "data_dir": args.data_dir,
        "rerank_mode": args.rerank_mode,
        "rerank_top_n": args.rerank_top_n,
        "rerank_min_confidence": args.rerank_min_confidence,
    }

    try:
        result = search_literature_dynamic.invoke(payload)
    except Exception as exc:
        print(f"search_literature_dynamic failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

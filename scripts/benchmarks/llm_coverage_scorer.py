"""LLM-based hybrid coverage scorer for literature benchmark.

Hybrid approach: uses existing string-based pattern matching first,
then asks LLM about unmatched items only (genes, pathways, celltypes).

Processes unique (case_id, method) pairs using first repeat's papers.
Results keyed by (case_id, method) apply to all repeats.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from scripts.benchmarks.score_lit_benchmark import _load_runs


def _build_coverage_prompt(
    missing_genes: list[str],
    missing_pathways: list[str],
    missing_celltypes: list[str],
    papers: list[dict[str, Any]],
) -> str:
    """Build LLM prompt for coverage assessment of unmatched items."""
    parts = [
        "You are a biomedical literature expert. Given the papers below, determine which biological items are discussed, referenced, or studied.",
        "",
        "An item is COVERED if any paper mentions it directly, by synonym, abbreviation, or closely related term. Consider:",
        "- Gene aliases (e.g., TP53 = p53, ERBB2 = HER2, CDH1 = E-cadherin)",
        "- Cell type synonyms (e.g., NK cells = natural killer cells, TAMs = tumor-associated macrophages)",
        "- Pathway variations (e.g., MAPK = ERK signaling, Wnt = beta-catenin pathway)",
        "",
        "Papers:",
    ]
    for i, p in enumerate(papers[:30], 1):
        title = str(p.get("title", ""))[:300]
        abstract = str(p.get("abstract", ""))[:500]
        parts.append(f"{i}. \"{title}\"")
        if abstract:
            parts.append(f"   {abstract}")
    parts.append("")
    parts.append("For each item below, answer exactly COVERED or NOT_COVERED on the same line:")
    parts.append("")

    if missing_genes:
        parts.append("Genes:")
        for g in missing_genes:
            parts.append(f"- {g}:")
        parts.append("")

    if missing_pathways:
        parts.append("Pathways:")
        for p in missing_pathways:
            parts.append(f"- {p}:")
        parts.append("")

    if missing_celltypes:
        parts.append("Cell Types:")
        for c in missing_celltypes:
            parts.append(f"- {c}:")
        parts.append("")

    return "\n".join(parts)


def _call_ollama(
    prompt: str, model: str, ollama_host: str, timeout: int = 180
) -> str:
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {"temperature": 0},
        }
    ).encode()
    req = urllib.request.Request(
        f"{ollama_host}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode())
    return str(body.get("message", {}).get("content", ""))


def _parse_coverage_response(
    response: str,
    missing_genes: list[str],
    missing_pathways: list[str],
    missing_celltypes: list[str],
) -> dict[str, list[str]]:
    """Parse LLM response to extract which missing items are covered."""
    covered_genes: list[str] = []
    covered_pathways: list[str] = []
    covered_celltypes: list[str] = []

    # Build lookup: item_name_lower -> (category, original_name)
    all_items: list[tuple[str, str, str]] = []  # (category, original, lower)
    for g in missing_genes:
        all_items.append(("gene", g, g.lower()))
    for p in missing_pathways:
        all_items.append(("pathway", p, p.lower()))
    for c in missing_celltypes:
        all_items.append(("celltype", c, c.lower()))

    lines = response.strip().split("\n")
    for line in lines:
        line_stripped = line.strip().lstrip("- ")
        if not line_stripped:
            continue
        upper = line_stripped.upper()
        if "COVERED" not in upper:
            continue
        is_not_covered = "NOT_COVERED" in upper or "NOT COVERED" in upper
        if is_not_covered:
            continue

        # Find which item this line refers to
        line_lower = line_stripped.lower()
        for category, original, item_lower in all_items:
            if item_lower in line_lower:
                if category == "gene" and original not in covered_genes:
                    covered_genes.append(original)
                elif category == "pathway" and original not in covered_pathways:
                    covered_pathways.append(original)
                elif category == "celltype" and original not in covered_celltypes:
                    covered_celltypes.append(original)
                break

    return {
        "llm_genes_covered": covered_genes,
        "llm_pathways_covered": covered_pathways,
        "llm_celltypes_covered": covered_celltypes,
    }


def _extract_unique_cases(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract unique (case_id, method) with first repeat's data."""
    seen: set[tuple[str, str]] = set()
    cases: list[dict[str, Any]] = []
    for r in records:
        if r.get("error"):
            continue
        key = (str(r.get("case_id", "")), str(r.get("method", "")))
        if key in seen:
            continue
        seen.add(key)

        coverage = r.get("coverage", {})
        if not isinstance(coverage, dict):
            cases.append(
                {
                    "case_id": key[0],
                    "method": key[1],
                    "skip": True,
                    "missing_genes": [],
                    "missing_pathways": [],
                    "missing_celltypes": [],
                }
            )
            continue

        missing_genes = coverage.get("genes_missing", [])
        missing_pathways = coverage.get("pathways_missing", [])
        missing_celltypes = coverage.get("celltypes_missing", [])

        if not missing_genes and not missing_pathways and not missing_celltypes:
            cases.append(
                {
                    "case_id": key[0],
                    "method": key[1],
                    "skip": True,
                    "missing_genes": [],
                    "missing_pathways": [],
                    "missing_celltypes": [],
                }
            )
            continue

        cases.append(
            {
                "case_id": key[0],
                "method": key[1],
                "missing_genes": missing_genes,
                "missing_pathways": missing_pathways,
                "missing_celltypes": missing_celltypes,
                "papers": r.get("papers", []),
                "input_genes": r.get("input", {}).get("genes", []),
                "input_pathways": r.get("input", {}).get("pathways", []),
                "input_celltypes": r.get("input", {}).get("celltypes", []),
                "string_genes_covered": coverage.get("genes_covered", []),
                "string_pathways_covered": coverage.get("pathways_covered", []),
                "string_celltypes_covered": coverage.get("celltypes_covered", []),
                "skip": False,
            }
        )
    return cases


def _score_one(
    case: dict[str, Any], model: str, ollama_host: str
) -> dict[str, Any]:
    if case["skip"]:
        return {
            "case_id": case["case_id"],
            "method": case["method"],
            "llm_genes_covered": [],
            "llm_pathways_covered": [],
            "llm_celltypes_covered": [],
            "missing_genes": case["missing_genes"],
            "missing_pathways": case["missing_pathways"],
            "missing_celltypes": case["missing_celltypes"],
            "skipped": True,
            "model": model,
        }

    prompt = _build_coverage_prompt(
        missing_genes=case["missing_genes"],
        missing_pathways=case["missing_pathways"],
        missing_celltypes=case["missing_celltypes"],
        papers=case["papers"],
    )

    try:
        response = _call_ollama(prompt, model, ollama_host)
        parsed = _parse_coverage_response(
            response,
            case["missing_genes"],
            case["missing_pathways"],
            case["missing_celltypes"],
        )
    except Exception as exc:
        return {
            "case_id": case["case_id"],
            "method": case["method"],
            "llm_genes_covered": [],
            "llm_pathways_covered": [],
            "llm_celltypes_covered": [],
            "missing_genes": case["missing_genes"],
            "missing_pathways": case["missing_pathways"],
            "missing_celltypes": case["missing_celltypes"],
            "error": str(exc),
            "model": model,
        }

    return {
        "case_id": case["case_id"],
        "method": case["method"],
        **parsed,
        "missing_genes": case["missing_genes"],
        "missing_pathways": case["missing_pathways"],
        "missing_celltypes": case["missing_celltypes"],
        "string_genes_covered": case.get("string_genes_covered", []),
        "string_pathways_covered": case.get("string_pathways_covered", []),
        "string_celltypes_covered": case.get("string_celltypes_covered", []),
        "input_genes": case.get("input_genes", []),
        "input_pathways": case.get("input_pathways", []),
        "input_celltypes": case.get("input_celltypes", []),
        "model": model,
    }


def _load_existing_keys(path: Path) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    if not path.exists():
        return keys
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                keys.add((str(obj["case_id"]), str(obj["method"])))
            except (json.JSONDecodeError, KeyError):
                continue
    return keys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, help="Path to run directory")
    parser.add_argument("--model", default="qwen3.5:122b", help="Ollama model name")
    parser.add_argument(
        "--ollama-host",
        default="http://localhost:6000",
        help="Ollama endpoint",
    )
    parser.add_argument(
        "--output",
        default="llm_coverage_labels.jsonl",
        help="Output filename",
    )
    parser.add_argument(
        "--concurrency", type=int, default=16, help="Parallel workers"
    )
    parser.add_argument(
        "--resume", action="store_true", help="Resume from existing output file"
    )
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    records = _load_runs(run_dir)
    print(f"Loaded {len(records)} records from {run_dir}")

    cases = _extract_unique_cases(records)
    to_score = [c for c in cases if not c["skip"]]
    skipped = [c for c in cases if c["skip"]]
    print(f"Extracted {len(cases)} unique (case_id, method) pairs")
    print(f"  Need LLM scoring: {len(to_score)}")
    print(f"  Fully covered (skip): {len(skipped)}")

    output_path = run_dir / args.output

    if args.resume:
        existing = _load_existing_keys(output_path)
        before = len(to_score)
        to_score = [
            c for c in to_score if (c["case_id"], c["method"]) not in existing
        ]
        print(
            f"Resume: {len(existing)} already scored, "
            f"{before - len(to_score)} skipped, {len(to_score)} remaining"
        )

    # Always write skipped entries (fully covered by string match)
    if not args.resume:
        with output_path.open("w", encoding="utf-8") as f:
            for c in skipped:
                result = _score_one(c, args.model, args.ollama_host)
                f.write(json.dumps(result, ensure_ascii=False) + "\n")
        print(f"Wrote {len(skipped)} skipped entries")

    if not to_score:
        print("Nothing to score.")
        return

    result_queue: queue.Queue[dict[str, Any]] = queue.Queue()
    scored = 0
    errors = 0
    lock = threading.Lock()

    def worker(case: dict[str, Any]) -> dict[str, Any]:
        result = _score_one(case, args.model, args.ollama_host)
        result_queue.put(result)
        return result

    stop_writer = threading.Event()

    def writer_loop() -> None:
        with output_path.open("a", encoding="utf-8") as f:
            while not stop_writer.is_set() or not result_queue.empty():
                try:
                    item = result_queue.get(timeout=0.5)
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
                    f.flush()
                except queue.Empty:
                    continue

    writer_thread = threading.Thread(target=writer_loop, daemon=True)
    writer_thread.start()

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(worker, c): c for c in to_score}
        for future in as_completed(futures):
            with lock:
                scored += 1
            try:
                result = future.result()
                if result.get("error"):
                    with lock:
                        errors += 1
            except Exception as exc:
                with lock:
                    errors += 1
                print(f"Error: {exc}", file=sys.stderr)

            if scored % 20 == 0 or scored == len(to_score):
                print(f"Progress: {scored}/{len(to_score)} scored", flush=True)

    stop_writer.set()
    writer_thread.join(timeout=10)

    print(f"\nScoring complete:")
    print(f"  Scored: {scored}")
    print(f"  Errors: {errors}")
    print(f"  Output: {output_path}")


if __name__ == "__main__":
    main()

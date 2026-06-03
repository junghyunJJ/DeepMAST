#!/usr/bin/env python3
"""Graded per-paper LR-relevance judge for retrieval skill ON/OFF comparison.

Independent of the deterministic bucket grader. Scores each retrieved raw paper
(papers_raw.json) against its benchmark case with a 0-3 LR-aware rubric using an
ollama-hosted judge (think disabled, temperature 0). Relevance is a property of
(case_id, pmid), so each unique pair is scored once and mapped back to every arm
occurrence; this measures per-paper relevance DEPTH (precision), controlling for
the volume differences between arms.

Rubric:
  3 = direct LR evidence (ligand-receptor interaction / signaling discussed)
  2 = receptor / ligand / pathway context in the disease setting
  1 = disease background only (no LR or pathway link)
  0 = irrelevant / off-topic

Usage:
  python scripts/benchmarks/score_retrieval_relevance_graded.py \
    --runner-rows docs/benchmarks/lr_retrieval_relevance/results/<root>/converted_runner_rows.jsonl \
    --output docs/benchmarks/lr_retrieval_relevance/results/<root>/graded_relevance_labels.jsonl \
    --ollama-host http://localhost:7000 --model qwen3.5:122b
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


def _build_prompt(ctx: dict[str, Any], title: str, abstract: str) -> str:
    lig = ctx.get("ligand") or "?"
    rec = ctx.get("receptor") or "?"
    disease = ctx.get("disease") or "?"
    pathways = ", ".join(ctx.get("pathways") or []) or "(none given)"
    celltypes = ", ".join(ctx.get("celltypes") or []) or "(none given)"
    parts = [
        "You are a biomedical literature expert grading how relevant a paper is to a "
        "specific ligand-receptor (LR) interaction interpretation in a disease context.",
        "",
        f"Ligand: {lig}",
        f"Receptor: {rec}",
        f"Disease: {disease}",
        f"Relevant pathways: {pathways}",
        f"Relevant cell types: {celltypes}",
        "",
        "Grade the paper on this 0-3 scale (depth of relevance to THIS LR interpretation):",
        f"  3 = directly discusses the {lig}-{rec} interaction or its signaling.",
        f"  2 = discusses {lig}, {rec}, or their pathway/cell-type context in this disease.",
        "  1 = about the disease only, with no link to this LR or its pathways.",
        "  0 = off-topic / irrelevant to the disease and the LR.",
        "",
        f"Paper title: {title}",
    ]
    if abstract:
        parts.append(f"Paper abstract: {abstract}")
    parts.append("")
    parts.append("Answer with exactly one digit: 0, 1, 2, or 3. No other text.")
    return "\n".join(parts)


def _call_ollama(prompt: str, model: str, ollama_host: str, timeout: int = 180) -> str:
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


def _parse_score(text: str) -> int | None:
    m = re.search(r"[0-3]", text)
    return int(m.group()) if m else None


def _score_one(rec: dict[str, Any], model: str, ollama_host: str) -> dict[str, Any]:
    prompt = _build_prompt(rec["ctx"], rec["title"], rec["abstract"])
    score: int | None = None
    for _ in range(2):  # one retry on parse failure
        try:
            score = _parse_score(_call_ollama(prompt, model, ollama_host))
            if score is not None:
                break
        except Exception:
            score = None
    return {
        "case_id": rec["case_id"],
        "pmid": rec["pmid"],
        "score": score,
        "model": model,
    }


def _build_unique_records(runner_rows: Path) -> list[dict[str, Any]]:
    """One record per unique (case_id, pmid); relevance is arm-independent."""
    seen: set[tuple[str, str]] = set()
    records: list[dict[str, Any]] = []
    rows = [json.loads(line) for line in runner_rows.read_text().splitlines() if line.strip()]
    for row in rows:
        ws = row.get("trial_workspace")
        if not ws:
            continue
        raw_path = Path(ws) / "papers_raw.json"
        ctx_path = Path(ws) / "search_context.json"
        if not raw_path.exists():
            continue
        ctx = json.loads(ctx_path.read_text()) if ctx_path.exists() else {}
        ctx = {
            "ligand": row.get("ligand"),
            "receptor": row.get("receptor"),
            "disease": ctx.get("disease") or row.get("disease"),
            "pathways": ctx.get("pathways") or row.get("pathways") or [],
            "celltypes": ctx.get("celltypes") or row.get("celltypes") or [],
        }
        papers = json.loads(raw_path.read_text()).get("papers", [])
        case_id = row["case_id"]
        for paper in papers:
            pmid = str(paper.get("pmid", "")).strip()
            if not pmid:
                continue
            key = (case_id, pmid)
            if key in seen:
                continue
            seen.add(key)
            records.append(
                {
                    "case_id": case_id,
                    "pmid": pmid,
                    "title": str(paper.get("title", "") or ""),
                    "abstract": str(paper.get("abstract", "") or ""),
                    "ctx": ctx,
                }
            )
    return records


def _load_done_keys(path: Path) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    if not path.exists():
        return keys
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("score") is not None:
                keys.add((str(obj["case_id"]), str(obj["pmid"])))
        except (json.JSONDecodeError, KeyError):
            continue
    return keys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner-rows", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ollama-host", default="http://localhost:7000")
    parser.add_argument("--model", default="qwen3.5:122b")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    records = _build_unique_records(Path(args.runner_rows))
    out_path = Path(args.output)
    done = _load_done_keys(out_path)
    todo = [r for r in records if (r["case_id"], r["pmid"]) not in done]
    print(f"unique pairs={len(records)} done={len(done)} todo={len(todo)}", flush=True)
    if not todo:
        print("Nothing to score.")
        return

    lock = threading.Lock()
    scored = 0
    with out_path.open("a", encoding="utf-8") as fh:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(_score_one, r, args.model, args.ollama_host) for r in todo]
            for fut in as_completed(futures):
                result = fut.result()
                with lock:
                    fh.write(json.dumps(result) + "\n")
                    fh.flush()
                    scored += 1
                    if scored % 100 == 0 or scored == len(todo):
                        print(f"Progress: {scored}/{len(todo)}", flush=True)
    print(f"Done. scored this run={scored}", flush=True)


if __name__ == "__main__":
    sys.exit(main())

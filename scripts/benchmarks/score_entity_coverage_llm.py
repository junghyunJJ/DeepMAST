#!/usr/bin/env python3
"""LLM entity-coverage scorer — semantic replacement for regex `_calculate_coverage`.

For each unique (case_id, pmid) retrieved paper, asks an ollama-hosted LLM which of
the case's pathways / cell types the paper actually discusses (synonyms + paraphrases
count, unlike regex). Output is per-paper covered-entity lists; arm-level coverage_pct
is the union over an arm's papers (computed in analyze_entity_coverage.py). One pass
over the raw retrieved set yields both raw and filtered (direct+context) coverage.

Usage:
  python scripts/benchmarks/score_entity_coverage_llm.py \
    --runner-rows .../converted_runner_rows.jsonl \
    --output .../entity_coverage_labels.jsonl \
    --ollama-host http://localhost:7000 --model qwen3.5:35b --workers 8
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


def _build_prompt(pathways: list[str], celltypes: list[str], title: str, abstract: str) -> str:
    plist = "\n".join(f"  - {p}" for p in pathways) or "  (none)"
    clist = "\n".join(f"  - {c}" for c in celltypes) or "  (none)"
    return (
        "You are a biomedical literature expert. Decide which of the listed biological "
        "concepts a paper ACTUALLY discusses, counting synonyms, abbreviations, gene/protein "
        "name variants, and paraphrases (not just exact string matches).\n\n"
        f"Candidate pathways:\n{plist}\n\n"
        f"Candidate cell types:\n{clist}\n\n"
        f"Paper title: {title}\n"
        f"Paper abstract: {abstract}\n\n"
        "Include a concept ONLY if the title/abstract genuinely discusses or refers to it. "
        "Return STRICT JSON with exact strings copied from the lists above:\n"
        '{"pathways": [...], "celltypes": [...]}\n'
        "Use [] when none apply. Output only the JSON object."
    )


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


def _parse_json(text: str) -> dict[str, list[str]] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    paths = obj.get("pathways", [])
    cells = obj.get("celltypes", [])
    return {
        "pathways": [str(x) for x in paths] if isinstance(paths, list) else [],
        "celltypes": [str(x) for x in cells] if isinstance(cells, list) else [],
    }


def _score_one(rec: dict[str, Any], model: str, ollama_host: str) -> dict[str, Any]:
    prompt = _build_prompt(rec["pathways"], rec["celltypes"], rec["title"], rec["abstract"])
    parsed: dict[str, list[str]] | None = None
    for _ in range(2):
        try:
            parsed = _parse_json(_call_ollama(prompt, model, ollama_host))
            if parsed is not None:
                break
        except Exception:
            parsed = None
    # Guard against hallucinated entries: intersect with the candidate lists.
    cov_p = [p for p in (parsed or {}).get("pathways", []) if p in rec["pathways"]] if parsed else None
    cov_c = [c for c in (parsed or {}).get("celltypes", []) if c in rec["celltypes"]] if parsed else None
    return {
        "case_id": rec["case_id"],
        "pmid": rec["pmid"],
        "pathways_covered": cov_p,
        "celltypes_covered": cov_c,
        "ok": parsed is not None,
        "model": model,
    }


def _build_unique_records(runner_rows: Path) -> list[dict[str, Any]]:
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
        pathways = ctx.get("pathways") or row.get("pathways") or []
        celltypes = ctx.get("celltypes") or row.get("celltypes") or []
        papers = json.loads(raw_path.read_text()).get("papers", [])
        case_id = row["case_id"]
        for paper in papers:
            pmid = str(paper.get("pmid", "")).strip()
            if not pmid or (case_id, pmid) in seen:
                continue
            seen.add((case_id, pmid))
            records.append(
                {
                    "case_id": case_id,
                    "pmid": pmid,
                    "title": str(paper.get("title", "") or ""),
                    "abstract": str(paper.get("abstract", "") or ""),
                    "pathways": list(pathways),
                    "celltypes": list(celltypes),
                }
            )
    return records


def _load_done(path: Path) -> set[tuple[str, str]]:
    done: set[tuple[str, str]] = set()
    if not path.exists():
        return done
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("ok"):
                done.add((str(obj["case_id"]), str(obj["pmid"])))
        except (json.JSONDecodeError, KeyError):
            continue
    return done


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner-rows", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ollama-host", default="http://localhost:7000")
    parser.add_argument("--model", default="qwen3.5:35b")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    records = _build_unique_records(Path(args.runner_rows))
    out_path = Path(args.output)
    done = _load_done(out_path)
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

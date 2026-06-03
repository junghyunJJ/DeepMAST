#!/usr/bin/env python3
"""LLM gene-coverage scorer (ligand/receptor) — companion to score_entity_coverage_llm.py.

For CCI cases the gene set is exactly the LR pair {ligand, receptor}. For each unique
(case_id, pmid) this asks the LLM which of the two genes the paper discusses (synonyms,
full names, and aliases count). Arm-level gene_coverage_pct = union over the arm's papers.
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


def _build_prompt(genes: list[str], title: str, abstract: str) -> str:
    glist = "\n".join(f"  - {g}" for g in genes)
    return (
        "You are a biomedical literature expert. Decide which of the listed genes/proteins a "
        "paper ACTUALLY discusses, counting official symbols, full names, and common aliases "
        "(e.g., EGF = epidermal growth factor; not just exact string matches).\n\n"
        f"Candidate genes:\n{glist}\n\n"
        f"Paper title: {title}\n"
        f"Paper abstract: {abstract}\n\n"
        "Return STRICT JSON with exact strings copied from the list above:\n"
        '{"genes": [...]}\n'
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


def _parse(text: str, genes: list[str]) -> list[str] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    got = obj.get("genes", []) if isinstance(obj, dict) else []
    if not isinstance(got, list):
        return None
    return [g for g in (str(x) for x in got) if g in genes]


def _score_one(rec: dict[str, Any], model: str, ollama_host: str) -> dict[str, Any]:
    prompt = _build_prompt(rec["genes"], rec["title"], rec["abstract"])
    covered: list[str] | None = None
    for _ in range(2):
        try:
            covered = _parse(_call_ollama(prompt, model, ollama_host), rec["genes"])
            if covered is not None:
                break
        except Exception:
            covered = None
    return {
        "case_id": rec["case_id"],
        "pmid": rec["pmid"],
        "genes_covered": covered,
        "ok": covered is not None,
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
        if not raw_path.exists():
            continue
        genes = [g for g in (row.get("ligand"), row.get("receptor")) if g]
        if not genes:
            continue
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
                    "genes": list(genes),
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
    parser.add_argument("--ollama-host", default="http://localhost:6000")
    parser.add_argument("--model", default="qwen3.5:122b")
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

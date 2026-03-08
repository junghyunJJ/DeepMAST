"""LLM-based paper relevance scorer for literature benchmark contamination measurement.

Uses majority-vote (default 3 calls, 2+ agreement) with an ollama-hosted LLM
to determine whether each paper is relevant to its associated disease query.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from scripts.benchmarks.score_lit_benchmark import _load_runs


def _build_prompt(disease: str, title: str, abstract: str) -> str:
    parts = [
        f'You are a biomedical literature expert. Determine if the following paper is relevant to the disease "{disease}".',
        "",
        "A paper is RELEVANT if it studies, discusses, or provides findings applicable to this disease, including synonyms, subtypes, and related conditions.",
        "",
        f"Paper title: {title}",
    ]
    if abstract:
        parts.append(f"Paper abstract: {abstract}")
    parts.append("")
    parts.append("Answer with exactly one word: RELEVANT or NOT_RELEVANT")
    return "\n".join(parts)


def _call_ollama(
    prompt: str, model: str, ollama_host: str, timeout: int = 120
) -> str:
    """Call ollama /api/chat with thinking disabled for speed."""
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


def _parse_vote(text: str) -> str:
    """Parse LLM response into RELEVANT, NOT_RELEVANT, or error."""
    upper = text.strip().upper()
    if "NOT_RELEVANT" in upper:
        return "NOT_RELEVANT"
    if "RELEVANT" in upper:
        return "RELEVANT"
    return "error"


def _score_one(
    disease: str,
    pmid: str,
    title: str,
    abstract: str,
    model: str,
    ollama_host: str,
    n_votes: int,
) -> dict[str, Any]:
    """Score a single (disease, pmid) pair with majority vote."""
    prompt = _build_prompt(disease, title, abstract)
    votes: list[str] = []
    for _ in range(n_votes):
        try:
            raw = _call_ollama(prompt, model, ollama_host)
            vote = _parse_vote(raw)
            if vote == "error":
                # Retry once on unparseable response
                raw = _call_ollama(prompt, model, ollama_host)
                vote = _parse_vote(raw)
            votes.append(vote)
        except Exception:
            votes.append("error")

    n_relevant = sum(1 for v in votes if v == "RELEVANT")
    n_not_relevant = sum(1 for v in votes if v == "NOT_RELEVANT")
    n_error = sum(1 for v in votes if v == "error")

    if n_error >= 2:
        relevant = None
    elif n_relevant >= 2:
        relevant = True
    else:
        relevant = False

    return {
        "disease": disease,
        "pmid": pmid,
        "title": title,
        "relevant": relevant,
        "votes": votes,
        "vote_count": {
            "relevant": n_relevant,
            "not_relevant": n_not_relevant,
            "error": n_error,
        },
        "model": model,
    }


def _extract_unique_pairs(
    records: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Extract unique (disease, pmid) pairs with first-seen title and abstract."""
    seen: set[tuple[str, str]] = set()
    pairs: list[dict[str, str]] = []
    for r in records:
        disease = str(r.get("input", {}).get("disease", "")).strip()
        papers = r.get("papers", [])
        if not isinstance(papers, list):
            continue
        for p in papers:
            if not isinstance(p, dict):
                continue
            pmid = str(p.get("pmid", "")).strip()
            if not pmid or not disease:
                continue
            key = (disease, pmid)
            if key in seen:
                continue
            seen.add(key)
            pairs.append(
                {
                    "disease": disease,
                    "pmid": pmid,
                    "title": str(p.get("title", "") or ""),
                    "abstract": str(p.get("abstract", "") or ""),
                }
            )
    return pairs


def _load_existing_keys(path: Path) -> set[tuple[str, str]]:
    """Load already-scored (disease, pmid) keys from existing output."""
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
                keys.add((str(obj["disease"]), str(obj["pmid"])))
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
        default="llm_relevance_labels.jsonl",
        help="Output filename",
    )
    parser.add_argument(
        "--votes", type=int, default=3, help="Number of LLM calls per paper"
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

    pairs = _extract_unique_pairs(records)
    print(f"Extracted {len(pairs)} unique (disease, pmid) pairs")

    output_path = run_dir / args.output

    if args.resume:
        existing = _load_existing_keys(output_path)
        before = len(pairs)
        pairs = [p for p in pairs if (p["disease"], p["pmid"]) not in existing]
        print(f"Resume: {len(existing)} already scored, {before - len(pairs)} skipped, {len(pairs)} remaining")

    if not pairs:
        print("Nothing to score.")
        return

    result_queue: queue.Queue[dict[str, Any]] = queue.Queue()
    scored = 0
    errors = 0
    lock = threading.Lock()

    def worker(pair: dict[str, str]) -> dict[str, Any]:
        result = _score_one(
            disease=pair["disease"],
            pmid=pair["pmid"],
            title=pair["title"],
            abstract=pair["abstract"],
            model=args.model,
            ollama_host=args.ollama_host,
            n_votes=args.votes,
        )
        result_queue.put(result)
        return result

    # Writer thread: drains queue and appends to JSONL
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
        futures = {pool.submit(worker, p): p for p in pairs}
        for future in as_completed(futures):
            with lock:
                scored += 1
            try:
                result = future.result()
                if result["relevant"] is None:
                    with lock:
                        errors += 1
            except Exception as exc:
                with lock:
                    errors += 1
                print(f"Error scoring {futures[future]}: {exc}", file=sys.stderr)

            if scored % 100 == 0 or scored == len(pairs):
                print(f"Progress: {scored}/{len(pairs)} scored", flush=True)

    stop_writer.set()
    writer_thread.join(timeout=10)

    # Summary
    relevant_count = 0
    not_relevant_count = 0
    null_count = 0
    if output_path.exists():
        with output_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("relevant") is True:
                        relevant_count += 1
                    elif obj.get("relevant") is False:
                        not_relevant_count += 1
                    else:
                        null_count += 1
                except json.JSONDecodeError:
                    continue

    print(f"\nScoring complete:")
    print(f"  Total scored this run: {scored}")
    print(f"  Total in output file: {relevant_count + not_relevant_count + null_count}")
    print(f"  Relevant: {relevant_count}")
    print(f"  Not relevant: {not_relevant_count}")
    print(f"  Unscored (errors): {null_count}")
    print(f"  Output: {output_path}")


if __name__ == "__main__":
    main()

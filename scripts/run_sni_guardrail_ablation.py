"""Run an SNI-only guardrail ablation against frozen historical controls.

Prepare with --root NEW_RUN --source BC_INPUTS --archive HISTORICAL_ARCHIVE;
then run with --root NEW_RUN. Preparation freezes the current committed code
and input paths for all workers. Historical ON controls retain BASE_HEAD;
a new run on newer code is not an exact reproduction of the archived benchmark.
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import run_bc_sni_repair_ablation as baseline

BASE_HEAD = "e78c7af80012d2dd15df093147fd8fb02d4782b1"
ARCHIVE = REPO_ROOT / "res/deep_interpreter/bc/sni_repair_ablation"
SOURCE = REPO_ROOT / "res/deep_interpreter/bc/bc"
FROZEN_CODE_PATHS = (
    "src", "skills", "scripts/run_bc_sni_repair_ablation.py",
    "scripts/run_deep_interpreter_agent.py", "scripts/run_sni_guardrail_ablation.py",
    "scripts/sni_guardrail_ablation_support.py",
)
HISTORICAL_ROOTS = (
    "post_repair_integrity_pair15r2_pair20_sequential_20260830T095354Z",
    "post_repair_integrity_counterbalanced_pair16_pair25_20260831T182417Z",
    "post_repair_integrity_counterbalanced_resume_pair17nosni_pair25_20260901T000438Z",
    "post_repair_integrity_counterbalanced_resume2_pair21_pair25_20260901T170744Z",
)
API = {"api_port": 8883, "backend_port": 6000}
REPORTS = (*baseline.REPORT_FILES, "CCI_Analysis_Report.html")
PATH_SETTINGS = {"DEEP_INTERPRETER_DATA_DIR", "DEEP_INTERPRETER_RAG_AUDIT_PATH"}
INPUT_NAMES = (
    *baseline.INPUT_FILES, "settings.json", "part4_therapeutic_synthesis.md", "drug.md",
    "planner_papers.json", "search_context.json", "citation_candidates.json",
    "lr_candidates.json", "lr_pairs_search.json", "selected_lr_pairs_backfill.json",
    "papers_metadata.json", "papers_raw.json", "papers_raw_metadata.json",
    "target_assessment.json", "dataset_result.json",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_cohort(rows: list[dict]) -> None:
    labels = [(r["pair_id"], r["sequence"]) for r in rows]
    expected = {(str(pair), seq) for pair in range(16, 26) for seq in ("AB", "BA")}
    if len(labels) != 20 or set(labels) != expected:
        raise ValueError("historical cohort must contain each Pair 16–25 AB/BA label exactly once")


def build_cohort(archive: Path = ARCHIVE) -> list[dict]:
    rows = []
    for number, name in enumerate(HISTORICAL_ROOTS):
        root = archive / name
        state = read_json(root / "sequence_status.json")
        for entry in state["runs"]:
            pair = entry["pair_id"]
            if entry["status"] not in {"passed", "failed"} or pair not in map(str, range(16, 26)):
                continue
            if number == 0:
                directory = root / "pairs" / f"pair-{pair}" / "wiki-on"
                sequence = "AB"
            else:
                if entry["condition"] != "SNI":
                    continue
                recorded_root = Path(entry["output_root"])
                relative_root = Path(*recorded_root.parts[recorded_root.parts.index(name) + 1:])
                directory = root / relative_root / f"pair-{pair}" / "wiki-on"
                sequence = entry["sequence"].split("-")[0]
            manifest = read_json(directory / "run_manifest.json")
            if manifest["condition_label"] != "SNI":
                raise ValueError(f"not SNI: {directory}")
            rows.append({
                "pair_id": pair, "sequence": sequence,
                "historical_dir": str(directory), "historical_status": manifest["return_status"],
                "historical_manifest_sha256": baseline.sha256(directory / "run_manifest.json"),
                "failure_classification": entry.get("failure_classification"),
            })
    validate_cohort(rows)
    return sorted(rows, key=lambda r: (int(r["pair_id"]), r["sequence"]))


def report_hashes(directory: Path) -> dict:
    return {name: baseline.sha256(directory / name) for name in REPORTS if (directory / name).is_file()}


def reports_complete(directory: Path) -> bool:
    return all((directory / name).is_file() and (directory / name).stat().st_size > 0 for name in REPORTS)


def source_hashes(source: Path | None = None) -> dict:
    source = source if source is not None else SOURCE
    missing = [name for name in baseline.INPUT_FILES if not (source / name).is_file()]
    if missing:
        raise RuntimeError(f"missing benchmark source inputs at {source}: {missing}")
    names = set(INPUT_NAMES)
    for pattern in ("*.csv", "*.h5ad", "*.png"):
        names.update(p.name for p in source.glob(pattern))
    for directory in ("papers", "evidence"):
        names.update(str(p.relative_to(source)) for p in (source / directory).rglob("*") if p.is_file())
    return {name: baseline.sha256(source / name) for name in sorted(names) if (source / name).is_file()}


def fetch_json(url: str) -> dict:
    with urlopen(url, timeout=20) as response:
        return json.load(response)


def service_preflight(source: Path | None = None) -> dict:
    source = source if source is not None else SOURCE
    models = {}
    for port in (6000, 4000):
        available = fetch_json(f"http://localhost:{port}/api/tags")["models"]
        matches = [m for m in available if m.get("name") == baseline.MODEL]
        if len(matches) != 1:
            raise RuntimeError(f"baseline model unavailable on {port}")
        models[str(port)] = {k: matches[0].get(k) for k in ("name", "digest")}
    health = fetch_json("http://localhost:8883/health")
    if health.get("status") != "ok":
        raise RuntimeError(f"RAG unhealthy: {health}")
    collection = baseline._default_collection_snapshot("http://localhost:8883")
    pmids = baseline._collection_pmids("http://localhost:8883")
    source_pmids = baseline._papers_pmids(source / "papers.json")
    if collection != baseline.BC_COLLECTION_SNAPSHOT or pmids != source_pmids or len(pmids) != 100:
        raise RuntimeError("fixed RAG collection/PMID identity changed")
    return {"checked_at": now(), "models": models, "collection": collection,
            "pmid_identity": baseline._pmid_identity(source_pmids, pmids)}


def verify_frozen_inputs(cohort: list[dict], *, source: Path | None = None, code_ref: str | None = None) -> dict:
    source = source if source is not None else SOURCE
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    reference = code_ref or head
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", reference, "--", *FROZEN_CODE_PATHS],
        cwd=REPO_ROOT, text=True,
    ).strip()
    if changed:
        raise RuntimeError(f"baseline generation code changed: {changed}")
    hashes = source_hashes(source)
    for row in cohort:
        directory = Path(row["historical_dir"])
        manifest = read_json(directory / "run_manifest.json")
        source_manifest = read_json(directory / "source_manifest.json")
        if baseline.sha256(directory / "run_manifest.json") != row["historical_manifest_sha256"]:
            raise RuntimeError(f"historical manifest changed: {directory}")
        expected_env = baseline._condition_env(directory, API, baseline.CONDITION_BY_LABEL["SNI"])
        for key, value in manifest["model_settings"].items():
            if key not in PATH_SETTINGS and expected_env.get(key) != value:
                raise RuntimeError(f"historical runtime setting mismatch: {directory}: {key}")
        for name, digest in hashes.items():
            if name == "targets.json":
                observed = source_manifest["source_files"][name]
            else:
                observed = baseline.sha256(directory / name)
            if observed != digest:
                raise RuntimeError(f"historical input differs from source: {directory}: {name}")
        for name, digest in source_manifest["source_files"].items():
            if hashes.get(name) != digest:
                raise RuntimeError(f"original source manifest mismatch: {directory}: {name}")
        observed_reports = report_hashes(directory)
        if "historical_report_hashes" in row and row["historical_report_hashes"] != observed_reports:
            raise RuntimeError(f"historical report changed: {directory}")
        row["historical_report_hashes"] = observed_reports
    return {"code_head": head, "historical_generation_commit": BASE_HEAD, "source": str(source), "input_sha256": hashes}


def generation_pending(row: dict) -> bool:
    return row["generation_status"] == "pending"


def summarize_rows(rows: list[dict]) -> dict:
    summary = {}
    for arm in ("on", "off"):
        selected = [r for r in rows if r["arm"] == arm]
        attempted = [r for r in selected if r["generation_status"] != "pending"]
        unknown = sum(r.get("evaluation", {}).get("usable") is None for r in attempted)
        usable = sum(r.get("evaluation", {}).get("usable") is True for r in attempted)
        complete = sum(r.get("evaluation", {}).get("complete", r.get("report_complete")) is True for r in attempted)
        times = [r["generation_seconds"] for r in attempted if r.get("generation_seconds") is not None]
        summary[arm] = {
            "planned": len(selected), "attempted": len(attempted), "unattempted": len(selected) - len(attempted),
            "usable": usable, "complete": complete, "evaluation_unknown": unknown,
            "usable_rate": usable / len(attempted) if attempted and not unknown else None,
            "failure_reasons": dict(Counter(r["failure_reason"] for r in attempted if r.get("failure_reason"))),
            "observed_generation_seconds": sum(times), "generation_time_observations": len(times),
            "seconds_per_usable_report": sum(times) / usable if usable and len(times) == len(attempted) and not unknown else None,
        }
    return summary


def persist(root: Path, state: dict) -> None:
    state["updated_at"] = now()
    state["summary"] = summarize_rows(state["runs"])
    write_json(root / "status.json", state)
    fields = ("pair_id", "sequence", "arm", "generation_status", "evaluation_status", "complete", "usable", "hard_error_count", "failure_reason", "generation_seconds", "generation_tokens", "evaluation_seconds", "data_dir")
    with (root / "comparison.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in state["runs"]:
            item = {name: row.get(name) for name in fields}
            evaluation = row.get("evaluation", {})
            item.update({k: evaluation.get(k) for k in ("usable", "hard_error_count")})
            item["complete"] = evaluation.get("complete", row.get("report_complete"))
            item["evaluation_status"] = evaluation.get("status", "pending")
            item["evaluation_seconds"] = evaluation.get("elapsed_seconds")
            writer.writerow(item)
    lines = ["# SNI Guardrail ON vs OFF", "", f"Status: **{state['status']}**. Updated: {state['updated_at']}", "",
             "Primary endpoint: all required reports complete and common post-hoc hard errors = 0.",
             "Pending/failed evaluations are unknown, never validation passes. All attempted runs remain in the denominator.", "",
             "| Arm | Planned | Attempted | Complete | Usable | Evaluation unknown | Usable rate |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for arm, item in state["summary"].items():
        rate = "pending" if item["usable_rate"] is None else f"{item['usable_rate']:.1%}"
        lines.append(f"| {arm.upper()} | {item['planned']} | {item['attempted']} | {item['complete']} | {item['usable']} | {item['evaluation_unknown']} | {rate} |")
    lines.extend(["", "- ON uses all 20 historical SNI runs, including two guardrail failures; OFF uses new first attempts.",
                  "- Required artifacts: Parts 1–3 Markdown, synthesis Markdown, and nonempty rendered HTML. Shared input Part 4 is fixed.",
                  "- Existing deterministic/semantic guardrail policy is reused without repair on separate copies. Separate scientific-accuracy evaluation is excluded.",
                  "- Calendar time differs between arms; these are repeated executions of one BC dataset, not independent biological samples.",
                  "- Generation tokens are unavailable from the historical runner; missing values stay blank, not zero. Evaluation costs are separate.",
                  "- A final comparison requires all 40 rows adjudicated; inspect comparison.csv for per-run results.", ""])
    (root / "comparison.md").write_text("\n".join(lines), encoding="utf-8")


def elapsed(manifest: dict) -> float | None:
    if not manifest.get("started_at") or not manifest.get("finished_at"):
        return None
    return (datetime.fromisoformat(manifest["finished_at"]) - datetime.fromisoformat(manifest["started_at"])).total_seconds()


def prepare(root: Path, *, source: Path | None = None, archive: Path = ARCHIVE) -> None:
    source = (source if source is not None else SOURCE).expanduser().resolve()
    if root.exists():
        raise FileExistsError(f"refusing to replace experiment: {root}")
    cohort = build_cohort(archive)
    frozen = verify_frozen_inputs(cohort, source=source)
    services = service_preflight(source)
    root.mkdir(parents=True)
    code_paths = [Path(__file__), REPO_ROOT / "scripts/sni_guardrail_ablation_support.py"]
    write_json(root / "experiment_manifest.json", {
        "created_at": now(), "cohort": cohort, "frozen": frozen, "preflight": services,
        "adapter_sha256": {str(p.relative_to(REPO_ROOT)): baseline.sha256(p) for p in code_paths},
        "historical_model_digest": None, "independent_scientific_evaluation": False,
    })
    rows = []
    for index, entry in enumerate(cohort):
        manifest = read_json(Path(entry["historical_dir"]) / "run_manifest.json")
        for arm in ("on", "off"):
            directory = Path(entry["historical_dir"]) if arm == "on" else root / "off" / f"pair-{entry['pair_id']}-{entry['sequence']}" / "pairs" / f"pair-{entry['pair_id']}" / "wiki-on"
            rows.append({"index": index, "pair_id": entry["pair_id"], "sequence": entry["sequence"],
                         "arm": arm, "data_dir": str(directory),
                         "generation_status": entry["historical_status"] if arm == "on" else "pending",
                         "report_complete": reports_complete(directory) if arm == "on" else None,
                         "generation_seconds": elapsed(manifest) if arm == "on" else None,
                         "generation_tokens": None,
                         "failure_reason": entry["failure_classification"] if arm == "on" else None})
    persist(root, {"status": "prepared", "created_at": now(), "runs": rows})


def prepare_evaluation_copy(source: Path, destination: Path) -> Path:
    if destination.exists():
        raise FileExistsError(f"refusing to replace evaluation copy: {destination}")
    ignored = (
        "logs", "before", "after", "diffs", "large_tool_results", "claim_rag_checkpoint.json",
        "report_validation*.json", "synthesis_guardrail*.json", "parts_guardrail_result.json",
        "synthesis_validation.json", "synthesis_raw_validation.json", "rag_audit.jsonl", "*.trace", "trace.jsonl",
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{destination.name}-copy-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "report"
        shutil.copytree(source, staged, ignore=shutil.ignore_patterns(*ignored))
        for name in ("targets.json", "run_targets.json"):
            path = staged / name
            if path.exists():
                targets = read_json(path)
                targets["data_directory"] = str(destination)
                write_json(path, targets)
        (staged / "data_path.txt").write_text(str(destination), encoding="utf-8")
        staged.rename(destination)
    return destination


def worker_generate(root: Path, row: dict) -> int:
    from scripts.sni_guardrail_ablation_support import without_report_guardrails

    directory = Path(row["data_dir"])
    source = Path(read_json(root / "experiment_manifest.json")["frozen"]["source"])
    pair = {"pair_id": row["pair_id"], **API, "rag_backend_port": 4000, "condition_order": ["SNI"]}
    started = time.monotonic()
    disabled = {"status": "disabled", "reason": "guardrail_ablation", "validation_performed": False}

    def stage_runner(data_dir: Path, env: dict) -> int:
        write_json(data_dir / "parts_guardrail_result.json", disabled)
        write_json(data_dir / "guardrail_ablation.json", {
            "started_at": now(), "report_guardrails": "disabled",
            "sni": env["DEEP_INTERPRETER_USE_WIKI_CONTEXT"],
            "inline_evidence_checks": "unchanged", "save_recovery": "unchanged",
            "posthoc_evaluation": "separate_copy_only",
        })
        return baseline._default_stage_runner(data_dir, env)

    with without_report_guardrails():
        code = baseline.run_condition(
            source=source, output_root=directory.parents[1], pair=pair,
            condition=baseline.CONDITION_BY_LABEL["SNI"], stage_runner=stage_runner,
            collection_snapshot=baseline._default_collection_snapshot, collection_pmids=baseline._collection_pmids,
            validate_report_guardrails=False,
        )
    manifest = read_json(directory / "run_manifest.json")
    manifest["report_guardrails"] = disabled
    manifest["status_semantics"] = "generation and input/RAG integrity only; primary endpoint requires separate posthoc evaluation"
    for counts in manifest["metrics"]["artifacts"].values():
        counts["initial_error_count"] = None
        counts["final_error_count"] = None
    write_json(directory / "run_manifest.json", manifest)
    write_json(directory / "ablation_generation.json", {
        "guardrails": "disabled", "sni": True, "return_code": code,
        "generation_seconds": time.monotonic() - started, "generation_tokens": None,
        "report_hashes": report_hashes(directory), "error": manifest.get("error"),
    })
    return code


def worker_evaluate(root: Path, row: dict) -> int:
    from scripts.sni_guardrail_ablation_support import evaluate_report

    source = Path(row["data_dir"])
    destination = root / "evaluation" / f"pair-{row['pair_id']}-{row['sequence']}" / row["arm"]
    original_hashes = report_hashes(source)
    if destination.exists():
        directory = destination
    elif source.is_dir():
        directory = prepare_evaluation_copy(source, destination)
    else:
        destination.mkdir(parents=True)
        directory = destination
    if report_hashes(directory) != original_hashes:
        raise RuntimeError("evaluation copy differs from original reports")
    env = baseline._condition_env(directory, API, baseline.CONDITION_BY_LABEL["SNI"])

    def evaluate() -> int:
        baseline._bind_read_only_collection(directory)
        result = evaluate_report(directory, provider="ollama")
        if report_hashes(source) != original_hashes:
            raise RuntimeError("original generation reports changed during evaluation")
        result["original_report_hashes"] = original_hashes
        result["evaluation_tokens"] = None
        write_json(destination.parent / f"{row['arm']}.json", result)
        return 0

    return baseline._with_env(env, evaluate)


def run_worker(root: Path, state: dict, row: dict, mode: str) -> int:
    frozen = read_json(root / "experiment_manifest.json")
    source = Path(frozen["frozen"]["source"])
    verify_frozen_inputs(frozen["cohort"], source=source, code_ref=frozen["frozen"]["code_head"])
    for relative, digest in frozen["adapter_sha256"].items():
        if baseline.sha256(REPO_ROOT / relative) != digest:
            raise RuntimeError(f"experiment implementation changed: {relative}")
    log = root / "logs" / f"{row['index']:02d}-{row['arm']}-{mode}.log"
    log.parent.mkdir(exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), mode,
                                    "--root", str(root), "--row", str(state["runs"].index(row))],
                                   cwd=REPO_ROOT, stdout=stream, stderr=subprocess.STDOUT)
        state["current"] = {"pair_id": row["pair_id"], "sequence": row["sequence"], "arm": row["arm"], "mode": mode, "pid": process.pid, "log": str(log)}
        persist(root, state)
        label = f"pair-{row['pair_id']} {row['sequence']} {row['arm'].upper()} {mode}"
        print(f"[{now()}] Started {label}; pid={process.pid}; log={log}", flush=True)
        return_code = process.wait()
        verify_frozen_inputs(frozen["cohort"], source=source, code_ref=frozen["frozen"]["code_head"])
        print(f"[{now()}] Finished {label}; exit={return_code}", flush=True)
        return return_code


def generation_failure(directory: Path) -> str:
    manifest_path = directory / "run_manifest.json"
    text = json.dumps(read_json(manifest_path).get("error")) if manifest_path.exists() else ""
    for log in (directory / "logs").glob("*.stderr.log"):
        text += log.read_text(encoding="utf-8", errors="replace")
    text = text.lower()
    if any(word in text for word in ("timeout", "timed out")):
        return "timeout"
    if any(word in text for word in ("connection refused", "connecterror", "connection reset", "network is unreachable")):
        return "infrastructure"
    return "execution_error"


def run_queue(root: Path) -> int:
    with (root / "queue.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = read_json(root / "experiment_manifest.json")
        source = Path(manifest["frozen"]["source"])
        verify_frozen_inputs(manifest["cohort"], source=source, code_ref=manifest["frozen"]["code_head"])
        if source_hashes(source) != manifest["frozen"]["input_sha256"]:
            raise RuntimeError("source changed since preparation")
        for relative, digest in manifest["adapter_sha256"].items():
            if baseline.sha256(REPO_ROOT / relative) != digest:
                raise RuntimeError(f"experiment implementation changed since preparation: {relative}")
        state = read_json(root / "status.json")
        state.update({"status": "running", "queue_pid": os.getpid(), "started_at": state.get("started_at", now())})
        persist(root, state)
        try:
            for index in range(20):
                off = next(r for r in state["runs"] if r["index"] == index and r["arm"] == "off")
                if off["generation_status"] == "running":
                    raise RuntimeError("interrupted generation requires explicit reconciliation; refusing to replace first attempt")
                if generation_pending(off):
                    if service_preflight(source)["models"] != manifest["preflight"]["models"]:
                        raise RuntimeError("model digest changed since preparation")
                    off["generation_status"] = "running"
                    persist(root, state)
                    started = time.monotonic()
                    code = run_worker(root, state, off, "_generate")
                    off["generation_seconds"] = time.monotonic() - started
                    off["generation_status"] = "passed" if code == 0 else "failed"
                    off["report_complete"] = reports_complete(Path(off["data_dir"]))
                    if code:
                        off["failure_reason"] = generation_failure(Path(off["data_dir"]))
                    persist(root, state)
                for row in (r for r in state["runs"] if r["index"] == index):
                    if "evaluation" in row:
                        continue
                    if service_preflight(source)["models"] != manifest["preflight"]["models"]:
                        raise RuntimeError("model digest changed since preparation")
                    code = run_worker(root, state, row, "_evaluate")
                    result_path = root / "evaluation" / f"pair-{row['pair_id']}-{row['sequence']}" / f"{row['arm']}.json"
                    row["evaluation"] = read_json(result_path) if code == 0 and result_path.exists() else {
                        "status": "evaluation_failed", "usable": None, "complete": None, "hard_error_count": None,
                    }
                    if row["evaluation"].get("usable") is False and not row.get("failure_reason"):
                        row["failure_reason"] = "quality_failure" if row["evaluation"].get("complete") else "incomplete_report"
                    persist(root, state)
            state["status"] = "complete" if all(r.get("evaluation", {}).get("usable") is not None for r in state["runs"]) else "complete_with_evaluation_unknown"
            state.pop("current", None)
            state["finished_at"] = now()
            persist(root, state)
            return 0 if state["status"] == "complete" else 2
        except BaseException as exc:
            state["status"] = "paused"
            state["pause_reason"] = f"{type(exc).__name__}: {exc}"
            persist(root, state)
            raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "run", "summarize", "_generate", "_evaluate"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--row", type=int)
    parser.add_argument("--source", type=Path, help="BC input directory (prepare only; persisted for workers)")
    parser.add_argument("--archive", type=Path, help="Historical control archive (prepare only)")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    if args.mode == "prepare":
        prepare(root, source=(args.source or SOURCE).expanduser().resolve(),
                archive=(args.archive or ARCHIVE).expanduser().resolve())
        print(root)
        return 0
    if args.source is not None or args.archive is not None:
        parser.error("--source and --archive are preparation options; later commands use the manifest")
    if args.mode == "run":
        return run_queue(root)
    state = read_json(root / "status.json")
    if args.mode == "summarize":
        persist(root, state)
        print(json.dumps(state["summary"], indent=2))
        return 0
    if args.row is None:
        parser.error("--row is required for internal worker commands")
    row = state["runs"][args.row]
    return worker_generate(root, row) if args.mode == "_generate" else worker_evaluate(root, row)


if __name__ == "__main__":
    raise SystemExit(main())

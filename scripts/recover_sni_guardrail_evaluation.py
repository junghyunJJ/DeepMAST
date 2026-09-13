"""Recover common post-hoc checks without changing any generated report."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import HumanMessage

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts import run_sni_guardrail_ablation as experiment
from scripts import sni_guardrail_ablation_support as support
from scripts import validate_report
from src.agents.deep_interpreter import claim_rag_validation as claims
from src.agents.deep_interpreter import report_guardrails, synthesis_consistency_validation

NON_CONTENT_ERRORS = {
    "claim_evaluation_incomplete", "evaluation_failed", "report_mutated_by_evaluation",
    "missing_required_artifact",
}


def invoke_json_judgment(model, group: dict, *, timeout_seconds: float | None = None):
    """Recover malformed tool encoding using the same judgment schema and rubric."""
    schema = json.dumps(claims.ClaimJudgmentBatch.model_json_schema())
    prompt = claims._judgment_prompt(group) + (
        "\nReturn only a JSON object matching this schema. "
        "Do not use Markdown fences or text outside the JSON:\n" + schema
    )
    structured = model.with_structured_output(claims.ClaimJudgmentBatch, method="json_schema", include_raw=True)
    response = claims.run_async(structured.ainvoke([HumanMessage(content=prompt)]), timeout=timeout_seconds)
    reason = response["raw"].response_metadata.get("done_reason")
    if response["parsed"] is None or reason == "length":
        raise RuntimeError(f"Incomplete JSON judgment: finish={reason}; parsing_error={response.get('parsing_error')}")
    return response["parsed"].judgments


@contextlib.contextmanager
def stable_judge_loop(diagnostics: Path | None = None):
    """Keep the loop alive as long as the reused Ollama async client."""
    original_invoke = claims._invoke_judgment
    encoding_failures = set()
    if diagnostics is not None and diagnostics.exists():
        for line in diagnostics.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("action") == "json_schema_retry" or (
                record.get("type") == "AttributeError" and "judgments" in record.get("message", "")
            ):
                encoding_failures.add(json.dumps(record["group"], sort_keys=True))
    with asyncio.Runner() as runner:
        def run(coro, timeout=60):
            async def wait():
                return await asyncio.wait_for(coro, timeout=timeout)
            return runner.run(wait())

        def invoke(model, group, **kwargs):
            started = time.monotonic()
            key = json.dumps(group, sort_keys=True)
            try:
                if key in encoding_failures:
                    return invoke_json_judgment(model, group, **kwargs)
                return original_invoke(model, group, **kwargs)
            except Exception as exc:
                encoding_error = (
                    isinstance(exc, AttributeError) and "NoneType" in str(exc) and "judgments" in str(exc)
                ) or "XML syntax error" in str(exc)
                if diagnostics is not None:
                    with diagnostics.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps({
                            "time": experiment.now(), "type": type(exc).__name__,
                            "message": str(exc), "traceback": traceback.format_exc(), "group": group,
                            "action": "json_schema_retry" if encoding_error else "propagate",
                        }) + "\n")
                if encoding_error:
                    encoding_failures.add(key)
                    timeout = kwargs.get("timeout_seconds")
                    remaining = None if timeout is None else timeout - (time.monotonic() - started)
                    if remaining is not None and remaining <= 0:
                        raise TimeoutError("Claim judgment deadline exhausted before encoding recovery") from exc
                    return invoke_json_judgment(model, group, timeout_seconds=remaining)
                raise

        with (
            patch.object(claims, "run_async", run),
            patch.object(claims, "_invoke_judgment", invoke),
            patch.object(claims, "_write_checkpoint", experiment.write_json),
        ):
            yield


def content_errors(issues: list[dict]) -> list[dict]:
    return [issue for issue in issues if issue.get("severity") == "error" and issue.get("code") not in NON_CONTENT_ERRORS]


def resolve_outcome(result: dict) -> dict:
    """A known content error fails the endpoint even if other checks are pending."""
    result = dict(result)
    issues = result.get("issues", [])
    errors = content_errors(issues)
    operational = [i for i in issues if i.get("code") in NON_CONTENT_ERRORS - {"missing_required_artifact"}]
    complete_evaluation = result.get("evaluation_complete", result.get("status") == "evaluated") and not operational
    if any(i.get("code") == "report_mutated_by_evaluation" for i in issues):
        usable = None
    elif not result.get("complete"):
        usable = False
    elif errors:
        usable = False
    elif complete_evaluation:
        usable = True
    else:
        usable = None
    result.update({"usable": usable, "hard_error_count": len(errors) if errors or complete_evaluation else None,
                   "evaluation_complete": bool(complete_evaluation), "hard_error_count_complete": bool(complete_evaluation)})
    return result


def deterministic_result(directory: Path) -> dict:
    hashes = experiment.report_hashes(directory)
    missing = support._missing_or_empty(directory)
    if missing:
        return resolve_outcome({"status": "incomplete", "complete": False, "issues": [
            {"severity": "error", "code": "missing_required_artifact", "file": name} for name in missing
        ], "evaluation_complete": False, "hashes_before": hashes, "hashes_after": hashes})
    issues = validate_report.validate_report(directory)
    issues += report_guardrails.validate_synthesis_report(directory)
    issues += synthesis_consistency_validation.validate_synthesis_consistency(directory)["issues"]
    return resolve_outcome({"status": "deterministic_only", "complete": True,
                            "issues": issues, "evaluation_complete": False,
                            "phases": {"parts": "deterministic", "synthesis": "deterministic"},
                            "hashes_before": hashes, "hashes_after": experiment.report_hashes(directory)})


def generation_classification(row: dict) -> str:
    directory = Path(row["data_dir"])
    manifest = experiment.read_json(directory / "run_manifest.json")
    stages = experiment.read_json(directory / "timing.json").get("stages", [])
    if experiment.reports_complete(directory) and len(stages) == 4 and all(s["return_code"] == 0 for s in stages):
        return "completed"
    final = directory / "report_validation_final.json"
    if not experiment.reports_complete(directory) and final.exists() and content_errors(experiment.read_json(final).get("issues", [])):
        return "guardrail_blocked"
    return manifest.get("return_status", "execution_error")


def prepare_copy(row: dict, output: Path, original: Path) -> Path:
    source = Path(row["data_dir"])
    destination = output / "work" / f"pair-{row['pair_id']}-{row['sequence']}" / row["arm"]
    if not destination.exists():
        experiment.prepare_evaluation_copy(source, destination)
        old_checkpoint = original / "evaluation" / f"pair-{row['pair_id']}-{row['sequence']}" / row["arm"] / "claim_rag_checkpoint.json"
        if old_checkpoint.exists():
            # Only reuse content-addressed checks from the SAME common post-hoc policy.
            raw_checkpoint = old_checkpoint.read_bytes()
            checkpoint = json.loads(raw_checkpoint)
            experiment.write_json(destination / "claim_rag_checkpoint.json", checkpoint)
            experiment.write_json(destination / "checkpoint_origin.json", {
                "path": str(old_checkpoint), "sha256": hashlib.sha256(raw_checkpoint).hexdigest(),
                "source": "common_posthoc_evaluation_only",
            })
    if experiment.report_hashes(destination) != row["original_report_hashes"]:
        raise RuntimeError(f"evaluation copy differs from frozen report: {destination}")
    return destination


def assess_row(row: dict, output: Path, original: Path) -> dict:
    started = time.monotonic()
    source = Path(row["data_dir"])
    if experiment.report_hashes(source) != row["original_report_hashes"]:
        raise RuntimeError(f"original report changed: {source}")
    directory = prepare_copy(row, output, original)
    result = deterministic_result(directory)
    result["deterministic_issues"] = list(result["issues"])
    if result["usable"] is None:
        env = experiment.baseline._condition_env(directory, experiment.API, experiment.baseline.CONDITION_BY_LABEL["SNI"])
        env.update({"LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"})

        def evaluate():
            experiment.baseline._bind_read_only_collection(directory)
            with stable_judge_loop(directory / "judge_errors.jsonl"):
                return resolve_outcome(support.evaluate_report(directory, provider="ollama"))

        common = experiment.baseline._with_env(env, evaluate)
        common["deterministic_issues"] = result["deterministic_issues"]
        result = common
    if experiment.report_hashes(source) != row["original_report_hashes"] or experiment.report_hashes(directory) != row["original_report_hashes"]:
        raise RuntimeError(f"report bytes changed during recovery: {source}")
    result.update({"elapsed_seconds": time.monotonic() - started,
                   "original_report_hashes": row["original_report_hashes"], "working_copy": str(directory)})
    return result


def result_path(output: Path, row: dict) -> Path:
    return output / "assessments" / f"pair-{row['pair_id']}-{row['sequence']}-{row['arm']}.json"


def prepare(original: Path, output: Path) -> list[dict]:
    state = experiment.read_json(original / "status.json")
    if sum(r["arm"] == "off" and r.get("report_complete") is True for r in state["runs"]) != 20:
        raise RuntimeError("all 20 OFF reports must finish generation before recovery")
    rows = []
    for row in state["runs"]:
        row = {k: v for k, v in row.items() if k != "evaluation"}
        row["original_report_hashes"] = experiment.report_hashes(Path(row["data_dir"]))
        generation_record = Path(row["data_dir"]) / "ablation_generation.json"
        if row["arm"] == "off" and experiment.read_json(generation_record)["report_hashes"] != row["original_report_hashes"]:
            raise RuntimeError(f"OFF report changed after generation: {generation_record}")
        row["generation_classification"] = generation_classification(row)
        manifest = experiment.read_json(Path(row["data_dir"]) / "run_manifest.json")
        row["generation_audit_error"] = manifest.get("error")
        rows.append(row)
    output.mkdir(parents=True, exist_ok=False)
    experiment.write_json(output / "manifest.json", {
        "created_at": experiment.now(), "original_experiment": str(original), "rows": rows,
        "policy": "report complete and common-policy hard errors zero; known hard error fails despite incomplete other checks",
        "transport_fix": "reuse one asyncio.Runner across each report's async judge client requests",
        "root_cause": "reproduced Event loop is closed on second call with reused Ollama async client",
        "encoding_recovery": "retry malformed/empty tool responses with native JSON schema and explicit serialization instructions; same model/rubric/evidence and original deadlines",
        "reuse": "content-addressed successful common-posthoc checks only; never generation guardrail verdicts",
        "historical_model_digest": None,
    })
    return rows


def run(original: Path, output: Path, limit: int | None = None) -> int:
    from scripts.summarize_sni_guardrail_recovery import write_comparison

    manifest_path = output / "manifest.json"
    rows = experiment.read_json(manifest_path)["rows"] if manifest_path.exists() else prepare(original, output)
    frozen = experiment.read_json(original / "experiment_manifest.json")
    experiment.verify_frozen_inputs(frozen["cohort"])
    if experiment.service_preflight()["models"] != frozen["preflight"]["models"]:
        raise RuntimeError("model weights changed since generation")
    for row in rows:
        if experiment.report_hashes(Path(row["data_dir"])) != row["original_report_hashes"]:
            raise RuntimeError(f"original report changed since recovery preparation: {row['data_dir']}")
        path = result_path(output, row)
        if path.exists():
            row["evaluation"] = experiment.read_json(path)
            copied = row["evaluation"].get("working_copy")
            if copied and experiment.report_hashes(Path(copied)) != row["original_report_hashes"]:
                raise RuntimeError(f"completed evaluation copy changed: {copied}")
    write_comparison(output, rows)
    completed_this_run = 0
    for row in rows:
        if "evaluation" in row and row["evaluation"].get("usable") is not None:
            continue
        label = f"Pair {row['pair_id']} {row['sequence']} {row['arm'].upper()}"
        print(f"[{experiment.now()}] Evaluating {label}", flush=True)
        experiment.write_json(output / "status.json", {"status": "running", "current": label, "updated_at": experiment.now(), "pid": os.getpid()})
        attempt_records = row.get("evaluation", {}).get("recovery_attempts", [])
        for attempt in range(3):
            if experiment.service_preflight()["models"] != frozen["preflight"]["models"]:
                raise RuntimeError("model weights changed before evaluation attempt")
            result = assess_row(row, output, original)
            attempt_records.append({"status": result["status"], "usable": result["usable"], "elapsed_seconds": result["elapsed_seconds"]})
            result["recovery_attempts"] = attempt_records
            result["elapsed_seconds"] = sum(record["elapsed_seconds"] for record in attempt_records)
            experiment.write_json(result_path(output, row), result)
            if result["usable"] is not None:
                break
            print(f"[{experiment.now()}] Incomplete evaluation for {label}; retrying only missing cached checks ({attempt+1}/3)", flush=True)
        row["evaluation"] = result
        write_comparison(output, rows)
        print(f"[{experiment.now()}] {label}: usable={result['usable']}, hard_errors={result['hard_error_count']}, fully_evaluated={result['evaluation_complete']}", flush=True)
        completed_this_run += 1
        if limit is not None and completed_this_run >= limit:
            break
    unknown = 40 - sum(r.get("evaluation", {}).get("usable") is not None for r in rows)
    status = "complete" if unknown == 0 else "incomplete"
    experiment.write_json(output / "status.json", {"status": status, "primary_outcomes_resolved": 40-unknown,
                         "primary_outcomes_unknown": unknown, "updated_at": experiment.now(), "pid": os.getpid()})
    return 0 if unknown == 0 else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, default=experiment.ARCHIVE / "guardrail_on_off_20260905T154030Z")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    return run(args.experiment.resolve(), args.output.resolve(), args.limit)


if __name__ == "__main__":
    raise SystemExit(main())

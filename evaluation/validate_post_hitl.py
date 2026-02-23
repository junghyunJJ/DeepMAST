"""Validate Post-HITL evaluation records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


_TOP_REQUIRED = {
    "schema_version",
    "run_meta",
    "hitl_context",
    "artifacts",
    "gold_binding",
    "predicted_claims",
    "matching",
    "scores",
    "eval_status",
}
_PARTS = {"part1", "part2", "part3"}
_CLAIM_TYPES = {"spatial", "pathway", "mechanism", "lr"}
_MATCH_STATUS = {"TP", "FP", "FN"}
_PMID_ALIGNMENT = {"strong", "weak", "unsupported"}
_EVAL_STATUS = {"ok", "invalid_precondition", "parse_failed"}


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _score_in_01(value: Any) -> bool:
    return isinstance(value, (int, float)) and 0.0 <= float(value) <= 1.0


def _require_dict(data: dict[str, Any], key: str, errors: list[str]) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        errors.append(f"Missing required dict '{key}'")
        return {}
    return value


def _require_list(data: dict[str, Any], key: str, errors: list[str]) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        errors.append(f"Missing required list '{key}'")
        return []
    return value


def validate_post_hitl_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["Payload root must be a JSON object."]

    missing = sorted(_TOP_REQUIRED - set(payload.keys()))
    if missing:
        errors.append(f"Missing top-level fields: {missing}")
        return errors

    if payload.get("schema_version") != "post_hitl_eval_v1":
        errors.append("schema_version must be 'post_hitl_eval_v1'.")

    run_meta = _require_dict(payload, "run_meta", errors)
    for key in (
        "run_id",
        "dataset_id",
        "agent_git_sha",
        "llm_provider",
        "llm_model",
        "started_at",
        "finished_at",
    ):
        if not _is_nonempty_str(run_meta.get(key)):
            errors.append(f"run_meta.{key} must be a non-empty string.")

    hitl = _require_dict(payload, "hitl_context", errors)
    if not isinstance(hitl.get("hitl_completed"), bool):
        errors.append("hitl_context.hitl_completed must be boolean.")
    if not isinstance(hitl.get("interpretation_approved"), bool):
        errors.append("hitl_context.interpretation_approved must be boolean.")
    if not isinstance(hitl.get("interest_clusters"), list):
        errors.append("hitl_context.interest_clusters must be a list.")
    if not isinstance(hitl.get("interest_celltypes"), list):
        errors.append("hitl_context.interest_celltypes must be a list.")
    if not _is_nonempty_str(hitl.get("sel_factor")):
        errors.append("hitl_context.sel_factor must be a non-empty string.")
    if not _is_nonempty_str(hitl.get("hitl_packet_hash")):
        errors.append("hitl_context.hitl_packet_hash must be a non-empty string.")

    artifacts = _require_dict(payload, "artifacts", errors)
    for key in (
        "part1_final",
        "part2_final",
        "part3_final",
        "part1_papers",
        "part23_papers",
        "final_report",
    ):
        if not _is_nonempty_str(artifacts.get(key)):
            errors.append(f"artifacts.{key} must be a non-empty string.")

    gold = _require_dict(payload, "gold_binding", errors)
    for key in ("gold_version", "alignment_profile", "evidence_file"):
        if not _is_nonempty_str(gold.get(key)):
            errors.append(f"gold_binding.{key} must be a non-empty string.")

    pred_claims = _require_list(payload, "predicted_claims", errors)
    for i, claim in enumerate(pred_claims):
        if not isinstance(claim, dict):
            errors.append(f"predicted_claims[{i}] must be an object.")
            continue
        if not _is_nonempty_str(claim.get("pred_id")):
            errors.append(f"predicted_claims[{i}].pred_id must be non-empty string.")
        if claim.get("part") not in _PARTS:
            errors.append(f"predicted_claims[{i}].part must be one of {_PARTS}.")
        if claim.get("claim_type") not in _CLAIM_TYPES:
            errors.append(
                f"predicted_claims[{i}].claim_type must be one of {_CLAIM_TYPES}."
            )
        if not _is_nonempty_str(claim.get("claim_text")):
            errors.append(f"predicted_claims[{i}].claim_text must be non-empty string.")
        if not isinstance(claim.get("entities"), list):
            errors.append(f"predicted_claims[{i}].entities must be a list.")
        if not _is_nonempty_str(claim.get("direction")):
            errors.append(f"predicted_claims[{i}].direction must be non-empty string.")
        if not isinstance(claim.get("cited_pmids"), list):
            errors.append(f"predicted_claims[{i}].cited_pmids must be a list.")
        if not isinstance(claim.get("novelty_flag"), bool):
            errors.append(f"predicted_claims[{i}].novelty_flag must be boolean.")

    matching = _require_list(payload, "matching", errors)
    for i, row in enumerate(matching):
        if not isinstance(row, dict):
            errors.append(f"matching[{i}] must be an object.")
            continue
        if not _is_nonempty_str(row.get("pred_id")):
            errors.append(f"matching[{i}].pred_id must be non-empty string.")
        gold_claim_id = row.get("gold_claim_id")
        if gold_claim_id is not None and not _is_nonempty_str(gold_claim_id):
            errors.append(
                f"matching[{i}].gold_claim_id must be null or non-empty string."
            )
        if row.get("status") not in _MATCH_STATUS:
            errors.append(f"matching[{i}].status must be one of {_MATCH_STATUS}.")
        if not _score_in_01(row.get("entity_overlap")):
            errors.append(f"matching[{i}].entity_overlap must be between 0 and 1.")
        if not isinstance(row.get("direction_match"), bool):
            errors.append(f"matching[{i}].direction_match must be boolean.")
        if row.get("pmid_alignment") not in _PMID_ALIGNMENT:
            errors.append(
                f"matching[{i}].pmid_alignment must be one of {_PMID_ALIGNMENT}."
            )

    scores = _require_dict(payload, "scores", errors)
    for part in ("part1", "part2", "part3"):
        s = scores.get(part)
        if not isinstance(s, dict):
            errors.append(f"scores.{part} must be an object.")
            continue
        for metric in ("precision", "recall", "f1"):
            if not _score_in_01(s.get(metric)):
                errors.append(f"scores.{part}.{metric} must be between 0 and 1.")

    overall = scores.get("overall")
    if not isinstance(overall, dict):
        errors.append("scores.overall must be an object.")
    else:
        for metric in (
            "precision",
            "recall",
            "f1",
            "grounding_validity",
            "strong_alignment_rate",
            "hallucination_rate",
        ):
            if not _score_in_01(overall.get(metric)):
                errors.append(f"scores.overall.{metric} must be between 0 and 1.")

    eval_status = payload.get("eval_status")
    if eval_status not in _EVAL_STATUS:
        errors.append(f"eval_status must be one of {_EVAL_STATUS}.")

    # Post-HITL precondition: if HITL is incomplete or interpretation is not approved,
    # status cannot be "ok".
    if (
        eval_status == "ok"
        and (not hitl.get("hitl_completed") or not hitl.get("interpretation_approved"))
    ):
        errors.append(
            "Post-HITL precondition failed: eval_status='ok' requires "
            "hitl_completed=true and interpretation_approved=true."
        )

    return errors


def _load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be object: {path}")
    return payload


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate Post-HITL evaluation JSON")
    parser.add_argument("--input", required=True, help="Path to post-HITL evaluation JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        payload = _load_json(args.input)
    except Exception as exc:
        print(f"Validation failed:\n- Could not read JSON: {exc}")
        return 1

    errors = validate_post_hitl_payload(payload)
    if errors:
        print("Validation failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print("Validation passed: post-HITL payload is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

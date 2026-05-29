"""Shared narrow-retry instruction for hypothesis generation recovery."""

from __future__ import annotations

import json
from pathlib import Path


def _numeric_prediction_guidance(errors: list[dict] | None) -> str:
    if not errors:
        return ""
    codes = {str(err.get("code") or "") for err in errors if isinstance(err, dict)}
    if "UNVERIFIED_NUMERIC_PREDICTION" not in codes:
        return ""
    return (
        " Specific fix for UNVERIFIED_NUMERIC_PREDICTION: remove unsupported "
        "percentages, fold changes, p-values, thresholds, and numeric effect "
        "sizes from falsifiable_prediction and validation_approach unless the "
        "same numeric value is directly present in a cited evidence file. If no "
        "direct evidence supports the number, rewrite the prediction "
        "qualitatively, for example 'will reduce disease-relevant marker "
        "expression compared with matched controls'. Do not copy failed numeric "
        "predictions from the existing invalid hypothesis_report.json."
    )


def _format_quality_errors_for_instruction(quality_errors: list[dict] | None) -> str:
    if not quality_errors:
        return ""
    parts: list[str] = []
    for err in quality_errors:
        if not isinstance(err, dict):
            continue
        code = str(err.get("code") or "UNKNOWN")
        message = str(err.get("message") or "")
        details = err.get("details")
        detail_text = f" details={details!r}" if details else ""
        parts.append(f"{code}: {message}{detail_text}")
    if not parts:
        return ""
    return (
        " Quality validation failures to fix before saving: "
        + "; ".join(parts)
        + _numeric_prediction_guidance(quality_errors)
    )


def build_hypothesis_retry_message(
    data_dir: str | Path,
    disease: str,
    quality_errors: list[dict] | None = None,
    *,
    attempt: int | None = None,
    max_attempts: int | None = None,
) -> str:
    """Build an orchestrator instruction that reruns only hypothesis_writer."""
    instruction_feedback = _format_quality_errors_for_instruction(quality_errors)
    attempt_text = ""
    if attempt is not None and max_attempts is not None:
        attempt_text = f" Retry attempt {attempt} of {max_attempts}."
    readable_feedback = ""
    if quality_errors:
        readable_feedback = (
            "\n\nFor auditability, the quality validation failures were:\n"
            f"{json.dumps(quality_errors, indent=2, ensure_ascii=False)}"
        )

    return (
        "The previous run completed Stage 1-3 evidence collection "
        "but hypothesis_report.json was NOT saved, is stale, or failed "
        "quality validation. You MUST now invoke ONLY the hypothesis_writer "
        "subagent to recover hypothesis generation. Do not re-run evidence_assessor "
        "or deep_diver. Do not re-run report_writer or summarizer. Emit exactly "
        "one tool call:\n\n"
        f"  task(subagent_type=\"hypothesis_writer\", instruction=\""
        f"Recovery run for {disease}.{attempt_text} "
        f"load_evidence_files(data_dir='{data_dir}', "
        f"scope='hypothesis'), generate 4-6 mechanistic hypotheses across ALL "
        f"four mandatory categories: Mechanism of Action, Therapeutic Strategy, "
        f"Cross-Target Interaction, and Novel Pathway. Each category must appear "
        f"at least once in the retained hypotheses. Cover every FEATURED gene in "
        f"biological_entities.genes across the retained set. Call "
        f"validate_evidence_references with every filename you plan to cite, "
        f"then immediately call save_hypothesis_report(data_dir='{data_dir}', "
        f"report=<the JSON payload>). Do NOT call sequential_thinking more than "
        f"6 times. If sequential_thinking returns an error about a degenerate "
        f"loop, STOP thinking and call save_hypothesis_report immediately with "
        f"your best corrected draft.{instruction_feedback}\")"
        f"{readable_feedback}\n\n"
        "After the hypothesis_writer task returns, emit the message "
        "'Hypothesis fixup complete.' and stop."
    )

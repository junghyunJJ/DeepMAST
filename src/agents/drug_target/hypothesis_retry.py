"""Shared narrow-retry instruction for hypothesis generation recovery."""

from __future__ import annotations

import json
import re
from pathlib import Path


def _numeric_prediction_guidance(errors: list[dict] | None) -> str:
    if not errors:
        return ""
    codes = {str(err.get("code") or "") for err in errors if isinstance(err, dict)}
    text = _flatten_error_text(errors)
    numeric_summary_present = any(
        isinstance(err, dict)
        and isinstance(err.get("details"), dict)
        and isinstance(err["details"].get("prediction_grounding_summary"), dict)
        and (
            err["details"]["prediction_grounding_summary"].get("grounded", 0) > 0
            or err["details"]["prediction_grounding_summary"].get("unverified", 0) > 0
        )
        for err in errors
    )
    if (
        "UNVERIFIED_NUMERIC_PREDICTION" not in codes
        and "unverified numeric values" not in text
        and "non-evidence-derived numeric values" not in text
        and not numeric_summary_present
    ):
        return ""
    return (
        " Specific fix for UNVERIFIED_NUMERIC_PREDICTION: remove unsupported "
        "numeric predicted effects, including unsupported percentages, fold changes, "
        "p-values, and effect-size thresholds, from falsifiable_prediction and "
        "from predictive claims in validation_approach unless the same numeric "
        "value is directly present in a cited evidence file. If no direct "
        "evidence supports the number, rewrite the prediction qualitatively, "
        "for example 'test whether the perturbation changes disease-relevant "
        "marker expression compared with matched controls'. Do not remove "
        "legitimate protocol or control details from validation_approach, such "
        "as doses, timepoints, sample sizes, assay thresholds, or control group "
        "definitions, when they are framed as experimental design rather than "
        "predicted effects. Non-evidence-derived effect-size thresholds may "
        "appear in experimental protocol outside falsifiable_prediction as "
        "success criteria or assay design, but not as predicted effects from "
        "Stage 1, Spatial, OpenTargets, or ChEMBL evidence. Do not copy failed "
        "numeric predictions from the existing invalid hypothesis_report.json."
    )


def _flatten_error_text(errors: list[dict] | None) -> str:
    chunks: list[str] = []
    for err in errors or []:
        if not isinstance(err, dict):
            continue
        chunks.append(str(err.get("code") or ""))
        chunks.append(str(err.get("message") or ""))
        details = err.get("details")
        if isinstance(details, dict):
            detail_errors = details.get("errors")
            if isinstance(detail_errors, list):
                chunks.extend(str(item) for item in detail_errors)
            grounding = details.get("hypothesis_grounding_violations")
            if isinstance(grounding, list):
                chunks.extend(str(item) for item in grounding)
    return "\n".join(chunk for chunk in chunks if chunk)


def _last_rejection_guidance(errors: list[dict] | None) -> str:
    text = _flatten_error_text(errors)
    if "HYPOTHESIS_LAST_SAVE_REJECTION" not in text:
        return ""
    return (
        " Last rejected save attempt details are authoritative. Repair those "
        "exact errors before trying to save again; do not repeat the same payload."
    )


def _direct_pair_axis_guidance(errors: list[dict] | None) -> str:
    text = _flatten_error_text(errors)
    if "claims direct pair axis" not in text:
        return ""
    available_files = sorted(
        set(
            re.findall(
                r"available:[^.;]*?(stage1_[A-Za-z0-9-]+--[A-Za-z0-9-]+\.json)",
                text,
            )
        )
    )
    available_text = ""
    if available_files:
        available_text = (
            " When the rejection names an available matching file, cite that exact "
            f"filename in evidence_references ({', '.join(available_files)}) or "
            "remove the direct pair-axis wording."
        )
    return (
        " Direct pair-axis repair: Do not invent a direct pair axis from separate "
        "hub-partner evidence. Use `A--B axis`, `A-B axis`, direct interaction, "
        "or paired readout wording only when a matching passed `stage1_A--B.json` "
        "or `stage1_B--A.json` exists and is cited. The two filename orders are "
        "equivalent for direct pair support only when the actual cited file is a "
        "passed Stage 1 file and is present in evidence_references."
        f"{available_text} Do not use synergy or "
        "synergistic effects unless direct combination evidence is cited; prefer "
        "`additive or non-additive effects`."
        f"{available_guidance} Otherwise rewrite as co-observed "
        "genes, convergent programs, or separate follow-up recommendations."
    )


def _featured_gene_reference_guidance(errors: list[dict] | None) -> str:
    text = _flatten_error_text(errors)
    if "GENE_LEVEL_EVIDENCE_REFERENCE_MISSING" not in text:
        return ""
    return (
        " FEATURED gene reference repair: If a FEATURED gene is mentioned in title, "
        "core_claim, prediction, validation_approach, or biological_entities.genes, "
        "cite every available exact gene-level file reported by the error, such as "
        "`ot_<GENE>.json` and `stage3_<GENE>.json`. If you cannot cite those files, "
        "remove that gene from the hypothesis text and biological_entities.genes."
    )


def _depleted_stage1_guidance(errors: list[dict] | None) -> str:
    text = _flatten_error_text(errors)
    if (
        "target-cell-depleted Stage 1 Census evidence" not in text
        and "coexpression-depleted Stage 1 Census evidence" not in text
        and "target-cell-depleted gene expression claim" not in text
    ):
        return ""
    return (
        " Depleted Stage 1 repair: remove AT2, Transitional AT2, "
        "pulmonary/alveolar epithelial, resolved Census cell-type, "
        "epithelial-intrinsic, same-cell, and target-cell-autonomous wording "
        "from recommendations citing depleted Stage 1 files, use the depleted Stage 1 "
        "file only as secondary spatial-niche/cross-cell framing when the pair "
        "concept is named, and support target/actionability with exact "
        "stage3_<GENE>.json and ot_<GENE>.json citations. For a "
        "`target-cell-depleted Stage 1 Census evidence as interest-cell support` "
        "error, choose exactly one repair path for the named hypothesis: "
        "(A) keep the depleted Stage 1 pair file only after rewriting the title, "
        "core_claim, prediction, validation_approach, and biological_entities.cell_types "
        "as secondary spatial-niche/cross-cell or non-interest-cell context; or "
        "(B) remove that Stage 1 pair citation entirely and rewrite the hypothesis "
        "as gene-level/actionability-only using available ot_<GENE>.json and "
        "stage3_<GENE>.json evidence. Do not leave the depleted Stage 1 file in a "
        "primary AT2/epithelial, interest-cell, same-cell, or intrinsic recommendation."
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
        + _last_rejection_guidance(quality_errors)
        + _direct_pair_axis_guidance(quality_errors)
        + _featured_gene_reference_guidance(quality_errors)
        + _depleted_stage1_guidance(quality_errors)
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
        "subagent to recover follow-up recommendation generation. Do not re-run evidence_assessor "
        "or deep_diver. Do not re-run report_writer or summarizer. Emit exactly "
        "one tool call:\n\n"
        f"  task(subagent_type=\"hypothesis_writer\", instruction=\""
        f"Recovery run for {disease}.{attempt_text} "
        f"load_evidence_files(data_dir='{data_dir}', "
        f"scope='hypothesis'), generate 4-6 evidence-grounded follow-up "
        f"recommendations across ALL "
        f"four mandatory categories: Mechanism of Action, Therapeutic Strategy, "
        f"Cross-Target Interaction, and Novel Pathway. Each category must appear "
        f"at least once in the retained recommendations. Cover every FEATURED gene in "
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

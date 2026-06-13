"""Shared narrow-retry instruction for hypothesis generation recovery."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_TOPN_MISSING_RE = re.compile(r"topn_missing\s*=\s*\[([^\]]*)\]", re.IGNORECASE)


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
    available_matches = sorted(
        set(re.findall(r"available:\s*([^.;]*stage1_[A-Za-z0-9-]+--[A-Za-z0-9-]+\.json[^.;]*)", text))
    )
    available_guidance = ""
    if available_matches:
        available_guidance = (
            " If the rejection names an available matching file, cite that exact "
            f"filename in the rejected hypothesis or remove the direct pair-axis wording; "
            f"available repair target(s): {'; '.join(available_matches)}."
        )
    return (
        " Direct pair-axis repair: Do not invent a direct pair axis from separate "
        "hub-partner evidence. Use `A--B axis`, `A-B axis`, direct interaction, "
        "or paired readout wording only when a matching passed `stage1_A--B.json` "
        "or `stage1_B--A.json` exists and is cited. The two filename orders are "
        "equivalent for direct pair support only when the cited file is a passed "
        "Stage 1 file present in evidence_references."
        f"{available_guidance} Do not use synergy or "
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


def _invalid_citation_guidance(errors: list[dict] | None) -> str:
    text = _flatten_error_text(errors)
    if (
        "which is not in evidence/ directory" not in text
        and "without proven passed=true status" not in text
    ):
        return ""
    missing_files = sorted(
        set(
            re.findall(
                r"'([^']+\.json)' which is not in evidence/ directory",
                text,
            )
        )
    )
    unpassed_pairs = sorted(
        set(
            re.findall(
                r"Stage 1 pair '([A-Za-z0-9-]+--[A-Za-z0-9-]+)' "
                r"without proven passed=true status",
                text,
            )
        )
    )
    details: list[str] = []
    if missing_files:
        details.append(f"fabricated or unavailable file(s): {', '.join(missing_files)}")
    if unpassed_pairs:
        details.append(f"unpassed Stage 1 pair(s): {', '.join(unpassed_pairs)}")
    detail_text = f" Specific rejected citations: {'; '.join(details)}." if details else ""
    return (
        " Invalid citation repair: before retrying, call `validate_evidence_references` "
        "with the combined flat list of all proposed evidence_references and repair every "
        "invalid reference. Use only exact filenames in `available_files`; use Stage 1 "
        "pair files only when they appear in `eligible_stage1_pair_files` or are otherwise "
        "confirmed passed=true. NEVER invent filenames, normalized pair directions, "
        "`stage3_<GENE>.json`, or `ot_<GENE>.json` files that are absent from evidence/."
        f"{detail_text}"
    )


def _extract_topn_missing_genes(text: str) -> list[str]:
    genes: list[str] = []
    for block in _TOPN_MISSING_RE.findall(text):
        genes.extend(re.findall(r"[A-Za-z][A-Za-z0-9_.-]*", block))
    return genes


def _collect_missing_gene_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _topn_missing_guidance(errors: list[dict] | None) -> str:
    genes = set(_extract_topn_missing_genes(_flatten_error_text(errors)))
    for err in errors or []:
        if not isinstance(err, dict):
            continue
        details = err.get("details")
        if not isinstance(details, dict):
            continue
        genes.update(_collect_missing_gene_strings(details.get("missing")))
        topn_coverage = details.get("topn_coverage")
        if isinstance(topn_coverage, dict):
            genes.update(_collect_missing_gene_strings(topn_coverage.get("missing")))

    if not genes:
        return ""

    joined = ", ".join(sorted(genes))
    return (
        " [FEATURED-GAP] Top-N coverage repair: the previous payload omitted "
        f"required top-ranked gene(s): {joined}. Do NOT retry the same payload. "
        "For each missing gene, add or repair a `[FEATURED-GAP]` hypothesis whose "
        "`biological_entities.genes` includes that gene and cite exact "
        "`stage3_<GENE>.json` and `ot_<GENE>.json` evidence when present. "
        "Do not remove other valid hypotheses just to satisfy top-N coverage."
    )


def _interest_cell_validation_guidance(errors: list[dict] | None) -> str:
    text = _flatten_error_text(errors)
    triggers = (
        "validation_approach does not mention the original interest label",
        "validation_approach does not test the original interest label",
        "biological_entities.cell_types does not include the original interest label",
        "lists interest/resolved cell type",
    )
    if not any(trigger in text for trigger in triggers):
        return ""
    stage1_refs = sorted(
        set(re.findall(r"stage1_[A-Za-z0-9-]+--[A-Za-z0-9-]+\.json", text))
    )
    refs_text = f" Affected Stage 1 file(s): {', '.join(stage1_refs)}." if stage1_refs else ""
    return (
        " Interest-cell validation repair: when a hypothesis cites target-cell-intrinsic "
        "Stage 1 evidence or lists an interest/resolved cell type, rewrite that named "
        "hypothesis so `biological_entities.cell_types` includes the original interest "
        "label or resolved Census cell type, and `validation_approach` explicitly names "
        "that cell context. For this breast-cancer semantic proxy context, use exact "
        "phrases such as `Prolif Invasive Tumor` or `malignant cell`; do not rely on "
        "generic disease, tumor, epithelial, or breast-cancer wording alone."
        f"{refs_text}"
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
        " Depleted Stage 1 repair: remove original interest label, resolved "
        "Census cell type such as malignant cell, legacy AT2, Transitional AT2, "
        "pulmonary/alveolar epithelial, "
        "epithelial-intrinsic, same-cell, and target-cell-autonomous wording "
        "from recommendations citing depleted Stage 1 files. A depleted Stage 1 "
        "file cannot support primary interest-cell intrinsic, legacy AT2/epithelial, "
        "same-cell, or target-cell-autonomous wording. For a "
        "`target-cell-depleted Stage 1 Census evidence as interest-cell support` "
        "error, choose exactly one repair path for the named hypothesis: "
        "(A) keep the depleted Stage 1 pair file only after rewriting the title, "
        "core_claim, prediction, validation_approach, and biological_entities.cell_types "
        "as secondary cross-cell or non-interest-cell context; use spatial-niche only "
        "if cited Stage 1 or spatial evidence directly supports spatial/niche context; "
        "or (B) remove that Stage 1 pair citation entirely and rewrite the hypothesis "
        "as gene-level/actionability-only using available ot_<GENE>.json and "
        "stage3_<GENE>.json evidence. Do not leave the depleted Stage 1 file in a "
        "primary interest-cell, legacy AT2/epithelial, same-cell, or intrinsic recommendation."
    )


def _legacy_at2_repair_guidance(errors: list[dict] | None) -> str:
    text = _flatten_error_text(errors).casefold()
    legacy_markers = (
        " at2",
        "transitional at2",
        "pulmonary alveolar type 2",
        "alveolar epithelial",
        "pulmonary epithelial",
    )
    if not any(marker in text for marker in legacy_markers):
        return ""
    if (
        "target-cell-depleted" not in text
        and "coexpression-depleted" not in text
        and "validation_approach does not" not in text
    ):
        return ""
    return (
        " Legacy AT2/Epithelial repair: preserve the Primary AT2/Epithelial branch "
        "only for hypotheses that cite non-depleted files from "
        "`interest_cell_intrinsic_stage1_pair_files`. For rejected hypotheses citing "
        "target-cell-depleted or coexpression-depleted Stage 1 files, remove "
        "AT2-intrinsic wording, remove AT2 validation language, or remove that Stage 1 "
        "citation and rebuild the hypothesis as gene-level/actionability-only with "
        "`stage3_<GENE>.json` and `ot_<GENE>.json`. Do not leave depleted Stage 1 "
        "files in a Primary AT2/Epithelial recommendation."
    )


def _semantic_proxy_repair_guidance(errors: list[dict] | None) -> str:
    text = _flatten_error_text(errors).casefold()
    if "malignant cell" not in text and "semantic_proxy" not in text:
        return ""
    return (
        " Semantic-proxy repair: for Prolif Invasive Tumor -> malignant cell or "
        "similar proxy contexts, validation_approach and biological_entities.cell_types "
        "must name the original interest label or the resolved Census proxy; generic "
        "tumor, breast-cancer, epithelial, or disease wording is not enough. If the "
        "rejected hypothesis cannot be repaired with exact cell-type wording, rewrite "
        "it as gene-level/actionability-only and remove interest-cell intrinsic claims."
    )


def _evidence_scope_guardrails() -> str:
    return (
        " Evidence scope guardrails: Every recommendation section must be written "
        "only from cited Evidence References. If no Stage 1 Census or spatial file "
        "is cited for a recommendation, do not call the recommendation "
        "spatial-niche, AT2/epithelial intrinsic, same-cell, interest-cell grounded, "
        "or resolved Census cell-type grounded; call it gene-level follow-up or "
        "actionability follow-up. If only one gene in a pair has ot_<GENE>.json or "
        "stage3_<GENE>.json evidence, state target-disease support or actionability "
        "only for that gene. Do not describe both genes as equally actionable unless "
        "both genes cite exact ot_<GENE>.json or stage3_<GENE>.json files. Prefer "
        "`perturbation/actionability follow-up candidate` over `therapeutic "
        "intervention candidate`. Prefer `additive or non-additive effects` over "
        "`synergistic effects` unless direct combination evidence is cited. For "
        "CD47 or other target perturbations, write `test whether perturbation "
        "changes cited cellular readouts`; do not state that perturbation alters "
        "fibrosis resolution unless a cited evidence file directly supports that "
        "claim."
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
        + _invalid_citation_guidance(quality_errors)
        + _interest_cell_validation_guidance(quality_errors)
        + _topn_missing_guidance(quality_errors)
        + _direct_pair_axis_guidance(quality_errors)
        + _featured_gene_reference_guidance(quality_errors)
        + _depleted_stage1_guidance(quality_errors)
        + _legacy_at2_repair_guidance(quality_errors)
        + _semantic_proxy_repair_guidance(quality_errors)
        + _evidence_scope_guardrails()
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

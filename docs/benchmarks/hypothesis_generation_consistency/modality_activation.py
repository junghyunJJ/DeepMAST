from __future__ import annotations

import json
from dataclasses import dataclass
from statistics import mean
from typing import Any, Sequence

from docs.benchmarks.hypothesis_generation_consistency.phase_activation import (
    DOMAIN_SKILL_UNIVERSE,
    EXPANDED6_SKILL_NAMES,
    model_slug,
    score_phase_activation,
)


@dataclass(frozen=True)
class ModalityActivationCase:
    case_id: str
    phase: str
    prompt: str
    expected_domain_skills: tuple[str, ...]


MODALITY_AWARE_BASE_PROMPT = """\
You are evaluating production-like skill activation for hypothesis_writer.

Do not write the downstream hypothesis. First, reason from the loaded evidence
that hypothesis_writer would receive after load_evidence_files(data_dir, scope="hypothesis").
Use the evidence modality inventory to decide which domain skill guides are
directly required before interpreting the evidence and producing
hypothesis_report.json.

A skill counts as activated only if read_skill_file is actually called during
this interaction for the required guide. Read only guides that are needed for
the evidence modalities in the case.

Do not call external database tools or APIs. Do not infer new evidence. Do not
draft reports, rank targets, or fill hypothesis_report.json.

After any needed skill reads, answer with:
1. ACTIVATED_SKILLS: a comma-separated list of skill names you read, or NONE
2. MODALITY_INVENTORY: one concise sentence naming the loaded evidence modalities
3. BENCHMARK_DECISION: one concise sentence stating whether activation is complete
"""


MODALITY_ACTIVATION_CASES = (
    ModalityActivationCase(
        case_id="stage1_census_loaded",
        phase="stage1",
        prompt=(
            "The loaded hypothesis evidence includes a Stage 1 single-cell "
            "expression comparison by cell type: target-vs-rest rates, "
            "coexpression rates, interest cell type calls, and enrichment or "
            "depletion summaries. Decide which skill guides must be read before "
            "hypothesis_writer interprets these modalities."
        ),
        expected_domain_skills=("compare-census-gene-pair-by-cell-type",),
    ),
    ModalityActivationCase(
        case_id="stage1_string_loaded",
        phase="stage1",
        prompt=(
            "The loaded hypothesis evidence includes a Stage 1 protein network "
            "packet: interaction scores, network neighbors, pathway convergence, "
            "and mechanism support for a target pair. Decide which skill guides "
            "must be read before hypothesis_writer interprets these modalities."
        ),
        expected_domain_skills=("string-database",),
    ),
    ModalityActivationCase(
        case_id="stage1_census_string_loaded",
        phase="stage1",
        prompt=(
            "The loaded hypothesis evidence includes Stage 1 single-cell "
            "expression and coexpression results plus protein interaction and "
            "network convergence results. Decide which skill guides must be "
            "read before hypothesis_writer interprets these modalities together."
        ),
        expected_domain_skills=(
            "compare-census-gene-pair-by-cell-type",
            "string-database",
        ),
    ),
    ModalityActivationCase(
        case_id="stage2_opentargets_loaded",
        phase="stage2",
        prompt=(
            "The loaded hypothesis evidence includes Stage 2 target-disease "
            "association evidence, tractability annotations, safety signals, "
            "and known-drug context. Decide which skill guides must be read "
            "before hypothesis_writer interprets these modalities."
        ),
        expected_domain_skills=("opentargets-database",),
    ),
    ModalityActivationCase(
        case_id="stage2_gwas_loaded",
        phase="stage2",
        prompt=(
            "The loaded hypothesis evidence includes Stage 2 genetic association "
            "evidence: variants, trait terms, p-values, mapped genes, and "
            "gene-trait support. Decide which skill guides must be read before "
            "hypothesis_writer interprets these modalities."
        ),
        expected_domain_skills=("gwas-database",),
    ),
    ModalityActivationCase(
        case_id="stage2_opentargets_gwas_loaded",
        phase="stage2",
        prompt=(
            "The loaded hypothesis evidence includes Stage 2 target-disease "
            "association, tractability, and safety evidence plus genetic "
            "association evidence with variants, traits, p-values, and mapped "
            "genes. Decide which skill guides must be read before "
            "hypothesis_writer interprets these modalities together."
        ),
        expected_domain_skills=("opentargets-database", "gwas-database"),
    ),
    ModalityActivationCase(
        case_id="stage3_chembl_loaded",
        phase="stage3",
        prompt=(
            "The loaded hypothesis evidence includes Stage 3 compound and "
            "bioactivity evidence: matched molecules, potency values, mechanism "
            "of action, clinical phase, and repurposing context. Decide which "
            "skill guides must be read before hypothesis_writer interprets "
            "these modalities."
        ),
        expected_domain_skills=("chembl-database",),
    ),
    ModalityActivationCase(
        case_id="full_multimodal_loaded",
        phase="composite",
        prompt=(
            "The loaded hypothesis evidence includes the full multimodal packet: "
            "target-disease association, genetic association, compound "
            "bioactivity, single-cell expression by cell type, coexpression, "
            "protein interactions, and network convergence. Decide which skill "
            "guides must be read before hypothesis_writer interprets these "
            "modalities together."
        ),
        expected_domain_skills=(
            "opentargets-database",
            "gwas-database",
            "chembl-database",
            "compare-census-gene-pair-by-cell-type",
            "string-database",
        ),
    ),
    ModalityActivationCase(
        case_id="negative_schema_only",
        phase="negative",
        prompt=(
            "The request is only to check hypothesis_report.json schema keys, "
            "field names, and section order for an already interpreted result. "
            "No loaded evidence modality needs interpretation. Decide whether "
            "any domain skill guide must be read."
        ),
        expected_domain_skills=(),
    ),
    ModalityActivationCase(
        case_id="negative_general_recommendation_style",
        phase="negative",
        prompt=(
            "The request is to make general writing-style recommendations for "
            "clear hypothesis prose without interpreting loaded evidence, "
            "querying databases, or validating any target. Decide whether any "
            "domain skill guide must be read."
        ),
        expected_domain_skills=(),
    ),
)


_EXPECTED_DOMAIN_SKILLS = {
    skill for case in MODALITY_ACTIVATION_CASES for skill in case.expected_domain_skills
}
_UNKNOWN_DOMAIN_SKILLS = sorted(_EXPECTED_DOMAIN_SKILLS - set(DOMAIN_SKILL_UNIVERSE))
_UNKNOWN_EXPANDED_SKILLS = sorted(_EXPECTED_DOMAIN_SKILLS - set(EXPANDED6_SKILL_NAMES))
if _UNKNOWN_DOMAIN_SKILLS or _UNKNOWN_EXPANDED_SKILLS:
    raise ValueError(
        "modality activation cases reference unknown domain skills: "
        f"{_UNKNOWN_DOMAIN_SKILLS or _UNKNOWN_EXPANDED_SKILLS}"
    )


CASE_BY_ID = {case.case_id: case for case in MODALITY_ACTIVATION_CASES}


def build_modality_trial_plan(
    *,
    models: Sequence[str],
    ports: Sequence[int],
    conditions: Sequence[str],
    case_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    selected_case_ids = tuple(case_ids) if case_ids else tuple(CASE_BY_ID)
    unknown = sorted(set(selected_case_ids) - set(CASE_BY_ID))
    if unknown:
        raise ValueError(f"unknown modality activation case ids: {unknown}")

    trials: list[dict[str, Any]] = []
    for model in models:
        for condition in conditions:
            for port in ports:
                for case_id in selected_case_ids:
                    case = CASE_BY_ID[case_id]
                    trials.append(
                        {
                            "model": model,
                            "port": int(port),
                            "condition": condition,
                            "case_id": case.case_id,
                            "phase": case.phase,
                            "run_id": (
                                f"{model_slug(model)}_{condition}_"
                                f"port{int(port)}_{case.case_id}"
                            ),
                        }
                    )
    return trials


def _round(value: float) -> float:
    return round(value, 4)


def _ratio(numerator: int, denominator: int) -> float:
    return _round(numerator / denominator) if denominator else 0.0


def _mean(values: list[float]) -> float:
    return _round(mean(values)) if values else 0.0


def score_modality_activation(
    *,
    expected_domain_skills: Sequence[str],
    activated_skill_names: Sequence[str],
) -> dict[str, Any]:
    return score_phase_activation(
        expected_domain_skills=expected_domain_skills,
        activated_skill_names=activated_skill_names,
    )


def aggregate_modality_activation(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for group_key in (
            f"{row['model']}::{row['condition']}",
            f"{row['model']}::{row['condition']}::{row['phase']}",
        ):
            groups.setdefault(group_key, []).append(row)

    summaries: dict[str, Any] = {}
    for key, group_rows in sorted(groups.items()):
        valid = [row for row in group_rows if not row.get("error")]
        runs = len(group_rows)
        exact = [row for row in valid if row.get("domain_exact_match") is True]
        summaries[key] = {
            "runs": runs,
            "valid_runs": len(valid),
            "error_runs": runs - len(valid),
            "domain_exact_match_rate": _ratio(len(exact), len(valid)),
            "mean_domain_precision": _mean(
                [float(row["domain_precision"]) for row in valid]
            ),
            "mean_domain_recall": _mean(
                [float(row["domain_recall"]) for row in valid]
            ),
            "mean_domain_specificity": _mean(
                [float(row["domain_specificity"]) for row in valid]
            ),
            "mean_domain_f1": _mean([float(row["domain_f1"]) for row in valid]),
            "mean_domain_fp": _mean([float(row.get("domain_fp", 0)) for row in valid]),
            "mean_domain_fn": _mean([float(row.get("domain_fn", 0)) for row in valid]),
            "core_activation_rate": _ratio(
                sum(1 for row in valid if row.get("core_activated") is True),
                len(valid),
            ),
        }
    return {"groups": summaries}


def render_modality_activation_summary(
    rows: Sequence[dict[str, Any]],
    aggregate: dict[str, Any],
) -> str:
    lines = [
        "# Modality-Aware Skill Activation Benchmark",
        "",
        (
            "This benchmark measures whether loaded evidence modalities trigger "
            "the needed skill-guide reads before hypothesis_writer interprets "
            "hypothesis evidence. It does not evaluate hypothesis_report.json "
            "quality."
        ),
        "",
        (
            "| model | port | condition | phase | case | expected domain skills | "
            "activated skills | exact match | precision | recall | specificity | error |"
        ),
        "| --- | ---: | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            (
                "| {model} | {port} | {condition} | {phase} | {case_id} | "
                "{expected} | {activated} | {exact} | {precision:.4f} | "
                "{recall:.4f} | {specificity:.4f} | {error} |"
            ).format(
                model=row["model"],
                port=row["port"],
                condition=row["condition"],
                phase=row["phase"],
                case_id=row["case_id"],
                expected=", ".join(row.get("expected_domain_skills", [])) or "-",
                activated=", ".join(row.get("activated_skill_names", [])) or "-",
                exact=row.get("domain_exact_match"),
                precision=float(row.get("domain_precision") or 0.0),
                recall=float(row.get("domain_recall") or 0.0),
                specificity=float(row.get("domain_specificity") or 0.0),
                error=row.get("error") or "-",
            )
        )
    lines.extend(
        [
            "",
            "## Aggregate",
            "",
            "```json",
            json.dumps(aggregate, indent=2, ensure_ascii=False),
            "```",
            "",
            "## Interpretation Rule",
            "",
            "A useful activation policy reads the guides required by the loaded "
            "modalities while preserving specificity on negative controls. Exact "
            "match rate and domain F1 are the primary summary signals.",
        ]
    )
    return "\n".join(lines) + "\n"

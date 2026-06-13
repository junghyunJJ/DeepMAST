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
class Fig3ActivationCase:
    case_id: str
    phase: str
    prompt: str
    expected_domain_skills: tuple[str, ...]


FIG3_STYLE_BASE_PROMPT = """\
You are evaluating skill activation for a controlled benchmark.

Do not solve the downstream task. Your task is to decide which skill guides are
directly required before doing the downstream task.

Use read_skill_file for every required skill guide now. A skill counts as activated only if
read_skill_file is actually called during this interaction.

Do not call database APIs or external tools. Do not draft reports. Do not
perform the downstream task.

After any needed skill reads, answer with:
1. ACTIVATED_SKILLS: a comma-separated list of skill names you read, or NONE
2. RATIONALE: one concise sentence explaining why those skills match the task
3. BENCHMARK_DECISION: one concise sentence stating whether activation is complete
"""


FIG3_ACTIVATION_CASES = (
    Fig3ActivationCase(
        case_id="stage1_census_expression",
        phase="stage1",
        prompt=(
            "Before running a disease-focused CELLxGENE Census comparison for "
            "two genes by cell type, decide which skill guide must be read."
        ),
        expected_domain_skills=("compare-census-gene-pair-by-cell-type",),
    ),
    Fig3ActivationCase(
        case_id="stage1_string_network",
        phase="stage1",
        prompt=(
            "Before analyzing STRING protein-protein interaction evidence, "
            "network neighbors, and pathway convergence for a target pair, "
            "decide which skill guide must be read."
        ),
        expected_domain_skills=("string-database",),
    ),
    Fig3ActivationCase(
        case_id="stage1_census_string_combined",
        phase="stage1",
        prompt=(
            "Before combining cell-type Census expression/coexpression evidence "
            "with STRING PPI network evidence for a mechanism screen, decide "
            "which skill guides must be read."
        ),
        expected_domain_skills=(
            "compare-census-gene-pair-by-cell-type",
            "string-database",
        ),
    ),
    Fig3ActivationCase(
        case_id="stage2_opentargets_target_disease",
        phase="stage2",
        prompt=(
            "Before assessing Open Targets target-disease association, "
            "tractability, safety, and known-drug evidence, decide which skill "
            "guide must be read."
        ),
        expected_domain_skills=("opentargets-database",),
    ),
    Fig3ActivationCase(
        case_id="stage2_gwas_genetic_association",
        phase="stage2",
        prompt=(
            "Before assessing GWAS SNP-trait, EFO trait, p-value, and "
            "gene-trait association evidence for target validation, decide "
            "which skill guide must be read."
        ),
        expected_domain_skills=("gwas-database",),
    ),
    Fig3ActivationCase(
        case_id="stage2_validation_composite",
        phase="stage2",
        prompt=(
            "Before combining Open Targets target-disease evidence with GWAS "
            "genetic association evidence for target validation, decide which "
            "skill guides must be read."
        ),
        expected_domain_skills=("opentargets-database", "gwas-database"),
    ),
    Fig3ActivationCase(
        case_id="stage3_chembl_compounds",
        phase="stage3",
        prompt=(
            "Before assessing ChEMBL compounds, bioactivity, clinical phase, "
            "mechanism of action, and repurposing evidence, decide which skill "
            "guide must be read."
        ),
        expected_domain_skills=("chembl-database",),
    ),
    Fig3ActivationCase(
        case_id="stage2_stage3_validation_drugs",
        phase="composite",
        prompt=(
            "Before doing a target validation and druggability screen that "
            "combines Open Targets, GWAS, and ChEMBL evidence, decide which "
            "skill guides must be read."
        ),
        expected_domain_skills=(
            "opentargets-database",
            "gwas-database",
            "chembl-database",
        ),
    ),
    Fig3ActivationCase(
        case_id="negative_schema_formatting",
        phase="negative",
        prompt=(
            "Before formatting JSON schema keys and section order for an "
            "already decided output, decide whether any database skill guide "
            "must be read."
        ),
        expected_domain_skills=(),
    ),
    Fig3ActivationCase(
        case_id="negative_general_biology",
        phase="negative",
        prompt=(
            "Before answering a general biology question about ligand-receptor "
            "signaling, decide whether any specialized database skill guide "
            "must be read."
        ),
        expected_domain_skills=(),
    ),
)


CASE_BY_ID = {case.case_id: case for case in FIG3_ACTIVATION_CASES}


def build_fig3_trial_plan(
    *,
    models: Sequence[str],
    ports: Sequence[int],
    conditions: Sequence[str],
    case_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    selected_case_ids = tuple(case_ids) if case_ids else tuple(CASE_BY_ID)
    unknown = sorted(set(selected_case_ids) - set(CASE_BY_ID))
    if unknown:
        raise ValueError(f"unknown fig3 activation case ids: {unknown}")

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


def aggregate_fig3_activation(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
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


def score_fig3_activation(
    *,
    expected_domain_skills: Sequence[str],
    activated_skill_names: Sequence[str],
) -> dict[str, Any]:
    return score_phase_activation(
        expected_domain_skills=expected_domain_skills,
        activated_skill_names=activated_skill_names,
    )


def render_fig3_activation_summary(
    rows: Sequence[dict[str, Any]],
    aggregate: dict[str, Any],
) -> str:
    lines = [
        "# Fig3-Style Skill Activation Benchmark",
        "",
        (
            "This benchmark measures activation mechanics only: passive skill "
            "listing versus passive listing plus SkillActivator. It does not "
            "evaluate hypothesis_report.json quality."
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
            "Use domain F1 and recall to judge activation improvement. Specificity "
            "and false positives must remain high enough that improvement is not "
            "caused by activating every skill.",
        ]
    )
    return "\n".join(lines) + "\n"

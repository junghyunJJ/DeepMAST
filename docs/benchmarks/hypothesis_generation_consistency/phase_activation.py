from __future__ import annotations

import json
from dataclasses import dataclass
from statistics import mean
from typing import Any, Iterable, Sequence


CORE_SKILL_NAME = "drug-target-hypothesis"

DOMAIN_SKILL_UNIVERSE = (
    "opentargets-database",
    "gwas-database",
    "chembl-database",
    "compare-census-gene-pair-by-cell-type",
    "string-database",
)

EXPANDED6_SKILL_NAMES = (CORE_SKILL_NAME, *DOMAIN_SKILL_UNIVERSE)


@dataclass(frozen=True)
class PhaseActivationCase:
    case_id: str
    phase: str
    prompt: str
    expected_domain_skills: tuple[str, ...]
    expect_core_skill: bool = True


PHASE_ACTIVATION_CASES = (
    PhaseActivationCase(
        case_id="stage1_census_expression",
        phase="stage1",
        prompt=(
            "Draft the Stage 1 hypothesis evidence interpretation from loaded "
            "Census results: target-vs-rest expression, coexpression rate, "
            "interest cell type, and depletion/enrichment calls are available. "
            "Decide which skill guides must be read before drafting."
        ),
        expected_domain_skills=("compare-census-gene-pair-by-cell-type",),
    ),
    PhaseActivationCase(
        case_id="stage1_string_network",
        phase="stage1",
        prompt=(
            "Draft the Stage 1 mechanism interpretation from loaded STRING "
            "evidence: ligand-receptor PPI score, network neighbors, and "
            "network convergence are available. Decide which skill guides must "
            "be read before drafting."
        ),
        expected_domain_skills=("string-database",),
    ),
    PhaseActivationCase(
        case_id="stage1_census_string_combined",
        phase="stage1",
        prompt=(
            "Draft the Stage 1 hypothesis interpretation using loaded Census "
            "target-vs-rest and coexpression results plus loaded STRING PPI "
            "and network convergence results. Decide which skill guides must "
            "be read before drafting."
        ),
        expected_domain_skills=(
            "compare-census-gene-pair-by-cell-type",
            "string-database",
        ),
    ),
    PhaseActivationCase(
        case_id="stage2_opentargets_target_disease",
        phase="stage2",
        prompt=(
            "Draft the Stage 2 target validation interpretation from loaded "
            "OpenTargets target-disease association, tractability, safety, "
            "and known-drug evidence. Decide which skill guides must be read "
            "before drafting."
        ),
        expected_domain_skills=("opentargets-database",),
    ),
    PhaseActivationCase(
        case_id="stage2_gwas_genetic_association",
        phase="stage2",
        prompt=(
            "Draft the Stage 2 genetics interpretation from loaded GWAS "
            "variant, SNP, EFO trait, p-value, and gene-trait association "
            "evidence. Decide which skill guides must be read before drafting."
        ),
        expected_domain_skills=("gwas-database",),
    ),
    PhaseActivationCase(
        case_id="stage2_validation_composite",
        phase="stage2",
        prompt=(
            "Draft the Stage 2 target validation paragraph using loaded "
            "OpenTargets target-disease scores and loaded GWAS genetic "
            "association evidence. Decide which skill guides must be read "
            "before drafting."
        ),
        expected_domain_skills=("opentargets-database", "gwas-database"),
    ),
    PhaseActivationCase(
        case_id="stage3_chembl_compounds",
        phase="stage3",
        prompt=(
            "Draft the Stage 3 druggability interpretation from loaded ChEMBL "
            "matched compounds, bioactivity, clinical phase, mechanism of "
            "action, and repurposing evidence. Decide which skill guides must "
            "be read before drafting."
        ),
        expected_domain_skills=("chembl-database",),
    ),
    PhaseActivationCase(
        case_id="stage2_stage3_validation_drugs",
        phase="composite",
        prompt=(
            "Draft a composite hypothesis evidence paragraph using loaded "
            "OpenTargets target-disease evidence, loaded GWAS genetic evidence, "
            "and loaded ChEMBL compound evidence. Decide which skill guides "
            "must be read before drafting."
        ),
        expected_domain_skills=(
            "opentargets-database",
            "gwas-database",
            "chembl-database",
        ),
    ),
    PhaseActivationCase(
        case_id="negative_schema_formatting",
        phase="negative",
        prompt=(
            "Format the hypothesis_report.json schema keys and section order. "
            "No domain evidence interpretation is requested. Decide which "
            "skill guides must be read before drafting."
        ),
        expected_domain_skills=(),
    ),
    PhaseActivationCase(
        case_id="negative_general_biology",
        phase="negative",
        prompt=(
            "Explain in general terms what ligand-receptor signaling means in "
            "a tissue microenvironment. Do not interpret loaded evidence. "
            "Decide which skill guides must be read before answering."
        ),
        expected_domain_skills=(),
        expect_core_skill=False,
    ),
)


def _sorted_unique(values: Iterable[str]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


def _round(value: float) -> float:
    return round(value, 4)


def _ratio(numerator: int, denominator: int) -> float:
    return _round(numerator / denominator) if denominator else 0.0


def score_phase_activation(
    *,
    expected_domain_skills: Sequence[str],
    activated_skill_names: Sequence[str],
) -> dict[str, Any]:
    expected = set(expected_domain_skills)
    activated = set(activated_skill_names)
    domain_universe = set(DOMAIN_SKILL_UNIVERSE)
    domain_activated = activated & domain_universe

    tp = len(expected & domain_activated)
    fp = len(domain_activated - expected)
    fn = len(expected - domain_activated)
    tn = len(domain_universe - expected - domain_activated)
    precision = 1.0 if not expected and not domain_activated else _ratio(tp, tp + fp)
    recall = 1.0 if not expected and not domain_activated else _ratio(tp, tp + fn)
    specificity = _ratio(tn, tn + fp)
    f1 = _round(2 * precision * recall / (precision + recall)) if precision + recall else 0.0

    return {
        "expected_domain_skills": _sorted_unique(expected),
        "activated_domain_skills": _sorted_unique(domain_activated),
        "domain_tp": tp,
        "domain_fp": fp,
        "domain_fn": fn,
        "domain_tn": tn,
        "domain_precision": precision,
        "domain_recall": recall,
        "domain_specificity": specificity,
        "domain_f1": f1,
        "domain_exact_match": fp == 0 and fn == 0,
        "domain_overactivated": fp > 0,
        "domain_underactivated": fn > 0,
        "core_activated": CORE_SKILL_NAME in activated,
    }


def model_slug(model: str) -> str:
    return model.replace("qwen3.5:", "qwen").replace(":", "").replace(".", "")


def _case_by_id() -> dict[str, PhaseActivationCase]:
    return {case.case_id: case for case in PHASE_ACTIVATION_CASES}


def build_phase_trial_plan(
    *,
    models: Sequence[str],
    ports: Sequence[int],
    conditions: Sequence[str],
    case_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    cases = _case_by_id()
    selected_case_ids = tuple(case_ids) if case_ids else tuple(cases)
    unknown = sorted(set(selected_case_ids) - set(cases))
    if unknown:
        raise ValueError(f"unknown phase activation case ids: {unknown}")

    trials: list[dict[str, Any]] = []
    for model in models:
        for condition in conditions:
            for port in ports:
                for case_id in selected_case_ids:
                    case = cases[case_id]
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


def _mean(values: list[float]) -> float:
    return _round(mean(values)) if values else 0.0


def aggregate_phase_activation(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = f"{row['model']}::{row['condition']}::{row['phase']}"
        groups.setdefault(key, []).append(row)

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
            "mean_domain_precision": _mean([float(row["domain_precision"]) for row in valid]),
            "mean_domain_recall": _mean([float(row["domain_recall"]) for row in valid]),
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


def render_phase_activation_summary(
    rows: Sequence[dict[str, Any]],
    aggregate: dict[str, Any],
) -> str:
    lines = [
        "# Phase-Aware Skill Activation Appropriateness",
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
            "A run that activates every domain skill has high recall but low precision. "
            "The primary pass signal is domain exact match rate plus specificity, not raw activation count.",
        ]
    )
    return "\n".join(lines) + "\n"

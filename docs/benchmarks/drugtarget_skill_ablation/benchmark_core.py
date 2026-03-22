"""Core utilities for DrugTarget skill-exposure A/B benchmarks.

This benchmark isolates strategy-layer effects by keeping the runnable surface
fixed (`read_skill_file` only) while toggling which benchmark cases expose
SKILL.md documents through SkillLoadHarness.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import logging
import math
import os
import random
import re
import sys
import time
from copy import deepcopy
from pathlib import Path
from statistics import mean
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

try:
    from scipy.stats import binomtest, wilcoxon
except Exception:  # pragma: no cover - scipy exists in the repo env, but keep fallback safe
    binomtest = None
    wilcoxon = None


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.drug_target.tools.skill_reader import read_skill_file
from src.agents.drug_target.tools.stage_logic import (
    EXPLORATORY_CRITERIA,
    VALIDATED_CRITERIA,
    classify_target,
    compute_priority,
    validate_rubric_assessment,
)
from src.agents.model import create_llm
from src.agents.shared.skill_load_harness import SkillLoadHarness

logger = logging.getLogger(__name__)

BENCHMARK_DIR = Path(__file__).resolve().parent
CASES_DIR = BENCHMARK_DIR / "cases"
RESULTS_DIR = BENCHMARK_DIR / "results"

MAIN_STAGE2_SKILL_REGISTRY: dict[str, str] = {
    "opentargets-database": str(PROJECT_ROOT / "skills" / "opentargets-database"),
    "gwas-database": str(PROJECT_ROOT / "skills" / "gwas-database"),
}
CHEMBL_SKILL_REGISTRY: dict[str, str] = {
    "chembl-database": str(PROJECT_ROOT / "skills" / "chembl-database"),
}
CHEMBL_STAGE_HINTS = {"chembl-database": "Stage 3 only"}

DEFAULT_MODEL_CONFIGS: list[dict[str, Any]] = [
    {
        "label": "gpt-4.1-mini",
        "provider": "openai",
        "model_kwargs": {"model": "gpt-4.1-mini", "temperature": 0},
        "repeats": 8,
    },
    {
        "label": "qwen3.5:35b",
        "provider": "ollama",
        "model_kwargs": {"model": "qwen3.5:35b", "temperature": 0},
        "repeats": 3,
    },
]

DEFAULT_JUDGE_MODEL_CANDIDATES: list[dict[str, Any]] = [
    {
        "label": "gpt-4.1-mini",
        "provider": "openai",
        "model_kwargs": {"model": "gpt-4.1-mini", "temperature": 0},
    },
    {
        "label": "gpt-4.1",
        "provider": "openai",
        "model_kwargs": {"model": "gpt-4.1", "temperature": 0},
    },
    {
        "label": "qwen3.5:35b",
        "provider": "ollama",
        "model_kwargs": {"model": "qwen3.5:35b", "temperature": 0},
    },
    {
        "label": "gpt-oss:20b",
        "provider": "ollama",
        "model_kwargs": {"model": "gpt-oss:20b", "temperature": 0},
    },
    {
        "label": "qwen3.5:122b",
        "provider": "ollama",
        "model_kwargs": {"model": "qwen3.5:122b", "temperature": 0},
    },
]

VARIANT_A = "A_tools_only"
VARIANT_B = "B_tools_plus_skills"
MAIN_STAGE2_BENCHMARK = "stage2_synthesis"
STAGE2_INTERPRETATION_V2_BENCHMARK = "stage2_interpretation_v2"
STAGE2_INTERPRETATION_V3_BENCHMARK = "stage2_interpretation_v3"
CHEMBL_MICRO_BENCHMARK = "chembl_micro"
RESEARCH_JUDGE_PANEL_SIZE = 3
DEFAULT_HUMAN_AUDIT_SAMPLE_RATE = 0.2
RESEARCH_JUDGE_CONFIDENCE = ("low", "medium", "high")
V3_PROBE_WEIGHTS = {"P1": 0.60, "P2": 0.25, "P3": 0.15}
V3_ALLOWED_SKILLS = {"opentargets-database", "gwas-database"}
V3_CASE_FILENAME = "stage2_interpretation_v3_cases.json"
V3_EXCERPT_LIBRARY_FILENAME = "skill_excerpt_library.json"
HUMAN_AUDIT_TEMPLATE_FIELDS = [
    "audit_id",
    "reviewer_id",
    "winner",
    "output_a_grounding",
    "output_a_rubric_alignment",
    "output_a_unsupported_claim_penalty",
    "output_a_major_error",
    "output_b_grounding",
    "output_b_rubric_alignment",
    "output_b_unsupported_claim_penalty",
    "output_b_major_error",
    "confidence",
    "rationale",
]

V3_PROBE_LAYOUT: dict[str, list[tuple[str, str, str]]] = {
    "real_flt1_breast": [
        ("P1", "genetic_support", "replication_inflation"),
        ("P2", "clinical_precedence", "approval_scope_inflation"),
        ("P3", "safety_weight", "safety_underweighting"),
    ],
    "real_tgfb1_breast": [
        ("P1", "genetic_support", "gwas_strength_inflation"),
        ("P2", "clinical_precedence", "approval_scope_inflation"),
        ("P3", "uncertainty_level", "uncertainty_underestimation"),
    ],
    "real_tgfbr2_breast": [
        ("P1", "clinical_precedence", "approval_scope_inflation"),
        ("P2", "genetic_support", "gwas_strength_inflation"),
        ("P3", "uncertainty_level", "uncertainty_underestimation"),
    ],
    "real_cd44_breast": [
        ("P1", "clinical_precedence", "approval_scope_inflation"),
        ("P2", "genetic_support", "gwas_strength_inflation"),
        ("P3", "uncertainty_level", "uncertainty_underestimation"),
    ],
    "real_spp1_breast": [
        ("P1", "tractability_signal", "predicted_tractability_inflation"),
        ("P2", "clinical_precedence", "approval_scope_inflation"),
        ("P3", "genetic_support", "gwas_strength_inflation"),
    ],
    "perturbation_ot_safety_conflict": [
        ("P1", "safety_weight", "safety_underweighting"),
        ("P2", "clinical_precedence", "approval_scope_inflation"),
        ("P3", "genetic_support", "gwas_strength_inflation"),
    ],
    "perturbation_gwas_significance_boundary": [
        ("P1", "genetic_support", "gwas_strength_inflation"),
        ("P2", "tractability_signal", "predicted_tractability_inflation"),
        ("P3", "uncertainty_level", "uncertainty_underestimation"),
    ],
    "perturbation_trait_ambiguity": [
        ("P1", "disease_alignment", "trait_alignment_inflation"),
        ("P2", "genetic_support", "gwas_strength_inflation"),
        ("P3", "clinical_precedence", "approval_scope_inflation"),
    ],
    "perturbation_evidence_conflict": [
        ("P1", "genetic_support", "gwas_strength_inflation"),
        ("P2", "clinical_precedence", "approval_scope_inflation"),
        ("P3", "uncertainty_level", "uncertainty_underestimation"),
    ],
    "real_vegfa_breast": [
        ("P1", "genetic_support", "replication_inflation"),
        ("P2", "clinical_precedence", "approval_scope_inflation"),
        ("P3", "safety_weight", "safety_underweighting"),
    ],
    "perturbation_approval_scope_mismatch": [
        ("P1", "approval_scope", "approval_scope_inflation"),
        ("P2", "clinical_precedence", "approval_scope_inflation"),
        ("P3", "genetic_support", "gwas_strength_inflation"),
    ],
    "perturbation_predicted_tractability_only": [
        ("P1", "tractability_signal", "predicted_tractability_inflation"),
        ("P2", "clinical_precedence", "approval_scope_inflation"),
        ("P3", "genetic_support", "gwas_strength_inflation"),
    ],
    "perturbation_adjacent_phase12_confound": [
        ("P1", "disease_alignment", "approval_scope_inflation"),
        ("P2", "clinical_precedence", "approval_scope_inflation"),
        ("P3", "genetic_support", "gwas_strength_inflation"),
    ],
    "perturbation_uncertainty_high_mixed_signal": [
        ("P1", "uncertainty_level", "uncertainty_underestimation"),
        ("P2", "disease_alignment", "trait_alignment_inflation"),
        ("P3", "genetic_support", "gwas_strength_inflation"),
    ],
}

V3_EXCERPTS_BY_ERROR_FAMILY: dict[str, list[str]] = {
    "gwas_strength_inflation": ["gwas_pvalue_threshold"],
    "replication_inflation": ["gwas_replication", "gwas_pvalue_threshold"],
    "trait_alignment_inflation": ["gwas_trait_alignment"],
    "approval_scope_inflation": ["ot_clinical_precedence", "ot_tractability_precedence"],
    "predicted_tractability_inflation": ["ot_tractability_precedence"],
    "safety_underweighting": ["ot_safety_caution", "ot_relative_score"],
    "uncertainty_underestimation": ["gwas_study_metadata", "ot_relative_score"],
}


def _required_stage2_case_keys() -> set[str]:
    return {
        "case_id",
        "benchmark_type",
        "source_type",
        "input_bundle",
        "gold_assessment",
        "expected_classification",
        "expected_priority",
        "judge_focus",
        "notes",
    }


def _required_stage2_interpretation_v2_keys() -> set[str]:
    return {
        "case_id",
        "benchmark_type",
        "base_case_id",
        "judge_focus",
        "notes",
        "case_rationale",
        "interpretation_checks",
        "overall_conclusion",
        "expected_uncertainty",
    }


def _required_v2_check_keys() -> set[str]:
    return {
        "check_id",
        "question",
        "options",
        "gold_label",
        "partial_credit_labels",
        "overclaim_labels",
        "required_evidence_anchors",
    }


def _required_stage2_interpretation_v3_keys() -> set[str]:
    return {
        "case_id",
        "benchmark_type",
        "base_case_id",
        "judge_focus",
        "notes",
        "case_rationale",
        "input_bundle",
        "evidence_refs",
        "skill_excerpt_ids",
        "probes",
        "secondary_conclusion",
    }


def _required_v3_probe_keys() -> set[str]:
    return {
        "probe_id",
        "source_check_id",
        "error_family",
        "question",
        "options",
        "gold_label",
        "conservative_labels",
        "target_error_labels",
        "required_evidence_refs",
        "required_excerpt_ids",
    }


def _default_v3_excerpt_library() -> dict[str, dict[str, Any]]:
    return {
        "gwas_pvalue_threshold": {
            "excerpt_id": "gwas_pvalue_threshold",
            "skill_name": "gwas-database",
            "error_families": ["gwas_strength_inflation", "replication_inflation"],
            "title": "Genome-wide significance threshold",
            "text": (
                "Treat p <= 5×10^-8 as genome-wide significant. Signals above that threshold are "
                "suggestive and should not be upgraded to genome-wide significance without stronger evidence."
            ),
            "source_path": "skills/gwas-database/SKILL.md",
            "source_line_ref": "307-309,459",
        },
        "gwas_replication": {
            "excerpt_id": "gwas_replication",
            "skill_name": "gwas-database",
            "error_families": ["replication_inflation", "uncertainty_underestimation"],
            "title": "Replication and study metadata matter",
            "text": (
                "Check replication across independent studies, along with sample size and ancestry, "
                "before treating an association as robust or broadly applicable."
            ),
            "source_path": "skills/gwas-database/SKILL.md",
            "source_line_ref": "307-309,440-462",
        },
        "gwas_trait_alignment": {
            "excerpt_id": "gwas_trait_alignment",
            "skill_name": "gwas-database",
            "error_families": ["trait_alignment_inflation"],
            "title": "Trait mapping should use EFO-aligned labels",
            "text": (
                "Use mapped EFO trait labels and association records to verify that the GWAS trait truly matches "
                "the disease context of interest rather than a related phenotype."
            ),
            "source_path": "skills/gwas-database/SKILL.md",
            "source_line_ref": "276,432-433",
        },
        "gwas_study_metadata": {
            "excerpt_id": "gwas_study_metadata",
            "skill_name": "gwas-database",
            "error_families": ["uncertainty_underestimation"],
            "title": "Study metadata informs uncertainty",
            "text": (
                "Interpret GWAS evidence with study metadata in mind, especially ancestry, sample size, "
                "and whether replication populations are reported. Missing or mixed metadata should increase uncertainty."
            ),
            "source_path": "skills/gwas-database/SKILL.md",
            "source_line_ref": "440-462",
        },
        "ot_relative_score": {
            "excerpt_id": "ot_relative_score",
            "skill_name": "opentargets-database",
            "error_families": ["safety_underweighting", "uncertainty_underestimation"],
            "title": "Association scores are relative, not absolute confidence",
            "text": (
                "Open Targets scores rank relative evidence strength and should be interpreted with the evidence "
                "breakdown rather than as stand-alone confidence measures."
            ),
            "source_path": "skills/opentargets-database/SKILL.md",
            "source_line_ref": "220,271-276",
        },
        "ot_clinical_precedence": {
            "excerpt_id": "ot_clinical_precedence",
            "skill_name": "opentargets-database",
            "error_families": ["approval_scope_inflation"],
            "title": "Clinical precedence is not disease match by itself",
            "text": (
                "Known drugs and clinical precedence help assess druggability, but exact disease relevance still "
                "depends on whether the evidence is disease-matched rather than merely adjacent or indirect."
            ),
            "source_path": "skills/opentargets-database/SKILL.md",
            "source_line_ref": "247-254,289-293",
        },
        "ot_tractability_precedence": {
            "excerpt_id": "ot_tractability_precedence",
            "skill_name": "opentargets-database",
            "error_families": ["approval_scope_inflation", "predicted_tractability_inflation"],
            "title": "Prefer discovery or clinical precedence when judging tractability",
            "text": (
                "Tractability should distinguish between predicted druggability and discovery or clinical precedence. "
                "Predicted tractability alone should not be read as clinical maturity."
            ),
            "source_path": "skills/opentargets-database/SKILL.md",
            "source_line_ref": "247-254,289-293",
        },
        "ot_safety_caution": {
            "excerpt_id": "ot_safety_caution",
            "skill_name": "opentargets-database",
            "error_families": ["safety_underweighting"],
            "title": "Safety liabilities are explicit caution flags",
            "text": (
                "Multiple safety liabilities, conflicting evidence, or essential targets with broad expression "
                "are caution flags that should reduce optimism when prioritizing targets."
            ),
            "source_path": "skills/opentargets-database/SKILL.md",
            "source_line_ref": "263-276",
        },
    }


def load_skill_excerpt_library(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    excerpt_path = Path(path) if path is not None else CASES_DIR / V3_EXCERPT_LIBRARY_FILENAME
    if excerpt_path.exists():
        payload = json.loads(excerpt_path.read_text(encoding="utf-8"))
    elif excerpt_path.name == V3_EXCERPT_LIBRARY_FILENAME:
        payload = _default_v3_excerpt_library()
    else:
        raise FileNotFoundError(excerpt_path)

    if not isinstance(payload, dict):
        raise ValueError("Skill excerpt library must be a JSON object")

    validated: dict[str, dict[str, Any]] = {}
    required = {"excerpt_id", "skill_name", "error_families", "title", "text", "source_path", "source_line_ref"}
    for excerpt_id, excerpt in payload.items():
        if not isinstance(excerpt, dict):
            raise ValueError(f"Excerpt {excerpt_id} must be an object")
        missing = required - set(excerpt)
        if missing:
            raise ValueError(f"Excerpt {excerpt_id} missing keys: {sorted(missing)}")
        if excerpt["skill_name"] not in V3_ALLOWED_SKILLS:
            raise ValueError(f"Excerpt {excerpt_id} uses unsupported skill {excerpt['skill_name']}")
        if not isinstance(excerpt["text"], str) or not excerpt["text"].strip():
            raise ValueError(f"Excerpt {excerpt_id} must include non-empty text")
        if not isinstance(excerpt["source_line_ref"], str) or not excerpt["source_line_ref"].strip():
            raise ValueError(f"Excerpt {excerpt_id} must include source_line_ref")
        validated[str(excerpt_id)] = excerpt
    return validated


def _find_v2_check(case: dict[str, Any], check_id: str) -> dict[str, Any]:
    for check in case.get("interpretation_checks", []):
        if check.get("check_id") == check_id:
            return check
    raise ValueError(f"Case {case['case_id']} missing V2 check {check_id}")


def _safety_probe_labels(gold_label: str) -> tuple[list[str], list[str]]:
    if gold_label == "minimal":
        return ["moderate"], ["major"]
    if gold_label == "moderate":
        return ["major"], ["minimal"]
    if gold_label == "major":
        return [], ["minimal"]
    return [], []


def _uncertainty_probe_from_v2(case: dict[str, Any]) -> dict[str, Any]:
    payload = case["expected_uncertainty"]
    gold_label = payload["gold_label"]
    if gold_label == "medium":
        conservative_labels = ["high"]
        target_error_labels = ["low"]
    elif gold_label == "high":
        conservative_labels = []
        target_error_labels = ["low", "medium"]
    else:
        conservative_labels = ["medium"]
        target_error_labels = ["high"]
    return {
        "question": payload["question"],
        "options": payload["options"],
        "gold_label": gold_label,
        "conservative_labels": conservative_labels,
        "target_error_labels": target_error_labels,
        "required_evidence_anchors": payload.get("required_evidence_anchors", []),
    }


def _build_v3_probe(
    *,
    case: dict[str, Any],
    probe_id: str,
    source_check_id: str,
    error_family: str,
) -> dict[str, Any]:
    if source_check_id == "uncertainty_level":
        source = _uncertainty_probe_from_v2(case)
    else:
        source = _find_v2_check(case, source_check_id)

    conservative_labels = list(source.get("partial_credit_labels", source.get("conservative_labels", [])))
    target_error_labels = list(source.get("overclaim_labels", source.get("target_error_labels", [])))

    if error_family == "safety_underweighting":
        conservative_labels, target_error_labels = _safety_probe_labels(source["gold_label"])

    return {
        "probe_id": probe_id,
        "source_check_id": source_check_id,
        "error_family": error_family,
        "question": source["question"],
        "options": list(source["options"]),
        "gold_label": source["gold_label"],
        "conservative_labels": conservative_labels,
        "target_error_labels": target_error_labels,
        "required_excerpt_ids": list(V3_EXCERPTS_BY_ERROR_FAMILY.get(error_family, [])),
        "required_evidence_anchors": list(source.get("required_evidence_anchors", [])),
    }


def _resolve_evidence_refs_for_v3_case(case: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]], dict[str, Any]]:
    anchors: list[str] = []
    for probe in case["probes"]:
        anchors.extend(probe.get("_anchor_buffer", []))
    secondary = deepcopy(case["secondary_conclusion"])
    anchors.extend(secondary.get("_anchor_buffer", []))

    evidence_refs: dict[str, str] = {}
    reverse: dict[str, str] = {}
    for anchor in anchors:
        if anchor in reverse:
            continue
        ref_id = f"E{len(reverse) + 1}"
        reverse[anchor] = ref_id
        evidence_refs[ref_id] = anchor

    resolved_probes: list[dict[str, Any]] = []
    for probe in case["probes"]:
        probe = deepcopy(probe)
        probe["required_evidence_refs"] = [reverse[anchor] for anchor in probe.pop("_anchor_buffer", []) if anchor in reverse]
        resolved_probes.append(probe)

    secondary["required_evidence_refs"] = [
        reverse[anchor] for anchor in secondary.pop("_anchor_buffer", []) if anchor in reverse
    ]
    return evidence_refs, resolved_probes, secondary


def _build_stage2_interpretation_v3_cases() -> list[dict[str, Any]]:
    v2_cases = load_cases(CASES_DIR / "stage2_interpretation_v2_cases.json")
    resolved: list[dict[str, Any]] = []
    for case in v2_cases:
        layout = V3_PROBE_LAYOUT.get(case["case_id"])
        if not layout:
            continue

        probes = [
            _build_v3_probe(case=case, probe_id=probe_id, source_check_id=source_check_id, error_family=error_family)
            for probe_id, source_check_id, error_family in layout
        ]
        for probe in probes:
            probe["_anchor_buffer"] = list(probe.pop("required_evidence_anchors", []))

        secondary = {
            "question": case["overall_conclusion"]["question"],
            "options": list(case["overall_conclusion"]["options"]),
            "gold_label": case["overall_conclusion"]["gold_label"],
            "_anchor_buffer": list(case["overall_conclusion"].get("required_evidence_anchors", [])),
        }
        evidence_refs, resolved_probes, resolved_secondary = _resolve_evidence_refs_for_v3_case(
            {"probes": probes, "secondary_conclusion": secondary}
        )
        skill_excerpt_ids: list[str] = []
        for probe in resolved_probes:
            for excerpt_id in probe["required_excerpt_ids"]:
                if excerpt_id not in skill_excerpt_ids:
                    skill_excerpt_ids.append(excerpt_id)

        resolved.append(
            {
                "case_id": case["case_id"],
                "benchmark_type": STAGE2_INTERPRETATION_V3_BENCHMARK,
                "base_case_id": case["base_case_id"],
                "source_type": case["source_type"],
                "input_bundle": case["input_bundle"],
                "judge_focus": case["judge_focus"],
                "notes": case["notes"],
                "case_rationale": case["case_rationale"],
                "evidence_refs": evidence_refs,
                "skill_excerpt_ids": skill_excerpt_ids,
                "probes": resolved_probes,
                "secondary_conclusion": resolved_secondary,
            }
        )
    return resolved


def _validate_v3_probe(case_id: str, probe: dict[str, Any], excerpt_library: dict[str, dict[str, Any]]) -> None:
    missing = _required_v3_probe_keys() - set(probe)
    if missing:
        raise ValueError(f"V3 case {case_id} probe missing keys: {sorted(missing)}")
    options = probe["options"]
    if not isinstance(options, list) or len(options) < 2 or not all(isinstance(item, str) and item for item in options):
        raise ValueError(f"V3 case {case_id} probe {probe.get('probe_id')} has invalid options")
    if probe["gold_label"] not in options:
        raise ValueError(f"V3 case {case_id} probe {probe.get('probe_id')} has invalid gold_label")
    for key in ("conservative_labels", "target_error_labels", "required_evidence_refs", "required_excerpt_ids"):
        value = probe[key]
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise ValueError(f"V3 case {case_id} probe {probe.get('probe_id')} has invalid {key}")
    for label in probe["conservative_labels"] + probe["target_error_labels"]:
        if label not in options:
            raise ValueError(f"V3 case {case_id} probe {probe.get('probe_id')} uses out-of-range label {label}")
    for excerpt_id in probe["required_excerpt_ids"]:
        if excerpt_id not in excerpt_library:
            raise ValueError(f"V3 case {case_id} probe {probe.get('probe_id')} references unknown excerpt {excerpt_id}")


def _validate_v3_secondary_conclusion(case_id: str, payload: dict[str, Any]) -> None:
    required = {"question", "options", "gold_label", "required_evidence_refs"}
    missing = required - set(payload)
    if missing:
        raise ValueError(f"V3 case {case_id} secondary_conclusion missing keys: {sorted(missing)}")
    if payload["gold_label"] not in payload["options"]:
        raise ValueError(f"V3 case {case_id} secondary_conclusion has invalid gold_label")


def build_case_excerpt_guidance(
    case: dict[str, Any],
    *,
    excerpt_library: dict[str, dict[str, Any]] | None = None,
    max_tokens: int = 500,
) -> str:
    library = excerpt_library or load_skill_excerpt_library()
    ordered_ids: list[str] = []
    for probe in case.get("probes", []):
        for excerpt_id in probe.get("required_excerpt_ids", []):
            if excerpt_id not in ordered_ids:
                ordered_ids.append(excerpt_id)
    for excerpt_id in case.get("skill_excerpt_ids", []):
        if excerpt_id not in ordered_ids:
            ordered_ids.append(excerpt_id)

    blocks: list[str] = []
    token_budget = 0
    for excerpt_id in ordered_ids:
        excerpt = library.get(excerpt_id)
        if not excerpt:
            continue
        excerpt_tokens = len(str(excerpt["text"]).split())
        if blocks and token_budget + excerpt_tokens > max_tokens:
            continue
        token_budget += excerpt_tokens
        blocks.append(
            f"### {excerpt['title']}\n"
            f"Skill: {excerpt['skill_name']}\n"
            f"Source: {excerpt['source_path']} ({excerpt['source_line_ref']})\n"
            f"{excerpt['text']}"
        )

    if not blocks:
        return ""
    return (
        "## Relevant Skill Excerpts\n"
        "Use the excerpted guidance below for interpretation only. Do not add facts beyond the frozen evidence bundle.\n\n"
        + "\n\n".join(blocks)
    )

def _validate_v2_check(case_id: str, check: dict[str, Any]) -> None:
    missing = _required_v2_check_keys() - set(check)
    if missing:
        raise ValueError(f"V2 case {case_id} check missing keys: {sorted(missing)}")

    options = check["options"]
    if not isinstance(options, list) or not options or not all(isinstance(item, str) and item for item in options):
        raise ValueError(f"V2 case {case_id} check {check.get('check_id')} has invalid options")

    for key in ("partial_credit_labels", "overclaim_labels", "required_evidence_anchors"):
        value = check[key]
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise ValueError(f"V2 case {case_id} check {check.get('check_id')} has invalid {key}")

    gold_label = check["gold_label"]
    if not isinstance(gold_label, str) or gold_label not in options:
        raise ValueError(f"V2 case {case_id} check {check.get('check_id')} has invalid gold_label")

    invalid_partial = [label for label in check["partial_credit_labels"] if label not in options]
    if invalid_partial:
        raise ValueError(
            f"V2 case {case_id} check {check.get('check_id')} has partial_credit_labels outside options: {invalid_partial}"
        )

    invalid_overclaim = [label for label in check["overclaim_labels"] if label not in options]
    if invalid_overclaim:
        raise ValueError(
            f"V2 case {case_id} check {check.get('check_id')} has overclaim_labels outside options: {invalid_overclaim}"
        )


def _validate_v2_answer_spec(case_id: str, key: str, payload: dict[str, Any]) -> None:
    required = {"question", "options", "gold_label"}
    missing = required - set(payload)
    if missing:
        raise ValueError(f"V2 case {case_id} {key} missing keys: {sorted(missing)}")
    options = payload["options"]
    if not isinstance(options, list) or not options or not all(isinstance(item, str) and item for item in options):
        raise ValueError(f"V2 case {case_id} {key} has invalid options")
    if not isinstance(payload["gold_label"], str) or payload["gold_label"] not in options:
        raise ValueError(f"V2 case {case_id} {key} has invalid gold_label")


def _load_stage2_base_case_map() -> dict[str, dict[str, Any]]:
    base_cases = load_cases(CASES_DIR / "stage2_synthesis_cases.json")
    return {case["case_id"]: case for case in base_cases if case["benchmark_type"] == MAIN_STAGE2_BENCHMARK}


def _resolve_stage2_interpretation_v2_case(
    case: dict[str, Any],
    *,
    stage2_base_cases: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    case_id = case["case_id"]
    base_case_id = case["base_case_id"]
    if base_case_id not in stage2_base_cases:
        raise ValueError(f"V2 case {case_id} references unknown base_case_id {base_case_id}")

    checks = case["interpretation_checks"]
    if not isinstance(checks, list) or len(checks) < 3:
        raise ValueError(f"V2 case {case_id} must define at least 3 interpretation_checks")
    seen_check_ids: set[str] = set()
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError(f"V2 case {case_id} has a non-object interpretation check: {check!r}")
        _validate_v2_check(case_id, check)
        check_id = check["check_id"]
        if check_id in seen_check_ids:
            raise ValueError(f"V2 case {case_id} has duplicate check_id {check_id}")
        seen_check_ids.add(check_id)

    if not isinstance(case["case_rationale"], str) or not case["case_rationale"].strip():
        raise ValueError(f"V2 case {case_id} must include a non-empty case_rationale")

    if not isinstance(case["judge_focus"], list) or not all(isinstance(item, str) for item in case["judge_focus"]):
        raise ValueError(f"V2 case {case_id} must include a string list judge_focus")

    overall = case["overall_conclusion"]
    expected_uncertainty = case["expected_uncertainty"]
    if not isinstance(overall, dict):
        raise ValueError(f"V2 case {case_id} overall_conclusion must be an object")
    if not isinstance(expected_uncertainty, dict):
        raise ValueError(f"V2 case {case_id} expected_uncertainty must be an object")
    _validate_v2_answer_spec(case_id, "overall_conclusion", overall)
    _validate_v2_answer_spec(case_id, "expected_uncertainty", expected_uncertainty)

    base_case = deepcopy(stage2_base_cases[base_case_id])
    resolved = {
        "case_id": case_id,
        "benchmark_type": STAGE2_INTERPRETATION_V2_BENCHMARK,
        "base_case_id": base_case_id,
        "source_type": base_case["source_type"],
        "input_bundle": base_case["input_bundle"],
        "judge_focus": case["judge_focus"],
        "notes": case["notes"],
        "case_rationale": case["case_rationale"],
        "interpretation_checks": checks,
        "overall_conclusion": overall,
        "expected_uncertainty": expected_uncertainty,
    }
    return resolved


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    """Load and lightly validate a frozen benchmark case file."""
    case_path = Path(path)
    if not case_path.exists() and case_path.name == V3_CASE_FILENAME:
        return _build_stage2_interpretation_v3_cases()
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a JSON list in {case_path}")

    seen_ids: set[str] = set()
    resolved_cases: list[dict[str, Any]] = []
    stage2_base_cases: dict[str, dict[str, Any]] | None = None
    excerpt_library: dict[str, dict[str, Any]] | None = None
    for case in payload:
        if not isinstance(case, dict):
            raise ValueError(f"Case in {case_path} is not an object: {case!r}")
        benchmark_type = case.get("benchmark_type")
        if benchmark_type == STAGE2_INTERPRETATION_V2_BENCHMARK:
            required = _required_stage2_interpretation_v2_keys()
        elif benchmark_type == STAGE2_INTERPRETATION_V3_BENCHMARK:
            required = _required_stage2_interpretation_v3_keys()
        else:
            required = _required_stage2_case_keys()
        missing = required - set(case)
        if missing:
            raise ValueError(f"Case {case.get('case_id', '<unknown>')} missing keys: {sorted(missing)}")
        case_id = case["case_id"]
        if case_id in seen_ids:
            raise ValueError(f"Duplicate case_id {case_id} in {case_path}")
        seen_ids.add(case_id)
        if benchmark_type == STAGE2_INTERPRETATION_V2_BENCHMARK:
            if stage2_base_cases is None:
                stage2_base_cases = _load_stage2_base_case_map()
            resolved_cases.append(
                _resolve_stage2_interpretation_v2_case(
                    case,
                    stage2_base_cases=stage2_base_cases,
                )
            )
        elif benchmark_type == STAGE2_INTERPRETATION_V3_BENCHMARK:
            if excerpt_library is None:
                excerpt_library = load_skill_excerpt_library()
            if not isinstance(case.get("judge_focus"), list) or not all(
                isinstance(item, str) and item for item in case["judge_focus"]
            ):
                raise ValueError(f"V3 case {case_id} must include a string list judge_focus")
            if not isinstance(case.get("case_rationale"), str) or not case["case_rationale"].strip():
                raise ValueError(f"V3 case {case_id} must include a non-empty case_rationale")
            if not isinstance(case.get("evidence_refs"), dict) or not case["evidence_refs"]:
                raise ValueError(f"V3 case {case_id} must define evidence_refs")
            if not isinstance(case.get("skill_excerpt_ids"), list):
                raise ValueError(f"V3 case {case_id} must define skill_excerpt_ids")
            for excerpt_id in case["skill_excerpt_ids"]:
                if excerpt_id not in excerpt_library:
                    raise ValueError(f"V3 case {case_id} references unknown excerpt {excerpt_id}")
            probes = case.get("probes")
            if not isinstance(probes, list) or len(probes) != 3:
                raise ValueError(f"V3 case {case_id} must define exactly 3 probes")
            for probe in probes:
                _validate_v3_probe(case_id, probe, excerpt_library)
                for evidence_ref in probe["required_evidence_refs"]:
                    if evidence_ref not in case["evidence_refs"]:
                        raise ValueError(
                            f"V3 case {case_id} probe {probe.get('probe_id')} references unknown evidence ref {evidence_ref}"
                        )
            _validate_v3_secondary_conclusion(case_id, case["secondary_conclusion"])
            for evidence_ref in case["secondary_conclusion"]["required_evidence_refs"]:
                if evidence_ref not in case["evidence_refs"]:
                    raise ValueError(
                        f"V3 case {case_id} secondary_conclusion references unknown evidence ref {evidence_ref}"
                    )
            resolved_cases.append(case)
        else:
            resolved_cases.append(case)
    return resolved_cases


async def render_skill_prompt(
    base_prompt: str,
    skill_registry: dict[str, str],
    *,
    stage_hints: dict[str, str] | None = None,
) -> str:
    """Apply SkillLoadHarness to a base system prompt."""
    harness = SkillLoadHarness(
        skill_registry=skill_registry,
        stage_hints=stage_hints or {},
    )

    class _MockRequest:
        def __init__(self, content: str):
            self.system_message = SystemMessage(content=content)
            self.system_prompt = None

        def override(self, **kwargs):
            new = _MockRequest(base_prompt)
            for key, value in kwargs.items():
                setattr(new, key, value)
            return new

    captured = base_prompt

    async def _handler(req):
        nonlocal captured
        captured = str(req.system_message.content)
        return None

    await harness.abefore_agent(state=None, runtime=None)
    await harness.awrap_model_call(_MockRequest(base_prompt), _handler)
    return captured


def _skill_doc_path(skill_root: str) -> str:
    root = Path(skill_root)
    return str(root if root.name == "SKILL.md" else root / "SKILL.md")


def _load_skill_doc(skill_path: str, *, offset: int = 0, limit: int = 2000) -> str:
    return str(read_skill_file.invoke({"skill_path": skill_path, "offset": offset, "limit": limit}))


def preload_skill_guidance(skill_registry: dict[str, str], *, limit: int = 2000) -> str:
    """Load exposed skill documents into a prompt-ready guidance block."""
    if not skill_registry:
        return ""

    blocks: list[str] = []
    for skill_name, skill_root in skill_registry.items():
        skill_path = _skill_doc_path(skill_root)
        content = _load_skill_doc(skill_path, limit=limit)
        blocks.append(f"### {skill_name}\nPath: {skill_path}\n\n{content}")
    return "\n\n".join(blocks)


def append_preloaded_skill_guidance(
    system_prompt: str,
    *,
    variant: str,
    preloaded_guidance: str,
) -> str:
    """Attach preloaded skill content to the B arm only."""
    if variant == VARIANT_A or not preloaded_guidance.strip():
        return system_prompt
    return (
        f"{system_prompt}\n\n## Preloaded Skill Guidance\n"
        "The benchmark runtime has already loaded the exposed skill documents below. "
        "Use them as interpretation guidance only.\n\n"
        f"{preloaded_guidance}"
    )


def enforce_skill_read_requirement(
    system_prompt: str,
    *,
    variant: str,
    skill_registry: dict[str, str],
) -> str:
    """Strengthen B-arm prompts so exposed skills are actually loaded."""
    if variant == VARIANT_A or not skill_registry:
        return system_prompt

    required_calls = "\n".join(
        f'- `read_skill_file(skill_path="{_skill_doc_path(path)}")` for `{name}`'
        for name, path in skill_registry.items()
    )

    requirement = (
        "\n\n## Benchmark Skill-Read Requirement\n"
        "This benchmark arm exposes interpretation skills and their use is mandatory.\n"
        "Before you score the case, you MUST call `read_skill_file` exactly once for each exposed skill "
        "document listed below.\n"
        "Do not return your final JSON until every required skill document has been loaded.\n"
        "Treat the loaded skill documents as interpretation guidance only; do not invent facts beyond the "
        "user evidence.\n"
        "Required calls:\n"
        f"{required_calls}\n"
        "Skipping any required skill read makes the benchmark response incomplete."
    )
    return f"{system_prompt}{requirement}"


def _benchmark_json_schema_text(benchmark_type: str) -> str:
    if benchmark_type == STAGE2_INTERPRETATION_V3_BENCHMARK:
        return json.dumps(
            {
                "gene_symbol": "GENE",
                "probe_answers": [
                    {
                        "probe_id": "P1",
                        "answer": "suggestive",
                        "evidence_refs": ["E1", "E2"],
                        "justification": "...",
                    }
                ],
                "secondary_conclusion": {
                    "answer": "exploratory_target",
                    "evidence_refs": ["E3"],
                    "justification": "...",
                },
            },
            indent=2,
        )

    if benchmark_type == CHEMBL_MICRO_BENCHMARK:
        return json.dumps(
            {
                "gene_symbol": "GENE",
                "validated_track": {
                    "existing_drug_evidence": {"score": 0, "rationale": "..."},
                    "clinical_trial_activity": {"score": 0, "rationale": "..."},
                    "mechanism_relevance": {"score": 0, "rationale": "..."},
                    "safety_profile": {"score": 0, "rationale": "..."},
                },
                "summary": "...",
            },
            indent=2,
        )

    if benchmark_type == STAGE2_INTERPRETATION_V2_BENCHMARK:
        return json.dumps(
            {
                "gene_symbol": "GENE",
                "interpretation_checks": [
                    {
                        "check_id": "genetic_support",
                        "answer": "suggestive",
                        "justification": "...",
                    }
                ],
                "overall_conclusion": {
                    "answer": "exploratory_target",
                    "justification": "...",
                },
                "uncertainty": {
                    "answer": "medium",
                    "justification": "...",
                },
                "summary": "...",
            },
            indent=2,
        )

    return json.dumps(
        {
            "gene_symbol": "GENE",
            "validated_track": {
                "existing_drug_evidence": {"score": 0, "rationale": "..."},
                "clinical_trial_activity": {"score": 0, "rationale": "..."},
                "mechanism_relevance": {"score": 0, "rationale": "..."},
                "safety_profile": {"score": 0, "rationale": "..."},
            },
            "exploratory_track": {
                "gwas_genetic_support": {"score": 0, "rationale": "..."},
                "tractability": {"score": 0, "rationale": "..."},
                "biological_plausibility": {"score": 0, "rationale": "..."},
                "novelty_opportunity": {"score": 0, "rationale": "..."},
            },
            "classification": "validated_target",
            "priority": "medium",
            "summary": "...",
        },
        indent=2,
    )


def build_system_prompt(benchmark_type: str) -> str:
    """Build the benchmark system prompt."""
    if benchmark_type == STAGE2_INTERPRETATION_V3_BENCHMARK:
        return (
            "You are benchmarking whether relevant SKILL.md excerpts reduce targeted interpretation errors.\n\n"
            "Use only the frozen evidence bundle and the provided E* evidence references.\n"
            "If skill excerpts are present, use them as interpretation guidance only.\n"
            "Do not invent new database facts, trial phases, disease mappings, replication status, or approval scope.\n"
            "Answer exactly three probes and one secondary conclusion.\n"
            "For every answer, cite only the relevant E* evidence references from the prompt.\n"
            "Prefer conservative answers when the bundle is ambiguous.\n\n"
            "Primary goal:\n"
            "- Avoid targeted interpretation errors around GWAS strength, replication, disease alignment, approval scope,\n"
            "  predicted tractability, safety weighting, and uncertainty.\n"
            "- Keep justifications short, evidence-bound, and limited to the cited E* refs.\n\n"
            "Return a single JSON object and nothing else.\n"
            f"Schema:\n{_benchmark_json_schema_text(benchmark_type)}"
        )

    if benchmark_type == CHEMBL_MICRO_BENCHMARK:
        return (
            "You are benchmarking ChEMBL evidence interpretation for drug-target assessment.\n\n"
            "Use only the evidence in the user message.\n"
            "If skill documents are available, they are interpretation guidance only.\n"
            "Do not invent missing trial phases, approved indications, or activity semantics.\n\n"
            "Score the validated-track criteria using this scale:\n"
            "- existing_drug_evidence: none(0) | indirect_evidence(1) | Phase 1-2(2) | Phase 3+/approved(3)\n"
            "- clinical_trial_activity: no_trials(0) | few_early_phase(1) | multiple_or_advanced(2) | extensive(3)\n"
            "- mechanism_relevance: unclear(0) | plausible(1) | well_supported(2) | direct_mechanism(3)\n"
            "- safety_profile: major_concerns(-2) | moderate_concerns(-1) | minimal_or_none(0)\n\n"
            "Return a single JSON object and nothing else.\n"
            f"Schema:\n{_benchmark_json_schema_text(benchmark_type)}"
        )

    if benchmark_type == STAGE2_INTERPRETATION_V2_BENCHMARK:
        return (
            "You are benchmarking whether exposed SKILL.md guidance improves Stage 2 interpretation and evidence synthesis.\n\n"
            "Use only the evidence in the user message.\n"
            "If skill documents are available, they are interpretation guidance only.\n"
            "Do not invent any new database facts, trial phases, ontology mappings, or GWAS strength claims.\n"
            "Answer each interpretation check by choosing exactly one of the allowed labels for that check.\n"
            "Keep each justification short and evidence-bound.\n"
            "If the frozen bundle is ambiguous, reflect that in the uncertainty field rather than making a stronger claim.\n\n"
            "Primary goal:\n"
            "- Make careful interpretation calls on genetics, clinical precedence, safety, tractability, and disease alignment.\n"
            "- Avoid stronger-than-supported claims, especially around replication, disease matching, and approval status.\n\n"
            "Return a single JSON object and nothing else.\n"
            f"Schema:\n{_benchmark_json_schema_text(benchmark_type)}"
        )

    return (
        "You are benchmarking Stage 2 evidence synthesis for drug-target assessment.\n\n"
        "Use only the evidence in the user message.\n"
        "If skill documents are available, they are interpretation guidance only.\n"
        "Do not invent any new database facts, trial phases, ontology mappings, or GWAS strength claims.\n\n"
        "Validated-track scale:\n"
        "- existing_drug_evidence: none(0) | indirect_evidence(1) | Phase 1-2(2) | Phase 3+/approved(3)\n"
        "- clinical_trial_activity: no_trials(0) | few_early_phase(1) | multiple_or_advanced(2) | extensive(3)\n"
        "- mechanism_relevance: unclear(0) | plausible(1) | well_supported(2) | direct_mechanism(3)\n"
        "- safety_profile: major_concerns(-2) | moderate_concerns(-1) | minimal_or_none(0)\n\n"
        "Exploratory-track scale:\n"
        "- gwas_genetic_support: no_signal(0) | suggestive(1) | genome_wide_significant(2) | replicated(3)\n"
        "- tractability: unknown(0) | predicted(1) | clinical_precedent(2) | approved_modality(3)\n"
        "- biological_plausibility: weak(0) | moderate(1) | strong(2) | compelling_multi_evidence(3)\n"
        "- novelty_opportunity: well_established(0) | moderately_explored(1) | emerging(2) | novel(3)\n\n"
        "Classification:\n"
        "- validated_target: validated pass logic satisfied\n"
        "- exploratory_target: validated fails, exploratory passes\n"
        "- novel_candidate: both fail, but biological_plausibility >= 2 or novelty_opportunity >= 2\n"
        "- insufficient_evidence: none of the above\n\n"
        "Priority:\n"
        "- validated_target high if validated total >= 6, medium if >= 3\n"
        "- exploratory_target high if exploratory total >= 8, medium if >= 5\n"
        "- novel_candidate low\n"
        "- insufficient_evidence unranked\n\n"
        "Return a single JSON object and nothing else.\n"
        f"Schema:\n{_benchmark_json_schema_text(benchmark_type)}"
    )


def build_user_prompt(case: dict[str, Any]) -> str:
    """Create the case-specific user prompt."""
    bundle = json.dumps(case["input_bundle"], indent=2, ensure_ascii=False)
    focus = ", ".join(case.get("judge_focus", []))
    if case["benchmark_type"] == STAGE2_INTERPRETATION_V3_BENCHMARK:
        evidence_lines = [f"- {ref_id}: {text}" for ref_id, text in case["evidence_refs"].items()]
        probe_lines: list[str] = []
        for probe in case["probes"]:
            options = " | ".join(probe["options"])
            required_refs = ", ".join(probe["required_evidence_refs"])
            probe_lines.append(
                f"{probe['probe_id']} [{probe['error_family']}]\n"
                f"Question: {probe['question']}\n"
                f"Allowed answers: {options}\n"
                f"Relevant evidence refs: {required_refs}"
            )

        conclusion_options = " | ".join(case["secondary_conclusion"]["options"])
        conclusion_refs = ", ".join(case["secondary_conclusion"]["required_evidence_refs"])
        return (
            f"Case ID: {case['case_id']}\n"
            f"Benchmark type: {case['benchmark_type']}\n"
            f"Judge focus: {focus}\n"
            f"Notes: {case['notes']}\n"
            f"Case rationale: {case['case_rationale']}\n\n"
            "Evidence references:\n"
            f"{chr(10).join(evidence_lines)}\n\n"
            "Answer these probes using only the cited E* evidence refs:\n"
            f"{chr(10).join(probe_lines)}\n\n"
            "Secondary conclusion:\n"
            f"Question: {case['secondary_conclusion']['question']}\n"
            f"Allowed answers: {conclusion_options}\n"
            f"Relevant evidence refs: {conclusion_refs}\n\n"
            f"Evidence bundle:\n{bundle}"
        )
    if case["benchmark_type"] == STAGE2_INTERPRETATION_V2_BENCHMARK:
        check_lines: list[str] = []
        for index, check in enumerate(case["interpretation_checks"], start=1):
            options = " | ".join(check["options"])
            check_lines.append(
                f"{index}. `{check['check_id']}`\n"
                f"   Question: {check['question']}\n"
                f"   Allowed answers: {options}"
            )

        overall_options = " | ".join(case["overall_conclusion"]["options"])
        uncertainty_options = " | ".join(case["expected_uncertainty"]["options"])
        return (
            f"Case ID: {case['case_id']}\n"
            f"Benchmark type: {case['benchmark_type']}\n"
            f"Judge focus: {focus}\n"
            f"Notes: {case['notes']}\n"
            f"Case rationale: {case['case_rationale']}\n\n"
            "Evaluate the frozen evidence bundle below.\n"
            "Use only the provided evidence and return JSON only.\n\n"
            "Interpretation checks:\n"
            f"{chr(10).join(check_lines)}\n\n"
            "Overall conclusion:\n"
            f"- Question: {case['overall_conclusion']['question']}\n"
            f"- Allowed answers: {overall_options}\n\n"
            "Uncertainty call:\n"
            f"- Question: {case['expected_uncertainty']['question']}\n"
            f"- Allowed answers: {uncertainty_options}\n\n"
            f"Evidence bundle:\n{bundle}"
        )
    return (
        f"Case ID: {case['case_id']}\n"
        f"Benchmark type: {case['benchmark_type']}\n"
        f"Judge focus: {focus}\n"
        f"Notes: {case['notes']}\n\n"
        "Evaluate the frozen evidence bundle below.\n"
        "Use only the provided evidence and return JSON only.\n\n"
        f"Evidence bundle:\n{bundle}"
    )


def _coerce_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    return str(content)


def _strip_code_fences(text: str) -> str:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    return text


def _extract_first_json_object(text: str) -> str:
    decoder = json.JSONDecoder()
    for start, char in enumerate(text):
        if char != "{":
            continue
        try:
            _, end = decoder.raw_decode(text[start:])
            return text[start : start + end]
        except json.JSONDecodeError:
            continue
    raise ValueError("No JSON object found in model output")


def parse_benchmark_output(content: Any) -> dict[str, Any]:
    """Parse a benchmark model response into a JSON object."""
    text = _coerce_text(content).strip()
    if not text:
        raise ValueError("Empty model output")

    candidate = _strip_code_fences(text).strip()
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    candidate = _extract_first_json_object(text)
    repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
    parsed = json.loads(repaired)
    if not isinstance(parsed, dict):
        raise ValueError("Parsed model output is not an object")
    return parsed


def _extract_score(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, dict):
        score = value.get("score")
        if isinstance(score, bool):
            return int(score)
        if isinstance(score, (int, float)):
            return int(score)
    return None


def _collect_rationale_text(parsed_output: dict[str, Any]) -> str:
    parts: list[str] = []
    checks = parsed_output.get("interpretation_checks")
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, dict):
                justification = check.get("justification")
                if justification:
                    parts.append(str(justification))
    for key in ("overall_conclusion", "uncertainty"):
        payload = parsed_output.get(key)
        if isinstance(payload, dict):
            justification = payload.get("justification")
            if justification:
                parts.append(str(justification))
    for track_name in ("validated_track", "exploratory_track"):
        track = parsed_output.get(track_name, {})
        if isinstance(track, dict):
            for criterion in track.values():
                if isinstance(criterion, dict):
                    rationale = criterion.get("rationale")
                    if rationale:
                        parts.append(str(rationale))
    summary = parsed_output.get("summary")
    if summary:
        parts.append(str(summary))
    return "\n".join(parts).lower()


def _score_anchor_coverage(case: dict[str, Any], parsed_output: dict[str, Any]) -> float | None:
    anchors = case.get("rationale_anchors") or []
    if case.get("benchmark_type") == STAGE2_INTERPRETATION_V2_BENCHMARK:
        anchors = []
        for check in case.get("interpretation_checks", []):
            anchors.extend(check.get("required_evidence_anchors", []))
        anchors.extend(case.get("overall_conclusion", {}).get("required_evidence_anchors", []))
        anchors.extend(case.get("expected_uncertainty", {}).get("required_evidence_anchors", []))
    if not anchors:
        return None
    text = _collect_rationale_text(parsed_output)
    hits = sum(1 for anchor in anchors if str(anchor).lower() in text)
    return hits / len(anchors)


def _answers_by_check_id(parsed_output: dict[str, Any]) -> dict[str, dict[str, Any]]:
    checks = parsed_output.get("interpretation_checks")
    if not isinstance(checks, list):
        return {}
    check_map: dict[str, dict[str, Any]] = {}
    for item in checks:
        if not isinstance(item, dict):
            continue
        check_id = item.get("check_id")
        if isinstance(check_id, str) and check_id:
            check_map[check_id] = item
    return check_map


def _answers_by_probe_id(parsed_output: dict[str, Any]) -> dict[str, dict[str, Any]]:
    probes = parsed_output.get("probe_answers")
    if not isinstance(probes, list):
        return {}
    probe_map: dict[str, dict[str, Any]] = {}
    for item in probes:
        if not isinstance(item, dict):
            continue
        probe_id = item.get("probe_id")
        if isinstance(probe_id, str) and probe_id:
            probe_map[probe_id] = item
    return probe_map


def _v3_support_score(
    *,
    answer: str,
    gold_label: str,
    conservative_labels: list[str],
    target_error_labels: list[str],
    options: list[str],
) -> float:
    if answer == gold_label:
        return 1.0
    if answer in conservative_labels:
        return 0.75
    if answer in target_error_labels:
        return 0.0
    if answer in options:
        return 0.25
    return 0.0


def score_stage2_interpretation_v3_output(
    case: dict[str, Any],
    parsed_output: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(parsed_output, dict):
        return {
            "malformed_output": True,
            "weighted_probe_error_score": 1.0,
            "probe_support_score": 0.0,
            "targeted_error_count": 0,
            "primary_probe_target_error": False,
            "primary_probe_target_error_rate": 0.0,
            "all_probe_target_error_rate": 0.0,
            "major_error_rate": 1.0,
            "evidence_ref_validity_rate": 0.0,
            "secondary_conclusion_accuracy": 0.0,
            "validation_errors": ["No parsed JSON output"],
            "error_family_breakdown": {},
        }

    validation_errors: list[str] = []
    predicted_probes = _answers_by_probe_id(parsed_output)
    support_scores: list[float] = []
    targeted_error_count = 0
    primary_probe_target_error = False
    valid_ref_count = 0
    cited_ref_count = 0
    error_family_breakdown: dict[str, float] = {}

    for probe in case["probes"]:
        probe_id = probe["probe_id"]
        predicted = predicted_probes.get(probe_id)
        if not isinstance(predicted, dict):
            validation_errors.append(f"Missing probe {probe_id}")
            support_scores.append(0.0)
            error_family_breakdown[probe.get("error_family", probe_id)] = 1.0
            if probe_id == "P1":
                primary_probe_target_error = True
            continue

        answer = predicted.get("answer")
        if answer not in probe["options"]:
            validation_errors.append(f"Invalid answer for probe {probe_id}")
        evidence_refs = predicted.get("evidence_refs")
        if not isinstance(evidence_refs, list) or not all(isinstance(item, str) for item in evidence_refs):
            validation_errors.append(f"Invalid evidence_refs for probe {probe_id}")
            evidence_refs = []
        justification = predicted.get("justification")
        if not isinstance(justification, str) or not justification.strip():
            validation_errors.append(f"Missing justification for probe {probe_id}")

        support_score = _v3_support_score(
            answer=str(answer),
            gold_label=probe["gold_label"],
            conservative_labels=probe["conservative_labels"],
            target_error_labels=probe["target_error_labels"],
            options=probe["options"],
        )
        support_scores.append(support_score)
        is_target_error = answer in probe["target_error_labels"]
        if is_target_error:
            targeted_error_count += 1
        if probe_id == "P1":
            primary_probe_target_error = is_target_error
        error_family_breakdown[probe.get("error_family", probe_id)] = 1.0 - support_score

        for ref in evidence_refs:
            cited_ref_count += 1
            if ref in case["evidence_refs"] and ref in probe["required_evidence_refs"]:
                valid_ref_count += 1

    secondary_accuracy = 0.0
    secondary = parsed_output.get("secondary_conclusion")
    if not isinstance(secondary, dict):
        validation_errors.append("Missing secondary_conclusion")
    else:
        answer = secondary.get("answer")
        if answer not in case["secondary_conclusion"]["options"]:
            validation_errors.append("Invalid secondary_conclusion answer")
        evidence_refs = secondary.get("evidence_refs")
        if not isinstance(evidence_refs, list) or not all(isinstance(item, str) for item in evidence_refs):
            validation_errors.append("Invalid secondary_conclusion evidence_refs")
            evidence_refs = []
        justification = secondary.get("justification")
        if not isinstance(justification, str) or not justification.strip():
            validation_errors.append("Missing secondary_conclusion justification")
        secondary_accuracy = 1.0 if answer == case["secondary_conclusion"]["gold_label"] else 0.0
        for ref in evidence_refs:
            cited_ref_count += 1
            if ref in case["evidence_refs"] and ref in case["secondary_conclusion"]["required_evidence_refs"]:
                valid_ref_count += 1

    weighted_probe_error_score = 0.0
    for index, score in enumerate(support_scores, start=1):
        weighted_probe_error_score += V3_PROBE_WEIGHTS.get(f"P{index}", 0.0) * (1.0 - score)

    probe_count = max(1, len(case["probes"]))
    return {
        "malformed_output": bool(validation_errors),
        "weighted_probe_error_score": weighted_probe_error_score,
        "probe_support_score": _mean(support_scores) or 0.0,
        "targeted_error_count": targeted_error_count,
        "primary_probe_target_error": primary_probe_target_error,
        "primary_probe_target_error_rate": 1.0 if primary_probe_target_error else 0.0,
        "all_probe_target_error_rate": targeted_error_count / probe_count,
        "major_error_rate": 1.0 if primary_probe_target_error else 0.0,
        "evidence_ref_validity_rate": (valid_ref_count / cited_ref_count) if cited_ref_count else 0.0,
        "secondary_conclusion_accuracy": secondary_accuracy,
        "validation_errors": validation_errors,
        "error_family_breakdown": error_family_breakdown,
    }


def score_stage2_interpretation_v2_output(
    case: dict[str, Any],
    parsed_output: dict[str, Any] | None,
) -> dict[str, Any]:
    """Score a targeted interpretation output against V2 gold labels."""
    if not isinstance(parsed_output, dict):
        return {
            "malformed_output": True,
            "interpretation_score": 0.0,
            "exact_check_count": 0,
            "exact_check_accuracy": 0.0,
            "partial_credit_accuracy": 0.0,
            "overclaim_rate": 0.0,
            "overall_conclusion_correct": False,
            "uncertainty_correct": False,
            "validation_errors": ["No parsed JSON output"],
            "rationale_anchor_coverage": None,
        }

    validation_errors: list[str] = []
    exact_count = 0
    partial_credit_total = 0.0
    overclaim_count = 0
    checks = case.get("interpretation_checks", [])
    predicted_checks = _answers_by_check_id(parsed_output)

    for check in checks:
        check_id = check["check_id"]
        predicted = predicted_checks.get(check_id)
        if not isinstance(predicted, dict):
            validation_errors.append(f"Missing interpretation check {check_id}")
            continue
        answer = predicted.get("answer")
        justification = predicted.get("justification")
        if answer not in check["options"]:
            validation_errors.append(f"Invalid answer for {check_id}")
            continue
        if not isinstance(justification, str) or not justification.strip():
            validation_errors.append(f"Missing justification for {check_id}")
        if answer == check["gold_label"]:
            exact_count += 1
            partial_credit_total += 1.0
        elif answer in check.get("partial_credit_labels", []):
            partial_credit_total += 0.5
        if answer in check.get("overclaim_labels", []):
            overclaim_count += 1

    overall = parsed_output.get("overall_conclusion")
    overall_correct = False
    if not isinstance(overall, dict):
        validation_errors.append("Missing overall_conclusion")
    else:
        if overall.get("answer") not in case["overall_conclusion"]["options"]:
            validation_errors.append("Invalid overall_conclusion answer")
        if not isinstance(overall.get("justification"), str) or not overall.get("justification", "").strip():
            validation_errors.append("Missing overall_conclusion justification")
        overall_correct = overall.get("answer") == case["overall_conclusion"]["gold_label"]

    uncertainty = parsed_output.get("uncertainty")
    uncertainty_correct = False
    if not isinstance(uncertainty, dict):
        validation_errors.append("Missing uncertainty")
    else:
        if uncertainty.get("answer") not in case["expected_uncertainty"]["options"]:
            validation_errors.append("Invalid uncertainty answer")
        if not isinstance(uncertainty.get("justification"), str) or not uncertainty.get("justification", "").strip():
            validation_errors.append("Missing uncertainty justification")
        uncertainty_correct = uncertainty.get("answer") == case["expected_uncertainty"]["gold_label"]

    check_count = max(1, len(checks))
    partial_credit_accuracy = partial_credit_total / check_count
    interpretation_score = (
        partial_credit_accuracy
        + (1.0 if overall_correct else 0.0)
        + (1.0 if uncertainty_correct else 0.0)
    ) / 3.0
    return {
        "malformed_output": bool(validation_errors),
        "interpretation_score": interpretation_score,
        "check_count": check_count,
        "exact_check_count": exact_count,
        "exact_check_accuracy": exact_count / check_count,
        "partial_credit_accuracy": partial_credit_accuracy,
        "overclaim_rate": overclaim_count / check_count,
        "overall_conclusion_correct": overall_correct,
        "uncertainty_correct": uncertainty_correct,
        "validation_errors": validation_errors,
        "rationale_anchor_coverage": _score_anchor_coverage(case, parsed_output),
    }


def score_stage2_output(
    case: dict[str, Any],
    parsed_output: dict[str, Any] | None,
) -> dict[str, Any]:
    """Score a Stage 2 synthesis output against a frozen gold case."""
    if not isinstance(parsed_output, dict):
        return {
            "malformed_output": True,
            "exact_match_count": 0,
            "near_match_count": 0,
            "exact_match_rate": 0.0,
            "near_match_rate": 0.0,
            "classification_correct": False,
            "priority_correct": False,
            "validation_errors": ["No parsed JSON output"],
            "rationale_anchor_coverage": None,
        }

    validation_errors = validate_rubric_assessment(parsed_output)
    exact = 0
    near = 0

    for criterion in VALIDATED_CRITERIA:
        gold = _extract_score(case["gold_assessment"]["validated_track"].get(criterion))
        pred = _extract_score(parsed_output.get("validated_track", {}).get(criterion))
        if pred is None or gold is None:
            continue
        if pred == gold:
            exact += 1
        if abs(pred - gold) <= 1:
            near += 1

    for criterion in EXPLORATORY_CRITERIA:
        gold = _extract_score(case["gold_assessment"]["exploratory_track"].get(criterion))
        pred = _extract_score(parsed_output.get("exploratory_track", {}).get(criterion))
        if pred is None or gold is None:
            continue
        if pred == gold:
            exact += 1
        if abs(pred - gold) <= 1:
            near += 1

    derived_classification = classify_target(parsed_output) if not validation_errors else None
    derived_priority = compute_priority(parsed_output) if not validation_errors else None

    classification_correct = (
        parsed_output.get("classification") == case["expected_classification"]
        and derived_classification == case["expected_classification"]
    )
    priority_correct = (
        parsed_output.get("priority") == case["expected_priority"]
        and derived_priority == case["expected_priority"]
    )

    return {
        "malformed_output": bool(validation_errors),
        "exact_match_count": exact,
        "near_match_count": near,
        "exact_match_rate": exact / 8.0,
        "near_match_rate": near / 8.0,
        "classification_correct": classification_correct,
        "priority_correct": priority_correct,
        "validation_errors": validation_errors,
        "rationale_anchor_coverage": _score_anchor_coverage(case, parsed_output),
    }


def score_chembl_output(
    case: dict[str, Any],
    parsed_output: dict[str, Any] | None,
) -> dict[str, Any]:
    """Score a ChEMBL supplementary output against a frozen gold case."""
    if not isinstance(parsed_output, dict):
        return {
            "malformed_output": True,
            "exact_match_count": 0,
            "near_match_count": 0,
            "exact_match_rate": 0.0,
            "near_match_rate": 0.0,
            "validation_errors": ["No parsed JSON output"],
            "rationale_anchor_coverage": None,
        }

    exact = 0
    near = 0
    validation_errors: list[str] = []
    track = parsed_output.get("validated_track")
    if not isinstance(track, dict):
        validation_errors.append("Missing validated_track")
        track = {}

    for criterion in VALIDATED_CRITERIA:
        gold = _extract_score(case["gold_assessment"]["validated_track"].get(criterion))
        pred = _extract_score(track.get(criterion))
        if pred is None or gold is None:
            validation_errors.append(f"Missing or invalid score for {criterion}")
            continue
        if pred == gold:
            exact += 1
        if abs(pred - gold) <= 1:
            near += 1

    return {
        "malformed_output": bool(validation_errors),
        "exact_match_count": exact,
        "near_match_count": near,
        "exact_match_rate": exact / 4.0,
        "near_match_rate": near / 4.0,
        "validation_errors": validation_errors,
        "rationale_anchor_coverage": _score_anchor_coverage(case, parsed_output),
    }


def _token_usage_from_ai_message(message: AIMessage) -> dict[str, int]:
    usage = getattr(message, "usage_metadata", None) or {}
    if usage:
        return {
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
        }

    response_metadata = getattr(message, "response_metadata", None) or {}
    token_usage = response_metadata.get("token_usage") or {}
    return {
        "input_tokens": int(token_usage.get("prompt_tokens", 0) or 0),
        "output_tokens": int(token_usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(token_usage.get("total_tokens", 0) or 0),
    }


async def run_tool_loop(
    llm: Any,
    *,
    system_prompt: str,
    user_prompt: str,
    max_round_trips: int = 4,
) -> dict[str, Any]:
    """Run a minimal tool-calling loop with `read_skill_file`."""
    llm_with_tools = llm.bind_tools([read_skill_file])
    messages: list[Any] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    tool_history: list[dict[str, Any]] = []
    final_message: AIMessage | None = None

    for _ in range(max_round_trips):
        response = await llm_with_tools.ainvoke(messages)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=_coerce_text(getattr(response, "content", response)))
        final_message = response
        messages.append(response)

        if not response.tool_calls:
            break

        for tool_call in response.tool_calls:
            tool_call_id = tool_call.get("id") or f"tool-call-{len(tool_history)}"
            tool_name = tool_call.get("name")
            tool_args = tool_call.get("args", {})

            if tool_name != read_skill_file.name:
                error_text = f"Unsupported tool requested: {tool_name}"
                tool_history.append(
                    {
                        "name": tool_name,
                        "args": tool_args,
                        "content_preview": error_text,
                    }
                )
                messages.append(ToolMessage(content=error_text, tool_call_id=tool_call_id))
                continue

            if not isinstance(tool_args, dict):
                try:
                    tool_args = json.loads(tool_args)
                except Exception:
                    tool_args = {"skill_path": str(tool_args)}

            result = await asyncio.to_thread(read_skill_file.invoke, tool_args)
            tool_history.append(
                {
                    "name": tool_name,
                    "args": tool_args,
                    "content_preview": str(result)[:240],
                }
            )
            messages.append(ToolMessage(content=str(result), tool_call_id=tool_call_id))

    if final_message is None:
        raise RuntimeError("Model produced no response")

    return {
        "final_text": _coerce_text(final_message.content),
        "tool_history": tool_history,
        "token_usage": _token_usage_from_ai_message(final_message),
    }


async def run_single_trial(
    *,
    llm: Any,
    case: dict[str, Any],
    variant: str,
) -> dict[str, Any]:
    """Run one benchmark trial for a single case and variant."""
    benchmark_type = case["benchmark_type"]
    if benchmark_type == STAGE2_INTERPRETATION_V3_BENCHMARK:
        skill_registry = {}
        stage_hints = {}
    elif variant == VARIANT_A:
        skill_registry = {}
        stage_hints = {}
    elif benchmark_type == CHEMBL_MICRO_BENCHMARK:
        skill_registry = CHEMBL_SKILL_REGISTRY
        stage_hints = CHEMBL_STAGE_HINTS
    else:
        skill_registry = MAIN_STAGE2_SKILL_REGISTRY
        stage_hints = {}

    base_system_prompt = build_system_prompt(benchmark_type)
    if benchmark_type == STAGE2_INTERPRETATION_V3_BENCHMARK:
        system_prompt = base_system_prompt
        if variant == VARIANT_B:
            excerpt_guidance = build_case_excerpt_guidance(case)
            if excerpt_guidance:
                system_prompt = f"{system_prompt}\n\n{excerpt_guidance}"
    else:
        system_prompt = await render_skill_prompt(
            base_system_prompt,
            skill_registry=skill_registry,
            stage_hints=stage_hints,
        )
        preloaded_guidance = preload_skill_guidance(skill_registry)
        system_prompt = append_preloaded_skill_guidance(
            system_prompt,
            variant=variant,
            preloaded_guidance=preloaded_guidance,
        )
    user_prompt = build_user_prompt(case)

    start = time.monotonic()
    error: str | None = None
    parsed_output: dict[str, Any] | None = None
    model_result: dict[str, Any] = {
        "final_text": "",
        "tool_history": [],
        "token_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
    }

    try:
        model_result = await run_tool_loop(
            llm,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        parsed_output = parse_benchmark_output(model_result["final_text"])
    except Exception as exc:
        error = str(exc)

    if benchmark_type == STAGE2_INTERPRETATION_V3_BENCHMARK:
        metrics = score_stage2_interpretation_v3_output(case, parsed_output)
    elif benchmark_type == STAGE2_INTERPRETATION_V2_BENCHMARK:
        metrics = score_stage2_interpretation_v2_output(case, parsed_output)
    elif benchmark_type == CHEMBL_MICRO_BENCHMARK:
        metrics = score_chembl_output(case, parsed_output)
    else:
        metrics = score_stage2_output(case, parsed_output)

    return {
        "case_id": case["case_id"],
        "benchmark_type": benchmark_type,
        "variant": variant,
        "latency_s": time.monotonic() - start,
        "raw_output": model_result["final_text"],
        "parsed_output": parsed_output,
        "tool_history": model_result["tool_history"],
        "token_usage": model_result["token_usage"],
        "metrics": metrics,
        "error": error,
    }


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return float(mean(values))


def _primary_trial_score(trial: dict[str, Any]) -> float:
    metrics = trial["metrics"]
    if "weighted_probe_error_score" in metrics:
        return float(1.0 - metrics["weighted_probe_error_score"])
    if "interpretation_score" in metrics:
        return float(metrics["interpretation_score"])
    return float(metrics.get("exact_match_rate", 0.0))


def _summarize_stage2_interpretation_v3_trials(trials: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "benchmark_type": STAGE2_INTERPRETATION_V3_BENCHMARK,
        "primary_metric": "weighted_probe_error_score",
        "pair_unit": "model_case",
        "trial_count": len(trials),
        "variants": {},
        "paired_tests": {},
    }

    for variant in (VARIANT_A, VARIANT_B):
        variant_trials = [trial for trial in trials if trial["variant"] == variant]
        metrics = [trial["metrics"] for trial in variant_trials]
        summary["variants"][variant] = {
            "n": len(variant_trials),
            "weighted_probe_error_score_mean": _mean([m["weighted_probe_error_score"] for m in metrics]),
            "probe_support_score_mean": _mean([m.get("probe_support_score", 0.0) for m in metrics]),
            "primary_probe_target_error_rate_mean": _mean([m["primary_probe_target_error_rate"] for m in metrics]),
            "all_probe_target_error_rate_mean": _mean([m["all_probe_target_error_rate"] for m in metrics]),
            "major_error_rate_mean": _mean([m["major_error_rate"] for m in metrics]),
            "evidence_ref_validity_rate_mean": _mean([m["evidence_ref_validity_rate"] for m in metrics]),
            "secondary_conclusion_accuracy": _mean([m["secondary_conclusion_accuracy"] for m in metrics]),
            "malformed_rate": _mean([1.0 if m["malformed_output"] else 0.0 for m in metrics]),
            "latency_s_mean": _mean([trial["latency_s"] for trial in variant_trials]),
            "tool_call_mean": _mean([float(len(trial["tool_history"])) for trial in variant_trials]),
            "total_tokens_mean": _mean(
                [float(trial["token_usage"].get("total_tokens", 0)) for trial in variant_trials]
            ),
        }

    pairs: dict[tuple[str, str], dict[str, list[float]]] = {}
    for trial in trials:
        model = str(trial.get("model", ""))
        key = (model, trial["case_id"])
        pairs.setdefault(key, {VARIANT_A: [], VARIANT_B: []})[trial["variant"]].append(
            float(trial["metrics"]["weighted_probe_error_score"])
        )

    a_values: list[float] = []
    b_values: list[float] = []
    for pair in pairs.values():
        if pair[VARIANT_A] and pair[VARIANT_B]:
            a_values.append(float(mean(pair[VARIANT_A])))
            b_values.append(float(mean(pair[VARIANT_B])))

    summary["paired_tests"]["weighted_probe_error_score_case_level"] = {
        "pair_unit_count": len(a_values),
        "delta_mean": _mean([a - b for a, b in zip(a_values, b_values)]),
        "wilcoxon_pvalue": (
            float(wilcoxon(a_values, b_values).pvalue)
            if wilcoxon is not None and len(a_values) > 1 and any(a != b for a, b in zip(a_values, b_values))
            else None
        ),
    }
    return summary


def _summarize_stage2_interpretation_v2_trials(trials: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "benchmark_type": STAGE2_INTERPRETATION_V2_BENCHMARK,
        "primary_metric": "interpretation_score",
        "pair_unit": "model_case",
        "trial_count": len(trials),
        "variants": {},
        "paired_tests": {},
    }

    for variant in (VARIANT_A, VARIANT_B):
        variant_trials = [trial for trial in trials if trial["variant"] == variant]
        metrics = [trial["metrics"] for trial in variant_trials]
        summary["variants"][variant] = {
            "n": len(variant_trials),
            "interpretation_score_mean": _mean([m["interpretation_score"] for m in metrics]),
            "exact_check_accuracy_mean": _mean([m["exact_check_accuracy"] for m in metrics]),
            "partial_credit_accuracy_mean": _mean([m["partial_credit_accuracy"] for m in metrics]),
            "overall_conclusion_accuracy": _mean(
                [1.0 if m.get("overall_conclusion_correct") else 0.0 for m in metrics]
            ),
            "uncertainty_accuracy": _mean([1.0 if m.get("uncertainty_correct") else 0.0 for m in metrics]),
            "overclaim_rate_mean": _mean([m["overclaim_rate"] for m in metrics]),
            "malformed_rate": _mean([1.0 if m["malformed_output"] else 0.0 for m in metrics]),
            "anchor_coverage_mean": _mean(
                [m["rationale_anchor_coverage"] for m in metrics if m["rationale_anchor_coverage"] is not None]
            ),
            "latency_s_mean": _mean([trial["latency_s"] for trial in variant_trials]),
            "tool_call_mean": _mean([float(len(trial["tool_history"])) for trial in variant_trials]),
            "total_tokens_mean": _mean(
                [float(trial["token_usage"].get("total_tokens", 0)) for trial in variant_trials]
            ),
        }

    pairs: dict[tuple[str, str], dict[str, list[float]]] = {}
    for trial in trials:
        model = str(trial.get("model", ""))
        key = (model, trial["case_id"])
        pairs.setdefault(key, {VARIANT_A: [], VARIANT_B: []})[trial["variant"]].append(_primary_trial_score(trial))

    a_values: list[float] = []
    b_values: list[float] = []
    for pair in pairs.values():
        if pair[VARIANT_A] and pair[VARIANT_B]:
            a_values.append(float(mean(pair[VARIANT_A])))
            b_values.append(float(mean(pair[VARIANT_B])))

    summary["paired_tests"]["interpretation_score_case_level"] = {
        "pair_unit_count": len(a_values),
        "delta_mean": _mean([b - a for a, b in zip(a_values, b_values)]),
        "wilcoxon_pvalue": (
            float(wilcoxon(a_values, b_values).pvalue)
            if wilcoxon is not None and len(a_values) > 1 and any(a != b for a, b in zip(a_values, b_values))
            else None
        ),
    }
    return summary


def summarize_trials(trials: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate deterministic trial metrics by variant."""
    if trials and trials[0].get("benchmark_type") == STAGE2_INTERPRETATION_V3_BENCHMARK:
        return _summarize_stage2_interpretation_v3_trials(trials)
    if trials and trials[0].get("benchmark_type") == STAGE2_INTERPRETATION_V2_BENCHMARK:
        return _summarize_stage2_interpretation_v2_trials(trials)

    summary: dict[str, Any] = {
        "benchmark_type": trials[0].get("benchmark_type") if trials else None,
        "trial_count": len(trials),
        "variants": {},
        "paired_tests": {},
    }

    for variant in (VARIANT_A, VARIANT_B):
        variant_trials = [trial for trial in trials if trial["variant"] == variant]
        metrics = [trial["metrics"] for trial in variant_trials]
        summary["variants"][variant] = {
            "n": len(variant_trials),
            "exact_match_rate_mean": _mean([m["exact_match_rate"] for m in metrics]),
            "near_match_rate_mean": _mean([m["near_match_rate"] for m in metrics]),
            "classification_accuracy": _mean(
                [1.0 if m.get("classification_correct") else 0.0 for m in metrics if "classification_correct" in m]
            ),
            "priority_accuracy": _mean(
                [1.0 if m.get("priority_correct") else 0.0 for m in metrics if "priority_correct" in m]
            ),
            "malformed_rate": _mean([1.0 if m["malformed_output"] else 0.0 for m in metrics]),
            "anchor_coverage_mean": _mean(
                [m["rationale_anchor_coverage"] for m in metrics if m["rationale_anchor_coverage"] is not None]
            ),
            "latency_s_mean": _mean([trial["latency_s"] for trial in variant_trials]),
            "tool_call_mean": _mean([float(len(trial["tool_history"])) for trial in variant_trials]),
            "total_tokens_mean": _mean(
                [float(trial["token_usage"].get("total_tokens", 0)) for trial in variant_trials]
            ),
        }

    pairs: dict[tuple[str, int], dict[str, float]] = {}
    for trial in trials:
        repeat_index = int(trial.get("repeat_index", 0))
        pairs.setdefault((trial["case_id"], repeat_index), {})[trial["variant"]] = trial["metrics"]["exact_match_rate"]

    a_values: list[float] = []
    b_values: list[float] = []
    for pair in pairs.values():
        if VARIANT_A in pair and VARIANT_B in pair:
            a_values.append(pair[VARIANT_A])
            b_values.append(pair[VARIANT_B])

    if a_values and b_values and len(a_values) == len(b_values):
        summary["paired_tests"]["exact_match_rate"] = {
            "delta_mean": _mean([b - a for a, b in zip(a_values, b_values)]),
            "wilcoxon_pvalue": (
                float(wilcoxon(a_values, b_values).pvalue)
                if wilcoxon is not None and len(a_values) > 1 and any(a != b for a, b in zip(a_values, b_values))
                else None
            ),
        }

    return summary


def _build_research_judge_prompt(
    *,
    case: dict[str, Any],
    prompt_a: dict[str, Any],
    prompt_b: dict[str, Any],
) -> str:
    if case["benchmark_type"] == STAGE2_INTERPRETATION_V3_BENCHMARK:
        probe_lines = []
        for probe in case["probes"]:
            probe_lines.append(
                f"{probe['probe_id']} [{probe['error_family']}]\n"
                f"Question: {probe['question']}\n"
                f"Allowed answers: {' | '.join(probe['options'])}\n"
                f"Relevant evidence refs: {', '.join(probe['required_evidence_refs'])}"
            )
        evidence_refs = "\n".join(f"- {ref_id}: {text}" for ref_id, text in case["evidence_refs"].items())
        return (
            "You are a blinded research judge evaluating two targeted interpretation outputs.\n"
            "Judge only targeted interpretation errors, evidence grounding, and overclaim restraint.\n"
            "Ignore writing style.\n\n"
            "Return JSON only with this schema:\n"
            "{\n"
            '  "output_a": {"targeted_error_probe_ids": ["P1"], "grounding": 0, "unsupported_claim_penalty": 0, "major_error": false, "notes": "..."},\n'
            '  "output_b": {"targeted_error_probe_ids": [], "grounding": 0, "unsupported_claim_penalty": 0, "major_error": false, "notes": "..."},\n'
            '  "confidence": "low",\n'
            '  "rationale": "..."\n'
            "}\n\n"
            f"Case ID: {case['case_id']}\n"
            f"Judge focus: {', '.join(case.get('judge_focus', []))}\n"
            f"Case rationale: {case.get('case_rationale', '')}\n\n"
            f"Evidence references:\n{evidence_refs}\n\n"
            "Probe definitions:\n"
            f"{chr(10).join(probe_lines)}\n\n"
            f"Output A:\n{prompt_a['raw_output']}\n\n"
            f"Output B:\n{prompt_b['raw_output']}\n"
        )
    if case["benchmark_type"] == STAGE2_INTERPRETATION_V2_BENCHMARK:
        return (
            "You are a blinded research judge evaluating two targeted interpretation outputs.\n"
            "Score each output independently against the frozen evidence bundle.\n"
            "Judge only interpretation correctness, evidence grounding, and restraint against overclaiming.\n"
            "Do not compare writing style.\n\n"
            "Rubric:\n"
            "- grounding: 0..3\n"
            "  0 = detached from the bundle\n"
            "  1 = partly grounded with notable omissions\n"
            "  2 = mostly grounded with minor gaps\n"
            "  3 = strongly grounded and evidence-faithful\n"
            "- rubric_alignment: 0..3\n"
            "  0 = interpretation checks are substantially misread\n"
            "  1 = partially aligned with important interpretation mistakes\n"
            "  2 = mostly aligned with minor mistakes\n"
            "  3 = strongly aligned with the benchmark interpretation rubric\n"
            "- unsupported_claim_penalty: 0 | -1 | -2\n"
            "  0 = no unsupported claims\n"
            "  -1 = minor stronger-than-supported claim\n"
            "  -2 = material overclaiming or disease-mismatch inflation\n"
            "- major_error: true | false\n"
            "  true only for a material factual or interpretive error\n\n"
            "Return JSON only with this schema:\n"
            "{\n"
            '  "output_a": {"grounding": 0, "rubric_alignment": 0, "unsupported_claim_penalty": 0, "major_error": false, "notes": "..."},\n'
            '  "output_b": {"grounding": 0, "rubric_alignment": 0, "unsupported_claim_penalty": 0, "major_error": false, "notes": "..."},\n'
            '  "confidence": "low",\n'
            '  "rationale": "..."\n'
            "}\n\n"
            f"Case ID: {case['case_id']}\n"
            f"Judge focus: {', '.join(case.get('judge_focus', []))}\n"
            f"Case rationale: {case.get('case_rationale', '')}\n\n"
            f"Evidence bundle:\n{json.dumps(case['input_bundle'], indent=2, ensure_ascii=False)}\n\n"
            f"Output A:\n{prompt_a['raw_output']}\n\n"
            f"Output B:\n{prompt_b['raw_output']}\n"
        )
    return (
        "You are a blinded research judge evaluating two benchmark outputs.\n"
        "Score each output independently against the provided evidence bundle.\n"
        "Do not infer anything beyond the evidence bundle.\n"
        "Do not compare writing style. Judge only evidence grounding and rubric correctness.\n\n"
        "Rubric:\n"
        "- grounding: 0..3\n"
        "  0 = weakly grounded or largely detached from the bundle\n"
        "  1 = partially grounded with notable omissions\n"
        "  2 = mostly grounded with minor gaps\n"
        "  3 = strongly grounded and evidence-faithful\n"
        "- rubric_alignment: 0..3\n"
        "  0 = rubric / classification logic substantially wrong\n"
        "  1 = partially aligned with important mistakes\n"
        "  2 = mostly aligned with minor mistakes\n"
        "  3 = strongly aligned with the benchmark rubric\n"
        "- unsupported_claim_penalty: 0 | -1 | -2\n"
        "  0 = no unsupported claims\n"
        "  -1 = minor overclaiming\n"
        "  -2 = material unsupported claims\n"
        "- major_error: true | false\n"
        "  true only when there is a material factual or interpretive error\n\n"
        "Return JSON only with this schema:\n"
        "{\n"
        '  "output_a": {"grounding": 0, "rubric_alignment": 0, "unsupported_claim_penalty": 0, "major_error": false, "notes": "..."},\n'
        '  "output_b": {"grounding": 0, "rubric_alignment": 0, "unsupported_claim_penalty": 0, "major_error": false, "notes": "..."},\n'
        '  "confidence": "low",\n'
        '  "rationale": "..."\n'
        "}\n\n"
        f"Case ID: {case['case_id']}\n"
        f"Judge focus: {', '.join(case.get('judge_focus', []))}\n\n"
        f"Evidence bundle:\n{json.dumps(case['input_bundle'], indent=2, ensure_ascii=False)}\n\n"
        f"Output A:\n{prompt_a['raw_output']}\n\n"
        f"Output B:\n{prompt_b['raw_output']}\n"
    )


def _validate_research_judge_output(
    parsed_output: dict[str, Any] | None,
    *,
    benchmark_type: str = MAIN_STAGE2_BENCHMARK,
) -> list[str]:
    if not isinstance(parsed_output, dict):
        return ["Judge output is not a JSON object"]

    errors: list[str] = []
    confidence = parsed_output.get("confidence")
    if confidence not in RESEARCH_JUDGE_CONFIDENCE:
        errors.append("Invalid or missing confidence")

    if not isinstance(parsed_output.get("rationale"), str):
        errors.append("Missing rationale")

    for key in ("output_a", "output_b"):
        payload = parsed_output.get(key)
        if not isinstance(payload, dict):
            errors.append(f"Missing {key}")
            continue
        grounding = payload.get("grounding")
        penalty = payload.get("unsupported_claim_penalty")
        major_error = payload.get("major_error")
        notes = payload.get("notes")

        if grounding not in {0, 1, 2, 3}:
            errors.append(f"{key}.grounding out of range")
        if penalty not in {0, -1, -2}:
            errors.append(f"{key}.unsupported_claim_penalty out of range")
        if not isinstance(major_error, bool):
            errors.append(f"{key}.major_error must be boolean")
        if not isinstance(notes, str):
            errors.append(f"{key}.notes missing")
        if benchmark_type == STAGE2_INTERPRETATION_V3_BENCHMARK:
            targeted_errors = payload.get("targeted_error_probe_ids")
            if not isinstance(targeted_errors, list) or not all(isinstance(item, str) for item in targeted_errors):
                errors.append(f"{key}.targeted_error_probe_ids invalid")
        else:
            alignment = payload.get("rubric_alignment")
            if alignment not in {0, 1, 2, 3}:
                errors.append(f"{key}.rubric_alignment out of range")
    return errors


def _judge_output_overall(payload: dict[str, Any]) -> int:
    return int(payload["grounding"]) + int(payload["rubric_alignment"]) + int(payload["unsupported_claim_penalty"])


def _judge_winner_from_rubric(parsed_output: dict[str, Any], *, benchmark_type: str = MAIN_STAGE2_BENCHMARK) -> str:
    output_a = parsed_output["output_a"]
    output_b = parsed_output["output_b"]
    major_a = bool(output_a["major_error"])
    major_b = bool(output_b["major_error"])
    if major_a and not major_b:
        return "B"
    if major_b and not major_a:
        return "A"

    if benchmark_type == STAGE2_INTERPRETATION_V3_BENCHMARK:
        errors_a = len(output_a.get("targeted_error_probe_ids", []))
        errors_b = len(output_b.get("targeted_error_probe_ids", []))
        if errors_a < errors_b:
            return "A"
        if errors_b < errors_a:
            return "B"
        score_a = int(output_a["grounding"]) + int(output_a["unsupported_claim_penalty"])
        score_b = int(output_b["grounding"]) + int(output_b["unsupported_claim_penalty"])
        if score_a - score_b >= 2:
            return "A"
        if score_b - score_a >= 2:
            return "B"
        return "tie"

    score_a = _judge_output_overall(output_a)
    score_b = _judge_output_overall(output_b)
    if score_a - score_b >= 2:
        return "A"
    if score_b - score_a >= 2:
        return "B"
    return "tie"


def _blinded_output_order(
    *,
    case_id: str,
    repeat_index: int,
    judge_label: str,
    trial_a: dict[str, Any],
    trial_b: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    seed = hashlib.sha256(f"{case_id}:{repeat_index}:{judge_label}".encode("utf-8")).hexdigest()
    if int(seed[-1], 16) % 2 == 0:
        first, second = trial_a, trial_b
    else:
        first, second = trial_b, trial_a
    label_map = {"A": first["variant"], "B": second["variant"]}
    return first, second, label_map


async def run_single_research_judge(
    *,
    judge_llm: Any,
    judge_label: str,
    case: dict[str, Any],
    repeat_index: int,
    trial_a: dict[str, Any],
    trial_b: dict[str, Any],
) -> dict[str, Any]:
    prompt_a, prompt_b, label_map = _blinded_output_order(
        case_id=case["case_id"],
        repeat_index=repeat_index,
        judge_label=judge_label,
        trial_a=trial_a,
        trial_b=trial_b,
    )
    prompt = _build_research_judge_prompt(case=case, prompt_a=prompt_a, prompt_b=prompt_b)
    response = await judge_llm.ainvoke([HumanMessage(content=prompt)])
    parsed = None
    validation_errors: list[str] = []
    error: str | None = None
    try:
        parsed = parse_benchmark_output(getattr(response, "content", response))
        validation_errors = _validate_research_judge_output(parsed, benchmark_type=case["benchmark_type"])
    except Exception as exc:
        error = str(exc)
        validation_errors = [error]

    winner_blinded = "tie"
    winner = "tie"
    deltas: dict[str, float] = {}
    if not validation_errors and isinstance(parsed, dict):
        winner_blinded = _judge_winner_from_rubric(parsed, benchmark_type=case["benchmark_type"])
        winner = label_map.get(winner_blinded, "tie") if winner_blinded in {"A", "B"} else "tie"

        if label_map["A"] == VARIANT_A:
            payload_a = parsed["output_a"]
            payload_b = parsed["output_b"]
        else:
            payload_a = parsed["output_b"]
            payload_b = parsed["output_a"]
        if case["benchmark_type"] == STAGE2_INTERPRETATION_V3_BENCHMARK:
            errors_a = len(payload_a.get("targeted_error_probe_ids", []))
            errors_b = len(payload_b.get("targeted_error_probe_ids", []))
            deltas = {
                "grounding_delta": float(payload_b["grounding"] - payload_a["grounding"]),
                "unsupported_claim_penalty_delta": float(
                    payload_b["unsupported_claim_penalty"] - payload_a["unsupported_claim_penalty"]
                ),
                "targeted_error_count_delta": float(errors_b - errors_a),
                "overall_delta": float(
                    (payload_b["grounding"] + payload_b["unsupported_claim_penalty"] - errors_b)
                    - (payload_a["grounding"] + payload_a["unsupported_claim_penalty"] - errors_a)
                ),
            }
        else:
            deltas = {
                "grounding_delta": float(payload_b["grounding"] - payload_a["grounding"]),
                "rubric_alignment_delta": float(payload_b["rubric_alignment"] - payload_a["rubric_alignment"]),
                "unsupported_claim_penalty_delta": float(
                    payload_b["unsupported_claim_penalty"] - payload_a["unsupported_claim_penalty"]
                ),
                "overall_delta": float(_judge_output_overall(payload_b) - _judge_output_overall(payload_a)),
            }

    return {
        "case_id": case["case_id"],
        "repeat_index": repeat_index,
        "judge_label": judge_label,
        "label_map": label_map,
        "parsed_output": parsed,
        "winner_blinded": winner_blinded,
        "winner": winner,
        "confidence": parsed.get("confidence") if isinstance(parsed, dict) else None,
        "rationale": parsed.get("rationale", "") if isinstance(parsed, dict) else "",
        "deltas": deltas,
        "validation_errors": validation_errors,
        "error": error,
    }


def aggregate_panel_verdict(
    *,
    case_id: str,
    repeat_index: int,
    model_label: str,
    judge_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    valid_rows = [row for row in judge_rows if not row["validation_errors"]]
    vote_counts = {
        VARIANT_A: sum(1 for row in valid_rows if row["winner"] == VARIANT_A),
        VARIANT_B: sum(1 for row in valid_rows if row["winner"] == VARIANT_B),
        "tie": sum(1 for row in valid_rows if row["winner"] == "tie"),
    }
    unanimous = len(valid_rows) == RESEARCH_JUDGE_PANEL_SIZE and max(vote_counts.values(), default=0) == RESEARCH_JUDGE_PANEL_SIZE

    top_winner = max(vote_counts, key=vote_counts.get) if valid_rows else "tie"
    sorted_counts = sorted(vote_counts.values(), reverse=True)
    has_majority = bool(sorted_counts and sorted_counts[0] >= 2 and (len(sorted_counts) < 2 or sorted_counts[0] > sorted_counts[1]))
    if not has_majority:
        winner = "tie"
    else:
        winner = top_winner

    if unanimous:
        confidence = "high"
    elif winner in {VARIANT_A, VARIANT_B}:
        confidence = "medium"
    else:
        confidence = "low"

    rationale = " | ".join(
        f"{row['judge_label']}: {row.get('rationale', '').strip()}"
        for row in valid_rows
        if row.get("rationale")
    )

    return {
        "case_id": case_id,
        "repeat_index": repeat_index,
        "model": model_label,
        "winner": winner,
        "raw_winner": winner,
        "confidence": confidence,
        "unanimous": unanimous,
        "judge_count": len(judge_rows),
        "valid_judge_count": len(valid_rows),
        "judge_error_count": len(judge_rows) - len(valid_rows),
        "vote_counts": vote_counts,
        "judge_labels": [row["judge_label"] for row in judge_rows],
        "rationale": rationale,
    }


def summarize_judgments(judgments: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate panel verdicts using the legacy winner-oriented schema."""
    wins_a = sum(1 for item in judgments if item["winner"] == VARIANT_A)
    wins_b = sum(1 for item in judgments if item["winner"] == VARIANT_B)
    ties = sum(1 for item in judgments if item["winner"] == "tie")
    non_ties = wins_a + wins_b

    sign_test_pvalue = None
    if non_ties and binomtest is not None:
        sign_test_pvalue = float(binomtest(wins_b, non_ties, 0.5).pvalue)

    return {
        "n": len(judgments),
        VARIANT_A: wins_a,
        VARIANT_B: wins_b,
        "tie": ties,
        "sign_test_pvalue": sign_test_pvalue,
    }


def summarize_research_panel(
    panel_verdicts: list[dict[str, Any]],
    judge_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = summarize_judgments(panel_verdicts)
    summary["unanimous_rate"] = _mean([1.0 if item.get("unanimous") else 0.0 for item in panel_verdicts]) or 0.0
    summary["confidence_counts"] = {
        "high": sum(1 for item in panel_verdicts if item.get("confidence") == "high"),
        "medium": sum(1 for item in panel_verdicts if item.get("confidence") == "medium"),
        "low": sum(1 for item in panel_verdicts if item.get("confidence") == "low"),
    }

    valid_rows = [row for row in judge_rows if not row["validation_errors"]]
    summary["mean_deltas"] = {
        "grounding_delta": _mean([row["deltas"].get("grounding_delta", 0.0) for row in valid_rows]),
        "rubric_alignment_delta": _mean([row["deltas"].get("rubric_alignment_delta", 0.0) for row in valid_rows]),
        "unsupported_claim_penalty_delta": _mean(
            [row["deltas"].get("unsupported_claim_penalty_delta", 0.0) for row in valid_rows]
        ),
        "targeted_error_count_delta": _mean(
            [row["deltas"].get("targeted_error_count_delta", 0.0) for row in valid_rows]
        ),
        "overall_delta": _mean([row["deltas"].get("overall_delta", 0.0) for row in valid_rows]),
    }
    summary["judge_error_rate"] = _mean([1.0 if row["validation_errors"] else 0.0 for row in judge_rows]) or 0.0
    return summary


def _deterministic_metric_leader(
    *,
    trial_a: dict[str, Any],
    trial_b: dict[str, Any],
) -> str:
    if trial_a.get("benchmark_type") == STAGE2_INTERPRETATION_V3_BENCHMARK:
        score_a = float(trial_a["metrics"]["weighted_probe_error_score"])
        score_b = float(trial_b["metrics"]["weighted_probe_error_score"])
        if score_a < score_b:
            return VARIANT_A
        if score_b < score_a:
            return VARIANT_B
        return "tie"

    score_a = _primary_trial_score(trial_a)
    score_b = _primary_trial_score(trial_b)
    if score_a > score_b:
        return VARIANT_A
    if score_b > score_a:
        return VARIANT_B
    return "tie"


def select_v3_judge_keys(
    trial_pairs: dict[tuple[str, int, str], dict[str, dict[str, Any]]],
    *,
    sample_rate: float = DEFAULT_HUMAN_AUDIT_SAMPLE_RATE,
) -> set[tuple[str, int, str]]:
    selected: set[tuple[str, int, str]] = set()
    tie_keys: list[tuple[str, int, str]] = []
    for key, pair in trial_pairs.items():
        trial_a = pair.get(VARIANT_A)
        trial_b = pair.get(VARIANT_B)
        if not trial_a or not trial_b:
            continue
        delta = float(trial_a["metrics"]["weighted_probe_error_score"]) - float(
            trial_b["metrics"]["weighted_probe_error_score"]
        )
        if abs(delta) > 1e-12:
            selected.add(key)
        else:
            tie_keys.append(key)

    if tie_keys:
        count = max(1, math.ceil(len(tie_keys) * sample_rate))
        ranked = sorted(
            tie_keys,
            key=lambda item: hashlib.sha256(f"v3-judge:{item[2]}:{item[0]}:{item[1]}".encode("utf-8")).hexdigest(),
        )
        selected.update(ranked[:count])
    return selected


def _stable_sample_bucket(items: list[dict[str, Any]], sample_rate: float, *, salt: str) -> list[dict[str, Any]]:
    if not items:
        return []
    count = max(1, math.ceil(len(items) * sample_rate))
    scored = sorted(
        items,
        key=lambda item: hashlib.sha256(
            f"{salt}:{item['model']}:{item['case_id']}:{item['repeat_index']}".encode("utf-8")
        ).hexdigest(),
    )
    return scored[:count]


def select_human_audit_cases(
    *,
    panel_verdicts: list[dict[str, Any]],
    trial_pairs: dict[tuple[str, int, str], dict[str, dict[str, Any]]],
    case_map: dict[str, dict[str, Any]],
    sample_rate: float = DEFAULT_HUMAN_AUDIT_SAMPLE_RATE,
) -> list[dict[str, Any]]:
    selected: dict[tuple[str, int, str], dict[str, Any]] = {}
    unanimous_remainder: list[dict[str, Any]] = []

    for verdict in panel_verdicts:
        key = (verdict["case_id"], verdict["repeat_index"], verdict["model"])
        pair = trial_pairs[key]
        deterministic_leader = _deterministic_metric_leader(
            trial_a=pair[VARIANT_A],
            trial_b=pair[VARIANT_B],
        )
        reasons: list[str] = []
        if not verdict.get("unanimous"):
            reasons.append("panel_not_unanimous")
        if verdict["winner"] != deterministic_leader:
            reasons.append("panel_vs_deterministic_disagreement")

        prompt_a, prompt_b, label_map = _blinded_output_order(
            case_id=verdict["case_id"],
            repeat_index=verdict["repeat_index"],
            judge_label="human_audit",
            trial_a=pair[VARIANT_A],
            trial_b=pair[VARIANT_B],
        )
        packet = {
            "audit_id": f"{verdict['model']}::{verdict['case_id']}::{verdict['repeat_index']}",
            "benchmark_type": case_map[verdict["case_id"]]["benchmark_type"],
            "case_id": verdict["case_id"],
            "repeat_index": verdict["repeat_index"],
            "model": verdict["model"],
            "judge_focus": case_map[verdict["case_id"]].get("judge_focus", []),
            "evidence_bundle": case_map[verdict["case_id"]]["input_bundle"],
            "output_a": prompt_a["raw_output"],
            "output_b": prompt_b["raw_output"],
            "label_map": label_map,
            "panel_winner": verdict["winner"],
            "panel_confidence": verdict["confidence"],
            "panel_vote_counts": verdict["vote_counts"],
            "deterministic_leader": deterministic_leader,
            "selection_reasons": reasons,
        }

        if reasons:
            selected[key] = packet
        else:
            unanimous_remainder.append(packet)

    remaining_by_bucket: dict[str, list[dict[str, Any]]] = {VARIANT_A: [], VARIANT_B: [], "tie": []}
    for packet in unanimous_remainder:
        remaining_by_bucket[packet["panel_winner"]].append(packet)

    for bucket, items in remaining_by_bucket.items():
        for packet in _stable_sample_bucket(items, sample_rate, salt=f"human-audit:{bucket}"):
            key = (packet["case_id"], packet["repeat_index"], packet["model"])
            packet["selection_reasons"] = list(packet["selection_reasons"]) + ["stratified_unanimous_sample"]
            selected.setdefault(key, packet)

    return list(selected.values())


def build_human_audit_template_rows(audit_queue: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for packet in audit_queue:
        row = {field: "" for field in HUMAN_AUDIT_TEMPLATE_FIELDS}
        row["audit_id"] = packet["audit_id"]
        rows.append(row)
    return rows


def load_human_audit_results(path: str | Path) -> list[dict[str, Any]]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def summarize_human_audit_results(
    *,
    panel_verdicts: list[dict[str, Any]],
    audit_queue: list[dict[str, Any]],
    completed_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    queue_map = {packet["audit_id"]: packet for packet in audit_queue}
    completed = [row for row in completed_rows if row.get("audit_id") in queue_map]

    wins = {VARIANT_A: 0, VARIANT_B: 0, "tie": 0}
    agreement_n = 0
    agreement_hits = 0
    completed_packets: list[dict[str, Any]] = []
    for row in completed:
        packet = queue_map[row["audit_id"]]
        winner_blinded = row.get("winner", "tie")
        winner = packet["label_map"].get(winner_blinded, "tie") if winner_blinded in {"A", "B"} else "tie"
        wins[winner] = wins.get(winner, 0) + 1
        completed_packets.append({"audit_id": row["audit_id"], "winner": winner})

        panel_winner = packet["panel_winner"]
        if panel_winner in {VARIANT_A, VARIANT_B, "tie"}:
            agreement_n += 1
            if panel_winner == winner:
                agreement_hits += 1

    non_ties = wins[VARIANT_A] + wins[VARIANT_B]
    sign_test_pvalue = None
    if non_ties and binomtest is not None:
        sign_test_pvalue = float(binomtest(wins[VARIANT_B], non_ties, 0.5).pvalue)

    return {
        "queued_count": len(audit_queue),
        "completed_count": len(completed),
        "pending_count": max(0, len(audit_queue) - len(completed)),
        "agreement_rate": (agreement_hits / agreement_n) if agreement_n else None,
        VARIANT_A: wins[VARIANT_A],
        VARIANT_B: wins[VARIANT_B],
        "tie": wins["tie"],
        "sign_test_pvalue": sign_test_pvalue,
        "completed_packets": completed_packets,
    }


def save_jsonl(path: str | Path, records: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def save_json(path: str | Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def save_csv(path: str | Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def render_markdown_summary(
    *,
    benchmark_title: str,
    summary: dict[str, Any],
    judgment_summary: dict[str, Any] | None = None,
) -> str:
    """Render a compact publication-ready markdown summary."""
    if summary.get("benchmark_type") == STAGE2_INTERPRETATION_V3_BENCHMARK:
        variants = summary.get("variants", {})
        lines = [
            f"# {benchmark_title}",
            "",
            "## Deterministic Metrics",
            "",
            "| Variant | N | Weighted Probe Error | Probe Support | Primary Probe Target Error | All Probe Target Error | Major Error | Evidence Ref Validity | Secondary Conclusion Acc | Tool Calls | Tokens |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for variant in (VARIANT_A, VARIANT_B):
            row = variants.get(variant, {})
            lines.append(
                "| "
                + " | ".join(
                    [
                        variant,
                        str(row.get("n") or 0),
                        _fmt_num(row.get("weighted_probe_error_score_mean")),
                        _fmt_num(row.get("probe_support_score_mean")),
                        _fmt_pct(row.get("primary_probe_target_error_rate_mean")),
                        _fmt_pct(row.get("all_probe_target_error_rate_mean")),
                        _fmt_pct(row.get("major_error_rate_mean")),
                        _fmt_pct(row.get("evidence_ref_validity_rate_mean")),
                        _fmt_pct(row.get("secondary_conclusion_accuracy")),
                        _fmt_num(row.get("tool_call_mean")),
                        _fmt_num(row.get("total_tokens_mean")),
                    ]
                )
                + " |"
            )

        paired = summary.get("paired_tests", {}).get("weighted_probe_error_score_case_level", {})
        if paired:
            lines.extend(
                [
                    "",
                    "## Primary Endpoint",
                    "",
                    f"- Pair unit count: `{paired.get('pair_unit_count', 0)}`",
                    f"- Case-level weighted probe error delta (A - B): `{_fmt_num(paired.get('delta_mean'))}`",
                    f"- Wilcoxon p-value: `{_fmt_num(paired.get('wilcoxon_pvalue'))}`",
                ]
            )

        if judgment_summary:
            lines.extend(
                [
                    "",
                    "## Blinded Judge",
                    "",
                    f"- `{VARIANT_A}` wins: `{judgment_summary.get(VARIANT_A, 0)}`",
                    f"- `{VARIANT_B}` wins: `{judgment_summary.get(VARIANT_B, 0)}`",
                    f"- `tie`: `{judgment_summary.get('tie', 0)}`",
                    f"- Sign-test p-value: `{_fmt_num(judgment_summary.get('sign_test_pvalue'))}`",
                ]
            )
        return "\n".join(lines) + "\n"

    if summary.get("benchmark_type") == STAGE2_INTERPRETATION_V2_BENCHMARK:
        variants = summary.get("variants", {})
        lines = [
            f"# {benchmark_title}",
            "",
            "## Deterministic Metrics",
            "",
            "| Variant | N | Interpretation Score | Exact Check Acc | Partial Credit Acc | Overall Conclusion Acc | Uncertainty Acc | Overclaim Rate | Anchor Coverage | Tool Calls | Tokens |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for variant in (VARIANT_A, VARIANT_B):
            row = variants.get(variant, {})
            lines.append(
                "| "
                + " | ".join(
                    [
                        variant,
                        str(row.get("n") or 0),
                        _fmt_pct(row.get("interpretation_score_mean")),
                        _fmt_pct(row.get("exact_check_accuracy_mean")),
                        _fmt_pct(row.get("partial_credit_accuracy_mean")),
                        _fmt_pct(row.get("overall_conclusion_accuracy")),
                        _fmt_pct(row.get("uncertainty_accuracy")),
                        _fmt_pct(row.get("overclaim_rate_mean")),
                        _fmt_pct(row.get("anchor_coverage_mean")),
                        _fmt_num(row.get("tool_call_mean")),
                        _fmt_num(row.get("total_tokens_mean")),
                    ]
                )
                + " |"
            )

        paired = summary.get("paired_tests", {}).get("interpretation_score_case_level", {})
        if paired:
            lines.extend(
                [
                    "",
                    "## Primary Endpoint",
                    "",
                    f"- Pair unit count: `{paired.get('pair_unit_count', 0)}`",
                    f"- Case-level interpretation delta mean (B - A): `{_fmt_num(paired.get('delta_mean'))}`",
                    f"- Wilcoxon p-value: `{_fmt_num(paired.get('wilcoxon_pvalue'))}`",
                ]
            )

        if judgment_summary:
            lines.extend(
                [
                    "",
                    "## Blinded Judge",
                    "",
                    f"- `{VARIANT_A}` wins: `{judgment_summary.get(VARIANT_A, 0)}`",
                    f"- `{VARIANT_B}` wins: `{judgment_summary.get(VARIANT_B, 0)}`",
                    f"- `tie`: `{judgment_summary.get('tie', 0)}`",
                    f"- Sign-test p-value: `{_fmt_num(judgment_summary.get('sign_test_pvalue'))}`",
                ]
            )
        return "\n".join(lines) + "\n"

    variants = summary.get("variants", {})
    lines = [
        f"# {benchmark_title}",
        "",
        "## Deterministic Metrics",
        "",
        "| Variant | N | Exact Match | Near Match | Class Acc | Priority Acc | Malformed | Anchor Coverage | Tool Calls | Tokens |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for variant in (VARIANT_A, VARIANT_B):
        row = variants.get(variant, {})
        lines.append(
            "| "
            + " | ".join(
                [
                    variant,
                    str(row.get("n") or 0),
                    _fmt_pct(row.get("exact_match_rate_mean")),
                    _fmt_pct(row.get("near_match_rate_mean")),
                    _fmt_pct(row.get("classification_accuracy")),
                    _fmt_pct(row.get("priority_accuracy")),
                    _fmt_pct(row.get("malformed_rate")),
                    _fmt_pct(row.get("anchor_coverage_mean")),
                    _fmt_num(row.get("tool_call_mean")),
                    _fmt_num(row.get("total_tokens_mean")),
                ]
            )
            + " |"
        )

    exact_test = summary.get("paired_tests", {}).get("exact_match_rate", {})
    if exact_test:
        lines.extend(
            [
                "",
                "## Paired Test",
                "",
                f"- Exact-match delta mean (B - A): `{_fmt_num(exact_test.get('delta_mean'))}`",
                f"- Wilcoxon p-value: `{_fmt_num(exact_test.get('wilcoxon_pvalue'))}`",
            ]
        )

    if judgment_summary:
        lines.extend(
            [
                "",
                "## Blinded Judge",
                "",
                f"- `{VARIANT_A}` wins: `{judgment_summary.get(VARIANT_A, 0)}`",
                f"- `{VARIANT_B}` wins: `{judgment_summary.get(VARIANT_B, 0)}`",
                f"- `tie`: `{judgment_summary.get('tie', 0)}`",
                f"- Sign-test p-value: `{_fmt_num(judgment_summary.get('sign_test_pvalue'))}`",
            ]
        )

    return "\n".join(lines) + "\n"


def render_research_markdown_summary(
    *,
    benchmark_title: str,
    summary: dict[str, Any],
    panel_summary: dict[str, Any] | None = None,
    human_audit_summary: dict[str, Any] | None = None,
) -> str:
    lines = [render_markdown_summary(benchmark_title=benchmark_title, summary=summary, judgment_summary=panel_summary).rstrip()]

    if panel_summary:
        mean_deltas = panel_summary.get("mean_deltas", {})
        confidence_counts = panel_summary.get("confidence_counts", {})
        lines.extend(
            [
                "",
                "## Research Panel",
                "",
                f"- Unanimous rate: `{_fmt_pct(panel_summary.get('unanimous_rate'))}`",
                f"- Judge error rate: `{_fmt_pct(panel_summary.get('judge_error_rate'))}`",
                f"- Confidence counts: `high={confidence_counts.get('high', 0)}`, `medium={confidence_counts.get('medium', 0)}`, `low={confidence_counts.get('low', 0)}`",
                f"- Mean B-A grounding delta: `{_fmt_num(mean_deltas.get('grounding_delta'))}`",
                f"- Mean B-A unsupported-claim delta: `{_fmt_num(mean_deltas.get('unsupported_claim_penalty_delta'))}`",
                f"- Mean B-A targeted-error-count delta: `{_fmt_num(mean_deltas.get('targeted_error_count_delta'))}`",
                f"- Mean B-A rubric delta: `{_fmt_num(mean_deltas.get('rubric_alignment_delta'))}`",
                f"- Mean B-A overall delta: `{_fmt_num(mean_deltas.get('overall_delta'))}`",
            ]
        )

    if human_audit_summary:
        lines.extend(
            [
                "",
                "## Human Audit",
                "",
                f"- Queued audits: `{human_audit_summary.get('queued_count', 0)}`",
                f"- Completed audits: `{human_audit_summary.get('completed_count', 0)}`",
                f"- Pending audits: `{human_audit_summary.get('pending_count', 0)}`",
                f"- Panel-vs-human agreement: `{_fmt_pct(human_audit_summary.get('agreement_rate'))}`",
                f"- Audited winners: `{VARIANT_A}={human_audit_summary.get(VARIANT_A, 0)}`, `{VARIANT_B}={human_audit_summary.get(VARIANT_B, 0)}`, `tie={human_audit_summary.get('tie', 0)}`",
                f"- Human-audited sign-test p-value: `{_fmt_num(human_audit_summary.get('sign_test_pvalue'))}`",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def _fmt_num(value: float | None) -> str:
    if value is None:
        return "NA"
    return f"{value:.3f}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "NA"
    return f"{value:.1%}"


def load_model_configs_from_env() -> list[dict[str, Any]]:
    """Resolve benchmark model configs with optional env overrides."""
    raw = os.getenv("DRUGTARGET_BENCHMARK_MODELS", "").strip()
    if not raw:
        return DEFAULT_MODEL_CONFIGS

    allowed = {cfg["label"]: cfg for cfg in DEFAULT_MODEL_CONFIGS}
    selected: list[dict[str, Any]] = []
    for token in [part.strip() for part in raw.split(",") if part.strip()]:
        if token in allowed:
            selected.append(allowed[token])
            continue

        provider, sep, model_name = token.partition(":")
        if not sep or not provider.strip() or not model_name.strip():
            raise ValueError(f"Unknown benchmark model label: {token}")
        selected.append(
            {
                "label": token,
                "provider": provider.strip(),
                "model_kwargs": {"model": model_name.strip(), "temperature": 0},
                "repeats": 1,
            }
        )
    return selected


def _model_identity(model_cfg: dict[str, Any]) -> str:
    provider = str(model_cfg["provider"]).strip()
    model_name = str(model_cfg.get("model_kwargs", {}).get("model", "")).strip()
    return f"{provider}:{model_name}"


def _parse_judge_model_token(token: str) -> dict[str, Any]:
    provider, sep, model_name = token.partition(":")
    if not sep or not provider.strip() or not model_name.strip():
        raise ValueError(
            "Judge model entries must use provider:model format, "
            f"got {token!r}"
        )
    return {
        "label": token.strip(),
        "provider": provider.strip(),
        "model_kwargs": {"model": model_name.strip(), "temperature": 0},
    }


def load_judge_model_configs(generator_model_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve an independent 3-judge panel for a generator model."""
    generator_identity = _model_identity(generator_model_cfg)
    raw = os.getenv("DRUGTARGET_BENCHMARK_JUDGE_MODELS", "").strip()

    if raw:
        judge_cfgs = [
            _parse_judge_model_token(token)
            for token in [part.strip() for part in raw.split(",") if part.strip()]
        ]
        if len(judge_cfgs) != RESEARCH_JUDGE_PANEL_SIZE:
            raise ValueError(
                "DRUGTARGET_BENCHMARK_JUDGE_MODELS must provide exactly "
                f"{RESEARCH_JUDGE_PANEL_SIZE} judge models"
            )
    else:
        judge_cfgs = [
            cfg
            for cfg in DEFAULT_JUDGE_MODEL_CANDIDATES
            if _model_identity(cfg) != generator_identity
        ][:RESEARCH_JUDGE_PANEL_SIZE]
        if len(judge_cfgs) != RESEARCH_JUDGE_PANEL_SIZE:
            raise ValueError(
                "Could not derive a non-overlapping 3-judge panel from default candidates"
            )

    identities = [_model_identity(cfg) for cfg in judge_cfgs]
    if len(set(identities)) != len(identities):
        raise ValueError("Judge panel contains duplicate model identities")
    if generator_identity in identities:
        raise ValueError(
            "Judge panel must not overlap the generator model: "
            f"{generator_identity}"
        )
    return judge_cfgs


async def run_benchmark(
    *,
    benchmark_type: str,
    cases_path: str | Path,
    include_judge: bool = True,
) -> dict[str, Any]:
    """Run a benchmark over a frozen case pack."""
    cases = load_cases(cases_path)
    cases = [case for case in cases if case["benchmark_type"] == benchmark_type]
    if not cases:
        raise ValueError(f"No cases found for benchmark_type={benchmark_type}")

    trials: list[dict[str, Any]] = []
    judgments: list[dict[str, Any]] = []
    research_judges: list[dict[str, Any]] = []
    models = load_model_configs_from_env()
    case_map = {case["case_id"]: case for case in cases}

    for model_cfg in models:
        llm = create_llm(provider=model_cfg["provider"], **model_cfg["model_kwargs"])
        repeats = int(os.getenv("DRUGTARGET_BENCHMARK_REPEATS", str(model_cfg["repeats"])))
        model_trials: list[dict[str, Any]] = []

        for repeat_index in range(repeats):
            for case in cases:
                for variant in (VARIANT_A, VARIANT_B):
                    trial = await run_single_trial(
                        llm=llm,
                        case=case,
                        variant=variant,
                    )
                    trial["model"] = model_cfg["label"]
                    trial["repeat_index"] = repeat_index
                    trials.append(trial)
                    model_trials.append(trial)

        if include_judge and model_trials:
            judge_cfgs = load_judge_model_configs(model_cfg)
            judge_panel = [
                (judge_cfg["label"], create_llm(provider=judge_cfg["provider"], **judge_cfg["model_kwargs"]))
                for judge_cfg in judge_cfgs
            ]
            trial_index: dict[tuple[str, int, str], dict[str, dict[str, Any]]] = {}
            for trial in model_trials:
                key = (trial["case_id"], int(trial.get("repeat_index", 0)), trial["model"])
                trial_index.setdefault(key, {})[trial["variant"]] = trial

            selected_judge_keys = (
                select_v3_judge_keys(trial_index)
                if benchmark_type == STAGE2_INTERPRETATION_V3_BENCHMARK
                else set(trial_index)
            )

            for (case_id, repeat_index, model_label), pair in trial_index.items():
                if (case_id, repeat_index, model_label) not in selected_judge_keys:
                    continue
                if VARIANT_A not in pair or VARIANT_B not in pair:
                    continue
                judge_rows_for_pair: list[dict[str, Any]] = []
                for judge_label, judge_llm in judge_panel:
                    judge_row = await run_single_research_judge(
                        judge_llm=judge_llm,
                        judge_label=judge_label,
                        case=case_map[case_id],
                        repeat_index=repeat_index,
                        trial_a=pair[VARIANT_A],
                        trial_b=pair[VARIANT_B],
                    )
                    judge_row["model"] = model_label
                    research_judges.append(judge_row)
                    judge_rows_for_pair.append(judge_row)

                judgments.append(
                    aggregate_panel_verdict(
                        case_id=case_id,
                        repeat_index=repeat_index,
                        model_label=model_label,
                        judge_rows=judge_rows_for_pair,
                    )
                )

    summary = summarize_trials(trials)
    judgment_summary = summarize_judgments(judgments) if judgments else None
    research_panel_summary = summarize_research_panel(judgments, research_judges) if judgments else None

    trial_pairs: dict[tuple[str, int, str], dict[str, dict[str, Any]]] = {}
    for trial in trials:
        key = (trial["case_id"], int(trial.get("repeat_index", 0)), trial["model"])
        trial_pairs.setdefault(key, {})[trial["variant"]] = trial

    audit_queue = (
        select_human_audit_cases(
            panel_verdicts=judgments,
            trial_pairs=trial_pairs,
            case_map=case_map,
            sample_rate=float(
                os.getenv(
                    "DRUGTARGET_BENCHMARK_HUMAN_AUDIT_SAMPLE_RATE",
                    str(DEFAULT_HUMAN_AUDIT_SAMPLE_RATE),
                )
            ),
        )
        if judgments
        else []
    )
    human_results_path = os.getenv("DRUGTARGET_BENCHMARK_HUMAN_AUDIT_RESULTS", "").strip()
    completed_human_audits = load_human_audit_results(human_results_path) if human_results_path else []
    human_audit_summary = summarize_human_audit_results(
        panel_verdicts=judgments,
        audit_queue=audit_queue,
        completed_rows=completed_human_audits,
    )

    return {
        "benchmark_type": benchmark_type,
        "trials": trials,
        "summary": summary,
        "judgments": judgments,
        "judgment_summary": judgment_summary,
        "research_judges": research_judges,
        "research_panel_summary": research_panel_summary,
        "human_audit_queue": audit_queue,
        "human_audit_template_rows": build_human_audit_template_rows(audit_queue),
        "human_audit_summary": human_audit_summary,
        "completed_human_audits": completed_human_audits,
    }


def default_results_paths(stem: str) -> dict[str, Path]:
    """Return default artifact paths for a benchmark run."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "trials_jsonl": RESULTS_DIR / f"{stem}_trials.jsonl",
        "summary_json": RESULTS_DIR / f"{stem}_summary.json",
        "judgments_jsonl": RESULTS_DIR / f"{stem}_judgments.jsonl",
        "results_md": RESULTS_DIR / f"{stem}_results.md",
    }


def research_results_paths(stem: str) -> dict[str, Path]:
    """Return research-grade artifact paths for a benchmark run."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "research_judges_jsonl": RESULTS_DIR / f"{stem}_research_judges.jsonl",
        "research_panel_summary_json": RESULTS_DIR / f"{stem}_research_panel_summary.json",
        "human_audit_queue_jsonl": RESULTS_DIR / f"{stem}_human_audit_queue.jsonl",
        "human_audit_template_csv": RESULTS_DIR / f"{stem}_human_audit_template.csv",
        "human_audit_summary_json": RESULTS_DIR / f"{stem}_human_audit_summary.json",
        "research_results_md": RESULTS_DIR / f"{stem}_research_results.md",
    }

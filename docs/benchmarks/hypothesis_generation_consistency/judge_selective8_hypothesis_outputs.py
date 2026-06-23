from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.model import create_llm


BENCHMARK_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BENCHMARK_DIR / "results"
DEFAULT_BENCHMARK_RESULTS = (
    RESULTS_DIR
    / "selective8_lung35_native_retry3_retryafterbudget_9run_20260615_135409"
    / "benchmark_results.json"
)
DEFAULT_STEM = "selective8_lung35_mistral_medium35_128b"

MODE_LABELS = {
    "middleware_only": "Middleware-only",
    "middleware_plus_activator": "Activator",
    "middleware_plus_governor": "Governor",
}
PAIR_SPECS = [
    ("governor_vs_middleware", "middleware_plus_governor", "middleware_only"),
    ("governor_vs_activator", "middleware_plus_governor", "middleware_plus_activator"),
    ("activator_vs_middleware", "middleware_plus_activator", "middleware_only"),
]
SCORE_FIELDS = (
    "evidence_grounding",
    "biological_plausibility",
    "therapeutic_relevance",
    "specificity_actionability",
    "novelty_nonredundancy",
)
CCI_SCORE_FIELDS = (
    "faithfulness",
    "uncertainty_handling",
    "evidence_calibration",
    "overclaiming",
)
UPTAKE_SCORE_FIELDS = (
    "expected_source_uptake",
    "skill_derived_specificity",
    "cross_source_synthesis",
    "actionable_validation_design",
    "evidence_calibrated_restraint",
)
CCI_TIE_THRESHOLD = 0.25
UPTAKE_TIE_THRESHOLD = 3.0
CONFIDENCE_VALUES = {"low", "medium", "high"}
JUDGE_SYSTEM_PROMPT = (
    "You are a strict scientific judge. Return only one valid JSON object that matches "
    "the requested schema. Do not continue, quote, or rewrite the input reports."
)
SIMPLE_JUDGE_JSON_SCHEMA_TEXT = (
    "{\n"
    '  "winner": "A",\n'
    '  "score_a": 0,\n'
    '  "score_b": 0,\n'
    '  "confidence": "low",\n'
    '  "rationale": "...",\n'
    '  "key_differences": ["..."]\n'
    "}"
)
RUBRIC_JUDGE_JSON_SCHEMA_TEXT = (
    "{\n"
    '  "output_a": {\n'
    '    "evidence_grounding": 0,\n'
    '    "biological_plausibility": 0,\n'
    '    "therapeutic_relevance": 0,\n'
    '    "specificity_actionability": 0,\n'
    '    "novelty_nonredundancy": 0,\n'
    '    "unsupported_claim_penalty": 0,\n'
    '    "major_error": false,\n'
    '    "notes": "..."\n'
    "  },\n"
    '  "output_b": {\n'
    '    "evidence_grounding": 0,\n'
    '    "biological_plausibility": 0,\n'
    '    "therapeutic_relevance": 0,\n'
    '    "specificity_actionability": 0,\n'
    '    "novelty_nonredundancy": 0,\n'
    '    "unsupported_claim_penalty": 0,\n'
    '    "major_error": false,\n'
    '    "notes": "..."\n'
    "  },\n"
    '  "confidence": "low",\n'
    '  "rationale": "...",\n'
    '  "key_differences": ["..."]\n'
    "}"
)
CCI_JUDGE_JSON_SCHEMA_TEXT = (
    "{\n"
    '  "output_a": {\n'
    '    "faithfulness": 1,\n'
    '    "fabrication_count": 0,\n'
    '    "uncertainty_handling": 1,\n'
    '    "evidence_calibration": 1,\n'
    '    "overclaiming": 1,\n'
    '    "fabricated_claims": ["..."],\n'
    '    "notes": "..."\n'
    "  },\n"
    '  "output_b": {\n'
    '    "faithfulness": 1,\n'
    '    "fabrication_count": 0,\n'
    '    "uncertainty_handling": 1,\n'
    '    "evidence_calibration": 1,\n'
    '    "overclaiming": 1,\n'
    '    "fabricated_claims": ["..."],\n'
    '    "notes": "..."\n'
    "  },\n"
    '  "confidence": "low",\n'
    '  "rationale": "...",\n'
    '  "key_differences": ["..."]\n'
    "}"
)
SKILL_UPTAKE_JUDGE_JSON_SCHEMA_TEXT = (
    "{\n"
    '  "output_a": {\n'
    '    "expected_source_uptake": 0,\n'
    '    "skill_derived_specificity": 0,\n'
    '    "cross_source_synthesis": 0,\n'
    '    "actionable_validation_design": 0,\n'
    '    "evidence_calibrated_restraint": 0,\n'
    '    "unsupported_claim_penalty": 0,\n'
    '    "major_error": false,\n'
    '    "notes": "..."\n'
    "  },\n"
    '  "output_b": {\n'
    '    "expected_source_uptake": 0,\n'
    '    "skill_derived_specificity": 0,\n'
    '    "cross_source_synthesis": 0,\n'
    '    "actionable_validation_design": 0,\n'
    '    "evidence_calibrated_restraint": 0,\n'
    '    "unsupported_claim_penalty": 0,\n'
    '    "major_error": false,\n'
    '    "notes": "..."\n'
    "  },\n"
    '  "confidence": "low",\n'
    '  "rationale": "...",\n'
    '  "key_differences": ["..."]\n'
    "}"
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def save_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def coerce_text(content: Any) -> str:
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(parts)
    return str(content)


def parse_json_object(content: Any) -> dict[str, Any]:
    text = coerce_text(content).strip()
    if not text:
        raise ValueError("empty judge output")

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = [fenced.group(1).strip()] if fenced else []
    candidates.append(text)

    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        for start, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                parsed, end = decoder.raw_decode(candidate[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
            if end:
                break
    raise ValueError("no JSON object found in judge output")


def validation_passed(trial: dict[str, Any]) -> bool:
    validation = trial.get("validation")
    return isinstance(validation, dict) and validation.get("validation_passed") is True


def report_path_for_trial(trial: dict[str, Any]) -> Path:
    validation = trial.get("validation")
    if isinstance(validation, dict) and validation.get("hypothesis_report"):
        return Path(str(validation["hypothesis_report"]))
    return Path(str(trial["workspace"])) / "evidence" / "hypothesis_report.json"


def report_summary_for_trial(trial: dict[str, Any]) -> dict[str, Any] | None:
    validation = trial.get("validation")
    if not isinstance(validation, dict):
        return None
    summary = validation.get("report_summary")
    return summary if isinstance(summary, dict) else None


def compact_text(value: Any, *, max_chars: int = 450) -> Any:
    if not isinstance(value, str):
        return value
    value = re.sub(r"\b[\w.-]+\.json\b", "<evidence_ref>", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 20].rstrip() + " ...[truncated]"


def compact_hypothesis(hypothesis: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": hypothesis.get("rank"),
        "title": compact_text(hypothesis.get("title"), max_chars=220),
        "category": hypothesis.get("category"),
        "gap_type": hypothesis.get("gap_type"),
        "biological_entities": hypothesis.get("biological_entities"),
        "core_claim": compact_text(hypothesis.get("core_claim")),
        "evidence_references": hypothesis.get("evidence_references"),
        "falsifiable_prediction": compact_text(hypothesis.get("falsifiable_prediction"), max_chars=260),
        "validation_approach": compact_text(hypothesis.get("validation_approach"), max_chars=260),
        "scores": hypothesis.get("scores"),
        "prediction_grounding": hypothesis.get("prediction_grounding"),
        "contrast_references": hypothesis.get("contrast_references"),
    }


def compact_report(report: dict[str, Any], summary: dict[str, Any] | None) -> dict[str, Any]:
    hypotheses = report.get("hypotheses")
    if not isinstance(hypotheses, list):
        hypotheses = []
    return {
        "schema_version": report.get("schema_version"),
        "disease": report.get("disease"),
        "hypotheses_generated": report.get("hypotheses_generated"),
        "hypotheses_retained": report.get("hypotheses_retained"),
        "evidence_coverage_pct": report.get("evidence_coverage_pct"),
        "topn_coverage": report.get("topn_coverage"),
        "prediction_grounding_summary": report.get("prediction_grounding_summary"),
        "gap_analysis": report.get("gap_analysis"),
        "report_summary": {
            key: summary.get(key)
            for key in (
                "hypothesis_count",
                "category_counts",
                "covered_genes",
                "evidence_refs",
                "topn_missing",
                "topn_coverage_pct",
                "evidence_coverage_pct",
                "unverified_numeric_predictions",
            )
            if summary is not None and key in summary
        },
        "hypotheses": [compact_hypothesis(item) for item in hypotheses if isinstance(item, dict)],
    }


def _join_list(value: Any, *, max_items: int = 12) -> str:
    if not isinstance(value, list):
        return "-"
    items = [str(item) for item in value[:max_items]]
    suffix = "" if len(value) <= max_items else f", ... (+{len(value) - max_items})"
    return ", ".join(items) + suffix if items else "-"


def render_hypothesis_for_prompt(hypothesis: dict[str, Any]) -> str:
    entities = hypothesis.get("biological_entities")
    if isinstance(entities, dict):
        genes = _join_list(entities.get("genes"))
        cell_types = _join_list(entities.get("cell_types"), max_items=3)
        pathways = _join_list(entities.get("pathways"), max_items=3)
    else:
        genes = cell_types = pathways = "-"
    return "\n".join(
        [
            f"H{hypothesis.get('rank')}: {hypothesis.get('title')}",
            f"Category: {hypothesis.get('category')}; Genes: {genes}; Cell types: {cell_types}; Pathways: {pathways}",
            f"Evidence refs: {_join_list(hypothesis.get('evidence_references'), max_items=8)}",
            f"Claim: {hypothesis.get('core_claim')}",
            f"Prediction: {hypothesis.get('falsifiable_prediction')}",
            f"Validation: {hypothesis.get('validation_approach')}",
        ]
    )


def render_report_for_prompt(report: dict[str, Any]) -> str:
    summary = report.get("report_summary")
    if not isinstance(summary, dict):
        summary = {}
    hypotheses = report.get("hypotheses")
    if not isinstance(hypotheses, list):
        hypotheses = []
    header = "\n".join(
        [
            f"Disease: {report.get('disease')}",
            f"Hypotheses generated/retained: {report.get('hypotheses_generated')} / {report.get('hypotheses_retained')}",
            f"Evidence coverage pct: {report.get('evidence_coverage_pct')}",
            f"Covered genes: {_join_list(summary.get('covered_genes'))}",
            f"Report evidence refs: {_join_list(summary.get('evidence_refs'), max_items=16)}",
            f"Top-N missing genes: {_join_list(summary.get('topn_missing'))}",
            f"Unverified numeric predictions: {summary.get('unverified_numeric_predictions', '-')}",
        ]
    )
    body = "\n\n".join(
        render_hypothesis_for_prompt(hypothesis)
        for hypothesis in hypotheses
        if isinstance(hypothesis, dict)
    )
    return f"{header}\n\nHypotheses:\n{body}"


def build_trial_index(benchmark_results: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    indexed: dict[tuple[str, int], dict[str, Any]] = {}
    for trial in benchmark_results.get("trials", []):
        if not isinstance(trial, dict):
            continue
        mode = trial.get("mode")
        repeat = trial.get("repeat")
        if mode not in MODE_LABELS or not isinstance(repeat, int):
            continue
        indexed[(mode, repeat)] = trial
    return indexed


def blinded_order(
    *,
    pair_id: str,
    repeat: int,
    judge_label: str,
    left_mode: str,
    right_mode: str,
) -> dict[str, str]:
    seed = hashlib.sha256(f"{pair_id}:{repeat}:{judge_label}".encode("utf-8")).hexdigest()
    if int(seed[-1], 16) % 2 == 0:
        return {"A": left_mode, "B": right_mode}
    return {"A": right_mode, "B": left_mode}


def build_judge_prompt(
    *,
    pair_id: str,
    repeat: int,
    label_map: dict[str, str],
    reports_by_mode: dict[str, dict[str, Any]],
    schema_mode: str,
) -> str:
    report_a = reports_by_mode[label_map["A"]]
    report_b = reports_by_mode[label_map["B"]]
    if schema_mode == "skill_uptake":
        scoring_text = (
            "Score each output independently using a skill-uptake downstream-impact rubric.\n"
            "The benchmark expected reports to use skill-derived evidence from these sources when relevant:\n"
            "- OpenTargets disease/tractability evidence, usually refs like ot_<gene>.json\n"
            "- ChEMBL/actionability evidence, usually refs like stage3_<gene>.json and named drugs/phases\n"
            "- Census/gene-pair expression or coexpression evidence, usually refs like stage1_<geneA>--<geneB>.json\n"
            "- STRING/PPI or cross-target interaction evidence, often expressed as STRING/PPI scores or interaction support\n"
            "Do not reward simply listing many genes or references. Reward only when the evidence is actually used "
            "to shape claims, synthesis, predictions, or validation plans.\n"
            "The directly prompted drug-target-hypothesis behavior is baseline and should not by itself count as "
            "downstream skill uptake.\n\n"
            "Scoring ranges:\n"
            "- expected_source_uptake: integer 0..5; higher means the report uses the expected skill evidence "
            "types that are relevant to this benchmark, especially source types beyond generic target lists\n"
            "- skill_derived_specificity: integer 0..5; higher means the report uses concrete skill outputs "
            "such as risk ratios, coexpression percentages, PPI scores, named drugs/phases, or specific disease evidence\n"
            "- cross_source_synthesis: integer 0..5; higher means hypotheses integrate multiple evidence sources "
            "into one coherent mechanism or prioritization, rather than listing isolated facts\n"
            "- actionable_validation_design: integer 0..5; higher means validation experiments/readouts follow "
            "from the specific skill evidence, not generic perturbation language\n"
            "- evidence_calibrated_restraint: integer 0..5; higher means the report separates supported evidence "
            "from open questions and avoids unsupported causal, clinical, or mechanism claims\n"
            "- unsupported_claim_penalty: 0, -1, or -2 for unsupported mechanisms, disease mismatches, fabricated "
            "numbers/references, or therapeutic overclaims\n"
            "- major_error: true only for material biological, factual, or evidence-interpretation errors\n"
            "- confidence: low, medium, or high\n"
            "The winner will be derived from the summed rubric score; differences < "
            f"{UPTAKE_TIE_THRESHOLD:.0f} are ties. Do not add a winner field.\n\n"
        )
        schema_text = SKILL_UPTAKE_JUDGE_JSON_SCHEMA_TEXT
    elif schema_mode == "cci":
        scoring_text = (
            "Score each output independently using a CCI-style hallucination and evidence-boundary rubric, "
            "adapted for therapeutic hypothesis reports.\n"
            "Scoring ranges:\n"
            "- faithfulness: integer 1..5; higher means claims stay within the report evidence\n"
            "- fabrication_count: integer 0+; count unsupported mechanisms, pathways, targets, disease links, "
            "numeric claims, or therapeutic implications not supported by the report evidence\n"
            "- uncertainty_handling: integer 1..5; higher means predictions and confidence are calibrated to "
            "the available evidence and report limitations\n"
            "- evidence_calibration: integer 1..5; higher means the strength of claims matches evidence "
            "coverage, top-N coverage, prediction grounding, and disease-specific support\n"
            "- overclaiming: integer 1..5; higher means fewer causal, clinical, drug-target, or validation "
            "claims beyond the evidence\n"
            "- confidence: low, medium, or high\n"
            "Composite score is derived as: 0.30*faithfulness + 0.25*overclaiming + "
            "0.20*uncertainty_handling + 0.15*evidence_calibration + "
            "0.10*(5 - min(fabrication_count, 5)).\n"
            f"The winner will be derived from the composite score; differences < {CCI_TIE_THRESHOLD} are ties. "
            "Do not add a winner field.\n\n"
        )
        schema_text = CCI_JUDGE_JSON_SCHEMA_TEXT
    elif schema_mode == "rubric":
        scoring_text = (
            "Score each output independently by rubric item.\n"
            "Scoring ranges:\n"
            "- each positive rubric score: integer 0..5\n"
            "- unsupported_claim_penalty: 0, -1, or -2\n"
            "- major_error: true only for material biological, factual, or evidence-interpretation errors\n"
            "- confidence: low, medium, or high\n"
            "The winner will be derived from the rubric scores, so do not add a winner field.\n\n"
        )
        schema_text = RUBRIC_JUDGE_JSON_SCHEMA_TEXT
    else:
        scoring_text = (
            "Choose which output is better overall. Use the full 0..10 score range when useful.\n"
            "Scoring ranges:\n"
            "- score_a and score_b: integers 0..10 for overall scientific interpretation quality\n"
            "- winner: A, B, or tie\n"
            "- confidence: low, medium, or high\n\n"
        )
        schema_text = SIMPLE_JUDGE_JSON_SCHEMA_TEXT
    return (
        "You are a blinded research judge evaluating two generated therapeutic hypothesis reports "
        "for a lung / idiopathic pulmonary fibrosis benchmark.\n"
        "The two reports were produced by different orchestration methods, but method names are hidden. "
        "Do not infer or reward the hidden method. Do not reward length by itself.\n\n"
        "Judge only the generated report, not the hidden method. Prioritize evidence-grounded scientific interpretation:\n"
        "- claims should cite and stay faithful to evidence references in the report\n"
        "- mechanisms should be coherent for lung/IPF biology\n"
        "- hypotheses should connect to actionable target or intervention logic without unsupported therapeutic leaps\n"
        "- predictions and validation approaches should be concrete, testable, and calibrated to evidence strength\n"
        "- penalize overclaims, disease mismatch, unsupported mechanisms, fabricated evidence, and generic repetition\n\n"
        f"{scoring_text}"
        f"Comparison ID: {pair_id}; repeat: {repeat}\n\n"
        f"Output A report:\n{render_report_for_prompt(report_a)}\n\n"
        f"Output B report:\n{render_report_for_prompt(report_b)}\n\n"
        "End of reports. Now return exactly one valid JSON object. "
        "Do not include markdown or prose outside JSON. Use this exact schema:\n"
        f"{schema_text}"
    )


def validate_output_payload(payload: Any, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return [f"{label} missing or not object"]
    for field in SCORE_FIELDS:
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 5:
            errors.append(f"{label}.{field} must be integer 0..5")
    penalty = payload.get("unsupported_claim_penalty")
    if penalty not in {0, -1, -2}:
        errors.append(f"{label}.unsupported_claim_penalty must be 0, -1, or -2")
    if not isinstance(payload.get("major_error"), bool):
        errors.append(f"{label}.major_error must be boolean")
    if not isinstance(payload.get("notes"), str):
        errors.append(f"{label}.notes must be string")
    return errors


def validate_cci_payload(payload: Any, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return [f"{label} missing or not object"]
    for field in CCI_SCORE_FIELDS:
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 5:
            errors.append(f"{label}.{field} must be integer 1..5")
    fabrication_count = payload.get("fabrication_count")
    if not isinstance(fabrication_count, int) or isinstance(fabrication_count, bool) or fabrication_count < 0:
        errors.append(f"{label}.fabrication_count must be integer >= 0")
    fabricated_claims = payload.get("fabricated_claims")
    if not isinstance(fabricated_claims, list) or not all(isinstance(item, str) for item in fabricated_claims):
        errors.append(f"{label}.fabricated_claims must be list[str]")
    if not isinstance(payload.get("notes"), str):
        errors.append(f"{label}.notes must be string")
    return errors


def validate_skill_uptake_payload(payload: Any, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return [f"{label} missing or not object"]
    for field in UPTAKE_SCORE_FIELDS:
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 5:
            errors.append(f"{label}.{field} must be integer 0..5")
    penalty = payload.get("unsupported_claim_penalty")
    if penalty not in {0, -1, -2}:
        errors.append(f"{label}.unsupported_claim_penalty must be 0, -1, or -2")
    if not isinstance(payload.get("major_error"), bool):
        errors.append(f"{label}.major_error must be boolean")
    if not isinstance(payload.get("notes"), str):
        errors.append(f"{label}.notes must be string")
    return errors


def validate_judge_output(parsed: Any, schema_mode: str) -> list[str]:
    if not isinstance(parsed, dict):
        return ["judge output is not object"]
    if "winner" in parsed or "score_a" in parsed or "score_b" in parsed:
        errors: list[str] = []
        if parsed.get("winner") not in {"A", "B", "tie"}:
            errors.append("winner must be A, B, or tie")
        for field in ("score_a", "score_b"):
            value = parsed.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 10:
                errors.append(f"{field} must be integer 0..10")
        if parsed.get("confidence") not in CONFIDENCE_VALUES:
            errors.append("confidence must be low, medium, or high")
        if not isinstance(parsed.get("rationale"), str):
            errors.append("rationale must be string")
        key_differences = parsed.get("key_differences")
        if not isinstance(key_differences, list) or not all(isinstance(item, str) for item in key_differences):
            errors.append("key_differences must be list[str]")
        return errors

    if schema_mode == "skill_uptake":
        errors: list[str] = []
        errors.extend(validate_skill_uptake_payload(parsed.get("output_a"), "output_a"))
        errors.extend(validate_skill_uptake_payload(parsed.get("output_b"), "output_b"))
        if parsed.get("confidence") not in CONFIDENCE_VALUES:
            errors.append("confidence must be low, medium, or high")
        if not isinstance(parsed.get("rationale"), str):
            errors.append("rationale must be string")
        key_differences = parsed.get("key_differences")
        if not isinstance(key_differences, list) or not all(isinstance(item, str) for item in key_differences):
            errors.append("key_differences must be list[str]")
        return errors

    if schema_mode == "cci":
        errors: list[str] = []
        errors.extend(validate_cci_payload(parsed.get("output_a"), "output_a"))
        errors.extend(validate_cci_payload(parsed.get("output_b"), "output_b"))
        if parsed.get("confidence") not in CONFIDENCE_VALUES:
            errors.append("confidence must be low, medium, or high")
        if not isinstance(parsed.get("rationale"), str):
            errors.append("rationale must be string")
        key_differences = parsed.get("key_differences")
        if not isinstance(key_differences, list) or not all(isinstance(item, str) for item in key_differences):
            errors.append("key_differences must be list[str]")
        return errors

    errors: list[str] = []
    errors.extend(validate_output_payload(parsed.get("output_a"), "output_a"))
    errors.extend(validate_output_payload(parsed.get("output_b"), "output_b"))
    if parsed.get("confidence") not in CONFIDENCE_VALUES:
        errors.append("confidence must be low, medium, or high")
    if not isinstance(parsed.get("rationale"), str):
        errors.append("rationale must be string")
    key_differences = parsed.get("key_differences")
    if not isinstance(key_differences, list) or not all(isinstance(item, str) for item in key_differences):
        errors.append("key_differences must be list[str]")
    return errors


def cci_composite_score(payload: dict[str, Any]) -> float:
    fabrication_count = min(float(payload["fabrication_count"]), 5.0)
    return (
        0.30 * float(payload["faithfulness"])
        + 0.25 * float(payload["overclaiming"])
        + 0.20 * float(payload["uncertainty_handling"])
        + 0.15 * float(payload["evidence_calibration"])
        + 0.10 * (5.0 - fabrication_count)
    )


def score_payload(payload: dict[str, Any], schema_mode: str) -> float:
    if schema_mode == "cci":
        return cci_composite_score(payload)
    if schema_mode == "skill_uptake":
        score = sum(int(payload[field]) for field in UPTAKE_SCORE_FIELDS)
        score += int(payload["unsupported_claim_penalty"])
        if payload.get("major_error") is True:
            score -= 5
        return float(score)
    score = sum(int(payload[field]) for field in SCORE_FIELDS)
    score += int(payload["unsupported_claim_penalty"])
    if payload.get("major_error") is True:
        score -= 5
    return score


def derive_winner(parsed: dict[str, Any], label_map: dict[str, str], schema_mode: str) -> tuple[str, str, dict[str, float]]:
    if "winner" in parsed and "score_a" in parsed and "score_b" in parsed:
        blinded = str(parsed["winner"])
        winner = label_map.get(blinded, "tie") if blinded in {"A", "B"} else "tie"
        return blinded, winner, {"A": int(parsed["score_a"]), "B": int(parsed["score_b"])}

    output_a = parsed["output_a"]
    output_b = parsed["output_b"]
    score_a = score_payload(output_a, schema_mode)
    score_b = score_payload(output_b, schema_mode)
    if schema_mode == "cci":
        if score_a - score_b >= CCI_TIE_THRESHOLD:
            return "A", label_map["A"], {"A": score_a, "B": score_b}
        if score_b - score_a >= CCI_TIE_THRESHOLD:
            return "B", label_map["B"], {"A": score_a, "B": score_b}
        return "tie", "tie", {"A": score_a, "B": score_b}
    if schema_mode == "skill_uptake":
        if output_a.get("major_error") is True and output_b.get("major_error") is not True:
            return "B", label_map["B"], {"A": score_a, "B": score_b}
        if output_b.get("major_error") is True and output_a.get("major_error") is not True:
            return "A", label_map["A"], {"A": score_a, "B": score_b}
        if score_a - score_b >= UPTAKE_TIE_THRESHOLD:
            return "A", label_map["A"], {"A": score_a, "B": score_b}
        if score_b - score_a >= UPTAKE_TIE_THRESHOLD:
            return "B", label_map["B"], {"A": score_a, "B": score_b}
        return "tie", "tie", {"A": score_a, "B": score_b}
    if output_a.get("major_error") is True and output_b.get("major_error") is not True:
        return "B", label_map["B"], {"A": score_a, "B": score_b}
    if output_b.get("major_error") is True and output_a.get("major_error") is not True:
        return "A", label_map["A"], {"A": score_a, "B": score_b}
    if score_a - score_b >= 3:
        return "A", label_map["A"], {"A": score_a, "B": score_b}
    if score_b - score_a >= 3:
        return "B", label_map["B"], {"A": score_a, "B": score_b}
    return "tie", "tie", {"A": score_a, "B": score_b}


async def run_single_judge(
    *,
    judge_llm: Any,
    judge_label: str,
    pair_id: str,
    repeat: int,
    label_map: dict[str, str],
    reports_by_mode: dict[str, dict[str, Any]],
    schema_mode: str,
) -> dict[str, Any]:
    prompt = build_judge_prompt(
        pair_id=pair_id,
        repeat=repeat,
        label_map=label_map,
        reports_by_mode=reports_by_mode,
        schema_mode=schema_mode,
    )
    raw_content: Any = None
    parsed: dict[str, Any] | None = None
    validation_errors: list[str] = []
    error: str | None = None
    try:
        response = await judge_llm.ainvoke(
            [SystemMessage(content=JUDGE_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
        raw_content = getattr(response, "content", response)
        parsed = parse_json_object(raw_content)
        parsed.setdefault("key_differences", [])
        validation_errors = validate_judge_output(parsed, schema_mode)
    except Exception as exc:
        error = str(exc)
        validation_errors = [error]

    winner_blinded = "tie"
    winner = "tie"
    blinded_scores: dict[str, float] = {}
    mode_scores: dict[str, float] = {}
    mode_payloads: dict[str, Any] = {}
    if parsed is not None and not validation_errors:
        winner_blinded, winner, blinded_scores = derive_winner(parsed, label_map, schema_mode)
        mode_scores = {
            label_map["A"]: blinded_scores["A"],
            label_map["B"]: blinded_scores["B"],
        }
        if "output_a" in parsed and "output_b" in parsed:
            mode_payloads = {
                label_map["A"]: parsed["output_a"],
                label_map["B"]: parsed["output_b"],
            }
            if schema_mode == "cci":
                mode_payloads = {
                    mode: {
                        **payload,
                        "cci_composite_score": score_payload(payload, schema_mode),
                    }
                    for mode, payload in mode_payloads.items()
                }
        else:
            mode_payloads = {
                label_map["A"]: {"overall_score": blinded_scores["A"]},
                label_map["B"]: {"overall_score": blinded_scores["B"]},
            }

    return {
        "policy": "valid_only",
        "pair_id": pair_id,
        "repeat": repeat,
        "judge_label": judge_label,
        "schema_mode": schema_mode,
        "label_map": label_map,
        "winner_blinded": winner_blinded,
        "winner": winner,
        "winner_label": MODE_LABELS.get(winner, "tie"),
        "blinded_scores": blinded_scores,
        "mode_scores": mode_scores,
        "mode_payloads": mode_payloads,
        "confidence": parsed.get("confidence") if isinstance(parsed, dict) else None,
        "rationale": parsed.get("rationale", "") if isinstance(parsed, dict) else "",
        "key_differences": parsed.get("key_differences", []) if isinstance(parsed, dict) else [],
        "parsed_output": parsed,
        "validation_errors": validation_errors,
        "error": error,
        "raw_output_excerpt": compact_text(coerce_text(raw_content), max_chars=2000) if raw_content is not None else "",
    }


def panel_from_judge_row(row: dict[str, Any]) -> dict[str, Any]:
    valid = not row.get("validation_errors")
    winner = row["winner"] if valid else "tie"
    left_mode, right_mode = PAIR_MODE_LOOKUP[row["pair_id"]]
    vote_counts = {
        left_mode: 1 if winner == left_mode else 0,
        right_mode: 1 if winner == right_mode else 0,
        "tie": 1 if winner == "tie" else 0,
    }
    return {
        "policy": "valid_only",
        "basis": "judge" if valid else "judge_error",
        "pair_id": row["pair_id"],
        "repeat": row["repeat"],
        "left_mode": left_mode,
        "right_mode": right_mode,
        "winner": winner,
        "winner_label": MODE_LABELS.get(winner, "tie"),
        "confidence": row.get("confidence") if valid else "low",
        "judge_count": 1,
        "valid_judge_count": 1 if valid else 0,
        "judge_error_count": 0 if valid else 1,
        "vote_counts": vote_counts,
        "judge_labels": [row["judge_label"]],
        "rationale": row.get("rationale", "") if valid else "; ".join(row.get("validation_errors", [])),
        "mode_scores": row.get("mode_scores", {}),
    }


PAIR_MODE_LOOKUP = {pair_id: (left_mode, right_mode) for pair_id, left_mode, right_mode in PAIR_SPECS}


def exact_two_sided_binom_pvalue(successes: int, trials: int) -> float | None:
    if trials <= 0:
        return None
    observed = math.comb(trials, successes) * (0.5**trials)
    total = 0.0
    for k in range(trials + 1):
        prob = math.comb(trials, k) * (0.5**trials)
        if prob <= observed + 1e-15:
            total += prob
    return min(1.0, total)


def summarize_panels(panels: list[dict[str, Any]]) -> dict[str, Any]:
    by_pair: dict[str, list[dict[str, Any]]] = {}
    for panel in panels:
        by_pair.setdefault(panel["pair_id"], []).append(panel)

    summary: dict[str, Any] = {}
    for pair_id, items in sorted(by_pair.items()):
        left_mode, right_mode = PAIR_MODE_LOOKUP[pair_id]
        left_wins = sum(1 for item in items if item["winner"] == left_mode)
        right_wins = sum(1 for item in items if item["winner"] == right_mode)
        ties = sum(1 for item in items if item["winner"] == "tie")
        non_ties = left_wins + right_wins
        summary[pair_id] = {
            "n": len(items),
            "left_mode": left_mode,
            "right_mode": right_mode,
            "left_label": MODE_LABELS[left_mode],
            "right_label": MODE_LABELS[right_mode],
            "wins": {
                left_mode: left_wins,
                right_mode: right_wins,
                "tie": ties,
            },
            "win_rates": {
                left_mode: left_wins / len(items) if items else None,
                right_mode: right_wins / len(items) if items else None,
                "tie": ties / len(items) if items else None,
            },
            "non_tie_n": non_ties,
            "sign_test_pvalue_left_vs_right": exact_two_sided_binom_pvalue(left_wins, non_ties),
            "judge_error_count": sum(int(item.get("judge_error_count", 0)) for item in items),
            "basis_counts": {
                basis: sum(1 for item in items if item.get("basis") == basis)
                for basis in sorted({str(item.get("basis")) for item in items})
            },
        }
    return summary


def summarize_mode_scores(judge_rows: list[dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, list[float]] = {}
    metric_values: dict[str, dict[str, list[float]]] = {}
    for row in judge_rows:
        if row.get("validation_errors"):
            continue
        for mode, score in row.get("mode_scores", {}).items():
            if isinstance(score, (int, float)) and not isinstance(score, bool):
                values.setdefault(mode, []).append(float(score))
        for mode, payload in row.get("mode_payloads", {}).items():
            if not isinstance(payload, dict):
                continue
            metric_values.setdefault(mode, {})
            for field in (
                *SCORE_FIELDS,
                "unsupported_claim_penalty",
                *CCI_SCORE_FIELDS,
                "fabrication_count",
                "cci_composite_score",
                *UPTAKE_SCORE_FIELDS,
            ):
                value = payload.get(field)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    metric_values[mode].setdefault(field, []).append(float(value))

    summary: dict[str, Any] = {}
    for mode in sorted(set(values) | set(metric_values)):
        summary[mode] = {
            "label": MODE_LABELS.get(mode, mode),
            "overall_mean": sum(values.get(mode, [])) / len(values[mode]) if values.get(mode) else None,
            "overall_n": len(values.get(mode, [])),
            "metrics": {
                metric: sum(metric_items) / len(metric_items)
                for metric, metric_items in sorted(metric_values.get(mode, {}).items())
                if metric_items
            },
        }
    return summary


def build_failure_penalty_panels(
    *,
    primary_panels: list[dict[str, Any]],
    trial_index: dict[tuple[str, int], dict[str, Any]],
    repeats: list[int],
) -> list[dict[str, Any]]:
    primary_by_key = {
        (panel["pair_id"], panel["repeat"]): panel
        for panel in primary_panels
        if panel.get("basis") in {"judge", "judge_error"}
    }
    panels: list[dict[str, Any]] = []
    for pair_id, left_mode, right_mode in PAIR_SPECS:
        for repeat in repeats:
            left_trial = trial_index.get((left_mode, repeat))
            right_trial = trial_index.get((right_mode, repeat))
            left_valid = left_trial is not None and validation_passed(left_trial)
            right_valid = right_trial is not None and validation_passed(right_trial)
            if left_valid and right_valid:
                source = primary_by_key.get((pair_id, repeat))
                if source is None:
                    continue
                panel = dict(source)
                panel["policy"] = "failure_penalty"
                panels.append(panel)
            elif left_valid and not right_valid:
                panels.append(
                    {
                        "policy": "failure_penalty",
                        "basis": "failure_penalty",
                        "pair_id": pair_id,
                        "repeat": repeat,
                        "left_mode": left_mode,
                        "right_mode": right_mode,
                        "winner": left_mode,
                        "winner_label": MODE_LABELS[left_mode],
                        "confidence": "high",
                        "judge_count": 0,
                        "valid_judge_count": 0,
                        "judge_error_count": 0,
                        "vote_counts": {left_mode: 1, right_mode: 0, "tie": 0},
                        "judge_labels": [],
                        "rationale": f"{MODE_LABELS[right_mode]} failed validation; {MODE_LABELS[left_mode]} had a valid report.",
                        "mode_scores": {},
                    }
                )
            elif right_valid and not left_valid:
                panels.append(
                    {
                        "policy": "failure_penalty",
                        "basis": "failure_penalty",
                        "pair_id": pair_id,
                        "repeat": repeat,
                        "left_mode": left_mode,
                        "right_mode": right_mode,
                        "winner": right_mode,
                        "winner_label": MODE_LABELS[right_mode],
                        "confidence": "high",
                        "judge_count": 0,
                        "valid_judge_count": 0,
                        "judge_error_count": 0,
                        "vote_counts": {left_mode: 0, right_mode: 1, "tie": 0},
                        "judge_labels": [],
                        "rationale": f"{MODE_LABELS[left_mode]} failed validation; {MODE_LABELS[right_mode]} had a valid report.",
                        "mode_scores": {},
                    }
                )
            else:
                panels.append(
                    {
                        "policy": "failure_penalty",
                        "basis": "both_invalid",
                        "pair_id": pair_id,
                        "repeat": repeat,
                        "left_mode": left_mode,
                        "right_mode": right_mode,
                        "winner": "tie",
                        "winner_label": "tie",
                        "confidence": "low",
                        "judge_count": 0,
                        "valid_judge_count": 0,
                        "judge_error_count": 0,
                        "vote_counts": {left_mode: 0, right_mode: 0, "tie": 1},
                        "judge_labels": [],
                        "rationale": "Both outputs failed validation.",
                        "mode_scores": {},
                    }
                )
    return panels


def render_markdown(summary: dict[str, Any]) -> str:
    metadata = summary["metadata"]
    lines = [
        "# Selective8 Lung/IPF Hypothesis Judge Results",
        "",
        f"- Benchmark results: `{metadata['benchmark_results']}`",
        f"- Judge: `{metadata['judge_label']}`",
        f"- Judge provider: `{metadata['judge_provider']}`",
        f"- Base URL: `{metadata['base_url']}`",
        f"- Primary policy: valid-only paired comparisons",
        f"- Secondary policy: validation-failure penalty over all repeats",
        "",
        "## Validity",
        "",
        "| method | valid / total | invalid repeats |",
        "| --- | ---: | --- |",
    ]
    for mode, item in summary["validity"].items():
        invalid = ", ".join(str(rep) for rep in item["invalid_repeats"]) or "-"
        lines.append(f"| {MODE_LABELS[mode]} | {item['valid']} / {item['total']} | {invalid} |")

    for policy_key, title in (
        ("primary_valid_only", "Primary: valid-only judge"),
        ("secondary_failure_penalty", "Secondary: failure-penalty"),
    ):
        lines.extend(
            [
                "",
                f"## {title}",
                "",
                "| comparison | n | left wins | right wins | ties | sign-test p | basis |",
                "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
            ]
        )
        for pair_id, item in summary[policy_key]["pair_summary"].items():
            left_mode = item["left_mode"]
            right_mode = item["right_mode"]
            basis = ", ".join(f"{k}:{v}" for k, v in item["basis_counts"].items())
            pvalue = item["sign_test_pvalue_left_vs_right"]
            pvalue_text = "-" if pvalue is None else f"{pvalue:.4g}"
            lines.append(
                "| {left} vs {right} | {n} | {left_wins} | {right_wins} | {ties} | {pvalue} | {basis} |".format(
                    left=MODE_LABELS[left_mode],
                    right=MODE_LABELS[right_mode],
                    n=item["n"],
                    left_wins=item["wins"][left_mode],
                    right_wins=item["wins"][right_mode],
                    ties=item["wins"]["tie"],
                    pvalue=pvalue_text,
                    basis=basis,
                )
            )

    lines.extend(["", "## Mean Judge Scores", ""])
    if metadata.get("schema_mode") == "cci":
        lines.append("| method | n | composite | faithfulness | fabrications | uncertainty | evidence calibration | overclaiming |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for mode, item in summary["score_summary"].items():
            metrics = item["metrics"]
            lines.append(
                "| {label} | {n} | {overall} | {faithfulness} | {fabrications} | {uncertainty} | {evidence_calibration} | {overclaiming} |".format(
                    label=item["label"],
                    n=item["overall_n"],
                    overall=_fmt_float(item["overall_mean"]),
                    faithfulness=_fmt_float(metrics.get("faithfulness")),
                    fabrications=_fmt_float(metrics.get("fabrication_count")),
                    uncertainty=_fmt_float(metrics.get("uncertainty_handling")),
                    evidence_calibration=_fmt_float(metrics.get("evidence_calibration")),
                    overclaiming=_fmt_float(metrics.get("overclaiming")),
                )
            )
    elif metadata.get("schema_mode") == "skill_uptake":
        lines.append(
            "| method | n | overall | source uptake | specificity | synthesis | validation design | restraint | penalty |"
        )
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for mode, item in summary["score_summary"].items():
            metrics = item["metrics"]
            lines.append(
                "| {label} | {n} | {overall} | {source_uptake} | {specificity} | {synthesis} | {validation_design} | {restraint} | {penalty} |".format(
                    label=item["label"],
                    n=item["overall_n"],
                    overall=_fmt_float(item["overall_mean"]),
                    source_uptake=_fmt_float(metrics.get("expected_source_uptake")),
                    specificity=_fmt_float(metrics.get("skill_derived_specificity")),
                    synthesis=_fmt_float(metrics.get("cross_source_synthesis")),
                    validation_design=_fmt_float(metrics.get("actionable_validation_design")),
                    restraint=_fmt_float(metrics.get("evidence_calibrated_restraint")),
                    penalty=_fmt_float(metrics.get("unsupported_claim_penalty")),
                )
            )
    else:
        lines.append("| method | n | overall | evidence | biology | therapeutic | specificity | novelty | penalty |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for mode, item in summary["score_summary"].items():
            metrics = item["metrics"]
            lines.append(
                "| {label} | {n} | {overall} | {evidence} | {biology} | {therapeutic} | {specificity} | {novelty} | {penalty} |".format(
                    label=item["label"],
                    n=item["overall_n"],
                    overall=_fmt_float(item["overall_mean"]),
                    evidence=_fmt_float(metrics.get("evidence_grounding")),
                    biology=_fmt_float(metrics.get("biological_plausibility")),
                    therapeutic=_fmt_float(metrics.get("therapeutic_relevance")),
                    specificity=_fmt_float(metrics.get("specificity_actionability")),
                    novelty=_fmt_float(metrics.get("novelty_nonredundancy")),
                    penalty=_fmt_float(metrics.get("unsupported_claim_penalty")),
                )
            )
    lines.append("")
    return "\n".join(lines)


def _fmt_float(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{float(value):.2f}"


def load_existing_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def output_paths(stem: str) -> dict[str, Path]:
    return {
        "judge_rows": RESULTS_DIR / f"{stem}_judge_rows.jsonl",
        "pairwise_panel": RESULTS_DIR / f"{stem}_pairwise_panel.jsonl",
        "summary": RESULTS_DIR / f"{stem}_summary.json",
        "results_md": RESULTS_DIR / f"{stem}_results.md",
    }


def create_judge_llm(args: argparse.Namespace) -> Any:
    if args.judge_provider == "ollama" and not args.no_ollama_json_mode:
        return ChatOllama(
            model=args.judge_model,
            base_url=args.base_url,
            temperature=args.temperature,
            num_ctx=args.num_ctx,
            num_predict=args.num_predict,
            format="json",
            keep_alive="24h",
            disable_streaming=True,
            client_kwargs={"timeout": 7200},
        )
    return create_llm(
        provider=args.judge_provider,
        model=args.judge_model,
        base_url=args.base_url,
        temperature=args.temperature,
        num_ctx=args.num_ctx,
        num_predict=args.num_predict,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-results", type=Path, default=DEFAULT_BENCHMARK_RESULTS)
    parser.add_argument("--stem", default=DEFAULT_STEM)
    parser.add_argument("--judge-provider", default="ollama")
    parser.add_argument("--judge-model", default="mistral-medium-3.5:128b")
    parser.add_argument("--base-url", default="http://localhost:5000")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--num-ctx", type=int, default=32768)
    parser.add_argument("--num-predict", type=int, default=1024)
    parser.add_argument("--no-ollama-json-mode", action="store_true")
    parser.add_argument("--schema-mode", choices=["simple", "rubric", "cci", "skill_uptake"], default="simple")
    parser.add_argument("--limit-valid-pairs", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


async def main_async() -> None:
    args = parse_args()
    paths = output_paths(args.stem)
    if args.overwrite:
        for path in paths.values():
            path.unlink(missing_ok=True)

    benchmark_results = load_json(args.benchmark_results)
    trial_index = build_trial_index(benchmark_results)
    repeats = sorted({repeat for _, repeat in trial_index})

    validity: dict[str, Any] = {}
    for mode in MODE_LABELS:
        mode_repeats = sorted(repeat for trial_mode, repeat in trial_index if trial_mode == mode)
        valid_repeats = [
            repeat
            for repeat in mode_repeats
            if validation_passed(trial_index[(mode, repeat)])
        ]
        validity[mode] = {
            "total": len(mode_repeats),
            "valid": len(valid_repeats),
            "invalid_repeats": [repeat for repeat in mode_repeats if repeat not in valid_repeats],
        }

    valid_pair_jobs: list[tuple[str, int, str, str]] = []
    for pair_id, left_mode, right_mode in PAIR_SPECS:
        for repeat in repeats:
            left_trial = trial_index.get((left_mode, repeat))
            right_trial = trial_index.get((right_mode, repeat))
            if left_trial is None or right_trial is None:
                continue
            if validation_passed(left_trial) and validation_passed(right_trial):
                valid_pair_jobs.append((pair_id, repeat, left_mode, right_mode))

    if args.limit_valid_pairs is not None:
        valid_pair_jobs = valid_pair_jobs[: args.limit_valid_pairs]

    if args.dry_run:
        print(
            json.dumps(
                {
                    "benchmark_results": str(args.benchmark_results),
                    "validity": validity,
                    "valid_pair_jobs": [
                        {
                            "pair_id": pair_id,
                            "repeat": repeat,
                            "left_mode": left_mode,
                            "right_mode": right_mode,
                        }
                        for pair_id, repeat, left_mode, right_mode in valid_pair_jobs
                    ],
                    "output_paths": {key: str(value) for key, value in paths.items()},
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    existing_rows = load_existing_rows(paths["judge_rows"])
    completed = {
        (row.get("pair_id"), row.get("repeat"), row.get("judge_label"))
        for row in existing_rows
    }
    judge_label = f"{args.judge_provider}:{args.judge_model}"
    judge_rows = list(existing_rows)
    judge_llm = create_judge_llm(args)

    for index, (pair_id, repeat, left_mode, right_mode) in enumerate(valid_pair_jobs, start=1):
        key = (pair_id, repeat, judge_label)
        if key in completed:
            print(f"[skip {index}/{len(valid_pair_jobs)}] {pair_id} repeat={repeat}", flush=True)
            continue
        reports_by_mode: dict[str, dict[str, Any]] = {}
        for mode in (left_mode, right_mode):
            trial = trial_index[(mode, repeat)]
            report = load_json(report_path_for_trial(trial))
            reports_by_mode[mode] = compact_report(report, report_summary_for_trial(trial))
        label_map = blinded_order(
            pair_id=pair_id,
            repeat=repeat,
            judge_label=judge_label,
            left_mode=left_mode,
            right_mode=right_mode,
        )
        print(f"[judge {index}/{len(valid_pair_jobs)}] {pair_id} repeat={repeat}", flush=True)
        row = await run_single_judge(
            judge_llm=judge_llm,
            judge_label=judge_label,
            pair_id=pair_id,
            repeat=repeat,
            label_map=label_map,
            reports_by_mode=reports_by_mode,
            schema_mode=args.schema_mode,
        )
        judge_rows.append(row)
        append_jsonl(paths["judge_rows"], row)

    relevant_keys = {(pair_id, repeat) for pair_id, repeat, _, _ in valid_pair_jobs}
    active_rows = [
        row
        for row in judge_rows
        if row.get("policy") == "valid_only" and (row.get("pair_id"), row.get("repeat")) in relevant_keys
    ]
    active_rows.sort(key=lambda row: (str(row.get("pair_id")), int(row.get("repeat", 0)), str(row.get("judge_label"))))
    primary_panels = [panel_from_judge_row(row) for row in active_rows]
    primary_panels.sort(key=lambda row: (str(row.get("pair_id")), int(row.get("repeat", 0))))
    secondary_panels = build_failure_penalty_panels(
        primary_panels=primary_panels,
        trial_index=trial_index,
        repeats=repeats if args.limit_valid_pairs is None else sorted({repeat for _, repeat, _, _ in valid_pair_jobs}),
    )
    all_panels = primary_panels + secondary_panels

    summary = {
        "metadata": {
            "benchmark_results": str(args.benchmark_results),
            "stem": args.stem,
            "judge_provider": args.judge_provider,
            "judge_model": args.judge_model,
            "judge_label": judge_label,
            "base_url": args.base_url,
            "temperature": args.temperature,
            "num_ctx": args.num_ctx,
            "num_predict": args.num_predict,
            "schema_mode": args.schema_mode,
            "cci_tie_threshold": CCI_TIE_THRESHOLD if args.schema_mode == "cci" else None,
            "uptake_tie_threshold": UPTAKE_TIE_THRESHOLD if args.schema_mode == "skill_uptake" else None,
            "limit_valid_pairs": args.limit_valid_pairs,
            "valid_pair_job_count": len(valid_pair_jobs),
        },
        "validity": validity,
        "primary_valid_only": {
            "pair_summary": summarize_panels(primary_panels),
            "panel_count": len(primary_panels),
        },
        "secondary_failure_penalty": {
            "pair_summary": summarize_panels(secondary_panels),
            "panel_count": len(secondary_panels),
        },
        "score_summary": summarize_mode_scores(active_rows),
        "judge_error_rate": (
            sum(1 for row in active_rows if row.get("validation_errors")) / len(active_rows)
            if active_rows
            else None
        ),
        "output_paths": {key: str(value) for key, value in paths.items()},
    }

    save_jsonl(paths["judge_rows"], active_rows)
    save_jsonl(paths["pairwise_panel"], all_panels)
    save_json(paths["summary"], summary)
    paths["results_md"].write_text(render_markdown(summary), encoding="utf-8")

    print(paths["judge_rows"])
    print(paths["pairwise_panel"])
    print(paths["summary"])
    print(paths["results_md"])


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

"""Blind pairwise judge for DTH yes/no hypothesis outputs.

The script prepares anonymized A/B panels from a cumulative DTH comparison
summary, optionally calls an OpenAI, Anthropic, or Ollama judge, and writes
judge rows plus aggregate results. Use ``--prepare-only`` to verify the local
panel without spending API credits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from dotenv import load_dotenv


BENCHMARK_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SUMMARY_JSON = (
    BENCHMARK_DIR
    / "results"
    / "ollama_cloud_qwen397b_dth_minimal_v120_9more_for20each_20260620_014911"
    / "cumulative_valid_only_summary_for_20each_target.json"
)
DEFAULT_STEM = "dth_yes_no_gpt4o_mini_blind"
CONDITIONS = ("DTH_yes", "DTH_no")
RUBRIC_FIELDS = (
    "evidence_grounding",
    "biological_plausibility",
    "therapeutic_relevance",
    "claim_boundary_restraint",
    "specificity_testability",
)
CONFIDENCE_VALUES = {"low", "medium", "high"}
PENALTY_VALUES = {0, -1, -2}
DEFAULT_TIE_THRESHOLD = 2.0
OPENAI_PRICING_PER_1M_USD = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-5.4": {"input": 4.00, "output": 24.00},
}
ANTHROPIC_PRICING_PER_1M_USD = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
}

JUDGE_SYSTEM_PROMPT = (
    "You are a strict blinded scientific judge. Return exactly one valid JSON "
    "object matching the requested schema. Do not reveal or infer hidden "
    "generation settings."
)

JUDGE_JSON_SCHEMA_TEXT = (
    "{\n"
    '  "output_a": {\n'
    '    "evidence_grounding": 0,\n'
    '    "biological_plausibility": 0,\n'
    '    "therapeutic_relevance": 0,\n'
    '    "claim_boundary_restraint": 0,\n'
    '    "specificity_testability": 0,\n'
    '    "unsupported_claim_penalty": 0,\n'
    '    "major_error": false,\n'
    '    "notes": "..."\n'
    "  },\n"
    '  "output_b": {\n'
    '    "evidence_grounding": 0,\n'
    '    "biological_plausibility": 0,\n'
    '    "therapeutic_relevance": 0,\n'
    '    "claim_boundary_restraint": 0,\n'
    '    "specificity_testability": 0,\n'
    '    "unsupported_claim_penalty": 0,\n'
    '    "major_error": false,\n'
    '    "notes": "..."\n'
    "  },\n"
    '  "judge_preference": "tie",\n'
    '  "confidence": "low",\n'
    '  "rationale": "...",\n'
    '  "key_differences": ["..."]\n'
    "}"
)

HIDDEN_TEXT_REPLACEMENTS = (
    (re.compile(r"\bDTH[_ -]?(?:yes|no)\b", re.IGNORECASE), "<hidden_condition>"),
    (re.compile(r"\bdrug-target-hypothesis\b", re.IGNORECASE), "<hidden_guide>"),
    (re.compile(r"\boperational_contract\b", re.IGNORECASE), "<hidden_contract>"),
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_jsonl(path: Path, records: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def sanitize_blind_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value
    for pattern, replacement in HIDDEN_TEXT_REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text


def compact_text(value: Any, *, max_chars: int = 520) -> Any:
    if not isinstance(value, str):
        return value
    text = sanitize_blind_text(value)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 18].rstrip() + " ...[truncated]"


def _join_list(value: Any, *, max_items: int = 12) -> str:
    if not isinstance(value, list):
        return "-"
    items = [str(sanitize_blind_text(item)) for item in value[:max_items]]
    suffix = "" if len(value) <= max_items else f", ... (+{len(value) - max_items})"
    return ", ".join(items) + suffix if items else "-"


def resolve_report_path(row: dict[str, Any]) -> Path:
    if row.get("hypothesis_report"):
        return Path(str(row["hypothesis_report"]))
    validation = row.get("validation")
    if isinstance(validation, dict) and validation.get("hypothesis_report"):
        return Path(str(validation["hypothesis_report"]))
    workspace = row.get("workspace")
    if workspace:
        return Path(str(workspace)) / "evidence" / "hypothesis_report.json"
    raise ValueError(f"cannot infer report path for run_id={row.get('run_id')}")


def _stamp_order(summary: dict[str, Any]) -> dict[str, int]:
    stamps = summary.get("included_stamps")
    if not isinstance(stamps, list):
        return {}
    return {str(stamp): index for index, stamp in enumerate(stamps)}


def _sort_run_rows(rows: list[dict[str, Any]], summary: dict[str, Any]) -> list[dict[str, Any]]:
    stamp_order = _stamp_order(summary)

    def key(row: dict[str, Any]) -> tuple[int, int, str, str]:
        return (
            stamp_order.get(str(row.get("stamp")), 999_999),
            int(row.get("repeat") or 0),
            str(row.get("run_id") or ""),
            str(row.get("workspace") or ""),
        )

    return sorted(rows, key=key)


def blinded_label_map(pair_id: str, seed: int) -> dict[str, str]:
    digest = hashlib.sha256(f"{seed}:{pair_id}".encode("utf-8")).hexdigest()
    if int(digest[-1], 16) % 2 == 0:
        return {"A": "DTH_yes", "B": "DTH_no"}
    return {"A": "DTH_no", "B": "DTH_yes"}


def build_pair_jobs(
    summary: dict[str, Any],
    *,
    seed: int,
    limit_pairs: int | None,
) -> list[dict[str, Any]]:
    table = summary.get("valid_run_table")
    if not isinstance(table, list):
        raise ValueError("summary_json must contain a valid_run_table list")

    rows_by_condition: dict[str, list[dict[str, Any]]] = {condition: [] for condition in CONDITIONS}
    for row in table:
        if not isinstance(row, dict):
            continue
        condition = row.get("condition")
        if condition not in rows_by_condition:
            continue
        if row.get("valid") is not True:
            continue
        rows_by_condition[str(condition)].append(row)

    sorted_rows = {
        condition: _sort_run_rows(rows, summary)
        for condition, rows in rows_by_condition.items()
    }
    counts = {condition: len(rows) for condition, rows in sorted_rows.items()}
    if counts["DTH_yes"] != counts["DTH_no"]:
        raise ValueError(f"condition run counts differ: {counts}")
    pair_count = counts["DTH_yes"]
    if limit_pairs is not None:
        pair_count = min(pair_count, limit_pairs)

    jobs: list[dict[str, Any]] = []
    for index in range(pair_count):
        pair_id = f"pair{index + 1:03d}"
        label_map = blinded_label_map(pair_id, seed)
        runs_by_condition = {
            condition: sorted_rows[condition][index]
            for condition in CONDITIONS
        }
        jobs.append(
            {
                "pair_id": pair_id,
                "pair_index": index + 1,
                "label_map": label_map,
                "runs_by_condition": runs_by_condition,
                "runs_by_blind_label": {
                    blind_label: runs_by_condition[condition]
                    for blind_label, condition in label_map.items()
                },
            }
        )
    return jobs


def panel_record(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "pair_id": job["pair_id"],
        "pair_index": job["pair_index"],
        "label_map": job["label_map"],
        "runs_by_blind_label": {
            blind_label: {
                "condition": row.get("condition"),
                "stamp": row.get("stamp"),
                "repeat": row.get("repeat"),
                "run_id": row.get("run_id"),
                "workspace": row.get("workspace"),
                "report_path": str(resolve_report_path(row)),
                "coverage": row.get("coverage"),
                "hypothesis_count": row.get("hypothesis_count"),
            }
            for blind_label, row in job["runs_by_blind_label"].items()
        },
    }


def load_reports_for_job(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for condition, row in job["runs_by_condition"].items():
        report_path = resolve_report_path(row)
        reports[condition] = load_json(report_path)
    return reports


def render_hypothesis_for_prompt(hypothesis: dict[str, Any]) -> str:
    entities = hypothesis.get("biological_entities")
    if isinstance(entities, dict):
        genes = _join_list(entities.get("genes"))
        cell_types = _join_list(entities.get("cell_types"), max_items=4)
        pathways = _join_list(entities.get("pathways"), max_items=4)
        drugs = _join_list(entities.get("drugs"), max_items=4)
    else:
        genes = cell_types = pathways = drugs = "-"
    return "\n".join(
        [
            f"H{hypothesis.get('rank')}: {compact_text(hypothesis.get('title'), max_chars=220)}",
            f"Category: {compact_text(hypothesis.get('category'), max_chars=120)}",
            f"Genes: {genes}; cell types: {cell_types}; pathways: {pathways}; drugs: {drugs}",
            f"Evidence refs: {_join_list(hypothesis.get('evidence_references'), max_items=10)}",
            f"Claim: {compact_text(hypothesis.get('core_claim'), max_chars=620)}",
            f"Prediction: {compact_text(hypothesis.get('falsifiable_prediction'), max_chars=360)}",
            f"Validation: {compact_text(hypothesis.get('validation_approach'), max_chars=360)}",
            f"Prediction grounding: {compact_text(hypothesis.get('prediction_grounding'), max_chars=120)}",
        ]
    )


def render_report_for_prompt(report: dict[str, Any]) -> str:
    hypotheses = report.get("hypotheses")
    if not isinstance(hypotheses, list):
        hypotheses = []
    topn = report.get("topn_coverage")
    if not isinstance(topn, dict):
        topn = {}
    prediction = report.get("prediction_grounding_summary")
    if not isinstance(prediction, dict):
        prediction = {}
    gap = report.get("gap_analysis")
    if not isinstance(gap, dict):
        gap = {}
    header = "\n".join(
        [
            f"Disease: {compact_text(report.get('disease'), max_chars=120)}",
            f"Hypotheses generated/retained: {report.get('hypotheses_generated')} / {report.get('hypotheses_retained')}",
            f"Evidence coverage pct: {report.get('evidence_coverage_pct')}",
            f"Covered top genes: {_join_list(topn.get('covered'))}",
            f"Missing top genes: {_join_list(topn.get('missing'))}",
            f"Prediction grounding summary: {json.dumps(prediction, ensure_ascii=False, sort_keys=True)}",
            f"Gap analysis: {json.dumps(gap, ensure_ascii=False, sort_keys=True)}",
        ]
    )
    body = "\n\n".join(
        render_hypothesis_for_prompt(hypothesis)
        for hypothesis in hypotheses
        if isinstance(hypothesis, dict)
    )
    return sanitize_blind_text(f"{header}\n\nHypotheses:\n{body}")


def build_judge_prompt(
    *,
    job: dict[str, Any],
    reports_by_condition: dict[str, dict[str, Any]],
) -> str:
    condition_a = job["label_map"]["A"]
    condition_b = job["label_map"]["B"]
    report_a = render_report_for_prompt(reports_by_condition[condition_a])
    report_b = render_report_for_prompt(reports_by_condition[condition_b])
    return (
        "You are evaluating two anonymized generated biomedical therapeutic-target "
        "hypothesis reports for breast cancer.\n"
        "The generation settings and method labels are hidden. Judge only the visible "
        "scientific report content, not report length or inferred method.\n\n"
        "Score each output independently using integer scores from 0 to 5:\n"
        "- evidence_grounding: uses stated evidence references to support claims\n"
        "- biological_plausibility: mechanisms fit breast cancer biology and the named entities\n"
        "- therapeutic_relevance: target/intervention logic is useful without clinical overreach\n"
        "- claim_boundary_restraint: separates supported evidence from unknowns and avoids overclaiming\n"
        "- specificity_testability: predictions and validation plans are concrete and falsifiable\n"
        "- unsupported_claim_penalty: 0, -1, or -2 for unsupported mechanisms, invented evidence, "
        "disease mismatch, or overstated therapeutic conclusions\n"
        "- major_error: true only for a material factual or evidence-interpretation error\n\n"
        f"Comparison ID: {job['pair_id']}\n\n"
        f"Output A report:\n{report_a}\n\n"
        f"Output B report:\n{report_b}\n\n"
        "Return exactly one valid JSON object. Do not include markdown or prose outside JSON. "
        "Use this schema:\n"
        f"{JUDGE_JSON_SCHEMA_TEXT}"
    )


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
    fenced = re.search(r"```(?:json)?\s*(.*)\s*```", text, re.DOTALL)
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
                parsed, _ = decoder.raw_decode(candidate[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    raise ValueError("no JSON object found in judge output")


def normalize_judge_preference(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"a", "output_a", "answer_a", "report_a"}:
        return "A"
    if normalized in {"b", "output_b", "answer_b", "report_b"}:
        return "B"
    if normalized in {"tie", "draw", "equal", "no_preference"}:
        return "tie"
    return None


def validate_score_payload(payload: Any, label: str) -> list[str]:
    if not isinstance(payload, dict):
        return [f"{label} missing or not object"]
    errors: list[str] = []
    for field in RUBRIC_FIELDS:
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 5:
            errors.append(f"{label}.{field} must be integer 0..5")
    penalty = payload.get("unsupported_claim_penalty")
    if penalty not in PENALTY_VALUES:
        errors.append(f"{label}.unsupported_claim_penalty must be one of {sorted(PENALTY_VALUES)}")
    if not isinstance(payload.get("major_error"), bool):
        errors.append(f"{label}.major_error must be boolean")
    if not isinstance(payload.get("notes"), str):
        errors.append(f"{label}.notes must be string")
    return errors


def validate_judge_output(parsed: Any) -> list[str]:
    if not isinstance(parsed, dict):
        return ["judge output is not object"]
    errors: list[str] = []
    errors.extend(validate_score_payload(parsed.get("output_a"), "output_a"))
    errors.extend(validate_score_payload(parsed.get("output_b"), "output_b"))
    judge_preference = normalize_judge_preference(parsed.get("judge_preference"))
    if judge_preference is None:
        errors.append("judge_preference must be A, B, or tie")
    else:
        parsed["judge_preference"] = judge_preference
    if parsed.get("confidence") not in CONFIDENCE_VALUES:
        errors.append("confidence must be low, medium, or high")
    if not isinstance(parsed.get("rationale"), str):
        errors.append("rationale must be string")
    differences = parsed.get("key_differences")
    if not isinstance(differences, list) or not all(isinstance(item, str) for item in differences):
        errors.append("key_differences must be list[str]")
    return errors


def score_payload(payload: dict[str, Any]) -> float:
    score = sum(float(payload[field]) for field in RUBRIC_FIELDS)
    score += float(payload["unsupported_claim_penalty"])
    if payload.get("major_error") is True:
        score -= 5.0
    return score


def derive_winner(
    parsed: dict[str, Any],
    *,
    label_map: dict[str, str],
    tie_threshold: float,
) -> tuple[str, str, dict[str, float], dict[str, dict[str, Any]]]:
    payloads_by_blind = {
        "A": parsed["output_a"],
        "B": parsed["output_b"],
    }
    scores_by_blind = {
        "A": score_payload(payloads_by_blind["A"]),
        "B": score_payload(payloads_by_blind["B"]),
    }
    if payloads_by_blind["A"].get("major_error") is True and payloads_by_blind["B"].get("major_error") is not True:
        winner_blinded = "B"
    elif payloads_by_blind["B"].get("major_error") is True and payloads_by_blind["A"].get("major_error") is not True:
        winner_blinded = "A"
    elif scores_by_blind["A"] - scores_by_blind["B"] >= tie_threshold:
        winner_blinded = "A"
    elif scores_by_blind["B"] - scores_by_blind["A"] >= tie_threshold:
        winner_blinded = "B"
    else:
        winner_blinded = "tie"

    winner = label_map[winner_blinded] if winner_blinded in {"A", "B"} else "tie"
    scores_by_condition = {
        label_map[blind]: score
        for blind, score in scores_by_blind.items()
    }
    payloads_by_condition = {
        label_map[blind]: payload
        for blind, payload in payloads_by_blind.items()
    }
    return winner_blinded, winner, scores_by_condition, payloads_by_condition


def _usage_int(usage: Any, name: str) -> int:
    if isinstance(usage, dict):
        return int(usage.get(name) or 0)
    return int(getattr(usage, name, 0) or 0)


def resolve_pricing(
    *,
    provider: str,
    model: str,
    input_cost_per_1m_usd: float | None,
    output_cost_per_1m_usd: float | None,
) -> dict[str, float | None]:
    pricing_by_provider = {
        "openai": OPENAI_PRICING_PER_1M_USD,
        "anthropic": ANTHROPIC_PRICING_PER_1M_USD,
    }
    default = pricing_by_provider.get(provider, {}).get(model, {})
    return {
        "input_per_1m_usd": (
            input_cost_per_1m_usd
            if input_cost_per_1m_usd is not None
            else default.get("input")
        ),
        "output_per_1m_usd": (
            output_cost_per_1m_usd
            if output_cost_per_1m_usd is not None
            else default.get("output")
        ),
    }


def estimate_cost(
    *,
    input_tokens: int,
    output_tokens: int,
    pricing: dict[str, float | None],
) -> float | None:
    input_price = pricing.get("input_per_1m_usd")
    output_price = pricing.get("output_per_1m_usd")
    if input_price is None or output_price is None:
        return None
    return (
        input_tokens * float(input_price) / 1_000_000
        + output_tokens * float(output_price) / 1_000_000
    )


def call_openai_judge(
    *,
    model: str,
    prompt: str,
    max_output_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI()
    response = client.responses.create(
        model=model,
        instructions=JUDGE_SYSTEM_PROMPT,
        input=prompt,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        text={"format": {"type": "json_object"}},
    )
    usage = getattr(response, "usage", None)
    return {
        "raw_text": response.output_text,
        "usage": {
            "input_tokens": _usage_int(usage, "input_tokens"),
            "output_tokens": _usage_int(usage, "output_tokens"),
        },
    }


def call_anthropic_judge(
    *,
    model: str,
    prompt: str,
    max_output_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=max_output_tokens,
        temperature=temperature,
        system=JUDGE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text_parts: list[str] = []
    for block in response.content:
        if getattr(block, "type", "") != "text":
            continue
        block_text = getattr(block, "text", "")
        if isinstance(block_text, str):
            text_parts.append(block_text)
    usage = getattr(response, "usage", None)
    return {
        "raw_text": "".join(text_parts),
        "usage": {
            "input_tokens": _usage_int(usage, "input_tokens"),
            "output_tokens": _usage_int(usage, "output_tokens"),
        },
    }


def build_ollama_chat_payload(
    *,
    model: str,
    prompt: str,
    temperature: float,
    max_output_tokens: int,
    think: bool | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "options": {
            "temperature": temperature,
            "num_predict": max_output_tokens,
        },
    }
    if think is not None:
        payload["think"] = think
    return payload


def call_ollama_judge(
    *,
    model: str,
    base_url: str,
    prompt: str,
    max_output_tokens: int,
    temperature: float,
    think: bool | None,
    timeout_seconds: float,
) -> dict[str, Any]:
    endpoint = base_url.rstrip("/") + "/api/chat"
    payload = build_ollama_chat_payload(
        model=model,
        prompt=prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        think=think,
    )
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        response_payload = json.loads(response.read().decode("utf-8"))
    message = response_payload.get("message")
    content = message.get("content", "") if isinstance(message, dict) else ""
    return {
        "raw_text": content,
        "usage": {
            "input_tokens": int(response_payload.get("prompt_eval_count") or 0),
            "output_tokens": int(response_payload.get("eval_count") or 0),
        },
    }


def judge_job(
    *,
    job: dict[str, Any],
    judge_provider: str,
    judge_model: str,
    base_url: str,
    tie_threshold: float,
    max_output_tokens: int,
    temperature: float,
    ollama_think: bool | None,
    timeout_seconds: float,
    pricing: dict[str, float | None],
) -> dict[str, Any]:
    reports = load_reports_for_job(job)
    prompt = build_judge_prompt(job=job, reports_by_condition=reports)
    raw_text = ""
    parsed: dict[str, Any] | None = None
    validation_errors: list[str] = []
    error: str | None = None
    usage = {"input_tokens": 0, "output_tokens": 0}
    cost = {"estimated_cost_usd": None}

    try:
        if judge_provider == "openai":
            result = call_openai_judge(
                model=judge_model,
                prompt=prompt,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            )
        elif judge_provider == "anthropic":
            result = call_anthropic_judge(
                model=judge_model,
                prompt=prompt,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
            )
        elif judge_provider == "ollama":
            result = call_ollama_judge(
                model=judge_model,
                base_url=base_url,
                prompt=prompt,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
                think=ollama_think,
                timeout_seconds=timeout_seconds,
            )
        else:
            raise ValueError(f"unsupported judge provider: {judge_provider}")
        raw_text = str(result["raw_text"])
        usage = result["usage"]
        cost["estimated_cost_usd"] = estimate_cost(
            input_tokens=int(usage["input_tokens"]),
            output_tokens=int(usage["output_tokens"]),
            pricing=pricing,
        )
        parsed = parse_json_object(raw_text)
        validation_errors = validate_judge_output(parsed)
    except Exception as exc:
        error = str(exc)
        validation_errors = [error]

    winner_blinded = "tie"
    winner = "tie"
    condition_scores: dict[str, float] = {}
    condition_payloads: dict[str, dict[str, Any]] = {}
    judge_preference = None
    if parsed is not None and not validation_errors:
        winner_blinded, winner, condition_scores, condition_payloads = derive_winner(
            parsed,
            label_map=job["label_map"],
            tie_threshold=tie_threshold,
        )
        judge_preference = parsed.get("judge_preference")

    return {
        "pair_id": job["pair_id"],
        "pair_index": job["pair_index"],
        "judge_provider": judge_provider,
        "judge_model": judge_model,
        "label_map": job["label_map"],
        "runs_by_condition": {
            condition: {
                "stamp": row.get("stamp"),
                "repeat": row.get("repeat"),
                "run_id": row.get("run_id"),
                "workspace": row.get("workspace"),
                "report_path": str(resolve_report_path(row)),
            }
            for condition, row in job["runs_by_condition"].items()
        },
        "winner_blinded": winner_blinded,
        "winner": winner,
        "judge_preference_blinded": judge_preference,
        "judge_preference": (
            job["label_map"].get(str(judge_preference))
            if judge_preference in {"A", "B"}
            else judge_preference
        ),
        "condition_scores": condition_scores,
        "condition_payloads": condition_payloads,
        "confidence": parsed.get("confidence") if isinstance(parsed, dict) else None,
        "rationale": sanitize_blind_text(parsed.get("rationale", "")) if isinstance(parsed, dict) else "",
        "key_differences": (
            [sanitize_blind_text(item) for item in parsed.get("key_differences", [])]
            if isinstance(parsed, dict)
            else []
        ),
        "parsed_output": parsed,
        "validation_errors": validation_errors,
        "error": error,
        "usage": usage,
        "cost": cost,
        "raw_output_excerpt": compact_text(raw_text, max_chars=2000),
    }


def exact_two_sided_binom_pvalue(successes: int, trials: int) -> float | None:
    if trials <= 0:
        return None
    observed = math.comb(trials, successes) * (0.5**trials)
    total = 0.0
    for k in range(trials + 1):
        probability = math.comb(trials, k) * (0.5**trials)
        if probability <= observed + 1e-15:
            total += probability
    return min(1.0, total)


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def aggregate_judge_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    valid_rows = [row for row in rows if not row.get("validation_errors")]
    wins = Counter({"DTH_yes": 0, "DTH_no": 0, "tie": 0})
    score_values: dict[str, list[float]] = {condition: [] for condition in CONDITIONS}
    metric_values: dict[str, dict[str, list[float]]] = {condition: {} for condition in CONDITIONS}
    deltas: list[float] = []
    confidence_counts: Counter[str] = Counter()
    input_tokens = 0
    output_tokens = 0
    cost_total = 0.0
    cost_known = True

    for row in rows:
        usage = row.get("usage")
        if isinstance(usage, dict):
            input_tokens += int(usage.get("input_tokens") or 0)
            output_tokens += int(usage.get("output_tokens") or 0)
        cost = row.get("cost")
        estimated = cost.get("estimated_cost_usd") if isinstance(cost, dict) else None
        if estimated is None:
            cost_known = False
        else:
            cost_total += float(estimated)

    for row in valid_rows:
        winner = row.get("winner")
        wins[str(winner) if winner in {"DTH_yes", "DTH_no", "tie"} else "tie"] += 1
        if row.get("confidence"):
            confidence_counts[str(row["confidence"])] += 1
        condition_scores = row.get("condition_scores")
        if isinstance(condition_scores, dict):
            yes_score = condition_scores.get("DTH_yes")
            no_score = condition_scores.get("DTH_no")
            if isinstance(yes_score, (int, float)) and not isinstance(yes_score, bool):
                score_values["DTH_yes"].append(float(yes_score))
            if isinstance(no_score, (int, float)) and not isinstance(no_score, bool):
                score_values["DTH_no"].append(float(no_score))
            if (
                isinstance(yes_score, (int, float))
                and not isinstance(yes_score, bool)
                and isinstance(no_score, (int, float))
                and not isinstance(no_score, bool)
            ):
                deltas.append(float(yes_score) - float(no_score))
        condition_payloads = row.get("condition_payloads")
        if isinstance(condition_payloads, dict):
            for condition in CONDITIONS:
                payload = condition_payloads.get(condition)
                if not isinstance(payload, dict):
                    continue
                for field in (*RUBRIC_FIELDS, "unsupported_claim_penalty"):
                    value = payload.get(field)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        metric_values[condition].setdefault(field, []).append(float(value))

    non_tie_n = int(wins["DTH_yes"] + wins["DTH_no"])
    return {
        "total_rows": len(rows),
        "valid_judge_rows": len(valid_rows),
        "judge_error_count": len(rows) - len(valid_rows),
        "wins": {condition: int(wins[condition]) for condition in ("DTH_yes", "DTH_no", "tie")},
        "win_rates": {
            condition: (wins[condition] / len(valid_rows) if valid_rows else None)
            for condition in ("DTH_yes", "DTH_no", "tie")
        },
        "non_tie_n": non_tie_n,
        "sign_test_pvalue_yes_vs_no": exact_two_sided_binom_pvalue(int(wins["DTH_yes"]), non_tie_n),
        "mean_score_by_condition": {
            condition: _mean(values)
            for condition, values in score_values.items()
        },
        "mean_score_delta_yes_minus_no": _mean(deltas),
        "metric_means_by_condition": {
            condition: {
                metric: _mean(values)
                for metric, values in sorted(metrics.items())
            }
            for condition, metrics in metric_values.items()
        },
        "confidence_counts": dict(sorted(confidence_counts.items())),
        "token_usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
        "estimated_total_cost_usd": round(cost_total, 12) if cost_known else None,
    }


def output_paths(output_dir: Path, stem: str) -> dict[str, Path]:
    return {
        "pair_panel": output_dir / f"{stem}_pair_panel.jsonl",
        "judge_rows": output_dir / f"{stem}_judge_rows.jsonl",
        "summary": output_dir / f"{stem}_summary.json",
        "results_md": output_dir / f"{stem}_results.md",
        "prompt_previews": output_dir / f"{stem}_prompt_previews",
    }


def select_active_rows(
    rows: Sequence[dict[str, Any]],
    *,
    active_pair_ids: set[str],
    judge_provider: str,
    judge_model: str,
) -> list[dict[str, Any]]:
    latest_by_pair: dict[str, dict[str, Any]] = {}
    for row in rows:
        pair_id = row.get("pair_id")
        if pair_id not in active_pair_ids:
            continue
        if row.get("judge_provider") != judge_provider or row.get("judge_model") != judge_model:
            continue
        latest_by_pair[str(pair_id)] = row
    return [
        latest_by_pair[pair_id]
        for pair_id in sorted(latest_by_pair)
    ]


def write_prompt_previews(
    *,
    jobs: Sequence[dict[str, Any]],
    paths: dict[str, Path],
    preview_count: int,
) -> None:
    if preview_count <= 0:
        return
    prompt_dir = paths["prompt_previews"]
    prompt_dir.mkdir(parents=True, exist_ok=True)
    for job in jobs[:preview_count]:
        reports = load_reports_for_job(job)
        prompt = build_judge_prompt(job=job, reports_by_condition=reports)
        (prompt_dir / f"{job['pair_id']}.txt").write_text(prompt, encoding="utf-8")


def render_markdown(payload: dict[str, Any]) -> str:
    metadata = payload["metadata"]
    lines = [
        "# DTH Yes/No Blind Judge",
        "",
        f"- Status: `{metadata['status']}`",
        f"- Source summary: `{metadata['summary_json']}`",
        f"- Pair count: {metadata['pair_count']}",
        f"- Judge: `{metadata['judge_provider']}:{metadata['judge_model']}`",
        f"- Tie threshold: {metadata['tie_threshold']}",
        "",
    ]
    aggregate = payload.get("aggregate")
    if isinstance(aggregate, dict) and aggregate.get("total_rows", 0):
        wins = aggregate["wins"]
        lines.extend(
            [
                "## Blind Result",
                "",
                "| condition | wins | win rate | mean score |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        for condition in CONDITIONS:
            rate = aggregate["win_rates"][condition]
            score = aggregate["mean_score_by_condition"][condition]
            rate_text = "-" if rate is None else f"{rate:.2%}"
            score_text = "-" if score is None else f"{score:.2f}"
            lines.append(f"| {condition} | {wins[condition]} | {rate_text} | {score_text} |")
        tie_rate = aggregate["win_rates"]["tie"]
        tie_text = "-" if tie_rate is None else f"{tie_rate:.2%}"
        lines.append(f"| tie | {wins['tie']} | {tie_text} | - |")
        pvalue = aggregate["sign_test_pvalue_yes_vs_no"]
        pvalue_text = "-" if pvalue is None else f"{pvalue:.4g}"
        delta = aggregate["mean_score_delta_yes_minus_no"]
        delta_text = "-" if delta is None else f"{delta:.2f}"
        lines.extend(
            [
                "",
                f"- Non-tie comparisons: {aggregate['non_tie_n']}",
                f"- Sign-test p-value, yes vs no: {pvalue_text}",
                f"- Mean score delta, yes minus no: {delta_text}",
                f"- Judge errors: {aggregate['judge_error_count']}",
                f"- Input/output tokens: {aggregate['token_usage']['input_tokens']} / {aggregate['token_usage']['output_tokens']}",
                f"- Estimated total cost USD: {aggregate['estimated_total_cost_usd']}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "## Prepared Panel",
                "",
                "No judge calls were made. Review the pair panel and prompt previews before running without `--prepare-only`.",
                "",
            ]
        )
    lines.extend(
        [
            "## Output Files",
            "",
            "```json",
            json.dumps(payload["output_paths"], indent=2, ensure_ascii=False),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--stem", default=DEFAULT_STEM)
    parser.add_argument(
        "--judge-provider",
        choices=["openai", "anthropic", "ollama"],
        default="openai",
    )
    parser.add_argument("--judge-model", default="gpt-4o-mini")
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--seed", type=int, default=20260621)
    parser.add_argument("--limit-pairs", type=int, default=None)
    parser.add_argument("--tie-threshold", type=float, default=DEFAULT_TIE_THRESHOLD)
    parser.add_argument("--max-output-tokens", type=int, default=1200)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--ollama-think", choices=["on", "off", "default"], default="on")
    parser.add_argument("--timeout-seconds", type=float, default=7200.0)
    parser.add_argument("--prompt-preview-count", type=int, default=3)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--rerun-failed", action="store_true")
    parser.add_argument("--input-cost-per-1m-usd", type=float, default=None)
    parser.add_argument("--output-cost-per-1m-usd", type=float, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv()
    summary_path = args.summary_json.expanduser().resolve()
    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir is not None
        else summary_path.parent / "judge"
    )
    paths = output_paths(output_dir, args.stem)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.overwrite:
        for key in ("pair_panel", "judge_rows", "summary", "results_md"):
            paths[key].unlink(missing_ok=True)

    source_summary = load_json(summary_path)
    jobs = build_pair_jobs(
        source_summary,
        seed=args.seed,
        limit_pairs=args.limit_pairs,
    )
    panel_rows = [panel_record(job) for job in jobs]
    write_jsonl(paths["pair_panel"], panel_rows)
    write_prompt_previews(
        jobs=jobs,
        paths=paths,
        preview_count=args.prompt_preview_count,
    )

    pricing = resolve_pricing(
        provider=args.judge_provider,
        model=args.judge_model,
        input_cost_per_1m_usd=args.input_cost_per_1m_usd,
        output_cost_per_1m_usd=args.output_cost_per_1m_usd,
    )
    ollama_think = {"on": True, "off": False, "default": None}[args.ollama_think]

    metadata = {
        "summary_json": str(summary_path),
        "stem": args.stem,
        "status": "prepared_only" if args.prepare_only else "judged",
        "pair_count": len(jobs),
        "judge_provider": args.judge_provider,
        "judge_model": args.judge_model,
        "base_url": args.base_url if args.judge_provider == "ollama" else None,
        "ollama_think": args.ollama_think if args.judge_provider == "ollama" else None,
        "seed": args.seed,
        "tie_threshold": args.tie_threshold,
        "limit_pairs": args.limit_pairs,
        "pricing_per_1m_usd": pricing,
    }

    if args.prepare_only:
        payload = {
            "metadata": metadata,
            "panel_count": len(panel_rows),
            "aggregate": {},
            "output_paths": {key: str(value) for key, value in paths.items()},
        }
        write_json(paths["summary"], payload)
        paths["results_md"].write_text(render_markdown(payload), encoding="utf-8")
        print(paths["pair_panel"])
        print(paths["summary"])
        print(paths["results_md"])
        return 0

    existing_rows = [] if args.overwrite else load_jsonl(paths["judge_rows"])
    completed = {
        (row.get("pair_id"), row.get("judge_provider"), row.get("judge_model"))
        for row in existing_rows
        if not args.rerun_failed or not row.get("validation_errors")
    }
    judge_rows = list(existing_rows)
    for index, job in enumerate(jobs, start=1):
        key = (job["pair_id"], args.judge_provider, args.judge_model)
        if key in completed:
            print(f"[skip {index}/{len(jobs)}] {job['pair_id']}", flush=True)
            continue
        print(f"[judge {index}/{len(jobs)}] {job['pair_id']}", flush=True)
        row = judge_job(
            job=job,
            judge_provider=args.judge_provider,
            judge_model=args.judge_model,
            base_url=args.base_url,
            tie_threshold=args.tie_threshold,
            max_output_tokens=args.max_output_tokens,
            temperature=args.temperature,
            ollama_think=ollama_think,
            timeout_seconds=args.timeout_seconds,
            pricing=pricing,
        )
        judge_rows.append(row)
        append_jsonl(paths["judge_rows"], row)

    active_pair_ids = {job["pair_id"] for job in jobs}
    active_rows = select_active_rows(
        judge_rows,
        active_pair_ids=active_pair_ids,
        judge_provider=args.judge_provider,
        judge_model=args.judge_model,
    )
    payload = {
        "metadata": metadata,
        "panel_count": len(panel_rows),
        "aggregate": aggregate_judge_rows(active_rows),
        "output_paths": {key: str(value) for key, value in paths.items()},
    }
    write_jsonl(paths["judge_rows"], active_rows)
    write_json(paths["summary"], payload)
    paths["results_md"].write_text(render_markdown(payload), encoding="utf-8")
    print(paths["judge_rows"])
    print(paths["summary"])
    print(paths["results_md"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

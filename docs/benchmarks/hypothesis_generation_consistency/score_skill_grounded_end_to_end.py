"""Score skill-grounded end-to-end hypothesis benchmark outputs."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Sequence

from docs.benchmarks.hypothesis_generation_consistency.analyze_selective_activation_traces import (
    EXPECTED_ACTIVE_SKILLS,
    EXPECTED_INACTIVE_SKILLS,
)


OPENAI_PRICING_PER_1M = {
    "gpt-5.4": {"input": 4.00, "output": 24.00},
}
ANTHROPIC_PRICING_PER_1M = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
}

RUBRIC_TEXT = """Score only Axes 2-5. Each axis is 0, 1, or 2.
Axis 2 Skill Evidence Integration: uses activated evidence types in prioritization rather than merely mentioning them.
Axis 3 Evidence Faithfulness & Claim Boundary: claims are bounded by supplied evidence and avoid unsupported specificity.
Axis 4 Biological Prioritization Quality: primary and secondary candidates are biologically coherent and useful for interpretation.
Axis 5 Follow-up Recommendation Readiness: recommendations are concrete enough to guide follow-up without overstating certainty.
Return JSON only with integer keys axis2, axis3, axis4, axis5 and a concise rationale string.
"""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def activated_skill_names(row: dict[str, Any]) -> list[str]:
    names = row.get("activated_skill_names")
    if names is None and isinstance(row.get("activation_trace_payload"), dict):
        names = row["activation_trace_payload"].get("activated_skill_names")
    if not isinstance(names, list):
        return []
    return sorted({str(name) for name in names})


def score_activation_axis(row: dict[str, Any]) -> dict[str, Any]:
    valid_trace = row.get("activation_trace_valid") is True
    activated = set(activated_skill_names(row)) if valid_trace else set()
    expected_active = set(EXPECTED_ACTIVE_SKILLS)
    expected_inactive = set(EXPECTED_INACTIVE_SKILLS)
    active_hits = len(activated.intersection(expected_active))
    false_positive_inactive = sorted(activated.intersection(expected_inactive))
    missing_active = sorted(expected_active - activated)
    if not valid_trace:
        axis1_score = 0
    elif active_hits == len(expected_active) and not false_positive_inactive:
        axis1_score = 2
    elif active_hits >= 3 and not false_positive_inactive:
        axis1_score = 1
    else:
        axis1_score = 0
    return {
        "axis1_score": axis1_score,
        "active_hits": active_hits,
        "active_total": len(expected_active),
        "missing_active": missing_active,
        "false_positive_inactive": false_positive_inactive,
        "activated_skill_names": sorted(activated),
    }


def infer_report_path(row: dict[str, Any]) -> Path:
    validation = row.get("validation")
    if isinstance(validation, dict) and validation.get("hypothesis_report"):
        return Path(str(validation["hypothesis_report"]))
    if row.get("hypothesis_report"):
        return Path(str(row["hypothesis_report"]))
    for key in ("workspace", "workspace_dir", "data_dir"):
        value = row.get(key)
        if value:
            return Path(str(value)) / "evidence" / "hypothesis_report.json"
    raise ValueError(f"cannot infer hypothesis_report.json path for run_id={row.get('run_id')}")


def score_missing_report_row(row: dict[str, Any], *, report_path: Path) -> dict[str, Any]:
    activation = score_activation_axis(row)
    return {
        "model": row.get("model"),
        "mode": row.get("mode"),
        "port": row.get("port"),
        "run_id": row.get("run_id"),
        "report_path": str(report_path),
        **activation,
        "hard_fail": True,
        "judge_scores": {},
        "axes2_5_mean": 0.0,
        "final_score_10pt": 0.0,
        "note": "hard fail: no hypothesis_report.json",
    }


def compact_report_for_judge(report: dict[str, Any]) -> str:
    compact = {
        "schema_version": report.get("schema_version"),
        "hypotheses": report.get("hypotheses", []),
        "follow_up_recommendations": report.get("follow_up_recommendations", {}),
        "evidence_grounded_follow_up_recommendations": report.get(
            "evidence_grounded_follow_up_recommendations",
            {},
        ),
        "prediction_grounding_summary": report.get("prediction_grounding_summary", {}),
        "topn_coverage": report.get("topn_coverage", {}),
        "gap_analysis": report.get("gap_analysis", {}),
    }
    return json.dumps(compact, ensure_ascii=False, indent=2)[:45000]


def _parse_json_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return json.loads(stripped)


def call_openai_judge(*, model: str, report_text: str) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI()
    response = client.responses.create(
        model=model,
        instructions=RUBRIC_TEXT,
        input=report_text,
        max_output_tokens=900,
        text={"format": {"type": "json_object"}},
    )
    parsed = _parse_json_text(response.output_text)
    usage = getattr(response, "usage", None)
    return {
        "scores": parsed,
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
    }


def call_anthropic_judge(*, model: str, report_text: str) -> dict[str, Any]:
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=900,
        system=RUBRIC_TEXT,
        messages=[{"role": "user", "content": report_text}],
    )
    text = "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    )
    parsed = _parse_json_text(text)
    usage = response.usage
    return {
        "scores": parsed,
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
    }


def axes2_5_sum(scores: dict[str, Any]) -> int:
    return sum(int(scores[f"axis{axis}"]) for axis in (2, 3, 4, 5))


def estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    table = OPENAI_PRICING_PER_1M if provider == "openai" else ANTHROPIC_PRICING_PER_1M
    pricing = table.get(model, {"input": 0.0, "output": 0.0})
    return (
        input_tokens * float(pricing["input"]) / 1_000_000
        + output_tokens * float(pricing["output"]) / 1_000_000
    )


def score_report_row(
    row: dict[str, Any],
    *,
    report_path: Path,
    openai_model: str,
    anthropic_model: str,
    skip_openai: bool,
    skip_anthropic: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    report_text = compact_report_for_judge(load_json(report_path))
    activation = score_activation_axis(row)
    judge_scores: dict[str, Any] = {}
    judge_axis_sums: list[int] = []
    cost_rows: list[dict[str, Any]] = []

    if not skip_openai:
        openai_result = call_openai_judge(model=openai_model, report_text=report_text)
        judge_scores["openai_gpt_5_4"] = openai_result["scores"]
        judge_axis_sums.append(axes2_5_sum(openai_result["scores"]))
        cost_rows.append(
            {
                "provider": "openai",
                "model": openai_model,
                "input_tokens": openai_result["input_tokens"],
                "output_tokens": openai_result["output_tokens"],
                "estimated_cost_usd": estimate_cost(
                    "openai",
                    openai_model,
                    openai_result["input_tokens"],
                    openai_result["output_tokens"],
                ),
            }
        )

    if not skip_anthropic:
        anthropic_result = call_anthropic_judge(
            model=anthropic_model,
            report_text=report_text,
        )
        judge_scores["anthropic_sonnet_4_6"] = anthropic_result["scores"]
        judge_axis_sums.append(axes2_5_sum(anthropic_result["scores"]))
        cost_rows.append(
            {
                "provider": "anthropic",
                "model": anthropic_model,
                "input_tokens": anthropic_result["input_tokens"],
                "output_tokens": anthropic_result["output_tokens"],
                "estimated_cost_usd": estimate_cost(
                    "anthropic",
                    anthropic_model,
                    anthropic_result["input_tokens"],
                    anthropic_result["output_tokens"],
                ),
            }
        )

    axes2_5_mean = sum(judge_axis_sums) / len(judge_axis_sums) if judge_axis_sums else 0.0
    scored = {
        "model": row.get("model"),
        "mode": row.get("mode"),
        "port": row.get("port"),
        "run_id": row.get("run_id"),
        "report_path": str(report_path),
        **activation,
        "hard_fail": False,
        "judge_scores": judge_scores,
        "axes2_5_mean": axes2_5_mean,
        "final_score_10pt": float(activation["axis1_score"]) + axes2_5_mean,
        "note": "report scored",
    }
    return scored, cost_rows


def aggregate_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(f"{row.get('model')}::{row.get('mode')}", []).append(row)
    summary: dict[str, Any] = {}
    for key, group_rows in groups.items():
        intended = len(group_rows)
        report_rows = [row for row in group_rows if not row.get("hard_fail")]
        summary[key] = {
            "intended_runs": intended,
            "report_present_runs": len(report_rows),
            "hard_fails": intended - len(report_rows),
            "mean_axis1": _mean(group_rows, "axis1_score"),
            "mean_axes2_5": _mean(group_rows, "axes2_5_mean"),
            "mean_final_score_10pt": _mean(group_rows, "final_score_10pt"),
            "report_present_mean_final_score_10pt": _mean(
                report_rows,
                "final_score_10pt",
            ),
        }
    return {"groups": dict(sorted(summary.items()))}


def _mean(rows: Sequence[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return sum(float(row.get(key, 0.0)) for row in rows) / len(rows)


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Skill-Grounded End-to-End Scores",
        "",
        "Primary metric: `final_score_10pt = Axis 1 activation fidelity (0-2) + mean judge Axes 2-5 (0-8)`.",
        "",
        "## Mode Summary",
        "",
        "```json",
        json.dumps(payload["aggregate"], indent=2, ensure_ascii=False),
        "```",
        "",
        "## Run Scores",
        "",
        "| model | mode | port | run_id | active hits | axis1 | final | note |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for row in payload["rows"]:
        lines.append(
            "| {model} | {mode} | {port} | `{run_id}` | {hits}/{total} | {axis1} | {final:.2f} | {note} |".format(
                model=row.get("model"),
                mode=row.get("mode"),
                port=row.get("port"),
                run_id=row.get("run_id"),
                hits=row.get("active_hits"),
                total=row.get("active_total"),
                axis1=row.get("axis1_score"),
                final=float(row.get("final_score_10pt", 0.0)),
                note=row.get("note", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Cost",
            "",
            "```json",
            json.dumps(payload["cost"], indent=2, ensure_ascii=False),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score skill-grounded end-to-end hypothesis benchmark results."
    )
    parser.add_argument("result_dir")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--openai-model", default="gpt-5.4")
    parser.add_argument("--anthropic-model", default="claude-sonnet-4-6")
    parser.add_argument("--skip-openai", action="store_true")
    parser.add_argument("--skip-anthropic", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv()
    result_dir = Path(args.result_dir).expanduser().resolve()
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else result_dir
    )
    benchmark = load_json(result_dir / "benchmark_results.json")
    scored_rows: list[dict[str, Any]] = []
    cost_rows: list[dict[str, Any]] = []

    for trial in benchmark.get("trials", []):
        if not isinstance(trial, dict):
            continue
        report_path = infer_report_path(trial)
        if not report_path.exists():
            scored_rows.append(score_missing_report_row(trial, report_path=report_path))
            continue
        scored, trial_cost_rows = score_report_row(
            trial,
            report_path=report_path,
            openai_model=args.openai_model,
            anthropic_model=args.anthropic_model,
            skip_openai=args.skip_openai,
            skip_anthropic=args.skip_anthropic,
        )
        scored_rows.append(scored)
        cost_rows.extend(trial_cost_rows)

    payload = {
        "source": str(result_dir / "benchmark_results.json"),
        "rubric": {
            "axis1": "Selective Skill Activation Fidelity",
            "axis2": "Skill Evidence Integration",
            "axis3": "Evidence Faithfulness & Claim Boundary",
            "axis4": "Biological Prioritization Quality",
            "axis5": "Follow-up Recommendation Readiness",
        },
        "rows": scored_rows,
        "aggregate": aggregate_rows(scored_rows),
        "cost": {
            "rows": cost_rows,
            "estimated_total_usd": sum(
                float(row["estimated_cost_usd"]) for row in cost_rows
            ),
            "pricing_defaults_per_1m_tokens": {
                "openai": OPENAI_PRICING_PER_1M,
                "anthropic": ANTHROPIC_PRICING_PER_1M,
            },
            "note": "Successful calls only; retry/failure calls are not included.",
        },
    }
    output_json = output_dir / "skill_grounded_end_to_end_scores.json"
    output_md = output_dir / "skill_grounded_end_to_end_scores.md"
    write_json(output_json, payload)
    output_md.write_text(render_markdown(payload), encoding="utf-8")
    print(f"wrote {output_json}")
    print(f"wrote {output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

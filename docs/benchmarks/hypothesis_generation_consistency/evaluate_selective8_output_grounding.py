"""Evaluate selective8 hypothesis reports for output-level evidence grounding.

The OpenAI judge is intentionally blinded to benchmark condition metadata. It
receives only a compact hypothesis_report.json representation. Validation status
is merged after judging so failed pipeline outputs cannot become complete
validated evidence-grounded runs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Sequence


MODE_LABELS = {
    "middleware_plus_governor": "Governor",
    "middleware_plus_activator": "Activator",
    "middleware_only": "Middleware only",
}
MODE_ORDER = tuple(MODE_LABELS)
MODALITY_FIELDS = (
    "open_targets",
    "chembl_druggability",
    "census_cell_type",
    "string_network",
)
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_OUTPUT_STEM = "output_grounding_gpt4o_mini_scores"

JUDGE_INSTRUCTIONS = """You are a blinded evaluator for lung / idiopathic pulmonary fibrosis therapeutic hypothesis reports.

Evaluate only the report text supplied by the user. You do not know which system produced it.
Do not infer that an evidence source or skill was used unless the report explicitly contains evidence from that modality.

For each required modality, assign:
0 = absent: no evidence from that modality is reflected in the report.
1 = weak/generic mention: the modality or concept is named, but not concretely connected to the target-disease hypothesis.
2 = grounded: concrete evidence from the modality is connected to target prioritization, disease mechanism, or follow-up logic.

Required modalities:
- open_targets: target-disease association, genetic evidence, known-drug evidence, or Open Targets-style target prioritization evidence.
- chembl_druggability: ligand, inhibitor, compound, bioactivity, IC50/Ki, known drug, or druggability evidence.
- census_cell_type: CELLxGENE/Census, single-cell, expression, co-expression, disease-relevant cell type, or target-vs-rest evidence.
- string_network: STRING, protein-protein interaction, network neighbor, pathway module, interaction network, or mechanistic network evidence.

Negative-control intrusion:
- gwas_intrusion is true only if GWAS is used as an evidence source for the hypothesis.
- literature_search_intrusion is true only if literature search/PubMed/web search is used as a separate evidence source.
- html_report_intrusion is true only if HTML report generation/output is used as evidence.
Do not mark ordinary citations, evidence filenames, or report formatting as literature/html intrusion unless they are used as evidence sources.

Return JSON only with this schema:
{
  "open_targets": {"score": 0, "evidence_span": "", "reason": ""},
  "chembl_druggability": {"score": 0, "evidence_span": "", "reason": ""},
  "census_cell_type": {"score": 0, "evidence_span": "", "reason": ""},
  "string_network": {"score": 0, "evidence_span": "", "reason": ""},
  "negative_controls": {
    "gwas_intrusion": false,
    "literature_search_intrusion": false,
    "html_report_intrusion": false,
    "evidence_span": "",
    "reason": ""
  }
}
"""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
    return rows


def save_jsonl(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


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


def benchmark_path(result_path: Path) -> Path:
    path = result_path.expanduser().resolve()
    if path.is_dir():
        return path / "benchmark_results.json"
    return path


def result_dir_for(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    return resolved if resolved.is_dir() else resolved.parent


def validation_passed(trial: dict[str, Any]) -> bool:
    validation = trial.get("validation")
    return isinstance(validation, dict) and validation.get("validation_passed") is True


def report_path_for_trial(trial: dict[str, Any]) -> Path:
    validation = trial.get("validation")
    if isinstance(validation, dict) and validation.get("hypothesis_report"):
        return Path(str(validation["hypothesis_report"]))
    return Path(str(trial.get("workspace", ""))) / "evidence" / "hypothesis_report.json"


def compact_text(value: Any, *, max_chars: int = 600) -> Any:
    if not isinstance(value, str):
        return value
    compacted = re.sub(r"\s+", " ", value).strip()
    if len(compacted) <= max_chars:
        return compacted
    return compacted[: max_chars - 20].rstrip() + " ...[truncated]"


def compact_hypothesis(hypothesis: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": hypothesis.get("rank"),
        "title": compact_text(hypothesis.get("title"), max_chars=240),
        "category": hypothesis.get("category"),
        "gap_type": hypothesis.get("gap_type"),
        "biological_entities": hypothesis.get("biological_entities"),
        "core_claim": compact_text(hypothesis.get("core_claim"), max_chars=900),
        "evidence_references": hypothesis.get("evidence_references"),
        "falsifiable_prediction": compact_text(
            hypothesis.get("falsifiable_prediction"),
            max_chars=500,
        ),
        "validation_approach": compact_text(
            hypothesis.get("validation_approach"),
            max_chars=500,
        ),
        "scores": hypothesis.get("scores"),
        "prediction_grounding": hypothesis.get("prediction_grounding"),
        "contrast_references": hypothesis.get("contrast_references"),
    }


def compact_report_for_judge(report: dict[str, Any]) -> str:
    hypotheses = report.get("hypotheses")
    if not isinstance(hypotheses, list):
        hypotheses = []
    compact = {
        "schema_version": report.get("schema_version"),
        "disease": report.get("disease"),
        "hypotheses_generated": report.get("hypotheses_generated"),
        "hypotheses_retained": report.get("hypotheses_retained"),
        "evidence_coverage_pct": report.get("evidence_coverage_pct"),
        "topn_coverage": report.get("topn_coverage"),
        "prediction_grounding_summary": report.get("prediction_grounding_summary"),
        "gap_analysis": report.get("gap_analysis"),
        "hypotheses": [
            compact_hypothesis(item) for item in hypotheses if isinstance(item, dict)
        ],
        "follow_up_recommendations": report.get("follow_up_recommendations"),
        "evidence_grounded_follow_up_recommendations": report.get(
            "evidence_grounded_follow_up_recommendations"
        ),
    }
    return json.dumps(compact, indent=2, ensure_ascii=False)[:45000]


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(stripped):
            if char != "{":
                continue
            parsed, _ = decoder.raw_decode(stripped[index:])
            break
        else:
            raise
    if not isinstance(parsed, dict):
        raise ValueError("judge output is not a JSON object")
    return parsed


def _score(payload: dict[str, Any], field: str) -> int:
    item = payload.get(field)
    if not isinstance(item, dict):
        return 0
    value = item.get("score")
    if not isinstance(value, int) or isinstance(value, bool):
        return 0
    return max(0, min(2, value))


def derive_output_grounding_fields(
    judge_payload: dict[str, Any],
    *,
    validation_passed: bool,
) -> dict[str, Any]:
    scores = {field: _score(judge_payload, field) for field in MODALITY_FIELDS}
    negative_controls = judge_payload.get("negative_controls")
    if not isinstance(negative_controls, dict):
        negative_controls = {}
    intrusion = any(
        negative_controls.get(field) is True
        for field in (
            "gwas_intrusion",
            "literature_search_intrusion",
            "html_report_intrusion",
        )
    )
    strict_count = sum(1 for value in scores.values() if value == 2)
    lenient_count = sum(1 for value in scores.values() if value >= 1)
    complete_output = strict_count == len(MODALITY_FIELDS) and not intrusion
    return {
        "open_targets_score": scores["open_targets"],
        "chembl_druggability_score": scores["chembl_druggability"],
        "census_cell_type_score": scores["census_cell_type"],
        "string_network_score": scores["string_network"],
        "required_modality_count_strict": strict_count,
        "required_modality_count_lenient": lenient_count,
        "string_mechanism_present": scores["string_network"] == 2,
        "negative_control_intrusion": intrusion,
        "negative_control_free": not intrusion,
        "complete_evidence_grounding_output_strict": complete_output,
        "complete_evidence_grounding_validated_strict": complete_output
        and validation_passed,
    }


def zero_grounding_fields(*, validation_passed: bool) -> dict[str, Any]:
    return derive_output_grounding_fields({}, validation_passed=validation_passed)


def call_openai_judge(
    *,
    model: str,
    report_text: str,
    temperature: float,
) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(timeout=180.0)
    response = client.responses.create(
        model=model,
        instructions=JUDGE_INSTRUCTIONS,
        input=report_text,
        temperature=temperature,
        max_output_tokens=1200,
        text={"format": {"type": "json_object"}},
    )
    parsed = parse_json_object(response.output_text)
    usage = getattr(response, "usage", None)
    return {
        "judge_payload": parsed,
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
    }


def base_row(trial: dict[str, Any], *, report_path: Path) -> dict[str, Any]:
    validation = validation_passed(trial)
    return {
        "model": trial.get("model"),
        "mode": trial.get("mode"),
        "mode_label": MODE_LABELS.get(str(trial.get("mode")), str(trial.get("mode"))),
        "repeat": trial.get("repeat"),
        "run_id": trial.get("run_id"),
        "report_path": str(report_path),
        "report_present": report_path.exists(),
        "validation_passed": validation,
    }


def score_trial(
    trial: dict[str, Any],
    *,
    model: str,
    skip_openai: bool,
    temperature: float,
) -> dict[str, Any]:
    report_path = report_path_for_trial(trial)
    row = base_row(trial, report_path=report_path)
    validation = bool(row["validation_passed"])

    if not report_path.exists():
        return {
            **row,
            **zero_grounding_fields(validation_passed=validation),
            "judge_payload": None,
            "judge_error": "missing hypothesis_report.json",
            "input_tokens": 0,
            "output_tokens": 0,
        }

    if skip_openai:
        return {
            **row,
            **zero_grounding_fields(validation_passed=validation),
            "judge_payload": None,
            "judge_error": "skipped openai judge",
            "input_tokens": 0,
            "output_tokens": 0,
        }

    report_text = compact_report_for_judge(load_json(report_path))
    result = call_openai_judge(
        model=model,
        report_text=report_text,
        temperature=temperature,
    )
    judge_payload = result["judge_payload"]
    return {
        **row,
        **derive_output_grounding_fields(judge_payload, validation_passed=validation),
        "judge_payload": judge_payload,
        "judge_error": None,
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
    }


def _mean(rows: Sequence[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return sum(float(row.get(key, 0.0) or 0.0) for row in rows) / len(rows)


def _count_true(rows: Sequence[dict[str, Any]], key: str) -> int:
    return sum(1 for row in rows if row.get(key) is True)


def aggregate_rows(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(str(row.get("mode")), []).append(row)

    ordered_modes = [mode for mode in MODE_ORDER if mode in groups]
    ordered_modes.extend(sorted(mode for mode in groups if mode not in MODE_ORDER))
    summary: dict[str, Any] = {}
    for mode in ordered_modes:
        group_rows = groups[mode]
        runs = len(group_rows)
        report_present_runs = _count_true(group_rows, "report_present")
        validation_runs = _count_true(group_rows, "validation_passed")
        judged_runs = sum(
            1
            for row in group_rows
            if row.get("report_present") is True and row.get("judge_error") is None
        )
        output_complete = _count_true(
            group_rows,
            "complete_evidence_grounding_output_strict",
        )
        validated_complete = _count_true(
            group_rows,
            "complete_evidence_grounding_validated_strict",
        )
        string_present = _count_true(group_rows, "string_mechanism_present")
        intrusion = _count_true(group_rows, "negative_control_intrusion")
        validation_weighted_rows = [
            {
                **row,
                "required_modality_count_strict_validated": (
                    row.get("required_modality_count_strict", 0)
                    if row.get("validation_passed") is True
                    else 0
                ),
                "required_modality_count_lenient_validated": (
                    row.get("required_modality_count_lenient", 0)
                    if row.get("validation_passed") is True
                    else 0
                ),
            }
            for row in group_rows
        ]
        summary[mode] = {
            "label": MODE_LABELS.get(mode, mode),
            "runs": runs,
            "report_present_runs": report_present_runs,
            "validation_passed_runs": validation_runs,
            "judged_runs": judged_runs,
            "judge_error_count": runs - judged_runs,
            "mean_required_modality_count_strict": _mean(
                group_rows,
                "required_modality_count_strict",
            ),
            "mean_required_modality_count_lenient": _mean(
                group_rows,
                "required_modality_count_lenient",
            ),
            "mean_required_modality_count_strict_validated": _mean(
                validation_weighted_rows,
                "required_modality_count_strict_validated",
            ),
            "mean_required_modality_count_lenient_validated": _mean(
                validation_weighted_rows,
                "required_modality_count_lenient_validated",
            ),
            "open_targets_strict_count": sum(
                1 for row in group_rows if row.get("open_targets_score") == 2
            ),
            "chembl_druggability_strict_count": sum(
                1 for row in group_rows if row.get("chembl_druggability_score") == 2
            ),
            "census_cell_type_strict_count": sum(
                1 for row in group_rows if row.get("census_cell_type_score") == 2
            ),
            "string_network_strict_count": sum(
                1 for row in group_rows if row.get("string_network_score") == 2
            ),
            "string_mechanism_present_count": string_present,
            "string_mechanism_present_rate": string_present / runs if runs else 0.0,
            "negative_control_intrusion_count": intrusion,
            "negative_control_intrusion_rate": intrusion / runs if runs else 0.0,
            "complete_evidence_grounding_output_strict_count": output_complete,
            "complete_evidence_grounding_output_strict_rate": output_complete / runs
            if runs
            else 0.0,
            "complete_evidence_grounding_validated_strict_count": validated_complete,
            "complete_evidence_grounding_validated_strict_rate": validated_complete
            / runs
            if runs
            else 0.0,
        }
    return {"groups": summary}


def output_paths(output_dir: Path, stem: str) -> dict[str, Path]:
    return {
        "jsonl": output_dir / f"{stem}.jsonl",
        "json": output_dir / f"{stem}.json",
        "md": output_dir / f"{stem}.md",
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Selective8 Output Grounding Judge",
        "",
        f"- Source: `{payload['source']}`",
        f"- Judge model: `{payload['metadata']['model']}`",
        "- Judge input: blinded compact `hypothesis_report.json` only",
        "- Complete validated strict: all four required modalities score 2, no negative-control intrusion, and validation passed",
        "",
        "## Mode Summary",
        "",
        "| mode | runs | report | valid | judged | modalities | valid modalities | STRING | output complete | validated complete | neg intrusion |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode, group in payload["aggregate"]["groups"].items():
        runs = int(group["runs"])
        lines.append(
            "| {label} | {runs} | {report} | {valid} | {judged} | {modalities:.2f} | {valid_modalities:.2f} | {string} ({string_rate:.1%}) | {output} ({output_rate:.1%}) | {validated} ({validated_rate:.1%}) | {intrusion} ({intrusion_rate:.1%}) |".format(
                label=group["label"],
                runs=runs,
                report=group["report_present_runs"],
                valid=group["validation_passed_runs"],
                judged=group["judged_runs"],
                modalities=float(group["mean_required_modality_count_strict"]),
                valid_modalities=float(
                    group["mean_required_modality_count_strict_validated"]
                ),
                string=group["string_mechanism_present_count"],
                string_rate=float(group["string_mechanism_present_rate"]),
                output=group["complete_evidence_grounding_output_strict_count"],
                output_rate=float(group["complete_evidence_grounding_output_strict_rate"]),
                validated=group["complete_evidence_grounding_validated_strict_count"],
                validated_rate=float(
                    group["complete_evidence_grounding_validated_strict_rate"]
                ),
                intrusion=group["negative_control_intrusion_count"],
                intrusion_rate=float(group["negative_control_intrusion_rate"]),
            )
        )

    lines.extend(
        [
            "",
            "## Strict Modality Counts",
            "",
            "| mode | Open Targets | ChEMBL/druggability | Census/cell type | STRING/network |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for group in payload["aggregate"]["groups"].values():
        lines.append(
            "| {label} | {ot} | {chembl} | {census} | {string} |".format(
                label=group["label"],
                ot=group["open_targets_strict_count"],
                chembl=group["chembl_druggability_strict_count"],
                census=group["census_cell_type_strict_count"],
                string=group["string_network_strict_count"],
            )
        )

    lines.extend(
        [
            "",
            "## Run Rows",
            "",
            "| mode | repeat | run | valid | strict modalities | STRING | complete validated | judge error |",
            "| --- | ---: | --- | --- | ---: | --- | --- | --- |",
        ]
    )
    for row in payload["rows"]:
        lines.append(
            "| {mode} | {repeat} | `{run_id}` | {valid} | {modalities} | {string} | {complete} | {error} |".format(
                mode=row.get("mode_label"),
                repeat=row.get("repeat"),
                run_id=row.get("run_id"),
                valid=row.get("validation_passed"),
                modalities=row.get("required_modality_count_strict"),
                string=row.get("string_mechanism_present"),
                complete=row.get("complete_evidence_grounding_validated_strict"),
                error=row.get("judge_error") or "-",
            )
        )
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_path", help="Result directory or benchmark_results.json")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--stem", default=DEFAULT_OUTPUT_STEM)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--skip-openai", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    load_dotenv()
    result_path = Path(args.result_path)
    benchmark_results_path = benchmark_path(result_path)
    result_dir = result_dir_for(result_path)
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else result_dir
    paths = output_paths(output_dir, args.stem)
    if args.overwrite:
        for path in paths.values():
            path.unlink(missing_ok=True)

    benchmark = load_json(benchmark_results_path)
    trials = [trial for trial in benchmark.get("trials", []) if isinstance(trial, dict)]
    if args.limit is not None:
        trials = trials[: args.limit]

    existing_rows = load_jsonl(paths["jsonl"])
    completed_run_ids = {row.get("run_id") for row in existing_rows}
    rows = list(existing_rows)

    for index, trial in enumerate(trials, start=1):
        run_id = trial.get("run_id")
        if run_id in completed_run_ids:
            print(f"[skip {index}/{len(trials)}] {run_id}", flush=True)
            continue
        print(f"[judge {index}/{len(trials)}] {run_id}", flush=True)
        try:
            row = score_trial(
                trial,
                model=args.model,
                skip_openai=args.skip_openai,
                temperature=args.temperature,
            )
        except Exception as exc:
            report_path = report_path_for_trial(trial)
            row = {
                **base_row(trial, report_path=report_path),
                **zero_grounding_fields(validation_passed=validation_passed(trial)),
                "judge_payload": None,
                "judge_error": str(exc),
                "input_tokens": 0,
                "output_tokens": 0,
            }
        rows.append(row)
        append_jsonl(paths["jsonl"], row)
        if args.sleep_seconds > 0 and index < len(trials):
            time.sleep(args.sleep_seconds)

    rows.sort(key=lambda row: (str(row.get("mode")), int(row.get("repeat") or 0)))
    payload = {
        "source": str(benchmark_results_path),
        "metadata": {
            "model": args.model,
            "temperature": args.temperature,
            "rubric": "required-modality output grounding; validation merged after blinded judging",
            "required_modalities": list(MODALITY_FIELDS),
            "mode_labels": MODE_LABELS,
            "skip_openai": args.skip_openai,
        },
        "rows": rows,
        "aggregate": aggregate_rows(rows),
        "usage": {
            "input_tokens": sum(int(row.get("input_tokens", 0) or 0) for row in rows),
            "output_tokens": sum(int(row.get("output_tokens", 0) or 0) for row in rows),
        },
    }
    write_json(paths["json"], payload)
    paths["md"].write_text(render_markdown(payload), encoding="utf-8")
    save_jsonl(paths["jsonl"], rows)
    print(f"wrote {paths['json']}")
    print(f"wrote {paths['md']}")
    print(f"wrote {paths['jsonl']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

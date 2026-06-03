"""Build and optionally score content-utility reports from skill ON/OFF search rows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from docs.benchmarks.harness_x_model.common import load_cases, normalize_case
from docs.benchmarks.lr_retrieval_relevance.analyze_content_utility import (
    analyze_results,
    write_report_artifacts,
)
from docs.benchmarks.lr_retrieval_relevance.build_content_utility_reports import (
    DEFAULT_CAP,
    PROTOCOL_MATCHED,
    PROTOCOL_REALUSE,
    SHORT_PROTOCOLS,
    build_content_utility_outputs,
)
from docs.benchmarks.lr_retrieval_relevance.query_trace import (
    append_jsonl,
    sha256_file,
    utc_now,
    write_json,
)


CONDITION_BY_SKILL_ON = {
    ("weak", False): "weak_no_skill",
    ("weak", True): "weak_updated_skill",
    ("strong", False): "strong_no_skill",
    ("strong", True): "strong_updated_skill",
}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _load_skill_rows(skill_results_dir: Path) -> list[dict[str, Any]]:
    summary_path = skill_results_dir / "summary.json"
    if summary_path.exists():
        summary = _read_json(summary_path)
        rows = summary.get("rows", [])
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    rows: list[dict[str, Any]] = []
    rows_dir = skill_results_dir / "rows"
    for path in sorted(rows_dir.glob("*.json")):
        rows.append(_read_json(path))
    return rows


def _cases_by_id(cases_path: Path) -> dict[str, dict[str, Any]]:
    cases = load_cases(cases_path)
    return {str(case["case_id"]): normalize_case(case) for case in cases}


def _ligand_receptor(case: dict[str, Any]) -> tuple[str, str]:
    bundle = case.get("raw_case", {}).get("input_bundle") or {}
    ligand = str(bundle.get("ligand") or "").strip()
    receptor = str(bundle.get("receptor") or "").strip()
    if ligand and receptor:
        return ligand, receptor
    parts = [part.strip() for part in str(case.get("lr_pair") or "").split("-")]
    return (parts[0] if parts else "", parts[1] if len(parts) > 1 else "")


def _resolve_saved_path(row: dict[str, Any]) -> Path:
    candidates: list[Path] = []
    if row.get("papers_path"):
        candidates.append(Path(str(row["papers_path"])).expanduser())
    if row.get("trial_workspace"):
        workspace = Path(str(row["trial_workspace"])).expanduser()
        candidates.extend([workspace / "papers.json", workspace / "papers_raw.json"])
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.exists():
            return resolved
    raise FileNotFoundError(f"no papers artifact for trial_index={row.get('trial_index')}")


def convert_skill_rows_to_content_utility_rows(
    *,
    skill_results_dir: str | Path,
    cases_path: str | Path,
) -> list[dict[str, Any]]:
    rows = _load_skill_rows(Path(skill_results_dir))
    cases = _cases_by_id(Path(cases_path))
    converted: list[dict[str, Any]] = []
    for row in rows:
        case_id = str(row.get("case_id") or "")
        case = cases.get(case_id)
        if case is None:
            raise KeyError(f"case_id not found in cases file: {case_id}")
        ligand, receptor = _ligand_receptor(case)
        repeat = int(row.get("repeat") or 1)
        model_strength = str(row.get("model_strength") or "")
        skill_on = bool(row.get("skill_on"))
        skill_arm = "updated_skill" if skill_on else "no_skill"
        saved_path = _resolve_saved_path(row)
        error = str(row.get("error") or "")
        primary_valid = not error and saved_path.exists()
        primary_invalid_reason = "" if primary_valid else (error or "papers_artifact_missing")
        condition = CONDITION_BY_SKILL_ON.get((model_strength, skill_on), str(row.get("condition") or ""))
        converted.append(
            {
                "row_type": "skill_onoff_content_utility_source_row",
                "generated_at": utc_now(),
                "condition": condition,
                "source_condition": row.get("condition"),
                "skill_arm": skill_arm,
                "model": row.get("model"),
                "model_strength": model_strength,
                "provider": "ollama",
                "temperature": 0.0,
                "repeat": repeat,
                "trial_index": row.get("trial_index"),
                "public_case_id": case_id,
                "case_id": case_id,
                "schedule_block_id": f"{case_id}:r{repeat}",
                "category": row.get("category") or case.get("category"),
                "ligand": ligand,
                "receptor": receptor,
                "lr_pair": row.get("lr_pair") or case.get("lr_pair"),
                "disease": case.get("disease"),
                "pathways": case.get("pathways", []),
                "celltypes": case.get("celltypes", []),
                "trial_workspace": row.get("trial_workspace"),
                "saved_full_json_path": str(saved_path),
                "saved_full_json_path_hash": sha256_file(saved_path),
                "papers_path": str(saved_path),
                "primary_valid": primary_valid,
                "primary_invalid_reason": primary_invalid_reason,
                "dependency_error": "",
                "model_tool_failure": error,
                "raw_paper_count": row.get("total_papers", 0),
                "candidate_unique_papers": row.get("candidate_unique_papers", 0),
                "direct_papers": row.get("direct_papers", 0),
                "context_papers": row.get("context_papers", 0),
                "disease_only_papers": row.get("disease_only_papers", 0),
                "rejected_papers": row.get("rejected_papers", 0),
                "handoff_papers": row.get("handoff_papers", 0),
                "source_skill_results_dir": str(Path(skill_results_dir)),
            }
        )
    return converted


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    for row in rows:
        append_jsonl(path, row)


def _protocols_from_arg(value: str) -> tuple[str, ...]:
    if value == "all":
        return (PROTOCOL_REALUSE, PROTOCOL_MATCHED)
    return (SHORT_PROTOCOLS[value],)


def _format_number(value: Any) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _write_results_ko(path: Path, summary: dict[str, Any], analysis: dict[str, Any] | None) -> None:
    lines = [
        "# CCI Skill ON/OFF Content-Utility Judge 결과",
        "",
        f"- 생성 시각: {utc_now()}",
        f"- score_mode: {summary.get('score_mode')}",
        f"- input rows: {summary.get('input_row_count')}",
        f"- input pairs: {summary.get('input_pair_count')}",
        "",
    ]
    if analysis is None:
        lines.extend(
            [
                "## 결론",
                "",
                "content-utility report와 judge task 생성까지 완료했다. live judge score는 아직 실행하지 않았다.",
            ]
        )
    else:
        primary = analysis["primary"]["primary_strength_balanced_effect"]
        sensitivity = analysis["sensitivity"]["primary_strength_balanced_effect"]
        primary_counts = analysis["primary"]["winner_counts"]
        sensitivity_counts = analysis["sensitivity"]["winner_counts"]
        lines.extend(
            [
                "## 핵심 결과",
                "",
                "| protocol | valid tasks | mean effect | updated wins | no-skill wins | ties |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
                (
                    f"| realuse | {analysis['primary']['valid_task_count']} | "
                    f"{_format_number(primary['mean_effect'])} | "
                    f"{primary_counts['updated_skill']} | {primary_counts['no_skill']} | {primary_counts['tie']} |"
                ),
                (
                    f"| matched | {analysis['sensitivity']['valid_task_count']} | "
                    f"{_format_number(sensitivity['mean_effect'])} | "
                    f"{sensitivity_counts['updated_skill']} | {sensitivity_counts['no_skill']} | {sensitivity_counts['tie']} |"
                ),
                "",
                "## 해석",
                "",
                "- effect는 updated_skill win score에서 tie baseline 0.5를 뺀 값이다.",
                "- 양수이면 skill ON으로 만든 report가 no-skill baseline보다 생물학적으로 더 유용하다고 judge가 본 것이다.",
                "- 이 점수는 논문 검색량 자체가 아니라, 선택된 논문들로 만든 최종 해석 report의 content utility를 비교한다.",
                "",
                "## 최종 결론",
                "",
                "live gpt-5.4 content-utility judge score까지 생성했다. 최종 주장은 full 30-case 결과의 valid task 수와 paired effect를 기준으로 해석해야 한다.",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-results-dir", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument(
        "--protocol",
        choices=("all", "realuse", "matched", PROTOCOL_REALUSE, PROTOCOL_MATCHED),
        default="all",
    )
    parser.add_argument("--score-mode", choices=("none", "dry-run", "live"), default="none")
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=20260503)
    parser.add_argument("--judge-order-seed", type=int, default=20260503)
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP)
    parser.add_argument("--cap-rationale", default="")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    converted_rows = convert_skill_rows_to_content_utility_rows(
        skill_results_dir=args.skill_results_dir,
        cases_path=args.cases,
    )
    converted_path = output_root / "converted_runner_rows.jsonl"
    _write_jsonl(converted_path, converted_rows)

    summary = build_content_utility_outputs(
        runner_rows_path=converted_path,
        output_root=output_root,
        protocols=_protocols_from_arg(args.protocol),
        cap=args.cap,
        cap_rationale=args.cap_rationale,
        score_mode=args.score_mode,
        judge_model=args.model,
        judge_temperature=args.temperature,
        judge_seed=args.seed,
        judge_order_seed=args.judge_order_seed,
        overwrite=args.overwrite,
    )

    analysis: dict[str, Any] | None = None
    if args.score_mode != "none":
        analysis = analyze_results(
            results_root=output_root,
            allow_dry_run=args.score_mode == "dry-run",
            bootstrap_iterations=args.bootstrap_iterations,
            seed=args.seed,
        )
        analysis_path = output_root / "analysis.json"
        write_json(analysis_path, analysis)
        analysis["artifacts"] = write_report_artifacts(analysis, output_root)
        write_json(analysis_path, analysis)

    _write_results_ko(output_root / "RESULTS_KO.md", summary, analysis)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

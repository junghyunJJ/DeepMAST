"""Summarize recovered SNI guardrail ON/OFF post-hoc evaluation rows."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_REPORT_FILES = (
    "part1_final.md",
    "part2_final.md",
    "part3_final.md",
    "synthesis.md",
    "CCI_Analysis_Report.html",
)

ARMS = ("on", "off")
PLANNED_PER_ARM = 20
CORRECTION_KEYS = (
    "deterministic_initial_errors",
    "semantic_initial_errors",
    "initial_errors",
    "final_errors",
    "released_initial_errors",
    "historic_final_errors",
    "normal_repairs",
    "terminal_repairs",
    "changed_sections",
    "changed_claims",
    "before_after_md_pairs",
    "before_after_md_pairs_differ",
)

OPERATIONAL_ERROR_CODES = {
    "claim_evaluation_incomplete",
    "evaluation_failed",
    "missing_required_artifact",
    "report_mutated_by_evaluation",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _report_artifacts(data_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "exists": (data_dir / name).is_file(),
            "bytes": (data_dir / name).stat().st_size if (data_dir / name).is_file() else 0,
        }
        for name in REQUIRED_REPORT_FILES
    }


def _artifacts_complete(artifacts: dict[str, dict[str, Any]]) -> bool:
    return all(item["exists"] and item["bytes"] > 0 for item in artifacts.values())


def _physical_stages(artifacts: dict[str, dict[str, Any]]) -> dict[str, bool]:
    return {
        "part1": artifacts.get("part1_final.md", {}).get("exists", False) and artifacts.get("part1_final.md", {}).get("bytes", 0) > 0,
        "part2": artifacts.get("part2_final.md", {}).get("exists", False) and artifacts.get("part2_final.md", {}).get("bytes", 0) > 0,
        "part3": artifacts.get("part3_final.md", {}).get("exists", False) and artifacts.get("part3_final.md", {}).get("bytes", 0) > 0,
        "synthesis": artifacts.get("synthesis.md", {}).get("exists", False) and artifacts.get("synthesis.md", {}).get("bytes", 0) > 0,
        "html": artifacts.get("CCI_Analysis_Report.html", {}).get("exists", False) and artifacts.get("CCI_Analysis_Report.html", {}).get("bytes", 0) > 0,
    }


def _text_blob(*values: Any) -> str:
    return json.dumps(values, sort_keys=True, default=str).lower()


def _flat(row: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in row and row[key] is not None:
        return row[key]
    return row.get("evaluation", {}).get(key, default)


def _issues(row: dict[str, Any]) -> list[dict[str, Any]]:
    top_level = row.get("issues")
    if top_level:
        return list(top_level)
    return list(row.get("evaluation", {}).get("issues", []) or [])


def _guardrail_initial_errors(guardrail: dict[str, Any]) -> tuple[int, int, int]:
    deterministic = guardrail.get("deterministic_initial_error_count")
    semantic = guardrail.get("semantic_initial_error_count")
    if deterministic is None and semantic is None:
        total = int(guardrail.get("initial_error_count") or 0)
        return 0, 0, total
    deterministic_count = int(deterministic or 0)
    semantic_count = int(semantic or 0)
    return deterministic_count, semantic_count, deterministic_count + semantic_count


def _before_after_counts(data_dir: Path) -> tuple[int, int]:
    before = data_dir / "before"
    after = data_dir / "after"
    if not before.is_dir() or not after.is_dir():
        return 0, 0
    pairs = 0
    differ = 0
    for before_path in before.glob("*.md"):
        after_path = after / before_path.name
        if not after_path.is_file():
            continue
        pairs += 1
        differ += before_path.read_bytes() != after_path.read_bytes()
    return pairs, differ


def _correction_counts(row: dict[str, Any], data_dir: Path, report_complete: bool | None) -> dict[str, int]:
    counts = {key: 0 for key in CORRECTION_KEYS}
    guardrails = [
        _read_json(data_dir / name)
        for name in ("parts_guardrail_result.json", "synthesis_guardrail_result.json")
        if data_dir and (data_dir / name).is_file()
    ]
    if not guardrails:
        counts.update({key: int(value or 0) for key, value in row.get("correction_counts", {}).items() if key in counts})
        return counts
    for guardrail in guardrails:
        deterministic, semantic, initial = _guardrail_initial_errors(guardrail)
        counts["deterministic_initial_errors"] += deterministic
        counts["semantic_initial_errors"] += semantic
        counts["initial_errors"] += initial
        counts["final_errors"] += int(guardrail.get("final_error_count") or 0)
        counts["normal_repairs"] += int(guardrail.get("repair_attempt_count") or 0)
        counts["terminal_repairs"] += int(guardrail.get("terminal_repair_count") or 0)
        counts["changed_sections"] += int(guardrail.get("changed_sections") or 0)
        counts["changed_claims"] += int(guardrail.get("changed_claims") or 0)
    counts["before_after_md_pairs"], counts["before_after_md_pairs_differ"] = _before_after_counts(data_dir)
    if row.get("arm") == "on" and report_complete is True:
        counts["released_initial_errors"] = counts["initial_errors"]
        counts["historic_final_errors"] = counts["final_errors"]
    return counts


def _normalize(row: dict[str, Any]) -> dict[str, Any]:
    data_dir = Path(str(row.get("data_dir", ""))).expanduser() if row.get("data_dir") else Path()
    manifest = _read_json(data_dir / "run_manifest.json") if data_dir else {}
    artifacts = row.get("artifacts") or (_report_artifacts(data_dir) if data_dir else {})
    report_complete = row.get("report_complete")
    if report_complete is None and artifacts:
        report_complete = _artifacts_complete(artifacts)

    issues = _issues(row)
    hard_error_count = _flat(row, "hard_error_count")
    complete = _flat(row, "complete", report_complete)
    usable = _flat(row, "usable")
    status = _flat(row, "status", "pending")
    evaluation_complete = _flat(row, "evaluation_complete", status == "evaluated")
    generation_status = row.get("generation_status", manifest.get("return_status"))
    blob = _text_blob(row.get("failure_reason"), row.get("generation_status"), manifest.get("error"), issues)
    audit_gap = "missing rag audit" in blob and report_complete is True
    classification = row.get("corrected_generation_classification") or row.get("generation_classification")
    if not classification:
        if generation_status == "pending":
            classification = "pending"
        elif report_complete is True:
            classification = "completed"
        elif "guardrail" in blob:
            classification = "guardrail_blocked"
        elif generation_status in {"failed", "error"}:
            classification = "execution_error"
        else:
            classification = "unknown"

    if hard_error_count is not None and hard_error_count > 0:
        outcome = "failed"
    elif usable is True:
        outcome = "passed"
    elif usable is False or complete is False:
        outcome = "failed"
    else:
        outcome = "unknown"

    item = {
        **row,
        "status": status,
        "complete": complete,
        "usable": usable,
        "hard_error_count": hard_error_count,
        "evaluation_complete": evaluation_complete,
        "issues": issues,
        "elapsed_seconds": _flat(row, "elapsed_seconds"),
        "hashes_before": _flat(row, "hashes_before", {}),
        "hashes_after": _flat(row, "hashes_after", {}),
        "report_complete": report_complete,
        "artifacts": artifacts,
        "physical_stages": row.get("physical_stages") or _physical_stages(artifacts),
        "audit_gap": audit_gap,
        "corrected_generation_classification": classification,
        "primary_outcome": outcome,
        "correction_counts": _correction_counts(row, data_dir, report_complete),
    }
    return item


def _rate(count: int, denominator: int) -> float | None:
    return count / denominator if denominator else None


def _seconds(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return {
        "seconds_total": round(sum(values), 3),
        "seconds_mean": round(sum(values) / len(values), 3) if values else None,
        "observations": len(values),
        "tokens_total": None,
    }


def _summarize_arm(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) > PLANNED_PER_ARM:
        raise ValueError(f"row count exceeds planned arm size: {len(rows)}>{PLANNED_PER_ARM}")
    passed = sum(row["primary_outcome"] == "passed" for row in rows)
    failed = sum(row["primary_outcome"] == "failed" for row in rows)
    if passed + failed > PLANNED_PER_ARM:
        raise ValueError(f"assessed rows exceed planned arm size: {passed + failed}>{PLANNED_PER_ARM}")
    unknown = PLANNED_PER_ARM - passed - failed
    complete_outputs = sum(row.get("report_complete") is True for row in rows)
    invalid_outputs = sum(
        row.get("report_complete") is True
        and row.get("hard_error_count") is not None
        and row["hard_error_count"] > 0
        for row in rows
    )
    return {
        "planned": PLANNED_PER_ARM,
        "current_rows": len(rows),
        "assessed": passed + failed,
        "passed": passed,
        "failed": failed,
        "unknown": unknown,
        "pass_bounds": {
            "lower": f"{passed}/{PLANNED_PER_ARM}",
            "upper": f"{passed + unknown}/{PLANNED_PER_ARM}",
            "kind": "known bounds, not CI",
        },
        "complete_outputs": complete_outputs,
        "invalid_output": {
            "count": invalid_outputs,
            "denominator": PLANNED_PER_ARM,
            "rate": _rate(invalid_outputs, PLANNED_PER_ARM),
        },
        "blocked": sum(row["corrected_generation_classification"] == "guardrail_blocked" for row in rows),
        "audit_gap_count": sum(row["audit_gap"] for row in rows),
        "generation_classification": dict(Counter(row["corrected_generation_classification"] for row in rows)),
        "generation_cost": _seconds(rows, "generation_seconds"),
        "evaluation_cost": _seconds(rows, "elapsed_seconds"),
    }


def _known_error_codes(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(
        str(issue.get("code", "unknown"))
        for row in rows
        for issue in row["issues"]
        if issue.get("severity") == "error" and issue.get("code") not in OPERATIONAL_ERROR_CODES
    ))


def _sum_corrections(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {key: sum(row["correction_counts"][key] for row in rows) for key in CORRECTION_KEYS}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = (
        "pair_id",
        "sequence",
        "arm",
        "generation_status",
        "corrected_generation_classification",
        "status",
        "evaluation_complete",
        "complete",
        "report_complete",
        "usable",
        "hard_error_count",
        "primary_outcome",
        "audit_gap",
        "generation_seconds",
        "elapsed_seconds",
        "data_dir",
    )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_markdown(path: Path, result: dict[str, Any]) -> None:
    def minutes(arm: str) -> str:
        seconds = result["summary"][arm]["generation_cost"]["seconds_mean"]
        return "" if seconds is None else f"{seconds / 60:.1f}"

    def invalid(arm: str) -> str:
        item = result["summary"][arm]["invalid_output"]
        return f"{item['count']}/{item['denominator']}"

    def bounds(arm: str) -> str:
        item = result["summary"][arm]["pass_bounds"]
        return f"{item['lower']} to {item['upper']}"

    on_corrections = result["corrections"]["on"]
    lines = [
        "# SNI guardrail ON/OFF post-hoc 비교",
        "",
        f"생성 시각: {result['created_at']}",
        "",
        "주요 지표는 arm당 계획된 20회 전체를 분모로 둔다. 미완료 보고서, 생성 실패, 평가 실패는 통과로 세지 않는다.",
        "unknown이 남아 있으면 범위는 관측 통과부터 관측 통과+unknown까지의 정확한 경계이며 신뢰구간이 아니다.",
        "",
        "| Metric | ON | OFF |",
        "|---|---:|---:|",
        f"| Complete reports | {result['summary']['on']['complete_outputs']}/20 | {result['summary']['off']['complete_outputs']}/20 |",
        f"| Primary passes | {result['summary']['on']['passed']}/20 | {result['summary']['off']['passed']}/20 |",
        f"| Unknown bounds | {bounds('on')} | {bounds('off')} |",
        f"| Known invalid outputs (/20) | {invalid('on')} | {invalid('off')} |",
        f"| Blocked reports | {result['summary']['on']['blocked']} | {result['summary']['off']['blocked']} |",
        f"| Unknown | {result['summary']['on']['unknown']} | {result['summary']['off']['unknown']} |",
        f"| Mean generation minutes | {minutes('on')} | {minutes('off')} |",
    ]
    lines.extend([
        "",
        "## Historic ON correction summary",
        "",
        f"- Initial errors: {on_corrections['initial_errors']} "
        f"(deterministic {on_corrections['deterministic_initial_errors']}, semantic {on_corrections['semantic_initial_errors']})",
        f"- Final staged counter: {on_corrections['final_errors']}",
        f"- Repair passes: ordinary {on_corrections['normal_repairs']}, terminal {on_corrections['terminal_repairs']}",
        f"- Changed sections/claims: {on_corrections['changed_sections']} / {on_corrections['changed_claims']}",
        f"- Before/after Markdown pairs: {on_corrections['before_after_md_pairs']}, different {on_corrections['before_after_md_pairs_differ']}",
        "- Examples: [repair_examples.md](repair_examples.md)",
    ])
    lines.extend(["", "## Known content error codes", ""])
    for arm in ARMS:
        codes = result["known_error_codes"][arm]
        text = ", ".join(f"{code}: {count}" for code, count in sorted(codes.items())) or "none"
        lines.append(f"- {arm.upper()}: {text}")
    lines.extend([
        "",
        "## 해석 한계",
        "",
        "- 이 평가는 사전 정의된 정책 준수 여부이며 전체 과학적 진실성 판정이 아니다.",
        "- ON 과거 실행과 OFF 실행은 달력 시간이 달라 historical calendar confound가 남는다.",
        "- 모든 반복은 하나의 BC dataset에서 나온 실행 반복이며 독립 생물학 표본이 아니다.",
        "- missing RAG audit만 있고 4개 Markdown과 HTML이 완성된 경우는 생성 차단이 아니라 audit gap으로 분리했다.",
        "- 내용 hard error가 확인되면 0-error 주 지표의 불합격은 확정된다. 나머지 의미 검사를 생략한 경우 evaluation_complete=false이며, 표시된 오류 수는 확인된 최소치다.",
        "- 교정 표의 초기·최종 오류는 과거 실행의 단계별 검출 카운터다. 고유한 오류 수나 수정된 문장 수가 아니며, 이번 공통 사후 판정과 구분해야 한다.",
        "- 평가 복구는 기존 성공 체크포인트를 재사용했다. 닫힌 이벤트 루프 재사용을 고쳤으며, 도구 응답 형식이 깨진 경우에만 같은 모델·근거·분류 기준의 JSON 응답으로 복구했다.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_comparison(output_root: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Write comparison.json, comparison.csv, and comparison.md from recovered rows."""
    output_root.mkdir(parents=True, exist_ok=True)
    normalized = [_normalize(row) for row in rows]
    by_arm = {arm: [row for row in normalized if row.get("arm") == arm] for arm in ARMS}
    result = {
        "created_at": _now(),
        "policy": {
            "planned_per_arm": PLANNED_PER_ARM,
            "primary_endpoint": "required reports complete and post-hoc hard_error_count == 0",
            "unknown_bounds": "exact known-pass to known-pass-plus-unknown bounds, not CI",
        },
        "summary": {arm: _summarize_arm(by_arm[arm]) for arm in ARMS},
        "known_error_codes": {arm: _known_error_codes(by_arm[arm]) for arm in ARMS},
        "corrections": {arm: _sum_corrections(by_arm[arm]) for arm in ARMS},
        "rows": normalized,
    }
    result["historical_on_reference"] = {
        **result["corrections"]["on"],
        "runs": len(by_arm["on"]),
        "complete": result["summary"]["on"]["complete_outputs"],
        "historic_guardrail_blocked": [
            f"{row.get('pair_id')}{row.get('sequence')}"
            for row in by_arm["on"]
            if row["corrected_generation_classification"] == "guardrail_blocked"
        ],
        "note": "staged counters are descriptive and not unique corrected-claim counts",
    }
    (output_root / "comparison.json").write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    _write_csv(output_root / "comparison.csv", normalized)
    _write_markdown(output_root / "comparison.md", result)
    return result

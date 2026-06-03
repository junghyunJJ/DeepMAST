"""Aggregate CCI production benchmark run rows into root-level summaries."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _row_paths(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.glob("*/row.json") if path.is_file())


def _load_rows(root: Path) -> list[dict[str, Any]]:
    return [_read_json(path) for path in _row_paths(root)]


def _csv_fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    fields = {field for row in rows for field in row}
    priority = ["run_id", "case_count", "error"]
    return [field for field in priority if field in fields] + sorted(fields - set(priority))


def _csv_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = _csv_fieldnames(rows)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _csv_value(row.get(field, "")) for field in fieldnames})


def _markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _row_has_error(row: dict[str, Any]) -> bool:
    value = row.get("error")
    return bool(value and str(value).strip())


def _failed_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if _row_has_error(row)]


def _write_results_ko(path: Path, title: str, summary: dict[str, Any]) -> None:
    status = summary["status"]
    lines = [
        f"# {title}",
        "",
        f"- 생성 시각: {summary['generated_at_utc']}",
        f"- status: {status}",
        "",
        "## 요약",
        "",
        "| 항목 | 값 |",
        "| --- | ---: |",
        f"| status | {status} |",
        f"| run_count | {summary['run_count']} |",
        f"| failed_runs | {summary['failed_runs']} |",
        "",
        "## 최종 결론",
        "",
    ]
    if status == "NO_DATA":
        lines.append("최종 결론: 집계할 `row.json`이 없어 benchmark 결과를 판정할 수 없다.")
    elif status == "FAIL":
        lines.append("최종 결론: 일부 production benchmark run에서 오류가 보고되어 실패했다.")
        lines.extend(["", "## 실패 Run", "", "| run_id | error |", "| --- | --- |"])
        for row in summary["failed_run_details"]:
            lines.append(
                f"| {_markdown_cell(row.get('run_id', ''))} | "
                f"{_markdown_cell(row.get('error', ''))} |"
            )
    else:
        lines.append("최종 결론: 모든 production benchmark run이 통과했다.")
    path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--title", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    rows = _load_rows(root)
    failed_rows = _failed_rows(rows)
    status = "NO_DATA" if not rows else ("FAIL" if failed_rows else "PASS")
    summary = {
        "generated_at_utc": _utc_now(),
        "run_count": len(rows),
        "failed_runs": len(failed_rows),
        "failed_run_details": [
            {"run_id": row.get("run_id", ""), "error": row.get("error", "")}
            for row in failed_rows
        ],
        "status": status,
        "rows": rows,
    }

    _write_json(root / "summary.json", summary)
    _write_csv(root / "summary.csv", rows)
    _write_results_ko(root / "RESULTS_KO.md", args.title, summary)
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

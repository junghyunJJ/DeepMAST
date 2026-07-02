from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts import repair_report as repair_report_script
from scripts import validate_report as validate_report_script


REQUIRED_REPORT_FILES = (
    "papers.json",
    "part1_final.md",
    "part2_final.md",
    "part3_final.md",
)


def _issue_payload(issues: list[dict[str, str]]) -> dict[str, Any]:
    return {"issue_count": len(issues), "issues": issues}


def _write_issues(path: Path, issues: list[dict[str, str]]) -> None:
    path.write_text(
        json.dumps(_issue_payload(issues), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _error_count(issues: list[dict[str, str]]) -> int:
    return sum(1 for issue in issues if issue.get("severity") == "error")


def _missing_required_files(data_dir: Path) -> list[str]:
    return [name for name in REQUIRED_REPORT_FILES if not (data_dir / name).exists()]


def run_report_guardrail(data_dir: str | Path, *, provider: str | None = None) -> dict[str, Any]:
    data_dir = Path(data_dir).expanduser().resolve()
    missing = _missing_required_files(data_dir)
    if missing:
        return {"status": "skipped", "missing": missing}

    initial_path = data_dir / "report_validation_initial.json"
    final_path = data_dir / "report_validation_final.json"

    initial_issues = validate_report_script.validate_report(data_dir)
    _write_issues(initial_path, initial_issues)
    initial_error_count = _error_count(initial_issues)

    changed_sections = 0
    if initial_error_count:
        changed_sections = repair_report_script.repair_report(
            data_dir,
            initial_path,
            provider=provider,
        )

    final_issues = validate_report_script.validate_report(data_dir)
    _write_issues(final_path, final_issues)
    final_error_count = _error_count(final_issues)

    return {
        "status": "failed" if final_error_count else "passed",
        "initial_issue_count": len(initial_issues),
        "initial_error_count": initial_error_count,
        "changed_sections": changed_sections,
        "final_issue_count": len(final_issues),
        "final_error_count": final_error_count,
    }

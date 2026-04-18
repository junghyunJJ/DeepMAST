"""Batch audit for skill directories.

Walks a parent directory containing skill folders, runs validate_strict on each,
and outputs a severity-sorted report table or JSON envelope.

Run: python -m scripts.audit_all <skills-dir> [--json] [--flat] [--strict]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

from scripts.models import (
    PDF_VERSION,
    TOOL_VERSION,
    Severity,
    ValidationReport,
    build_summary,
)
from scripts.validate_strict import validate_all

SEVERITY_ORDER = {Severity.ERROR: 0, Severity.SOFT_ERROR: 1, Severity.WARNING: 2}


def discover_skills(skills_dir: Path) -> list[Path]:
    """Return sorted list of subdirectories that contain a SKILL.md file."""
    if not skills_dir.is_dir():
        return []
    found = []
    for child in sorted(skills_dir.iterdir()):
        if child.is_dir() and (child / "SKILL.md").is_file():
            found.append(child)
    return found


def sort_results_by_severity(report: ValidationReport) -> ValidationReport:
    """Sort report results: failed first (ERROR > SOFT-ERROR > WARNING), then passed."""
    def _sort_key(r):
        failed_rank = 0 if not r.passed else 1
        sev_rank = SEVERITY_ORDER.get(r.severity, 99)
        return (failed_rank, sev_rank, r.rule_id)

    report.results = sorted(report.results, key=_sort_key)
    return report


def audit_skills(
    skills_dir: Path,
    *,
    strict: bool = False,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Run validate_all on every discovered skill and return the audit envelope."""
    skill_dirs = discover_skills(skills_dir)
    skill_reports: list[dict[str, Any]] = []
    total_passed = 0
    total_failed = 0

    for sd in skill_dirs:
        report = validate_all(sd, agent_id=agent_id, strict=strict)
        report = sort_results_by_severity(report)
        passed = report.summary["passed"]
        if passed:
            total_passed += 1
        else:
            total_failed += 1
        skill_reports.append({
            "skill_name": sd.name,
            "report": report.to_dict(),
        })

    return {
        "audit_version": TOOL_VERSION,
        "pdf_version": PDF_VERSION,
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "skills_dir": str(skills_dir),
        "skills": skill_reports,
        "summary": {
            "total": len(skill_reports),
            "passed": total_passed,
            "failed": total_failed,
        },
    }


def _render_table(envelope: dict[str, Any], strict: bool) -> str:
    """Render a human-readable text table from the audit envelope."""
    lines: list[str] = []
    lines.append(f"Audit: {envelope['skills_dir']}")
    lines.append(f"Tool: {envelope['audit_version']} | PDF: {envelope['pdf_version']} | {envelope['timestamp']}")
    lines.append("")

    for entry in envelope["skills"]:
        skill_name = entry["skill_name"]
        report_data = entry["report"]
        summary = report_data["summary"]
        status = "PASS" if summary["passed"] else "FAIL"
        lines.append(f"{'=' * 60}")
        lines.append(f"[{status}] {skill_name}")

        for r in report_data["results"]:
            if r["passed"]:
                continue
            tag = r["severity"]
            if strict and not r["passed"] and r["severity"] == "SOFT-ERROR":
                tag = "SOFT-ERROR->ERROR"
            lines.append(f"  [{tag}] {r['rule_id']} {r['rule_name']}: {r['message']}")

        lines.append(
            f"  error={summary['error_count']} soft_error={summary['soft_error_count']} "
            f"warning={summary['warning_count']}"
        )
        lines.append("")

    s = envelope["summary"]
    lines.append(f"{'=' * 60}")
    lines.append(f"Total: {s['total']} | Passed: {s['passed']} | Failed: {s['failed']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="audit_all", description="Batch-validate all skills in a directory")
    parser.add_argument("skills_dir", type=Path, help="Parent directory containing skill folders")
    parser.add_argument("--strict", action="store_true", help="Promote SOFT-ERROR to ERROR")
    parser.add_argument("--json", action="store_true", help="Output JSON envelope")
    parser.add_argument("--flat", action="store_true", help="With --json, emit only the skills list")
    parser.add_argument("--agent-id", default=None, help="Optional agent identifier")
    args = parser.parse_args(argv)

    if not args.skills_dir.exists():
        print(f"Directory not found: {args.skills_dir}", file=sys.stderr)
        return 2

    if not args.skills_dir.is_dir():
        print(f"Not a directory: {args.skills_dir}", file=sys.stderr)
        return 2

    envelope = audit_skills(args.skills_dir, strict=args.strict, agent_id=args.agent_id)

    if args.json:
        payload: Any = envelope["skills"] if args.flat else envelope
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(_render_table(envelope, args.strict))

    return 1 if envelope["summary"]["failed"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

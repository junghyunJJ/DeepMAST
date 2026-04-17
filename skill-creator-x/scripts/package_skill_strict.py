"""Strict packager — gates package_skill.py behind validate_strict (ADR-006).

Run: python -m scripts.package_skill_strict <skill-dir> [output-dir] [--no-strict]

Behavior:
  1. Run validate_all() on the skill folder.
  2. If any ERROR is present, abort and print the offending rules.
  3. Unless --no-strict is given, SOFT-ERROR failures also abort (promoted).
  4. Otherwise delegate to the unchanged scripts.package_skill.package_skill().
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts.models import Severity, ValidationReport
from scripts.package_skill import package_skill
from scripts.validate_strict import validate_all


def _blocking_results(report: ValidationReport, strict: bool) -> list:
    blocking = []
    for r in report.results:
        if r.passed:
            continue
        if r.severity is Severity.ERROR:
            blocking.append(r)
        elif strict and r.severity is Severity.SOFT_ERROR:
            blocking.append(r)
    return blocking


def package_skill_strict(skill_path: Path, output_dir: Path | None = None,
                         strict: bool = True) -> Path | None:
    skill_path = Path(skill_path).resolve()
    print(f"🔍 Strict validation: {skill_path}")
    report = validate_all(skill_path, strict=strict)
    blocking = _blocking_results(report, strict=strict)
    if blocking:
        print("❌ Packaging blocked by validate_strict:")
        for r in blocking:
            tag = r.severity.value
            if strict and r.severity is Severity.SOFT_ERROR:
                tag = f"{tag}->ERROR"
            print(f"  [{tag}] {r.rule_id} {r.rule_name} (PDF {r.pdf_reference}): {r.message}")
        print("   Fix the above issues and retry. Use --no-strict to allow SOFT-ERRORs.")
        return None

    summary = report.summary
    print(
        f"✅ validate_strict passed (error={summary['error_count']} "
        f"soft_error={summary['soft_error_count']} warning={summary['warning_count']}; "
        f"strict={strict}). Invoking package_skill ...\n"
    )
    return package_skill(skill_path, output_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="package_skill_strict")
    parser.add_argument("skill_dir", type=Path)
    parser.add_argument("output_dir", nargs="?", type=Path, default=None)
    parser.add_argument("--no-strict", action="store_true",
                        help="Allow SOFT-ERROR rules through (ERROR still blocks)")
    args = parser.parse_args(argv)

    out = package_skill_strict(args.skill_dir, args.output_dir, strict=not args.no_strict)
    return 0 if out is not None else 1


if __name__ == "__main__":
    sys.exit(main())

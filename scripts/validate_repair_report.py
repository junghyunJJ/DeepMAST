#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE = REPO_ROOT / "scripts" / "validate_report.py"
REPAIR = REPO_ROOT / "scripts" / "repair_report.py"


def _has_error_issues(path: Path) -> bool:
    data = json.loads(path.read_text(encoding="utf-8"))
    return any(i.get("severity") == "error" for i in data.get("issues", []))


def _run_validate(data_dir: Path, output: Path) -> int:
    result = subprocess.run(
        [sys.executable, str(VALIDATE), str(data_dir), "--output", str(output)],
        cwd=REPO_ROOT,
        text=True,
        check=False,
    )
    return result.returncode


def _run_repair(data_dir: Path, issues: Path, provider: str | None) -> int:
    cmd = [sys.executable, str(REPAIR), str(data_dir), "--issues", str(issues)]
    if provider:
        cmd.extend(["--provider", provider])
    result = subprocess.run(cmd, cwd=REPO_ROOT, text=True, check=False)
    return result.returncode


def validate_repair_once(data_dir: Path, *, provider: str | None = None) -> int:
    data_dir = data_dir.resolve()
    first = data_dir / "report_validation_initial.json"
    final = data_dir / "report_validation_final.json"

    repair_rc = 0
    _run_validate(data_dir, first)
    if _has_error_issues(first):
        repair_rc = _run_repair(data_dir, first, provider)

    _run_validate(data_dir, final)
    if repair_rc != 0:
        return repair_rc
    return 1 if _has_error_issues(final) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run validate -> repair -> validate once.")
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("--provider", default=None)
    args = parser.parse_args(argv)
    return validate_repair_once(args.data_dir, provider=args.provider)


if __name__ == "__main__":
    sys.exit(main())

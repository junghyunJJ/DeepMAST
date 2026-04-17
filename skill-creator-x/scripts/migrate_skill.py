"""Full migration for legacy skills to PDF-compliant structure.

Handles structural overhaul: missing frontmatter, wrong naming, missing sections.
Uses autofix internally for safe field-level fixes after structural changes.
ADR-010 criteria determine whether migration is needed.

Run: python -m scripts.migrate_skill <skill-dir> [--assess] [--apply] [--yes] [--json]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("pyyaml required: pip install pyyaml", file=sys.stderr)
    raise

from scripts.autofix import autofix, create_backup
from scripts.models import ValidationReport
from scripts.validate_strict import (
    ALLOWED_FRONTMATTER_KEYS,
    _split_frontmatter,
    validate_all,
)


@dataclass
class MigrationAssessment:
    skill_path: str
    needs_migration: bool
    changes_required: list[str] = field(default_factory=list)
    estimated_risk: str = "low"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MigrationResult:
    skill_path: str
    applied: bool
    backup_path: Path | None = None
    git_branch: str | None = None
    changes_made: list[str] = field(default_factory=list)
    diff: str = ""
    before_report: ValidationReport | None = None
    after_report: ValidationReport | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_path": self.skill_path,
            "applied": self.applied,
            "backup_path": str(self.backup_path) if self.backup_path else None,
            "git_branch": self.git_branch,
            "changes_made": self.changes_made,
            "diff": self.diff,
            "before_report": self.before_report.to_dict() if self.before_report else None,
            "after_report": self.after_report.to_dict() if self.after_report else None,
        }


def _detect_git(skill_dir: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(skill_dir), capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _create_migrate_branch(skill_dir: Path, name: str) -> str | None:
    branch = f"skill-migrate/{name}"
    try:
        result = subprocess.run(
            ["git", "checkout", "-b", branch],
            cwd=str(skill_dir), capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return branch
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _unified_diff(old: str, new: str, filename: str = "SKILL.md") -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    ))


def assess_migration(skill_dir: Path) -> MigrationAssessment:
    """Evaluate whether a skill needs full migration per ADR-010."""
    skill_dir = Path(skill_dir).resolve()
    assessment = MigrationAssessment(skill_path=str(skill_dir), needs_migration=False)

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        assessment.needs_migration = True
        assessment.estimated_risk = "high"
        assessment.changes_required.append("SKILL.md file missing or wrong case")

        lower_match = None
        for f in skill_dir.iterdir():
            if f.is_file() and f.name.lower() == "skill.md" and f.name != "SKILL.md":
                lower_match = f.name
                break
        if lower_match:
            assessment.changes_required.append(f"Found '{lower_match}' — needs case rename to SKILL.md")
        return assessment

    report = validate_all(skill_dir)
    failing = {r.rule_id for r in report.results if not r.passed}

    if "FM-005" in failing:
        assessment.needs_migration = True
        assessment.changes_required.append("Missing frontmatter delimiters (FM-005)")

    if "FM-001" in failing and "FM-002" in failing:
        assessment.needs_migration = True
        assessment.changes_required.append("Both filename and folder naming violated (FM-001 + FM-002)")

    if len(failing) >= 5:
        assessment.needs_migration = True
        assessment.changes_required.append(f"{len(failing)} rules violated (threshold: 5)")

    for rule_id in sorted(failing):
        rule_msg = next((r.message for r in report.results if r.rule_id == rule_id and not r.passed), "")
        assessment.changes_required.append(f"{rule_id}: {rule_msg}")

    if assessment.needs_migration:
        if "FM-005" in failing or len(failing) >= 5:
            assessment.estimated_risk = "high"
        elif "FM-001" in failing or "FM-002" in failing:
            assessment.estimated_risk = "medium"
    else:
        assessment.estimated_risk = "low"

    return assessment


def restructure_frontmatter(content: str, skill_dir: Path | None = None) -> str:
    """Add frontmatter delimiters if missing, move unknown keys under metadata."""
    split = _split_frontmatter(content)
    if split is not None:
        fm_text, body = split
        fm = yaml.safe_load(fm_text) or {}
    else:
        fm = {}
        body = "\n" + content

    if "name" not in fm:
        if skill_dir is not None:
            fm["name"] = re.sub(r"[_\s]+", "-", skill_dir.name.strip().lower()).strip("-")
        else:
            fm["name"] = "unnamed-skill"

    if "description" not in fm:
        fm["description"] = "Skill description. Use when the skill is needed."

    unknown = set(fm.keys()) - ALLOWED_FRONTMATTER_KEYS
    if unknown:
        metadata = fm.get("metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        for key in sorted(unknown):
            metadata[key] = fm.pop(key)
        fm["metadata"] = metadata

    fm_text = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False).rstrip("\n")
    return f"---\n{fm_text}\n---\n{body}"


def insert_missing_sections(content: str) -> str:
    """Append missing Common Issues and Examples sections."""
    split = _split_frontmatter(content)
    body = split[1] if split is not None else content

    if not re.search(r"(?im)^#{1,6}\s*(common\s+issues|error\s+handling|troubleshooting)\b", body):
        content = content.rstrip("\n") + "\n\n## Common Issues\n\n### Example Error\nDescribe common error and resolution.\n"

    split2 = _split_frontmatter(content)
    body2 = split2[1] if split2 is not None else content

    if not re.search(r"(?im)^#{1,2}\s+examples?\b", body2):
        content = content.rstrip("\n") + "\n\n## Examples\n\nExample 1: Describe a typical usage.\n"

    return content


def fix_naming(skill_dir: Path, *, dry_run: bool = True) -> list[str]:
    """Fix SKILL.md case and folder kebab-case naming."""
    changes: list[str] = []
    is_git = _detect_git(skill_dir)

    for f in skill_dir.iterdir():
        if f.is_file() and f.name.lower() == "skill.md" and f.name != "SKILL.md":
            if not dry_run:
                new_path = skill_dir / "SKILL.md"
                if is_git:
                    subprocess.run(["git", "mv", str(f), str(new_path)],
                                   cwd=str(skill_dir), capture_output=True, timeout=10)
                else:
                    f.rename(new_path)
            changes.append(f"Rename {f.name} -> SKILL.md")
            break

    folder_name = skill_dir.name
    kebab_name = re.sub(r"[_\s]+", "-", folder_name.strip().lower())
    kebab_name = re.sub(r"-+", "-", kebab_name).strip("-")

    if kebab_name != folder_name:
        new_dir = skill_dir.parent / kebab_name
        if not dry_run and not new_dir.exists():
            if is_git:
                subprocess.run(["git", "mv", str(skill_dir), str(new_dir)],
                               cwd=str(skill_dir.parent), capture_output=True, timeout=10)
            else:
                skill_dir.rename(new_dir)
        changes.append(f"Rename folder {folder_name} -> {kebab_name}")

    return changes


def migrate_skill(
    skill_dir: Path,
    *,
    apply: bool = False,
    yes: bool = False,
    use_git: bool = True,
) -> MigrationResult:
    """Execute full migration on a legacy skill."""
    skill_dir = Path(skill_dir).resolve()
    result = MigrationResult(skill_path=str(skill_dir), applied=False)

    skill_md = skill_dir / "SKILL.md"
    alt_md = None
    if not skill_md.is_file():
        for f in skill_dir.iterdir():
            if f.is_file() and f.name.lower() == "skill.md":
                alt_md = f
                break
        if alt_md is None:
            result.changes_made.append("No SKILL.md found — cannot migrate")
            return result

    before_report = validate_all(skill_dir)
    result.before_report = before_report

    if alt_md:
        original_content = alt_md.read_text(encoding="utf-8")
    else:
        original_content = skill_md.read_text(encoding="utf-8")

    new_content = restructure_frontmatter(original_content, skill_dir=skill_dir)
    result.changes_made.append("Restructured frontmatter")

    new_content = insert_missing_sections(new_content)
    result.changes_made.append("Inserted missing sections")

    diff = _unified_diff(original_content, new_content)
    result.diff = diff

    naming_changes = fix_naming(skill_dir, dry_run=not (apply and yes))
    result.changes_made.extend(naming_changes)

    if apply and yes:
        backup_dir = create_backup(skill_dir)
        result.backup_path = backup_dir

        if use_git and _detect_git(skill_dir):
            branch_name = skill_dir.name
            branch = _create_migrate_branch(skill_dir, branch_name)
            result.git_branch = branch

        target = alt_md if alt_md else skill_md
        target.write_text(new_content, encoding="utf-8")

        if alt_md and alt_md.name != "SKILL.md":
            new_path = skill_dir / "SKILL.md"
            alt_md.rename(new_path)
            result.changes_made.append(f"Renamed {alt_md.name} -> SKILL.md")

        autofix_report = autofix(skill_dir, fix_all_safe=True, dry_run=False, yes=True)
        result.changes_made.append(f"Applied {autofix_report.summary['applied']} autofix rules")

        after_report = validate_all(skill_dir)
        result.after_report = after_report
        result.applied = True
    else:
        result.changes_made.append("dry-run: no changes written")

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="migrate_skill", description="Migrate legacy skills to PDF-compliant format (ADR-010)")
    parser.add_argument("skill_dir", type=Path, help="Skill directory to migrate")
    parser.add_argument("--assess", action="store_true", help="Only assess migration need")
    parser.add_argument("--apply", action="store_true", help="Apply migration")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--no-git", action="store_true", help="Disable git integration")
    args = parser.parse_args(argv)

    if not args.skill_dir.exists():
        print(f"Directory not found: {args.skill_dir}", file=sys.stderr)
        return 2

    if args.assess:
        assessment = assess_migration(args.skill_dir)
        if args.json:
            print(json.dumps(assessment.to_dict(), indent=2, ensure_ascii=False))
        else:
            status = "NEEDS MIGRATION" if assessment.needs_migration else "OK (update only)"
            print(f"Assessment: {assessment.skill_path}")
            print(f"Status: {status}")
            print(f"Risk: {assessment.estimated_risk}")
            if assessment.changes_required:
                print("Changes required:")
                for c in assessment.changes_required:
                    print(f"  - {c}")
        return 0

    result = migrate_skill(
        args.skill_dir,
        apply=args.apply,
        yes=args.yes,
        use_git=not args.no_git,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"Migration: {result.skill_path}")
        print(f"Applied: {result.applied}")
        if result.backup_path:
            print(f"Backup: {result.backup_path}")
        if result.git_branch:
            print(f"Git branch: {result.git_branch}")
        if result.changes_made:
            print("Changes:")
            for c in result.changes_made:
                print(f"  - {c}")
        if result.diff:
            print("\nDiff:")
            print(result.diff)

    return 0


if __name__ == "__main__":
    sys.exit(main())

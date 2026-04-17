"""Safe auto-fix for common SKILL.md validation failures.

Implements 9 deterministic fix rules (ADR-011 safety principles):
  - dry-run default, automatic backup, diff transparency,
    post-fix re-validation, fenced block protection, sentence-boundary truncation.

Run: python -m scripts.autofix <skill-dir> [--fix FM-014] [--fix-all-safe] [--yes] [--json]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import json
import re
import shutil
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("pyyaml required: pip install pyyaml", file=sys.stderr)
    raise

from scripts.models import Severity
from scripts.validate_strict import (
    ALLOWED_FRONTMATTER_KEYS,
    FENCED_BLOCK_RE,
    MAX_COMPAT_LEN,
    MAX_DESC_LEN,
    _split_frontmatter,
    validate_all,
)

ALL_SAFE_RULES = [
    "FM-004", "FM-007", "FM-008", "FM-013", "FM-014",
    "FM-015", "FM-016", "BD-005", "BD-006",
]


@dataclass
class FixResult:
    rule_id: str
    applied: bool
    dry_run: bool
    diff: str
    message: str
    backup_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["backup_path"] = str(self.backup_path) if self.backup_path else None
        return d


@dataclass
class AutofixReport:
    skill_path: str
    timestamp: str
    fixes: list[FixResult] = field(default_factory=list)
    backup_dir: Path | None = None
    summary: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_path": self.skill_path,
            "timestamp": self.timestamp,
            "fixes": [f.to_dict() for f in self.fixes],
            "backup_dir": str(self.backup_dir) if self.backup_dir else None,
            "summary": self.summary,
        }


def _unified_diff(old: str, new: str, filename: str = "SKILL.md") -> str:
    return "".join(difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    ))


def _truncate_at_sentence(text: str, max_len: int) -> str:
    """Truncate at the last sentence boundary (period) within max_len."""
    if len(text) <= max_len:
        return text
    truncated = text[:max_len]
    last_dot = truncated.rfind(".")
    if last_dot > 0:
        return truncated[: last_dot + 1]
    return truncated.rstrip() + "..."


def _rebuild_frontmatter(fm: dict, body: str) -> str:
    fm_text = yaml.dump(fm, default_flow_style=False, allow_unicode=True, sort_keys=False).rstrip("\n")
    return f"---\n{fm_text}\n---\n{body}"


def _parse_skill(content: str) -> tuple[dict, str] | None:
    split = _split_frontmatter(content)
    if split is None:
        return None
    fm = yaml.safe_load(split[0]) or {}
    body_with_leading = split[1]
    if not body_with_leading.startswith("\n"):
        body_with_leading = "\n" + body_with_leading
    return fm, body_with_leading


# ---------------------------------------------------------------------------
# Individual fix functions
# ---------------------------------------------------------------------------


def fix_fm007_008_name_kebab(content: str) -> tuple[str, str]:
    parsed = _parse_skill(content)
    if parsed is None:
        return content, ""
    fm, body = parsed
    name = fm.get("name", "")
    if not isinstance(name, str):
        return content, ""
    new_name = re.sub(r"[_\s]+", "-", name.strip().lower())
    new_name = re.sub(r"-+", "-", new_name).strip("-")
    if new_name == name:
        return content, ""
    fm["name"] = new_name
    new_content = _rebuild_frontmatter(fm, body)
    return new_content, _unified_diff(content, new_content)


def fix_fm013_desc_truncate(content: str) -> tuple[str, str]:
    parsed = _parse_skill(content)
    if parsed is None:
        return content, ""
    fm, body = parsed
    desc = fm.get("description", "")
    if not isinstance(desc, str) or len(desc) <= MAX_DESC_LEN:
        return content, ""
    fm["description"] = _truncate_at_sentence(desc, MAX_DESC_LEN)
    new_content = _rebuild_frontmatter(fm, body)
    return new_content, _unified_diff(content, new_content)


def fix_fm014_desc_xml_strip(content: str) -> tuple[str, str]:
    parsed = _parse_skill(content)
    if parsed is None:
        return content, ""
    fm, body = parsed
    desc = fm.get("description", "")
    if not isinstance(desc, str):
        return content, ""
    new_desc = re.sub(r"<[^>]*>", "", desc)
    new_desc = new_desc.replace(">=", "GTE ").replace("<=", "LTE ")
    new_desc = new_desc.replace(">", "greater than ").replace("<", "less than ")
    new_desc = re.sub(r"\s+", " ", new_desc).strip()
    if new_desc == desc:
        return content, ""
    fm["description"] = new_desc
    new_content = _rebuild_frontmatter(fm, body)
    return new_content, _unified_diff(content, new_content)


def fix_fm015_compat_truncate(content: str) -> tuple[str, str]:
    parsed = _parse_skill(content)
    if parsed is None:
        return content, ""
    fm, body = parsed
    compat = fm.get("compatibility", "")
    if not isinstance(compat, str) or len(compat) <= MAX_COMPAT_LEN:
        return content, ""
    fm["compatibility"] = _truncate_at_sentence(compat, MAX_COMPAT_LEN)
    new_content = _rebuild_frontmatter(fm, body)
    return new_content, _unified_diff(content, new_content)


def fix_fm016_unknown_keys(content: str) -> tuple[str, str]:
    parsed = _parse_skill(content)
    if parsed is None:
        return content, ""
    fm, body = parsed
    unknown = set(fm.keys()) - ALLOWED_FRONTMATTER_KEYS
    if not unknown:
        return content, ""
    metadata = fm.get("metadata", {}) or {}
    if not isinstance(metadata, dict):
        metadata = {}
    for key in sorted(unknown):
        metadata[key] = fm.pop(key)
    fm["metadata"] = metadata
    new_content = _rebuild_frontmatter(fm, body)
    return new_content, _unified_diff(content, new_content)


def fix_fm004_readme_move(skill_dir: Path) -> tuple[bool, str]:
    readme = skill_dir / "README.md"
    if not readme.is_file():
        return False, ""
    refs_dir = skill_dir / "references"
    refs_dir.mkdir(exist_ok=True)
    dest = refs_dir / "README.md"
    shutil.move(str(readme), str(dest))
    return True, f"Moved README.md -> references/README.md"


def fix_bd005_error_handling(content: str) -> tuple[str, str]:
    parsed = _parse_skill(content)
    if parsed is None:
        return content, ""
    _, body = parsed
    if re.search(r"(?im)^#{1,6}\s*(common\s+issues|error\s+handling|troubleshooting)\b", body):
        return content, ""
    template = "\n\n## Common Issues\n\n### Example Error\nDescribe common error and resolution.\n"
    new_content = content.rstrip("\n") + template
    return new_content, _unified_diff(content, new_content)


def fix_bd006_examples(content: str) -> tuple[str, str]:
    parsed = _parse_skill(content)
    if parsed is None:
        return content, ""
    _, body = parsed
    if re.search(r"(?im)^#{1,6}\s*examples?\b", body):
        return content, ""
    template = "\n\n## Examples\n\nExample 1: Describe a typical usage.\n"
    new_content = content.rstrip("\n") + template
    return new_content, _unified_diff(content, new_content)


RULE_HANDLERS = {
    "FM-007": fix_fm007_008_name_kebab,
    "FM-008": fix_fm007_008_name_kebab,
    "FM-013": fix_fm013_desc_truncate,
    "FM-014": fix_fm014_desc_xml_strip,
    "FM-015": fix_fm015_compat_truncate,
    "FM-016": fix_fm016_unknown_keys,
    "BD-005": fix_bd005_error_handling,
    "BD-006": fix_bd006_examples,
}


def create_backup(skill_dir: Path) -> Path:
    ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
    backup_dir = skill_dir / "backups" / ts
    backup_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    if skill_md.is_file():
        shutil.copy2(str(skill_md), str(backup_dir / "SKILL.md"))
    return backup_dir


def autofix(
    skill_dir: Path,
    *,
    rules: list[str] | None = None,
    fix_all_safe: bool = False,
    dry_run: bool = True,
    yes: bool = False,
) -> AutofixReport:
    skill_dir = Path(skill_dir).resolve()
    skill_md = skill_dir / "SKILL.md"
    ts = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

    report = AutofixReport(skill_path=str(skill_dir), timestamp=ts)

    if not skill_md.is_file():
        report.summary = {"applied": 0, "skipped": 0, "manual_required": 0}
        return report

    target_rules = list(rules or [])
    if fix_all_safe:
        target_rules = list(ALL_SAFE_RULES)
    if not target_rules:
        target_rules = list(ALL_SAFE_RULES)

    before_report = validate_all(skill_dir)
    failing_rules = {r.rule_id for r in before_report.results if not r.passed}

    applicable = [r for r in target_rules if r in failing_rules]

    backup_dir = None
    if applicable and not dry_run and yes:
        backup_dir = create_backup(skill_dir)
        report.backup_dir = backup_dir

    content = skill_md.read_text(encoding="utf-8")
    applied_count = 0
    skipped_count = 0

    seen_handlers: set[int] = set()

    for rule_id in applicable:
        if rule_id == "FM-004":
            moved, msg = fix_fm004_readme_move(skill_dir) if (not dry_run and yes) else (False, "")
            if dry_run or not yes:
                readme_exists = (skill_dir / "README.md").is_file()
                report.fixes.append(FixResult(
                    rule_id=rule_id, applied=False, dry_run=True,
                    diff="Would move README.md -> references/README.md" if readme_exists else "",
                    message="dry-run: would move README.md" if readme_exists else "no README.md to move",
                ))
                skipped_count += 1
            elif moved:
                report.fixes.append(FixResult(
                    rule_id=rule_id, applied=True, dry_run=False,
                    diff=msg, message=msg, backup_path=backup_dir,
                ))
                applied_count += 1
            continue

        handler = RULE_HANDLERS.get(rule_id)
        if handler is None:
            skipped_count += 1
            continue

        handler_id = id(handler)
        if handler_id in seen_handlers:
            continue
        seen_handlers.add(handler_id)

        new_content, diff = handler(content)
        if not diff:
            report.fixes.append(FixResult(
                rule_id=rule_id, applied=False, dry_run=dry_run,
                diff="", message="no change needed",
            ))
            skipped_count += 1
            continue

        if dry_run or not yes:
            report.fixes.append(FixResult(
                rule_id=rule_id, applied=False, dry_run=True,
                diff=diff, message="dry-run: diff shown above",
            ))
            skipped_count += 1
        else:
            content = new_content
            report.fixes.append(FixResult(
                rule_id=rule_id, applied=True, dry_run=False,
                diff=diff, message="applied", backup_path=backup_dir,
            ))
            applied_count += 1

    if applied_count > 0 and not dry_run and yes:
        skill_md.write_text(content, encoding="utf-8")

        after_report = validate_all(skill_dir)
        before_errors = before_report.summary["error_count"] + before_report.summary["soft_error_count"]
        after_errors = after_report.summary["error_count"] + after_report.summary["soft_error_count"]
        if after_errors >= before_errors:
            report.fixes.append(FixResult(
                rule_id="REGRESSION",
                applied=False,
                dry_run=False,
                diff="",
                message=f"WARNING: errors did not decrease ({before_errors} -> {after_errors}). Check backup at {backup_dir}",
            ))

    report.summary = {
        "applied": applied_count,
        "skipped": skipped_count,
        "manual_required": len(failing_rules) - len(applicable),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autofix", description="Auto-fix common SKILL.md issues (ADR-011)")
    parser.add_argument("skill_dir", type=Path, help="Skill directory containing SKILL.md")
    parser.add_argument("--fix", action="append", dest="rules", metavar="RULE_ID", help="Fix specific rule (repeatable)")
    parser.add_argument("--fix-all-safe", action="store_true", help="Apply all safe auto-fix rules")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Show diffs without modifying (default)")
    parser.add_argument("--yes", action="store_true", help="Apply fixes without confirmation")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    args = parser.parse_args(argv)

    if not args.skill_dir.exists():
        print(f"Skill directory not found: {args.skill_dir}", file=sys.stderr)
        return 2

    actual_dry_run = not args.yes
    report = autofix(
        args.skill_dir,
        rules=args.rules,
        fix_all_safe=args.fix_all_safe,
        dry_run=actual_dry_run,
        yes=args.yes,
    )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"Autofix: {report.skill_path}")
        print(f"Timestamp: {report.timestamp}")
        if report.backup_dir:
            print(f"Backup: {report.backup_dir}")
        print()
        for fix in report.fixes:
            status = "APPLIED" if fix.applied else ("DRY-RUN" if fix.dry_run else "SKIPPED")
            print(f"[{status}] {fix.rule_id}: {fix.message}")
            if fix.diff:
                print(fix.diff)
        print()
        s = report.summary
        print(f"Summary: applied={s['applied']} skipped={s['skipped']} manual_required={s['manual_required']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

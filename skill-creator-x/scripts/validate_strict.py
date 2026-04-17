"""Strict PDF-compliance validator for Agent Skills.

Implements 25 rules derived from Anthropic's
"The Complete Guide to Building Skills for Claude" (2026-01) using the
3-tier severity model (ADR-007: ERROR / SOFT-ERROR / WARNING).

Run: python -m scripts.validate_strict <skill-dir> [--strict] [--json] [--flat]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("pyyaml required: pip install pyyaml", file=sys.stderr)
    raise

from scripts.models import (
    PDF_VERSION,
    TOOL_VERSION,
    Severity,
    ValidationReport,
    ValidationResult,
    build_summary,
)

RESERVED_WORDS = ("claude", "anthropic")
ALLOWED_FRONTMATTER_KEYS = {
    "name",
    "description",
    "license",
    "allowed-tools",
    "metadata",
    "compatibility",
}
SOFT_ERROR_DISCLAIMER = (
    " [note: PDF prescribes this but the automated check is heuristic-based]"
)
KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
FENCED_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
BLOCKQUOTE_MARKER_RE = re.compile(r"^>\s?", re.MULTILINE)
VERB_HINT_RE = re.compile(r"\b(use|analyze|create|generate|fix|check|build|run|process|extract|convert|write|find|search|review|validate)\b", re.IGNORECASE)
WHEN_HINT_RE = re.compile(r"\b(use when|use for|use if|when user|when the user|use to|for when)\b", re.IGNORECASE)

MAX_SKILL_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_BODY_LINES = 500
MAX_BODY_WORDS = 5000
MAX_NAME_LEN = 64
MAX_DESC_LEN = 1024
MAX_COMPAT_LEN = 500


def _ok(rule_id: str, name: str, severity: Severity, verb: str, ref: str, msg: str = "") -> ValidationResult:
    return ValidationResult(
        rule_id=rule_id,
        rule_name=name,
        severity=severity,
        pdf_verb=verb,
        passed=True,
        message=msg or "OK",
        pdf_reference=ref,
    )


def _fail(rule_id: str, name: str, severity: Severity, verb: str, ref: str, msg: str) -> ValidationResult:
    if severity is Severity.SOFT_ERROR:
        msg = msg + SOFT_ERROR_DISCLAIMER
    return ValidationResult(
        rule_id=rule_id,
        rule_name=name,
        severity=severity,
        pdf_verb=verb,
        passed=False,
        message=msg,
        pdf_reference=ref,
    )


def _strip_fenced_blocks(body: str) -> str:
    return FENCED_BLOCK_RE.sub("", body)


def _strip_code_blocks(body: str) -> str:
    """Strip fenced blocks, inline code spans, and blockquote markers.

    BD-003 applies only to prose — inline code is an explicit code expression
    (e.g., `<path>`, `<skill-name>`) and markdown blockquotes begin with `> `
    which is syntax, not XML. Extends the OQ 1 decision.
    """
    body = FENCED_BLOCK_RE.sub("", body)
    body = INLINE_CODE_RE.sub("", body)
    body = BLOCKQUOTE_MARKER_RE.sub("", body)
    return body


def _split_frontmatter(content: str) -> tuple[str, str] | None:
    """Return (frontmatter_text, body) or None if missing delimiters."""
    if not content.startswith("---"):
        return None
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", content, re.DOTALL)
    if not m:
        return None
    return m.group(1), m.group(2)


def _list_entries(skill_dir: Path) -> list[str]:
    if not skill_dir.is_dir():
        return []
    return [p.name for p in skill_dir.iterdir() if p.is_file()]


def _has_exact_file(skill_dir: Path, filename: str) -> bool:
    """Case-sensitive presence check (APFS/HFS+ default is case-insensitive)."""
    return filename in _list_entries(skill_dir)


def _load_skill_content(skill_dir: Path) -> tuple[Path | None, str | None]:
    """Locate SKILL.md case-sensitively. Return (path, content) or (None, None)."""
    if not _has_exact_file(skill_dir, "SKILL.md"):
        return None, None
    target = skill_dir / "SKILL.md"
    return target, target.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Structure rules (FM-001..004, ST-001, SC-001, SC-002)
# ---------------------------------------------------------------------------


def validate_structure(skill_dir: Path) -> list[ValidationResult]:
    results: list[ValidationResult] = []

    # FM-001: SKILL.md exact filename (case-sensitive even on case-insensitive FS)
    names = _list_entries(skill_dir)
    if "SKILL.md" in names:
        results.append(_ok("FM-001", "skill-md-filename", Severity.ERROR,
                           '"Must be exactly `SKILL.md`"', "p.10"))
    else:
        wrong = next((n for n in names if n.lower() == "skill.md" and n != "SKILL.md"), None)
        msg = (
            f"SKILL.md not found (found '{wrong}' instead; filename is case-sensitive)"
            if wrong else "SKILL.md not found"
        )
        results.append(_fail("FM-001", "skill-md-filename", Severity.ERROR,
                             '"Must be exactly `SKILL.md`"', "p.10", msg))

    # FM-002: folder kebab-case
    folder = skill_dir.name
    if KEBAB_RE.match(folder):
        results.append(_ok("FM-002", "folder-kebab-case", Severity.ERROR,
                           '"Use kebab-case"', "p.10"))
    else:
        results.append(_fail("FM-002", "folder-kebab-case", Severity.ERROR,
                             '"Use kebab-case"', "p.10",
                             f"Folder name '{folder}' is not kebab-case"))

    # FM-004: README.md forbidden inside the skill folder
    if (skill_dir / "README.md").is_file():
        results.append(_fail("FM-004", "no-readme-in-skill", Severity.WARNING,
                             '"Don\'t include README.md"', "p.10",
                             "README.md inside skill folder (use SKILL.md or references/ instead)"))
    else:
        results.append(_ok("FM-004", "no-readme-in-skill", Severity.WARNING,
                           '"Don\'t include README.md"', "p.10"))

    # ST-001: folder size under 10 MB
    if skill_dir.is_dir():
        total = sum(p.stat().st_size for p in skill_dir.rglob("*") if p.is_file())
        if total <= MAX_SKILL_BYTES:
            results.append(_ok("ST-001", "skill-folder-size", Severity.WARNING,
                               '"Compressed as .zip file"', "p.30",
                               f"{total / (1024*1024):.2f} MB"))
        else:
            results.append(_fail("ST-001", "skill-folder-size", Severity.WARNING,
                                 '"Compressed as .zip file"', "p.30",
                                 f"Skill folder is {total / (1024*1024):.2f} MB (limit 10 MB)"))
    return results


# ---------------------------------------------------------------------------
# Frontmatter rules (FM-003, FM-005..016)
# ---------------------------------------------------------------------------


def _description_what_when_heuristic(desc: str) -> tuple[bool, int]:
    """Return (passed, score_out_of_3) for FM-012 heuristic.

    Checks: (1) length >= 20, (2) WHEN keyword, (3) verb. Pass if >= 2/3.
    """
    score = 0
    if len(desc.strip()) >= 20:
        score += 1
    if WHEN_HINT_RE.search(desc):
        score += 1
    if VERB_HINT_RE.search(desc):
        score += 1
    return (score >= 2, score)


def validate_frontmatter(path: Path, skill_dir: Path | None = None) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    content = path.read_text(encoding="utf-8")

    split = _split_frontmatter(content)
    if split is None:
        results.append(_fail("FM-005", "frontmatter-delimiters", Severity.ERROR,
                             '"Correct" (--- delimiters required)', "p.25",
                             "Missing YAML frontmatter `---` delimiters"))
        return results
    results.append(_ok("FM-005", "frontmatter-delimiters", Severity.ERROR,
                       '"Correct" (--- delimiters required)', "p.25"))

    frontmatter_text = split[0]
    try:
        fm = yaml.safe_load(frontmatter_text) or {}
        if not isinstance(fm, dict):
            raise yaml.YAMLError("frontmatter must be a mapping")
    except yaml.YAMLError as e:
        results.append(_fail("FM-005", "frontmatter-yaml-valid", Severity.ERROR,
                             '"Correct" (YAML mapping)', "p.25",
                             f"Invalid YAML in frontmatter: {e}"))
        return results

    # FM-006: name required
    name = fm.get("name")
    if isinstance(name, str) and name.strip():
        results.append(_ok("FM-006", "name-required", Severity.ERROR,
                           '"(required)"', "p.10"))
        name = name.strip()

        # FM-007: kebab-case charset
        if KEBAB_RE.match(name):
            results.append(_ok("FM-007", "name-kebab-charset", Severity.ERROR,
                               '"kebab-case only"', "p.10"))
        else:
            results.append(_fail("FM-007", "name-kebab-charset", Severity.ERROR,
                                 '"kebab-case only"', "p.10",
                                 f"name '{name}' not kebab-case (lowercase letters, digits, hyphens only; no leading/trailing/double hyphens)"))

        # FM-008: no spaces/capitals (subset of FM-007 but reported separately per PDF)
        if " " in name or any(c.isupper() for c in name):
            results.append(_fail("FM-008", "name-no-spaces-or-capitals", Severity.ERROR,
                                 '"No spaces or capitals"', "p.10, p.25",
                                 f"name '{name}' contains spaces or capital letters"))
        else:
            results.append(_ok("FM-008", "name-no-spaces-or-capitals", Severity.ERROR,
                               '"No spaces or capitals"', "p.10, p.25"))

        # FM-009: reserved words
        lowered = name.lower()
        if any(rw in lowered for rw in RESERVED_WORDS):
            results.append(_fail("FM-009", "name-reserved-words", Severity.ERROR,
                                 '"Forbidden" / "(reserved)"', "p.11, p.31",
                                 f"name '{name}' contains reserved token ('claude' or 'anthropic')"))
        else:
            results.append(_ok("FM-009", "name-reserved-words", Severity.ERROR,
                               '"Forbidden" / "(reserved)"', "p.11, p.31"))

        # FM-010: length <= 64
        if len(name) <= MAX_NAME_LEN:
            results.append(_ok("FM-010", "name-length", Severity.ERROR,
                               "spec: <= 64 chars", "schemas.md"))
        else:
            results.append(_fail("FM-010", "name-length", Severity.ERROR,
                                 "spec: <= 64 chars", "schemas.md",
                                 f"name is {len(name)} chars (max {MAX_NAME_LEN})"))

        # FM-003: folder == name (SOFT-ERROR; see footnote [1] in plan v2.1)
        if skill_dir is not None:
            if skill_dir.name == name:
                results.append(_ok("FM-003", "folder-name-match", Severity.SOFT_ERROR,
                                   '"Should match folder name"', "p.10"))
            else:
                results.append(_fail("FM-003", "folder-name-match", Severity.SOFT_ERROR,
                                     '"Should match folder name"', "p.10",
                                     f"folder '{skill_dir.name}' != name '{name}' (breaks Cursor/Copilot loading)"))
    else:
        results.append(_fail("FM-006", "name-required", Severity.ERROR,
                             '"(required)"', "p.10",
                             "Missing or empty `name` in frontmatter"))

    # FM-011: description required
    desc = fm.get("description")
    if isinstance(desc, str) and desc.strip():
        results.append(_ok("FM-011", "description-required", Severity.ERROR,
                           '"(required)"', "p.10"))
        desc = desc.strip()

        # FM-012: WHAT + WHEN heuristic (SOFT-ERROR)
        passed, score = _description_what_when_heuristic(desc)
        if passed:
            results.append(_ok("FM-012", "description-what-when", Severity.SOFT_ERROR,
                               '"MUST include BOTH"', "p.10",
                               f"heuristic score {score}/3"))
        else:
            results.append(_fail("FM-012", "description-what-when", Severity.SOFT_ERROR,
                                 '"MUST include BOTH"', "p.10",
                                 f"description may be missing WHAT or WHEN (heuristic score {score}/3; expect >=2)"))

        # FM-013: length <= 1024
        if len(desc) <= MAX_DESC_LEN:
            results.append(_ok("FM-013", "description-length", Severity.ERROR,
                               '"Under 1024 characters"', "p.10, p.31"))
        else:
            results.append(_fail("FM-013", "description-length", Severity.ERROR,
                                 '"Under 1024 characters"', "p.10, p.31",
                                 f"description is {len(desc)} chars (max {MAX_DESC_LEN})"))

        # FM-014: no XML brackets in description
        if "<" in desc or ">" in desc:
            results.append(_fail("FM-014", "description-no-xml", Severity.ERROR,
                                 '"No XML tags (< or >)"', "p.10, p.31",
                                 "description contains `<` or `>` (forbidden in frontmatter)"))
        else:
            results.append(_ok("FM-014", "description-no-xml", Severity.ERROR,
                               '"No XML tags (< or >)"', "p.10, p.31"))
    else:
        results.append(_fail("FM-011", "description-required", Severity.ERROR,
                             '"(required)"', "p.10",
                             "Missing or empty `description` in frontmatter"))

    # FM-015: compatibility length (only if present)
    compat = fm.get("compatibility")
    if compat is not None:
        if isinstance(compat, str) and 1 <= len(compat) <= MAX_COMPAT_LEN:
            results.append(_ok("FM-015", "compatibility-length", Severity.ERROR,
                               '"1-500 characters"', "p.11"))
        else:
            length = len(compat) if isinstance(compat, str) else -1
            results.append(_fail("FM-015", "compatibility-length", Severity.ERROR,
                                 '"1-500 characters"', "p.11",
                                 f"compatibility length {length} outside [1, {MAX_COMPAT_LEN}]"))

    # FM-016: only allowed top-level keys
    unknown = set(fm.keys()) - ALLOWED_FRONTMATTER_KEYS
    if unknown:
        results.append(_fail("FM-016", "frontmatter-allowed-keys", Severity.ERROR,
                             "Reference B schema (implied)", "p.31",
                             f"Unknown frontmatter keys: {sorted(unknown)} (allowed: {sorted(ALLOWED_FRONTMATTER_KEYS)})"))
    else:
        results.append(_ok("FM-016", "frontmatter-allowed-keys", Severity.ERROR,
                           "Reference B schema (implied)", "p.31"))

    return results


# ---------------------------------------------------------------------------
# Body rules (BD-001..006)
# ---------------------------------------------------------------------------


def validate_body(path: Path) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    content = path.read_text(encoding="utf-8")

    split = _split_frontmatter(content)
    body = split[1] if split is not None else content

    # BD-001: <= 500 lines (body only)
    line_count = body.count("\n") + (0 if body.endswith("\n") or not body else 1)
    if line_count <= MAX_BODY_LINES:
        results.append(_ok("BD-001", "body-line-count", Severity.WARNING,
                           '"Keep SKILL.md under 500 lines" (recommended)', "p.5",
                           f"{line_count} lines"))
    else:
        results.append(_fail("BD-001", "body-line-count", Severity.WARNING,
                             '"Keep SKILL.md under 500 lines" (recommended)', "p.5",
                             f"body is {line_count} lines (target <= {MAX_BODY_LINES})"))

    # BD-002: <= 5000 words (split on whitespace per OQ 6 default)
    word_count = len(body.split())
    if word_count <= MAX_BODY_WORDS:
        results.append(_ok("BD-002", "body-word-count", Severity.WARNING,
                           '"Keep SKILL.md under 5,000 words" (recommended)', "p.27",
                           f"{word_count} words"))
    else:
        results.append(_fail("BD-002", "body-word-count", Severity.WARNING,
                             '"Keep SKILL.md under 5,000 words" (recommended)', "p.27",
                             f"body is {word_count} words (target <= {MAX_BODY_WORDS})"))

    # BD-003: XML brackets outside fenced blocks AND outside inline code (OQ 1 decision)
    body_stripped = _strip_code_blocks(body)
    if "<" in body_stripped or ">" in body_stripped:
        results.append(_fail("BD-003", "body-no-xml-outside-fences", Severity.SOFT_ERROR,
                             '"No XML tags (< >)"', "p.11, p.30, p.31",
                             "body contains `<` or `>` outside fenced code blocks or inline code"))
    else:
        results.append(_ok("BD-003", "body-no-xml-outside-fences", Severity.SOFT_ERROR,
                           '"No XML tags (< >)"', "p.11, p.30, p.31"))

    # BD-004: specific and actionable instructions (heuristic)
    #   PASS if body contains an imperative cue (numbered list OR run command).
    actionable = bool(re.search(r"(^|\n)\d+\.\s+\S", body) or re.search(r"`[^`]{0,60}`", body))
    if actionable:
        results.append(_ok("BD-004", "body-actionable-instructions", Severity.WARNING,
                           '"Be Specific and Actionable"', "p.13"))
    else:
        results.append(_fail("BD-004", "body-actionable-instructions", Severity.WARNING,
                             '"Be Specific and Actionable"', "p.13",
                             "body lacks numbered steps or inline command examples (heuristic)"))

    # BD-005: error handling section (SOFT-ERROR)
    if re.search(r"(?im)^#{1,6}\s*(common\s+issues|error\s+handling|troubleshooting)\b", body):
        results.append(_ok("BD-005", "body-error-handling", Severity.SOFT_ERROR,
                           '"Include error handling"', "p.12-13"))
    else:
        results.append(_fail("BD-005", "body-error-handling", Severity.SOFT_ERROR,
                             '"Include error handling"', "p.12-13",
                             "no '## Common Issues' / '## Error Handling' / '## Troubleshooting' heading found"))

    # BD-006: examples section (WARNING)
    if re.search(r"(?im)^#{1,6}\s*examples?\b", body):
        results.append(_ok("BD-006", "body-examples-section", Severity.WARNING,
                           '"Examples" (recommended)', "p.12"))
    else:
        results.append(_fail("BD-006", "body-examples-section", Severity.WARNING,
                             '"Examples" (recommended)', "p.12",
                             "no '## Examples' heading found"))

    return results


# ---------------------------------------------------------------------------
# References integrity (SC-001, SC-002)
# ---------------------------------------------------------------------------

REF_LINK_RE = re.compile(r"(?<![\w/])(references|scripts|assets)/([\w/-]+(?:\.[\w-]+)*)")


def validate_references(skill_dir: Path, skill_md: Path) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    body = skill_md.read_text(encoding="utf-8")
    body_no_fences = _strip_fenced_blocks(body)

    # SC-001: scripts/ files look runnable (shebang or .py/.sh/.js extension)
    scripts_dir = skill_dir / "scripts"
    if scripts_dir.is_dir():
        files = [p for p in scripts_dir.iterdir() if p.is_file() and not p.name.startswith("__")]
        bad: list[str] = []
        for f in files:
            if f.suffix in {".py", ".sh", ".js", ".ts", ".rb", ".mjs"}:
                continue
            # fallback: shebang check
            try:
                head = f.read_bytes()[:128]
                if head.startswith(b"#!"):
                    continue
            except OSError:
                pass
            bad.append(f.name)
        if not bad:
            results.append(_ok("SC-001", "scripts-runnable", Severity.WARNING,
                               "structural (implied)", "p.10"))
        else:
            results.append(_fail("SC-001", "scripts-runnable", Severity.WARNING,
                                 "structural (implied)", "p.10",
                                 f"scripts/ contains files with no recognizable runtime hint: {bad}"))
    else:
        results.append(_ok("SC-001", "scripts-runnable", Severity.WARNING,
                           "structural (implied)", "p.10", "no scripts/ directory (OK)"))

    # SC-002: referenced files under references/ scripts/ assets/ exist
    missing: list[str] = []
    seen: set[str] = set()
    for m in REF_LINK_RE.finditer(body_no_fences):
        rel = f"{m.group(1)}/{m.group(2)}"
        if rel in seen:
            continue
        seen.add(rel)
        if not (skill_dir / rel).exists():
            missing.append(rel)
    if not missing:
        results.append(_ok("SC-002", "referenced-files-exist", Severity.ERROR,
                           '"Reference bundled resources clearly"', "p.13"))
    else:
        results.append(_fail("SC-002", "referenced-files-exist", Severity.ERROR,
                             '"Reference bundled resources clearly"', "p.13",
                             f"SKILL.md references missing files: {missing}"))
    return results


# ---------------------------------------------------------------------------
# Convenience: validate_security (subset re-export for external callers)
# ---------------------------------------------------------------------------


def validate_security(path: Path) -> list[ValidationResult]:
    """Re-run just the security-oriented rules (FM-009, FM-014, BD-003)."""
    picked: list[ValidationResult] = []
    for r in validate_frontmatter(path):
        if r.rule_id in {"FM-009", "FM-014"}:
            picked.append(r)
    for r in validate_body(path):
        if r.rule_id == "BD-003":
            picked.append(r)
    return picked


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def validate_all(skill_dir: Path, *, agent_id: str | None = None, strict: bool = False) -> ValidationReport:
    skill_dir = Path(skill_dir).resolve()
    results = validate_structure(skill_dir)

    skill_md, _ = _load_skill_content(skill_dir)
    if skill_md is not None:
        results.extend(validate_frontmatter(skill_md, skill_dir=skill_dir))
        results.extend(validate_body(skill_md))
        results.extend(validate_references(skill_dir, skill_md))

    summary = build_summary(results, strict=strict)
    return ValidationReport(
        tool_version=TOOL_VERSION,
        pdf_version=PDF_VERSION,
        timestamp=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        skill_path=str(skill_dir),
        agent_id=agent_id,
        results=results,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _render_text(report: ValidationReport, strict: bool) -> str:
    lines = [
        f"Skill: {report.skill_path}",
        f"Tool: {report.tool_version} | PDF: {report.pdf_version} | {report.timestamp}",
        "",
    ]
    for r in report.results:
        symbol = "✅" if r.passed else ("🚫" if r.severity is Severity.ERROR else ("⚠️ " if r.severity is Severity.WARNING else "⚠️ "))
        # In strict mode, SOFT-ERROR failures are effectively ERRORs.
        tag = r.severity.value
        if strict and not r.passed and r.severity is Severity.SOFT_ERROR:
            tag = f"{Severity.SOFT_ERROR.value}->ERROR"
        lines.append(f"{symbol} [{tag}] {r.rule_id} {r.rule_name} (PDF {r.pdf_reference}): {r.message}")
    s = report.summary
    lines.append("")
    lines.append(
        f"Summary: error={s['error_count']} soft_error={s['soft_error_count']} warning={s['warning_count']} "
        f"strict={s['strict']} passed={s['passed']}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validate_strict")
    parser.add_argument("skill_dir", type=Path)
    parser.add_argument("--strict", action="store_true",
                        help="Promote SOFT-ERROR failures to ERROR (WARNING stays WARNING)")
    parser.add_argument("--json", action="store_true", help="Emit JSON envelope (ADR-009)")
    parser.add_argument("--flat", action="store_true",
                        help="With --json, emit only the results list (no envelope)")
    parser.add_argument("--agent-id", default=os.environ.get("SKILL_CREATOR_X_AGENT_ID"),
                        help="Optional agent identifier stored in the report envelope")
    args = parser.parse_args(argv)

    if not args.skill_dir.exists():
        print(f"Skill directory not found: {args.skill_dir}", file=sys.stderr)
        return 2

    report = validate_all(args.skill_dir, agent_id=args.agent_id, strict=args.strict)

    if args.json:
        payload: Any = [r.to_dict() for r in report.results] if args.flat else report.to_dict()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(_render_text(report, args.strict))

    # Exit code: effective errors fail, SOFT-ERROR counts only in --strict.
    effective_errors = report.summary["error_count"] + (report.summary["soft_error_count"] if args.strict else 0)
    return 1 if effective_errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())

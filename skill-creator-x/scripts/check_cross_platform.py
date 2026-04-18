"""Cross-platform skill compatibility checker.

Validates that a skill directory structure is compatible with each
supported AI coding platform's conventions.

CLI:
    python -m scripts.check_cross_platform <skill-dir> \
        [--platforms claude,codex,cursor,gemini,copilot] [--json] [--flat]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from scripts.models import Platform, PlatformCheckResult


def get_known_platforms() -> list[Platform]:
    home = Path.home()
    return [
        Platform(
            name="claude",
            skill_dir=home / ".claude" / "skills",
            config_marker=home / ".claude",
            activation_method="automatic",
            constraints=[],
        ),
        Platform(
            name="codex",
            skill_dir=home / ".codex" / "skills",
            config_marker=home / ".codex",
            activation_method="automatic",
            constraints=["Verify Python path when running scripts/"],
        ),
        Platform(
            name="cursor",
            skill_dir=Path(".cursor") / "skills",
            config_marker=Path(".cursor"),
            activation_method="project-open",
            constraints=["Project scope only (no global install)"],
        ),
        Platform(
            name="gemini",
            skill_dir=home / ".gemini" / "skills",
            config_marker=home / ".gemini",
            activation_method="manual",
            constraints=["Verify SKILL.md parsing scope"],
        ),
        Platform(
            name="copilot",
            skill_dir=Path(".github") / "skills",
            config_marker=Path(".github"),
            activation_method="repository",
            constraints=["Depends on GitHub Copilot skills support level"],
        ),
    ]


def detect_installed_platforms() -> list[Platform]:
    installed = []
    for platform in get_known_platforms():
        marker = platform.config_marker
        if not marker.is_absolute():
            marker = Path.cwd() / marker
        if marker.exists():
            installed.append(platform)
    return installed


def _read_skill_name(skill_dir: Path) -> str | None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        fm = yaml.safe_load(parts[1])
        return fm.get("name") if isinstance(fm, dict) else None
    except yaml.YAMLError:
        return None


def check_compatibility(skill_dir: Path, platform: Platform) -> PlatformCheckResult:
    issues: list[str] = []
    suggestions: list[str] = []

    skill_dir = Path(skill_dir)
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.exists():
        return PlatformCheckResult(
            platform=platform,
            compatible=False,
            issues=["SKILL.md not found"],
        )

    folder_name = skill_dir.name
    skill_name = _read_skill_name(skill_dir)

    if skill_name and folder_name != skill_name:
        if platform.name in ("cursor", "copilot"):
            issues.append(
                f"Folder '{folder_name}' != name '{skill_name}': "
                f"{platform.name} may fail to load the skill"
            )
        else:
            suggestions.append(
                f"Folder '{folder_name}' != name '{skill_name}': "
                f"consider renaming for consistency"
            )

    if platform.name == "cursor":
        if skill_dir.is_absolute():
            suggestions.append(
                "Cursor uses project-local .cursor/skills/ — "
                "install with relative path"
            )

    scripts_dir = skill_dir / "scripts"
    if scripts_dir.exists() and platform.name == "codex":
        py_files = list(scripts_dir.glob("*.py"))
        if py_files:
            suggestions.append(
                "Codex CLI: verify Python path is available for scripts/"
            )

    if platform.constraints:
        for c in platform.constraints:
            suggestions.append(f"Platform constraint: {c}")

    compatible = len(issues) == 0
    return PlatformCheckResult(
        platform=platform,
        compatible=compatible,
        issues=issues,
        suggestions=suggestions,
    )


def check_all_platforms(
    skill_dir: Path,
    platforms: list[Platform] | None = None,
) -> list[PlatformCheckResult]:
    if platforms is None:
        platforms = get_known_platforms()
    return [check_compatibility(skill_dir, p) for p in platforms]


def _result_to_dict(r: PlatformCheckResult) -> dict:
    return {
        "platform": r.platform.name,
        "compatible": r.compatible,
        "issues": r.issues,
        "suggestions": r.suggestions,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check skill compatibility across platforms",
    )
    parser.add_argument("skill_dir", type=Path, help="Path to skill directory")
    parser.add_argument(
        "--platforms",
        type=str,
        default=None,
        help="Comma-separated platform names (default: all)",
    )
    parser.add_argument("--json", dest="json_output", action="store_true")
    parser.add_argument(
        "--flat",
        action="store_true",
        help="JSON output without envelope",
    )
    args = parser.parse_args(argv)

    skill_dir = args.skill_dir.resolve()
    if not skill_dir.exists():
        print(f"Error: {skill_dir} does not exist", file=sys.stderr)
        return 1

    all_platforms = {p.name: p for p in get_known_platforms()}
    if args.platforms:
        names = [n.strip() for n in args.platforms.split(",")]
        selected = []
        for n in names:
            if n not in all_platforms:
                print(f"Unknown platform: {n}", file=sys.stderr)
                return 1
            selected.append(all_platforms[n])
    else:
        selected = list(all_platforms.values())

    results = check_all_platforms(skill_dir, selected)

    if args.json_output:
        data = [_result_to_dict(r) for r in results]
        if args.flat:
            print(json.dumps(data, indent=2))
        else:
            from datetime import datetime, timezone

            from scripts.models import PDF_VERSION, TOOL_VERSION

            envelope = {
                "tool_version": TOOL_VERSION,
                "pdf_version": PDF_VERSION,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "skill_path": str(skill_dir),
                "results": data,
            }
            print(json.dumps(envelope, indent=2))
    else:
        any_issue = False
        for r in results:
            icon = "pass" if r.compatible else "FAIL"
            print(f"[{icon}] {r.platform.name}")
            for issue in r.issues:
                print(f"  issue: {issue}")
                any_issue = True
            for s in r.suggestions:
                print(f"  suggestion: {s}")

        if any_issue:
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

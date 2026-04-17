"""Multi-platform skill installer.

Installs (or uninstalls) a skill directory to detected AI coding platforms
via symlink or copy.  --dry-run is the default for safety.

CLI:
    python -m scripts.install_multiplatform <skill-path> \
        [--target all|claude|codex|cursor|gemini|copilot] \
        [--method copy|symlink] [--dry-run] [--no-dry-run] \
        [--uninstall] [--json] [--flat]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from scripts.check_cross_platform import get_known_platforms
from scripts.models import InstallResult, Platform


def detect_platforms() -> list[Platform]:
    installed = []
    for platform in get_known_platforms():
        marker = platform.config_marker
        if not marker.is_absolute():
            marker = Path.cwd() / marker
        if marker.exists():
            installed.append(platform)
    return installed


def _resolve_target_dir(platform: Platform, skill_name: str) -> Path:
    skill_dir = platform.skill_dir
    if not skill_dir.is_absolute():
        skill_dir = Path.cwd() / skill_dir
    return skill_dir / skill_name


def install_to_platform(
    skill_path: Path,
    platform: Platform,
    method: str = "symlink",
    dry_run: bool = True,
) -> InstallResult:
    skill_path = Path(skill_path).resolve()
    skill_name = skill_path.name

    target = _resolve_target_dir(platform, skill_name)

    if dry_run:
        action = "symlink" if method == "symlink" else "copy"
        return InstallResult(
            platform=platform.name,
            success=True,
            installed_path=target,
            method=action,
            error=f"dry-run: would {action} {skill_path} -> {target}",
        )

    try:
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists() or target.is_symlink():
            if target.is_symlink():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

        if method == "symlink":
            target.symlink_to(skill_path)
        else:
            shutil.copytree(skill_path, target)

        return InstallResult(
            platform=platform.name,
            success=True,
            installed_path=target,
            method=method,
        )
    except OSError as e:
        return InstallResult(
            platform=platform.name,
            success=False,
            installed_path=None,
            method=method,
            error=str(e),
        )


def verify_installation(platform: Platform, skill_name: str) -> bool:
    target = _resolve_target_dir(platform, skill_name)
    skill_md = target / "SKILL.md"
    return skill_md.exists()


def uninstall_from_platform(platform: Platform, skill_name: str) -> bool:
    target = _resolve_target_dir(platform, skill_name)

    if not target.exists() and not target.is_symlink():
        return False

    try:
        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return True
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install/uninstall skill to AI coding platforms",
    )
    parser.add_argument("skill_path", type=Path, help="Path to skill directory")
    parser.add_argument(
        "--target",
        type=str,
        default="all",
        help="Target platform(s): all, or comma-separated names",
    )
    parser.add_argument(
        "--method",
        choices=["copy", "symlink"],
        default="symlink",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
    )
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--json", dest="json_output", action="store_true")
    parser.add_argument("--flat", action="store_true")
    args = parser.parse_args(argv)

    skill_path = args.skill_path.resolve()
    if not skill_path.exists():
        print(f"Error: {skill_path} does not exist", file=sys.stderr)
        return 1

    all_platforms = {p.name: p for p in get_known_platforms()}

    if args.target == "all":
        selected = detect_platforms()
        if not selected:
            selected = list(all_platforms.values())
    else:
        names = [n.strip() for n in args.target.split(",")]
        selected = []
        for n in names:
            if n not in all_platforms:
                print(f"Unknown platform: {n}", file=sys.stderr)
                return 1
            selected.append(all_platforms[n])

    skill_name = skill_path.name

    if args.uninstall:
        results = []
        for p in selected:
            ok = uninstall_from_platform(p, skill_name)
            results.append({
                "platform": p.name,
                "uninstalled": ok,
            })
        if args.json_output:
            print(json.dumps(results if args.flat else _envelope(skill_path, results), indent=2))
        else:
            for r in results:
                status = "removed" if r["uninstalled"] else "not found"
                print(f"[{status}] {r['platform']}")
        return 0

    install_results: list[InstallResult] = []
    for p in selected:
        result = install_to_platform(skill_path, p, args.method, args.dry_run)
        install_results.append(result)

    if args.json_output:
        data = [r.to_dict() for r in install_results]
        if args.flat:
            print(json.dumps(data, indent=2))
        else:
            print(json.dumps(_envelope(skill_path, data), indent=2))
    else:
        for r in install_results:
            icon = "OK" if r.success else "FAIL"
            print(f"[{icon}] {r.platform} -> {r.installed_path}")
            if r.error:
                print(f"  {r.error}")

    failed = [r for r in install_results if not r.success]
    return 1 if failed else 0


def _envelope(skill_path: Path, data: list) -> dict:
    from datetime import datetime, timezone

    from scripts.models import PDF_VERSION, TOOL_VERSION

    return {
        "tool_version": TOOL_VERSION,
        "pdf_version": PDF_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill_path": str(skill_path),
        "results": data,
    }


if __name__ == "__main__":
    raise SystemExit(main())

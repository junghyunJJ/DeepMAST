"""Multi-platform skill installer.

Installs (or uninstalls) a skill directory to detected AI coding platforms
via symlink or copy.  --dry-run is the default for safety.

Destructive-op guards (P1-2, deepwork review):
- Overwriting an existing non-symlink target requires --force; the previous
  target is renamed to ``<target>.bak-<UTCtimestamp>`` (atomic, recoverable),
  never rmtree'd.
- Cursor and Copilot use relative platform paths (``.cursor/skills``,
  ``.github/skills``). When any such platform is selected, --project-root
  must be supplied; otherwise the installer refuses rather than silently
  writing into the caller's CWD.
- In a TTY, --no-dry-run + --force additionally requires the operator to
  echo the absolute target path on stdin. Piped/non-TTY invocations
  (``yes | ...``, CI) bypass this so automation is unaffected.

CLI:
    python -m scripts.install_multiplatform <skill-path> \\
        [--target all|claude|codex|cursor|gemini|copilot] \\
        [--method copy|symlink] [--dry-run] [--no-dry-run] [--force] \\
        [--project-root /path/to/repo] \\
        [--uninstall] [--json] [--flat]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from scripts.check_cross_platform import get_known_platforms
from scripts.models import InstallResult, Platform


class SafetyError(RuntimeError):
    """Raised when an install operation refuses to proceed for safety reasons."""


def detect_platforms() -> list[Platform]:
    installed = []
    for platform in get_known_platforms():
        marker = platform.config_marker
        if not marker.is_absolute():
            marker = Path.cwd() / marker
        if marker.exists():
            installed.append(platform)
    return installed


def _resolve_target_dir(
    platform: Platform,
    skill_name: str,
    project_root: Path | None = None,
) -> Path:
    """Resolve the install target for ``skill_name`` under ``platform``.

    - Absolute ``platform.skill_dir`` (claude/codex/gemini): used directly.
      ``project_root`` is ignored and need not be supplied.
    - Relative ``platform.skill_dir`` (cursor/copilot): ``project_root`` MUST
      be supplied; otherwise :class:`SafetyError` is raised. Historically this
      silently joined against ``Path.cwd()``, which installed skills to
      whatever directory the CLI happened to be invoked from — a surprising
      footgun for relative-path platforms.
    """
    skill_dir = platform.skill_dir
    if skill_dir.is_absolute():
        return skill_dir / skill_name
    if project_root is not None:
        return (project_root / skill_dir / skill_name).resolve()
    raise SafetyError(
        f"--project-root required for relative platform paths ({platform.name})"
    )


def _read_target_frontmatter_name(target: Path) -> str | None:
    skill_md = target / "SKILL.md"
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
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None
    name = fm.get("name")
    return str(name).strip() if isinstance(name, str) else None


def _tty_echoback_required(target: Path) -> str | None:
    """Return ``None`` if the operator confirmed the target; else an error message.

    Only activates when stdin is a TTY. Automation (pipes, CI, ``yes | ...``)
    goes through the non-TTY branch and skips this prompt.
    """
    if not sys.stdin.isatty():
        return None
    print(
        f"About to overwrite: {target}\n"
        "Re-type the ABSOLUTE target path above to confirm:",
        file=sys.stderr,
    )
    response = sys.stdin.readline().strip()
    if response != str(target):
        return f"target path mismatch (expected {target!s}); aborted"
    return None


def install_to_platform(
    skill_path: Path,
    platform: Platform,
    method: str = "symlink",
    dry_run: bool = True,
    *,
    force: bool = False,
    project_root: Path | None = None,
) -> InstallResult:
    skill_path = Path(skill_path).resolve()
    skill_name = skill_path.name

    try:
        target = _resolve_target_dir(platform, skill_name, project_root=project_root)
    except SafetyError as e:
        return InstallResult(
            platform=platform.name,
            success=False,
            installed_path=None,
            method=method,
            error=str(e),
        )

    if dry_run:
        action = "symlink" if method == "symlink" else "copy"
        return InstallResult(
            platform=platform.name,
            success=True,
            installed_path=target,
            method=action,
            error=f"dry-run: would {action} {skill_path} -> {target}",
        )

    # Apply path — safety guards for destructive overwrites.
    if target.exists() and not target.is_symlink() and not force:
        return InstallResult(
            platform=platform.name,
            success=False,
            installed_path=target,
            method=method,
            error=(
                f"target exists at {target}: --force required to overwrite "
                "(the existing target will be renamed to <target>.bak-<UTC-timestamp>, "
                "never rmtree'd)"
            ),
        )

    if force and target.exists() and not target.is_symlink():
        # Under a TTY, demand the operator echo the absolute path back.
        confirm_error = _tty_echoback_required(target)
        if confirm_error is not None:
            return InstallResult(
                platform=platform.name,
                success=False,
                installed_path=target,
                method=method,
                error=confirm_error,
            )

    try:
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.is_symlink():
            # Symlinks carry no user data; unlink is safe.
            target.unlink()
        elif target.exists():
            if target.is_dir():
                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                backup = target.parent / f"{target.name}.bak-{ts}"
                # If a backup with this timestamp already exists (sub-second
                # retry) pick a suffixed name so we never clobber a prior backup.
                suffix = 1
                while backup.exists():
                    backup = target.parent / f"{target.name}.bak-{ts}-{suffix}"
                    suffix += 1
                target.rename(backup)
            else:
                # Non-directory file at target (unusual). Back it up too.
                ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                target.rename(target.parent / f"{target.name}.bak-{ts}")

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


def verify_installation(
    platform: Platform,
    skill_name: str,
    project_root: Path | None = None,
) -> bool:
    """Return True if the installed target has a SKILL.md whose frontmatter
    ``name`` matches the target directory name.

    Pre-P1-2 this only checked that ``SKILL.md`` existed — which passed even
    when the target held a different, unrelated skill. Frontmatter-name match
    is the minimum signal that the skill actually landed in the intended slot.
    """
    try:
        target = _resolve_target_dir(platform, skill_name, project_root=project_root)
    except SafetyError:
        return False
    name = _read_target_frontmatter_name(target)
    if name is None:
        return False
    return name == target.name


def uninstall_from_platform(
    platform: Platform,
    skill_name: str,
    project_root: Path | None = None,
) -> bool:
    try:
        target = _resolve_target_dir(platform, skill_name, project_root=project_root)
    except SafetyError:
        return False

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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Required with --no-dry-run to overwrite an existing non-symlink target. "
             "The previous target is renamed to <target>.bak-<UTC-timestamp>.",
    )
    parser.add_argument(
        "--project-root",
        dest="project_root",
        type=Path,
        default=None,
        help="Required when any selected platform has a relative skill_dir "
             "(cursor, copilot). Absolute-path platforms (claude/codex/gemini) "
             "ignore this flag.",
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
    project_root: Path | None = args.project_root.resolve() if args.project_root else None

    if args.uninstall:
        results = []
        for p in selected:
            ok = uninstall_from_platform(p, skill_name, project_root=project_root)
            results.append({"platform": p.name, "uninstalled": ok})
        if args.json_output:
            print(json.dumps(results if args.flat else _envelope(skill_path, results), indent=2))
        else:
            for r in results:
                status = "removed" if r["uninstalled"] else "not found"
                print(f"[{status}] {r['platform']}")
        return 0

    install_results: list[InstallResult] = []
    for p in selected:
        result = install_to_platform(
            skill_path,
            p,
            method=args.method,
            dry_run=args.dry_run,
            force=args.force,
            project_root=project_root,
        )
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

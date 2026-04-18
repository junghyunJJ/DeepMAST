"""Tests for scripts.install_multiplatform."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from scripts.install_multiplatform import (
    SafetyError,
    detect_platforms,
    install_to_platform,
    main,
    uninstall_from_platform,
    verify_installation,
)
from scripts.models import Platform


def _make_skill(tmp_path: Path, name: str = "my-skill") -> Path:
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test skill\n---\n\n# Test\n"
    )
    return skill_dir


def _make_platform(tmp_path: Path, name: str = "claude") -> Platform:
    return Platform(
        name=name,
        skill_dir=tmp_path / f".{name}" / "skills",
        config_marker=tmp_path / f".{name}",
        activation_method="automatic",
    )


class TestDetectPlatforms:
    def test_detects_existing_marker(self, tmp_path, monkeypatch):
        (tmp_path / ".claude").mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        platforms = detect_platforms()
        names = [p.name for p in platforms]
        assert "claude" in names

    def test_no_markers(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)
        platforms = detect_platforms()
        for p in platforms:
            marker = p.config_marker
            if not marker.is_absolute():
                marker = Path.cwd() / marker
            assert marker.exists()


class TestInstallToPlatform:
    def test_dry_run_returns_success(self, tmp_path):
        skill = _make_skill(tmp_path)
        platform = _make_platform(tmp_path)
        result = install_to_platform(skill, platform, method="symlink", dry_run=True)
        assert result.success
        assert "dry-run" in (result.error or "")
        assert result.installed_path is not None

    def test_symlink_install(self, tmp_path):
        skill = _make_skill(tmp_path)
        platform = _make_platform(tmp_path)
        platform.skill_dir.mkdir(parents=True, exist_ok=True)
        result = install_to_platform(skill, platform, method="symlink", dry_run=False)
        assert result.success
        assert result.installed_path.is_symlink()
        assert (result.installed_path / "SKILL.md").exists()

    def test_copy_install(self, tmp_path):
        skill = _make_skill(tmp_path)
        platform = _make_platform(tmp_path)
        result = install_to_platform(skill, platform, method="copy", dry_run=False)
        assert result.success
        assert result.installed_path.is_dir()
        assert not result.installed_path.is_symlink()
        assert (result.installed_path / "SKILL.md").exists()

    def test_overwrite_existing_symlink(self, tmp_path):
        skill = _make_skill(tmp_path)
        platform = _make_platform(tmp_path)
        install_to_platform(skill, platform, method="symlink", dry_run=False)
        result = install_to_platform(skill, platform, method="symlink", dry_run=False)
        assert result.success

    def test_overwrite_existing_copy_requires_force(self, tmp_path):
        """P1-2: overwriting a real directory target now requires force=True."""
        skill = _make_skill(tmp_path)
        platform = _make_platform(tmp_path)
        install_to_platform(skill, platform, method="copy", dry_run=False)
        # Second install WITHOUT force should refuse.
        result = install_to_platform(skill, platform, method="copy", dry_run=False)
        assert not result.success
        assert result.error is not None and "--force" in result.error

    def test_overwrite_existing_copy_with_force(self, tmp_path):
        """P1-2: force=True renames the existing target to a timestamped backup."""
        skill = _make_skill(tmp_path)
        platform = _make_platform(tmp_path)
        install_to_platform(skill, platform, method="copy", dry_run=False)
        result = install_to_platform(
            skill, platform, method="copy", dry_run=False, force=True
        )
        assert result.success
        # A `.bak-<ts>` sibling should exist.
        backups = list(platform.skill_dir.glob("my-skill.bak-*"))
        assert len(backups) == 1


class TestVerifyInstallation:
    def test_verified_after_install(self, tmp_path):
        skill = _make_skill(tmp_path)
        platform = _make_platform(tmp_path)
        install_to_platform(skill, platform, method="symlink", dry_run=False)
        assert verify_installation(platform, "my-skill")

    def test_not_verified_before_install(self, tmp_path):
        platform = _make_platform(tmp_path)
        assert not verify_installation(platform, "my-skill")


class TestUninstallFromPlatform:
    def test_uninstall_symlink(self, tmp_path):
        skill = _make_skill(tmp_path)
        platform = _make_platform(tmp_path)
        install_to_platform(skill, platform, method="symlink", dry_run=False)
        assert uninstall_from_platform(platform, "my-skill")
        assert not verify_installation(platform, "my-skill")

    def test_uninstall_copy(self, tmp_path):
        skill = _make_skill(tmp_path)
        platform = _make_platform(tmp_path)
        install_to_platform(skill, platform, method="copy", dry_run=False)
        assert uninstall_from_platform(platform, "my-skill")
        assert not verify_installation(platform, "my-skill")

    def test_uninstall_nonexistent_returns_false(self, tmp_path):
        platform = _make_platform(tmp_path)
        assert not uninstall_from_platform(platform, "no-skill")


class TestCLI:
    def test_dry_run_default(self, tmp_path, capsys):
        skill = _make_skill(tmp_path)
        rc = main([str(skill), "--target", "claude"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_json_output(self, tmp_path, capsys):
        skill = _make_skill(tmp_path)
        rc = main([str(skill), "--target", "claude", "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "tool_version" in data
        assert "results" in data

    def test_json_flat_output(self, tmp_path, capsys):
        skill = _make_skill(tmp_path)
        rc = main([str(skill), "--target", "claude", "--json", "--flat"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)

    def test_unknown_target_error(self, tmp_path):
        skill = _make_skill(tmp_path)
        rc = main([str(skill), "--target", "unknown"])
        assert rc == 1

    def test_nonexistent_path_error(self, tmp_path):
        rc = main([str(tmp_path / "nope")])
        assert rc == 1

    def test_uninstall_cli(self, tmp_path, capsys):
        skill = _make_skill(tmp_path)
        rc = main([str(skill), "--target", "claude", "--uninstall"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "not found" in out

    def test_uninstall_json_cli(self, tmp_path, capsys):
        skill = _make_skill(tmp_path)
        rc = main([str(skill), "--target", "claude", "--uninstall", "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "results" in data


# ---------------------------------------------------------------------------
# P1-2: safety + backup + relative-path + frontmatter-verify tests
# ---------------------------------------------------------------------------


def _relative_platform(name: str = "cursor") -> Platform:
    """A Platform whose skill_dir is a relative path (like real cursor/copilot)."""
    return Platform(
        name=name,
        skill_dir=Path(f".{name}") / "skills",
        config_marker=Path(f".{name}"),
        activation_method="project-open",
    )


class TestP1_2SafetyAndBackup:
    def test_destructive_requires_force(self, tmp_path):
        """--no-dry-run alone must not overwrite an existing non-symlink target."""
        skill = _make_skill(tmp_path)
        platform = _make_platform(tmp_path)
        # Pre-populate target so it exists.
        install_to_platform(skill, platform, method="copy", dry_run=False)
        # Attempt a second apply WITHOUT force.
        result = install_to_platform(skill, platform, method="copy", dry_run=False)
        assert not result.success
        assert result.error is not None
        assert "--force" in result.error
        # Original target must still be present and untouched.
        assert (platform.skill_dir / "my-skill" / "SKILL.md").exists()

    def test_force_creates_timestamped_backup(self, tmp_path):
        """With --force, the previous target is renamed to <target>.bak-<ts>."""
        skill = _make_skill(tmp_path)
        platform = _make_platform(tmp_path)
        platform.skill_dir.mkdir(parents=True, exist_ok=True)
        target = platform.skill_dir / "my-skill"
        target.mkdir()
        canary = target / "canary.txt"
        canary.write_text("baseline-canary-payload")
        # Apply with force.
        result = install_to_platform(
            skill, platform, method="copy", dry_run=False, force=True
        )
        assert result.success
        # A timestamped backup sibling must exist with the canary.
        backups = sorted(platform.skill_dir.glob("my-skill.bak-*"))
        assert len(backups) == 1
        assert (backups[0] / "canary.txt").read_text() == "baseline-canary-payload"
        # The new target has the skill's SKILL.md.
        assert (target / "SKILL.md").exists()


class TestP1_2ProjectRoot:
    def test_relative_platform_path_requires_project_root(self, tmp_path):
        """Cursor/Copilot's relative skill_dir must refuse without --project-root."""
        skill = _make_skill(tmp_path)
        platform = _relative_platform("cursor")
        result = install_to_platform(
            skill, platform, method="copy", dry_run=False
        )
        assert not result.success
        assert result.error is not None
        assert "--project-root" in result.error
        assert "cursor" in result.error

    def test_project_root_explicit_resolves_correctly(self, tmp_path):
        """Explicit --project-root resolves relative platform paths to that root."""
        skill = _make_skill(tmp_path)
        project_root = tmp_path / "proj"
        project_root.mkdir()
        platform = _relative_platform("cursor")
        result = install_to_platform(
            skill, platform, method="copy", dry_run=False, project_root=project_root
        )
        assert result.success
        expected = project_root / ".cursor" / "skills" / "my-skill"
        assert result.installed_path == expected.resolve()
        assert (expected / "SKILL.md").exists()

    def test_absolute_platform_path_defaults_project_root_to_skill_parent(self, tmp_path):
        """Absolute platform paths (claude/codex/gemini) work without --project-root."""
        skill = _make_skill(tmp_path)
        # _make_platform already uses tmp_path (absolute).
        platform = _make_platform(tmp_path)
        platform.skill_dir.mkdir(parents=True, exist_ok=True)
        result = install_to_platform(
            skill, platform, method="copy", dry_run=False, project_root=None
        )
        assert result.success
        assert (platform.skill_dir / "my-skill" / "SKILL.md").exists()


class TestP1_2VerifyInstallation:
    def test_verify_installation_parses_frontmatter(self, tmp_path):
        """verify_installation returns False when frontmatter name != target dir name."""
        platform = _make_platform(tmp_path)
        platform.skill_dir.mkdir(parents=True, exist_ok=True)
        target = platform.skill_dir / "my-skill"
        target.mkdir()
        # Frontmatter says a DIFFERENT name than the dirname.
        (target / "SKILL.md").write_text(
            "---\nname: other-skill\ndescription: Mismatch.\n---\n\n# test\n"
        )
        assert verify_installation(platform, "my-skill") is False

    def test_verify_installation_ok_when_name_matches(self, tmp_path):
        """verify_installation returns True when frontmatter name == target dir name."""
        platform = _make_platform(tmp_path)
        platform.skill_dir.mkdir(parents=True, exist_ok=True)
        target = platform.skill_dir / "my-skill"
        target.mkdir()
        (target / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Match.\n---\n\n# test\n"
        )
        assert verify_installation(platform, "my-skill") is True


class _TTYStringIO(io.StringIO):
    """StringIO that reports itself as a TTY for monkeypatch scenarios."""

    def isatty(self) -> bool:  # noqa: D401 - match io.IOBase signature
        return True


class TestP1_2TTYEchoback:
    def test_force_tty_requires_stdin_echoback(self, tmp_path, monkeypatch, capsys):
        """Under a TTY, --force + --no-dry-run requires stdin echo-back of target path.

        Non-TTY invocations (CI, `yes |`) are unaffected — the tests above
        exercise that path without any monkeypatching.
        """
        skill = _make_skill(tmp_path)
        platform = _make_platform(tmp_path)
        platform.skill_dir.mkdir(parents=True, exist_ok=True)
        target = platform.skill_dir / "my-skill"
        target.mkdir()
        (target / "preexisting.txt").write_text("x")

        # Wrong echo-back -> abort. Replace stdin with a TTY-reporting StringIO
        # so `sys.stdin.isatty()` and `sys.stdin.readline()` both come from the
        # same patched object.
        monkeypatch.setattr(sys, "stdin", _TTYStringIO("/wrong/path\n"))
        result = install_to_platform(
            skill, platform, method="copy", dry_run=False, force=True
        )
        assert not result.success
        assert result.error is not None
        assert "mismatch" in result.error.lower() or "aborted" in result.error.lower()
        # Pre-existing target untouched.
        assert (target / "preexisting.txt").exists()

        # Correct echo-back -> apply proceeds.
        monkeypatch.setattr(sys, "stdin", _TTYStringIO(f"{target}\n"))
        result = install_to_platform(
            skill, platform, method="copy", dry_run=False, force=True
        )
        assert result.success
        assert (target / "SKILL.md").exists()

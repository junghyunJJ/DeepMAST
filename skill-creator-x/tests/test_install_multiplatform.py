"""Tests for scripts.install_multiplatform."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.install_multiplatform import (
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

    def test_overwrite_existing_copy(self, tmp_path):
        skill = _make_skill(tmp_path)
        platform = _make_platform(tmp_path)
        install_to_platform(skill, platform, method="copy", dry_run=False)
        result = install_to_platform(skill, platform, method="copy", dry_run=False)
        assert result.success


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

"""Tests for scripts.check_cross_platform."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_cross_platform import (
    check_all_platforms,
    check_compatibility,
    detect_installed_platforms,
    get_known_platforms,
    main,
)
from scripts.models import Platform


def _make_skill(tmp_path: Path, name: str = "my-skill") -> Path:
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Test skill\n---\n\n# Test\n"
    )
    return skill_dir


class TestGetKnownPlatforms:
    def test_returns_five_platforms(self):
        platforms = get_known_platforms()
        assert len(platforms) == 5
        names = {p.name for p in platforms}
        assert names == {"claude", "codex", "cursor", "gemini", "copilot"}

    def test_all_are_platform_instances(self):
        for p in get_known_platforms():
            assert isinstance(p, Platform)
            assert p.skill_dir is not None
            assert p.config_marker is not None


class TestDetectInstalledPlatforms:
    def test_detects_claude_if_marker_exists(self, tmp_path, monkeypatch):
        marker = tmp_path / ".claude"
        marker.mkdir()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        installed = detect_installed_platforms()
        names = [p.name for p in installed]
        assert "claude" in names

    def test_no_markers_returns_empty_or_subset(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.chdir(tmp_path)
        installed = detect_installed_platforms()
        for p in installed:
            assert p.config_marker.exists() or (Path.cwd() / p.config_marker).exists()


class TestCheckCompatibility:
    def test_missing_skill_md(self, tmp_path):
        skill_dir = tmp_path / "no-skill"
        skill_dir.mkdir()
        platform = get_known_platforms()[0]
        result = check_compatibility(skill_dir, platform)
        assert not result.compatible
        assert any("SKILL.md not found" in i for i in result.issues)

    def test_compatible_matching_name(self, tmp_path):
        skill_dir = _make_skill(tmp_path, "my-skill")
        platform = get_known_platforms()[0]
        result = check_compatibility(skill_dir, platform)
        assert result.compatible
        assert len(result.issues) == 0

    def test_name_mismatch_cursor_is_issue(self, tmp_path):
        skill_dir = _make_skill(tmp_path, "wrong-folder")
        (skill_dir / "SKILL.md").write_text(
            "---\nname: correct-name\ndescription: Test\n---\n\n# Test\n"
        )
        cursor = [p for p in get_known_platforms() if p.name == "cursor"][0]
        result = check_compatibility(skill_dir, cursor)
        assert not result.compatible
        assert any("cursor" in i.lower() for i in result.issues)

    def test_name_mismatch_claude_is_suggestion(self, tmp_path):
        skill_dir = _make_skill(tmp_path, "wrong-folder")
        (skill_dir / "SKILL.md").write_text(
            "---\nname: correct-name\ndescription: Test\n---\n\n# Test\n"
        )
        claude = [p for p in get_known_platforms() if p.name == "claude"][0]
        result = check_compatibility(skill_dir, claude)
        assert result.compatible
        assert any("renaming" in s for s in result.suggestions)

    def test_copilot_name_mismatch_is_issue(self, tmp_path):
        skill_dir = _make_skill(tmp_path, "bad-folder")
        (skill_dir / "SKILL.md").write_text(
            "---\nname: good-name\ndescription: Test\n---\n\n# Test\n"
        )
        copilot = [p for p in get_known_platforms() if p.name == "copilot"][0]
        result = check_compatibility(skill_dir, copilot)
        assert not result.compatible

    def test_codex_scripts_suggestion(self, tmp_path):
        skill_dir = _make_skill(tmp_path, "my-skill")
        scripts = skill_dir / "scripts"
        scripts.mkdir()
        (scripts / "run.py").write_text("print('hello')")
        codex = [p for p in get_known_platforms() if p.name == "codex"][0]
        result = check_compatibility(skill_dir, codex)
        assert result.compatible
        assert any("Python path" in s for s in result.suggestions)


class TestCheckAllPlatforms:
    def test_returns_results_for_all_platforms(self, tmp_path):
        skill_dir = _make_skill(tmp_path, "my-skill")
        results = check_all_platforms(skill_dir)
        assert len(results) == 5

    def test_filter_specific_platforms(self, tmp_path):
        skill_dir = _make_skill(tmp_path, "my-skill")
        platforms = [p for p in get_known_platforms() if p.name in ("claude", "codex")]
        results = check_all_platforms(skill_dir, platforms)
        assert len(results) == 2


class TestCLI:
    def test_text_output(self, tmp_path, capsys):
        skill_dir = _make_skill(tmp_path, "my-skill")
        rc = main([str(skill_dir)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "claude" in out

    def test_json_output(self, tmp_path, capsys):
        skill_dir = _make_skill(tmp_path, "my-skill")
        rc = main([str(skill_dir), "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "tool_version" in data
        assert "results" in data
        assert len(data["results"]) == 5

    def test_json_flat_output(self, tmp_path, capsys):
        skill_dir = _make_skill(tmp_path, "my-skill")
        rc = main([str(skill_dir), "--json", "--flat"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)
        assert len(data) == 5

    def test_filter_platforms_flag(self, tmp_path, capsys):
        skill_dir = _make_skill(tmp_path, "my-skill")
        rc = main([str(skill_dir), "--json", "--flat", "--platforms", "claude,codex"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 2

    def test_unknown_platform_error(self, tmp_path, capsys):
        skill_dir = _make_skill(tmp_path, "my-skill")
        rc = main([str(skill_dir), "--platforms", "unknown"])
        assert rc == 1

    def test_nonexistent_dir_error(self, tmp_path, capsys):
        rc = main([str(tmp_path / "nope")])
        assert rc == 1

    def test_text_output_returns_1_on_issues(self, tmp_path, capsys):
        skill_dir = _make_skill(tmp_path, "bad-folder")
        (skill_dir / "SKILL.md").write_text(
            "---\nname: good-name\ndescription: Test\n---\n\n# Test\n"
        )
        rc = main([str(skill_dir)])
        assert rc == 1

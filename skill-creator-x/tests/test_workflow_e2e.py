"""End-to-end workflow tests using the demo api-rate-limiter skill."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.autofix import autofix
from scripts.check_cross_platform import check_all_platforms, get_known_platforms
from scripts.install_multiplatform import install_to_platform
from scripts.models import Severity
from scripts.package_skill_strict import package_skill_strict
from scripts.validate_strict import validate_all

FIXTURES = Path(__file__).parent / "fixtures"
DEMO_SKILL = FIXTURES / "demo-skill-api-rate-limiter"
INVALID_RESERVED = FIXTURES / "invalid-reserved-name"
INVALID_XML = FIXTURES / "invalid-xml-brackets"


class TestE2ECreateSkill:
    """Verify the demo skill passes full validation pipeline."""

    def test_demo_skill_exists(self):
        assert (DEMO_SKILL / "SKILL.md").exists()
        assert (DEMO_SKILL / "scripts" / "check_rate_limit.py").exists()
        assert (DEMO_SKILL / "references" / "retry-strategies.md").exists()

    def test_validate_strict_zero_errors(self):
        report = validate_all(DEMO_SKILL)
        errors = [r for r in report.results if not r.passed and r.severity is Severity.ERROR]
        assert len(errors) == 0, f"Unexpected errors: {errors}"
        assert report.summary["passed"]

    def test_validate_strict_json_structure(self):
        report = validate_all(DEMO_SKILL)
        d = report.to_dict()
        assert "tool_version" in d
        assert "results" in d
        assert "summary" in d
        assert isinstance(d["results"], list)


class TestE2EStep4ToStep5Cycle:
    """Invalid skill -> fix -> re-validate cycle."""

    def test_invalid_reserved_name_has_error(self):
        report = validate_all(INVALID_RESERVED)
        errors = [r for r in report.results if not r.passed and r.severity is Severity.ERROR]
        assert len(errors) > 0
        assert any("reserved" in r.rule_name or "FM-009" in r.rule_id for r in errors)

    def test_fixed_skill_passes(self, tmp_path):
        fixed = tmp_path / "fixed-skill"
        fixed.mkdir()
        src_md = INVALID_RESERVED / "SKILL.md"
        text = src_md.read_text()
        text = text.replace("claude-helper", "my-helper")
        (fixed / "SKILL.md").write_text(text)
        report = validate_all(fixed)
        errors = [r for r in report.results if not r.passed and r.severity is Severity.ERROR]
        assert len(errors) == 0

    def test_autofix_xml_then_revalidate(self, tmp_path):
        """Autofix removes XML brackets from description, re-validate passes FM-014."""
        import shutil

        fix_dir = tmp_path / "fix-xml"
        shutil.copytree(INVALID_XML, fix_dir)
        report_before = validate_all(fix_dir)
        fm014 = [r for r in report_before.results if r.rule_id == "FM-014"]
        assert len(fm014) == 1
        assert not fm014[0].passed

        fix_report = autofix(fix_dir, rules=["FM-014"], dry_run=False, yes=True)
        assert fix_report.summary["applied"] >= 1

        report_after = validate_all(fix_dir)
        fm014_after = [r for r in report_after.results if r.rule_id == "FM-014"]
        assert len(fm014_after) == 1
        assert fm014_after[0].passed


class TestE2EStep7ToStep8Flow:
    """Cross-platform check -> install dry-run -> package."""

    def test_cross_platform_compatible(self):
        results = check_all_platforms(DEMO_SKILL)
        claude = [r for r in results if r.platform.name == "claude"][0]
        assert claude.compatible

    def test_install_dry_run_succeeds(self):
        platforms = get_known_platforms()
        claude = [p for p in platforms if p.name == "claude"][0]
        result = install_to_platform(DEMO_SKILL, claude, method="symlink", dry_run=True)
        assert result.success
        assert "dry-run" in (result.error or "")

    def test_package_strict_succeeds(self, tmp_path):
        out = package_skill_strict(DEMO_SKILL, tmp_path, strict=False)
        assert out is not None
        assert out.suffix == ".skill"
        assert out.exists()


class TestE2EPackageStrictBlocks:
    """Package should be blocked when validate_strict has ERRORs."""

    def test_package_blocked_on_reserved_name(self, tmp_path):
        out = package_skill_strict(INVALID_RESERVED, tmp_path, strict=True)
        assert out is None

    def test_package_blocked_on_xml_brackets(self, tmp_path, capsys):
        out = package_skill_strict(INVALID_XML, tmp_path, strict=True)
        assert out is None
        captured = capsys.readouterr().out
        assert "FM-014" in captured

"""Unit tests for scripts/audit_all.py (T7.1)."""

from __future__ import annotations

import json
import textwrap
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

from scripts.audit_all import (
    audit_skills,
    discover_skills,
    main,
    sort_results_by_severity,
)
from scripts.models import Severity, ValidationReport, ValidationResult
from scripts.validate_strict import validate_all
from tests.conftest import VALID_MINIMAL_BODY, make_skill


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skills_dir(tmp_path: Path, count: int = 3) -> Path:
    """Create a parent dir with N valid skill subdirectories."""
    parent = tmp_path / "all-skills"
    parent.mkdir()
    for i in range(count):
        make_skill(
            parent,
            folder=f"skill-{i}",
            name=f"skill-{i}",
        )
    return parent


def _make_mixed_skills_dir(tmp_path: Path) -> Path:
    """Create parent dir with 2 valid and 1 invalid skill."""
    parent = tmp_path / "mixed-skills"
    parent.mkdir()
    make_skill(parent, folder="good-skill", name="good-skill")
    make_skill(parent, folder="another-good", name="another-good")
    make_skill(
        parent,
        folder="bad-skill",
        name="bad-skill",
        description="<xml>forbidden brackets</xml>",
    )
    return parent


# ---------------------------------------------------------------------------
# discover_skills
# ---------------------------------------------------------------------------


class TestDiscoverSkills:
    def test_discovers_skill_folders(self, tmp_path):
        parent = _make_skills_dir(tmp_path)
        found = discover_skills(parent)
        assert len(found) == 3
        assert all((d / "SKILL.md").exists() for d in found)

    def test_skips_non_skill_directories(self, tmp_path):
        parent = _make_skills_dir(tmp_path, count=1)
        (parent / "not-a-skill").mkdir()
        (parent / "not-a-skill" / "README.md").write_text("hello")
        found = discover_skills(parent)
        assert len(found) == 1

    def test_returns_sorted(self, tmp_path):
        parent = tmp_path / "sorted-test"
        parent.mkdir()
        for name in ["zebra-skill", "alpha-skill", "mid-skill"]:
            make_skill(parent, folder=name, name=name)
        found = discover_skills(parent)
        names = [d.name for d in found]
        assert names == sorted(names)

    def test_empty_dir(self, tmp_path):
        parent = tmp_path / "empty"
        parent.mkdir()
        assert discover_skills(parent) == []

    def test_nonexistent_dir(self, tmp_path):
        assert discover_skills(tmp_path / "nope") == []


# ---------------------------------------------------------------------------
# sort_results_by_severity
# ---------------------------------------------------------------------------


class TestSortResultsBySeverity:
    def test_failed_errors_first(self):
        report = validate_all(Path("/nonexistent-for-sort"))
        report.results = [
            ValidationResult("W-1", "warn", Severity.WARNING, "", False, "w", ""),
            ValidationResult("E-1", "err", Severity.ERROR, "", False, "e", ""),
            ValidationResult("S-1", "soft", Severity.SOFT_ERROR, "", False, "s", ""),
            ValidationResult("P-1", "pass", Severity.ERROR, "", True, "p", ""),
        ]
        sorted_report = sort_results_by_severity(report)
        ids = [r.rule_id for r in sorted_report.results]
        assert ids == ["E-1", "S-1", "W-1", "P-1"]


# ---------------------------------------------------------------------------
# audit_skills (batch validation)
# ---------------------------------------------------------------------------


class TestAuditSkills:
    def test_batch_three_valid(self, tmp_path):
        parent = _make_skills_dir(tmp_path)
        envelope = audit_skills(parent)
        assert envelope["summary"]["total"] == 3
        assert envelope["summary"]["passed"] == 3
        assert envelope["summary"]["failed"] == 0

    def test_batch_mixed_pass_fail(self, tmp_path):
        parent = _make_mixed_skills_dir(tmp_path)
        envelope = audit_skills(parent)
        assert envelope["summary"]["total"] == 3
        assert envelope["summary"]["passed"] == 2
        assert envelope["summary"]["failed"] == 1

    def test_envelope_structure(self, tmp_path):
        parent = _make_skills_dir(tmp_path, count=1)
        envelope = audit_skills(parent)
        assert "audit_version" in envelope
        assert "pdf_version" in envelope
        assert "timestamp" in envelope
        assert "skills_dir" in envelope
        assert "skills" in envelope
        assert "summary" in envelope
        skill_entry = envelope["skills"][0]
        assert "skill_name" in skill_entry
        assert "report" in skill_entry
        report = skill_entry["report"]
        assert "tool_version" in report
        assert "results" in report
        assert "summary" in report

    def test_strict_mode(self, tmp_path):
        parent = tmp_path / "strict-test"
        parent.mkdir()
        make_skill(
            parent,
            folder="soft-fail",
            name="soft-fail",
            description="short",
        )
        env_normal = audit_skills(parent, strict=False)
        env_strict = audit_skills(parent, strict=True)
        normal_report = env_normal["skills"][0]["report"]
        strict_report = env_strict["skills"][0]["report"]
        assert strict_report["summary"]["strict"] is True
        assert normal_report["summary"]["strict"] is False

    def test_empty_dir_zero_skills(self, tmp_path):
        parent = tmp_path / "empty"
        parent.mkdir()
        envelope = audit_skills(parent)
        assert envelope["summary"]["total"] == 0
        assert envelope["summary"]["passed"] == 0
        assert envelope["summary"]["failed"] == 0

    def test_severity_sorted_in_results(self, tmp_path):
        parent = _make_mixed_skills_dir(tmp_path)
        envelope = audit_skills(parent)
        for entry in envelope["skills"]:
            results = entry["report"]["results"]
            failed = [r for r in results if not r["passed"]]
            if not failed:
                continue
            sev_order = {"ERROR": 0, "SOFT-ERROR": 1, "WARNING": 2}
            sev_values = [sev_order.get(r["severity"], 99) for r in failed]
            assert sev_values == sorted(sev_values)


# ---------------------------------------------------------------------------
# CLI (main)
# ---------------------------------------------------------------------------


class TestCLI:
    def test_json_output(self, tmp_path):
        parent = _make_skills_dir(tmp_path, count=2)
        buf = StringIO()
        with redirect_stdout(buf):
            rc = main([str(parent), "--json"])
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert "audit_version" in data
        assert "skills" in data
        assert "summary" in data
        assert data["summary"]["total"] == 2

    def test_json_flat(self, tmp_path):
        parent = _make_skills_dir(tmp_path, count=2)
        buf = StringIO()
        with redirect_stdout(buf):
            rc = main([str(parent), "--json", "--flat"])
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert isinstance(data, list)
        assert len(data) == 2

    def test_text_output(self, tmp_path):
        parent = _make_skills_dir(tmp_path, count=1)
        buf = StringIO()
        with redirect_stdout(buf):
            rc = main([str(parent)])
        assert rc == 0
        text = buf.getvalue()
        assert "skill-0" in text
        assert "PASS" in text
        assert "Total:" in text

    def test_text_shows_failures(self, tmp_path):
        parent = _make_mixed_skills_dir(tmp_path)
        buf = StringIO()
        with redirect_stdout(buf):
            rc = main([str(parent)])
        assert rc == 1
        text = buf.getvalue()
        assert "FAIL" in text
        assert "Failed: 1" in text

    def test_nonexistent_dir_returns_2(self, tmp_path, capsys):
        rc = main([str(tmp_path / "nope")])
        assert rc == 2

    def test_not_a_dir_returns_2(self, tmp_path, capsys):
        f = tmp_path / "file.txt"
        f.write_text("x")
        rc = main([str(f)])
        assert rc == 2

    def test_strict_flag(self, tmp_path):
        parent = tmp_path / "strict-cli"
        parent.mkdir()
        make_skill(
            parent,
            folder="soft-fail",
            name="soft-fail",
            description="short",
        )
        buf = StringIO()
        with redirect_stdout(buf):
            rc = main([str(parent), "--json", "--strict"])
        data = json.loads(buf.getvalue())
        assert data["skills"][0]["report"]["summary"]["strict"] is True


# ---------------------------------------------------------------------------
# Smoke test with real fixtures
# ---------------------------------------------------------------------------


class TestFixturesSmoke:
    def test_all_fixtures(self, fixtures_dir):
        envelope = audit_skills(fixtures_dir)
        assert envelope["summary"]["total"] >= 3
        for entry in envelope["skills"]:
            assert "skill_name" in entry
            assert "report" in entry
            report = entry["report"]
            assert "results" in report
            assert "summary" in report
            assert len(report["results"]) > 0

    def test_valid_fixtures_pass(self, fixtures_dir):
        envelope = audit_skills(fixtures_dir)
        valid_skills = [
            e for e in envelope["skills"]
            if e["skill_name"].startswith("valid-")
        ]
        for entry in valid_skills:
            assert entry["report"]["summary"]["passed"], (
                f"{entry['skill_name']} should pass but didn't"
            )

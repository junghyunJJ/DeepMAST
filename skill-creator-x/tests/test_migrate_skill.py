"""Unit tests for scripts/migrate_skill.py (T8.2)."""

from __future__ import annotations

import json
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.migrate_skill import (
    assess_migration,
    fix_naming,
    insert_missing_sections,
    main,
    migrate_skill,
    restructure_frontmatter,
)
from scripts.validate_strict import validate_all
from tests.conftest import VALID_MINIMAL_BODY, make_skill


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_legacy_no_frontmatter(tmp_path: Path) -> Path:
    sd = tmp_path / "legacy-no-fm"
    sd.mkdir()
    (sd / "SKILL.md").write_text(
        "# Old Skill\n\nNo frontmatter at all.\n\n## Usage\nJust run it.\n",
        encoding="utf-8",
    )
    return sd


def _make_legacy_wrong_naming(tmp_path: Path) -> Path:
    sd = tmp_path / "My_Skill"
    sd.mkdir()
    (sd / "skill.md").write_text(
        "---\nname: My_Skill\ndescription: A legacy skill. Use when testing.\n---\n\n"
        "# My Skill\n\n## Instructions\n1. Do it.\n\n## Examples\nEx 1.\n\n"
        "## Common Issues\n### Err\nFix.\n",
        encoding="utf-8",
    )
    return sd


# ---------------------------------------------------------------------------
# 1. test_assess_legacy_no_frontmatter
# ---------------------------------------------------------------------------


class TestAssessment:
    def test_assess_legacy_no_frontmatter(self, tmp_path):
        sd = _make_legacy_no_frontmatter(tmp_path)
        assessment = assess_migration(sd)
        assert assessment.needs_migration is True
        rule_ids = " ".join(assessment.changes_required)
        assert "FM-005" in rule_ids
        assert assessment.estimated_risk == "high"

    def test_assess_valid_skill(self, tmp_path):
        sd = make_skill(tmp_path, folder="valid-test", name="valid-test")
        assessment = assess_migration(sd)
        assert assessment.needs_migration is False
        assert assessment.estimated_risk == "low"

    def test_assess_many_violations(self, tmp_path):
        sd = make_skill(
            tmp_path, folder="many-issues", name="many-issues",
            description="<bad>",
            extra_frontmatter={"author": "x", "version": "1"},
            body="# Title\nNo steps, no examples, no issues section.\n",
        )
        assessment = assess_migration(sd)
        assert len(assessment.changes_required) >= 3

    def test_assess_missing_skill_md(self, tmp_path):
        sd = tmp_path / "empty-dir"
        sd.mkdir()
        assessment = assess_migration(sd)
        assert assessment.needs_migration is True
        assert assessment.estimated_risk == "high"

    def test_assess_wrong_case_skill_md(self, tmp_path):
        sd = tmp_path / "wrong-case"
        sd.mkdir()
        (sd / "Skill.md").write_text("---\nname: wrong-case\ndescription: test. Use when testing.\n---\n\n# T\n")
        assessment = assess_migration(sd)
        assert any("FM-001" in c for c in assessment.changes_required)


# ---------------------------------------------------------------------------
# 3. test_apply_frontmatter_reconstruction
# ---------------------------------------------------------------------------


class TestRestructureFrontmatter:
    def test_adds_delimiters_and_fields(self, tmp_path):
        content = "# Title\n\nSome content.\n"
        sd = tmp_path / "no-fm"
        sd.mkdir()
        result = restructure_frontmatter(content, skill_dir=sd)
        assert result.startswith("---\n")
        assert "name:" in result
        assert "description:" in result

    def test_preserves_existing_frontmatter(self, tmp_path):
        content = "---\nname: existing\ndescription: Already there. Use when testing.\n---\n\n# Body\n"
        result = restructure_frontmatter(content)
        assert "existing" in result

    def test_unknown_key_to_metadata(self):
        content = "---\nname: test\ndescription: Test. Use when testing.\nauthor: me\n---\n\n# Body\n"
        result = restructure_frontmatter(content)
        assert "metadata:" in result
        assert "author:" not in result.split("metadata:")[0]


# ---------------------------------------------------------------------------
# 5. test_apply_section_insertion
# ---------------------------------------------------------------------------


class TestInsertMissingSections:
    def test_appends_both_sections(self):
        content = "---\nname: t\ndescription: T. Use when testing.\n---\n\n# Title\n\n## Instructions\n1. Do.\n"
        result = insert_missing_sections(content)
        assert "## Common Issues" in result
        assert "## Examples" in result

    def test_no_duplicate_if_present(self, tmp_path):
        sd = make_skill(tmp_path, folder="has-both", name="has-both")
        content = (sd / "SKILL.md").read_text()
        result = insert_missing_sections(content)
        assert result.count("## Common Issues") == 1
        assert result.count("## Examples") == 1


# ---------------------------------------------------------------------------
# 6. test_apply_naming_correction
# ---------------------------------------------------------------------------


class TestFixNaming:
    def test_renames_wrong_case(self, tmp_path):
        sd = tmp_path / "rename-test"
        sd.mkdir()
        (sd / "skill.md").write_text("# test\n")
        changes = fix_naming(sd, dry_run=False)
        assert any("SKILL.md" in c for c in changes)
        assert (sd / "SKILL.md").exists()

    def test_reports_folder_rename_as_manual(self, tmp_path):
        """P1-3: fix_naming must emit a MANUAL instruction, not rename the folder.

        The prior behavior renamed the skill directory mid-run; subsequent
        operations (backup, frontmatter write, autofix) then wrote to a stale
        path, silently losing the backup. Option alpha defers the rename to
        the human who owns the git/IDE/CI paths.
        """
        sd = tmp_path / "My_Skill"
        sd.mkdir()
        (sd / "SKILL.md").write_text("# test\n")
        # Call WITH dry_run=False — this used to rename the folder; now it
        # must still emit a MANUAL instruction and leave the directory in place.
        changes = fix_naming(sd, dry_run=False)

        # A MANUAL rename instruction is present and references the kebab name.
        manual_entries = [c for c in changes if c.startswith("MANUAL:")]
        assert manual_entries, f"expected a MANUAL: entry in {changes!r}"
        assert any("My_Skill" in c and "my-skill" in c for c in manual_entries)
        # The message must point the user at the backup location post-rename.
        assert any("backups/" in c for c in manual_entries), (
            "MANUAL instruction must tell the user where the backup lives "
            "after the rename; look for the literal substring 'backups/'"
        )

        # The folder was NOT renamed.
        assert (tmp_path / "My_Skill").exists()
        assert not (tmp_path / "my-skill").exists()

    def test_no_changes_if_correct(self, tmp_path):
        sd = make_skill(tmp_path, folder="good-name", name="good-name")
        changes = fix_naming(sd, dry_run=True)
        assert len(changes) == 0


# ---------------------------------------------------------------------------
# P1-3 end-to-end: migrate_skill must not write to a ghost path
# ---------------------------------------------------------------------------


class TestP1_3PreservesSkillDir:
    def test_apply_preserves_skill_dir(self, tmp_path):
        """After --apply --yes, the original directory is intact and backup is real."""
        sd = tmp_path / "My_Skill"
        sd.mkdir()
        (sd / "skill.md").write_text(
            "---\nname: My_Skill\ndescription: A legacy skill. Use when testing.\n---\n\n"
            "# My Skill\n\n## Instructions\n1. Do it.\n\n"
            "## Examples\nEx 1.\n\n"
            "## Common Issues\n### Err\nFix.\n",
            encoding="utf-8",
        )
        result = migrate_skill(sd, apply=True, yes=True, use_git=False)

        # SKILL.md case-fix (intra-dir) did land.
        assert (sd / "SKILL.md").exists()

        # The backup landed inside the ORIGINAL directory (My_Skill/backups/<ts>/),
        # not at a ghost kebab path.
        assert result.backup_path is not None
        assert result.backup_path.exists(), (
            f"backup_path {result.backup_path} must actually exist — "
            "bug would write it to a ghost 'my-skill/' path"
        )
        # The backup path must be under the original, still-un-renamed skill dir.
        assert str(result.backup_path).startswith(str(sd)), (
            f"backup_path {result.backup_path} must be inside the original "
            f"skill dir {sd}, not a sibling"
        )

        # The MANUAL rename instruction is surfaced to the user.
        assert any(c.startswith("MANUAL:") for c in result.changes_made)

    def test_no_ghost_backup_dir(self, tmp_path):
        """No sibling 'my-skill/' directory should be created anywhere."""
        sd = tmp_path / "My_Skill"
        sd.mkdir()
        (sd / "SKILL.md").write_text(
            "---\nname: My_Skill\ndescription: A legacy skill. Use when testing.\n---\n\n"
            "# My Skill\n\n## Instructions\n1. Do.\n",
            encoding="utf-8",
        )
        migrate_skill(sd, apply=True, yes=True, use_git=False)

        # Walk everything under tmp_path — no 'my-skill' (kebab sibling) must exist.
        ghosts = [p for p in tmp_path.rglob("my-skill") if p.is_dir()]
        # Backup path can include the ORIGINAL skill dir name ("My_Skill"), but
        # never a kebab sibling at the parent level.
        assert not (tmp_path / "my-skill").exists()
        assert not any(p.parent == tmp_path for p in ghosts)


# ---------------------------------------------------------------------------
# 7. test_git_branch_creation
# ---------------------------------------------------------------------------


class TestGitBranch:
    def test_git_branch_creation_mocked(self, tmp_path):
        sd = make_skill(tmp_path, folder="git-test", name="git-test",
                        body="# T\nNo steps.\n")
        with patch("scripts.migrate_skill._detect_git", return_value=True), \
             patch("scripts.migrate_skill._create_migrate_branch", return_value="skill-migrate/git-test") as mock_branch:
            result = migrate_skill(sd, apply=True, yes=True, use_git=True)
            assert result.git_branch == "skill-migrate/git-test"
            mock_branch.assert_called_once()

    def test_no_git_flag(self, tmp_path):
        sd = make_skill(tmp_path, folder="no-git", name="no-git",
                        body="# T\nNo steps.\n")
        result = migrate_skill(sd, apply=True, yes=True, use_git=False)
        assert result.git_branch is None


# ---------------------------------------------------------------------------
# 8. test_diff_output
# ---------------------------------------------------------------------------


class TestDiffOutput:
    def test_diff_is_unified_format(self, tmp_path):
        sd = _make_legacy_no_frontmatter(tmp_path)
        result = migrate_skill(sd)
        assert "---" in result.diff or "+++ " in result.diff or "@@" in result.diff

    def test_diff_non_empty_for_legacy(self, tmp_path):
        sd = _make_legacy_no_frontmatter(tmp_path)
        result = migrate_skill(sd)
        assert len(result.diff) > 0


# ---------------------------------------------------------------------------
# 9. test_before_after_validation_report_comparison
# ---------------------------------------------------------------------------


class TestBeforeAfterComparison:
    def test_after_has_fewer_errors(self, tmp_path):
        sd = _make_legacy_no_frontmatter(tmp_path)
        result = migrate_skill(sd, apply=True, yes=True, use_git=False)
        assert result.applied is True
        assert result.before_report is not None
        assert result.after_report is not None
        before_errors = result.before_report.summary["error_count"]
        after_errors = result.after_report.summary["error_count"]
        assert after_errors < before_errors

    def test_backup_created(self, tmp_path):
        sd = _make_legacy_no_frontmatter(tmp_path)
        result = migrate_skill(sd, apply=True, yes=True, use_git=False)
        assert result.backup_path is not None
        assert result.backup_path.exists()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCLI:
    def test_assess_json(self, tmp_path):
        sd = make_skill(tmp_path, folder="cli-assess", name="cli-assess")
        buf = StringIO()
        with redirect_stdout(buf):
            rc = main([str(sd), "--assess", "--json"])
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert "needs_migration" in data
        assert "changes_required" in data

    def test_assess_text(self, tmp_path):
        sd = _make_legacy_no_frontmatter(tmp_path)
        buf = StringIO()
        with redirect_stdout(buf):
            rc = main([str(sd), "--assess"])
        assert rc == 0
        text = buf.getvalue()
        assert "NEEDS MIGRATION" in text

    def test_apply_json(self, tmp_path):
        sd = _make_legacy_no_frontmatter(tmp_path)
        buf = StringIO()
        with redirect_stdout(buf):
            rc = main([str(sd), "--apply", "--yes", "--no-git", "--json"])
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert data["applied"] is True

    def test_dry_run_default(self, tmp_path):
        sd = _make_legacy_no_frontmatter(tmp_path)
        original = (sd / "SKILL.md").read_text()
        buf = StringIO()
        with redirect_stdout(buf):
            rc = main([str(sd), "--json"])
        assert rc == 0
        assert (sd / "SKILL.md").read_text() == original

    def test_nonexistent_dir_returns_2(self, tmp_path, capsys):
        rc = main([str(tmp_path / "nope"), "--assess"])
        assert rc == 2

    def test_text_output_apply(self, tmp_path):
        sd = _make_legacy_no_frontmatter(tmp_path)
        buf = StringIO()
        with redirect_stdout(buf):
            rc = main([str(sd), "--apply", "--yes", "--no-git"])
        assert rc == 0
        text = buf.getvalue()
        assert "Applied: True" in text

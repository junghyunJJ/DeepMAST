"""Unit tests for scripts/autofix.py (T7.2)."""

from __future__ import annotations

import json
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from scripts.autofix import (
    ALL_SAFE_RULES,
    autofix,
    create_backup,
    fix_bd005_error_handling,
    fix_bd006_examples,
    fix_fm004_readme_move,
    fix_fm007_008_name_kebab,
    fix_fm013_desc_truncate,
    fix_fm014_desc_xml_strip,
    fix_fm015_compat_truncate,
    fix_fm016_unknown_keys,
    main,
    _truncate_at_sentence,
)
from scripts.validate_strict import validate_all
from tests.conftest import VALID_MINIMAL_BODY, make_skill


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_skill(skill_dir: Path) -> str:
    return (skill_dir / "SKILL.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Sentence-boundary truncation (ADR-011 principle 6)
# ---------------------------------------------------------------------------


class TestTruncateAtSentence:
    def test_no_truncation_needed(self):
        assert _truncate_at_sentence("Short text.", 100) == "Short text."

    def test_truncates_at_period(self):
        text = "First sentence. Second sentence. Third sentence is very long."
        result = _truncate_at_sentence(text, 35)
        assert result == "First sentence. Second sentence."
        assert len(result) <= 35

    def test_fallback_when_no_period(self):
        text = "A long text without any period that goes on and on"
        result = _truncate_at_sentence(text, 20)
        assert result.endswith("...")
        assert len(result) <= 23


# ---------------------------------------------------------------------------
# FM-007/008: name kebab-case
# ---------------------------------------------------------------------------


class TestFixFM007008:
    def test_underscores_to_hyphens(self, tmp_path):
        sd = make_skill(tmp_path, folder="bad-name", name="my_skill_name")
        content = _read_skill(sd)
        new_content, diff = fix_fm007_008_name_kebab(content)
        assert "my-skill-name" in new_content
        assert diff != ""

    def test_spaces_and_capitals(self, tmp_path):
        sd = make_skill(tmp_path, folder="bad-name", name="My Skill Name")
        content = _read_skill(sd)
        new_content, diff = fix_fm007_008_name_kebab(content)
        assert "my-skill-name" in new_content

    def test_already_kebab_no_change(self, tmp_path):
        sd = make_skill(tmp_path, folder="good-name", name="good-name")
        content = _read_skill(sd)
        new_content, diff = fix_fm007_008_name_kebab(content)
        assert diff == ""


# ---------------------------------------------------------------------------
# FM-013: description truncation
# ---------------------------------------------------------------------------


class TestFixFM013:
    def test_truncates_long_desc(self, tmp_path):
        long_desc = "First sentence. " * 80
        sd = make_skill(tmp_path, folder="long-desc", name="long-desc", description=long_desc)
        content = _read_skill(sd)
        new_content, diff = fix_fm013_desc_truncate(content)
        assert diff != ""
        import yaml
        split = new_content.split("---")
        fm = yaml.safe_load(split[1])
        assert len(fm["description"]) <= 1024

    def test_short_desc_no_change(self, tmp_path):
        sd = make_skill(tmp_path, folder="short-desc", name="short-desc",
                        description="Short. Use when testing.")
        content = _read_skill(sd)
        _, diff = fix_fm013_desc_truncate(content)
        assert diff == ""

    def test_fixture_needs_autofix_long_desc(self, fixtures_dir):
        content = (fixtures_dir / "needs-autofix-long-desc" / "SKILL.md").read_text()
        new_content, diff = fix_fm013_desc_truncate(content)
        assert diff != ""
        import yaml
        split = new_content.split("---")
        fm = yaml.safe_load(split[1])
        assert len(fm["description"]) <= 1024


# ---------------------------------------------------------------------------
# FM-014: XML brackets in description
# ---------------------------------------------------------------------------


class TestFixFM014:
    def test_strips_xml_tags(self, tmp_path):
        sd = make_skill(tmp_path, folder="xml-desc", name="xml-desc",
                        description="Fix <xml> tags and <b>bold</b> text. Use when testing.")
        content = _read_skill(sd)
        new_content, diff = fix_fm014_desc_xml_strip(content)
        assert "<" not in new_content.split("---")[1].split("---")[0]
        assert diff != ""

    def test_no_xml_no_change(self, tmp_path):
        sd = make_skill(tmp_path, folder="clean-desc", name="clean-desc",
                        description="Clean description without brackets. Use when testing.")
        content = _read_skill(sd)
        _, diff = fix_fm014_desc_xml_strip(content)
        assert diff == ""

    def test_fixture_needs_autofix_xml_brackets(self, fixtures_dir):
        content = (fixtures_dir / "needs-autofix-xml-brackets" / "SKILL.md").read_text()
        new_content, diff = fix_fm014_desc_xml_strip(content)
        assert diff != ""
        assert "<xml>" not in new_content
        assert "<tags>" not in new_content


# ---------------------------------------------------------------------------
# FM-015: compatibility truncation
# ---------------------------------------------------------------------------


class TestFixFM015:
    def test_truncates_long_compat(self, tmp_path):
        long_compat = "Compatible with everything. " * 30
        sd = make_skill(tmp_path, folder="long-compat", name="long-compat", compatibility=long_compat)
        content = _read_skill(sd)
        new_content, diff = fix_fm015_compat_truncate(content)
        assert diff != ""

    def test_short_compat_no_change(self, tmp_path):
        sd = make_skill(tmp_path, folder="short-compat", name="short-compat", compatibility="Claude Code 1.0+")
        content = _read_skill(sd)
        _, diff = fix_fm015_compat_truncate(content)
        assert diff == ""


# ---------------------------------------------------------------------------
# FM-016: unknown keys -> metadata
# ---------------------------------------------------------------------------


class TestFixFM016:
    def test_moves_unknown_keys(self, tmp_path):
        sd = make_skill(tmp_path, folder="unknown-keys", name="unknown-keys",
                        extra_frontmatter={"author": "test", "version": "1.0"})
        content = _read_skill(sd)
        new_content, diff = fix_fm016_unknown_keys(content)
        assert diff != ""
        assert "metadata:" in new_content
        import yaml
        split = new_content.split("---")
        fm = yaml.safe_load(split[1])
        assert "author" not in fm
        assert fm["metadata"]["author"] == "test"

    def test_no_unknown_keys_no_change(self, tmp_path):
        sd = make_skill(tmp_path, folder="clean-keys", name="clean-keys")
        content = _read_skill(sd)
        _, diff = fix_fm016_unknown_keys(content)
        assert diff == ""

    def test_fixture_needs_autofix_unknown_keys(self, fixtures_dir):
        content = (fixtures_dir / "needs-autofix-unknown-keys" / "SKILL.md").read_text()
        new_content, diff = fix_fm016_unknown_keys(content)
        assert diff != ""
        import yaml
        split = new_content.split("---")
        fm = yaml.safe_load(split[1])
        assert "author" not in fm
        assert "version" not in fm
        assert fm["metadata"]["author"] == "someone"


# ---------------------------------------------------------------------------
# FM-004: README.md -> references/
# ---------------------------------------------------------------------------


class TestFixFM004:
    def test_moves_readme(self, tmp_path):
        sd = make_skill(tmp_path, folder="has-readme", name="has-readme", include_readme=True)
        moved, msg = fix_fm004_readme_move(sd)
        assert moved is True
        assert not (sd / "README.md").exists()
        assert (sd / "references" / "README.md").exists()

    def test_no_readme_no_change(self, tmp_path):
        sd = make_skill(tmp_path, folder="no-readme", name="no-readme")
        moved, msg = fix_fm004_readme_move(sd)
        assert moved is False


# ---------------------------------------------------------------------------
# BD-005: error handling section
# ---------------------------------------------------------------------------


class TestFixBD005:
    def test_appends_section(self, tmp_path):
        body = "# Skill\n\n## Instructions\n1. Do things.\n\n## Examples\nExample 1: usage.\n"
        sd = make_skill(tmp_path, folder="no-errors", name="no-errors", body=body)
        content = _read_skill(sd)
        new_content, diff = fix_bd005_error_handling(content)
        assert "## Common Issues" in new_content
        assert diff != ""

    def test_already_has_section(self, tmp_path):
        sd = make_skill(tmp_path, folder="has-errors", name="has-errors")
        content = _read_skill(sd)
        _, diff = fix_bd005_error_handling(content)
        assert diff == ""

    def test_skips_when_in_fenced_block(self, tmp_path):
        body = (
            "# Skill\n\n## Instructions\n1. Do things.\n\n"
            "```markdown\n## Common Issues\nThis is inside a fenced block.\n```\n"
        )
        sd = make_skill(tmp_path, folder="fenced-errors", name="fenced-errors", body=body)
        content = _read_skill(sd)
        new_content, diff = fix_bd005_error_handling(content)
        assert "## Common Issues" in new_content
        assert diff != "", "Should append section because heading is only inside fenced block"


# ---------------------------------------------------------------------------
# BD-006: examples section
# ---------------------------------------------------------------------------


class TestFixBD006:
    def test_appends_section(self, tmp_path):
        body = "# Skill\n\n## Instructions\n1. Do things.\n\n## Common Issues\n### Err\nFix it.\n"
        sd = make_skill(tmp_path, folder="no-examples", name="no-examples", body=body)
        content = _read_skill(sd)
        new_content, diff = fix_bd006_examples(content)
        assert "## Examples" in new_content
        assert diff != ""

    def test_already_has_section(self, tmp_path):
        sd = make_skill(tmp_path, folder="has-examples", name="has-examples")
        content = _read_skill(sd)
        _, diff = fix_bd006_examples(content)
        assert diff == ""

    def test_skips_when_in_fenced_block(self, tmp_path):
        body = (
            "# Skill\n\n## Instructions\n1. Do things.\n\n"
            "## Common Issues\n### Err\nFix it.\n\n"
            "```markdown\n## Examples\nThis is inside a fenced block.\n```\n"
        )
        sd = make_skill(tmp_path, folder="fenced-examples", name="fenced-examples", body=body)
        content = _read_skill(sd)
        new_content, diff = fix_bd006_examples(content)
        assert "## Examples" in new_content
        assert diff != "", "Should append section because heading is only inside fenced block"


# ---------------------------------------------------------------------------
# create_backup
# ---------------------------------------------------------------------------


class TestCreateBackup:
    def test_creates_backup_dir(self, tmp_path):
        sd = make_skill(tmp_path, folder="backup-test", name="backup-test")
        backup_dir = create_backup(sd)
        assert backup_dir.exists()
        assert (backup_dir / "SKILL.md").exists()
        assert backup_dir.parent.name == "backups"


# ---------------------------------------------------------------------------
# autofix orchestrator
# ---------------------------------------------------------------------------


class TestAutofix:
    def test_dry_run_default(self, tmp_path):
        sd = make_skill(tmp_path, folder="dry-run", name="Dry_Run")
        original = _read_skill(sd)
        report = autofix(sd)
        assert _read_skill(sd) == original
        assert report.summary["applied"] == 0

    def test_apply_with_yes(self, tmp_path):
        sd = make_skill(tmp_path, folder="apply-test", name="Apply_Test")
        report = autofix(sd, rules=["FM-007"], dry_run=False, yes=True)
        assert report.summary["applied"] >= 1
        assert report.backup_dir is not None
        new_content = _read_skill(sd)
        assert "apply-test" in new_content

    def test_fix_all_safe(self, tmp_path):
        sd = make_skill(tmp_path, folder="fix-all", name="Fix_All",
                        description="<xml>tagged</xml> description. Use when testing autofix.",
                        extra_frontmatter={"author": "me"})
        report = autofix(sd, fix_all_safe=True, dry_run=False, yes=True)
        assert report.summary["applied"] >= 1

    def test_regression_detection(self, tmp_path):
        sd = make_skill(tmp_path, folder="regression", name="regression")
        report = autofix(sd, dry_run=True)
        regression_fixes = [f for f in report.fixes if f.rule_id == "REGRESSION"]
        assert len(regression_fixes) == 0

    def test_no_skill_md(self, tmp_path):
        sd = tmp_path / "empty-skill"
        sd.mkdir()
        report = autofix(sd)
        assert report.summary["applied"] == 0

    def test_post_fix_revalidation(self, tmp_path):
        sd = make_skill(tmp_path, folder="revalidate", name="Revalidate_Me",
                        description="<b>Bold</b> description text. Use when verifying revalidation.")
        report = autofix(sd, rules=["FM-007", "FM-014"], dry_run=False, yes=True)
        assert report.summary["applied"] >= 1
        after = validate_all(sd)
        for r in after.results:
            if r.rule_id in ("FM-007", "FM-014"):
                assert r.passed, f"{r.rule_id} should pass after fix"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestCLI:
    def test_json_output(self, tmp_path):
        sd = make_skill(tmp_path, folder="cli-json", name="cli-json")
        buf = StringIO()
        with redirect_stdout(buf):
            rc = main([str(sd), "--json"])
        assert rc == 0
        data = json.loads(buf.getvalue())
        assert "skill_path" in data
        assert "fixes" in data
        assert "summary" in data

    def test_text_output(self, tmp_path):
        sd = make_skill(tmp_path, folder="cli-text", name="Cli_Text")
        buf = StringIO()
        with redirect_stdout(buf):
            rc = main([str(sd)])
        assert rc == 0
        text = buf.getvalue()
        assert "Autofix:" in text
        assert "Summary:" in text

    def test_nonexistent_dir_returns_2(self, tmp_path, capsys):
        rc = main([str(tmp_path / "nope")])
        assert rc == 2

    def test_fix_specific_rule(self, tmp_path):
        sd = make_skill(tmp_path, folder="fix-one", name="Fix_One")
        buf = StringIO()
        with redirect_stdout(buf):
            rc = main([str(sd), "--fix", "FM-007", "--yes", "--json"])
        assert rc == 0
        data = json.loads(buf.getvalue())
        applied = [f for f in data["fixes"] if f["applied"]]
        assert len(applied) >= 1

    def test_dry_run_is_default(self, tmp_path):
        sd = make_skill(tmp_path, folder="dry-default", name="Dry_Default")
        original = _read_skill(sd)
        buf = StringIO()
        with redirect_stdout(buf):
            rc = main([str(sd), "--json"])
        assert rc == 0
        assert _read_skill(sd) == original


# ---------------------------------------------------------------------------
# P2-B: FM-008 FixResult preservation + CLI drift fixes
# ---------------------------------------------------------------------------


class TestP2B_FM008FixResult:
    """FM-007 and FM-008 share fix_fm007_008_name_kebab. The old dedupe used
    a ``set[int]`` of ``id(handler)`` values and silently dropped the second
    rule_id from the report. After P2-B the cache is keyed on
    ``handler.__name__`` and every rule_id still gets its own FixResult entry
    sharing the computed diff.
    """

    def test_fm008_reported_when_fm007_handles_it(self, tmp_path):
        from scripts.autofix import autofix

        sd = make_skill(tmp_path, folder="Fm_Bad", name="Fm_Bad")
        # Both FM-007 and FM-008 should be failing for this name.
        report = autofix(
            sd, rules=["FM-007", "FM-008"], dry_run=False, yes=True
        )
        rule_ids_applied = {
            f.rule_id for f in report.fixes if f.applied and f.rule_id != "REGRESSION"
        }
        assert "FM-007" in rule_ids_applied, rule_ids_applied
        assert "FM-008" in rule_ids_applied, (
            "FM-008 must appear as its own FixResult even though it shares a handler "
            f"with FM-007. Got applied rule_ids: {rule_ids_applied}"
        )
        # Both entries should carry the same diff (same handler output).
        fm7 = next(f for f in report.fixes if f.rule_id == "FM-007" and f.applied)
        fm8 = next(f for f in report.fixes if f.rule_id == "FM-008" and f.applied)
        assert fm7.diff == fm8.diff


class TestP2B_CLI:
    def test_cli_no_dry_run_flag_rejected_with_deprecation_notice(self, tmp_path, capsys):
        """OQ-1 resolved: --dry-run is removed; an explicit deprecation
        message is printed on stderr before argparse exits non-zero.
        """
        sd = make_skill(tmp_path, folder="dep-dry", name="dep-dry")
        with pytest.raises(SystemExit) as exc_info:
            main([str(sd), "--dry-run"])
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        # The deprecation notice is visible on stderr (not just argparse's default error).
        assert "--dry-run" in captured.err
        assert "deprecated" in captured.err.lower() or "removed" in captured.err.lower()

    def test_cli_fix_repeatable(self, tmp_path):
        sd = make_skill(
            tmp_path, folder="fix-repeat", name="Fix_Repeat",
            description="<xml>bad</xml>",
        )
        buf = StringIO()
        with redirect_stdout(buf):
            rc = main([str(sd), "--fix", "FM-007", "--fix", "FM-014", "--yes", "--json"])
        assert rc == 0
        data = json.loads(buf.getvalue())
        applied_rule_ids = {f["rule_id"] for f in data["fixes"] if f["applied"]}
        assert "FM-007" in applied_rule_ids
        assert "FM-014" in applied_rule_ids

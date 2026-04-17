"""Unit tests for scripts/validate_strict.py (M1 DoD 6)."""

from __future__ import annotations

import io
import json
import textwrap
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from scripts.models import Severity, ValidationReport
from scripts.validate_strict import (
    SOFT_ERROR_DISCLAIMER,
    main,
    validate_all,
    validate_body,
    validate_frontmatter,
    validate_references,
    validate_structure,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def find(report, rule_id: str):
    for r in report.results:
        if r.rule_id == rule_id:
            return r
    raise AssertionError(f"rule {rule_id} not in report")


def any_failing(report, rule_id: str) -> bool:
    return any(r.rule_id == rule_id and not r.passed for r in report.results)


# ---------------------------------------------------------------------------
# Valid skills (sanity)
# ---------------------------------------------------------------------------


def test_valid_minimal_skill(fixtures_dir):
    report = validate_all(fixtures_dir / "valid-skill-minimal")
    assert report.summary["error_count"] == 0
    assert report.summary["soft_error_count"] == 0


def test_valid_full_skill(fixtures_dir):
    report = validate_all(fixtures_dir / "valid-skill-full")
    assert report.summary["error_count"] == 0
    assert report.summary["soft_error_count"] == 0
    assert report.summary["warning_count"] == 0


# ---------------------------------------------------------------------------
# Structure rules (FM-001, FM-002, FM-004, ST-001)
# ---------------------------------------------------------------------------


def test_missing_skill_md(tmp_path):
    (tmp_path / "empty-skill").mkdir()
    report = validate_all(tmp_path / "empty-skill")
    assert find(report, "FM-001").passed is False
    assert find(report, "FM-001").severity is Severity.ERROR


def test_wrong_case_skill_md(fixtures_dir):
    report = validate_all(fixtures_dir / "invalid-structure")
    fm001 = find(report, "FM-001")
    assert fm001.passed is False
    assert "case-sensitive" in fm001.message.lower() or "skill.md" in fm001.message


def test_folder_not_kebab_case(skill_factory):
    skill = skill_factory(folder="MySkill", name="my-skill")
    report = validate_all(skill)
    assert find(report, "FM-002").passed is False


def test_readme_in_skill_folder(skill_factory):
    skill = skill_factory(include_readme=True)
    report = validate_all(skill)
    assert find(report, "FM-004").passed is False
    assert find(report, "FM-004").severity is Severity.WARNING


def test_skill_folder_size_within_limit(skill_factory):
    skill = skill_factory()
    report = validate_all(skill)
    assert find(report, "ST-001").passed is True


# ---------------------------------------------------------------------------
# Frontmatter rules (FM-003, FM-005..016)
# ---------------------------------------------------------------------------


def test_folder_name_mismatch(skill_factory):
    skill = skill_factory(folder="my-skill", name="different-name")
    report = validate_all(skill)
    fm003 = find(report, "FM-003")
    assert fm003.passed is False
    assert fm003.severity is Severity.SOFT_ERROR


def test_missing_frontmatter_delimiters(skill_factory):
    skill = skill_factory(omit_delimiters=True)
    report = validate_all(skill)
    assert find(report, "FM-005").passed is False


def test_missing_name(skill_factory):
    skill = skill_factory(name=None)
    report = validate_all(skill)
    assert find(report, "FM-006").passed is False


def test_name_with_spaces(skill_factory):
    skill = skill_factory(folder="my-skill", name='"my skill"')
    report = validate_all(skill)
    assert find(report, "FM-007").passed is False
    assert find(report, "FM-008").passed is False


def test_name_with_capitals(skill_factory):
    skill = skill_factory(folder="my-skill", name="My-Skill")
    report = validate_all(skill)
    assert find(report, "FM-007").passed is False
    assert find(report, "FM-008").passed is False


def test_name_with_underscore(skill_factory):
    skill = skill_factory(folder="my-skill", name="my_skill")
    report = validate_all(skill)
    assert find(report, "FM-007").passed is False


def test_name_contains_claude(fixtures_dir):
    # Uses the dedicated fixture to exercise the full path.
    report = validate_all(fixtures_dir / "invalid-reserved-name")
    assert find(report, "FM-009").passed is False
    assert find(report, "FM-009").severity is Severity.ERROR


def test_name_contains_anthropic(skill_factory):
    skill = skill_factory(folder="anthropic-tool", name="anthropic-tool")
    report = validate_all(skill)
    assert find(report, "FM-009").passed is False


def test_name_too_long(skill_factory):
    long = "a" + "-long" * 15  # > 64 chars
    skill = skill_factory(folder=long, name=long)
    report = validate_all(skill)
    assert find(report, "FM-010").passed is False


def test_missing_description(skill_factory):
    skill = skill_factory(description=None)
    report = validate_all(skill)
    assert find(report, "FM-011").passed is False


def test_description_without_when(skill_factory):
    # No WHEN keyword, short, no obvious verb -> heuristic fails.
    skill = skill_factory(description="a tool")
    report = validate_all(skill)
    fm012 = find(report, "FM-012")
    assert fm012.passed is False
    assert fm012.severity is Severity.SOFT_ERROR


def test_description_too_long(skill_factory):
    skill = skill_factory(description="x" * 1025)
    report = validate_all(skill)
    assert find(report, "FM-013").passed is False


def test_description_xml_brackets(fixtures_dir):
    report = validate_all(fixtures_dir / "invalid-xml-brackets")
    fm014 = find(report, "FM-014")
    assert fm014.passed is False
    assert fm014.severity is Severity.ERROR


def test_compatibility_too_long(skill_factory):
    skill = skill_factory(compatibility="c" * 501)
    report = validate_all(skill)
    assert find(report, "FM-015").passed is False


def test_unknown_frontmatter_key(skill_factory):
    skill = skill_factory(extra_frontmatter={"version": "1.0.0"})
    report = validate_all(skill)
    assert find(report, "FM-016").passed is False


# ---------------------------------------------------------------------------
# Body rules (BD-001..006)
# ---------------------------------------------------------------------------


def test_body_over_500_lines(skill_factory):
    long_body = "\n".join(["line" + str(i) for i in range(520)]) + "\n## Examples\n## Common Issues\n"
    skill = skill_factory(body=long_body)
    report = validate_all(skill)
    bd001 = find(report, "BD-001")
    assert bd001.passed is False
    assert bd001.severity is Severity.WARNING


def test_body_over_5000_words(skill_factory):
    words = " ".join(["word"] * 5100)
    body = f"# T\n\n## Instructions\n{words}\n\n## Examples\nex\n\n## Common Issues\nx\n"
    skill = skill_factory(body=body)
    report = validate_all(skill)
    assert find(report, "BD-002").passed is False


def test_body_xml_in_fenced_block_passes(skill_factory):
    body = textwrap.dedent("""\
    # T
    ## Instructions
    Example XML:
    ```xml
    <config><flag/></config>
    ```
    ## Examples
    ok
    ## Common Issues
    ok
    """)
    skill = skill_factory(body=body)
    report = validate_all(skill)
    assert find(report, "BD-003").passed is True


def test_body_xml_outside_fenced_block(skill_factory):
    body = textwrap.dedent("""\
    # T
    ## Instructions
    This paragraph has <stray> tags outside a fenced block.
    ## Examples
    ok
    ## Common Issues
    ok
    """)
    skill = skill_factory(body=body)
    report = validate_all(skill)
    bd003 = find(report, "BD-003")
    assert bd003.passed is False
    assert bd003.severity is Severity.SOFT_ERROR


def test_body_no_error_handling(skill_factory):
    body = textwrap.dedent("""\
    # T
    ## Instructions
    1. do it
    ## Examples
    ok
    """)
    skill = skill_factory(body=body)
    report = validate_all(skill)
    bd005 = find(report, "BD-005")
    assert bd005.passed is False
    assert bd005.severity is Severity.SOFT_ERROR


def test_body_no_examples(skill_factory):
    body = textwrap.dedent("""\
    # T
    ## Instructions
    1. do it
    ## Common Issues
    ok
    """)
    skill = skill_factory(body=body)
    report = validate_all(skill)
    assert find(report, "BD-006").passed is False


# ---------------------------------------------------------------------------
# Structure rules (SC-001, SC-002)
# ---------------------------------------------------------------------------


def test_referenced_file_missing(skill_factory):
    body = textwrap.dedent("""\
    # T
    ## Instructions
    See references/missing.md for details.
    ## Examples
    ok
    ## Common Issues
    ok
    """)
    skill = skill_factory(body=body)
    report = validate_all(skill)
    sc002 = find(report, "SC-002")
    assert sc002.passed is False
    assert sc002.severity is Severity.ERROR


def test_referenced_file_exists_passes(skill_factory):
    body = textwrap.dedent("""\
    # T
    ## Instructions
    See references/notes.md.
    ## Examples
    ok
    ## Common Issues
    ok
    """)
    skill = skill_factory(
        body=body,
        references={"notes.md": "# notes\n"},
    )
    report = validate_all(skill)
    assert find(report, "SC-002").passed is True


def test_scripts_runnable_recognized(skill_factory):
    skill = skill_factory(scripts={"run.py": "print('hi')\n"})
    report = validate_all(skill)
    assert find(report, "SC-001").passed is True


def test_scripts_unrunnable_flagged(skill_factory):
    skill = skill_factory(scripts={"notes.txt": "not a script\n"})
    report = validate_all(skill)
    assert find(report, "SC-001").passed is False


# ---------------------------------------------------------------------------
# 3-tier severity semantics (ADR-007)
# ---------------------------------------------------------------------------


def test_soft_error_default_as_warning(skill_factory):
    # Short description with no WHEN -> FM-012 fails. Non-strict mode:
    # soft-error is reported but summary.passed stays true (no ERROR).
    skill = skill_factory(description="a tool")
    report = validate_all(skill, strict=False)
    assert any_failing(report, "FM-012")
    assert report.summary["passed"] is True
    assert report.summary["strict"] is False


def test_soft_error_strict_as_error(skill_factory):
    skill = skill_factory(description="a tool")
    report = validate_all(skill, strict=True)
    assert report.summary["passed"] is False
    assert report.summary["strict"] is True


def test_warning_stays_warning_in_strict(skill_factory):
    # Body without examples -> BD-006 WARNING. Even --strict passes.
    body = textwrap.dedent("""\
    # T
    ## Instructions
    1. step one.
    ## Common Issues
    ok
    """)
    skill = skill_factory(body=body)
    report = validate_all(skill, strict=True)
    assert any_failing(report, "BD-006")
    assert report.summary["passed"] is True


def test_soft_error_disclaimer_message(skill_factory):
    skill = skill_factory(description="a tool")
    report = validate_all(skill)
    fm012 = find(report, "FM-012")
    assert not fm012.passed
    assert SOFT_ERROR_DISCLAIMER.strip() in fm012.message


# ---------------------------------------------------------------------------
# JSON output (ADR-009)
# ---------------------------------------------------------------------------


def _run_cli(args: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(args)
    return rc, buf.getvalue()


def test_json_envelope_structure(fixtures_dir):
    rc, out = _run_cli([str(fixtures_dir / "valid-skill-minimal"), "--json"])
    assert rc == 0
    payload = json.loads(out)
    for key in ("tool_version", "pdf_version", "timestamp", "skill_path", "agent_id", "results", "summary"):
        assert key in payload
    assert isinstance(payload["results"], list)


def test_json_flat_output(fixtures_dir):
    rc, out = _run_cli([str(fixtures_dir / "valid-skill-minimal"), "--json", "--flat"])
    assert rc == 0
    payload = json.loads(out)
    assert isinstance(payload, list)
    assert all("rule_id" in r for r in payload)


def test_json_summary_counts(skill_factory):
    # Craft a skill that produces at least 1 soft-error and 1 warning.
    skill = skill_factory(description="a tool", include_readme=True)
    rc, out = _run_cli([str(skill), "--json"])
    # rc=0 because no ERROR; soft-error + warning tolerated in non-strict.
    assert rc == 0
    summary = json.loads(out)["summary"]
    assert summary["error_count"] == 0
    assert summary["soft_error_count"] >= 1
    assert summary["warning_count"] >= 1


def test_cli_exit_code_on_error(fixtures_dir):
    rc, _ = _run_cli([str(fixtures_dir / "invalid-reserved-name")])
    assert rc == 1


def test_cli_strict_exit_code_on_soft_error(skill_factory):
    skill = skill_factory(description="a tool")
    rc, _ = _run_cli([str(skill), "--strict"])
    assert rc == 1


def test_cli_missing_skill_dir(tmp_path):
    rc, _ = _run_cli([str(tmp_path / "does-not-exist")])
    assert rc == 2


# ---------------------------------------------------------------------------
# package_skill_strict integration
# ---------------------------------------------------------------------------


def test_package_strict_blocks_on_error(fixtures_dir, tmp_path):
    from scripts.package_skill_strict import package_skill_strict

    result = package_skill_strict(
        fixtures_dir / "invalid-reserved-name",
        output_dir=tmp_path,
    )
    assert result is None


def test_package_strict_passes_clean(fixtures_dir, tmp_path):
    from scripts.package_skill_strict import package_skill_strict

    result = package_skill_strict(
        fixtures_dir / "valid-skill-minimal",
        output_dir=tmp_path,
    )
    assert result is not None
    assert Path(result).exists()


def test_package_strict_no_strict_allows_soft_errors(skill_factory, tmp_path):
    from scripts.package_skill_strict import package_skill_strict

    # Skill has no ERROR but a SOFT-ERROR (short description). With --no-strict
    # (strict=False) packaging should succeed.
    skill = skill_factory(
        folder="soft-only-skill",
        name="soft-only-skill",
        description="a tool",  # triggers FM-012 SOFT-ERROR
    )
    result = package_skill_strict(skill, output_dir=tmp_path, strict=False)
    assert result is not None


# ---------------------------------------------------------------------------
# Misc: subfunctions callable directly
# ---------------------------------------------------------------------------


def test_validate_frontmatter_returns_list(fixtures_dir):
    skill = fixtures_dir / "valid-skill-minimal"
    results = validate_frontmatter(skill / "SKILL.md", skill_dir=skill)
    assert results
    assert all(hasattr(r, "rule_id") for r in results)


def test_validate_body_returns_list(fixtures_dir):
    results = validate_body(fixtures_dir / "valid-skill-minimal" / "SKILL.md")
    assert results
    ids = {r.rule_id for r in results}
    assert ids >= {"BD-001", "BD-002", "BD-003", "BD-004", "BD-005", "BD-006"}


def test_validate_structure_returns_list(fixtures_dir):
    results = validate_structure(fixtures_dir / "valid-skill-minimal")
    assert any(r.rule_id == "FM-001" for r in results)


def test_validate_references_returns_list(fixtures_dir):
    skill = fixtures_dir / "valid-skill-full"
    results = validate_references(skill, skill / "SKILL.md")
    assert any(r.rule_id == "SC-002" for r in results)

"""P2-1 test half — skill-creator-x must pass its own validator.

This is the "cobbler's children" regression guard: the tool that validates
other skills should pass its own ERROR and SOFT-ERROR rules. Start waivered
(no WARNINGs promoted to ERROR); OQ-3 tracks the strict-mode promotion.
"""
from __future__ import annotations

from pathlib import Path

from scripts.validate_strict import validate_all


SKILL_ROOT = Path(__file__).resolve().parents[1]

# Rules deliberately NOT enforced in the self-check yet. Empty for now;
# if a specific rule needs a waiver later, add it here with a one-line
# comment explaining why. See OQ-3 in .omc/plans/open-questions.md.
WAIVERS: set[str] = set()


def test_skill_creator_x_passes_strict():
    """No ERROR or SOFT-ERROR rules should be failing on skill-creator-x itself.

    This asserts the tool meets its own minimum bar. It intentionally does NOT
    promote WARNINGs (BD-001 body-line-count, BD-002 word-count, etc.) to
    errors yet — see OQ-3.
    """
    report = validate_all(SKILL_ROOT)
    blocking = [
        r for r in report.results
        if not r.passed
        and r.severity in ("ERROR", "SOFT-ERROR")
        and r.rule_id not in WAIVERS
    ]
    assert blocking == [], "\n".join(
        f"{r.rule_id} [{r.severity}]: {r.message}" for r in blocking
    )


def test_split_frontmatter_public_and_alias_both_importable():
    """Public split_frontmatter + deprecated _split_frontmatter alias both import.

    P2-B promotes _split_frontmatter to a public symbol. The old name stays
    for one release as a deprecated alias so downstream scripts do not break
    mid-refactor. This test guarantees the deprecation window contract.
    """
    from scripts.validate_strict import _split_frontmatter, split_frontmatter

    # Both must be callables.
    assert callable(split_frontmatter)
    assert callable(_split_frontmatter)

    # Same behavior on a valid frontmatter string.
    sample = "---\nname: test\ndescription: Test. Use when testing.\n---\n\n# Body\n"
    expected = split_frontmatter(sample)
    via_alias = _split_frontmatter(sample)
    assert expected == via_alias
    assert expected is not None
    fm_text, body = expected
    assert "name: test" in fm_text
    assert body.startswith("\n# Body")

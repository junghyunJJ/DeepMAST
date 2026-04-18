"""P2-5 — utils.parse_skill_md must delegate to yaml.safe_load.

The old hand-rolled parser:
- Truncated quoted strings on embedded colons/newlines.
- Hijacked body lines that started with ``name:`` because it scanned the
  whole file instead of just the frontmatter block.
- Only recognized four block-scalar indicators (``>``, ``|``, ``>-``, ``|-``).

The new implementation uses ``yaml.safe_load`` via the public
``split_frontmatter`` helper.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.utils import parse_skill_md


def _write(tmp_path: Path, frontmatter: str, body: str = "# Body\n") -> Path:
    sd = tmp_path / "skill-x"
    sd.mkdir()
    (sd / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\n{body}", encoding="utf-8")
    return sd


def test_quoted_multiline_description(tmp_path):
    """A double-quoted string with embedded colons and escape sequences parses in full."""
    sd = _write(
        tmp_path,
        frontmatter='name: q\ndescription: "Line one with: colons and \\"quotes\\""',
    )
    name, description, _ = parse_skill_md(sd)
    assert name == "q"
    assert description == 'Line one with: colons and "quotes"'


def test_flow_mapping_metadata_not_hijacked(tmp_path):
    """A flow-style metadata mapping doesn't leak into name or description."""
    sd = _write(
        tmp_path,
        frontmatter="name: x\ndescription: A short desc. Use when testing.\nmetadata: {author: me, version: 1}",
    )
    name, description, _ = parse_skill_md(sd)
    assert name == "x"
    assert description == "A short desc. Use when testing."


def test_body_line_name_colon_ignored(tmp_path):
    """A body line starting with ``name:`` must NOT override the frontmatter name."""
    sd = _write(
        tmp_path,
        frontmatter='name: correct-name\ndescription: Has the right name. Use when right.',
        body="# Example\n\nname: Bob wrote this line as prose.\n",
    )
    name, _description, _ = parse_skill_md(sd)
    assert name == "correct-name"


def test_escape_sequences_preserved(tmp_path):
    r"""``\u2013`` in a double-quoted scalar expands to the en-dash character."""
    sd = _write(
        tmp_path,
        frontmatter='name: e\ndescription: "A \\u2013 dash"',
    )
    _name, description, _ = parse_skill_md(sd)
    assert description == "A \u2013 dash"  # en-dash


def test_block_scalar_literal_description(tmp_path):
    """``description: |`` preserves newlines between content lines.

    YAML's literal block scalar preserves newlines. The outer .strip()
    trims the leading/trailing newline introduced by the block opener.
    """
    sd = _write(
        tmp_path,
        frontmatter="name: b\ndescription: |\n  Line one.\n  Line two.",
    )
    _name, description, _ = parse_skill_md(sd)
    # Newline between the two lines is preserved; leading/trailing whitespace stripped.
    assert description == "Line one.\nLine two."


def test_block_scalar_folded_description(tmp_path):
    """``description: >`` folds newlines into single spaces."""
    sd = _write(
        tmp_path,
        frontmatter="name: f\ndescription: >\n  Line one.\n  Line two.",
    )
    _name, description, _ = parse_skill_md(sd)
    # Folded scalar joins the two lines with a single space.
    assert description == "Line one. Line two."


def test_plain_scalar_with_colon_in_value(tmp_path):
    """A plain scalar whose value contains a colon inside quotes parses intact."""
    sd = _write(
        tmp_path,
        frontmatter='name: p\ndescription: "Use when user asks: \\"do X\\""',
    )
    _name, description, _ = parse_skill_md(sd)
    # YAML preserves the full quoted value including the colon.
    assert description == 'Use when user asks: "do X"'

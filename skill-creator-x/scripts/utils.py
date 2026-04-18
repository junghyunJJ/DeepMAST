"""Shared utilities for skill-creator scripts."""

from pathlib import Path

import yaml

from scripts.validate_strict import split_frontmatter


def parse_skill_md(skill_path: Path) -> tuple[str, str, str]:
    """Parse a SKILL.md file, returning ``(name, description, full_content)``.

    Since P2-B this delegates to :func:`yaml.safe_load` via the public
    :func:`scripts.validate_strict.split_frontmatter` helper. The previous
    hand-rolled parser only recognized four block-scalar indicators, mangled
    quoted multi-line values, and — because it scanned the entire file
    linewise — was hijacked by any body line that happened to start with
    ``name:``. Delegating to PyYAML removes all three classes of bug and
    shares the frontmatter-splitting contract with the rest of the toolkit.

    Raises ``ValueError`` if the file is missing frontmatter delimiters or
    the frontmatter block is not a YAML mapping. Callers that want a
    best-effort parse should catch ``ValueError`` and fall back to empty
    strings.
    """
    content = (skill_path / "SKILL.md").read_text(encoding="utf-8")
    split = split_frontmatter(content)
    if split is None:
        raise ValueError("SKILL.md missing frontmatter delimiters")
    fm_text, _body = split
    try:
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError as e:
        raise ValueError(f"SKILL.md frontmatter is not valid YAML: {e}") from e
    if fm is None:
        fm = {}
    if not isinstance(fm, dict):
        raise ValueError(
            "SKILL.md frontmatter must be a mapping at the top level"
        )
    name = str(fm.get("name", "")).strip()
    description_raw = fm.get("description", "")
    # Trim only leading/trailing whitespace for folded/plain scalars; do NOT
    # collapse internal newlines — a literal block scalar (``description: |``)
    # preserves them intentionally and downstream consumers that care about
    # the distinction now see the original YAML semantics instead of the
    # hand-parser's always-join-on-spaces behavior.
    description = str(description_raw).strip() if description_raw is not None else ""
    return name, description, content

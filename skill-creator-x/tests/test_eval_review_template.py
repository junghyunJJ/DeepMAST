"""Tests for P1-1: eval_review.html XSS-safe placeholder injection.

See .omc/plans/skill-creator-x-p1-p2-fixes.md P1-1 for context.

The injection fix embeds eval data via a JSON <script type="application/json">
tag parsed with document.getElementById(...).textContent + JSON.parse. The
skill name and description placeholders are HTML-escaped before substitution.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path


HTML_PATH = Path(__file__).resolve().parents[1] / "assets" / "eval_review.html"


def _substitute(template: str, *, name: str, description: str, eval_items: list[dict]) -> str:
    """Mirror the substitution step the skill instructs agents to perform.

    The contract defined in SKILL.md step 2 after the P1-1 fix:
    - __EVAL_DATA_PLACEHOLDER__ → json.dumps(eval_items).replace("</", "<\\/")
    - __SKILL_NAME_PLACEHOLDER__ → html.escape(name, quote=True)
    - __SKILL_DESCRIPTION_PLACEHOLDER__ → html.escape(description, quote=True)
    """
    eval_json = json.dumps(eval_items).replace("</", "<\\/")
    return (
        template.replace("__EVAL_DATA_PLACEHOLDER__", eval_json)
        .replace("__SKILL_NAME_PLACEHOLDER__", html.escape(name, quote=True))
        .replace("__SKILL_DESCRIPTION_PLACEHOLDER__", html.escape(description, quote=True))
    )


def test_placeholder_uses_json_script_tag():
    """The eval-data placeholder must sit inside a JSON script tag, not raw JS."""
    content = HTML_PATH.read_text(encoding="utf-8")
    # New pattern: JSON-typed script tag with a well-known id.
    assert '<script type="application/json" id="eval-data">' in content
    assert "__EVAL_DATA_PLACEHOLDER__" in content

    # Old vulnerable pattern must be gone.
    assert "const EVAL_DATA = __EVAL_DATA_PLACEHOLDER__" not in content

    # The placeholder must occur inside the JSON script tag.
    m = re.search(
        r'<script type="application/json" id="eval-data">\s*__EVAL_DATA_PLACEHOLDER__\s*</script>',
        content,
    )
    assert m is not None, "placeholder must be the literal contents of the JSON script tag"

    # The runtime code parses via textContent + JSON.parse.
    assert "document.getElementById('eval-data').textContent" in content
    assert "JSON.parse(" in content


def test_skill_name_escaped():
    """A hostile skill name does not break out of its span."""
    template = HTML_PATH.read_text(encoding="utf-8")
    hostile = '<script>alert(1)</script>&"'
    rendered = _substitute(template, name=hostile, description="ok", eval_items=[])
    # The hostile literal tag must NOT appear as raw HTML.
    assert "<script>alert(1)</script>" not in rendered
    # But the escaped form IS present (visible as text).
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered


def test_eval_data_roundtrip_with_hostile_query():
    """A hostile eval query survives the JSON script-tag embedding and round-trips."""
    template = HTML_PATH.read_text(encoding="utf-8")
    hostile_query = '</script><img src=x onerror=alert(1)>\n\\ "double" \'single\''
    items = [{"query": hostile_query, "should_trigger": True}]
    rendered = _substitute(template, name="my-skill", description="d", eval_items=items)

    # Extract the JSON from inside the script tag.
    m = re.search(
        r'<script type="application/json" id="eval-data">\s*(.*?)\s*</script>',
        rendered,
        re.DOTALL,
    )
    assert m is not None, "JSON script tag must be present in rendered output"
    embedded = m.group(1)

    # The literal `</` sequence from `</script>` in the query must be escaped to `<\/`
    # so the browser does not terminate the script tag early.
    assert "</script>" not in embedded, (
        "embedded JSON must not contain a literal </script> token; "
        "json.dumps(...).replace('</', '<\\/') should escape it"
    )

    # Round-trip: unescape `<\/` back to `</` and parse.
    restored = embedded.replace("<\\/", "</")
    parsed = json.loads(restored)
    assert parsed == items

"""The loaded reporting skill must match the guarded writer surface."""

import json
from pathlib import Path


SKILL_PATH = Path("skills/drug-target-reporting/SKILL.md")
SCORING_PATH = Path("skills/drug-target-reporting/references/scoring_guide.md")


def test_reporting_skill_matches_guarded_direct_writer_surface() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "## Supported local Ollama diagnostic invocation" in text
    assert "This invocation is diagnostic; no successful report was produced." in text
    assert "## Verified local Ollama smoke invocation" not in text
    assert "Author exactly one `hybrid_report_sections/v1` payload through\n`save_report_sections`." in text
    assert "Qwen owns only canonical Section 4 hypotheses and 2–4\nSection 5 recommendations in `report_sections.json`." in text
    assert "Jinja owns every rendered layout and factual value" in text
    assert "build_evidence_summary" in text
    assert 'scope="hypothesis"' in text
    assert "call `save_report_sections`\n   exactly once, then stop." in text
    assert "NEVER create or read `evidence/hypothesis_report.json`." in text
    assert "NEVER create or write `report_data.json`, `target_assessment.json`, or\n  `drug.md`." in text
    for retired_operation in (
        "save_report_expansions",
        "render_drug_md_from_expansions",
        "generate_drug_html_report",
    ):
        assert retired_operation not in text


def test_reporting_skill_evals_and_scoring_avoid_legacy_section_four_source() -> None:
    assert "hypothesis_report.json" not in SCORING_PATH.read_text(encoding="utf-8")
    scenarios = json.loads(Path("skills/drug-target-reporting/evals/evals.json").read_text())
    serialized = json.dumps(scenarios)
    assert "save_report_expansions" not in serialized
    assert "render_drug_md_from_expansions" not in serialized
    assert "generate_drug_html_report" not in serialized

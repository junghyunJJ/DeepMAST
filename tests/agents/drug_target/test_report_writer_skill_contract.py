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
    assert "build_evidence_summary" not in text
    assert "include_legacy_hypothesis=False" not in text
    assert "resolved_drugs.json" not in text
    assert "sole factual input" in text
    assert "gated assessment, featured OpenTargets/Stage 3 evidence, and passed Stage 1 evidence" in " ".join(
        text.split()
    )
    assert 'scope="hypothesis"' in text
    assert "1-5 supporting evidence paths" in text
    assert "1-3 supporting evidence paths" not in text
    assert '"schema_version": "hybrid_report_sections/v1"' in text
    assert '"hypothesis_report": {"hypotheses": [...], "gap_analysis": {...}}' in text
    assert '"text": "one future-directed sentence."' in text
    assert '"supporting_sources": ["evidence/<exact-file>.json"]' in text
    assert "Never use `recommendation` or `sources` as keys." in text
    assert "Include all three top-level keys even when an evidence limitation is discussed." in text
    assert "call `save_report_sections`\n   exactly once, then stop." in text
    assert "NEVER create or read `evidence/hypothesis_report.json`." in text
    assert "target assessment" not in text.lower()
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
    initial = next(item for item in scenarios["evals"] if item["id"] == "initial_direct_write")
    assert initial["expected_output"] == (
        "Read the reporting skill, call load_lr_candidates, call "
        'load_evidence_files with scope="hypothesis", then call '
        "save_report_sections once with one sections payload and stop."
    )
    repair = next(item for item in scenarios["evals"] if item["id"] == "repair_only")
    assert repair["expected_output"] == (
        "Change only the listed sections issue and save the corrected sections payload once; "
        "do not read skills or rebuild evidence."
    )
    assert "drug.md" not in json.dumps(repair)

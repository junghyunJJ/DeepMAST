"""Production report-writer prompt contract."""

from src.agents.drug_target.subagents.prompts import (
    EVIDENCE_ASSESSOR_PROMPT,
    REPORT_WRITER_PROMPT,
)


def test_report_writer_prompt_owns_sections_payload_and_repair_contract() -> None:
    assert "build_evidence_summary" not in REPORT_WRITER_PROMPT
    assert "include_legacy_hypothesis=False" not in REPORT_WRITER_PROMPT
    assert 'Call load_evidence_files with scope="hypothesis"' in REPORT_WRITER_PROMPT
    assert "save_report_sections" in REPORT_WRITER_PROMPT
    assert "one and only terminal write" in REPORT_WRITER_PROMPT
    assert "hybrid_report_sections/v1" in REPORT_WRITER_PROMPT
    assert "4-6 canonical hypotheses" in REPORT_WRITER_PROMPT
    assert "2-4 one-sentence" in REPORT_WRITER_PROMPT
    assert "1-5 supporting evidence paths" in REPORT_WRITER_PROMPT
    assert "1-3 supporting evidence paths" not in REPORT_WRITER_PROMPT
    assert '"schema_version": "hybrid_report_sections/v1"' in REPORT_WRITER_PROMPT
    assert '"hypothesis_report": {"hypotheses": [...], "gap_analysis": {...}}' in REPORT_WRITER_PROMPT
    assert '"text": "one future-directed sentence."' in REPORT_WRITER_PROMPT
    assert '"supporting_sources": ["evidence/<exact-file>.json"]' in REPORT_WRITER_PROMPT
    assert "Never use `recommendation` or `sources` as keys." in REPORT_WRITER_PROMPT
    assert "Include all three top-level keys even when an evidence limitation is discussed." in REPORT_WRITER_PROMPT
    assert "## REPAIR MODE" in REPORT_WRITER_PROMPT
    assert "JSON sections payload" in REPORT_WRITER_PROMPT
    assert "never edit `drug.md`" in REPORT_WRITER_PROMPT
    assert "exactly one `save_report_sections` call" in REPORT_WRITER_PROMPT
    assert "Load the current sections receipt" not in REPORT_WRITER_PROMPT
    assert "Use the corrected JSON sections payload supplied" in REPORT_WRITER_PROMPT
    assert "save_report_expansions" not in REPORT_WRITER_PROMPT
    assert "render_drug_md_from_expansions" not in REPORT_WRITER_PROMPT
    assert "generate_drug_html_report" not in REPORT_WRITER_PROMPT
    assert "NEVER create or read evidence/hypothesis_report.json" in REPORT_WRITER_PROMPT
    assert "NEVER create or write report_data.json" in REPORT_WRITER_PROMPT
    assert "save_target_assessment" not in REPORT_WRITER_PROMPT
    assert "save_drug_md" not in REPORT_WRITER_PROMPT


def test_evidence_assessor_fallback_loader_is_limited_to_assessment_scope() -> None:
    assert 'load_evidence_files(data_dir, scope="assessment")' in EVIDENCE_ASSESSOR_PROMPT


def test_evidence_assessor_hands_off_to_the_production_report_writer() -> None:
    assert "handoff signal to report_writer" in EVIDENCE_ASSESSOR_PROMPT
    assert "handoff signal to `hypothesis_writer`" not in EVIDENCE_ASSESSOR_PROMPT

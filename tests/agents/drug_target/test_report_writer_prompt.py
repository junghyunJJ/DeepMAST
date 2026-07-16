"""Production report-writer prompt contract."""

from src.agents.drug_target.subagents.prompts import REPORT_WRITER_PROMPT


def test_report_writer_prompt_owns_direct_markdown_and_repair_contract() -> None:
    assert "build_evidence_summary" in REPORT_WRITER_PROMPT
    assert "include_legacy_hypothesis=False" in REPORT_WRITER_PROMPT
    assert 'scope="hypothesis"' in REPORT_WRITER_PROMPT
    assert "save_target_assessment exactly once" in REPORT_WRITER_PROMPT
    assert "save_drug_md" in REPORT_WRITER_PROMPT
    assert "strip_unexpanded_markers=False" in REPORT_WRITER_PROMPT
    assert "## REPAIR MODE" in REPORT_WRITER_PROMPT
    assert "Do not read skills or call initial-write tools" in REPORT_WRITER_PROMPT
    assert "#### 4.1.1." in REPORT_WRITER_PROMPT
    assert "- Genes:" in REPORT_WRITER_PROMPT
    assert "save_report_expansions" not in REPORT_WRITER_PROMPT
    assert "render_drug_md_from_expansions" not in REPORT_WRITER_PROMPT
    assert "generate_drug_html_report" not in REPORT_WRITER_PROMPT
    assert "NEVER create or read evidence/hypothesis_report.json" in REPORT_WRITER_PROMPT
    assert "NEVER create or write report_data.json" in REPORT_WRITER_PROMPT
    assert REPORT_WRITER_PROMPT.index("save_target_assessment") < REPORT_WRITER_PROMPT.index("save_drug_md")

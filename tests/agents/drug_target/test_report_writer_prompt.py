"""Production report-writer prompt contract."""

from src.agents.drug_target.subagents.prompts import (
    EVIDENCE_ASSESSOR_PROMPT,
    REPORT_WRITER_PROMPT,
)


def test_report_writer_prompt_is_recommendation_only() -> None:
    prompt = " ".join(REPORT_WRITER_PROMPT.split())
    assert "build_evidence_summary" not in REPORT_WRITER_PROMPT
    assert "include_legacy_hypothesis=False" not in REPORT_WRITER_PROMPT
    assert "load_validated_hypothesis_report" in REPORT_WRITER_PROMPT
    assert "pipeline_recommendations" in REPORT_WRITER_PROMPT
    assert "save_report_sections" in REPORT_WRITER_PROMPT
    assert "4-6 canonical hypotheses" not in REPORT_WRITER_PROMPT
    assert "load_evidence_files" not in REPORT_WRITER_PROMPT
    assert "load_lr_candidates" not in REPORT_WRITER_PROMPT
    assert '"hypothesis_report"' not in REPORT_WRITER_PROMPT
    assert "gap analysis" not in REPORT_WRITER_PROMPT.lower()
    assert "exactly `schema_version` and `pipeline_recommendations`" in REPORT_WRITER_PROMPT
    assert "2-4 Section 5 pipeline recommendations" in REPORT_WRITER_PROMPT
    assert "1-5 exact `evidence/<filename>.json` paths" in REPORT_WRITER_PROMPT
    assert "If its receipt has `saved:true`, stop." in REPORT_WRITER_PROMPT
    assert "If its receipt has `saved:false`, repair only returned recommendation violations" in prompt
    assert "call `save_report_sections` once more" in REPORT_WRITER_PROMPT
    assert REPORT_WRITER_PROMPT.count("call `save_report_sections` once more") == 1
    assert "then stop." in REPORT_WRITER_PROMPT
    assert "## REPAIR MODE" in REPORT_WRITER_PROMPT
    assert "supplied recommendation payload" in REPORT_WRITER_PROMPT
    assert "Call `save_report_sections` exactly once with the corrected recommendation payload, then stop." in REPORT_WRITER_PROMPT
    assert "save_report_expansions" not in REPORT_WRITER_PROMPT
    assert "render_drug_md_from_expansions" not in REPORT_WRITER_PROMPT
    assert "generate_drug_html_report" not in REPORT_WRITER_PROMPT
    assert "save_target_assessment" not in REPORT_WRITER_PROMPT
    assert "save_drug_md" not in REPORT_WRITER_PROMPT


def test_evidence_assessor_fallback_loader_is_limited_to_assessment_scope() -> None:
    assert 'load_evidence_files(data_dir, scope="assessment")' in EVIDENCE_ASSESSOR_PROMPT


def test_evidence_assessor_hands_off_to_the_production_report_writer() -> None:
    assert "handoff signal to report_writer" in EVIDENCE_ASSESSOR_PROMPT
    assert "handoff signal to `hypothesis_writer`" not in EVIDENCE_ASSESSOR_PROMPT

"""Current report-writer docs must distinguish guarded and legacy entrypoints."""

from pathlib import Path


REFERENCE = Path("docs/drugtarget/drug_target_agent_reference.md")
STAGE_GUIDE = Path("docs/drugtarget/drug_target_stage_guide.md")


def test_docs_describe_reporter_integration_as_guarded_direct_agent() -> None:
    reference = REFERENCE.read_text(encoding="utf-8")
    stage_guide = STAGE_GUIDE.read_text(encoding="utf-8")

    for text in (reference, stage_guide):
        assert "**Production entrypoints**" in text
        assert "`run_drug_target_e2e.py`" in text
        assert "`run_drug_target_agent_bc.py`" in text
        assert "`create_drug_target_agent`" in text
        assert "**Production Reporter integration**" in text
        assert "`run_drug_target_assessment(data_dir, disease)`" in text
        assert '`workflow_mode="guarded_report"`' in text
        assert "returned `agent.ainvoke(...)`" in text
        assert "`drug_target_graph.ainvoke(...)`" not in text
        assert "super_graph.py" in text
        assert "Legacy compatibility super-graph" in text

    assert "`run_report_writer_only.py` is diagnostic-only." in reference
    assert "`run_report_writer_only.py` only diagnoses the\ncanonical writer against existing evidence." in stage_guide

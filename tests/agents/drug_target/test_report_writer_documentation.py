"""Current report-writer docs must distinguish guarded and legacy entrypoints."""

from pathlib import Path


REFERENCE = Path("docs/drugtarget/drug_target_agent_reference.md")
STAGE_GUIDE = Path("docs/drugtarget/drug_target_stage_guide.md")


def test_docs_describe_guarded_reporter_and_graph_builder_entrypoints() -> None:
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
        assert "Guarded direct-agent deployment entrypoint" in text
        assert "graph_builder.py` | Legacy" not in text
        assert "Legacy compatibility `drug_target_graph`" not in text
        assert "`graph_builder.py` and `super_graph.py` retain" not in text
        assert "`drug_target_graph.ainvoke(...)`" not in text
        assert "super_graph.py" in text
        assert "Legacy compatibility super-graph" in text

    assert "`run_report_writer_only.py` is diagnostic-only." in reference
    assert "`run_report_writer_only.py` only diagnoses the\ncanonical writer against existing evidence." in stage_guide
    assert "returned payload" not in reference
    assert "no longer exposes `build_evidence_summary`" in reference
    assert "verify its absence in the JSONL trace" in reference

    for text in (reference, stage_guide):
        assert "evidence_assessor -> hypothesis_writer -> report_writer" in text
        assert "valid existing handoff" in text
        assert "--skip-evidence-assessor" in text

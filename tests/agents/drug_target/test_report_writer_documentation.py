"""Current report-writer docs must distinguish guarded and legacy entrypoints."""

from pathlib import Path


REFERENCE = Path("docs/drugtarget/drug_target_agent_reference.md")
STAGE_GUIDE = Path("docs/drugtarget/drug_target_stage_guide.md")


def test_reference_documents_native_ollama_resume_profile() -> None:
    text = REFERENCE.read_text(encoding="utf-8")

    assert "  --provider ollama \\\n" in text
    assert "  --provider ollama-openai \\\n" in text
    assert "OLLAMA_REASONING=false" in text
    assert "OLLAMA_NUM_PREDICT=4096" in text
    assert "--heartbeat-seconds 15" in text


def test_docs_define_native_qwen_publication_success_profile() -> None:
    for path in (REFERENCE, STAGE_GUIDE):
        text = path.read_text(encoding="utf-8")
        assert "OLLAMA_NUM_PREDICT=4096" in text
        assert "qwen3.5:122b" in text
        assert "OLLAMA_REASONING=false" in text
        assert "evidence/hypothesis_report.json" in text
        assert "report_sections.json" in text
        assert "drug.md" in text
        assert "drug_report_validation_final.json" in text
        assert 'publication.status: "passed"' in text
        assert "HYPOTHESIS_REPORT_MISSING" in text
        assert "non-Ollama coordinator paths only" in text
        assert "native Ollama/Qwen instead uses its separate per-unit initial response" in text
        assert "writer's bounded repair path" in text


def test_docs_describe_ollama_gene_card_contract() -> None:
    for path in (REFERENCE, STAGE_GUIDE):
        text = path.read_text(encoding="utf-8")
        assert "gene-card" in text
        assert "4 final hypotheses" in text
        assert "assessment_results.json" in text
        assert "ot_<GENE>.json" in text
        assert "stage3_<GENE>.json" in text
        assert "interest-cell-intrinsic Stage 1" in text

    reference = REFERENCE.read_text(encoding="utf-8")
    assert "Qwen-authored canonical hypotheses" not in reference
    assert "Python owns the canonical Section" in reference


def test_docs_describe_bounded_ollama_report_sections() -> None:
    for path in (REFERENCE, STAGE_GUIDE):
        text = path.read_text(encoding="utf-8")
        assert "Python still selects all evidence, FEATURED genes," in text
        assert "L-R pairs, scores, and layout." in text
        assert "four labelled hypothesis" in text
        assert "optional one-sentence Section 3 follow-ups" in text
        assert "two Section 5" in text
        assert "three repairs" in text
        assert "evidence/llm_enrichment_audit.json" in text
        assert "DrugReportGuardrailMiddleware" in text
        assert "production_save_report_sections_tool" in text
        assert "Python selects supporting sources" in text
        assert "Section 5 only" not in text
        assert "card is retried once" not in text
        assert "Invalid prose is retried once" not in text


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
        assert "evidence_assessor -> report_writer" not in text
        assert 'WORKFLOW_ORDER = ["evidence_assessor", "report_writer"]' not in text
        assert 'WORKFLOW_ORDER = ["evidence_assessor", "hypothesis_writer", "report_writer"]' in text

    assert "guarded 2-subagent" not in reference
    assert "Guarded 2-Subagent" not in stage_guide
    assert "Allows only evidence_assessor/report_writer" not in reference
    assert "Allows only evidence_assessor, hypothesis_writer, and report_writer" not in reference
    assert "The top-level task allowlist permits exactly these three subagents" not in stage_guide
    assert "REPORT_PIPELINE_COMPLETE" not in reference


def test_docs_describe_code_enforced_guarded_phase_order() -> None:
    for path in (REFERENCE, STAGE_GUIDE):
        text = path.read_text(encoding="utf-8")
        assert "prepare -> validate_evidence -> hypothesis_writer" in text
        assert "validate_hypothesis -> report_writer" in text
        assert "report_writer is never invoked without a fresh valid hypothesis handoff" in text
        assert "root LLM does not schedule guarded production phases" in text
        assert "root LLM does not schedule guarded production retries" in text

    reference = REFERENCE.read_text(encoding="utf-8")
    assert (
        "evidence_assessor -> hypothesis_writer -> report_writer -> "
        "DrugReportGuardrailMiddleware -> guarded publication"
    ) not in reference


def test_docs_keep_legacy_and_diagnostic_paths_outside_production() -> None:
    reference = REFERENCE.read_text(encoding="utf-8")
    assert "legacy_hypothesis remains prompt-driven compatibility only" in reference
    assert "run_report_writer_only.py remains diagnostic-only" in reference

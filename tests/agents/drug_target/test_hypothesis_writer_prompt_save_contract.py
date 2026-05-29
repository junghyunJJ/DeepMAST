from src.agents.drug_target.subagents import prompts


def test_hypothesis_writer_file_access_rules_name_save_hypothesis_report_as_primary() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT
    file_rules = text.split("## Execution Discipline", 1)[0]

    assert (
        "ALWAYS use `save_hypothesis_report(data_dir=data_dir, report=report)`"
        in file_rules
    )
    assert "NEVER use `write_file`" in file_rules
    assert "`save_evidence(data_dir, filename, data)`" not in file_rules
    assert "save_hypothesis_report(data_dir, hypothesis_data)" not in file_rules


def test_hypothesis_writer_final_save_step_marks_save_evidence_as_fallback_only() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT
    final_save = text.split("### Phase 5: Save Report", 1)[1]

    assert "`save_hypothesis_report(data_dir=data_dir, report=report)`" in final_save
    assert "Compatibility fallback only" in final_save
    assert (
        '`save_evidence(data_dir=data_dir, filename="hypothesis_report.json", data=report)`'
        in final_save
    )
    assert final_save.index(
        "`save_hypothesis_report(data_dir=data_dir, report=report)`"
    ) < final_save.index("Compatibility fallback only")
    assert "save_hypothesis_report(data_dir, hypothesis_data)" not in final_save


def test_hypothesis_writer_prompt_requires_evidence_vs_inference_wording() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "Evidence-vs-Inference Wording" in text
    assert "Direct evidence" in text
    assert "Hypothesis-level inference" in text
    assert "may`, `could`, or `test whether" in text
    assert "suggests" in text
    assert "therapeutic benefit" in text
    assert "restores fibrosis resolution" in text
    assert "drives disease" in text
    assert "Do not list anti-* antibodies" in text
    assert "known_drugs.json" in text
    assert "resolved_drugs.json" in text
    assert "stage3_<GENE>.json" in text
    assert "validation_approach as perturbation reagents" in text
    assert (
        "Genes or pathways not present in cited evidence may appear as mechanistic"
        in text
    )

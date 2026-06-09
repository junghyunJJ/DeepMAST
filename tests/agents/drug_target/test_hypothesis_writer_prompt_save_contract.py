from pathlib import Path

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
    assert "Recommendation-level inference" in text
    assert "may`, `could`, or `test whether" in text
    assert "suggests" in text
    assert "therapeutic benefit" in text
    assert "restores fibrosis resolution" in text
    assert "drives disease" in text
    assert "Do not list anti-* antibodies" in text
    assert "known_drugs.json" in text
    assert "resolved_drugs.json" in text
    assert "stage3_<GENE>.json" in text
    assert "Biological Grounding" in text
    assert "Target-Disease Support" in text
    assert "Actionability" in text
    assert "Interpretation Constraint" in text
    assert "Stage 2 OpenTargets" in text
    assert "target-disease support, not causal biology" in text
    assert "Stage 3" in text
    assert "actionability" in text
    assert "not biological causality" in text
    assert "validation_approach as perturbation reagents" in text
    assert (
        "Genes or pathways not present in cited evidence may appear as mechanistic"
        in text
    )
    assert "functional axis" in text
    assert "major source" in text
    assert "synergistic" in text
    assert "Not yet established:" in text
    assert "dysregulation via" in text
    assert "blockade for reducing" in text
    assert "barrier dysfunction" in text
    assert "prioritizes" in text
    assert "nominates" in text
    assert "spatial-niche follow-up candidate" in text
    assert "cross-cell candidate" in text
    assert "test whether ... changes" in text
    assert "secondary Stage 1 framing evidence table" in text
    assert (
        "cite depleted Stage 1 pair files when the recommendation names that pair concept"
        in text
    )
    assert "not as AT2-intrinsic support" in text
    assert "stage1_pair_usage_guidance" in text
    assert "interest_cell_intrinsic_stage1_pair_files" in text
    assert "spatial_niche_only_stage1_pair_files" in text
    assert "spatial_niche_only_stage1_pair_files` are Stage 1 PASS files but must not be\n  cited" not in text
    assert "spatial_niche_only_stage1_pair_files` are Stage 1 PASS files but must not be\n  used as AT2-intrinsic" in text
    assert "cite these files only as secondary spatial-niche/cross-cell" in text
    assert "A file being in `eligible_stage1_pair_files` only means Stage 1 PASS" in text


def test_hypothesis_writer_prompt_prefers_conservative_perturbation_language() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT
    lower_intervention = text.split("- Lower intervention-success wording:", 1)[
        1
    ].split("- Do not list anti-*", 1)[0]

    assert "Avoid `therapeutic intervention candidate`" in lower_intervention
    assert (
        "prefer `perturbation/actionability follow-up candidate`"
        in lower_intervention
    )
    assert "Avoid `synergistic effects`" in lower_intervention
    assert "prefer `additive or non-additive effects`" in lower_intervention
    assert "Avoid statements such as `CD47 blockade alters fibrosis resolution`" in lower_intervention
    assert (
        "prefer `test whether CD47 perturbation changes macrophage-fibroblast readouts`"
        in lower_intervention
    )
    assert lower_intervention.index("Avoid `therapeutic intervention candidate`") < (
        lower_intervention.index("prefer `perturbation/actionability follow-up candidate`")
    )
    assert lower_intervention.index("Avoid `synergistic effects`") < (
        lower_intervention.index("prefer `additive or non-additive effects`")
    )


def test_hypothesis_writer_prompt_uses_neutral_fallback_readout_language() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT
    anti_overclaim = text.split("### Evidence-vs-Inference Wording (ANTI-OVERCLAIM)", 1)[
        1
    ].split("Rules:", 1)[0]

    assert 'wording such as "may reduce"' not in anti_overclaim
    assert "Use qualitative language: \"significant reduction\"" not in text
    assert "Use neutral qualitative language:" in text
    assert "`test whether ... changes`" in text
    assert "`measurable change`" in text
    assert "`directional change`" in text
    assert "`response relative to controls`" in text
    assert "`qualitative readout change`" in text
    assert "unsupported\ndirectional outcomes" in text


def test_hypothesis_writer_prompt_requires_layered_asymmetric_evidence_bounded_prose() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "moderately enriched, evidence-bounded prose" in text
    assert "three evidence layers" in text
    assert "Stage 1/pair-level evidence" in text
    assert "Stage 2/3/gene-level evidence" in text
    assert "unresolved follow-up boundary" in text
    assert "When only a subset of genes in a Stage 1 pair has cited Stage 2 or Stage 3 support" in text
    assert "write the recommendation as `<SUPPORTED_GENE>-anchored`" in text
    assert "coexpression-context partner" in text
    assert "Do not imply target-disease support, actionability, tractability, or druggability" in text
    assert "unless the exact gene-level file is present in `evidence_references`" in text


def test_hypothesis_writer_prompt_treats_unsupported_pair_partner_as_context_readout() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "asymmetric Stage 2/3 support" in text
    assert "supported gene is the perturbation or actionability anchor" in text
    assert "unsupported partner is a coexpression-context partner or readout" in text
    assert "Do not perturb or validate the unsupported partner as an independently supported target" in text
    assert "measure the unsupported partner only as a contextual readout" in text
    assert "ICAM1-centered perturbation" in text
    assert "EZR localization or coexpression as a secondary readout" in text
    assert "ICAM1+MUC1 perturbation" not in text


def test_hypothesis_writer_prompt_handles_grounding_rejections() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "hypothesis_grounding_violations" in text
    assert "claims direct pair axis 'A--B'" in text
    assert "target-cell-depleted Stage 1 Census evidence as interest-cell support" in text
    assert (
        "coexpression-depleted Stage 1 Census evidence as an interest-cell intrinsic same-cell claim"
        in text
    )
    assert "target-cell-depleted gene expression claim" in text
    assert "Do not build combinatorial axes from one hub's separate partners" in text
    assert "support the FEATURED gene with `stage3_<GENE>.json`/`ot_<GENE>.json`" in text
    assert "secondary spatial-niche/cross-cell evidence" in text
    assert "authoritative whitelist for interest-cell intrinsic Stage 1 usage" in text


def test_hypothesis_writer_prompt_requires_intrinsic_stage1_primary_contract() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "interest_cell_intrinsic_stage1_pair_files" in text
    assert "write Primary\n  AT2/Epithelial recommendations first from those files" in text
    assert "Secondary\n  Spatial-Niche recommendations" in text
    assert "At least one retained hypothesis must cite an\n  intrinsic Stage 1 file" in text
    assert (
        "frame AT2, alveolar epithelial, or pulmonary epithelial biology" in text
    )


def test_hypothesis_writer_prompt_separates_secondary_spatial_niche_support() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "spatial_niche_only_stage1_pair_files" in text
    assert "secondary spatial-niche/cross-cell\n  framing evidence" in text
    assert "never cite depleted or\n  non-intrinsic pairs as AT2-intrinsic evidence" in text
    assert "Primary\n  AT2/Epithelial" in text
    assert "Secondary Spatial-Niche" in text


def test_hypothesis_writer_prompt_distinguishes_gene_level_only_from_spatial_niche() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "Gene-level/actionability-only follow-up recommendations" in text
    assert "No Stage 1/spatial grounding reference cited" in text
    assert "do not label it as spatial-niche" in text
    assert "gene-level follow-up candidate" in text
    assert "actionability follow-up candidate" in text
    assert "Only use `spatial-niche` when a Stage 1/spatial pair file is cited" in text


def test_hypothesis_writer_prompt_forbids_false_missing_stage1_support() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert (
        "Do not describe a pair as lacking passed Stage 1 support when the matching\n"
        "  `stage1_<GENE_A>--<GENE_B>.json` exists"
    ) in text
    assert "eligible_stage1_pair_files" in text
    assert "interest_cell_intrinsic_stage1_pair_files" in text
    assert "spatial_niche_only_stage1_pair_files" in text


def test_hypothesis_writer_prompt_requires_pre_save_repair_checklist() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "### Pre-save deterministic repair checklist" in text
    assert "### Phase 5: Save Report" in text
    assert text.index("### Pre-save deterministic repair checklist") < text.index(
        "### Phase 5: Save Report"
    )
    assert "Do not call save_hypothesis_report with the same payload after saved=false" in text
    assert "For every GENE_LEVEL_EVIDENCE_REFERENCE_MISSING error" in text
    assert "For every unsupported direct pair-axis error" in text
    assert "For every depleted Stage 1 Census error" in text
    assert "If the last rejection mentions a specific hypothesis index" in text


def test_hypothesis_skill_documents_rejection_sidecar_recovery() -> None:
    text = Path("skills/drug-target-hypothesis/SKILL.md").read_text()

    assert "### Phase 5.6: Last Rejection Sidecar" in text
    assert "hypothesis_report_last_rejection.json" in text
    assert (
        "The graph-level retry may surface this sidecar as HYPOTHESIS_LAST_SAVE_REJECTION"
        in text
    )
    assert "Repair the exact saved=false errors before saving again" in text
    assert "Do not repeat a rejected payload" in text


def test_hypothesis_skill_documents_asymmetric_pair_support_contract() -> None:
    text = Path("skills/drug-target-hypothesis/SKILL.md").read_text()

    assert "asymmetric Stage 2/3 support" in text
    assert "supported gene is the perturbation or actionability anchor" in text
    assert "unsupported partner is a coexpression-context partner or readout" in text
    assert "Do not treat the unsupported partner as independently druggable" in text


def test_hypothesis_skill_documents_gene_level_only_candidate_labeling() -> None:
    text = Path("skills/drug-target-hypothesis/SKILL.md").read_text()

    assert "Gene-level/actionability-only follow-up recommendations" in text
    assert "do not label it as spatial-niche" in text
    assert "Only use `spatial-niche` when a Stage 1/spatial pair file is cited" in text


def test_hypothesis_skill_matches_followup_recommendation_save_contract() -> None:
    text = Path("skills/drug-target-hypothesis/SKILL.md").read_text()
    example = text.split("### Example 1: Happy-path save flow", 1)[1].split(
        "### Example 2:",
        1,
    )[0]

    assert "evidence-backed follow-up recommendations" in text
    assert "conservative drug-target follow-up recommendations" in text
    assert "Keep 4-6 retained recommendations" in text
    assert "4-6 retained recommendations while covering every FEATURED gene" in text
    assert "If FEATURED coverage cannot be satisfied within 6 retained recommendations" in text
    assert "`max(4, len(FEATURED))`" not in text
    assert "Maintain all four thematic categories" in text
    assert "If `save_hypothesis_report` returns `saved: false`" in text
    assert "Do not proceed to `save_hypothesis_report`" in text
    assert "save_hypothesis_report(data_dir=data_dir, report=report)" in text
    assert "save_hypothesis_report(data_dir, hypothesis_data)" not in text
    assert "save_evidence(...)" not in text
    assert "save_hypothesis_report(data_dir=data_dir, report={" in example
    assert "save_evidence(data_dir, \"hypothesis_report.json\"" not in example

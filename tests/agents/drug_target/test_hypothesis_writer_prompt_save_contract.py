from pathlib import Path

from src.agents.drug_target.subagents import prompts


def _skill_text() -> str:
    return Path("skills/drug-target-hypothesis/SKILL.md").read_text()


def test_hypothesis_writer_prompt_names_primary_runtime_tools() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert 'load_evidence_files(data_dir=data_dir, scope="hypothesis")' in text
    assert "validate_evidence_references(data_dir, all_cited_filenames)" in text
    assert "save_hypothesis_report(data_dir=data_dir, report=report)" in text
    assert "save_evidence(data_dir" not in text
    assert "save_hypothesis_report(data_dir, hypothesis_data)" not in text
    assert "Do not use `read_file`, `write_file`, `ls`, grep" in text


def test_hypothesis_writer_default_matches_minimal_dth_required_contract() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT
    minimal_dth = prompts.render_hypothesis_writer_prompt(
        "operational_contract_minimal_plus_dth"
    )

    assert text == minimal_dth
    assert "production DTH-required operational contract" not in text


def test_hypothesis_writer_prompt_keeps_dth_as_only_required_skill() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert 'read_skill_file("skills/drug-target-hypothesis/SKILL.md")' in text
    assert "loaded skill guides may provide extra interpretation guidance" in text
    assert 'read_skill_file("skills/opentargets-database/SKILL.md")' not in text
    assert 'read_skill_file("skills/gwas-database/SKILL.md")' not in text
    assert 'read_skill_file("skills/chembl-database/SKILL.md")' not in text
    assert (
        'read_skill_file("skills/compare-census-gene-pair-by-cell-type/SKILL.md")'
        not in text
    )
    assert 'read_skill_file("skills/string-database/SKILL.md")' not in text


def test_hypothesis_writer_prompt_preserves_artifact_shape_and_coverage_contract() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "Generate 4-6 retained recommendations" in text
    assert "include every FEATURED gene at least once" in text
    for category in (
        "Mechanism of Action",
        "Therapeutic Strategy",
        "Cross-Target Interaction",
        "Novel Pathway",
    ):
        assert category in text

    for field in (
        '"disease": DISEASE',
        '"evidence_coverage_pct": <float>',
        '"hypotheses_generated": <int>',
        '"hypotheses_retained": <int>',
        '"hypotheses": [',
        '"gap_analysis": {',
        '"evidence_references": ["...json"]',
        '"biological_entities": {"genes": [], "pathways": [], "cell_types": [], "drugs": []}',
    ):
        assert field in text


def test_hypothesis_writer_prompt_preserves_minimal_grounding_rules() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    required_phrases = (
        "FEATURED gene list",
        "mechanical_save_gate_contract",
        "direct_pair_axes",
        "pair_axes_not_listed_policy",
        "Pre-Save Support Declarations",
        "direct_pair_axis_file",
        "cell_context_anchor",
        "allowed_direct_pair_axes",
        "matching passed Stage 1 pair file",
        "Do not cite failed Stage 1 files as positive evidence",
        "OpenTargets and Stage 3 files provide target support",
        "Put drug or compound names in `biological_entities.drugs` only when",
        "target-prioritization follow-up",
        "Use simple numeric scores between 0 and 1",
    )
    for phrase in required_phrases:
        assert phrase in text


def test_hypothesis_writer_prompt_preserves_bounded_repair_contract() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    required_phrases = (
        "If `save_hypothesis_report` returns `saved: false`",
        "never resend an identical rejected payload",
        "missing FEATURED genes",
        "unsupported pair-axis errors",
        "invalid references",
        "Stop after 3 save attempts",
    )
    for phrase in required_phrases:
        assert phrase in text


def test_hypothesis_writer_prompt_repairs_primary_intrinsic_coverage() -> None:
    from src.agents.drug_target.subagents.prompts import HYPOTHESIS_WRITER_PROMPT

    assert "PRIMARY_EPITHELIAL_INTRINSIC_COVERAGE_MISSING" in HYPOTHESIS_WRITER_PROMPT
    assert "interest_cell_intrinsic_stage1_pair_files" in HYPOTHESIS_WRITER_PROMPT
    assert "required_cell_context_anchor" in HYPOTHESIS_WRITER_PROMPT
    assert "Do not use a spatial-niche-only Stage 1 file" in HYPOTHESIS_WRITER_PROMPT


def test_hypothesis_writer_prompt_does_not_embed_dth_interpretation_rubric() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    forbidden_prompt_phrases = (
        "DTH quality signature",
        "target rationale",
        "claim boundary",
        "Interest-cell intrinsic pair",
        "Secondary spatial-niche or cross-cell",
        "Gene-level/actionability-only",
        "Evidence-vs-Inference Wording",
        "Quantitative Predictions",
        "UCB Scoring",
    )
    for phrase in forbidden_prompt_phrases:
        assert phrase not in text


def test_dth_skill_keeps_interpretation_and_repair_rubric() -> None:
    text = _skill_text()

    required_phrases = (
        "## Small-Model DTH Decision Card",
        "Choose exactly one support class for each recommendation",
        "Interest-cell intrinsic",
        "Secondary spatial-niche or cross-cell",
        "Gene-level/actionability-only",
        "DTH quality signature",
        "UCB Scoring and Filtering",
        "Unsupported direct pair axis",
        "topn_coverage.missing",
        "Stage 1 pair filenames may be ligand-receptor ordered",
        "Repair the exact saved=false errors before saving again",
    )
    for phrase in required_phrases:
        assert phrase in text


def test_hypothesis_skill_documents_rejection_sidecar_recovery() -> None:
    text = _skill_text()

    assert "### Phase 5.6: Last Rejection Sidecar" in text
    assert "hypothesis_report_last_rejection.json" in text
    assert (
        "The graph-level retry may surface this sidecar as HYPOTHESIS_LAST_SAVE_REJECTION"
        in text
    )
    assert "Stage 1 pair filenames may be ligand-receptor ordered" in text
    assert "cite the actual available filename returned by validation/load evidence" in text
    assert "If the rejection names an available reverse-order file" in text
    assert "cite that exact file or remove the direct pair-axis wording" in text
    assert "If the rejection names an available reverse-order matching file" in text
    assert "Repair the exact saved=false errors before saving again" in text
    assert "Do not repeat a rejected payload" in text


def test_hypothesis_skill_documents_asymmetric_pair_support_contract() -> None:
    text = _skill_text()

    assert "asymmetric Stage 2/3 support" in text
    assert "supported gene is the perturbation or actionability anchor" in text
    assert "unsupported partner is a coexpression-context partner or readout" in text
    assert "Do not treat the unsupported partner as independently druggable" in text


def test_hypothesis_skill_documents_gene_level_only_candidate_labeling() -> None:
    text = _skill_text()

    assert "Gene-level/actionability-only follow-up recommendations" in text
    assert "do not label it as spatial-niche" in text
    assert "Only use `spatial-niche` when a Stage 1/spatial pair file is cited" in text


def test_hypothesis_skill_matches_followup_recommendation_save_contract() -> None:
    text = _skill_text()
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

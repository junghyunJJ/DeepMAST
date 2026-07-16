"""Regression tests for hypothesis_writer skill activation prompt cues."""

from __future__ import annotations

from pathlib import Path

from src.agents.drug_target.subagents import prompts
from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS


def _extract_skill_interpretation_checkpoint(prompt: str) -> str:
    checkpoint_marker = "### Skill Interpretation Checkpoint"
    next_marker = "### Phase 1: Evidence Ingestion & Target Categorization"

    assert checkpoint_marker in prompt
    checkpoint = prompt.split(checkpoint_marker, 1)[1]
    assert next_marker in checkpoint
    return checkpoint.split(next_marker, 1)[0]


def test_hypothesis_writer_prompt_is_production_dth_required_contract() -> None:
    prompt = prompts.HYPOTHESIS_WRITER_PROMPT

    assert prompt == prompts.render_hypothesis_writer_prompt(
        "operational_contract_minimal_plus_dth"
    )
    assert 'read_skill_file("skills/drug-target-hypothesis/SKILL.md")' in prompt
    assert "Do not read any other skill guide in this condition." in prompt

    forbidden_forced_reads = (
        'read_skill_file("skills/opentargets-database/SKILL.md")',
        'read_skill_file("skills/gwas-database/SKILL.md")',
        'read_skill_file("skills/chembl-database/SKILL.md")',
        'read_skill_file("skills/compare-census-gene-pair-by-cell-type/SKILL.md")',
        'read_skill_file("skills/string-database/SKILL.md")',
    )
    for skill_path in forbidden_forced_reads:
        assert skill_path not in prompt


def test_hypothesis_writer_prompt_keeps_dth_interpretation_in_skill() -> None:
    prompt = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "loaded skill guides may provide extra interpretation guidance" in prompt
    assert "DTH quality signature" not in prompt
    assert "target rationale" not in prompt
    assert "claim boundary" not in prompt
    assert "Interest-cell intrinsic pair" not in prompt
    assert "Secondary spatial-niche or cross-cell" not in prompt
    assert "Gene-level/actionability-only" not in prompt


def test_hypothesis_writer_prompt_preserves_production_save_contract() -> None:
    prompt = prompts.HYPOTHESIS_WRITER_PROMPT

    required_guardrails = (
        'load_evidence_files(data_dir=data_dir, scope="hypothesis")',
        "validate_evidence_references(data_dir, all_cited_filenames)",
        "save_hypothesis_report(data_dir=data_dir, report=report)",
        "FEATURED gene list",
        "matching passed Stage 1 pair file",
        "Stop after 3 save attempts",
        "never resend an identical rejected payload",
        "Use simple numeric scores between 0 and 1",
    )
    for guardrail in required_guardrails:
        assert guardrail in prompt


def test_hypothesis_writer_prompt_is_disease_agnostic_and_not_modality_map() -> None:
    prompt = prompts.HYPOTHESIS_WRITER_PROMPT

    forbidden_phrases = (
        "Use this modality-to-skill map",
        "Primary AT2/Epithelial",
        "AT2-intrinsic",
        "pulmonary alveolar",
        "fibrosis resolution",
        "semantic_proxy",
        "Prolif Invasive Tumor",
    )
    for phrase in forbidden_phrases:
        assert phrase not in prompt

    assert "cell_context_anchor" in prompt
    assert "allowed_direct_pair_axes" in prompt
    assert "exact cell-context phrase required" in prompt


def test_progressive_disclosure_prompt_mode_removes_forced_skill_reads() -> None:
    prompt = prompts.render_hypothesis_writer_prompt("progressive_disclosure_only")

    forced_skill_paths = (
        'read_skill_file("skills/drug-target-hypothesis/SKILL.md")',
        'read_skill_file("skills/opentargets-database/SKILL.md")',
        'read_skill_file("skills/gwas-database/SKILL.md")',
        'read_skill_file("skills/chembl-database/SKILL.md")',
        'read_skill_file("skills/compare-census-gene-pair-by-cell-type/SKILL.md")',
        'read_skill_file("skills/string-database/SKILL.md")',
    )

    assert "Use progressive disclosure for skill guidance" in prompt
    assert "Available skills are provided by SkillsMiddleware" in prompt
    assert "Use this modality-to-skill map" not in prompt
    assert "### Phase 1: Evidence Ingestion & Target Categorization" in prompt
    for skill_path in forced_skill_paths:
        assert skill_path not in prompt


def test_dth_only_required_prompt_mode_requires_only_drug_target_skill() -> None:
    prompt = prompts.render_hypothesis_writer_prompt("dth_only_required")

    assert "Use DTH-only controlled skill activation" in prompt
    assert 'read_skill_file("skills/drug-target-hypothesis/SKILL.md")' in prompt
    assert 'read_skill_file("skills/opentargets-database/SKILL.md")' not in prompt
    assert 'read_skill_file("skills/gwas-database/SKILL.md")' not in prompt
    assert 'read_skill_file("skills/chembl-database/SKILL.md")' not in prompt
    assert (
        'read_skill_file("skills/compare-census-gene-pair-by-cell-type/SKILL.md")'
        not in prompt
    )
    assert 'read_skill_file("skills/string-database/SKILL.md")' not in prompt


def test_thin_basic_prompt_mode_has_no_forced_skill_reads() -> None:
    prompt = prompts.render_hypothesis_writer_prompt("thin_basic")

    assert "Goal: create a valid `evidence/hypothesis_report.json`" in prompt
    assert "No skill guide is required in this control condition" in prompt
    assert 'read_skill_file("skills/drug-target-hypothesis/SKILL.md")' not in prompt
    assert 'read_skill_file("skills/opentargets-database/SKILL.md")' not in prompt
    assert "Use this modality-to-skill map" not in prompt
    assert "Call `save_hypothesis_report` exactly once" in prompt
    assert "graph-native hypothesis quality retry" in prompt
    assert "up to 3 total save attempts" not in prompt
    assert "UCB" not in prompt


def test_thin_basic_forced_read_prompt_modes_name_exact_skill_paths() -> None:
    dth_prompt = prompts.render_hypothesis_writer_prompt("thin_basic_dth_required")
    domain_prompt = prompts.render_hypothesis_writer_prompt(
        "thin_basic_domain4_required"
    )
    combined_prompt = prompts.render_hypothesis_writer_prompt(
        "thin_basic_dth_plus_domain4_required"
    )

    dth_path = 'read_skill_file("skills/drug-target-hypothesis/SKILL.md")'
    domain_paths = (
        'read_skill_file("skills/opentargets-database/SKILL.md")',
        'read_skill_file("skills/chembl-database/SKILL.md")',
        'read_skill_file("skills/compare-census-gene-pair-by-cell-type/SKILL.md")',
        'read_skill_file("skills/string-database/SKILL.md")',
    )

    assert dth_path in dth_prompt
    for path in domain_paths:
        assert path not in dth_prompt

    assert dth_path not in domain_prompt
    for path in domain_paths:
        assert path in domain_prompt

    assert dth_path in combined_prompt
    for path in domain_paths:
        assert path in combined_prompt


def test_dth_contrast_prompt_modes_differ_only_by_dth_forced_read() -> None:
    no_skill_prompt = prompts.render_hypothesis_writer_prompt(
        "dth_contrast_no_skill"
    )
    dth_prompt = prompts.render_hypothesis_writer_prompt(
        "dth_contrast_dth_required"
    )

    dth_path = 'read_skill_file("skills/drug-target-hypothesis/SKILL.md")'

    assert "DTH contrast benchmark" in no_skill_prompt
    assert "DTH contrast benchmark" in dth_prompt
    assert "## Evidence-Grounding Contract" in no_skill_prompt
    assert "## Evidence-Grounding Contract" in dth_prompt
    assert "No skill guide is available in this control condition" in no_skill_prompt
    assert dth_path not in no_skill_prompt
    assert dth_path in dth_prompt
    assert 'read_skill_file("skills/opentargets-database/SKILL.md")' not in dth_prompt
    assert "identical rejected payload" in no_skill_prompt
    assert "identical rejected payload" in dth_prompt
    assert "Stop after 3 save attempts" in no_skill_prompt
    assert "Stop after 3 save attempts" in dth_prompt
    assert "cell_context_anchor" in no_skill_prompt
    assert "cell_context_anchor" in dth_prompt
    assert "allowed_direct_pair_axes" in no_skill_prompt
    assert "allowed_direct_pair_axes" in dth_prompt
    assert "hypothesis_writer_contract.required_cell_context_anchor" in no_skill_prompt
    assert "hypothesis_writer_contract.allowed_direct_pair_axes" in dth_prompt
    assert "Do not create new direct axes" in no_skill_prompt
    assert "Do not create new direct axes" in dth_prompt
    assert "malignant cell" in no_skill_prompt
    assert "malignant cell" in dth_prompt


def test_operational_contract_prompt_modes_isolate_dth_skill_read() -> None:
    base_prompt = prompts.render_hypothesis_writer_prompt("operational_contract_only")
    dth_prompt = prompts.render_hypothesis_writer_prompt("operational_contract_plus_dth")

    dth_path = 'read_skill_file("skills/drug-target-hypothesis/SKILL.md")'

    assert "minimal operational contract for small-model DTH contrast" in base_prompt
    assert "minimal operational contract for small-model DTH contrast" in dth_prompt
    assert "No skill guide is available in this control condition" in base_prompt
    assert dth_path not in base_prompt
    assert dth_path in dth_prompt
    assert 'read_skill_file("skills/opentargets-database/SKILL.md")' not in dth_prompt

    shared_minimal_phrases = (
        'load_evidence_files(data_dir=data_dir, scope="hypothesis")',
        "No drug-target interpretation rubric is provided by this base prompt",
        "Generate 4-6 retained recommendations.",
        "`Mechanism of Action`, `Therapeutic Strategy`, `Cross-Target Interaction`,",
        "and `Novel Pathway`;",
        "Build a JSON-compatible object:",
    )
    for phrase in shared_minimal_phrases:
        assert phrase in base_prompt
        assert phrase in dth_prompt

    required_production_phrases = (
        "validate_evidence_references(data_dir, all_cited_filenames)",
        "save_hypothesis_report(data_dir=data_dir, report=report)",
        "include every FEATURED gene at least once in `biological_entities.genes`",
        "Stop after 3 save attempts",
        "Use simple numeric scores between 0 and 1.",
    )
    for phrase in required_production_phrases:
        assert phrase in base_prompt
        assert phrase in dth_prompt


def test_operational_contract_prompt_modes_reuse_minimal_success_surface() -> None:
    base_prompt = prompts.render_hypothesis_writer_prompt("operational_contract_only")
    dth_prompt = prompts.render_hypothesis_writer_prompt("operational_contract_plus_dth")
    minimal_base_prompt = prompts.render_hypothesis_writer_prompt(
        "operational_contract_minimal"
    )
    minimal_dth_prompt = prompts.render_hypothesis_writer_prompt(
        "operational_contract_minimal_plus_dth"
    )

    dth_path = 'read_skill_file("skills/drug-target-hypothesis/SKILL.md")'

    assert base_prompt == minimal_base_prompt
    assert dth_prompt == minimal_dth_prompt
    assert dth_path not in base_prompt
    assert dth_path in dth_prompt
    assert "No drug-target interpretation rubric is provided by this base prompt" in base_prompt
    assert "No drug-target interpretation rubric is provided by this base prompt" in dth_prompt


def test_operational_contract_plus_dth_bounds_forced_skill_read_to_once() -> None:
    base_prompt = prompts.render_hypothesis_writer_prompt("operational_contract_only")
    dth_prompt = prompts.render_hypothesis_writer_prompt("operational_contract_plus_dth")
    minimal_dth_prompt = prompts.render_hypothesis_writer_prompt(
        "operational_contract_minimal_plus_dth"
    )

    dth_path = 'read_skill_file("skills/drug-target-hypothesis/SKILL.md")'
    bounded_read_phrases = (
        "Call each listed skill guide exactly once in this hypothesis_writer run.",
        "Do not call read_skill_file again after the guide has been loaded.",
        "If a save attempt is rejected, repair from the loaded evidence and the already-read guide; do not re-read the skill guide.",
    )

    assert dth_prompt == minimal_dth_prompt
    assert dth_path in dth_prompt
    assert dth_path not in base_prompt
    for phrase in bounded_read_phrases:
        assert phrase in dth_prompt
        assert phrase not in base_prompt


def test_dth_contrast_prompts_delete_unsupported_pair_context() -> None:
    prompt_modes = (
        "dth_contrast_no_skill",
        "dth_contrast_dth_required",
    )

    for mode in prompt_modes:
        prompt = prompts.render_hypothesis_writer_prompt(mode)
        compact_prompt = " ".join(prompt.split())
        assert "Do not mention the unsupported partner" in compact_prompt
        assert "together with the supported gene" in compact_prompt
        assert "even as context or a readout" in compact_prompt
        assert "delete the unsupported partner gene" in compact_prompt
        assert 'Do not preserve rejected pairs as "context"' in compact_prompt


def test_operational_contract_prompts_do_not_embed_dth_interpretation_terms() -> None:
    prompt_modes = (
        "operational_contract_only",
        "operational_contract_plus_dth",
    )

    forbidden_interpretation_terms = (
        "DTH quality signature",
        "target rationale",
        "claim boundary",
        "Interest-cell intrinsic pair",
        "gene-level/actionability-only",
    )

    for mode in prompt_modes:
        prompt = prompts.render_hypothesis_writer_prompt(mode)
        compact_prompt = " ".join(prompt.split())
        for phrase in forbidden_interpretation_terms:
            assert phrase not in compact_prompt


def test_operational_contract_minimal_prompt_modes_keep_dth_interpretation_in_skill() -> None:
    base_prompt = prompts.render_hypothesis_writer_prompt("operational_contract_minimal")
    dth_prompt = prompts.render_hypothesis_writer_prompt(
        "operational_contract_minimal_plus_dth"
    )

    dth_path = 'read_skill_file("skills/drug-target-hypothesis/SKILL.md")'

    assert "minimal operational contract for small-model DTH contrast" in base_prompt
    assert "minimal operational contract for small-model DTH contrast" in dth_prompt
    assert "No skill guide is available in this control condition" in base_prompt
    assert dth_path not in base_prompt
    assert dth_path in dth_prompt
    assert 'read_skill_file("skills/opentargets-database/SKILL.md")' not in dth_prompt

    for prompt in (base_prompt, dth_prompt):
        assert "No drug-target interpretation rubric is provided by this base prompt" in prompt
        assert "Use this modality-to-skill map" not in prompt
        assert "FEATURED gene list" in prompt
        assert "matching Stage 1 pair file" in prompt
        assert "Stop after 3 save attempts" in prompt
        assert "DTH quality signature" not in prompt
        assert "target rationale" not in prompt
        assert "claim boundary" not in prompt
        assert "Interest-cell intrinsic pair" not in prompt
        assert "spatial-niche/cross-cell" not in prompt
        assert "gene-level/actionability-only" not in prompt


def test_operational_contract_prompts_require_structured_packet_without_dth_rubric() -> None:
    prompt_modes = (
        "operational_contract_only",
        "operational_contract_plus_dth",
        "operational_contract_minimal",
        "operational_contract_minimal_plus_dth",
    )
    required_phrases = (
        "mechanical_save_gate_contract",
        "featured_genes",
        "direct_pair_axes",
        "pair_axes_not_listed_policy",
        "Pre-Save Support Declarations",
        "support_class",
        "direct_pair_axis_file",
        "forbidden_as_direct_pair_claim",
    )
    required_raw_phrases = (
        "This declaration is a mechanical save-gate checklist, not a DTH interpretation rubric.",
    )
    forbidden_interpretation_terms = (
        "DTH quality signature",
        "target rationale",
        "claim boundary",
        "Interest-cell intrinsic pair",
        "Secondary spatial-niche or cross-cell",
        "gene-level/actionability-only",
    )

    for mode in prompt_modes:
        prompt = prompts.render_hypothesis_writer_prompt(mode)
        compact_prompt = " ".join(prompt.split())
        for phrase in required_phrases:
            assert phrase in compact_prompt
        for phrase in required_raw_phrases:
            assert phrase in prompt
        for phrase in forbidden_interpretation_terms:
            assert phrase not in compact_prompt


def test_drug_target_hypothesis_skill_is_disease_agnostic_for_operational_rules() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    skill_text = (repo_root / "skills/drug-target-hypothesis/SKILL.md").read_text(
        encoding="utf-8"
    )

    forbidden_operational_phrases = (
        "Primary epithelial/AT2-intrinsic",
        "Primary AT2/Epithelial",
        "AT2-intrinsic",
        "non-AT2",
        "Transitional AT2",
        "pulmonary/alveolar epithelial",
        "fibrosis resolution",
        "macrophage-fibroblast",
    )
    for phrase in forbidden_operational_phrases:
        assert phrase not in skill_text

    assert "primary interest-cell intrinsic support" in skill_text
    assert "original interest cell label or resolved Census cell type" in skill_text
    assert "cell_context_anchor" in skill_text
    assert "allowed_direct_pair_axes" in skill_text
    assert "hypothesis_writer_contract.required_cell_context_anchor" in skill_text
    assert "hypothesis_writer_contract.allowed_direct_pair_axes" in skill_text
    assert "do not claim Census validated lost state" in skill_text
    assert "canonical_existing=none" in skill_text


def test_drug_target_hypothesis_skill_has_small_model_decision_card() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    skill_text = (repo_root / "skills/drug-target-hypothesis/SKILL.md").read_text(
        encoding="utf-8"
    )

    required_phrases = (
        "## Small-Model DTH Decision Card",
        "Use this card before reading the longer workflow",
        "Choose exactly one support class for each recommendation",
        "Interest-cell intrinsic",
        "Secondary spatial-niche or cross-cell",
        "Gene-level/actionability-only",
        "DTH quality signature",
        "Unsupported direct pair axis",
        "topn_coverage.missing",
    )
    for phrase in required_phrases:
        assert phrase in skill_text


def test_drug_target_hypothesis_skill_uses_structured_packet_for_quality_signature() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    skill_text = (repo_root / "skills/drug-target-hypothesis/SKILL.md").read_text(
        encoding="utf-8"
    )

    required_phrases = (
        "mechanical_save_gate_contract",
        "direct_pair_axes",
        "featured_genes",
        "support_class",
        "direct_pair_axis_file",
        "Use the packet to avoid invalid claims, then use this skill to make the retained recommendations better.",
        "The base prompt handles mechanical survival; this skill handles interpretation quality.",
    )
    for phrase in required_phrases:
        assert phrase in skill_text


def test_get_subagents_can_render_progressive_disclosure_prompt_mode() -> None:
    from src.agents.drug_target.subagents.configs import get_legacy_subagents

    subagents = get_legacy_subagents(
        hypothesis_writer_prompt_mode="progressive_disclosure_only"
    )
    hypothesis_writer = next(
        subagent for subagent in subagents if subagent["name"] == "hypothesis_writer"
    )
    prompt = hypothesis_writer["system_prompt"]

    assert "Use progressive disclosure for skill guidance" in prompt
    assert "Use this modality-to-skill map" not in prompt
    assert 'read_skill_file("skills/opentargets-database/SKILL.md")' not in prompt


def test_get_subagents_enforces_native_retry_only_for_thin_prompt_modes() -> None:
    from src.agents.drug_target.middleware import HypothesisRetryLoopMiddleware
    from src.agents.drug_target.subagents.configs import get_legacy_subagents

    subagents = get_legacy_subagents(hypothesis_writer_prompt_mode="thin_basic")
    hypothesis_writer = next(
        subagent for subagent in subagents if subagent["name"] == "hypothesis_writer"
    )

    retry_middleware = next(
        middleware
        for middleware in hypothesis_writer["middleware"]
        if isinstance(middleware, HypothesisRetryLoopMiddleware)
    )
    assert retry_middleware._stop_after_first_save is True

    subagents = get_legacy_subagents(hypothesis_writer_prompt_mode="dth_contrast_no_skill")
    hypothesis_writer = next(
        subagent for subagent in subagents if subagent["name"] == "hypothesis_writer"
    )
    retry_middleware = next(
        middleware
        for middleware in hypothesis_writer["middleware"]
        if isinstance(middleware, HypothesisRetryLoopMiddleware)
    )
    assert retry_middleware._stop_after_first_save is False
    assert retry_middleware._max_hypothesis_save_attempts == 3

    subagents = get_legacy_subagents(hypothesis_writer_prompt_mode="operational_contract_only")
    hypothesis_writer = next(
        subagent for subagent in subagents if subagent["name"] == "hypothesis_writer"
    )
    retry_middleware = next(
        middleware
        for middleware in hypothesis_writer["middleware"]
        if isinstance(middleware, HypothesisRetryLoopMiddleware)
    )
    assert retry_middleware._stop_after_first_save is False
    assert retry_middleware._max_hypothesis_save_attempts == 3
    assert retry_middleware._single_read_skill_paths == ()

    subagents = get_legacy_subagents(
        hypothesis_writer_prompt_mode="operational_contract_plus_dth"
    )
    hypothesis_writer = next(
        subagent for subagent in subagents if subagent["name"] == "hypothesis_writer"
    )
    retry_middleware = next(
        middleware
        for middleware in hypothesis_writer["middleware"]
        if isinstance(middleware, HypothesisRetryLoopMiddleware)
    )
    assert retry_middleware._single_read_skill_paths == (
        "skills/drug-target-hypothesis/SKILL.md",
    )

    subagents = get_legacy_subagents(
        hypothesis_writer_prompt_mode="operational_contract_minimal"
    )
    hypothesis_writer = next(
        subagent for subagent in subagents if subagent["name"] == "hypothesis_writer"
    )
    retry_middleware = next(
        middleware
        for middleware in hypothesis_writer["middleware"]
        if isinstance(middleware, HypothesisRetryLoopMiddleware)
    )
    assert retry_middleware._stop_after_first_save is False
    assert retry_middleware._max_hypothesis_save_attempts == 3

    subagents = get_legacy_subagents(
        hypothesis_writer_prompt_mode="operational_contract_minimal_plus_dth"
    )
    hypothesis_writer = next(
        subagent for subagent in subagents if subagent["name"] == "hypothesis_writer"
    )
    retry_middleware = next(
        middleware
        for middleware in hypothesis_writer["middleware"]
        if isinstance(middleware, HypothesisRetryLoopMiddleware)
    )
    assert retry_middleware._single_read_skill_paths == (
        "skills/drug-target-hypothesis/SKILL.md",
    )


def test_progressive_disclosure_with_modality_map_keeps_soft_routing() -> None:
    prompt = prompts.render_hypothesis_writer_prompt(
        "progressive_disclosure_with_modality_map"
    )
    checkpoint = _extract_skill_interpretation_checkpoint(prompt)

    assert "Use progressive disclosure with modality-based skill routing" in prompt
    assert "Read the full core hypothesis-writing skill guide first" not in prompt
    assert "The core hypothesis-writing guide remains required" not in prompt
    assert 'read_skill_file("skills/drug-target-hypothesis/SKILL.md")' not in checkpoint
    assert "Use this modality-to-skill map" in checkpoint
    assert 'read_skill_file("skills/opentargets-database/SKILL.md")' in checkpoint
    assert 'read_skill_file("skills/chembl-database/SKILL.md")' in checkpoint
    assert (
        'read_skill_file("skills/compare-census-gene-pair-by-cell-type/SKILL.md")'
        in checkpoint
    )
    assert 'read_skill_file("skills/string-database/SKILL.md")' in checkpoint


def test_get_subagents_can_render_progressive_disclosure_with_modality_map() -> None:
    from src.agents.drug_target.subagents.configs import get_legacy_subagents

    subagents = get_legacy_subagents(
        hypothesis_writer_prompt_mode="progressive_disclosure_with_modality_map"
    )
    hypothesis_writer = next(
        subagent for subagent in subagents if subagent["name"] == "hypothesis_writer"
    )
    prompt = hypothesis_writer["system_prompt"]

    assert "Use progressive disclosure with modality-based skill routing" in prompt
    assert "Use this modality-to-skill map" in prompt
    assert 'read_skill_file("skills/drug-target-hypothesis/SKILL.md")' not in prompt
    assert 'read_skill_file("skills/opentargets-database/SKILL.md")' in prompt


def test_progressive_disclosure_governor_does_not_hard_require_drug_target_skill() -> None:
    from src.agents.drug_target.subagents.configs import get_legacy_subagents
    from src.agents.shared.skill_activation_governor import SkillActivationGovernor

    allowed_names = (
        "drug-target-hypothesis",
        "opentargets-database",
        "chembl-database",
    )
    registry = {
        name: f"skills/{name}"
        for name in allowed_names
    }
    subagents = get_legacy_subagents(
        skills_dir="skills",
        subagent_skill_names={"hypothesis_writer": allowed_names},
        subagent_skill_registries={"hypothesis_writer": registry},
        skill_activation_mode="middleware_plus_governor",
        hypothesis_writer_prompt_mode="progressive_disclosure_only",
    )
    hypothesis_writer = next(
        subagent for subagent in subagents if subagent["name"] == "hypothesis_writer"
    )
    governor = next(
        middleware
        for middleware in hypothesis_writer["middleware"]
        if isinstance(middleware, SkillActivationGovernor)
    )

    assert governor.hard_required_skill_names == ()
    assert governor.required_skill_names == ()
    assert governor.candidate_skill_names == allowed_names


def test_progressive_disclosure_with_modality_map_governor_keeps_drug_target_candidate() -> None:
    from src.agents.drug_target.subagents.configs import get_legacy_subagents
    from src.agents.shared.skill_activation_governor import SkillActivationGovernor

    allowed_names = (
        "drug-target-hypothesis",
        "opentargets-database",
        "chembl-database",
    )
    registry = {
        name: f"skills/{name}"
        for name in allowed_names
    }
    subagents = get_legacy_subagents(
        skills_dir="skills",
        subagent_skill_names={"hypothesis_writer": allowed_names},
        subagent_skill_registries={"hypothesis_writer": registry},
        skill_activation_mode="middleware_plus_governor",
        hypothesis_writer_prompt_mode="progressive_disclosure_with_modality_map",
    )
    hypothesis_writer = next(
        subagent for subagent in subagents if subagent["name"] == "hypothesis_writer"
    )
    governor = next(
        middleware
        for middleware in hypothesis_writer["middleware"]
        if isinstance(middleware, SkillActivationGovernor)
    )

    assert governor.hard_required_skill_names == ()
    assert governor.required_skill_names == ()
    assert governor.candidate_skill_names == allowed_names


def test_hypothesis_writer_still_has_no_database_query_tools() -> None:
    tools = SUBAGENT_CONFIGS["hypothesis_writer"]["tools"]
    names = {tool.name for tool in tools}

    forbidden_db_tools = {
        "query_chembl_target_profile",
        "search_literature_dynamic",
        "query_stage2_gene_panel",
        "query_cellxgene_lr_context",
        "query_kegg_pathways",
        "query_reactome_pathways",
        "query_string_ppi_pair",
    }

    assert names.isdisjoint(forbidden_db_tools)

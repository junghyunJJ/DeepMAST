"""Regression tests for hypothesis_writer skill activation prompt cues."""

from __future__ import annotations

import re

from src.agents.drug_target.subagents import prompts
from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS


def _extract_skill_interpretation_checkpoint(prompt: str) -> str:
    checkpoint_marker = "### Skill Interpretation Checkpoint"
    next_marker = "### Phase 1: Evidence Ingestion & Target Categorization"

    assert checkpoint_marker in prompt
    checkpoint = prompt.split(checkpoint_marker, 1)[1]
    assert next_marker in checkpoint
    return checkpoint.split(next_marker, 1)[0]


def _assert_line_maps_terms_to_skill(
    section: str, terms: tuple[str, ...], skill_path: str
) -> None:
    pattern = re.compile(
        rf"(?m)^[^\n]*{re.escape(terms[0])}[^\n]*(?:\n[^\n]*){{0,4}}?"
        rf"{re.escape(skill_path)}"
    )
    match = pattern.search(section)
    assert match is not None

    chunk = match.group(0)
    for term in terms:
        assert term in chunk
    assert skill_path in chunk


def test_hypothesis_writer_prompt_has_skill_interpretation_checkpoint() -> None:
    prompt = prompts.HYPOTHESIS_WRITER_PROMPT
    checkpoint = _extract_skill_interpretation_checkpoint(prompt)

    assert "After `load_evidence_files(data_dir, scope=\"hypothesis\")` returns" in checkpoint
    assert "read the additional skill guides that match the loaded evidence modalities" in checkpoint


def test_hypothesis_writer_prompt_lists_expanded6_skill_paths() -> None:
    prompt = prompts.HYPOTHESIS_WRITER_PROMPT
    checkpoint = _extract_skill_interpretation_checkpoint(prompt)

    required_skill_paths = (
        'read_skill_file("skills/drug-target-hypothesis/SKILL.md")',
        'read_skill_file("skills/opentargets-database/SKILL.md")',
        'read_skill_file("skills/gwas-database/SKILL.md")',
        'read_skill_file("skills/chembl-database/SKILL.md")',
        'read_skill_file("skills/compare-census-gene-pair-by-cell-type/SKILL.md")',
        'read_skill_file("skills/string-database/SKILL.md")',
    )

    for skill_path in required_skill_paths:
        assert skill_path in checkpoint


def test_hypothesis_writer_prompt_maps_modalities_to_skill_guides() -> None:
    prompt = prompts.HYPOTHESIS_WRITER_PROMPT
    checkpoint = _extract_skill_interpretation_checkpoint(prompt)

    modality_skill_mappings = (
        (("OpenTargets", "target-disease"), "skills/opentargets-database/SKILL.md"),
        (("GWAS", "genetic association"), "skills/gwas-database/SKILL.md"),
        (("ChEMBL", "matched compounds"), "skills/chembl-database/SKILL.md"),
        (
            ("Census", "target-vs-rest", "coexpression"),
            "skills/compare-census-gene-pair-by-cell-type/SKILL.md",
        ),
        (
            ("STRING", "PPI", "network convergence"),
            "skills/string-database/SKILL.md",
        ),
    )

    for terms, skill_path in modality_skill_mappings:
        _assert_line_maps_terms_to_skill(checkpoint, terms, skill_path)


def test_hypothesis_writer_prompt_bounds_skill_use_to_loaded_evidence() -> None:
    prompt = prompts.HYPOTHESIS_WRITER_PROMPT
    checkpoint = _extract_skill_interpretation_checkpoint(prompt)

    required_guardrails = (
        "Use these additional skills as interpretation guides for already-loaded evidence only.",
        "Do not run new external database queries unless the parent task explicitly asks for evidence augmentation.",
        "Do not cite facts, genes, drugs, variants, pathways, cell types, or interactions that are not present in the loaded evidence files.",
    )

    for guardrail in required_guardrails:
        assert guardrail in checkpoint


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

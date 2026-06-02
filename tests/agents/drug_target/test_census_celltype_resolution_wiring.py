from __future__ import annotations

from src.agents.drug_target.subagents import configs, prompts
from src.agents.drug_target.tools import resolve_census_celltypes


def _tool_names(subagent: dict) -> set[str]:
    return {getattr(tool, "name", "") for tool in subagent["tools"]}


def test_resolve_census_celltypes_is_reexported_tool() -> None:
    assert getattr(resolve_census_celltypes, "name", "") == "resolve_census_celltypes"


def test_evidence_assessor_exposes_resolver_tool() -> None:
    subagents = configs.get_subagents(data_dir="/tmp/nonexistent", disease="pulmonary fibrosis")
    evidence = next(item for item in subagents if item["name"] == "evidence_assessor")

    assert "resolve_census_celltypes" in _tool_names(evidence)


def test_census_disable_strips_census_and_cellxgene_tools() -> None:
    subagents = configs.get_subagents(
        data_dir="/tmp/nonexistent",
        disease="pulmonary fibrosis",
        enable_census=False,
    )
    evidence = next(item for item in subagents if item["name"] == "evidence_assessor")

    assert {
        "query_cellxgene_lr_context",
        "list_census_diseases",
        "list_census_cell_types",
        "resolve_census_celltypes",
        "run_compare_census_lr_pair",
        "run_batch_census_lr_pairs",
    }.isdisjoint(_tool_names(evidence))


def test_evidence_prompt_requires_resolver_and_celltype_resolution_artifact() -> None:
    text = prompts.EVIDENCE_ASSESSOR_PROMPT

    assert "resolve_census_celltypes" in text
    assert "celltype_resolution.json" in text
    assert "primary_resolved_celltype" in text
    assert "Use the first resolved interest cell type as the Stage 1 target" in text
    assert "Do not use `list_census_cell_types` for matching" in text

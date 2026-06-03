from __future__ import annotations

from src.agents.drug_target.subagents import configs, prompts
from src.agents.drug_target.tools import (
    apply_semantic_celltype_proxy,
    resolve_census_celltypes,
    run_stage1_batch,
    search_census_celltype_options,
)


def _tool_names(subagent: dict) -> set[str]:
    return {getattr(tool, "name", "") for tool in subagent["tools"]}


def test_resolve_census_celltypes_is_reexported_tool() -> None:
    assert getattr(resolve_census_celltypes, "name", "") == "resolve_census_celltypes"


def test_apply_semantic_celltype_proxy_is_reexported_tool() -> None:
    assert getattr(apply_semantic_celltype_proxy, "name", "") == "apply_semantic_celltype_proxy"


def test_search_census_celltype_options_is_reexported_tool() -> None:
    assert getattr(search_census_celltype_options, "name", "") == "search_census_celltype_options"


def test_evidence_assessor_exposes_resolver_tool() -> None:
    subagents = configs.get_subagents(data_dir="/tmp/nonexistent", disease="pulmonary fibrosis")
    evidence = next(item for item in subagents if item["name"] == "evidence_assessor")

    assert "resolve_census_celltypes" in _tool_names(evidence)
    assert "apply_semantic_celltype_proxy" in _tool_names(evidence)
    assert "search_census_celltype_options" in _tool_names(evidence)


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
        "apply_semantic_celltype_proxy",
        "search_census_celltype_options",
        "run_compare_census_lr_pair",
        "run_batch_census_lr_pairs",
    }.isdisjoint(_tool_names(evidence))


def test_census_disabled_stage1_tool_forces_enable_census_false(monkeypatch) -> None:
    def capture_stage1_payload(**kwargs):
        return kwargs

    monkeypatch.setattr(run_stage1_batch, "func", capture_stage1_payload)

    subagents = configs.get_subagents(
        data_dir="/tmp/nonexistent",
        disease="pulmonary fibrosis",
        enable_census=False,
    )
    evidence = next(item for item in subagents if item["name"] == "evidence_assessor")
    disabled_stage1 = next(
        tool for tool in evidence["tools"] if getattr(tool, "name", "") == "run_stage1_batch"
    )

    assert disabled_stage1.name == "run_stage1_batch"

    omitted_payload = disabled_stage1.invoke(
        {
            "data_dir": "/tmp/nonexistent",
            "disease": "pulmonary fibrosis",
            "target_cell_type": "pulmonary alveolar type 2 cell",
        }
    )
    explicit_true_payload = disabled_stage1.invoke(
        {
            "data_dir": "/tmp/nonexistent",
            "disease": "pulmonary fibrosis",
            "target_cell_type": "pulmonary alveolar type 2 cell",
            "enable_census": True,
        }
    )

    assert omitted_payload["enable_census"] is False
    assert explicit_true_payload["enable_census"] is False


def test_evidence_prompt_requires_resolver_and_celltype_resolution_artifact() -> None:
    text = prompts.EVIDENCE_ASSESSOR_PROMPT

    assert "resolve_census_celltypes" in text
    assert "resolve_census_celltypes(interest_celltypes=interest_celltypes, disease=CENSUS_DISEASE, data_dir=DATA_DIR)" in text
    assert "available_celltype_preview" in text
    assert "census_celltype_options.json" in text
    assert "search_census_celltype_options" in text
    assert "apply_semantic_celltype_proxy" in text
    assert "Do not hard-code tumor or lineage vocabulary" in text
    assert "celltype_resolution.json" in text
    assert "primary_resolved_celltype" in text
    assert "executed == true" in text
    assert "errors == []" in text
    assert "stop before Census Stage 1" in text
    assert "Use the first resolved interest cell type as the Stage 1 target" in text
    assert "Do not use `list_census_cell_types` for matching" in text

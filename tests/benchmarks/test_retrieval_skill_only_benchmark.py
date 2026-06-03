from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from docs.benchmarks.harness_x_model.common import (
    _ADVANCED_KWARG_LEAKAGE_TERMS,
    _searcher_tools,
    compose_searcher_prompt,
)
from scripts.benchmarks import run_cci_searcher_skill_onoff_benchmark as runner


def _search_tool_properties(*, skill_on: bool) -> dict:
    tools = _searcher_tools(skill_on=skill_on, benchmark_mode="retrieval_only")
    search_tool = next(
        tool for tool in tools if getattr(tool, "name", "") == "search_literature_dynamic"
    )
    return search_tool.args_schema.model_json_schema()["properties"]


def test_retrieval_only_skill_on_mentions_raw_only_and_forbids_handoff() -> None:
    prompt = compose_searcher_prompt(
        skill_on=True,
        benchmark_mode="retrieval_only",
    )

    assert "SEARCHER retrieval-only benchmark mode" in prompt
    assert "papers_raw.json" in prompt
    assert "`output_path=\"papers_raw.json\"`" in prompt
    assert "`data_dir=data_path.strip()`" in prompt
    assert "Advanced Retrieval Kwargs" in prompt
    assert "enable_lr_pair_queries=True" in prompt
    assert "coverage_weighted_sort=True" in prompt
    assert "Do not call `create_literature_handoff`" in prompt
    assert "Do not write `/citation_candidates.json`" in prompt
    assert "full production retrieval pipeline" not in prompt
    assert "production SEARCHER behavior" not in prompt
    assert "Call `create_literature_handoff`" not in prompt
    assert "It writes `/citation_candidates.json`" not in prompt
    assert "It writes filtered `/papers.json`" not in prompt
    assert "create filtered `/papers.json`" not in prompt
    assert "create_literature_handoff(" not in prompt
    assert "Default handoff cap is `40`" not in prompt


def test_retrieval_only_skill_on_preserves_advanced_kwarg_hint() -> None:
    prompt = compose_searcher_prompt(
        skill_on=True,
        benchmark_mode="retrieval_only",
    )

    assert "Advanced Retrieval Kwargs" in prompt
    assert "enable_lr_pair_queries=True" in prompt
    assert "coverage_weighted_sort=True" in prompt


def test_retrieval_only_skill_off_has_no_biomedical_skill_guidance() -> None:
    prompt = compose_searcher_prompt(
        skill_on=False,
        benchmark_mode="retrieval_only",
    )

    assert "biomedical-literature-search" not in prompt
    assert "SEARCHER retrieval-only benchmark mode" in prompt
    assert "Do not call `create_literature_handoff`" in prompt
    assert "Call `create_literature_handoff`" not in prompt
    assert "It writes `/citation_candidates.json`" not in prompt
    assert "It writes filtered `/papers.json`" not in prompt
    assert "create filtered `/papers.json`" not in prompt
    assert "Advanced Kwargs" not in prompt
    assert "Skill Activator" not in prompt
    assert "read_skill_file" not in prompt
    assert "pubmed-eutils-search" not in prompt
    assert "html-report-generator" not in prompt
    assert "enable_lr_pair_queries" not in prompt
    assert "coverage_weighted_sort" not in prompt


def test_retrieval_only_skill_off_has_no_advanced_kwarg_leakage() -> None:
    prompt = compose_searcher_prompt(
        skill_on=False,
        benchmark_mode="retrieval_only",
    )

    for term in _ADVANCED_KWARG_LEAKAGE_TERMS:
        assert term not in prompt


def test_retrieval_only_skill_off_hides_advanced_search_kwargs() -> None:
    properties = _search_tool_properties(skill_on=False)

    assert "enable_lr_pair_queries" not in properties
    assert "coverage_weighted_sort" not in properties


def test_retrieval_only_skill_on_exposes_advanced_search_kwargs() -> None:
    properties = _search_tool_properties(skill_on=True)

    assert "enable_lr_pair_queries" in properties
    assert "coverage_weighted_sort" in properties


def test_retrieval_only_recovery_rejects_papers_json_only(tmp_path) -> None:
    workspace = tmp_path / "trial"
    workspace.mkdir()
    (workspace / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "1"}]}),
        encoding="utf-8",
    )
    row = {
        "trial_workspace": str(workspace),
        "papers_path": str(workspace / "papers_raw.json"),
        "error": "papers_not_written",
    }

    recovered = runner._recover_papers_artifact(row, benchmark_mode="retrieval_only")

    assert recovered is False
    assert row["error"] == "papers_not_written"
    assert row.get("artifact_recovered") is not True


def test_retrieval_only_recovery_accepts_papers_raw_json(tmp_path) -> None:
    workspace = tmp_path / "trial"
    workspace.mkdir()
    raw_path = workspace / "papers_raw.json"
    raw_path.write_text(
        json.dumps({"papers": [{"pmid": "1"}, {"pmid": "2"}]}),
        encoding="utf-8",
    )
    row = {
        "trial_workspace": str(workspace),
        "papers_path": str(workspace / "missing" / "papers_raw.json"),
        "error": "papers_not_written",
    }

    recovered = runner._recover_papers_artifact(row, benchmark_mode="retrieval_only")

    assert recovered is True
    assert row["error"] == ""
    assert row["agent_error"] == "papers_not_written"
    assert row["artifact_recovered"] is True
    assert row["papers_path"] == str(raw_path)
    assert row["total_papers"] == 2


def test_content_utility_r_script_uses_clean_benchmark_a_csvs_not_old_rds() -> None:
    script = (
        PROJECT_ROOT
        / "docs"
        / "benchmarks"
        / "lr_retrieval_relevance"
        / "content_utility_manuscript_figures.R"
    ).read_text(encoding="utf-8")

    assert "fig2b_raw_bucket_composition.csv" in script
    assert "fig2c_selected_count.csv" in script
    assert "fig2d_overlap.csv" in script
    assert "readRDS" not in script
    assert "full_paper_relevance_v1" not in script

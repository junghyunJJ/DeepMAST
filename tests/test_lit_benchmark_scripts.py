"""Unit tests for literature reproducibility/benchmark helper scripts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_validate_case_rejects_missing_required_fields():
    from scripts.benchmarks.run_lit_benchmark import validate_case

    with pytest.raises(ValueError):
        validate_case({"case_id": "c1", "genes": ["CDH1"]})


def test_load_cases_reads_and_validates_json(tmp_path: Path):
    from scripts.benchmarks.run_lit_benchmark import load_cases

    payload = [
        {
            "case_id": "case-1",
            "genes": ["CDH1", "TGFB1"],
            "pathways": ["EMT"],
            "celltypes": ["Tumor"],
            "disease": "breast cancer",
            "notes": "smoke",
        }
    ]
    p = tmp_path / "cases.json"
    p.write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_cases(str(p))
    assert loaded[0]["case_id"] == "case-1"
    assert loaded[0]["genes"] == ["CDH1", "TGFB1"]


def test_extract_pmids_deduplicates_and_preserves_order():
    from scripts.benchmarks.run_lit_benchmark import extract_pmids

    papers = [
        {"pmid": "123"},
        {"pmid": 456},
        {"pmid": "123"},
        {"pmid": ""},
        {"title": "no pmid"},
    ]
    assert extract_pmids(papers) == ["123", "456"]


def test_jaccard_and_topk_overlap_helpers():
    from scripts.benchmarks.score_lit_benchmark import jaccard, top_k_overlap

    assert jaccard(["1", "2"], ["2", "3"]) == pytest.approx(1 / 3)
    assert top_k_overlap(["1", "2", "3"], ["2", "3", "4"], k=2) == pytest.approx(0.5)


def test_bootstrap_paired_ci_returns_interval():
    from scripts.benchmarks.score_lit_benchmark import bootstrap_paired_ci

    a = [0.6, 0.7, 0.8, 0.9, 0.75]
    b = [0.4, 0.45, 0.55, 0.6, 0.5]

    lo, hi, p_value = bootstrap_paired_ci(a, b, n_boot=2000, seed=7)
    assert lo <= hi
    assert 0 <= p_value <= 1
    assert hi > 0


def test_compute_coverage_pass_from_explicit_flag():
    from scripts.benchmarks.score_lit_benchmark import compute_coverage_pass

    record = {"coverage_sufficient": True}
    assert compute_coverage_pass(record) is True


def test_compute_coverage_pass_from_coverage_metrics():
    from scripts.benchmarks.score_lit_benchmark import compute_coverage_pass

    record = {
        "coverage": {
            "genes_coverage_pct": 61.0,
            "pathways_coverage_pct": 50.0,
            "total_papers": 18,
        }
    }
    assert compute_coverage_pass(record) is True


def test_compute_coverage_pass_fails_when_minimums_not_met():
    from scripts.benchmarks.score_lit_benchmark import compute_coverage_pass

    record = {
        "coverage": {
            "genes_coverage_pct": 59.9,
            "pathways_coverage_pct": 49.9,
            "total_papers": 14,
        }
    }
    assert compute_coverage_pass(record) is False


def test_run_method_once_uses_tool_invoke(monkeypatch):
    from scripts.benchmarks import run_lit_benchmark as runner

    class DummyTool:
        def __init__(self, payload):
            self.payload = payload
            self.called_with = None

        def invoke(self, params):
            self.called_with = params
            return self.payload

    dynamic_tool = DummyTool(
        {
            "papers": [{"pmid": "100", "title": "t", "abstract": "a"}],
            "coverage": {"genes_coverage_pct": 100, "pathways_coverage_pct": 100, "total_papers": 1},
            "search_method": "search_literature_dynamic",
            "recommended_actions": [],
        }
    )
    lit_tool = DummyTool([{"pmid": "101", "title": "t2", "abstract": "a2"}])
    eutils_tool = DummyTool({"papers": [{"pmid": "102"}], "query_used": "x"})

    monkeypatch.setattr(runner, "search_literature_dynamic", dynamic_tool)
    monkeypatch.setattr(runner, "search_literature", lit_tool)
    monkeypatch.setattr(runner, "search_pubmed_advanced", eutils_tool)

    case = {
        "case_id": "c1",
        "genes": ["CDH1"],
        "pathways": ["EMT"],
        "celltypes": ["Tumor"],
        "disease": "breast cancer",
    }

    papers_d, cov_d, _, method_d, _ = runner._run_method_once(
        method="dynamic",
        case=case,
        max_results=5,
        max_iterations=1,
        rerank_mode="off",
    )
    assert method_d == "search_literature_dynamic"
    assert papers_d and cov_d
    assert dynamic_tool.called_with["genes"] == ["CDH1"]
    assert dynamic_tool.called_with["enforce_disease_match"] is True

    papers_dn, cov_dn, _, method_dn, _ = runner._run_method_once(
        method="dynamic_no_disease_filter",
        case=case,
        max_results=5,
        max_iterations=1,
        rerank_mode="off",
    )
    assert method_dn == "search_literature_dynamic"
    assert papers_dn and cov_dn
    assert dynamic_tool.called_with["enforce_disease_match"] is False

    papers_l, cov_l, _, method_l, _ = runner._run_method_once(
        method="baseline_lit",
        case=case,
        max_results=5,
        max_iterations=1,
        rerank_mode="off",
    )
    assert method_l == "search_literature"
    assert papers_l and cov_l["total_papers"] == 1
    assert lit_tool.called_with["disease"] == "breast cancer"

    papers_e, cov_e, query_e, method_e, _ = runner._run_method_once(
        method="baseline_eutils",
        case=case,
        max_results=5,
        max_iterations=1,
        rerank_mode="off",
    )
    assert method_e == "search_pubmed_advanced"
    assert papers_e and query_e == "x"
    assert cov_e["total_papers"] == 1


def test_arg_parser_accepts_dynamic_no_disease_filter():
    from scripts.benchmarks.run_lit_benchmark import _build_arg_parser

    parser = _build_arg_parser()
    args = parser.parse_args(["--methods", "dynamic_no_disease_filter"])
    assert args.methods == ["dynamic_no_disease_filter"]


def test_harness_enricher_uses_benchmark_local_pathway_fixture():
    from docs.benchmarks.harness_x_model import enrich_cases_string_kegg as enricher
    from src.agents.deep_interpreter.tools import literature

    deleted_symbol = "PATHWAY" + "_TO_GENES"
    assert not hasattr(literature, deleted_symbol)
    assert "mapk" in enricher.BENCHMARK_PATHWAY_GENE_FIXTURE
    assert enricher.kegg_hub_genes_for_case(["MAPK"])["MAPK1"] == pytest.approx(
        enricher.KEGG_FALLBACK_SCORE
    )


def test_extract_continuous_metrics_normalizes_ratios():
    from scripts.benchmarks.score_lit_benchmark import extract_continuous_metrics

    record = {
        "coverage": {
            "genes_coverage_pct": 0.82,     # ratio format
            "pathways_coverage_pct": 45.0,  # percent format
            "total_papers": 12,
        },
        "total_papers": 99,
    }

    metrics = extract_continuous_metrics(record)
    assert metrics["gene_coverage_pct"] == pytest.approx(82.0)
    assert metrics["pathway_coverage_pct"] == pytest.approx(45.0)
    assert metrics["coverage_composite_pct"] == pytest.approx(63.5)
    assert metrics["total_papers"] == pytest.approx(12.0)


def test_method_summary_includes_continuous_metrics():
    from scripts.benchmarks.score_lit_benchmark import _compute_method_summary

    records = [
        {
            "method": "dynamic",
            "case_id": "c1",
            "error": None,
            "coverage": {
                "genes_coverage_pct": 80.0,
                "pathways_coverage_pct": 60.0,
                "total_papers": 20,
            },
            "total_papers": 20,
            "latency_ms": 100.0,
            "pmids": ["1"],
            "papers": [{"title": "breast sample", "abstract": "breast"}],
            "input": {"disease": "breast cancer"},
        },
        {
            "method": "dynamic",
            "case_id": "c1",
            "error": None,
            "coverage": {
                "genes_coverage_pct": 100.0,
                "pathways_coverage_pct": 40.0,
                "total_papers": 10,
            },
            "total_papers": 10,
            "latency_ms": 200.0,
            "pmids": ["2"],
            "papers": [{"title": "breast sample", "abstract": "breast"}],
            "input": {"disease": "breast cancer"},
        },
        {
            "method": "baseline_lit",
            "case_id": "c1",
            "error": None,
            "coverage": {
                "genes_coverage_pct": 20.0,
                "pathways_coverage_pct": 10.0,
                "total_papers": 5,
            },
            "total_papers": 5,
            "latency_ms": 300.0,
            "pmids": ["3"],
            "papers": [{"title": "breast sample", "abstract": "breast"}],
            "input": {"disease": "breast cancer"},
        },
    ]

    summary_rows, case_metric_cache = _compute_method_summary(records=records, labels={})
    by_method = {row["method"]: row for row in summary_rows}
    dyn = by_method["dynamic"]

    assert dyn["mean_gene_coverage_pct"] == pytest.approx(90.0)
    assert dyn["mean_pathway_coverage_pct"] == pytest.approx(50.0)
    assert dyn["mean_coverage_composite_pct"] == pytest.approx(70.0)
    assert dyn["mean_total_papers"] == pytest.approx(15.0)

    assert case_metric_cache["dynamic:gene_coverage_pct"]["c1"] == pytest.approx(90.0)
    assert case_metric_cache["dynamic:pathway_coverage_pct"]["c1"] == pytest.approx(50.0)
    assert case_metric_cache["dynamic:coverage_composite_pct"]["c1"] == pytest.approx(70.0)
    assert case_metric_cache["dynamic:total_papers"]["c1"] == pytest.approx(15.0)

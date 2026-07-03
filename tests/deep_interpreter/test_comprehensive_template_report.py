from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.agents.deep_interpreter import report_guardrails
from src.agents.deep_interpreter.tools import report as report_tool
from src.agents.deep_interpreter.tools.report import _generate_html_report_impl


FIGURES = [
    "1.cluster_spatial.png",
    "2.celltype_heatmap_analysis.png",
    "3.neighborhood_enrichment_squidpy.png",
    "4.spatial_enrich_decoupler.png",
    "5.spatial_relation_MISTy.png",
    "6.liana_MoransR.png",
    "7.factor_spatial_NMF.png",
    "8.pathway_factor_heatmap.png",
    "9.quadrant_analysis.png",
    "10.spatial_plot_interections.png",
    "11.lr_interections.png",
]


def _write_fixture_data(data_dir: Path) -> None:
    png = b"\x89PNG\r\n\x1a\n"
    for name in FIGURES:
        (data_dir / name).write_bytes(png)

    (data_dir / "part1_final.md").write_text(
        "# Part 1\n\nSpatial clustering highlights invasive tumor regions.\n",
        encoding="utf-8",
    )
    (data_dir / "part2_final.md").write_text(
        "# Part 2\n\nFactor3 links ERBB signaling with MAPK and PI3K activity.\n",
        encoding="utf-8",
    )
    (data_dir / "part3_final.md").write_text(
        "# Part 3\n\nERBB3, EPHB4, and ERBB2 are selected L-R evidence genes.\n",
        encoding="utf-8",
    )
    (data_dir / "part4_therapeutic_synthesis.md").write_text(
        "# Part 4\n\n"
        "Therapeutic implications prioritize **ERBB3**, EPHB4, and ERBB2.\n\n"
        "| Compound | Phase |\n"
        "|----------|------:|\n"
        "| **CHEMBL1** | phase 3 |\n",
        encoding="utf-8",
    )
    (data_dir / "synthesis.md").write_text(
        "# Integrated Biological Narrative\n\n"
        "Intro text outside the executive summary.\n\n"
        "## Executive Summary\n\n"
        "Integrated **invasive-vascular corridor** program.\n\n"
        "## Cross-Part Themes\n\n"
        "| Theme | Strength |\n"
        "|-------|----------|\n"
        "| Corridor | **Strong** |\n",
        encoding="utf-8",
    )
    (data_dir / "synthesis_targets.json").write_text(
        json.dumps(
            {
                "part4_synthesis_available": True,
                "drug_md_available": True,
                "canonical_source": "part4_therapeutic_synthesis.md",
                "supporting_source": "drug.md",
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "synthesis_validation.json").write_text(
        json.dumps(
            {
                "literature_source": "papers.json",
                "expanded_literature": False,
                "rag_part_name": "all",
                "rag_mode": False,
                "claims_validated": 0,
                "claims_by_status": {"supported": 0, "caveated": 0, "hypothesis": 0},
                "validation_results": [],
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "data_path.txt").write_text(str(data_dir), encoding="utf-8")

    csv_payload = "name,value,score\nA,10,0.1\nB,20,0.2\n"
    for name in [
        "sig_clusterwithcelltyp.csv",
        "res_nhood_enrichment.csv",
        "sig_PathwayEnrich_decoupler.csv",
        "sel_interest_sig_liana.csv",
        "res_liana_cluster_factor.csv",
        "sig_liana_pathway_factor.csv",
    ]:
        (data_dir / name).write_text(csv_payload, encoding="utf-8")


def test_comprehensive_template_mode_renders_dense_fixed_structure(tmp_path: Path):
    _write_fixture_data(tmp_path)
    output = tmp_path / "CCI_Analysis_Report.html"

    result = _generate_html_report_impl(
        parts={
            "template_mode": "comprehensive",
            "title": "CCI Analysis Report",
            "subtitle": "Comprehensive Cell-Cell Interaction Analysis",
            "analysis_config": {"Target Clusters": "4, 14, 17", "NMF Factor": "Factor3"},
            "quality_score": 0.7,
            "references": [],
        },
        output_path=str(output),
        data_dir=str(tmp_path),
    )

    html = output.read_text(encoding="utf-8")
    assert "Report generated successfully" in result
    assert "Part 1: Spatial Organization and Pathway Analysis" in html
    assert "Part 2: Cell-Cell Interaction and Intercellular Pattern Analysis" in html
    assert "Part 3: Critical Ligand-Receptor Interactions" in html
    assert "Comprehensive Summary" in html
    assert "Therapeutic Implications" in html
    assert "ERBB3" in html
    assert "EPHB4" in html
    assert "ERBB2" in html
    assert html.count("<img ") >= 10
    assert html.count("<table") >= 5

    top_summary = html.split('<div class="summary-box">', 1)[1].split("</div>", 1)[0]
    assert "Integrated Biological Narrative" not in top_summary
    assert "Intro text outside the executive summary" not in top_summary
    assert "<strong>invasive-vascular corridor</strong>" in top_summary
    assert "**invasive-vascular corridor**" not in html
    assert "|-------|----------|" not in html
    assert "<strong>Strong</strong>" in html
    assert "part4_synthesis_available" not in html


def test_generate_html_report_runs_synthesis_guardrail_before_comprehensive_render(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_fixture_data(tmp_path)
    output = tmp_path / "CCI_Analysis_Report.html"
    seen: list[object] = []

    def fake_guardrail(data_dir: str | Path, *, provider: str | None = None) -> dict[str, object]:
        del provider
        seen.append("guardrail")
        Path(data_dir, "synthesis.md").write_text(
            "## Executive Summary\n\nRepaired synthesis.\n",
            encoding="utf-8",
        )
        return {
            "status": "passed",
            "artifact": "synthesis.md",
            "initial_issue_count": 1,
            "initial_error_count": 1,
            "changed_claims": 1,
            "final_issue_count": 1,
            "final_error_count": 0,
        }

    def fake_render(parts: dict, output_path: str, data_dir: str) -> str:
        del parts
        seen.append(("render", Path(data_dir, "synthesis.md").read_text(encoding="utf-8")))
        Path(output_path).write_text("<html>ok</html>", encoding="utf-8")
        return "<html>ok</html>"

    monkeypatch.setattr(report_guardrails, "run_synthesis_guardrail", fake_guardrail)
    monkeypatch.setattr(report_tool, "_render_comprehensive_template", fake_render)

    result = report_tool.generate_html_report.invoke(
        {
            "parts": {"template_mode": "comprehensive"},
            "output_path": str(output),
            "data_dir": str(tmp_path),
        }
    )

    assert "Report generated successfully" in result
    assert seen == ["guardrail", ("render", "## Executive Summary\n\nRepaired synthesis.\n")]


def test_generate_html_report_persists_parts_synthesis_before_guardrail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_fixture_data(tmp_path)
    (tmp_path / "synthesis.md").unlink()
    output = tmp_path / "CCI_Analysis_Report.html"
    seen: list[str] = []

    def fake_guardrail(data_dir: str | Path, *, provider: str | None = None) -> dict[str, object]:
        del provider
        seen.append(Path(data_dir, "synthesis.md").read_text(encoding="utf-8"))
        return {
            "status": "passed",
            "artifact": "synthesis.md",
            "initial_issue_count": 0,
            "initial_error_count": 0,
            "changed_claims": 0,
            "final_issue_count": 0,
            "final_error_count": 0,
        }

    def fake_render(parts: dict, output_path: str, data_dir: str) -> str:
        del parts, data_dir
        Path(output_path).write_text("<html>ok</html>", encoding="utf-8")
        return "Report generated successfully"

    monkeypatch.setattr(report_guardrails, "run_synthesis_guardrail", fake_guardrail)
    monkeypatch.setattr(report_tool, "_render_comprehensive_template", fake_render)

    result = report_tool.generate_html_report.invoke(
        {
            "parts": {
                "template_mode": "comprehensive",
                "synthesis": "## Executive Summary\n\nMaterialized synthesis.",
            },
            "output_path": str(output),
            "data_dir": str(tmp_path),
        }
    )

    assert "Report generated successfully" in result
    assert seen == ["## Executive Summary\n\nMaterialized synthesis.\n"]
    assert (tmp_path / "synthesis.md").read_text(encoding="utf-8") == seen[0]


def test_generate_html_report_blocks_when_synthesis_missing_before_guardrail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_fixture_data(tmp_path)
    (tmp_path / "synthesis.md").unlink()
    output = tmp_path / "CCI_Analysis_Report.html"

    def fake_guardrail(data_dir: str | Path, *, provider: str | None = None) -> dict[str, object]:
        del data_dir, provider
        return {"status": "skipped", "missing": ["synthesis.md"]}

    def fail_render(parts: dict, output_path: str, data_dir: str) -> str:
        del parts, output_path, data_dir
        raise AssertionError("HTML render should not run without synthesis.md")

    monkeypatch.setattr(report_guardrails, "run_synthesis_guardrail", fake_guardrail)
    monkeypatch.setattr(report_tool, "_render_comprehensive_template", fail_render)

    result = report_tool.generate_html_report.invoke(
        {
            "parts": {"template_mode": "comprehensive"},
            "output_path": str(output),
            "data_dir": str(tmp_path),
        }
    )

    assert "Error generating report: synthesis guardrail failed before HTML rendering" in result
    assert "synthesis.md" in result
    assert not output.exists()


def test_generate_html_report_writes_missing_reporter_artifacts_before_render(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_fixture_data(tmp_path)
    (tmp_path / "synthesis_validation.json").unlink()
    (tmp_path / "synthesis_targets.json").unlink()
    output = tmp_path / "CCI_Analysis_Report.html"
    seen: list[dict[str, Any]] = []

    def fake_guardrail(data_dir: str | Path, *, provider: str | None = None) -> dict[str, object]:
        del data_dir, provider
        return {
            "status": "passed",
            "artifact": "synthesis.md",
            "initial_issue_count": 3,
            "initial_error_count": 1,
            "changed_claims": 1,
            "final_issue_count": 2,
            "final_error_count": 0,
        }

    def fake_render(parts: dict, output_path: str, data_dir: str) -> str:
        del parts
        seen.append(
            {
                "validation": json.loads(
                    Path(data_dir, "synthesis_validation.json").read_text(encoding="utf-8")
                ),
                "targets": json.loads(
                    Path(data_dir, "synthesis_targets.json").read_text(encoding="utf-8")
                ),
            }
        )
        Path(output_path).write_text("<html>ok</html>", encoding="utf-8")
        return "Report generated successfully"

    monkeypatch.setattr(report_guardrails, "run_synthesis_guardrail", fake_guardrail)
    monkeypatch.setattr(report_tool, "_render_comprehensive_template", fake_render)

    result = report_tool.generate_html_report.invoke(
        {
            "parts": {"template_mode": "comprehensive"},
            "output_path": str(output),
            "data_dir": str(tmp_path),
        }
    )

    assert "Report generated successfully" in result
    assert output.exists()
    assert seen[0]["validation"]["auto_generated"] is True
    assert seen[0]["validation"]["synthesis_guardrail"]["final_error_count"] == 0
    assert seen[0]["targets"]["part4_synthesis_available"] is True
    assert seen[0]["targets"]["canonical_source"] == "part4_therapeutic_synthesis.md"


def test_generate_html_report_preserves_existing_reporter_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_fixture_data(tmp_path)
    output = tmp_path / "CCI_Analysis_Report.html"
    existing_validation = {"manual": True}
    existing_targets = {"canonical_source": "manual.md"}
    (tmp_path / "synthesis_validation.json").write_text(
        json.dumps(existing_validation),
        encoding="utf-8",
    )
    (tmp_path / "synthesis_targets.json").write_text(
        json.dumps(existing_targets),
        encoding="utf-8",
    )

    def fake_guardrail(data_dir: str | Path, *, provider: str | None = None) -> dict[str, object]:
        del data_dir, provider
        return {
            "status": "passed",
            "artifact": "synthesis.md",
            "initial_issue_count": 0,
            "initial_error_count": 0,
            "changed_claims": 0,
            "final_issue_count": 0,
            "final_error_count": 0,
        }

    def fake_render(parts: dict, output_path: str, data_dir: str) -> str:
        del parts, data_dir
        Path(output_path).write_text("<html>ok</html>", encoding="utf-8")
        return "Report generated successfully"

    monkeypatch.setattr(report_guardrails, "run_synthesis_guardrail", fake_guardrail)
    monkeypatch.setattr(report_tool, "_render_comprehensive_template", fake_render)

    result = report_tool.generate_html_report.invoke(
        {
            "parts": {"template_mode": "comprehensive"},
            "output_path": str(output),
            "data_dir": str(tmp_path),
        }
    )

    assert "Report generated successfully" in result
    assert json.loads((tmp_path / "synthesis_validation.json").read_text(encoding="utf-8")) == existing_validation
    assert json.loads((tmp_path / "synthesis_targets.json").read_text(encoding="utf-8")) == existing_targets


def test_generate_html_report_blocks_comprehensive_render_on_failed_synthesis_guardrail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_fixture_data(tmp_path)
    output = tmp_path / "CCI_Analysis_Report.html"

    def fake_guardrail(data_dir: str | Path, *, provider: str | None = None) -> dict[str, object]:
        del data_dir, provider
        return {"status": "failed", "artifact": "synthesis.md", "final_error_count": 1}

    def fail_render(parts: dict, output_path: str, data_dir: str) -> str:
        del parts, output_path, data_dir
        raise AssertionError("HTML render should not run after failed synthesis guardrail")

    monkeypatch.setattr(report_guardrails, "run_synthesis_guardrail", fake_guardrail)
    monkeypatch.setattr(report_tool, "_render_comprehensive_template", fail_render)

    result = report_tool.generate_html_report.invoke(
        {
            "parts": {"template_mode": "comprehensive"},
            "output_path": str(output),
            "data_dir": str(tmp_path),
        }
    )

    assert "Error generating report: synthesis guardrail failed before HTML rendering" in result
    assert not output.exists()

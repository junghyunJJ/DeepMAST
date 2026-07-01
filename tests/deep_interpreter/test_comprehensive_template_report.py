from __future__ import annotations

import json
from pathlib import Path

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

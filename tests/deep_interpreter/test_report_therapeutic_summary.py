"""Tests for Therapeutic tab rendering in HTML report output."""

import tempfile
from pathlib import Path


def test_generate_simple_report_renders_gwas_and_multisource_summary():
    from src.agents.deep_interpreter.tools.report import generate_simple_report

    therapeutic = {
        "druggable_targets": [
            {
                "gene": "ERBB2",
                "name": "ERBB2 receptor",
                "tractability": {"SM": ["Clinical_Precedence"]},
                "association_score": 0.91,
                "evidence_count": 12,
                "safety_concerns": 0,
            }
        ],
        "known_drugs": [
            {
                "drug_name": "TRASTUZUMAB",
                "phase": 4,
                "mechanism_of_action": "ERBB2 inhibitor",
                "target_genes": ["ERBB2"],
                "status": "Approved",
                "clinical_trials_total_count": 31,
                "drugbank_match_count": 1,
            }
        ],
        "novel_targets": [],
        "summary": {
            "total_genes_evaluated": 25,
            "druggable_count": 10,
            "known_drugs_count": 1,
            "novel_target_count": 2,
            "validated_pass_count": 3,
            "exploratory_pass_count": 4,
            "top_validated_genes": ["ERBB2"],
            "top_exploratory_genes": ["GDF15"],
            "gwas_direct_status": "ok",
            "genes_with_gwas_direct_signal": 2,
            "multi_source_status": {
                "chembl": "ok",
                "clinicaltrials": "ok",
                "drugbank": "degraded",
            },
            "genes_with_chembl_target_support": 5,
            "drugs_with_clinical_trials": 1,
            "drugs_with_drugbank_match": 1,
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "report.html"
        status = generate_simple_report(
            title="Test Report",
            content={
                "subtitle": "test",
                "summary": "Executive summary",
                "config": "config",
                "part1": {},
                "part2": {},
                "part3": {},
                "synthesis": "synthesis",
                "quality_score": 0.8,
                "references": [],
                "therapeutic": therapeutic,
            },
            output_path=str(out_path),
        )

        assert "Report generated successfully" in status
        html = out_path.read_text(encoding="utf-8")
        assert "Therapeutic Potential Summary" in html
        assert "GWAS Direct:" in html
        assert "Multi-source Status:" in html
        assert "Trials (CT.gov)" in html
        assert "DrugBank Match" in html
        assert "TRASTUZUMAB" in html


def test_generate_simple_report_renders_string_tractability():
    from src.agents.deep_interpreter.tools.report import generate_simple_report

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "report.html"
        generate_simple_report(
            title="Test Report",
            content={
                "part1": {}, "part2": {}, "part3": {}, "references": [],
                "therapeutic": {"druggable_targets": [{"gene": "ERBB2", "tractability": "approved"}]},
            },
            output_path=str(out_path),
        )

        assert "approved" in out_path.read_text(encoding="utf-8")


def test_generate_simple_report_ignores_non_mapping_therapeutic_entries():
    from src.agents.deep_interpreter.tools.report import generate_simple_report

    therapeutic = {
        "druggable_targets": [
            "invalid target",
            {"gene": "ERBB2", "name": "ERBB2 receptor", "association_score": 0.91},
        ],
        "known_drugs": [
            "invalid drug",
            {"drug_name": "TRASTUZUMAB", "phase": 4, "target_genes": ["ERBB2"]},
        ],
        "novel_targets": [
            "invalid novel target",
            {"gene": "ERBB3", "name": "ERBB3 receptor"},
        ],
        "summary": {},
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "report.html"
        status = generate_simple_report(
            title="Test Report",
            content={
                "part1": {}, "part2": {}, "part3": {}, "references": [],
                "therapeutic": therapeutic,
            },
            output_path=str(out_path),
        )

        assert "Report generated successfully" in status
        html = out_path.read_text(encoding="utf-8")
        assert "ERBB2" in html
        assert "TRASTUZUMAB" in html
        assert "ERBB3" in html
        assert "invalid target" not in html
        assert "invalid drug" not in html
        assert "invalid novel target" not in html

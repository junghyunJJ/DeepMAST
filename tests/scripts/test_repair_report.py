from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "repair_report.py"
SPEC = importlib.util.spec_from_file_location("repair_report", SCRIPT_PATH)
assert SPEC and SPEC.loader
repair_report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair_report)


class FakeLLM:
    def invoke(self, prompt: str):
        assert "Factor1 showed significant enrichment" in prompt
        assert "UNCHANGED INTRO" not in prompt
        return type(
            "Msg",
            (),
            {
                "content": (
                    "### Biological Interpretation\n"
                    "Factor1 may reflect TGFb/MAPK activity inferred from LR annotations, "
                    "not pathway-factor significance."
                )
            },
        )()


class FailLLM:
    def invoke(self, prompt: str):
        raise AssertionError(f"LLM should not be called: {prompt}")


def test_repair_replaces_only_flagged_section(tmp_path: Path) -> None:
    report = tmp_path / "part2_final.md"
    report.write_text(
        "## Analysis 2-7: Keep\n"
        "UNCHANGED INTRO\n"
        "## Analysis 2-8: Pathway Factor Heatmap\n"
        "### Biological Interpretation\n"
        "Factor1 showed significant enrichment for TGFb/MAPK.\n"
        "## Part 2 Summary\n"
        "UNCHANGED SUMMARY\n",
        encoding="utf-8",
    )
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "code": "unsupported_factor1_pathway_significance",
                        "severity": "error",
                        "file": "part2_final.md",
                        "section": "## Analysis 2-8: Pathway Factor Heatmap",
                        "value": "Factor1 pathway significance",
                        "evidence": "No Factor1 row in sig_liana_pathway_factor.csv.",
                        "repair_instruction": "Rephrase as hypothesis.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    changed = repair_report.repair_report(tmp_path, issues_path, llm=FakeLLM())

    text = report.read_text(encoding="utf-8")
    assert changed == 1
    assert "UNCHANGED INTRO" in text
    assert "UNCHANGED SUMMARY" in text
    assert "Factor1 showed significant enrichment" not in text
    assert "not pathway-factor significance" in text


def test_repair_skips_file_level_issue_without_section(tmp_path: Path) -> None:
    report = tmp_path / "part1_final.md"
    report.write_text("Fake PMID:99999999\n", encoding="utf-8")
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "code": "pmid_not_in_papers",
                        "severity": "error",
                        "file": "part1_final.md",
                        "section": "",
                        "value": "99999999",
                        "evidence": "Absent from papers.json.",
                        "repair_instruction": "Remove unsupported PMID.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    changed = repair_report.repair_report(tmp_path, issues_path, llm=FakeLLM())

    assert changed == 0
    assert report.read_text(encoding="utf-8") == "Fake PMID:99999999\n"


def test_repair_skips_issue_file_outside_data_dir(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text(
        "## Analysis 2-8: Pathway Factor Heatmap\n"
        "Factor1 showed significant enrichment for MAPK.\n",
        encoding="utf-8",
    )
    issues_path = data_dir / "issues.json"
    issues_path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "code": "unsupported_factor1_pathway_significance",
                        "severity": "error",
                        "file": "../outside.md",
                        "section": "## Analysis 2-8: Pathway Factor Heatmap",
                        "value": "MAPK",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    changed = repair_report.repair_report(data_dir, issues_path, llm=FailLLM())

    assert changed == 0
    assert "significant enrichment" in outside.read_text(encoding="utf-8")

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from src.agents.deep_interpreter import claim_rag_validation


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


class CountingLLM:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, prompt: str):
        self.calls += 1
        assert "first issue" in prompt
        assert "second issue" in prompt
        return type(
            "Msg",
            (),
            {
                "content": (
                    "## Analysis 2-8: Pathway Factor Heatmap\n"
                    "### Biological Interpretation\n"
                    "Factor1 may reflect pathway activity inferred from LR annotations."
                )
            },
        )()


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


def test_repair_groups_multiple_issues_for_same_section(tmp_path: Path) -> None:
    report = tmp_path / "part2_final.md"
    report.write_text(
        "## Analysis 2-8: Pathway Factor Heatmap\n"
        "Factor1 showed significant enrichment for MAPK and EGFR.\n",
        encoding="utf-8",
    )
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "code": "unsupported_pathway_factor_significance",
                        "severity": "error",
                        "file": "part2_final.md",
                        "section": "## Analysis 2-8: Pathway Factor Heatmap",
                        "value": "first issue",
                    },
                    {
                        "code": "unsupported_pathway_factor_significance",
                        "severity": "error",
                        "file": "part2_final.md",
                        "section": "## Analysis 2-8: Pathway Factor Heatmap",
                        "value": "second issue",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    llm = CountingLLM()

    changed = repair_report.repair_report(tmp_path, issues_path, llm=llm)

    assert changed == 1
    assert llm.calls == 1


def test_repair_skips_unknown_file_level_issue_without_section(tmp_path: Path) -> None:
    report = tmp_path / "part1_final.md"
    report.write_text("Fake PMID:99999999\n", encoding="utf-8")
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "code": "unknown_file_level_issue",
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


def test_repair_corrects_one_digit_pmid_typo_without_llm(tmp_path: Path) -> None:
    (tmp_path / "papers.json").write_text(
        json.dumps([{"pmid": "20498641", "title": "known"}]),
        encoding="utf-8",
    )
    report = tmp_path / "part2_final.md"
    report.write_text(
        "- PMID: 20498643 - ErbB3 coexpression evidence.\n",
        encoding="utf-8",
    )
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "code": "pmid_not_in_papers",
                        "severity": "error",
                        "file": "part2_final.md",
                        "section": "",
                        "value": "20498643",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    changed = repair_report.repair_report(tmp_path, issues_path, llm=FailLLM())

    assert changed == 1
    assert "20498641" in report.read_text(encoding="utf-8")
    assert "20498643" not in report.read_text(encoding="utf-8")


def test_repair_removes_unsupported_pmid_when_no_unique_close_match(tmp_path: Path) -> None:
    (tmp_path / "papers.json").write_text(json.dumps([{"pmid": "11111111"}]), encoding="utf-8")
    report = tmp_path / "part2_final.md"
    report.write_text(
        "Supported text.\n"
        "- PMID: 99999999 - fabricated evidence line.\n"
        "Inline unsupported citation (PMID:99999999) should be removed.\n",
        encoding="utf-8",
    )
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "code": "pmid_not_in_papers",
                        "severity": "error",
                        "file": "part2_final.md",
                        "section": "",
                        "value": "99999999",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    changed = repair_report.repair_report(tmp_path, issues_path, llm=FailLLM())

    text = report.read_text(encoding="utf-8")
    assert changed == 1
    assert "99999999" not in text
    assert "fabricated evidence line" not in text
    assert "Supported text." in text


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


def test_repair_prompt_requires_association_language_for_mechanistic_issues(tmp_path: Path) -> None:
    issue = {
        "code": "unsupported_mechanistic_interpretation",
        "severity": "error",
        "file": "part1_final.md",
        "section": "## Analysis 1-5: MISTy",
        "value": "drives",
    }
    prompt = repair_report._build_prompt(
        issue,
        "## Analysis 1-5: MISTy\n"
        "### Biological Interpretation\n"
        "The MISTy association confirms that hypoxia drives tumor behavior.\n",
    )

    assert "Rewrite causal or mechanistic report-derived claims as associations or hypotheses." in prompt
    assert "Do not claim treatment sensitivity, resistance, patient stratification, or therapeutic vulnerability unless the validation issue provides direct support for that exact claim." in prompt


def test_claim_rag_repair_prompt_forbids_new_evidence() -> None:
    prompt = repair_report._build_prompt(
        {
            "code": "claim_rag_overclaimed",
            "severity": "error",
            "file": "part1_final.md",
            "section": "## Analysis 1-1",
            "value": "TGFB drives fibrosis.",
            "evidence": "PMID 11111111 supports association only.",
            "repair_instruction": "Rewrite as association.",
        },
        "## Analysis 1-1\nTGFB drives fibrosis.\n",
    )

    assert "use only the evidence in the validation issue" in prompt.lower()
    assert "do not replace the cited paper" in prompt.lower()


def test_repair_removes_only_unsupported_inline_pmid_when_sibling_supports(
    tmp_path: Path,
) -> None:
    report = "## Biology\nTGFB is associated with fibrosis (PMID: 11111111; PMID: 22222222).\n"
    (tmp_path / "part1_final.md").write_text(report, encoding="utf-8")
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "severity": "error",
                        "code": "inline_citation_unsupported",
                        "file": "part1_final.md",
                        "section": "## Biology",
                        "source_claim_index": 0,
                        "inline_pmid": "22222222",
                        "value": "TGFB is associated with fibrosis (PMID: 11111111; PMID: 22222222).",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    rows = [
        {
            "file": "part1_final.md",
            "section": "## Biology",
            "source_claim_index": 0,
            "inline_pmid": "11111111",
            "status": "supported",
        },
        {
            "file": "part1_final.md",
            "section": "## Biology",
            "source_claim_index": 0,
            "inline_pmid": "22222222",
            "status": "unsupported",
        },
    ]

    assert repair_report.repair_report(tmp_path, issues_path, claim_validation=rows) == 1
    repaired = (tmp_path / "part1_final.md").read_text(encoding="utf-8")
    assert "11111111" in repaired
    assert "22222222" not in repaired


def test_repair_handles_hedged_failed_inline_pmid_when_sibling_supports(
    tmp_path: Path,
) -> None:
    claim = "TGFB may be associated with fibrosis (PMID: 11111111; PMID: 22222222)."
    (tmp_path / "part1_final.md").write_text(f"## Biology\n{claim}\n", encoding="utf-8")
    issue = claim_rag_validation._issue_for(
        {
            "status": "unsupported",
            "hedged": True,
            "supporting_pmids": [],
            "evidence_quote": "",
            "reason": "The cited paper does not support this claim.",
            "file": "part1_final.md",
            "section": "## Biology",
            "source_claim_index": 0,
            "inline_pmid": "22222222",
            "claim": claim,
        }
    )
    assert issue is not None
    assert issue["severity"] == "error"
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(json.dumps({"issues": [issue]}), encoding="utf-8")
    rows = [
        {
            "file": "part1_final.md",
            "section": "## Biology",
            "source_claim_index": 0,
            "inline_pmid": "11111111",
            "status": "supported",
        },
        {
            "file": "part1_final.md",
            "section": "## Biology",
            "source_claim_index": 0,
            "inline_pmid": "22222222",
            "status": "unsupported",
        },
    ]

    assert repair_report.repair_report(tmp_path, issues_path, claim_validation=rows) == 1
    repaired = (tmp_path / "part1_final.md").read_text(encoding="utf-8")
    assert repaired == "## Biology\nTGFB may be associated with fibrosis (PMID: 11111111).\n"


def test_inline_pmid_repair_requires_supported_sibling(tmp_path: Path) -> None:
    report = "## Biology\nTGFB is associated with fibrosis (PMID: 22222222).\n"
    (tmp_path / "part1_final.md").write_text(report, encoding="utf-8")
    issue = {
        "severity": "error",
        "code": "inline_citation_unsupported",
        "file": "part1_final.md",
        "section": "## Biology",
        "source_claim_index": 0,
        "inline_pmid": "22222222",
        "value": "TGFB is associated with fibrosis (PMID: 22222222).",
    }
    rows = [
        {
            "file": "part1_final.md",
            "section": "## Biology",
            "source_claim_index": 0,
            "inline_pmid": "22222222",
            "status": "unsupported",
        }
    ]

    assert repair_report._repair_inline_citation_issue(tmp_path.resolve(), issue, rows) is False
    assert (tmp_path / "part1_final.md").read_text(encoding="utf-8") == report


def test_inline_pmid_repair_only_changes_named_section(tmp_path: Path) -> None:
    claim = "TGFB is associated with fibrosis (PMID: 11111111; PMID: 22222222)."
    report = f"## Earlier\n{claim}\n## Biology\n{claim}\n"
    (tmp_path / "part1_final.md").write_text(report, encoding="utf-8")
    issue = {
        "severity": "error",
        "code": "inline_citation_unsupported",
        "file": "part1_final.md",
        "section": "## Biology",
        "source_claim_index": 0,
        "inline_pmid": "22222222",
        "value": claim,
    }
    rows = [
        {
            "file": "part1_final.md",
            "section": "## Biology",
            "source_claim_index": 0,
            "inline_pmid": "11111111",
            "status": "supported",
        },
        {
            "file": "part1_final.md",
            "section": "## Biology",
            "source_claim_index": 0,
            "inline_pmid": "22222222",
            "status": "unsupported",
        },
    ]

    assert repair_report._repair_inline_citation_issue(tmp_path.resolve(), issue, rows) is True
    repaired = (tmp_path / "part1_final.md").read_text(encoding="utf-8")
    assert f"## Earlier\n{claim}\n" in repaired
    assert (
        "## Biology\nTGFB is associated with fibrosis (PMID: 11111111).\n" in repaired
    )


def test_inline_pmid_repair_ignores_unverifiable_and_unknown_codes(tmp_path: Path) -> None:
    claim = "TGFB is associated with fibrosis (PMID: 11111111; PMID: 22222222)."
    for code in ("inline_citation_unverifiable", "inline_citation_surprising"):
        report = tmp_path / f"{code}.md"
        report.write_text(f"## Biology\n{claim}\n", encoding="utf-8")
        issue = {
            "severity": "error",
            "code": code,
            "file": report.name,
            "section": "## Biology",
            "source_claim_index": 0,
            "inline_pmid": "22222222",
            "value": claim,
        }
        rows = [
            {
                "file": report.name,
                "section": "## Biology",
                "source_claim_index": 0,
                "inline_pmid": "11111111",
                "status": "supported",
            }
        ]

        assert repair_report._repair_inline_citation_issue(tmp_path.resolve(), issue, rows) is False
        assert report.read_text(encoding="utf-8") == f"## Biology\n{claim}\n"


def test_pathway_factor_repair_prompt_separates_annotations_from_measurements() -> None:
    prompt = repair_report._build_prompt(
        {
            "code": "unsupported_pathway_factor_significance",
            "severity": "error",
            "file": "part2_final.md",
            "section": "## Analysis 2-8: Pathway-Factor Enrichment",
            "value": "Factor2: TNFa",
            "evidence": "sig_liana_pathway_factor.csv lacks the claimed factor-pathway support.",
            "repair_instruction": (
                "Rephrase as an LR-annotation-based hypothesis, "
                "not measured pathway-factor significance."
            ),
        },
        (
            "## Analysis 2-8: Pathway-Factor Enrichment\n"
            "TNFa annotation may provide context for Factor2 regions."
        ),
    )

    assert (
        "Keep L-R pathway annotations and measured factor-pathway results "
        "in separate sentences."
    ) in prompt
    assert (
        "Do not place an unsupported pathway label and factor label in the "
        "same sentence unless that sentence explicitly states that no "
        "measured association was identified."
    ) in prompt

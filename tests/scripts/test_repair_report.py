from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

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
        self.schema = None

    def with_structured_output(self, schema, **_kwargs):
        self.schema = schema
        return self

    def invoke(self, prompt: str):
        self.calls += 1
        assert "first issue" in prompt
        assert "second issue" in prompt
        assert self.schema is not None
        return self.schema(
            action="replace",
            replacement_text=(
                "Factor1 may reflect pathway activity inferred from LR annotations."
            ),
        )


class TruncatedSectionLLM:
    def invoke(self, prompt: str):
        assert "Original unsupported claim." in prompt
        return type(
            "Msg",
            (),
            {
                "content": (
                    "## Analysis 2-8\n"
                    "### Figure Description\n"
                    "Shortened description.\n"
                    "### Quantitative Findings\n"
                    "Measured values remain.\n"
                )
            },
        )()


class RepairDecisionLLM:
    def __init__(self, *, action: str = "replace", replacement_text: str = "") -> None:
        self.action = action
        self.replacement_text = replacement_text
        self.calls = 0
        self.prompts: list[str] = []
        self.schema = None

    def with_structured_output(self, schema, **_kwargs):
        self.schema = schema
        return self

    def invoke(self, prompt: str):
        self.calls += 1
        self.prompts.append(prompt)
        assert self.schema is not None
        return self.schema(
            action=self.action,
            replacement_text=self.replacement_text,
        )


class MalformedDecisionLLM:
    def with_structured_output(self, _schema, **_kwargs):
        return self

    def invoke(self, _prompt: str):
        return {"action": "rewrite", "replacement_text": "x"}


def _write_issues(path: Path, issues: list[dict[str, object]]) -> Path:
    issues_path = path / "issues.json"
    issues_path.write_text(json.dumps({"issues": issues}), encoding="utf-8")
    return issues_path


def _trace_rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_repair_uses_validator_replacement_text_without_llm(tmp_path: Path) -> None:
    report = tmp_path / "part2_final.md"
    report.write_text("## Results\nLRIG1-ERBB3 Moran's R = 0.4213.\n", encoding="utf-8")
    issues_path = _write_issues(
        tmp_path,
        [
            {
                "code": "lr_metric_value_mismatch",
                "severity": "error",
                "file": "part2_final.md",
                "section": "## Results",
                "value": "legacy diagnostic label",
                "target_text": "LRIG1-ERBB3 Moran's R = 0.4213.",
                "replacement_text": "LRIG1-ERBB3 Moran's R = 0.3629.",
            }
        ],
    )

    changed = repair_report.repair_report(tmp_path, issues_path, llm=FailLLM())

    assert changed == 1
    assert report.read_text(encoding="utf-8") == "## Results\nLRIG1-ERBB3 Moran's R = 0.3629.\n"


def test_repair_rewrites_target_text_and_preserves_surrounding_markdown(tmp_path: Path) -> None:
    original = (
        "## Biology\n"
        "UNCHANGED INTRO\n"
        "LRIG1-ERBB3 proves treatment vulnerability (PMID: 12345678).\n"
        "UNCHANGED TAIL\n"
        "## Later\n"
        "UNCHANGED LATER\n"
    )
    replacement = "LRIG1-ERBB3 is a nominated interaction for follow-up (PMID: 12345678)."
    report = tmp_path / "part3_final.md"
    report.write_text(original, encoding="utf-8")
    issues_path = _write_issues(
        tmp_path,
        [
            {
                "code": "part3_therapeutic_spillover",
                "severity": "error",
                "file": "part3_final.md",
                "section": "## Biology",
                "target_text": "LRIG1-ERBB3 proves treatment vulnerability (PMID: 12345678).",
                "evidence": "No therapeutic validation was provided.",
                "repair_instruction": "Remove therapeutic framing.",
            }
        ],
    )
    llm = RepairDecisionLLM(replacement_text=replacement)

    changed = repair_report.repair_report(tmp_path, issues_path, llm=llm)

    assert changed == 1
    assert llm.calls == 1
    assert report.read_text(encoding="utf-8") == (
        "## Biology\n"
        "UNCHANGED INTRO\n"
        f"{replacement}\n"
        "UNCHANGED TAIL\n"
        "## Later\n"
        "UNCHANGED LATER\n"
    )


def test_repair_accepts_structured_replace_below_old_half_length_limit(tmp_path: Path) -> None:
    target = "NECTIN4 is an underexplored therapeutic target that warrants drug development."
    report = tmp_path / "part3_final.md"
    report.write_text(f"## Biology\nBefore.\n{target}\nAfter.\n", encoding="utf-8")
    issues = _write_issues(tmp_path, [{
        "severity": "error",
        "code": "part3_therapeutic_spillover",
        "file": report.name,
        "section": "## Biology",
        "target_text": target,
        "evidence": "Part3 contains spatial evidence only.",
        "repair_instruction": "Remove therapeutic framing.",
    }])

    changed = repair_report.repair_report(
        tmp_path,
        issues,
        llm=RepairDecisionLLM(
            action="replace",
            replacement_text="NECTIN4 remains a selected spatial signal.",
        ),
    )

    assert changed == 1
    assert report.read_text(encoding="utf-8") == (
        "## Biology\nBefore.\nNECTIN4 remains a selected spatial signal.\nAfter.\n"
    )


def test_repair_accepts_structured_delete_for_only_the_exact_target(tmp_path: Path) -> None:
    target = "NECTIN4 is an underexplored therapeutic target."
    original = f"## Biology\nKeep before.\n{target}\nKeep after.\n## Later\nKeep later.\n"
    report = tmp_path / "part3_final.md"
    report.write_text(original, encoding="utf-8")
    trace = tmp_path / "repair_trace.jsonl"
    trace.write_text("", encoding="utf-8")
    issues = _write_issues(tmp_path, [{
        "severity": "error",
        "code": "part3_therapeutic_spillover",
        "file": report.name,
        "section": "## Biology",
        "target_text": target,
        "evidence": "No supported spatial statement remains in this sentence.",
        "repair_instruction": "Delete the unsupported target only.",
    }])

    changed = repair_report.repair_report(
        tmp_path,
        issues,
        llm=RepairDecisionLLM(action="delete", replacement_text=""),
    )

    repaired = report.read_text(encoding="utf-8")
    assert changed == 1
    assert target not in repaired
    assert "Keep before." in repaired
    assert "Keep after." in repaired
    assert "## Later\nKeep later.\n" in repaired
    assert repair_report._markdown_headings(repaired) == repair_report._markdown_headings(original)
    assert _trace_rows(trace)[-1]["path"] == "llm_delete"


def test_target_spans_finds_exact_and_soft_wrapped_matches() -> None:
    assert repair_report._target_spans("Alpha beta.\n", "Alpha beta.") == (
        "exact",
        [(0, 11)],
    )
    assert repair_report._target_spans("Alpha\nbeta.\n", "Alpha beta.") == (
        "whitespace_normalized",
        [(0, 11)],
    )


def test_repair_does_not_match_target_across_paragraph_break(tmp_path: Path) -> None:
    original = "## Results\nAlpha\n\nbeta.\n"
    report = tmp_path / "part2_final.md"
    report.write_text(original, encoding="utf-8")
    trace_path = tmp_path / "repair_trace.jsonl"
    trace_path.write_text("", encoding="utf-8")
    issues_path = _write_issues(
        tmp_path,
        [
            {
                "code": "semantic_issue",
                "severity": "error",
                "file": "part2_final.md",
                "section": "## Results",
                "target_text": "Alpha beta.",
                "replacement_text": "Alpha gamma.",
            }
        ],
    )

    changed = repair_report.repair_report(tmp_path, issues_path, llm=FailLLM())

    assert changed == 0
    assert report.read_text(encoding="utf-8") == original
    rows = _trace_rows(trace_path)
    assert rows[-1]["event"] == "target_repair_rejected"
    assert rows[-1]["reason"] == "target_missing"


def test_repair_replaces_repeated_target_when_issue_count_matches(tmp_path: Path) -> None:
    target = "LRIG1-ERBB3 Moran's R = 0.4213."
    replacement = "LRIG1-ERBB3 Moran's R = 0.3629."
    original = f"## Results\n{target}\nMiddle stays.\n{target}\n"
    report = tmp_path / "part2_final.md"
    report.write_text(original, encoding="utf-8")
    issues_path = _write_issues(
        tmp_path,
        [
            {
                "code": "lr_metric_value_mismatch",
                "severity": "error",
                "file": "part2_final.md",
                "section": "## Results",
                "target_text": target,
                "replacement_text": replacement,
            },
            {
                "code": "lr_metric_value_mismatch",
                "severity": "error",
                "file": "part2_final.md",
                "section": "## Results",
                "target_text": target,
                "replacement_text": replacement,
            },
        ],
    )

    changed = repair_report.repair_report(tmp_path, issues_path, llm=FailLLM())

    assert changed == 1
    assert report.read_text(encoding="utf-8") == f"## Results\n{replacement}\nMiddle stays.\n{replacement}\n"


def test_repair_rejects_repeated_target_when_issue_count_mismatches(tmp_path: Path) -> None:
    target = "LRIG1-ERBB3 Moran's R = 0.4213."
    original = f"## Results\n{target}\n{target}\n"
    report = tmp_path / "part2_final.md"
    report.write_text(original, encoding="utf-8")
    trace_path = tmp_path / "repair_trace.jsonl"
    trace_path.write_text("", encoding="utf-8")
    issues_path = _write_issues(
        tmp_path,
        [
            {
                "code": "lr_metric_value_mismatch",
                "severity": "error",
                "file": "part2_final.md",
                "section": "## Results",
                "target_text": target,
                "replacement_text": "LRIG1-ERBB3 Moran's R = 0.3629.",
            }
        ],
    )

    changed = repair_report.repair_report(tmp_path, issues_path, llm=FailLLM())

    assert changed == 0
    assert report.read_text(encoding="utf-8") == original
    rows = _trace_rows(trace_path)
    assert rows[-1]["event"] == "target_repair_rejected"
    assert rows[-1]["reason"] == "target_count_mismatch"
    assert rows[-1]["occurrence_count"] == 2
    assert rows[-1]["issue_count"] == 1


@pytest.mark.parametrize(
    ("body", "target", "reason"),
    [
        ("Alpha\nbeta.\nAlpha \t beta.\n", "Alpha beta.", "ambiguous_target"),
        ("Different sentence.\n", "Missing sentence.", "target_missing"),
    ],
)
def test_repair_rejects_unresolved_targets_and_preserves_file(
    tmp_path: Path,
    body: str,
    target: str,
    reason: str,
) -> None:
    original = f"## Results\n{body}"
    report = tmp_path / "part2_final.md"
    report.write_text(original, encoding="utf-8")
    trace_path = tmp_path / "repair_trace.jsonl"
    trace_path.write_text("", encoding="utf-8")
    issues_path = _write_issues(
        tmp_path,
        [
            {
                "code": "semantic_issue",
                "severity": "error",
                "file": "part2_final.md",
                "section": "## Results",
                "target_text": target,
                "replacement_text": "Alpha gamma.",
            }
        ],
    )

    changed = repair_report.repair_report(tmp_path, issues_path, llm=FailLLM())

    assert changed == 0
    assert report.read_text(encoding="utf-8") == original
    rows = _trace_rows(trace_path)
    assert rows[-1]["event"] == "target_repair_rejected"
    assert rows[-1]["reason"] == reason


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        ("", "unsafe_replacement"),
        ("### New Heading\nLRIG1 remains supported.", "unsafe_replacement"),
        ("LRIG1 remains supported (PMID: 99999999).", "unsafe_replacement"),
    ],
)
def test_repair_rejects_unsafe_target_replacements_and_preserves_file(
    tmp_path: Path,
    candidate: str,
    reason: str,
) -> None:
    target = "LRIG1-ERBB3 drives tumor survival in the cited model (PMID: 12345678)."
    original = f"## Biology\n{target}\n"
    report = tmp_path / "part2_final.md"
    report.write_text(original, encoding="utf-8")
    trace_path = tmp_path / "repair_trace.jsonl"
    trace_path.write_text("", encoding="utf-8")
    issues_path = _write_issues(
        tmp_path,
        [
            {
                "code": "claim_rag_overclaimed",
                "severity": "error",
                "file": "part2_final.md",
                "section": "## Biology",
                "target_text": target,
            }
        ],
    )

    changed = repair_report.repair_report(
        tmp_path,
        issues_path,
        llm=RepairDecisionLLM(replacement_text=candidate),
    )

    assert changed == 0
    assert report.read_text(encoding="utf-8") == original
    rows = _trace_rows(trace_path)
    assert rows[-1]["event"] == "target_repair_rejected"
    assert rows[-1]["reason"] == reason
    assert "New Heading" not in trace_path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("action", "candidate", "reason"),
    [
        ("replace", "", "unsafe_replacement"),
        ("delete", "text must be empty", "unsafe_replacement"),
        ("replace", "### New Heading", "unsafe_replacement"),
        ("replace", "Claim (PMID: 99999999).", "unsafe_replacement"),
    ],
)
def test_repair_rejects_unsafe_structured_decisions_and_preserves_file(
    tmp_path: Path,
    action: str,
    candidate: str,
    reason: str,
) -> None:
    target = "Original supported context with an unsupported conclusion (PMID: 12345678)."
    original = f"## Biology\n{target}\n"
    report = tmp_path / "part2_final.md"
    report.write_text(original, encoding="utf-8")
    trace = tmp_path / "repair_trace.jsonl"
    trace.write_text("", encoding="utf-8")
    issues = _write_issues(tmp_path, [{
        "severity": "error",
        "code": "claim_rag_overclaimed",
        "file": report.name,
        "section": "## Biology",
        "target_text": target,
    }])

    changed = repair_report.repair_report(
        tmp_path,
        issues,
        llm=RepairDecisionLLM(action=action, replacement_text=candidate),
    )

    assert changed == 0
    assert report.read_text(encoding="utf-8") == original
    assert _trace_rows(trace)[-1]["reason"] == reason


def test_repair_rejects_malformed_structured_decision(tmp_path: Path) -> None:
    target = "Unsupported claim."
    original = f"## Biology\n{target}\n"
    report = tmp_path / "part2_final.md"
    report.write_text(original, encoding="utf-8")
    trace = tmp_path / "repair_trace.jsonl"
    trace.write_text("", encoding="utf-8")
    issues = _write_issues(tmp_path, [{
        "severity": "error",
        "code": "claim_rag_unsupported",
        "file": report.name,
        "section": "## Biology",
        "target_text": target,
    }])

    changed = repair_report.repair_report(
        tmp_path,
        issues,
        llm=MalformedDecisionLLM(),
    )

    assert changed == 0
    assert report.read_text(encoding="utf-8") == original
    assert _trace_rows(trace)[-1]["reason"] == "invalid_repair_decision"


def test_repair_rejects_error_issue_without_supported_target(tmp_path: Path) -> None:
    original = "## Results\nUnsupported sentence stays.\n"
    report = tmp_path / "part2_final.md"
    report.write_text(original, encoding="utf-8")
    trace_path = tmp_path / "repair_trace.jsonl"
    trace_path.write_text("", encoding="utf-8")
    issues_path = _write_issues(
        tmp_path,
        [
            {
                "code": "new_validator_error",
                "severity": "error",
                "file": "part2_final.md",
                "section": "## Results",
                "value": "Unsupported sentence stays.",
            }
        ],
    )

    changed = repair_report.repair_report(tmp_path, issues_path, llm=FailLLM())

    assert changed == 0
    assert report.read_text(encoding="utf-8") == original
    rows = _trace_rows(trace_path)
    assert rows[-1]["event"] == "target_repair_rejected"
    assert rows[-1]["reason"] == "unhandled_repair_target"


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
                        "target_text": "Factor1 showed significant enrichment for TGFb/MAPK.",
                        "evidence": "No Factor1 row in sig_liana_pathway_factor.csv.",
                        "repair_instruction": "Rephrase as hypothesis.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    changed = repair_report.repair_report(
        tmp_path,
        issues_path,
        llm=RepairDecisionLLM(
            replacement_text=(
                "Factor1 may reflect TGFb/MAPK activity inferred from LR annotations, "
                "not pathway-factor significance."
            )
        ),
    )

    text = report.read_text(encoding="utf-8")
    assert changed == 1
    assert "UNCHANGED INTRO" in text
    assert "UNCHANGED SUMMARY" in text
    assert "Factor1 showed significant enrichment" not in text
    assert "not pathway-factor significance" in text


def test_repair_rejects_truncated_section_and_preserves_original(tmp_path: Path) -> None:
    original = (
        "## Analysis 2-8\n"
        "### Figure Description\n"
        "Full figure description.\n"
        "### Quantitative Findings\n"
        "Measured values remain.\n"
        "### Biological Interpretation\n"
        "Original unsupported claim.\n"
        "### References\n"
        "- PMID: 12345678\n"
    )
    report = tmp_path / "part2_final.md"
    report.write_text(original, encoding="utf-8")
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "code": "unsupported_mechanistic_interpretation",
                        "severity": "error",
                        "file": "part2_final.md",
                        "section": "## Analysis 2-8",
                        "value": "Original unsupported claim.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    changed = repair_report.repair_report(tmp_path, issues_path, llm=TruncatedSectionLLM())

    assert changed == 0
    assert report.read_text(encoding="utf-8") == original


def test_rejected_section_repair_appends_metadata_without_candidate_text(tmp_path: Path) -> None:
    original = (
        "## Analysis 2-8\n"
        "### Figure Description\n"
        "Full figure description.\n"
        "### Quantitative Findings\n"
        "Measured values remain.\n"
        "### Biological Interpretation\n"
        "Original unsupported claim.\n"
        "### References\n"
        "- PMID: 12345678\n"
    )
    report = tmp_path / "part2_final.md"
    report.write_text(original, encoding="utf-8")
    trace_path = tmp_path / "repair_trace.jsonl"
    trace_path.write_text("", encoding="utf-8")
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "code": "unsupported_mechanistic_interpretation",
                        "severity": "error",
                        "file": "part2_final.md",
                        "section": "## Analysis 2-8",
                        "value": "Original unsupported claim.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    changed = repair_report.repair_report(tmp_path, issues_path, llm=TruncatedSectionLLM())

    assert changed == 0
    rows = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["event"] == "target_repair_rejected"
    assert rows[0]["file"] == "part2_final.md"
    assert rows[0]["section"] == "## Analysis 2-8"
    assert rows[0]["reason"] == "unhandled_repair_target"
    assert "Shortened description" not in trace_path.read_text(encoding="utf-8")


def test_repair_rejects_section_shaped_target_replacement(tmp_path: Path) -> None:
    original = (
        "## Analysis 2-8\n"
        "### Figure Description\n"
        "Full figure description.\n"
        "### Quantitative Findings\n"
        "Measured values remain.\n"
        "### Biological Interpretation\n"
        "Original unsupported claim.\n"
        "### References\n"
        "- PMID: 12345678\n"
    )
    report = tmp_path / "part2_final.md"
    report.write_text(original, encoding="utf-8")
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "code": "unsupported_mechanistic_interpretation",
                        "severity": "error",
                        "file": "part2_final.md",
                        "section": "## Analysis 2-8",
                        "value": "Original unsupported claim.",
                        "target_text": "Original unsupported claim.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    changed = repair_report.repair_report(
        tmp_path,
        issues_path,
        llm=RepairDecisionLLM(
            replacement_text=(
                "## Analysis 2-8\n"
                "### Figure Description\n"
                "Full figure description.\n"
                "### Quantitative Findings\n"
                "Measured values remain.\n"
                "### Biological Interpretation\n"
                "Hedged claim.\n"
                "### References\n"
                "- PMID: 12345678\n"
            )
        ),
    )

    assert changed == 0
    assert report.read_text(encoding="utf-8") == original


def test_repair_rewrites_unresolved_inline_citations_as_exact_claim(
    tmp_path: Path,
) -> None:
    original_claim = (
        "ERBB2 overexpression drives breast-cancer progression and "
        "NRG1-ERBB3 signaling broadly sustains circulating-tumor-cell survival "
        "(PMID: 28174229; PMID: 39753722)."
    )
    replacement = (
        "ERBB2 overexpression is associated with breast-cancer progression "
        "(PMID: 28174229), while NRG1-ERBB3 signaling was required for "
        "circulating-tumor-cell survival in the cited model (PMID: 39753722)."
    )
    original = (
        "## Biology\n"
        "### Context\n"
        "Unrelated context stays put.\n"
        "### Interpretation\n"
        f"{original_claim}\n"
        "A separate sentence stays unchanged.\n"
        "### References\n"
        "- PMID: 28174229\n"
        "- PMID: 39753722\n"
        "## Next\n"
        "Tail text stays put.\n"
    )
    report = tmp_path / "part2_final.md"
    report.write_text(original, encoding="utf-8")
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "severity": "error",
                        "code": "inline_citation_unsupported",
                        "file": "part2_final.md",
                        "section": "## Biology",
                        "source_claim_index": 4,
                        "inline_pmid": "28174229",
                        "value": original_claim,
                        "target_text": original_claim,
                        "evidence": "The cited paper supports association, not causality.",
                    },
                    {
                        "severity": "error",
                        "code": "inline_citation_overclaimed",
                        "file": "part2_final.md",
                        "section": "## Biology",
                        "source_claim_index": 4,
                        "inline_pmid": "39753722",
                        "value": original_claim,
                        "target_text": original_claim,
                        "evidence": "The cited paper is model-specific.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    llm = RepairDecisionLLM(replacement_text=replacement)

    changed = repair_report.repair_report(tmp_path, issues_path, llm=llm)

    text = report.read_text(encoding="utf-8")
    assert changed == 1
    assert llm.calls == 1
    assert original_claim not in text
    assert replacement in text
    assert repair_report._markdown_headings(text) == [
        "## Biology",
        "### Context",
        "### Interpretation",
        "### References",
        "## Next",
    ]
    assert "Unrelated context stays put." in text
    assert "A separate sentence stays unchanged." in text
    assert "Tail text stays put." in text


def test_repair_routes_non_inline_claim_rag_overclaimed_to_exact_claim(
    tmp_path: Path,
) -> None:
    original_claim = "TGFB drives fibrosis despite association-only evidence (PMID: 11111111)."
    replacement = "TGFB is associated with fibrosis in the cited evidence (PMID: 11111111)."
    original = (
        "## Earlier\n"
        f"{original_claim}\n"
        "## Biology\n"
        "### Interpretation\n"
        f"{original_claim}\n"
        "Unrelated section sentence stays unchanged.\n"
        "## Later\n"
        "Tail stays unchanged.\n"
    )
    report = tmp_path / "part1_final.md"
    report.write_text(original, encoding="utf-8")
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "severity": "error",
                        "code": "claim_rag_overclaimed",
                        "file": "part1_final.md",
                        "section": "## Biology",
                        "value": original_claim,
                        "target_text": original_claim,
                        "evidence": "PMID 11111111 supports association only.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    llm = RepairDecisionLLM(replacement_text=replacement)

    changed = repair_report.repair_report(tmp_path, issues_path, llm=llm)

    text = report.read_text(encoding="utf-8")
    assert changed == 1
    assert llm.calls == 1
    assert "Decide how to repair only this exact claim" in llm.prompts[0]
    assert "Rewrite only this markdown section" not in llm.prompts[0]
    assert f"## Earlier\n{original_claim}\n" in text
    assert f"## Biology\n### Interpretation\n{replacement}\n" in text
    assert "Unrelated section sentence stays unchanged." in text
    assert "## Later\nTail stays unchanged.\n" in text


def test_repair_replaces_repeated_part3_spillover_when_issue_count_matches(
    tmp_path: Path,
) -> None:
    claim = (
        "MIF-CD74 is a high-confidence therapeutic target and should be prioritized "
        "for druggability."
    )
    replacement = (
        "MIF-CD74 remains a spatially supported ligand-receptor signal for follow-up."
    )
    original = (
        "## Analysis 3-10: Selected Gene L-R Spatial Evidence\n"
        "### Biological Interpretation\n"
        f"{claim}\n"
        "Unrelated spatial sentence stays unchanged.\n"
        f"{claim}\n"
        f"{claim}\n"
        "## Later\n"
        "Tail stays unchanged.\n"
    )
    report = tmp_path / "part3_final.md"
    report.write_text(original, encoding="utf-8")
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "severity": "error",
                        "code": "part3_therapeutic_spillover",
                        "file": "part3_final.md",
                        "section": "## Analysis 3-10: Selected Gene L-R Spatial Evidence",
                        "value": claim,
                        "target_text": claim,
                    }
                    for _ in range(3)
                ]
            }
        ),
        encoding="utf-8",
    )
    llm = RepairDecisionLLM(replacement_text=replacement)

    changed = repair_report.repair_report(tmp_path, issues_path, llm=llm)

    text = report.read_text(encoding="utf-8")
    assert changed == 1
    assert llm.calls == 1
    assert claim not in text
    assert text.count(replacement) == 3
    assert "Unrelated spatial sentence stays unchanged." in text
    assert "## Later\nTail stays unchanged.\n" in text
    assert repair_report._markdown_headings(text) == [
        "## Analysis 3-10: Selected Gene L-R Spatial Evidence",
        "### Biological Interpretation",
        "## Later",
    ]


def test_repair_refuses_repeated_part3_spillover_when_issue_count_mismatches(
    tmp_path: Path,
) -> None:
    claim = (
        "MIF-CD74 is a high-confidence therapeutic target and should be prioritized "
        "for druggability."
    )
    original = (
        "## Analysis 3-10: Selected Gene L-R Spatial Evidence\n"
        "### Biological Interpretation\n"
        f"{claim}\n"
        f"{claim}\n"
        f"{claim}\n"
    )
    report = tmp_path / "part3_final.md"
    report.write_text(original, encoding="utf-8")
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "severity": "error",
                        "code": "part3_therapeutic_spillover",
                        "file": "part3_final.md",
                        "section": "## Analysis 3-10: Selected Gene L-R Spatial Evidence",
                        "value": claim,
                    }
                    for _ in range(2)
                ]
            }
        ),
        encoding="utf-8",
    )
    llm = RepairDecisionLLM(replacement_text="MIF-CD74 remains a spatial signal.")

    changed = repair_report.repair_report(tmp_path, issues_path, llm=llm)

    assert changed == 0
    assert llm.calls == 0
    assert report.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    ("candidate", "mutation"),
    [
        ("", "accepting deletion"),
        (
            "### Nested Output\nERBB2 overexpression is associated with progression "
            "(PMID: 28174229).",
            "accepting nested section output",
        ),
        (
            "ERBB2 overexpression is associated with progression (PMID: 99999999).",
            "accepting invented evidence",
        ),
        (
            "ERBB2 overexpression is associated with progression (PMID 99999999).",
            "accepting colonless invented evidence",
        ),
    ],
)
def test_repair_rejects_unsafe_exact_claim_replacements(
    tmp_path: Path,
    candidate: str,
    mutation: str,
) -> None:
    assert mutation
    original_claim = (
        "ERBB2 overexpression drives breast-cancer progression "
        "(PMID: 28174229)."
    )
    original = (
        "## Biology\n"
        "### Interpretation\n"
        f"{original_claim}\n"
        "Unrelated sentence stays unchanged.\n"
    )
    report = tmp_path / "part2_final.md"
    report.write_text(original, encoding="utf-8")
    issues_path = tmp_path / "issues.json"
    issues_path.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "severity": "error",
                        "code": "inline_citation_unsupported",
                        "file": "part2_final.md",
                        "section": "## Biology",
                        "source_claim_index": 1,
                        "inline_pmid": "28174229",
                        "value": original_claim,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    changed = repair_report.repair_report(
        tmp_path,
        issues_path,
        llm=RepairDecisionLLM(replacement_text=candidate),
    )

    assert changed == 0
    assert report.read_text(encoding="utf-8") == original


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
                        "target_text": "Factor1 showed significant enrichment for MAPK and EGFR.",
                    },
                    {
                        "code": "unsupported_pathway_factor_significance",
                        "severity": "error",
                        "file": "part2_final.md",
                        "section": "## Analysis 2-8: Pathway Factor Heatmap",
                        "value": "second issue",
                        "target_text": "Factor1 showed significant enrichment for MAPK and EGFR.",
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


def test_repair_prompt_requires_association_language_for_mechanistic_issues() -> None:
    issue = {
        "code": "unsupported_mechanistic_interpretation",
        "severity": "error",
        "file": "part1_final.md",
        "section": "## Analysis 1-5: MISTy",
        "value": "drives",
    }
    prompt = repair_report._build_claim_prompt(
        [issue],
        "The MISTy association confirms that hypoxia drives tumor behavior.",
    )

    assert "Rewrite causal or mechanistic report-derived claims as associations or hypotheses." in prompt
    assert "Do not claim treatment sensitivity, resistance, patient stratification, or therapeutic vulnerability unless the validation issue provides direct support for that exact claim." in prompt


def test_claim_rag_repair_prompt_forbids_new_evidence() -> None:
    prompt = repair_report._build_claim_prompt(
        [
            {
                "code": "claim_rag_overclaimed",
                "severity": "error",
                "file": "part1_final.md",
                "section": "## Analysis 1-1",
                "value": "TGFB drives fibrosis.",
                "evidence": "PMID 11111111 supports association only.",
                "repair_instruction": "Rewrite as association.",
            }
        ],
        "TGFB drives fibrosis.",
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


def test_repair_removes_multiple_unsupported_inline_pmids_when_sibling_supports(
    tmp_path: Path,
) -> None:
    claim = (
        "TGFB is associated with fibrosis "
        "(PMID: 11111111; PMID: 22222222; PMID: 33333333)."
    )
    (tmp_path / "part1_final.md").write_text(f"## Biology\n{claim}\n", encoding="utf-8")
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
                        "value": claim,
                    },
                    {
                        "severity": "error",
                        "code": "inline_citation_unsupported",
                        "file": "part1_final.md",
                        "section": "## Biology",
                        "source_claim_index": 0,
                        "inline_pmid": "33333333",
                        "value": claim,
                    },
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
        {
            "file": "part1_final.md",
            "section": "## Biology",
            "source_claim_index": 0,
            "inline_pmid": "33333333",
            "status": "unsupported",
        },
    ]

    assert repair_report.repair_report(
        tmp_path,
        issues_path,
        llm=FailLLM(),
        claim_validation=rows,
    ) == 1
    repaired = (tmp_path / "part1_final.md").read_text(encoding="utf-8")
    assert repaired == "## Biology\nTGFB is associated with fibrosis (PMID: 11111111).\n"


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
    prompt = repair_report._build_claim_prompt(
        [
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
            }
        ],
        "TNFa annotation may provide context for Factor2 regions.",
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

from __future__ import annotations

import json
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents.middleware import AgentState
from langchain_core.messages import AIMessage


def _agent_state() -> AgentState[Any]:
    return {"messages": []}


@pytest.fixture(autouse=True)
def _stub_claim_rag_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.agents.deep_interpreter import report_guardrails

    monkeypatch.setattr(
        report_guardrails.claim_rag_validation,
        "validate_claims",
        lambda *_args, **_kwargs: {"claims": [], "issues": []},
    )


def _write_required_files(data_dir: Path) -> None:
    (data_dir / "papers.json").write_text('{"papers": []}', encoding="utf-8")
    (data_dir / "part1_final.md").write_text("## Part 1\n", encoding="utf-8")
    (data_dir / "part2_final.md").write_text("## Part 2\n", encoding="utf-8")
    (data_dir / "part3_final.md").write_text("## Part 3\n", encoding="utf-8")


def _write_synthesis_required_files(data_dir: Path) -> None:
    (data_dir / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "12345678", "title": "Supported paper"}]}),
        encoding="utf-8",
    )
    (data_dir / "synthesis.md").write_text(
        "## Executive Summary\n\n"
        "MISTy spatial evidence drives a therapy-resistant subpopulation (PMID: 87654321).\n",
        encoding="utf-8",
    )


def _write_consistency_guardrail_fixture(data_dir: Path, synthesis: str) -> None:
    (data_dir / "papers.json").write_text('{"papers": []}', encoding="utf-8")
    (data_dir / "part1_final.md").write_text("## Part 1\n", encoding="utf-8")
    (data_dir / "part2_final.md").write_text("## Part 2\n", encoding="utf-8")
    (data_dir / "part3_final.md").write_text("## Part 3\n", encoding="utf-8")
    (data_dir / "part4_candidate_selection.json").write_text(
        json.dumps(
            {
                "selected_genes": ["ERBB3"],
                "selected_lr_pairs": [
                    {"interaction": "CDH1^ERBB3", "combinedscore": 0.8141}
                ],
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "part4_therapeutic_synthesis.md").write_text(
        "### 1. Candidate: ERBB3\n"
        "- Score profile: combined 16 = validated 10 + exploratory 6.\n",
        encoding="utf-8",
    )
    (data_dir / "synthesis.md").write_text(synthesis, encoding="utf-8")


def test_run_report_guardrail_skips_when_parts_are_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text('{"papers": []}', encoding="utf-8")
    (tmp_path / "part1_final.md").write_text("## Part 1\n", encoding="utf-8")

    def fail_validate(_data_dir: Path) -> list[dict[str, str]]:
        raise AssertionError("validate_report must not run before all required files exist")

    monkeypatch.setattr(report_guardrails.validate_report_script, "validate_report", fail_validate)

    result = report_guardrails.run_report_guardrail(tmp_path, provider="ollama")

    assert result["status"] == "skipped"
    assert result["missing"] == ["part2_final.md", "part3_final.md"]
    assert not (tmp_path / "report_validation_initial.json").exists()
    assert not (tmp_path / "report_validation_final.json").exists()


def test_run_report_guardrail_fails_when_papers_json_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)
    (tmp_path / "papers.json").unlink()

    def fail_claim_validate(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("claim validation must not run without papers.json")

    monkeypatch.setattr(
        report_guardrails.claim_rag_validation,
        "validate_claims",
        fail_claim_validate,
    )

    result = report_guardrails.run_report_guardrail(tmp_path, provider="ollama")

    initial = json.loads((tmp_path / "report_validation_initial.json").read_text(encoding="utf-8"))
    final = json.loads((tmp_path / "report_validation_final.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["initial_error_count"] == 1
    assert result["final_error_count"] == 1
    assert initial["issues"][0]["code"] == "papers_json_missing"
    assert final["issues"][0]["code"] == "papers_json_missing"
    assert initial["claim_validation"] == []
    assert final["claim_validation"] == []


def test_run_synthesis_guardrail_skips_until_synthesis_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text('{"papers": []}', encoding="utf-8")

    def fail_validate(_data_dir: Path) -> list[dict[str, str]]:
        raise AssertionError("part-level validate_report must not run for synthesis guardrail")

    monkeypatch.setattr(report_guardrails.validate_report_script, "validate_report", fail_validate)

    result = report_guardrails.run_synthesis_guardrail(tmp_path)

    assert result == {"status": "skipped", "missing": ["synthesis.md"]}
    assert not (tmp_path / "synthesis_guardrail_initial.json").exists()
    assert not (tmp_path / "synthesis_guardrail_final.json").exists()


def test_run_synthesis_guardrail_repairs_invalid_pmid_and_softens_overclaim(
    tmp_path: Path,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_synthesis_required_files(tmp_path)

    result = report_guardrails.run_synthesis_guardrail(tmp_path)

    synthesis = (tmp_path / "synthesis.md").read_text(encoding="utf-8")
    initial = json.loads((tmp_path / "synthesis_guardrail_initial.json").read_text(encoding="utf-8"))
    final = json.loads((tmp_path / "synthesis_guardrail_final.json").read_text(encoding="utf-8"))

    assert result["status"] == "passed"
    assert result["artifact"] == "synthesis.md"
    assert result["initial_error_count"] >= 1
    assert result["repair_attempt_count"] == 1
    assert result["changed_claims"] >= 1
    assert result["final_error_count"] == 0
    assert "87654321" not in synthesis
    assert "hypothesis requiring validation" in synthesis.lower()
    assert initial["issue_count"] >= 1
    assert final["issue_count"] >= 1
    assert all(issue["severity"] != "error" for issue in final["issues"])


def test_run_synthesis_guardrail_validates_synthesis_claim_rag_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "11111111", "abstract": "association"}]}),
        encoding="utf-8",
    )
    claim = "MISTy spatial evidence is associated with fibrosis (PMID: 11111111)."
    (tmp_path / "synthesis.md").write_text(
        f"## Cross-Part Themes\n\n{claim}\n",
        encoding="utf-8",
    )
    called_filenames: list[tuple[str, ...]] = []

    def fake_claim_validate(
        _data_dir: Path,
        filenames: tuple[str, ...],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        called_filenames.append(filenames)
        return {
            "claims": [
                {
                    "status": "supported",
                    "claim": claim,
                    "inline_pmid": "11111111",
                }
            ],
            "issues": [],
            "selection": {
                "selected_claim_count": 1,
                "inline_citation_expected_count": 1,
            },
            "inline_citation_coverage": {
                "expected_count": 1,
                "evaluated_count": 1,
                "supported_count": 1,
                "coverage_complete": True,
                "citations": [
                    {
                        "file": "synthesis.md",
                        "section": "## Cross-Part Themes",
                        "source_claim_index": 0,
                        "inline_pmid": "11111111",
                        "claim": claim,
                        "status": "supported",
                    }
                ],
            },
        }

    monkeypatch.setattr(
        report_guardrails.claim_rag_validation, "validate_claims", fake_claim_validate
    )

    result = report_guardrails.run_synthesis_guardrail(tmp_path, provider="ollama")

    initial = json.loads(
        (tmp_path / "synthesis_guardrail_initial.json").read_text(encoding="utf-8")
    )
    final = json.loads(
        (tmp_path / "synthesis_guardrail_final.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "passed"
    assert called_filenames == [("synthesis.md",)]
    assert result["claims_validated"] == 1
    assert result["claims_by_status"]["supported"] == 1
    assert initial["claim_validation"][0]["inline_pmid"] == "11111111"
    assert final["claim_validation"][0]["inline_pmid"] == "11111111"
    assert initial["claim_selection"]["selected_claim_count"] == 1
    assert final["claim_selection"]["selected_claim_count"] == 1
    assert initial["inline_citation_coverage"]["coverage_complete"] is True
    assert final["inline_citation_coverage"]["coverage_complete"] is True


def test_run_synthesis_guardrail_removes_only_unsupported_sibling_citation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text(
        json.dumps(
            {
                "papers": [
                    {"pmid": "11111111", "abstract": "supported"},
                    {"pmid": "22222222", "abstract": "unsupported"},
                ]
            }
        ),
        encoding="utf-8",
    )
    claim = "TGFB is associated with fibrosis (PMID: 11111111; PMID: 22222222)."
    (tmp_path / "synthesis.md").write_text(
        f"## Cross-Part Themes\n\n{claim}\n",
        encoding="utf-8",
    )

    def fake_claim_validate(
        _data_dir: Path,
        filenames: tuple[str, ...],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        assert filenames == ("synthesis.md",)
        text = (tmp_path / "synthesis.md").read_text(encoding="utf-8")
        has_unsupported = "22222222" in text
        claims = [
            {
                "file": "synthesis.md",
                "section": "## Cross-Part Themes",
                "source_claim_index": 0,
                "inline_pmid": "11111111",
                "claim": claim,
                "status": "supported",
                "supporting_pmids": ["11111111"],
                "evidence_quote": "supported",
                "reason": "supported",
            }
        ]
        if has_unsupported:
            claims.append(
                {
                    "file": "synthesis.md",
                    "section": "## Cross-Part Themes",
                    "source_claim_index": 0,
                    "inline_pmid": "22222222",
                    "claim": claim,
                    "status": "unsupported",
                    "supporting_pmids": [],
                    "evidence_quote": "",
                    "reason": "unsupported",
                }
            )
        return {
            "claims": claims,
            "issues": [
                {
                    "code": "inline_citation_unsupported",
                    "severity": "error",
                    "file": "synthesis.md",
                    "section": "## Cross-Part Themes",
                    "source_claim_index": 0,
                    "inline_pmid": "22222222",
                    "value": claim,
                }
            ]
            if has_unsupported
            else [],
            "selection": {"selected_claim_count": len(claims)},
            "inline_citation_coverage": {
                "expected_count": len(claims),
                "evaluated_count": len(claims),
                "supported_count": 1,
                "coverage_complete": not has_unsupported,
                "citations": claims,
            },
        }

    monkeypatch.setattr(
        report_guardrails.claim_rag_validation, "validate_claims", fake_claim_validate
    )

    result = report_guardrails.run_synthesis_guardrail(tmp_path, provider="ollama")

    synthesis = (tmp_path / "synthesis.md").read_text(encoding="utf-8")
    final = json.loads(
        (tmp_path / "synthesis_guardrail_final.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "passed"
    assert "11111111" in synthesis
    assert "22222222" not in synthesis
    assert final["inline_citation_coverage"]["coverage_complete"] is True


def test_run_synthesis_guardrail_hedges_sole_unsupported_inline_citation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "22222222", "abstract": "association only"}]}),
        encoding="utf-8",
    )
    claim = "TGFB drives fibrosis (PMID: 22222222)."
    (tmp_path / "synthesis.md").write_text(
        f"## Cross-Part Themes\n\n{claim}\n",
        encoding="utf-8",
    )

    def fake_claim_validate(
        _data_dir: Path,
        filenames: tuple[str, ...],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        assert filenames == ("synthesis.md",)
        text = (tmp_path / "synthesis.md").read_text(encoding="utf-8")
        hedged = "hypothesis requiring validation" in text.lower()
        citation = {
            "file": "synthesis.md",
            "section": "## Cross-Part Themes",
            "source_claim_index": 0,
            "inline_pmid": "22222222",
            "claim": claim,
            "status": "overclaimed" if not hedged else "supported",
            "supporting_pmids": [],
            "evidence_quote": "association only",
            "reason": "paper supports association only",
        }
        return {
            "claims": [citation],
            "issues": []
            if hedged
            else [
                {
                    "code": "inline_citation_overclaimed",
                    "severity": "error",
                    "file": "synthesis.md",
                    "section": "## Cross-Part Themes",
                    "source_claim_index": 0,
                    "inline_pmid": "22222222",
                    "value": claim,
                }
            ],
            "selection": {"selected_claim_count": 1},
            "inline_citation_coverage": {
                "expected_count": 1,
                "evaluated_count": 1,
                "supported_count": 1 if hedged else 0,
                "coverage_complete": hedged,
                "citations": [citation],
            },
        }

    monkeypatch.setattr(
        report_guardrails.claim_rag_validation, "validate_claims", fake_claim_validate
    )

    result = report_guardrails.run_synthesis_guardrail(tmp_path, provider="ollama")

    synthesis = (tmp_path / "synthesis.md").read_text(encoding="utf-8")
    assert result["status"] == "passed"
    assert "PMID: 22222222" in synthesis
    assert "hypothesis requiring validation" in synthesis.lower()


def test_repair_synthesis_report_rewrites_explicit_inline_contradiction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    claim = (
        "LAMA5 is downregulated and correlates with worse recurrence-free survival "
        "(PMID: 40694271), indicating metastatic progression."
    )
    (tmp_path / "synthesis.md").write_text(claim + "\n", encoding="utf-8")
    issues = [
        {
            "severity": "error",
            "code": "inline_citation_overclaimed",
            "file": "synthesis.md",
            "value": claim,
            "inline_pmid": "40694271",
            "evidence_quote": "Higher LAMA5 expression was associated with better recurrence-free survival.",
            "reason": "The claim incorrectly states worse survival; the evidence states better survival.",
        }
    ]

    model = SimpleNamespace(
        invoke=lambda _prompt: (
            "Higher LAMA5 expression was associated with better recurrence-free "
            "survival (PMID: 40694271). This remains a hypothesis requiring validation."
        )
    )
    monkeypatch.setattr(report_guardrails.repair_report_script, "_create_model", lambda *_: model)

    assert report_guardrails.repair_synthesis_report(tmp_path, issues) == 1
    text = (tmp_path / "synthesis.md").read_text(encoding="utf-8")
    assert "better recurrence-free survival (PMID: 40694271)" in text
    assert "This remains a hypothesis requiring validation." in text
    assert "worse recurrence-free survival" not in text


def test_repair_synthesis_report_falls_back_when_contradiction_rewrite_omits_pmid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    claim = "LAMA5 correlates with worse recurrence-free survival (PMID: 40694271)."
    (tmp_path / "synthesis.md").write_text(claim + "\n", encoding="utf-8")
    issues = [
        {
            "severity": "error",
            "code": "inline_citation_overclaimed",
            "file": "synthesis.md",
            "value": claim,
            "inline_pmid": "40694271",
            "evidence_quote": "Higher LAMA5 expression was associated with better recurrence-free survival.",
            "reason": "The claim incorrectly states worse survival; the evidence states better survival.",
        }
    ]
    model = SimpleNamespace(invoke=lambda _prompt: "Higher LAMA5 expression was better.")
    monkeypatch.setattr(report_guardrails.repair_report_script, "_create_model", lambda *_: model)

    assert report_guardrails.repair_synthesis_report(tmp_path, issues) == 1
    text = (tmp_path / "synthesis.md").read_text(encoding="utf-8")
    assert (
        "Higher LAMA5 expression was associated with better recurrence-free survival "
        "(PMID: 40694271)."
    ) in text
    assert "This remains a hypothesis requiring validation." in text
    assert "worse recurrence-free survival" not in text


def test_run_synthesis_guardrail_repairs_claim_rag_inline_contradiction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import claim_rag_validation, report_guardrails

    real_claim_rag_validation = importlib.reload(claim_rag_validation)
    claim = (
        "LAMA5 is downregulated and correlates with worse recurrence-free survival "
        "(PMID: 40694271), indicating metastatic progression."
    )
    evidence_quote = (
        "Higher LAMA5 expression was associated with better recurrence-free survival."
    )
    (tmp_path / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "40694271", "abstract": evidence_quote}]}),
        encoding="utf-8",
    )
    (tmp_path / "synthesis.md").write_text(
        f"## Integrated Biological Narrative\n\n{claim}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        report_guardrails.claim_rag_validation,
        "validate_claims",
        real_claim_rag_validation.validate_claims,
    )
    monkeypatch.setattr(
        real_claim_rag_validation.search_literature_fulltext,
        "invoke",
        lambda _args: [
            {
                "page_content": evidence_quote,
                "metadata": {"filename": "pmid_40694271.txt"},
                "score": 0.9,
            }
        ],
    )

    class InlineContradictionModel:
        def with_structured_output(self, _schema: Any, *, method: str | None = None) -> Any:
            return self

        def invoke(self, messages: list[Any]) -> Any:
            payload = json.loads(
                messages[0].content.split("Claims and evidence:\n", maxsplit=1)[1]
            )
            item = payload[0]
            overclaimed = "worse recurrence-free survival" in item["claim"]
            return real_claim_rag_validation.ClaimJudgmentBatch(
                judgments=[
                    real_claim_rag_validation.ClaimJudgment(
                        claim_index=item["claim_index"],
                        status="overclaimed" if overclaimed else "supported",
                        reason=(
                            "The claim incorrectly states worse survival; the evidence states better survival."
                            if overclaimed
                            else "The corrected claim matches the supplied evidence."
                        ),
                        supporting_pmids=["40694271"],
                        evidence_quote=evidence_quote,
                    )
                ]
            )

    monkeypatch.setattr(
        real_claim_rag_validation,
        "_create_judge_llm",
        lambda *_args, **_kwargs: InlineContradictionModel(),
    )
    repair_model_call_count = 0
    repair_model_providers: list[str | None] = []

    def rewrite_to_still_contradicted(_prompt: str) -> str:
        nonlocal repair_model_call_count
        repair_model_call_count += 1
        return "LAMA5 correlates with worse recurrence-free survival (PMID: 40694271)."

    repair_model = SimpleNamespace(invoke=rewrite_to_still_contradicted)

    def create_repair_model(provider: str | None) -> Any:
        repair_model_providers.append(provider)
        return repair_model

    monkeypatch.setattr(
        report_guardrails.repair_report_script,
        "_create_model",
        create_repair_model,
    )

    result = report_guardrails.run_synthesis_guardrail(tmp_path, provider="ollama")

    initial = json.loads(
        (tmp_path / "synthesis_guardrail_initial.json").read_text(encoding="utf-8")
    )
    text = (tmp_path / "synthesis.md").read_text(encoding="utf-8")
    assert repair_model_call_count == 1
    assert repair_model_providers == ["ollama"]
    assert result["status"] == "passed"
    assert result["repair_attempt_count"] == 2
    assert initial["issues"][0]["reason"].startswith("The claim incorrectly states")
    assert initial["issues"][0]["evidence_quote"] == evidence_quote
    assert "better recurrence-free survival (PMID: 40694271)" in text
    assert "worse recurrence-free survival" not in text


def test_run_synthesis_guardrail_repairs_consistency_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_consistency_guardrail_fixture(
        tmp_path,
        "### 1. ERBB3 (Combined Score: 15)\n",
    )

    result = report_guardrails.run_synthesis_guardrail(tmp_path)

    assert result["status"] == "passed"
    assert result["repair_attempt_count"] == 1
    assert result["consistency_issue_count"] == 1
    assert "Combined Score: 16" in (tmp_path / "synthesis.md").read_text(
        encoding="utf-8"
    )
    final = json.loads(
        (tmp_path / "synthesis_guardrail_final.json").read_text(encoding="utf-8")
    )
    assert final["claim_validation"] == []
    assert final["consistency_validation"]
    assert not [issue for issue in final["issues"] if issue["severity"] == "error"]


def test_run_synthesis_guardrail_fails_unresolved_consistency_issue(
    tmp_path: Path,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    synthesis = "### 1. EGFR (Combined Score: 15)\n"
    _write_consistency_guardrail_fixture(tmp_path, synthesis)

    result = report_guardrails.run_synthesis_guardrail(tmp_path)

    final = json.loads(
        (tmp_path / "synthesis_guardrail_final.json").read_text(encoding="utf-8")
    )
    assert (tmp_path / "synthesis.md").read_text(encoding="utf-8") == synthesis
    assert result["status"] == "failed"
    assert result["repair_attempt_count"] == 1
    assert final["issues"][-1]["code"] == "synthesis_consistency_unresolved"


def test_run_synthesis_guardrail_rejects_html_fragment_synthesis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    def fail_if_called(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("semantic validation must wait for valid Markdown")

    monkeypatch.setattr(
        report_guardrails.claim_rag_validation,
        "validate_claims",
        fail_if_called,
    )
    monkeypatch.setattr(
        report_guardrails.synthesis_consistency_validation,
        "validate_synthesis_consistency",
        fail_if_called,
    )

    (tmp_path / "papers.json").write_text('{"papers": []}', encoding="utf-8")
    (tmp_path / "synthesis.md").write_text(
        '<div class="summary-box"><p>HTML belongs in the rendered report.</p></div>\n',
        encoding="utf-8",
    )

    result = report_guardrails.run_synthesis_guardrail(tmp_path)
    final = json.loads((tmp_path / "synthesis_guardrail_final.json").read_text(encoding="utf-8"))

    assert result["status"] == "failed"
    assert result["repair_attempt_count"] == 1
    assert result["final_error_count"] == 1
    assert final["issues"][0]["code"] == "synthesis_not_markdown"


def test_run_synthesis_guardrail_allows_neutral_clinical_context(
    tmp_path: Path,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "12345678", "title": "Supported paper"}]}),
        encoding="utf-8",
    )
    synthesis = (
        "## Executive Summary\n\n"
        "MISTy spatial analysis used clinical metadata from the treatment cohort "
        "(PMID: 12345678).\n"
    )
    (tmp_path / "synthesis.md").write_text(synthesis, encoding="utf-8")

    result = report_guardrails.run_synthesis_guardrail(tmp_path)

    assert result["status"] == "passed"
    assert result["changed_claims"] == 0
    assert result["repair_attempt_count"] == 0
    assert result["initial_error_count"] == 0
    assert result["final_error_count"] == 0
    assert (tmp_path / "synthesis.md").read_text(encoding="utf-8") == synthesis


def test_run_synthesis_guardrail_repairs_duplicate_overclaims_once_each(
    tmp_path: Path,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "12345678", "title": "Supported paper"}]}),
        encoding="utf-8",
    )
    claim = "MISTy spatial evidence drives a therapy-resistant subpopulation (PMID: 12345678)."
    (tmp_path / "synthesis.md").write_text(
        f"## Executive Summary\n\n{claim}\n\n{claim}\n",
        encoding="utf-8",
    )

    result = report_guardrails.run_synthesis_guardrail(tmp_path)
    synthesis = (tmp_path / "synthesis.md").read_text(encoding="utf-8")

    assert result["status"] == "passed"
    assert result["changed_claims"] == 2
    assert synthesis.count("hypothesis requiring validation") == 2
    assert f"{claim} this remains a hypothesis requiring validation. this remains" not in synthesis


def test_run_synthesis_guardrail_allows_negated_therapeutic_limitation(
    tmp_path: Path,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "12345678", "title": "Supported paper"}]}),
        encoding="utf-8",
    )
    synthesis = (
        "## Limitations\n\n"
        "MISTy spatial evidence does not establish a therapeutic vulnerability "
        "(PMID: 12345678).\n"
    )
    (tmp_path / "synthesis.md").write_text(synthesis, encoding="utf-8")

    result = report_guardrails.run_synthesis_guardrail(tmp_path)

    assert result["status"] == "passed"
    assert result["changed_claims"] == 0
    assert result["initial_error_count"] == 0
    assert result["final_error_count"] == 0
    assert (tmp_path / "synthesis.md").read_text(encoding="utf-8") == synthesis


def test_run_synthesis_guardrail_allows_negated_therapeutic_proof_limitation(
    tmp_path: Path,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    (tmp_path / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": "12345678", "title": "Supported paper"}]}),
        encoding="utf-8",
    )
    synthesis = (
        "## Limitations\n\n"
        "MISTy spatial evidence does not prove therapeutic vulnerability "
        "(PMID: 12345678).\n"
    )
    (tmp_path / "synthesis.md").write_text(synthesis, encoding="utf-8")

    result = report_guardrails.run_synthesis_guardrail(tmp_path)

    assert result["status"] == "passed"
    assert result["changed_claims"] == 0
    assert result["initial_error_count"] == 0
    assert result["final_error_count"] == 0
    assert (tmp_path / "synthesis.md").read_text(encoding="utf-8") == synthesis


def test_run_synthesis_guardrail_retries_up_to_three_repairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_synthesis_required_files(tmp_path)
    validate_count = 0
    repair_count = 0

    def fake_validate(_data_dir: Path) -> list[dict[str, str]]:
        nonlocal validate_count
        validate_count += 1
        severity = "warning" if validate_count == 4 else "error"
        return [{"severity": severity, "code": "bounded_synthesis_retry"}]

    def fake_repair(
        _data_dir: Path,
        _issues: list[dict[str, str]],
        _claim_validation: list[dict[str, Any]] | None = None,
        *,
        provider: str | None = None,
        deterministic_contradictions: bool = False,
    ) -> int:
        _ = provider
        _ = deterministic_contradictions
        nonlocal repair_count
        repair_count += 1
        return 1

    monkeypatch.setattr(report_guardrails, "validate_synthesis_report", fake_validate)
    monkeypatch.setattr(report_guardrails, "repair_synthesis_report", fake_repair)

    result = report_guardrails.run_synthesis_guardrail(tmp_path)

    assert validate_count == 4
    assert repair_count == 3
    assert result["status"] == "passed"
    assert result["repair_attempt_count"] == 3
    assert result["changed_claims"] == 3
    assert result["final_error_count"] == 0


def test_run_synthesis_guardrail_terminally_repairs_new_final_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_synthesis_required_files(tmp_path)
    persistent = {
        "severity": "error",
        "code": "existing_error",
        "file": "synthesis.md",
        "section": "## Existing",
        "value": "Existing error",
    }
    latent = {
        "severity": "warning",
        "code": "claim_rag_unverifiable",
        "file": "synthesis.md",
        "section": "## Clinical/Biological Implications",
        "value": "Analysis-derived claim",
    }
    promoted = {
        **latent,
        "severity": "error",
        "code": "claim_rag_unsupported",
    }
    repaired = {
        **latent,
        "code": "claim_rag_hypothesis_warning",
    }
    validations = [
        [persistent, latent],
        [persistent, latent],
        [persistent, latent],
        [promoted],
        [repaired],
    ]
    validate_count = 0
    repaired_issue_batches: list[list[dict[str, str]]] = []

    def fake_validate(
        _data_dir: Path,
        *,
        provider: str | None,
        claim_cache: dict[str, list[dict[str, Any]]],
    ) -> tuple[
        list[dict[str, str]],
        list[dict[str, Any]],
        dict[str, list[dict[str, Any]]],
        None,
        None,
    ]:
        nonlocal validate_count
        _ = provider, claim_cache
        issues = validations[validate_count]
        validate_count += 1
        return issues, [], {"issues": [], "results": []}, None, None

    def fake_repair(
        _data_dir: Path,
        issues: list[dict[str, str]],
        _claim_validation: list[dict[str, Any]] | None = None,
        *,
        provider: str | None = None,
        deterministic_contradictions: bool = False,
    ) -> int:
        _ = provider
        repaired_issue_batches.append(issues)
        if len(repaired_issue_batches) == 4:
            assert deterministic_contradictions is True
        return 1

    monkeypatch.setattr(report_guardrails, "_validate_synthesis_guardrails", fake_validate)
    monkeypatch.setattr(report_guardrails, "repair_synthesis_report", fake_repair)

    result = report_guardrails.run_synthesis_guardrail(tmp_path, provider="ollama")

    assert validate_count == 5
    assert len(repaired_issue_batches) == 4
    assert repaired_issue_batches[-1] == [promoted]
    assert result["status"] == "passed"
    assert result["repair_attempt_count"] == 3
    assert result["terminal_repair_count"] == 1
    assert result["final_error_count"] == 0


def test_run_synthesis_guardrail_does_not_terminally_retry_persistent_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_synthesis_required_files(tmp_path)
    persistent = {
        "severity": "error",
        "code": "claim_rag_unsupported",
        "file": "synthesis.md",
        "section": "## Clinical/Biological Implications",
        "value": "Persistent unsupported claim",
    }
    validate_count = 0
    repair_count = 0

    def fake_validate(
        _data_dir: Path,
        *,
        provider: str | None,
        claim_cache: dict[str, list[dict[str, Any]]],
    ) -> tuple[
        list[dict[str, str]],
        list[dict[str, Any]],
        dict[str, list[dict[str, Any]]],
        None,
        None,
    ]:
        nonlocal validate_count
        _ = provider, claim_cache
        validate_count += 1
        return [persistent], [], {"issues": [], "results": []}, None, None

    def fake_repair(
        _data_dir: Path,
        _issues: list[dict[str, str]],
        _claim_validation: list[dict[str, Any]] | None = None,
        *,
        provider: str | None = None,
        deterministic_contradictions: bool = False,
    ) -> int:
        nonlocal repair_count
        _ = provider, deterministic_contradictions
        repair_count += 1
        return 1

    monkeypatch.setattr(report_guardrails, "_validate_synthesis_guardrails", fake_validate)
    monkeypatch.setattr(report_guardrails, "repair_synthesis_report", fake_repair)

    result = report_guardrails.run_synthesis_guardrail(tmp_path)

    assert validate_count == 4
    assert repair_count == 3
    assert result["status"] == "failed"
    assert result["repair_attempt_count"] == 3
    assert result["terminal_repair_count"] == 0
    assert result["final_error_count"] == 1


def test_run_report_guardrail_stops_after_first_successful_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)
    calls: list[str] = []

    def fake_validate(_data_dir: Path) -> list[dict[str, str]]:
        calls.append("validate")
        if calls.count("validate") == 1:
            return [
                {
                    "severity": "error",
                    "code": "pmid_not_in_papers",
                    "file": "part1_final.md",
                    "section": "",
                    "value": "999",
                }
            ]
        return [
            {
                "severity": "warning",
                "code": "mechanistic_overclaim",
                "file": "part1_final.md",
                "section": "## Part 1",
                "value": "hypothesis",
            }
        ]

    def fake_repair(
        data_dir: Path,
        issues_path: Path,
        *,
        provider: str | None = None,
        llm=None,
        claim_validation: list[dict[str, Any]] | None = None,
    ) -> int:
        calls.append("repair")
        assert data_dir == tmp_path.resolve()
        assert issues_path == tmp_path.resolve() / "report_validation_initial.json"
        assert provider == "ollama"
        assert llm is None
        assert claim_validation == []
        return 1

    monkeypatch.setattr(report_guardrails.validate_report_script, "validate_report", fake_validate)
    monkeypatch.setattr(report_guardrails.repair_report_script, "repair_report", fake_repair)

    result = report_guardrails.run_report_guardrail(tmp_path, provider="ollama")

    assert calls == ["validate", "repair", "validate"]
    assert result == {
        "status": "passed",
        "initial_issue_count": 1,
        "initial_error_count": 1,
        "repair_attempt_count": 1,
        "terminal_repair_count": 0,
        "changed_sections": 1,
        "final_issue_count": 1,
        "final_error_count": 0,
    }
    initial = json.loads((tmp_path / "report_validation_initial.json").read_text(encoding="utf-8"))
    final = json.loads((tmp_path / "report_validation_final.json").read_text(encoding="utf-8"))
    assert initial["issue_count"] == 1
    assert final["issue_count"] == 1
    assert final["issues"][0]["severity"] == "warning"


def test_run_report_guardrail_merges_claim_errors_and_revalidates_after_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)
    claim_calls = 0

    monkeypatch.setattr(
        report_guardrails.validate_report_script,
        "validate_report",
        lambda _data_dir: [],
    )

    def fake_claim_validate(*_args, **_kwargs):
        nonlocal claim_calls
        claim_calls += 1
        if claim_calls == 1:
            return {
                "claims": [{"status": "overclaimed", "claim": "TGFB drives fibrosis."}],
                "issues": [
                    {
                        "code": "claim_rag_overclaimed",
                        "severity": "error",
                        "file": "part1_final.md",
                        "section": "## Part 1",
                        "value": "TGFB drives fibrosis.",
                        "evidence": "The paper supports association only.",
                        "repair_instruction": "Rewrite as association.",
                    }
                ],
            }
        return {
            "claims": [{"status": "supported", "claim": "TGFB is associated with fibrosis."}],
            "issues": [],
        }

    repair_calls = 0

    def fake_repair(
        *_args: Any,
        claim_validation: list[dict[str, Any]] | None = None,
        **_kwargs: Any,
    ) -> int:
        nonlocal repair_calls
        repair_calls += 1
        assert claim_validation == [
            {"status": "overclaimed", "claim": "TGFB drives fibrosis."}
        ]
        return 1

    monkeypatch.setattr(
        report_guardrails.claim_rag_validation, "validate_claims", fake_claim_validate
    )
    monkeypatch.setattr(
        report_guardrails.repair_report_script, "repair_report", fake_repair
    )

    result = report_guardrails.run_report_guardrail(tmp_path, provider="ollama")

    initial = json.loads(
        (tmp_path / "report_validation_initial.json").read_text(encoding="utf-8")
    )
    final = json.loads(
        (tmp_path / "report_validation_final.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "passed"
    assert result["repair_attempt_count"] == 1
    assert claim_calls == 2
    assert repair_calls == 1
    assert initial["issues"][0]["code"] == "claim_rag_overclaimed"
    assert initial["claim_validation"][0]["status"] == "overclaimed"
    assert final["claim_validation"][0]["status"] == "supported"


def test_run_report_guardrail_writes_claim_selection_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)
    monkeypatch.setattr(
        report_guardrails.validate_report_script,
        "validate_report",
        lambda _data_dir: [],
    )
    monkeypatch.setattr(
        report_guardrails.claim_rag_validation,
        "validate_claims",
        lambda *_args, **_kwargs: {
            "claims": [],
            "issues": [],
            "selection": {
                "extracted_claim_count": 3,
                "selected_claim_count": 2,
                "skipped_claims": [
                    {
                        "file": "part1_final.md",
                        "section": "## Analysis 1-1",
                        "index": 1,
                        "claim": "The spatial pattern contains three clusters (PMID: 11111111).",
                        "reason": "outside_high_risk_scope",
                    }
                ],
            },
        },
    )

    report_guardrails.run_report_guardrail(tmp_path, provider="ollama")

    initial = json.loads(
        (tmp_path / "report_validation_initial.json").read_text(encoding="utf-8")
    )
    assert initial["claim_selection"]["selected_claim_count"] == 2
    assert initial["claim_selection"]["skipped_claims"][0]["reason"] == (
        "outside_high_risk_scope"
    )


def test_run_report_guardrail_preserves_claim_selection_after_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)
    validate_calls = 0
    selections = [
        {
            "extracted_claim_count": 3,
            "selected_claim_count": 1,
            "skipped_claims": [{"reason": "outside_high_risk_scope"}],
            "checkpoint_hits": 1,
            "judgment_batch_count": 1,
            "single_claim_fallback_count": 0,
        },
        {
            "extracted_claim_count": 2,
            "selected_claim_count": 1,
            "skipped_claims": [{"reason": "after_repair_low_risk"}],
            "checkpoint_hits": 1,
            "judgment_batch_count": 1,
            "single_claim_fallback_count": 0,
        },
    ]

    def fake_validate(_data_dir: Path) -> list[dict[str, str]]:
        nonlocal validate_calls
        validate_calls += 1
        if validate_calls == 1:
            return [{"severity": "error", "code": "pmid_not_in_papers"}]
        return []

    claim_calls = 0

    def fake_claim_validate(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal claim_calls
        selection = selections[claim_calls]
        claim_calls += 1
        return {"claims": [], "issues": [], "selection": selection}

    monkeypatch.setattr(
        report_guardrails.validate_report_script, "validate_report", fake_validate
    )
    monkeypatch.setattr(
        report_guardrails.claim_rag_validation, "validate_claims", fake_claim_validate
    )
    monkeypatch.setattr(
        report_guardrails.repair_report_script,
        "repair_report",
        lambda *_args, **_kwargs: 1,
    )

    result = report_guardrails.run_report_guardrail(tmp_path, provider="ollama")

    final = json.loads(
        (tmp_path / "report_validation_final.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "passed"
    assert result["repair_attempt_count"] == 1
    assert claim_calls == 2
    assert final["claim_selection"] == selections[1]


def test_run_report_guardrail_retries_up_to_three_repairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)
    calls: list[str] = []

    def fake_validate(_data_dir: Path) -> list[dict[str, str]]:
        calls.append("validate")
        severity = "warning" if calls.count("validate") == 4 else "error"
        return [{"severity": severity, "code": "bounded_retry"}]

    def fake_repair(
        data_dir: Path,
        issues_path: Path,
        *,
        provider: str | None = None,
        llm=None,
        claim_validation: list[dict[str, Any]] | None = None,
    ) -> int:
        calls.append("repair")
        assert data_dir == tmp_path.resolve()
        assert issues_path in {
            tmp_path.resolve() / "report_validation_initial.json",
            tmp_path.resolve() / "report_validation_final.json",
        }
        assert claim_validation == []
        return 1

    monkeypatch.setattr(report_guardrails.validate_report_script, "validate_report", fake_validate)
    monkeypatch.setattr(report_guardrails.repair_report_script, "repair_report", fake_repair)

    result = report_guardrails.run_report_guardrail(tmp_path, provider="ollama")

    assert calls == [
        "validate",
        "repair",
        "validate",
        "repair",
        "validate",
        "repair",
        "validate",
    ]
    assert result["status"] == "passed"
    assert result["repair_attempt_count"] == 3
    assert result["changed_sections"] == 3
    assert result["final_error_count"] == 0


def test_run_report_guardrail_terminally_repairs_new_final_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)
    persistent = {
        "severity": "error",
        "code": "existing_error",
        "file": "part2_final.md",
        "section": "## Existing",
        "value": "Existing error",
    }
    latent = {
        "severity": "warning",
        "code": "claim_rag_unverifiable",
        "file": "part2_final.md",
        "section": "## Analysis",
        "value": "Lrig1 directionality claim.",
    }
    promoted = {
        **latent,
        "severity": "error",
        "code": "claim_rag_unsupported",
    }
    validations = [
        [persistent, latent],
        [persistent, latent],
        [persistent, latent],
        [promoted],
        [],
    ]
    validate_count = 0
    repaired_issue_batches: list[list[dict[str, str]]] = []

    def fake_validate(
        _data_dir: Path,
        *,
        provider: str | None,
        claim_cache: dict[str, list[dict[str, Any]]],
    ) -> tuple[list[dict[str, str]], list[dict[str, Any]], None, None]:
        nonlocal validate_count
        _ = provider, claim_cache
        issues = validations[validate_count]
        validate_count += 1
        return issues, [], None, None

    def fake_repair(
        _data_dir: Path,
        issues_path: Path,
        *,
        provider: str | None = None,
        llm=None,
        claim_validation: list[dict[str, Any]] | None = None,
    ) -> int:
        _ = provider, llm, claim_validation
        payload = json.loads(issues_path.read_text(encoding="utf-8"))
        repaired_issue_batches.append(payload["issues"])
        return 1

    monkeypatch.setattr(report_guardrails, "_validate_part_reports", fake_validate)
    monkeypatch.setattr(report_guardrails.repair_report_script, "repair_report", fake_repair)

    result = report_guardrails.run_report_guardrail(tmp_path, provider="ollama")

    assert validate_count == 5
    assert len(repaired_issue_batches) == 4
    assert repaired_issue_batches[-1] == [promoted]
    assert result["status"] == "passed"
    assert result["repair_attempt_count"] == 3
    assert result["terminal_repair_count"] == 1
    assert result["final_error_count"] == 0


def test_run_report_guardrail_does_not_terminally_retry_persistent_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)
    persistent = {
        "severity": "error",
        "code": "claim_rag_unsupported",
        "file": "part2_final.md",
        "section": "## Analysis",
        "value": "Persistent unsupported claim.",
    }
    validate_count = 0
    repair_count = 0

    def fake_validate(
        _data_dir: Path,
        *,
        provider: str | None,
        claim_cache: dict[str, list[dict[str, Any]]],
    ) -> tuple[list[dict[str, str]], list[dict[str, Any]], None, None]:
        nonlocal validate_count
        _ = provider, claim_cache
        validate_count += 1
        return [persistent], [], None, None

    def fake_repair(
        _data_dir: Path,
        _issues_path: Path,
        *,
        provider: str | None = None,
        llm=None,
        claim_validation: list[dict[str, Any]] | None = None,
    ) -> int:
        nonlocal repair_count
        _ = provider, llm, claim_validation
        repair_count += 1
        return 1

    monkeypatch.setattr(report_guardrails, "_validate_part_reports", fake_validate)
    monkeypatch.setattr(report_guardrails.repair_report_script, "repair_report", fake_repair)

    result = report_guardrails.run_report_guardrail(tmp_path)

    assert validate_count == 4
    assert repair_count == 3
    assert result["status"] == "failed"
    assert result["repair_attempt_count"] == 3
    assert result["terminal_repair_count"] == 0
    assert result["final_error_count"] == 1


def test_run_report_guardrail_records_remaining_errors_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.agents.deep_interpreter import report_guardrails

    _write_required_files(tmp_path)
    validate_count = 0
    repair_count = 0

    def fake_validate(_data_dir: Path) -> list[dict[str, str]]:
        nonlocal validate_count
        validate_count += 1
        return [{"severity": "error", "code": "still_bad"}]

    def fake_repair(
        data_dir: Path,
        issues_path: Path,
        *,
        provider: str | None = None,
        llm=None,
        claim_validation: list[dict[str, Any]] | None = None,
    ) -> int:
        nonlocal repair_count
        repair_count += 1
        assert claim_validation == []
        return 0

    monkeypatch.setattr(report_guardrails.validate_report_script, "validate_report", fake_validate)
    monkeypatch.setattr(report_guardrails.repair_report_script, "repair_report", fake_repair)

    result = report_guardrails.run_report_guardrail(tmp_path)

    assert validate_count == 2
    assert repair_count == 1
    assert result["status"] == "failed"
    assert result["repair_attempt_count"] == 1
    assert result["final_error_count"] == 1
    final = json.loads((tmp_path / "report_validation_final.json").read_text(encoding="utf-8"))
    assert final["issues"] == [{"severity": "error", "code": "still_bad"}]


def test_report_guardrail_middleware_returns_message_when_guardrail_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter.middleware.report_guardrail import ReportGuardrailMiddleware

    def fake_run(data_dir: Path, *, provider: str | None = None) -> dict[str, object]:
        assert data_dir == tmp_path
        assert provider == "ollama"
        return {
            "status": "passed",
            "initial_issue_count": 1,
            "initial_error_count": 1,
            "changed_sections": 1,
            "final_issue_count": 0,
            "final_error_count": 0,
        }

    monkeypatch.setattr(
        "src.agents.deep_interpreter.middleware.report_guardrail.run_report_guardrail",
        fake_run,
    )

    result = ReportGuardrailMiddleware(data_dir=tmp_path, provider="ollama").after_agent(
        _agent_state(), None
    )

    assert result is not None
    [message] = result["messages"]
    assert isinstance(message, AIMessage)
    payload = json.loads(str(message.content))
    assert payload["report_guardrail"]["status"] == "passed"
    assert payload["report_guardrail"]["changed_sections"] == 1


def test_report_guardrail_middleware_is_silent_when_guardrail_skips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter.middleware.report_guardrail import ReportGuardrailMiddleware

    def fake_run(data_dir: Path, *, provider: str | None = None) -> dict[str, object]:
        return {"status": "skipped", "missing": ["part3_final.md"]}

    monkeypatch.setattr(
        "src.agents.deep_interpreter.middleware.report_guardrail.run_report_guardrail",
        fake_run,
    )

    result = ReportGuardrailMiddleware(data_dir=tmp_path).after_agent(_agent_state(), None)

    assert result is None


def _failed_guardrail_result() -> dict[str, object]:
    return {
        "status": "failed",
        "initial_issue_count": 1,
        "initial_error_count": 1,
        "repair_attempt_count": 3,
        "changed_sections": 0,
        "final_issue_count": 1,
        "final_error_count": 1,
    }


def test_report_guardrail_middleware_raises_when_hard_errors_remain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter.middleware.report_guardrail import ReportGuardrailMiddleware

    monkeypatch.setattr(
        "src.agents.deep_interpreter.middleware.report_guardrail.run_report_guardrail",
        lambda *_args, **_kwargs: _failed_guardrail_result(),
    )

    with pytest.raises(
        RuntimeError,
        match=r"Report guardrail failed with 1 hard error\(s\).*report_validation_final\.json",
    ):
        ReportGuardrailMiddleware(data_dir=tmp_path).after_agent(_agent_state(), None)


def test_report_guardrail_middleware_export_uses_env_data_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter.middleware import ReportGuardrailMiddleware

    seen: list[Path] = []

    def fake_run(data_dir: Path, *, provider: str | None = None) -> dict[str, object]:
        seen.append(data_dir)
        return {
            "status": "passed",
            "initial_issue_count": 0,
            "initial_error_count": 0,
            "changed_sections": 0,
            "final_issue_count": 0,
            "final_error_count": 0,
        }

    monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "src.agents.deep_interpreter.middleware.report_guardrail.run_report_guardrail",
        fake_run,
    )

    result = ReportGuardrailMiddleware().after_agent(_agent_state(), None)

    assert result is not None
    assert seen == [tmp_path]


@pytest.mark.asyncio
async def test_report_guardrail_middleware_async_hook_raises_when_hard_errors_remain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.deep_interpreter.middleware.report_guardrail import ReportGuardrailMiddleware

    monkeypatch.setattr(
        "src.agents.deep_interpreter.middleware.report_guardrail.run_report_guardrail",
        lambda *_args, **_kwargs: _failed_guardrail_result(),
    )

    with pytest.raises(
        RuntimeError,
        match=r"Report guardrail failed with 1 hard error\(s\).*report_validation_final\.json",
    ):
        await ReportGuardrailMiddleware(data_dir=tmp_path).aafter_agent(_agent_state(), None)


def test_get_subagents_attaches_report_guardrail_only_to_interpreter() -> None:
    from src.agents.deep_interpreter.middleware import ReportGuardrailMiddleware
    from src.agents.deep_interpreter.subagents.configs import get_subagents

    subagents = get_subagents(
        data_dir="/tmp/deepmast-report-guardrail-test",
        provider="ollama",
    )
    by_name = {subagent["name"]: subagent for subagent in subagents}

    interpreter_middleware = by_name["interpreter"]["middleware"]
    report_guardrails = [
        middleware
        for middleware in interpreter_middleware
        if isinstance(middleware, ReportGuardrailMiddleware)
    ]
    assert len(report_guardrails) == 1
    assert report_guardrails[0]._provider == "ollama"

    for name in ("planner", "searcher", "reporter"):
        assert not any(
            isinstance(middleware, ReportGuardrailMiddleware)
            for middleware in by_name[name].get("middleware", [])
        )


def test_standalone_subagent_graph_uses_configured_middleware(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeAgent:
        async def ainvoke(
            self,
            state: dict[str, Any],
            config: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return {"state": state, "config": config}

        def with_config(self, config: dict[str, int]) -> SimpleNamespace:
            return SimpleNamespace(
                config=config,
                ainvoke=self.ainvoke,
                reporter_recovery_enabled=False,
            )

    def fake_create_agent(*_args: Any, **kwargs: Any) -> FakeAgent:
        calls.append(kwargs)
        return FakeAgent()

    monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("langchain.agents.create_agent", fake_create_agent)
    monkeypatch.setattr(
        "src.agents.deep_interpreter.agent.create_deep_interpreter_agent",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "src.agents.deep_interpreter.wrapper_agent.DeepInterpreterWrapperAgent",
        lambda *_args, **_kwargs: SimpleNamespace(graph=SimpleNamespace()),
    )
    monkeypatch.setattr(
        "src.agents.model.create_llm",
        lambda *_args, **_kwargs: object(),
    )

    sys.modules.pop("src.agents.deep_interpreter.graph_builder", None)
    graph_builder = importlib.import_module("src.agents.deep_interpreter.graph_builder")
    from src.agents.deep_interpreter.middleware import (
        ReportGuardrailMiddleware,
        WriteFileArgGuardMiddleware,
    )

    graph = graph_builder.create_subagent_graph("interpreter", provider="ollama")

    call = calls[-1]
    middleware = call["middleware"]
    assert graph.config == {"recursion_limit": 200}
    assert any(isinstance(item, WriteFileArgGuardMiddleware) for item in middleware)
    report_guardrails = [item for item in middleware if isinstance(item, ReportGuardrailMiddleware)]
    assert len(report_guardrails) == 1
    assert report_guardrails[0]._resolved_data_dir() == tmp_path.resolve()
    assert report_guardrails[0]._provider == "ollama"
    assert getattr(graph, "reporter_recovery_enabled", False) is False

    graph = graph_builder.create_subagent_graph("reporter", provider="ollama")

    call = calls[-1]
    middleware = call["middleware"]
    assert graph.config == {"recursion_limit": 200}
    assert getattr(graph, "reporter_recovery_enabled", False) is True
    assert any(isinstance(item, WriteFileArgGuardMiddleware) for item in middleware)
    assert not any(isinstance(item, ReportGuardrailMiddleware) for item in middleware)

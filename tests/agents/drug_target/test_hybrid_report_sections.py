from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.drug_target.hybrid_report_sections import (
    REPORT_SECTIONS_FILENAME,
    ReportRecommendationsPayload,
    build_ollama_candidate_followup_specs,
    build_ollama_candidate_followups,
    build_ollama_report_recommendations,
    canonicalize_report_sections,
)
from src.agents.drug_target.tools.hypothesis_schema import (
    canonicalize_hypothesis_report,
    persist_hypothesis_report,
    validate_canonical_hypothesis_report,
)


def _write_evidence(tmp_path: Path) -> Path:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "CD4"}, {"gene": "FN1"}]}),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_filter_results.json").write_text(
        json.dumps(
            [
                {"ligand": "FN1", "receptor": "CD4", "passed": True},
                {"ligand": "FN1", "receptor": "SDC2", "passed": True},
            ]
        ),
        encoding="utf-8",
    )
    for filename in (
        "stage1_FN1--CD4.json",
        "stage1_FN1--SDC2.json",
        "stage3_CD4.json",
        "stage3_FN1.json",
    ):
        (evidence_dir / filename).write_text("{}", encoding="utf-8")
    return evidence_dir


def _write_renderer_evidence(tmp_path: Path) -> Path:
    evidence_dir = _write_evidence(tmp_path)
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps(
            {
                "disease": "IPF",
                "rubric_assessment": [
                    {
                        "gene": "CD4",
                        "classification": "validated_target",
                        "priority": "high",
                        "combined_total": 12,
                        "stage3_candidate": True,
                    },
                    {
                        "gene": "FN1",
                        "classification": "exploratory_target",
                        "priority": "medium",
                        "combined_total": 8,
                        "stage3_candidate": True,
                    },
                ],
                "stage3_candidates": [{"gene": "CD4"}, {"gene": "FN1"}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "lr_candidates.json").write_text(
        json.dumps({"pairs": [{"ligand": "FN1", "receptor": "CD4"}]}),
        encoding="utf-8",
    )
    return evidence_dir


def _hypothesis(
    rank: int,
    category: str,
    title: str,
    refs: list[str],
    genes: list[str],
) -> dict:
    return {
        "rank": rank,
        "title": title,
        "category": category,
        "gap_type": "none",
        "core_claim": f"{title} is testable in IPF biology.",
        "evidence_references": refs,
        "contrast_references": [],
        "biological_entities": {
            "genes": genes,
            "pathways": [],
            "cell_types": [],
            "drugs": [],
        },
        "falsifiable_prediction": "Measure a qualitative response change.",
        "validation_approach": "Run a perturbation assay with matched controls.",
        "scores": {
            "evidence_coverage": 0.8,
            "specificity": 0.8,
            "novelty": 0.7,
            "actionability": 0.7,
            "composite": 0.75,
        },
    }


def _hypothesis_report() -> dict:
    return {
        "schema_version": "hypothesis_report.v2",
        "disease": "IPF",
        "hypotheses_generated": 4,
        "hypotheses_retained": 4,
        "hypotheses": [
            _hypothesis(
                1,
                "Mechanism of Action",
                "FN1-CD4 mechanism",
                ["stage1_FN1--CD4.json", "stage3_FN1.json", "stage3_CD4.json"],
                ["FN1", "CD4"],
            ),
            _hypothesis(
                2,
                "Therapeutic Strategy",
                "FN1 actionability follow-up",
                ["stage1_FN1--SDC2.json", "stage3_FN1.json"],
                ["FN1", "SDC2"],
            ),
            _hypothesis(
                3,
                "Cross-Target Interaction",
                "FN1-CD4 cross-target follow-up",
                ["stage1_FN1--CD4.json", "stage3_FN1.json", "stage3_CD4.json"],
                ["FN1", "CD4"],
            ),
            _hypothesis(
                4,
                "Novel Pathway",
                "FN1 matrix remodeling pathway",
                ["stage3_FN1.json", "stage3_CD4.json"],
                ["FN1", "CD4"],
            ),
        ],
        "gap_analysis": {},
    }


def _payload() -> dict:
    return {
        "schema_version": "hybrid_report_sections/v1",
        "hypothesis_report": _hypothesis_report(),
        "pipeline_recommendations": [
            {
                "text": (
                    "Prioritize orthogonal validation of FN1 before advancing target "
                    "selection."
                ),
                "supporting_sources": ["evidence/assessment_results.json"],
            },
            {
                "text": "Evaluate CD4 and FN1 signals in future mechanistic assays.",
                "supporting_sources": ["evidence/stage3_CD4.json"],
            },
        ],
    }


def _source_paths() -> set[str]:
    return {
        "evidence/assessment_results.json",
        "evidence/stage1_FN1--CD4.json",
        "evidence/stage1_FN1--SDC2.json",
        "evidence/stage3_CD4.json",
        "evidence/stage3_FN1.json",
    }


def _report_data() -> dict:
    return {
        "candidates": [
            {
                "gene": "CD4",
                "drugs": [],
                "sources": ["evidence/stage3_CD4.json"],
            },
            {
                "gene": "FN1",
                "drugs": [],
                "sources": ["evidence/stage3_FN1.json"],
            },
        ]
    }


def _write_valid_hypothesis_report(tmp_path: Path) -> None:
    _write_evidence(tmp_path)
    persist_hypothesis_report(tmp_path, _hypothesis_report())


def test_report_recommendations_payload_has_no_hypothesis_field() -> None:
    schema = ReportRecommendationsPayload.model_json_schema()

    assert set(schema["required"]) == {
        "schema_version",
        "pipeline_recommendations",
    }
    assert "hypothesis_report" not in schema["properties"]
    assert "candidate_followups" in schema["properties"]


def test_ollama_candidate_followups_use_featured_stage3_sources(
    tmp_path: Path,
) -> None:
    _write_evidence(tmp_path)

    specs = build_ollama_candidate_followup_specs(tmp_path)
    followups = build_ollama_candidate_followups(
        tmp_path,
        {"FN1": "Prioritize FN1 perturbation follow-up before advancing target selection."},
    )

    assert specs == [
        {"gene": "CD4", "supporting_source": "evidence/stage3_CD4.json"},
        {"gene": "FN1", "supporting_source": "evidence/stage3_FN1.json"},
    ]
    assert followups == [
        {
            "gene": "FN1",
            "text": "Prioritize FN1 perturbation follow-up before advancing target selection.",
            "supporting_source": "evidence/stage3_FN1.json",
        }
    ]


def test_ollama_candidate_followups_reject_unsafe_causal_claims(
    tmp_path: Path,
) -> None:
    _write_evidence(tmp_path)

    followups = build_ollama_candidate_followups(
        tmp_path,
        {
            "FN1": (
                "Prioritize FN1 validation because it drives disease progression."
            ),
        },
    )

    assert followups == []


def test_canonicalize_report_sections_accepts_source_bound_candidate_followup(
    tmp_path: Path,
) -> None:
    evidence_dir = _write_evidence(tmp_path)
    payload = _payload()
    payload["candidate_followups"] = [{
        "gene": "FN1",
        "text": "Prioritize FN1 perturbation follow-up before advancing target selection.",
        "supporting_source": "evidence/stage3_FN1.json",
    }]

    canonical, errors = canonicalize_report_sections(
        payload,
        evidence_dir,
        _source_paths(),
        _report_data(),
    )

    assert errors == []
    assert canonical is not None
    assert canonical["candidate_followups"][0]["gene"] == "FN1"


def test_canonicalize_report_sections_keeps_internal_underscore_identifiers(
    tmp_path: Path,
) -> None:
    evidence_dir = _write_evidence(tmp_path)
    payload = _payload()
    payload["candidate_followups"] = [{
        "gene": "FN1",
        "text": "Prioritize FN1_variant perturbation follow-up before advancing target selection.",
        "supporting_source": "evidence/stage3_FN1.json",
    }]

    canonical, errors = canonicalize_report_sections(
        payload,
        evidence_dir,
        _source_paths(),
        _report_data(),
    )

    assert errors == []
    assert canonical is not None


def test_canonicalize_report_sections_rejects_unknown_followup_gene(
    tmp_path: Path,
) -> None:
    evidence_dir = _write_evidence(tmp_path)
    payload = _payload()
    payload["candidate_followups"] = [{
        "gene": "TP53",
        "text": "Prioritize TP53 perturbation follow-up before advancing target selection.",
        "supporting_source": "evidence/stage3_FN1.json",
    }]

    canonical, errors = canonicalize_report_sections(
        payload,
        evidence_dir,
        _source_paths(),
        _report_data(),
    )

    assert canonical is None
    assert "candidate_followups[0].gene" in "\n".join(errors)


def test_ollama_recommendation_payload_uses_hypothesis_sources(
    tmp_path: Path,
) -> None:
    _write_valid_hypothesis_report(tmp_path)

    payload = build_ollama_report_recommendations(
        tmp_path,
        {
            "primary": "Prioritize FN1 validation before advancing target selection.",
            "secondary": "Evaluate CD4 evidence before planning follow-up studies.",
        },
    )

    assert payload["schema_version"] == "hybrid_report_sections/v1"
    assert len(payload["pipeline_recommendations"]) == 2
    assert all(
        len(item["supporting_sources"]) == 1
        for item in payload["pipeline_recommendations"]
    )
    assert all(
        path.startswith("evidence/")
        for item in payload["pipeline_recommendations"]
        for path in item["supporting_sources"]
    )


def test_ollama_recommendation_payload_replaces_unsafe_text(tmp_path: Path) -> None:
    _write_valid_hypothesis_report(tmp_path)

    payload = build_ollama_report_recommendations(
        tmp_path,
        {"primary": "# bad\ntext"},
    )

    assert payload["pipeline_recommendations"][0]["text"].startswith("Prioritize")


def test_ollama_recommendation_payload_replaces_unsafe_causal_claim(
    tmp_path: Path,
) -> None:
    _write_valid_hypothesis_report(tmp_path)

    payload = build_ollama_report_recommendations(
        tmp_path,
        {
            "primary": (
                "Prioritize FN1 validation because it drives disease progression."
            ),
        },
    )

    assert payload["pipeline_recommendations"][0]["text"] == (
        "Prioritize CD4 validation before advancing target selection."
    )


def test_bound_hypothesis_reader_requires_valid_handoff(tmp_path: Path) -> None:
    from src.agents.drug_target.production_report_tools import (
        production_load_validated_hypothesis_report_tool,
    )

    receipt = json.loads(
        production_load_validated_hypothesis_report_tool(tmp_path).invoke({})
    )

    assert receipt["valid"] is False
    assert receipt["errors"][0]["code"] == "HYPOTHESIS_REPORT_MISSING"


def test_sections_save_host_injects_saved_handoff(tmp_path: Path) -> None:
    from src.agents.drug_target.production_report_tools import (
        production_save_report_sections_tool,
    )

    _write_renderer_evidence(tmp_path)
    persist_hypothesis_report(tmp_path, _hypothesis_report())
    receipt = json.loads(
        production_save_report_sections_tool(tmp_path, "IPF").invoke(
            {
                "payload": {
                    "schema_version": "hybrid_report_sections/v1",
                    "pipeline_recommendations": _payload()["pipeline_recommendations"],
                },
            }
        )
    )

    assert receipt["saved"] is True
    saved = json.loads((tmp_path / REPORT_SECTIONS_FILENAME).read_text())
    handoff = json.loads((tmp_path / "evidence" / "hypothesis_report.json").read_text())
    assert saved["hypothesis_report"]["hypotheses"] == handoff["hypotheses"]


def test_validate_canonical_hypothesis_report_accepts_current_contract_without_write(
    tmp_path: Path,
) -> None:
    evidence_dir = _write_evidence(tmp_path)
    canonical, errors, _ = canonicalize_hypothesis_report(
        _hypothesis_report(),
        evidence_dir,
        legacy_compat=False,
    )

    assert canonical is not None
    assert errors == []
    assert validate_canonical_hypothesis_report(canonical, evidence_dir) == []
    assert not (evidence_dir / "hypothesis_report.json").exists()


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda report: report["hypotheses"].__setitem__(
                0, {**report["hypotheses"][0], "category": "Invalid"}
            ),
            "category is not canonical",
        ),
        (
            lambda report: report["hypotheses"][0].__setitem__(
                "evidence_references", ["stage3_missing.json"]
            ),
            "not in evidence/ directory",
        ),
        (
            lambda report: report.__setitem__("hypotheses", report["hypotheses"][:3]),
            "HYPOTHESIS_COUNT_OUT_OF_RANGE",
        ),
    ],
)
def test_canonicalize_report_sections_rejects_invalid_hypothesis_contract(
    tmp_path: Path,
    mutate,
    expected: str,
) -> None:
    evidence_dir = _write_evidence(tmp_path)
    payload = _payload()
    mutate(payload["hypothesis_report"])

    canonical, errors = canonicalize_report_sections(
        payload,
        evidence_dir,
        _source_paths(),
        _report_data(),
    )

    assert canonical is None
    assert expected in "\n".join(errors)


def test_canonicalize_report_sections_accepts_bounded_recommendations(
    tmp_path: Path,
) -> None:
    evidence_dir = _write_evidence(tmp_path)
    payload = _payload()
    payload["pipeline_recommendations"][0]["supporting_sources"] = sorted(
        _source_paths()
    )

    canonical, errors = canonicalize_report_sections(
        payload,
        evidence_dir,
        _source_paths(),
        _report_data(),
    )

    assert errors == []
    assert canonical is not None
    assert canonical["schema_version"] == "hybrid_report_sections/v1"
    assert len(canonical["pipeline_recommendations"]) == 2
    assert canonical["pipeline_recommendations"][0]["supporting_sources"] == sorted(
        _source_paths()
    )
    assert REPORT_SECTIONS_FILENAME == "report_sections.json"
    assert not (evidence_dir / "hypothesis_report.json").exists()


@pytest.mark.parametrize(
    "text",
    [
        "Prioritize NINTEDANIB testing before advancing target selection.",
        "Prioritize 7 experiments before advancing target selection.",
        "[source: evidence/assessment_results.json] Prioritize FN1 validation.",
        "Prioritize **FN1** validation before advancing target selection.",
        "Prioritize _FN1_ validation before advancing target selection.",
        "Prioritize `FN1` validation before advancing target selection.",
        "Prioritize <script>FN1</script> validation before advancing target selection.",
        "FN1 is a supported candidate in deterministic analysis.",
        "Prioritize FN1 validation\nbefore advancing target selection.",
        (
            "Prioritize orthogonal validation of FN1 before advancing target "
            "selection. Evaluate CD4 signals in future mechanistic assays."
        ),
    ],
)
def test_canonicalize_report_sections_rejects_unsafe_recommendation_text(
    tmp_path: Path,
    text: str,
) -> None:
    evidence_dir = _write_evidence(tmp_path)
    payload = _payload()
    payload["pipeline_recommendations"][0]["text"] = text

    canonical, errors = canonicalize_report_sections(
        payload,
        evidence_dir,
        _source_paths(),
        _report_data(),
    )

    assert canonical is None
    assert errors


@pytest.mark.parametrize("count", [1, 5])
def test_canonicalize_report_sections_rejects_invalid_recommendation_count(
    tmp_path: Path,
    count: int,
) -> None:
    evidence_dir = _write_evidence(tmp_path)
    payload = _payload()
    payload["pipeline_recommendations"] = payload["pipeline_recommendations"][:count]
    while len(payload["pipeline_recommendations"]) < count:
        payload["pipeline_recommendations"].append(
            {
                "text": "Prioritize FN1 validation before advancing target selection.",
                "supporting_sources": ["evidence/assessment_results.json"],
            }
        )

    canonical, errors = canonicalize_report_sections(
        payload,
        evidence_dir,
        _source_paths(),
        _report_data(),
    )

    assert canonical is None
    assert "pipeline_recommendations" in "\n".join(errors)


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        (
            ["evidence/assessment_results.json", "evidence/assessment_results.json"],
            "must be unique",
        ),
        (["evidence/not_allowed.json"], "deterministic evidence paths"),
        (
            [
                "evidence/assessment_results.json",
                "evidence/stage1_FN1--CD4.json",
                "evidence/stage1_FN1--SDC2.json",
                "evidence/stage3_CD4.json",
                "evidence/stage3_FN1.json",
                "evidence/not_allowed.json",
            ],
            "supporting_sources",
        ),
    ],
)
def test_canonicalize_report_sections_rejects_invalid_recommendation_sources(
    tmp_path: Path,
    sources: list[str],
    expected: str,
) -> None:
    evidence_dir = _write_evidence(tmp_path)
    payload = _payload()
    payload["pipeline_recommendations"][0]["supporting_sources"] = sources

    canonical, errors = canonicalize_report_sections(
        payload,
        evidence_dir,
        _source_paths(),
        _report_data(),
    )

    assert canonical is None
    assert expected in "\n".join(errors)


def test_canonicalize_report_sections_ignores_caller_entity_allowlist(
    tmp_path: Path,
) -> None:
    evidence_dir = _write_evidence(tmp_path)
    payload = _payload()
    payload["pipeline_recommendations"][0]["text"] = (
        "Prioritize NINTEDANIB testing before advancing target selection."
    )
    report_data = _report_data()
    report_data["allowed_genes"] = ["CD4", "FN1", "NINTEDANIB"]

    canonical, errors = canonicalize_report_sections(
        payload,
        evidence_dir,
        _source_paths(),
        report_data,
    )

    assert canonical is None
    assert "Unsupported entity token" in "\n".join(errors)


def test_hybrid_renderer_preserves_canonical_candidate_followup_sources(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import render_hybrid_report

    evidence_dir = _write_renderer_evidence(tmp_path)
    payload = _payload()
    payload["candidate_followups"] = [
        {
            "gene": "CD4",
            "text": "Evaluate CD4 perturbation follow-up before advancing target selection.",
            "supporting_source": "evidence/stage3_CD4.json",
        },
        {
            "gene": "FN1",
            "text": "Prioritize FN1 perturbation follow-up before advancing target selection.",
            "supporting_source": "evidence/stage3_FN1.json",
        },
    ]
    canonical, errors = canonicalize_report_sections(
        payload,
        evidence_dir,
        _source_paths(),
        _report_data(),
    )

    assert errors == []
    assert canonical is not None

    markdown, _ = render_hybrid_report(str(tmp_path), "IPF", canonical)

    assert "[from evidence/stage3_CD4.json]" in markdown
    assert "[from evidence/stage3_FN1.json]" in markdown


def test_hybrid_renderer_uses_canonical_sections_with_host_owned_provenance(
    tmp_path: Path,
) -> None:
    from src.agents.drug_target.deterministic_report import (
        build_report_data,
        render_hybrid_report,
        render_report_markdown,
    )
    from src.agents.drug_target.tools import validate_drug_report_finalization

    evidence_dir = _write_renderer_evidence(tmp_path)
    (evidence_dir / "stage1_evidence.json").write_text(
        json.dumps(
            {
                "FN1--CD4": {
                    "ligand": "FN1",
                    "receptor": "CD4",
                    "string_ppi": {
                        "interaction_found": True,
                        "max_combined_score": 0.9,
                    },
                    "census_validation": {
                        "resolved_cell_type": "pulmonary alveolar type 2 cell",
                        "target_vs_rest": {
                            "coexpression": {"risk_ratio": 2.0, "p_value": 0.01}
                        },
                    },
                    "stage1_filter": {"passed": True},
                }
            }
        ),
        encoding="utf-8",
    )
    (evidence_dir / "celltype_resolution.json").write_text(
        json.dumps(
            {
                "primary_input_celltype": "AT2",
                "primary_resolved_celltype": "pulmonary alveolar type 2 cell",
                "interest_celltypes": ["AT2"],
            }
        ),
        encoding="utf-8",
    )
    payload = _payload()
    payload["candidate_followups"] = [{
        "gene": "FN1",
        "text": "Prioritize FN1 perturbation follow-up before advancing target selection.",
        "supporting_source": "evidence/stage3_FN1.json",
    }]
    canonical, errors = canonicalize_report_sections(
        payload,
        evidence_dir,
        _source_paths(),
        _report_data(),
    )

    assert errors == []
    assert canonical is not None
    canonical["hypothesis_report"]["hypotheses"][0]["interpretation_note"] = (
        "This follow-up does not establish a causal mechanism."
    )
    canonical["hypothesis_report"]["hypotheses"][0]["biological_entities"][
        "cell_types"
    ] = ["pulmonary alveolar type 2 cell"]
    report_data = build_report_data(
        str(tmp_path),
        "IPF",
        hypothesis_data=canonical,
        hypothesis_source=REPORT_SECTIONS_FILENAME,
    )
    markdown = render_report_markdown(
        report_data,
        pipeline_recommendations=canonical["pipeline_recommendations"],
    )

    for section in range(1, 6):
        assert f"## {section}." in markdown
    assert any(
        line.startswith("#### 4.") and line.endswith("FN1-CD4 mechanism")
        for line in markdown.splitlines()
    )
    for field in (
        "**Category:**",
        "**Core Claim:**",
        "- Genes:",
        "**Falsifiable Prediction:**",
        "**Validation Approach:**",
    ):
        assert field in markdown
    assert "### 5.1. Pipeline Execution Summary" in markdown
    assert "| Total genes assessed |" in markdown
    assert "### 5.2. Evidence-Grounded Follow-up Recommendations" in markdown
    for recommendation in canonical["pipeline_recommendations"]:
        assert (
            f"{recommendation['text']} [source: interpretation]" in markdown
        )
        assert markdown.count(recommendation["text"]) == 1
        assert json.dumps(recommendation["supporting_sources"]) not in markdown
    assert "supporting_sources" not in markdown
    for sentence in (
        "These recommendations are grounded",
        "Treat them as spatial-niche",
        "Treat them as gene-level",
    ):
        line = next(line for line in markdown.splitlines() if sentence in line)
        assert "[source:" in line

    rendered_markdown, rendered_report_data = render_hybrid_report(
        str(tmp_path),
        "IPF",
        canonical,
    )

    assert rendered_markdown == (tmp_path / "drug.md").read_text(encoding="utf-8")
    assert (
        "Prioritize FN1 perturbation follow-up before advancing target selection."
        in rendered_markdown
    )
    assert "This follow-up does not establish a causal mechanism." in rendered_markdown
    assert "supports target-cell context, but not causal mechanism." in rendered_markdown
    assert "**Core Claim:**" in rendered_markdown
    assert "**Falsifiable Prediction:**" in rendered_markdown
    assert rendered_report_data["sections"]["hypotheses"]["sources"] == [
        REPORT_SECTIONS_FILENAME
    ]
    assert json.loads((tmp_path / REPORT_SECTIONS_FILENAME).read_text(encoding="utf-8")) == canonical
    render_metadata = json.loads(
        (tmp_path / "drug_report_render.json").read_text(encoding="utf-8")
    )
    assert render_metadata["mode"] == "hybrid_jinja_qwen"
    assert render_metadata["source_hashes"]["report_sections"]
    validation = json.loads(
        validate_drug_report_finalization.invoke(
            {"data_dir": str(tmp_path), "publication_mode": "agent_markdown"}
        )
    )
    assert validation["valid"] is True
    finding_types = {
        finding["type"]
        for finding in validation["checks"]["validate_drug_md"]["raw"]["findings"]
    }
    assert "UNANCHORED_SENTENCE" not in finding_types
    assert "FABRICATED_DRUG_NAME" not in finding_types


def test_valid_hybrid_report_passes_guardrail_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.agents.drug_target import report_guardrails
    from src.agents.drug_target.deterministic_report import render_hybrid_report

    evidence_dir = _write_renderer_evidence(tmp_path)
    canonical, errors = canonicalize_report_sections(
        _payload(),
        evidence_dir,
        _source_paths(),
        _report_data(),
    )
    assert errors == []
    assert canonical is not None
    render_hybrid_report(str(tmp_path), "IPF", canonical)

    validations: list[dict] = []
    real_validate = report_guardrails._validate

    def validate(data_dir: Path) -> dict:
        result = real_validate(data_dir)
        validations.append(result)
        return result

    async def publish(data_dir: Path, **_kwargs: object) -> dict[str, str]:
        assert validations[-1]["valid"] is True
        for name in report_guardrails.PUBLICATION_ARTIFACTS:
            (data_dir / name).write_text("published", encoding="utf-8")
        return {"status": "published"}

    monkeypatch.setattr(report_guardrails, "_validate", validate)
    monkeypatch.setattr(report_guardrails, "_publish_report_outputs", publish)

    result = report_guardrails.run_drug_report_guardrail(tmp_path, disease="IPF")

    assert result["status"] == "passed"
    assert all((tmp_path / name).exists() for name in report_guardrails.PUBLICATION_ARTIFACTS)
    audit = json.loads((tmp_path / "drug_report_validation_final.json").read_text())
    assert audit["publication"]["status"] == "passed"
    source = next(
        source for source in audit["sources"] if source["path"] == REPORT_SECTIONS_FILENAME
    )
    assert source["sha256"]


def test_hybrid_renderer_explicitly_omits_legacy_interpretations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from src.agents.drug_target import deterministic_report

    evidence_dir = _write_renderer_evidence(tmp_path)
    canonical, errors = canonicalize_report_sections(
        _payload(),
        evidence_dir,
        _source_paths(),
        _report_data(),
    )

    assert errors == []
    assert canonical is not None
    captured: dict[str, object] = {}

    def capture_render(
        _report_data: object,
        **kwargs: object,
    ) -> str:
        captured.update(kwargs)
        return ""

    monkeypatch.setattr(deterministic_report, "render_report_markdown", capture_render)

    deterministic_report.render_hybrid_report(str(tmp_path), "IPF", canonical)

    assert captured == {
        "interpretations": {"candidates": {}},
        "pipeline_recommendations": canonical["pipeline_recommendations"],
    }

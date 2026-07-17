"""The loaded reporting skill must match the guarded writer surface."""

import json
from pathlib import Path


SKILL_PATH = Path("skills/drug-target-reporting/SKILL.md")
SCORING_PATH = Path("skills/drug-target-reporting/references/scoring_guide.md")


def test_reporting_skill_uses_validated_handoff_not_raw_evidence() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "## Supported local Ollama diagnostic invocation" in text
    assert "This invocation is diagnostic; no successful report was produced." in text
    assert "## Verified local Ollama smoke invocation" not in text
    assert "Qwen owns only 2–4 Section 5 recommendations" in text
    assert "load_validated_hypothesis_report" in text
    assert "Jinja owns every rendered layout and factual value" in text
    assert "build_evidence_summary" not in text
    assert "include_legacy_hypothesis=False" not in text
    assert "resolved_drugs.json" not in text
    assert 'load_evidence_files(scope="hypothesis")' not in text
    assert "load_lr_candidates" not in text
    assert "`hypothesis_report.json` is read only via `load_validated_hypothesis_report` and is never cited" in text
    assert "gap analysis" not in text.lower()
    assert "exactly `schema_version` and `pipeline_recommendations`" in text
    assert "1-5 exact `evidence/<filename>.json` paths" in text
    assert "If its receipt has `saved:true`, stop." in text
    assert "If its receipt has `saved:false`, repair only returned recommendation violations" in normalized
    assert "call `save_report_sections` once more" in text
    assert text.count("call `save_report_sections` once more") == 1
    assert "Never author Markdown or a hypothesis JSON object." in normalized
    assert "Call `save_report_sections` exactly once with the corrected recommendation payload, then stop." in normalized
    assert "read only via `load_validated_hypothesis_report` and is never cited" in text
    for retired_operation in (
        "save_report_expansions",
        "render_drug_md_from_expansions",
        "generate_drug_html_report",
    ):
        assert retired_operation not in text


def test_reporting_skill_evals_and_scoring_avoid_legacy_section_four_source() -> None:
    assert "hypothesis_report.json" not in SCORING_PATH.read_text(encoding="utf-8")
    scenarios = json.loads(Path("skills/drug-target-reporting/evals/evals.json").read_text())
    serialized = json.dumps(scenarios)
    assert "save_report_expansions" not in serialized
    assert "render_drug_md_from_expansions" not in serialized
    assert "generate_drug_html_report" not in serialized
    initial = next(item for item in scenarios["evals"] if item["id"] == "initial_handoff_synthesis")
    assert initial["expected_output"] == (
        "Read the reporting skill, load_validated_hypothesis_report, then save one "
        "recommendation-only sections payload; if saved:true stop; if saved:false "
        "repair only reported recommendation violations and save once more."
    )
    repair = next(item for item in scenarios["evals"] if item["id"] == "repair_only")
    assert repair["expected_output"] == (
        "Change only the listed recommendation issue and save the corrected recommendation "
        "payload once; do not read skills or reload the validated handoff."
    )
    assert "drug.md" not in json.dumps(repair)

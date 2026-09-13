import json
from pathlib import Path

import pytest

from scripts import run_sni_guardrail_ablation as experiment


def test_primary_yield_keeps_failures_and_does_not_treat_pending_as_pass():
    rows = [
        {"arm": "on", "generation_status": "passed", "evaluation": {"status": "evaluated", "complete": True, "usable": True}},
        {"arm": "on", "generation_status": "failed", "evaluation": {"status": "incomplete", "complete": False, "usable": False}},
        {"arm": "on", "generation_status": "passed", "evaluation": {"status": "evaluation_failed", "complete": True, "usable": None}},
        {"arm": "off", "generation_status": "pending"},
    ]
    result = experiment.summarize_rows(rows)
    assert result["on"]["attempted"] == 3
    assert result["on"]["usable"] == 1
    assert result["on"]["evaluation_unknown"] == 1
    assert result["on"]["usable_rate"] is None
    assert result["off"]["attempted"] == 0
    assert result["off"]["usable_rate"] is None
    rows[2]["evaluation"] = {"status": "evaluated", "complete": True, "usable": False}
    assert experiment.summarize_rows(rows)["on"]["usable_rate"] == pytest.approx(1 / 3)


def test_evaluation_copy_keeps_reports_but_discards_prior_verdicts(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "part1_final.md").write_text("# Original report\n")
    (source / "targets.json").write_text(json.dumps({"data_directory": str(source), "sel_factor": "Factor3"}))
    (source / "claim_rag_checkpoint.json").write_text('{"batches":{"old":"passed"}}')
    (source / "report_validation_final.json").write_text('{"issues":[]}')
    (source / "synthesis_validation.json").write_text('{"synthesis_guardrail":{"status":"passed"}}')
    copied = experiment.prepare_evaluation_copy(source, tmp_path / "evaluation")
    assert (copied / "part1_final.md").read_text() == "# Original report\n"
    assert not (copied / "claim_rag_checkpoint.json").exists()
    assert not (copied / "report_validation_final.json").exists()
    assert not (copied / "synthesis_validation.json").exists()
    assert json.loads((copied / "targets.json").read_text())["data_directory"] == str(copied)
    assert (source / "claim_rag_checkpoint.json").exists()
    with pytest.raises(FileExistsError):
        experiment.prepare_evaluation_copy(source, copied)


def test_cohort_requires_each_original_label_once():
    rows = [{"pair_id": str(pair), "sequence": seq} for pair in range(16, 26) for seq in ("AB", "BA")]
    experiment.validate_cohort(rows)
    rows[-1] = dict(rows[0])
    with pytest.raises(ValueError, match="cohort"):
        experiment.validate_cohort(rows)


def test_completed_generation_is_not_silently_replaced(tmp_path):
    row = {"generation_status": "failed", "data_dir": str(tmp_path)}
    assert not experiment.generation_pending(row)
    row["generation_status"] = "running"
    assert not experiment.generation_pending(row)
    row["generation_status"] = "pending"
    assert experiment.generation_pending(row)


@pytest.mark.parametrize("message, expected", [
    ("ReadTimeout: request timed out", "timeout"),
    ("ConnectError: connection refused", "infrastructure"),
    ("stage runner returned 1", "execution_error"),
])
def test_failure_classification_preserves_execution_cause(tmp_path, message, expected):
    (tmp_path / "run_manifest.json").write_text(json.dumps({"error": {"message": message}}))
    assert experiment.generation_failure(tmp_path) == expected


def test_off_generation_records_disabled_validation_in_real_run_manifest(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    pmids = {str(n) for n in range(100)}
    (source / "papers.json").write_text(json.dumps({"papers": [{"pmid": p} for p in sorted(pmids)]}))
    (source / "targets.json").write_text('{"sel_factor":"Factor3"}')
    (source / "interpretation_guide.md").write_text("guide")
    (source / "part4_candidate_selection.json").write_text("{}")
    monkeypatch.setattr(experiment, "SOURCE", source)
    monkeypatch.setattr(experiment.baseline, "_default_collection_snapshot", lambda url: dict(experiment.baseline.BC_COLLECTION_SNAPSHOT))
    monkeypatch.setattr(experiment.baseline, "_collection_pmids", lambda url: pmids)

    def generate_without_llm(directory, env):
        for name in experiment.REPORTS:
            (directory / name).write_text("unvalidated generated content")
        (directory / "rag_audit.jsonl").write_text(json.dumps({
            "endpoint": "agentic_search", "collection_uuid": experiment.baseline.BC_COLLECTION_ID,
            "use_wiki_context": True, "success": True, "error_type": None, "result_count": 1,
        }) + "\n")
        return 0

    monkeypatch.setattr(experiment.baseline, "_default_stage_runner", generate_without_llm)
    directory = tmp_path / "off" / "pairs" / "pair-16" / "wiki-on"
    assert experiment.worker_generate(tmp_path, {"pair_id": "16", "data_dir": str(directory)}) == 0
    manifest = json.loads((directory / "run_manifest.json").read_text())
    assert manifest["metrics"]["artifacts"]["part1_final.md"]["final_error_count"] is None
    assert manifest["report_guardrails"]["status"] == "disabled"
    assert json.loads((directory / "parts_guardrail_result.json").read_text())["validation_performed"] is False

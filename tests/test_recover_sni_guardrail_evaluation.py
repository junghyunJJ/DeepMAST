import asyncio
import json
from types import SimpleNamespace

import pytest

from scripts import recover_sni_guardrail_evaluation as recovery
from src.agents.deep_interpreter import claim_rag_validation as claims


def test_reused_judge_client_keeps_one_live_loop_until_evaluation_finishes():
    async def current_loop():
        return asyncio.get_running_loop()

    original = claims.run_async
    with recovery.stable_judge_loop():
        first = claims.run_async(current_loop())
        assert not first.is_closed()
        assert claims.run_async(current_loop()) is first
    assert first.is_closed()
    assert claims.run_async is original


def test_judge_timeout_does_not_close_the_shared_loop():
    async def answer():
        return 42

    with recovery.stable_judge_loop():
        with pytest.raises(TimeoutError):
            claims.run_async(asyncio.sleep(1), timeout=0.001)
        assert claims.run_async(answer()) == 42


@pytest.mark.parametrize("issues, complete, status, expected", [
    ([{"severity": "error", "code": "bad_content"}, {"severity": "error", "code": "claim_evaluation_incomplete"}], True, "evaluation_failed", False),
    ([{"severity": "error", "code": "claim_evaluation_incomplete"}], True, "evaluation_failed", None),
    ([], True, "evaluated", True),
    ([], False, "incomplete", False),
    ([{"severity": "error", "code": "report_mutated_by_evaluation"}], True, "evaluation_failed", None),
])
def test_primary_outcome_distinguishes_known_error_from_missing_evaluation(issues, complete, status, expected):
    result = recovery.resolve_outcome({"issues": issues, "complete": complete, "status": status})
    assert result["usable"] is expected
    if issues and issues[0]["code"] == "bad_content":
        assert result["hard_error_count"] == 1
        assert not result["evaluation_complete"]


@pytest.mark.parametrize("change_copy", [False, True])
def test_resume_rejects_stale_assessment_when_report_bytes_change(tmp_path, monkeypatch, change_copy):
    source = tmp_path / "source"
    source.mkdir()
    (source / "part1_final.md").write_text("original")
    hashes = recovery.experiment.report_hashes(source)
    original = tmp_path / "experiment"
    original.mkdir()
    (original / "experiment_manifest.json").write_text(json.dumps({"cohort": [], "preflight": {"models": {}}}))
    output = tmp_path / "recovery"
    output.mkdir()
    row = {"pair_id": "16", "sequence": "AB", "arm": "on", "data_dir": str(source), "original_report_hashes": hashes}
    (output / "manifest.json").write_text(json.dumps({"rows": [row]}))
    working = output / "work/pair-16-AB/on"
    working.mkdir(parents=True)
    (working / "part1_final.md").write_text("original")
    path = recovery.result_path(output, row)
    path.parent.mkdir()
    path.write_text(json.dumps({"usable": True, "working_copy": str(working)}))
    ((working if change_copy else source) / "part1_final.md").write_text("changed")
    monkeypatch.setattr(recovery.experiment, "verify_frozen_inputs", lambda cohort, **kwargs: None)
    monkeypatch.setattr(recovery.experiment, "service_preflight", lambda source: {"models": {}})
    with pytest.raises(RuntimeError, match="report|copy"):
        recovery.run(original, output)


def test_missing_tool_response_uses_json_schema_without_changing_negative_verdict(monkeypatch):
    def missing(*args, **kwargs):
        raise AttributeError("'NoneType' object has no attribute 'judgments'")

    verdict = claims.ClaimJudgment(claim_index=0, status="unsupported", reason="Evidence conflicts.")
    monkeypatch.setattr(claims, "_invoke_judgment", missing)
    monkeypatch.setattr(recovery, "invoke_json_judgment", lambda *a, **kw: [verdict], raising=False)
    with recovery.stable_judge_loop():
        result = claims._invoke_judgment(object(), {"claims": []}, timeout_seconds=30)
    assert result == [verdict]
    assert result[0].status == "unsupported"


def test_connection_failure_is_not_relabelled_as_a_model_judgment(monkeypatch):
    def unavailable(*args, **kwargs):
        raise ConnectionError("server unavailable")

    monkeypatch.setattr(claims, "_invoke_judgment", unavailable)
    with recovery.stable_judge_loop():
        with pytest.raises(ConnectionError, match="server unavailable"):
            claims._invoke_judgment(object(), {"claims": []}, timeout_seconds=30)


def test_known_encoding_failure_reuses_json_recovery_instead_of_repeating_truncation(tmp_path, monkeypatch):
    group = {"claims": []}
    diagnostics = tmp_path / "judge_errors.jsonl"
    diagnostics.write_text(json.dumps({"type": "AttributeError", "message": "'NoneType' object has no attribute 'judgments'", "group": group}) + "\n")
    def must_not_repeat(*args, **kwargs):
        raise AssertionError("known broken encoding must not be repeated")
    verdict = claims.ClaimJudgment(claim_index=0, status="overclaimed", reason="Too strong.")
    monkeypatch.setattr(claims, "_invoke_judgment", must_not_repeat)
    monkeypatch.setattr(recovery, "invoke_json_judgment", lambda *a, **kw: [verdict])
    with recovery.stable_judge_loop(diagnostics):
        assert claims._invoke_judgment(object(), group, timeout_seconds=30) == [verdict]


@pytest.mark.parametrize("parsed, finish", [(None, "stop"), (True, "length")])
def test_json_recovery_rejects_missing_or_truncated_judgment(parsed, finish):
    batch = claims.ClaimJudgmentBatch(judgments=[claims.ClaimJudgment(claim_index=0, status="supported", reason="Evidence matches.")])
    async def respond(messages):
        return {"parsed": batch if parsed else None, "raw": SimpleNamespace(response_metadata={"done_reason": finish}), "parsing_error": None}
    model = SimpleNamespace(with_structured_output=lambda *a, **kw: SimpleNamespace(ainvoke=respond))
    group = {"claims": [{"index": 0, "claim": "Example claim", "candidate_pmids": [], "evidence": []}]}
    with recovery.stable_judge_loop():
        with pytest.raises(RuntimeError, match="Incomplete JSON judgment"):
            recovery.invoke_json_judgment(model, group, timeout_seconds=30)

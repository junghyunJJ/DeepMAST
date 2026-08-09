import json
from email.message import Message
from pathlib import Path
from typing import cast
from urllib.error import HTTPError

from scripts import sni_ablation_api_stack as stack
from scripts import run_bc_sni_repair_ablation as bc_runner

Payload = dict[str, object]


def _smoke_args(report_path: Path, *extra: str) -> list[str]:
    return [
        "smoke",
        "--collection-id",
        stack.BC_COLLECTION_ID,
        "--question",
        "Which SNI behavior is active?",
        "--report",
        str(report_path),
        "--sgcp-rag-dir",
        str(report_path.parent),
        "--env-file",
        str(report_path.parent / ".env"),
        *extra,
    ]


def _call_payloads(calls: list[tuple[str, str, object | None]]) -> list[Payload]:
    return [cast(Payload, payload) for _, _, payload in calls if isinstance(payload, dict)]


def test_compose_commands_target_only_ablation_services(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    rc = stack.main(
        [
            "up",
            "--sgcp-rag-dir",
            str(tmp_path),
            "--env-file",
            str(tmp_path / ".env"),
        ],
        docker=calls.append,
    )

    assert rc == 0
    assert calls == [
        [
            "docker",
            "compose",
            "--env-file",
            str(tmp_path / ".env"),
            "-f",
            str(stack.COMPOSE_FILE),
            "--project-name",
            "sgcp-sni-ablation",
            "up",
            "-d",
            "--no-deps",
            "sgcp-sni-api-4000",
            "sgcp-sni-api-5000",
            "sgcp-sni-api-6000",
            "sgcp-sni-api-7000",
        ]
    ]


def test_smoke_writes_machine_readable_report_without_credentials(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("POSTGRES_PASSWORD=secret\n", encoding="utf-8")
    report_path = tmp_path / "smoke.json"
    calls: list[tuple[str, str, object | None]] = []

    def fake_http(method: str, url: str, payload: object | None = None) -> object:
        calls.append((method, url, payload))
        if url.endswith("/health"):
            return {"status": "ok"}
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen3.5:122b"}]}
        if url.endswith("/agentic-search"):
            assert isinstance(payload, dict)
            use_wiki = payload["use_wiki_context"]
            return {
                "generation": "ok",
                "wiki_context_status": "selected" if use_wiki else "disabled",
            }
        if f"/collections/{stack.BC_COLLECTION_ID}" in url:
            return stack.BC_COLLECTION_SNAPSHOT
        raise AssertionError(url)

    rc = stack.main(
        _smoke_args(report_path, "--env-file", str(env_file)),
        http=fake_http,
    )

    assert rc == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert {api["backend_port"] for api in report["apis"]} == {4000, 5000, 6000, 7000}
    assert all(api["model"]["ok"] for api in report["apis"])
    assert all(api["collection"]["ok"] for api in report["apis"])
    assert all(
        api["agentic"]["wiki_on"]["observed_status"] == "selected"
        for api in report["apis"]
    )
    assert all(
        api["agentic"]["wiki_off"]["observed_status"] == "disabled"
        for api in report["apis"]
    )
    assert "secret" not in report_path.read_text(encoding="utf-8")
    payloads = _call_payloads(calls)
    assert any(payload["use_wiki_context"] is True for payload in payloads)
    assert any(payload["use_wiki_context"] is False for payload in payloads)


def test_smoke_fails_when_collection_snapshot_changes(tmp_path: Path) -> None:
    def fake_http(method: str, url: str, payload: object | None = None) -> object:
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen3.5:122b"}]}
        if url.endswith("/health"):
            return {"status": "ok"}
        if url.endswith("/agentic-search"):
            return {"wiki_context_status": "selected"}
        if "/collections/" in url and not url.endswith("/agentic-search"):
            return stack.BC_COLLECTION_SNAPSHOT | {"chunk_count": 1552}
        raise AssertionError(url)

    rc = stack.main(
        _smoke_args(tmp_path / "smoke.json"),
        http=fake_http,
    )

    assert rc == 1


def test_smoke_records_endpoint_errors_in_report(tmp_path: Path) -> None:
    def fake_http(method: str, url: str, payload: object | None = None) -> object:
        if url.endswith("/health"):
            return {"status": "ok"}
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen3.5:122b"}]}
        raise HTTPError(url, 503, "Unavailable", Message(), None)

    report_path = tmp_path / "smoke.json"
    rc = stack.main(
        _smoke_args(report_path),
        http=fake_http,
    )

    assert rc == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    error = report["apis"][0]["agentic"]["wiki_on"]["error"]
    assert error["type"] == "HTTPError"
    assert error["message"] == "HTTP Error 503: Unavailable"
    assert error["code"] == 503
    assert error["reason"] == "Unavailable"
    assert error["url"] == (
        f"http://localhost:8881/collections/{stack.BC_COLLECTION_ID}/agentic-search"
    )


def test_smoke_rejects_nested_status_when_top_level_status_is_wrong(tmp_path: Path) -> None:
    def fake_http(method: str, url: str, payload: object | None = None) -> object:
        if url.endswith("/health"):
            return {"status": "ok"}
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen3.5:122b"}]}
        if url.endswith("/agentic-search"):
            return {
                "wiki_context_status": "not_selected",
                "steps": [{"wiki_context_status": "disabled"}],
            }
        if f"/collections/{stack.BC_COLLECTION_ID}" in url:
            return stack.BC_COLLECTION_SNAPSHOT
        raise AssertionError(url)

    report_path = tmp_path / "smoke.json"
    rc = stack.main(_smoke_args(report_path), http=fake_http)

    assert rc == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["apis"][0]["agentic"]["wiki_off"] == {
        "ok": False,
        "expected_status": "disabled",
        "observed_status": "not_selected",
    }


def test_smoke_requires_health_status_ok(tmp_path: Path) -> None:
    def fake_http(method: str, url: str, payload: object | None = None) -> object:
        if url.endswith("/health"):
            return {"status": "healthy"}
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen3.5:122b"}]}
        if url.endswith("/agentic-search"):
            assert isinstance(payload, dict)
            return {
                "wiki_context_status": "selected"
                if payload["use_wiki_context"]
                else "disabled"
            }
        if f"/collections/{stack.BC_COLLECTION_ID}" in url:
            return stack.BC_COLLECTION_SNAPSHOT
        raise AssertionError(url)

    report_path = tmp_path / "smoke.json"
    rc = stack.main(_smoke_args(report_path), http=fake_http)

    assert rc == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["apis"][0]["health"] == {"ok": False, "status": "healthy"}


def test_smoke_rejects_wrong_collection_id_and_expected_snapshot(tmp_path: Path) -> None:
    def fake_http(method: str, url: str, payload: object | None = None) -> object:
        return {"status": "ok"}

    wrong_id_report = tmp_path / "wrong-id.json"
    wrong_id_rc = stack.main(
        [
            "smoke",
            "--collection-id",
            "0038c134-936a-4e63-82ac-b7683bf7844b",
            "--question",
            "Which SNI behavior is active?",
            "--report",
            str(wrong_id_report),
        ],
        http=fake_http,
    )

    mismatch_report = tmp_path / "mismatch.json"
    mismatch_rc = stack.main(
        _smoke_args(
            mismatch_report,
            "--expected-collection",
            json.dumps(stack.BC_COLLECTION_SNAPSHOT | {"document_count": 99}),
        ),
        http=fake_http,
    )

    assert wrong_id_rc == 1
    assert mismatch_rc == 1
    wrong_id = json.loads(wrong_id_report.read_text(encoding="utf-8"))
    mismatch = json.loads(mismatch_report.read_text(encoding="utf-8"))
    assert wrong_id["error"]["type"] == "FixedCollectionMismatch"
    assert mismatch["error"]["type"] == "FixedCollectionMismatch"


def test_compose_file_declares_reproducible_four_api_topology() -> None:
    text = stack.COMPOSE_FILE.read_text(encoding="utf-8")

    assert "langconnect_mcp-api" in text
    assert "external: true" in text
    assert "name: langconnect_mcp_langconnect-network" in text
    assert "langconnect-api" not in text
    assert "5432:5432" not in text
    for host_port, backend_port in zip(range(8881, 8885), range(4000, 8000, 1000)):
        assert f'"{host_port}:8080"' in text
        assert f"http://host.docker.internal:{backend_port}" in text


def _minimal_source(root: Path) -> Path:
    source = root / "bc_interpreter"
    source.mkdir()
    for name in (
        "papers.json",
        "targets.json",
        "interpretation_guide.md",
        "part4_candidate_selection.json",
    ):
        (source / name).write_text("{}\n" if name.endswith(".json") else "guide\n", encoding="utf-8")
    for name in (
        "part1_final.md",
        "part2_final.md",
        "part3_final.md",
        "synthesis.md",
        "synthesis_guarded.md",
        "report_validation_final.json",
        "guardrail_before_after_summary.md",
    ):
        (source / name).write_text("generated\n", encoding="utf-8")
    (source / "evidence").mkdir()
    (source / "evidence" / "kept.json").write_text("{}\n", encoding="utf-8")
    return source


def _successful_condition_artifacts(data_dir: Path) -> None:
    for name in bc_runner.REPORT_FILES:
        (data_dir / name).write_text("ok\n", encoding="utf-8")
    (data_dir / "rag_audit.jsonl").write_text(
        json.dumps({"endpoint": "agentic_search", "fallback_used": False}) + "\n",
        encoding="utf-8",
    )
    (data_dir / "report_validation_initial.json").write_text(
        json.dumps({"issues": [{"file": "part1_final.md", "severity": "error"}]}),
        encoding="utf-8",
    )
    (data_dir / "report_validation_final.json").write_text(
        json.dumps({"issues": []}),
        encoding="utf-8",
    )
    (data_dir / "parts_guardrail_result.json").write_text(
        json.dumps({"status": "passed", "repair_attempt_count": 2, "changed_sections": 5}),
        encoding="utf-8",
    )
    (data_dir / "synthesis_validation.json").write_text(
        json.dumps(
            {
                "synthesis_guardrail": {
                    "initial_error_count": 3,
                    "final_error_count": 0,
                    "repair_attempt_count": 3,
                    "terminal_repair_count": 1,
                    "changed_claims": 4,
                }
            }
        ),
        encoding="utf-8",
    )


def test_bc_runner_copies_each_condition_without_source_mutation(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)
    run_dir = bc_runner.prepare_condition_copy(
        source=source,
        output_root=tmp_path / "runs",
        pair_id=2,
        condition=bc_runner.CONDITIONS[0],
    )

    assert run_dir == tmp_path / "runs" / "pair-02" / "wiki-on"
    assert (source / "part1_final.md").exists()
    assert not (run_dir / "part1_final.md").exists()
    assert (run_dir / "evidence" / "kept.json").exists()
    manifest = json.loads((run_dir / "source_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"] == str(source)
    assert manifest["source_files"]["papers.json"] == manifest["copied_files"]["papers.json"]
    run_targets = json.loads((run_dir / "run_targets.json").read_text(encoding="utf-8"))
    assert run_targets["data_directory"] == str(run_dir.resolve())
    assert (run_dir / "logs").is_dir()


def test_bc_runner_pair_uses_sequential_conditions_with_fixed_endpoint_env(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)
    calls: list[tuple[int, str, dict[str, str]]] = []

    def fake_stage(data_dir: Path, env: dict[str, str]) -> int:
        calls.append((len(calls), data_dir.name, env.copy()))
        _successful_condition_artifacts(data_dir)
        return 0

    rc = bc_runner.main(
        [
            "--pair",
            "1",
            "--output-root",
            str(tmp_path / "runs"),
            "--source",
            str(source),
        ],
        stage_runner=fake_stage,
        collection_snapshot=lambda _api_url: stack.BC_COLLECTION_SNAPSHOT,
    )

    assert rc == 0
    assert [name for _, name, _ in calls] == ["wiki-on", "wiki-off"]
    on_env = calls[0][2]
    off_env = calls[1][2]
    assert on_env["OLLAMA_BASE_URL"] == "http://localhost:4000"
    assert on_env["CCI_RAG_BASE_URL"] == "http://localhost:8881"
    assert on_env["DEEP_INTERPRETER_USE_WIKI_CONTEXT"] == "true"
    assert on_env["DEEP_INTERPRETER_REQUIRE_AGENTIC_RAG"] == "true"
    assert on_env["DEEP_INTERPRETER_RAG_AUDIT_PATH"].endswith("/pair-01/wiki-on/rag_audit.jsonl")
    assert off_env["DEEP_INTERPRETER_USE_WIKI_CONTEXT"] == "false"
    manifest = json.loads(
        (tmp_path / "runs" / "pair-01" / "wiki-on" / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["collection"] == stack.BC_COLLECTION_SNAPSHOT
    assert manifest["rag_api_url"] == "http://localhost:8881"
    assert manifest["return_status"] == "passed"


def test_bc_runner_all_schedules_at_most_four_backend_lanes(tmp_path: Path) -> None:
    schedule = bc_runner.build_schedule([1, 2, 3, 4, 5, 6], stack.APIS)

    assert len(schedule) == 2
    assert [item["pair_id"] for item in schedule[0]] == [1, 2, 3, 4]
    assert [item["backend_port"] for item in schedule[0]] == [4000, 5000, 6000, 7000]
    assert [item["pair_id"] for item in schedule[1]] == [5, 6]


def test_bc_runner_metrics_count_terminal_synthesis_repair(tmp_path: Path) -> None:
    data_dir = tmp_path / "condition"
    data_dir.mkdir()
    _successful_condition_artifacts(data_dir)

    metrics = bc_runner.extract_metrics(data_dir)

    assert metrics["parts"] == {"repair_attempt_count": 2, "changed_sections": 5}
    assert metrics["synthesis"] == {
        "repair_attempt_count": 3,
        "terminal_repair_count": 1,
        "total_repair_count": 4,
        "changed_claims": 4,
    }
    assert metrics["artifacts"]["part1_final.md"]["initial_error_count"] == 1
    assert metrics["artifacts"]["part1_final.md"]["final_error_count"] == 0
    assert metrics["artifacts"]["synthesis.md"]["initial_error_count"] == 3


def test_bc_runner_fails_on_collection_drift_or_invalid_audit(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)

    def fake_stage(data_dir: Path, env: dict[str, str]) -> int:
        _successful_condition_artifacts(data_dir)
        (data_dir / "rag_audit.jsonl").write_text(
            json.dumps({"endpoint": "chunk_search", "fallback_used": True}) + "\n",
            encoding="utf-8",
        )
        return 0

    audit_rc = bc_runner.main(
        ["--pair", "1", "--output-root", str(tmp_path / "audit"), "--source", str(source)],
        stage_runner=fake_stage,
        collection_snapshot=lambda _api_url: stack.BC_COLLECTION_SNAPSHOT,
    )
    drift_rc = bc_runner.main(
        ["--pair", "1", "--output-root", str(tmp_path / "drift"), "--source", str(source)],
        stage_runner=lambda data_dir, env: (_successful_condition_artifacts(data_dir) or 0),
        collection_snapshot=lambda _api_url: stack.BC_COLLECTION_SNAPSHOT | {"chunk_count": 1552},
    )

    assert audit_rc == 1
    assert drift_rc == 1


def test_bc_runner_fails_when_audit_is_missing(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)

    def fake_stage(data_dir: Path, env: dict[str, str]) -> int:
        _successful_condition_artifacts(data_dir)
        (data_dir / "rag_audit.jsonl").unlink()
        return 0

    rc = bc_runner.main(
        ["--pair", "1", "--output-root", str(tmp_path / "runs"), "--source", str(source)],
        stage_runner=fake_stage,
        collection_snapshot=lambda _api_url: stack.BC_COLLECTION_SNAPSHOT,
    )

    assert rc == 1


def test_bc_runner_fails_when_final_guardrail_errors_remain(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)

    def fake_stage(data_dir: Path, env: dict[str, str]) -> int:
        _successful_condition_artifacts(data_dir)
        (data_dir / "report_validation_final.json").write_text(
            json.dumps({"issues": [{"file": "part2_final.md", "severity": "error"}]}),
            encoding="utf-8",
        )
        return 0

    rc = bc_runner.main(
        ["--pair", "1", "--output-root", str(tmp_path / "runs"), "--source", str(source)],
        stage_runner=fake_stage,
        collection_snapshot=lambda _api_url: stack.BC_COLLECTION_SNAPSHOT,
    )

    assert rc == 1


def test_bc_runner_smoke_runs_only_first_pair_with_mocked_stages(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)
    seen: list[str] = []

    def fake_stage(data_dir: Path, env: dict[str, str]) -> int:
        seen.append(str(data_dir.relative_to(tmp_path / "runs")))
        _successful_condition_artifacts(data_dir)
        return 0

    rc = bc_runner.main(
        ["--smoke", "--output-root", str(tmp_path / "runs"), "--source", str(source)],
        stage_runner=fake_stage,
        collection_snapshot=lambda _api_url: stack.BC_COLLECTION_SNAPSHOT,
    )

    assert rc == 0
    assert seen == ["pair-01/wiki-on", "pair-01/wiki-off"]

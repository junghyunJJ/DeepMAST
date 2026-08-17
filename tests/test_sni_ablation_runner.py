import json
import threading
from email.message import Message
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError

import pytest

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
        http=lambda method, url, payload=None: {"status": "ok"},
        sleep=lambda seconds: None,
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


def test_up_waits_for_all_api_health_before_returning(tmp_path: Path) -> None:
    docker_calls: list[list[str]] = []
    sleep_calls: list[float] = []
    health_calls: dict[str, int] = {}

    def fake_http(method: str, url: str, payload: object | None = None) -> object:
        assert method == "GET"
        assert payload is None
        assert url.endswith("/health")
        health_calls[url] = health_calls.get(url, 0) + 1
        return {"status": "starting" if health_calls[url] == 1 else "ok"}

    rc = stack.main(
        [
            "up",
            "--sgcp-rag-dir",
            str(tmp_path),
            "--env-file",
            str(tmp_path / ".env"),
            "--ready-timeout",
            "5",
            "--ready-interval",
            "0",
        ],
        docker=docker_calls.append,
        http=fake_http,
        sleep=sleep_calls.append,
    )

    assert rc == 0
    assert len(docker_calls) == 1
    assert set(health_calls) == {
        f"http://localhost:{api['api_port']}/health" for api in stack.APIS
    }
    assert all(count == 2 for count in health_calls.values())
    assert sleep_calls == [0.0]


def test_up_times_out_with_unready_endpoint_evidence(tmp_path: Path, capsys) -> None:
    def fake_http(method: str, url: str, payload: object | None = None) -> object:
        if url == "http://localhost:8882/health":
            raise ConnectionResetError(54, "Connection reset by peer")
        return {"status": "starting"}

    rc = stack.main(
        [
            "up",
            "--sgcp-rag-dir",
            str(tmp_path),
            "--env-file",
            str(tmp_path / ".env"),
            "--ready-timeout",
            "0",
            "--ready-interval",
            "0",
        ],
        docker=lambda cmd: None,
        http=fake_http,
        sleep=lambda seconds: None,
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "unready ablation API endpoints" in captured.err
    assert "http://localhost:8881/health deadline exhausted" in captured.err
    assert "http://localhost:8882/health deadline exhausted" in captured.err


def test_up_bounds_hung_health_probe_by_remaining_ready_timeout(
    tmp_path: Path, capsys
) -> None:
    now = 100.0
    probe_timeouts: list[float] = []

    def clock() -> float:
        return now

    def fake_health(url: str, timeout: float) -> object:
        nonlocal now
        probe_timeouts.append(timeout)
        now += timeout
        raise TimeoutError(f"probe timeout after {timeout:g}s")

    rc = stack.main(
        [
            "up",
            "--sgcp-rag-dir",
            str(tmp_path),
            "--env-file",
            str(tmp_path / ".env"),
            "--ready-timeout",
            "10",
            "--ready-interval",
            "0",
        ],
        docker=lambda cmd: None,
        health_http=fake_health,
        sleep=lambda seconds: None,
        clock=clock,
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert probe_timeouts == [10.0]
    assert now == 110.0
    assert "http://localhost:8881/health TimeoutError" in captured.err
    assert "probe timeout after 10s" in captured.err


def test_up_recomputes_remaining_deadline_before_each_health_probe(
    tmp_path: Path, capsys
) -> None:
    now = 100.0
    calls: list[tuple[str, float]] = []

    def clock() -> float:
        return now

    def fake_health(url: str, timeout: float) -> object:
        nonlocal now
        calls.append((url, timeout))
        if url == "http://localhost:8881/health":
            now += 9.0
            return {"status": "ok"}
        if url == "http://localhost:8882/health":
            now += timeout
            raise TimeoutError(f"probe timeout after {timeout:g}s")
        raise AssertionError(f"deadline exhausted before {url}")

    rc = stack.main(
        [
            "up",
            "--sgcp-rag-dir",
            str(tmp_path),
            "--env-file",
            str(tmp_path / ".env"),
            "--ready-timeout",
            "10",
            "--ready-interval",
            "5",
        ],
        docker=lambda cmd: None,
        health_http=fake_health,
        sleep=lambda seconds: None,
        clock=clock,
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert calls == [
        ("http://localhost:8881/health", 10.0),
        ("http://localhost:8882/health", 1.0),
    ]
    assert now == 110.0
    assert "http://localhost:8882/health TimeoutError" in captured.err
    assert "http://localhost:8883/health deadline exhausted" in captured.err


def test_up_readiness_checks_only_health_endpoints(tmp_path: Path) -> None:
    docker_calls: list[list[str]] = []
    http_calls: list[tuple[str, str, object | None]] = []

    def fake_http(method: str, url: str, payload: object | None = None) -> object:
        http_calls.append((method, url, payload))
        return {"status": "ok"}

    rc = stack.main(
        [
            "up",
            "--sgcp-rag-dir",
            str(tmp_path),
            "--env-file",
            str(tmp_path / ".env"),
        ],
        docker=docker_calls.append,
        http=fake_http,
        sleep=lambda seconds: None,
    )

    assert rc == 0
    assert docker_calls[0][-4:] == [api["service"] for api in stack.APIS]
    assert all(method == "GET" for method, _, _ in http_calls)
    assert all(url.endswith("/health") for _, url, _ in http_calls)
    assert all(payload is None for _, _, payload in http_calls)


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
            return {
                "models": [
                    {"name": "qwen3.5:122b", "digest": "hidden"},
                    {"name": "qwen3.5:35b"},
                ],
                "opaque": {"secret": "do-not-copy"},
            }
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
    assert {api["backend_port"] for api in report["apis"]} == {4000}
    assert all(api["model"]["ok"] for api in report["apis"])
    assert all(api["collection"]["ok"] for api in report["apis"])
    assert all(
        api["model"] == {
            "ok": True,
            "expected": "qwen3.5:122b",
            "observed_names": ["qwen3.5:122b", "qwen3.5:35b"],
        }
        for api in report["apis"]
    )
    assert all(
        api["collection"] == {
            "ok": True,
            "expected": stack.BC_COLLECTION_SNAPSHOT,
            "observed": stack.BC_COLLECTION_SNAPSHOT,
        }
        for api in report["apis"]
    )
    assert all(
        api["agentic"]["wiki_on"]["observed_status"] == "selected"
        for api in report["apis"]
    )
    assert all(
        api["agentic"]["wiki_off"]["observed_status"] == "disabled"
        for api in report["apis"]
    )
    assert "secret" not in report_path.read_text(encoding="utf-8")
    assert "digest" not in report_path.read_text(encoding="utf-8")
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

    report = json.loads((tmp_path / "smoke.json").read_text(encoding="utf-8"))
    assert report["apis"][0]["collection"] == {
        "ok": False,
        "expected": stack.BC_COLLECTION_SNAPSHOT,
        "observed": stack.BC_COLLECTION_SNAPSHOT | {"chunk_count": 1552},
    }


def test_smoke_reports_observed_model_names_when_expected_model_missing(
    tmp_path: Path,
) -> None:
    def fake_http(method: str, url: str, payload: object | None = None) -> object:
        if url.endswith("/health"):
            return {"status": "ok"}
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen3.5:35b"}]}
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
    assert report["apis"][0]["model"] == {
        "ok": False,
        "expected": "qwen3.5:122b",
        "observed_names": ["qwen3.5:35b"],
    }


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


def test_smoke_serializes_connection_errors_in_report(tmp_path: Path) -> None:
    def fake_http(method: str, url: str, payload: object | None = None) -> object:
        raise URLError(ConnectionRefusedError(61, "Connection refused"))

    report_path = tmp_path / "smoke.json"
    rc = stack.main(_smoke_args(report_path), http=fake_http)

    assert rc == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    error = report["apis"][0]["health"]["error"]
    assert error["type"] == "URLError"
    assert error["reason"] == "[Errno 61] Connection refused"


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
    for host_port in range(8881, 8885):
        assert f'"{host_port}:8080"' in text
    assert text.count("http://host.docker.internal:4000") == 8
    assert "http://host.docker.internal:5000" not in text
    assert "http://host.docker.internal:6000" not in text
    assert "http://host.docker.internal:7000" not in text


def _minimal_source(root: Path) -> Path:
    source = root / "bc_interpreter"
    source.mkdir()
    for name in (
        "targets.json",
        "interpretation_guide.md",
        "part4_candidate_selection.json",
    ):
        (source / name).write_text("{}\n" if name.endswith(".json") else "guide\n", encoding="utf-8")
    (source / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": str(i)} for i in range(100)]}),
        encoding="utf-8",
    )
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


def _pmids_100() -> set[str]:
    return {str(i) for i in range(100)}


def _manifest_output_root(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "manifested"
    root.mkdir(parents=True)
    manifest_path = root / "experiment_manifest.json"
    manifest_path.write_text(
        Path(
            "res/deep_interpreter/bc/sni_repair_ablation/experiment_manifest_rag4000.json"
        ).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return manifest_path, root / "pairs"


def _successful_condition_artifacts(data_dir: Path) -> None:
    for name in bc_runner.REPORT_FILES:
        (data_dir / name).write_text("ok\n", encoding="utf-8")
    (data_dir / "rag_audit.jsonl").write_text(
        json.dumps(
            {
                "endpoint": "agentic_search",
                "collection_uuid": stack.BC_COLLECTION_ID,
                "use_wiki_context": "wiki-on" in data_dir.parts,
                "success": True,
                "error_type": None,
                "result_count": 3,
            }
        )
        + "\n",
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
        json.dumps(
            {
                "status": "passed",
                "repair_attempt_count": 2,
                "terminal_repair_count": 1,
                "changed_sections": 5,
            }
        ),
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


def test_bc_runner_defaults_to_canonical_bc_source() -> None:
    assert bc_runner.BC_SOURCE == bc_runner.REPO_ROOT / "res/deep_interpreter/bc/bc"


def test_bc_runner_rejects_collection_pmid_mismatch_before_stage(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)
    (source / "papers.json").write_text(
        json.dumps({"papers": [{"pmid": str(i)} for i in range(100)]}),
        encoding="utf-8",
    )
    stage_called = False

    def stage_runner(_data_dir: Path, _env: dict[str, str]) -> int:
        nonlocal stage_called
        stage_called = True
        return 0

    rc = bc_runner.run_condition(
        source=source,
        output_root=tmp_path / "runs",
        pair={
            "pair_id": "01",
            "api_port": 8882,
            "backend_port": 5000,
            "rag_backend_port": 4000,
            "condition_order": ["no-SNI", "SNI"],
        },
        condition=bc_runner.CONDITION_BY_LABEL["no-SNI"],
        stage_runner=stage_runner,
        collection_snapshot=lambda _url: stack.BC_COLLECTION_SNAPSHOT,
        collection_pmids=lambda _url: {str(i) for i in range(99)},
    )

    assert rc == 1
    assert stage_called is False


def test_bc_runner_rejects_empty_matching_pmid_sets_before_stage(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)
    (source / "papers.json").write_text(json.dumps({"papers": []}), encoding="utf-8")
    stage_called = False

    def stage_runner(_data_dir: Path, _env: dict[str, str]) -> int:
        nonlocal stage_called
        stage_called = True
        return 0

    rc = bc_runner.run_condition(
        source=source,
        output_root=tmp_path / "runs",
        pair={
            "pair_id": "01",
            "api_port": 8882,
            "backend_port": 5000,
            "rag_backend_port": 4000,
            "condition_order": ["no-SNI", "SNI"],
        },
        condition=bc_runner.CONDITION_BY_LABEL["no-SNI"],
        stage_runner=stage_runner,
        collection_snapshot=lambda _url: stack.BC_COLLECTION_SNAPSHOT,
        collection_pmids=lambda _url: set(),
    )

    assert rc == 1
    assert stage_called is False


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


def test_bc_runner_clears_copied_runtime_scratch(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)
    runtime_dirs = ("before", "after", "diffs", "logs")
    root_artifacts = (
        "timing.json",
        "run_manifest.json",
        "guardrail_manifest.json",
        "recovery_manifest.json",
        "report_validation_terminal.json",
        "rag_audit.jsonl",
        "rag_binding.json",
        "collection_snapshot.json",
        "reporter_attempt_1.json",
        "repair_trace.jsonl",
        "writer.trace",
        "token_usage.json",
        "part1_tokens.json",
        "part1_run.stdout.log",
        "part2_run.stdout.jsonl",
        "part3_run.stderr.log",
    )
    for directory in runtime_dirs:
        (source / directory).mkdir()
        (source / directory / "stale.txt").write_text("stale\n", encoding="utf-8")
    for name in root_artifacts:
        (source / name).write_text("stale\n", encoding="utf-8")

    run_dir = bc_runner.prepare_condition_copy(
        source=source,
        output_root=tmp_path / "runs",
        pair_id=2,
        condition=bc_runner.CONDITIONS[0],
    )

    assert all((source / directory / "stale.txt").exists() for directory in runtime_dirs)
    assert all((source / name).exists() for name in root_artifacts)
    assert all(not any((run_dir / directory).iterdir()) for directory in runtime_dirs)
    assert all(not (run_dir / name).exists() for name in root_artifacts)


def test_bc_runner_propagates_runtime_scratch_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _minimal_source(tmp_path)
    (source / "before").mkdir()
    (source / "before" / "stale.txt").write_text("stale\n", encoding="utf-8")
    real_rmtree = bc_runner.shutil.rmtree

    def fail_before(path: Path, *args: object, **kwargs: object) -> None:
        if Path(path).name == "before":
            if kwargs.get("ignore_errors") is True:
                return
            raise OSError("cannot remove before")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(bc_runner.shutil, "rmtree", fail_before)

    with pytest.raises(OSError, match="cannot remove before"):
        bc_runner.prepare_condition_copy(
            source=source,
            output_root=tmp_path / "runs",
            pair_id=2,
            condition=bc_runner.CONDITIONS[0],
        )

    run_dir = tmp_path / "runs" / "pair-02" / "wiki-on"
    assert not (run_dir / "run_targets.json").exists()


def test_bc_runner_allows_runtime_targets_data_directory_update(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)
    targets = {
        "interest_celltypes": ["B cell"],
        "interest_clusters": ["4"],
        "sel_factor": "CXCL13",
        "data_directory": "/old/run",
    }
    (source / "targets.json").write_text(json.dumps(targets), encoding="utf-8")
    run_dir = bc_runner.prepare_condition_copy(
        source=source,
        output_root=tmp_path / "runs",
        pair_id=1,
        condition=bc_runner.CONDITIONS[0],
    )

    rewritten_targets = targets | {"data_directory": str(run_dir.resolve())}
    (run_dir / "targets.json").write_text(json.dumps(rewritten_targets), encoding="utf-8")

    bc_runner._verify_source_manifest(run_dir)


def test_bc_runner_rejects_runtime_targets_selection_change(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)
    targets = {
        "interest_celltypes": ["B cell"],
        "interest_clusters": ["4"],
        "sel_factor": "CXCL13",
        "data_directory": "/old/run",
    }
    (source / "targets.json").write_text(json.dumps(targets), encoding="utf-8")
    run_dir = bc_runner.prepare_condition_copy(
        source=source,
        output_root=tmp_path / "runs",
        pair_id=1,
        condition=bc_runner.CONDITIONS[0],
    )
    rewritten_targets = targets | {
        "interest_celltypes": ["Plasma cell"],
        "data_directory": str(run_dir.resolve()),
    }
    (run_dir / "targets.json").write_text(json.dumps(rewritten_targets), encoding="utf-8")

    with pytest.raises(RuntimeError, match="copied target selection changed during run"):
        bc_runner._verify_source_manifest(run_dir)


def test_bc_runner_pair_uses_sequential_conditions_with_fixed_endpoint_env(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)
    manifest_path, output_root = _manifest_output_root(tmp_path)
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
            str(output_root),
            "--manifest",
            str(manifest_path),
            "--source",
            str(source),
        ],
        stage_runner=fake_stage,
        collection_snapshot=lambda _api_url: stack.BC_COLLECTION_SNAPSHOT,
        collection_pmids=lambda _api_url: _pmids_100(),
    )

    assert rc == 0
    assert [name for _, name, _ in calls] == ["wiki-off", "wiki-on"]
    off_env = calls[0][2]
    on_env = calls[1][2]
    assert on_env["OLLAMA_BASE_URL"] == "http://localhost:5000"
    assert on_env["CCI_RAG_BASE_URL"] == "http://localhost:8882"
    assert on_env["DEEP_INTERPRETER_USE_WIKI_CONTEXT"] == "true"
    assert on_env["DEEP_INTERPRETER_REQUIRE_AGENTIC_RAG"] == "true"
    assert on_env["OLLAMA_REQUEST_TIMEOUT_SECONDS"] == "10800"
    assert on_env["REPORTER_ATTEMPT_TIMEOUT_SECONDS"] == "10800"
    assert on_env["DEEP_INTERPRETER_FIXED_COLLECTION_ID"] == stack.BC_COLLECTION_ID
    assert on_env["DEEP_INTERPRETER_RAG_AUDIT_PATH"].endswith("/pairs/pair-01/wiki-on/rag_audit.jsonl")
    assert off_env["DEEP_INTERPRETER_USE_WIKI_CONTEXT"] == "false"
    assert off_env["OLLAMA_REQUEST_TIMEOUT_SECONDS"] == "10800"
    assert off_env["REPORTER_ATTEMPT_TIMEOUT_SECONDS"] == "10800"
    assert off_env["DEEP_INTERPRETER_FIXED_COLLECTION_ID"] == stack.BC_COLLECTION_ID
    manifest = json.loads(
        (output_root / "pair-01" / "wiki-off" / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["collection"] == stack.BC_COLLECTION_SNAPSHOT
    assert manifest["backend_port"] == 5000
    assert manifest["rag_backend_port"] == 4000
    assert manifest["rag_api_url"] == "http://localhost:8882"
    assert manifest["condition_label"] == "no-SNI"
    assert manifest["pair_condition_order"] == ["no-SNI", "SNI"]
    assert manifest["return_status"] == "passed"


def test_bc_runner_run_pair_stops_after_first_condition_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_run_condition(**kwargs: object) -> int:
        condition = kwargs["condition"]
        assert isinstance(condition, bc_runner.Condition)
        calls.append(condition.label)
        return 1 if condition.label == "no-SNI" else 0

    monkeypatch.setattr(bc_runner, "run_condition", fake_run_condition)

    rc = bc_runner.run_pair(
        {
            "pair_id": "01",
            "api_port": 8882,
            "backend_port": 5000,
            "rag_backend_port": 4000,
            "condition_order": ["no-SNI", "SNI"],
        },
        source=tmp_path / "source",
        output_root=tmp_path / "runs",
        stage_runner=lambda _data_dir, _env: 0,
        collection_snapshot=lambda _api_url: stack.BC_COLLECTION_SNAPSHOT,
    )

    assert rc == 1
    assert calls == ["no-SNI"]


def test_bc_runner_manifest_validates_replacement_rag_port_and_frozen_schedule(tmp_path: Path) -> None:
    manifest_path, _output_root = _manifest_output_root(tmp_path)
    manifest = bc_runner.load_experiment_manifest(manifest_path)

    assert [
        (
            item["pair_id"],
            item["api_port"],
            item["backend_port"],
            item["rag_backend_port"],
            item["condition_order"],
        )
        for item in manifest["pairs"]
    ] == [
        ("01", 8882, 5000, 4000, ["no-SNI", "SNI"]),
        ("02", 8883, 6000, 4000, ["SNI", "no-SNI"]),
        ("03", 8884, 7000, 4000, ["no-SNI", "SNI"]),
        ("04", 8882, 5000, 4000, ["SNI", "no-SNI"]),
        ("05", 8883, 6000, 4000, ["no-SNI", "SNI"]),
        ("06", 8884, 7000, 4000, ["SNI", "no-SNI"]),
        ("07", 8882, 5000, 4000, ["no-SNI", "SNI"]),
        ("08", 8883, 6000, 4000, ["SNI", "no-SNI"]),
        ("09", 8884, 7000, 4000, ["no-SNI", "SNI"]),
        ("10", 8882, 5000, 4000, ["SNI", "no-SNI"]),
    ]
    assert [item["backend_port"] for item in manifest["pairs"]].count(5000) == 4
    assert [item["backend_port"] for item in manifest["pairs"]].count(6000) == 3
    assert [item["backend_port"] for item in manifest["pairs"]].count(7000) == 3
    assert [item["condition_order"][0] for item in manifest["pairs"]].count("SNI") == 5


def test_bc_runner_rejects_incorrect_replacement_rag_port_or_schedule(tmp_path: Path) -> None:
    manifest_path, _output_root = _manifest_output_root(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    bad_rag = tmp_path / "bad-rag.json"
    manifest["rag_backend_port"] = 5000
    bad_rag.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="rag_backend_port"):
        bc_runner.load_experiment_manifest(bad_rag)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bad_schedule = tmp_path / "bad-schedule.json"
    manifest["ordered_pairs"][0]["api_port"] = 8881
    bad_schedule.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="pair 01"):
        bc_runner.load_experiment_manifest(bad_schedule)


def test_bc_runner_all_schedules_one_pair_batches_in_manifest_order(tmp_path: Path) -> None:
    manifest_path, _output_root = _manifest_output_root(tmp_path)
    manifest = bc_runner.load_experiment_manifest(manifest_path)
    schedule = bc_runner.build_schedule(manifest)

    assert [[item["pair_id"] for item in batch] for batch in schedule] == [
        [f"{idx:02d}"] for idx in range(1, 11)
    ]


def test_bc_runner_rejects_manifest_drift_before_copy(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)
    manifest_path, output_root = _manifest_output_root(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["fixed_collection"]["expected_chunk_count"] = 1552
    manifest["ordered_pairs"][0]["condition_order"] = ["SNI", "no-SNI"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    rc = bc_runner.main(
        ["--pair", "1", "--output-root", str(output_root), "--manifest", str(manifest_path), "--source", str(source)],
        stage_runner=lambda data_dir, env: 0,
        collection_snapshot=lambda _api_url: stack.BC_COLLECTION_SNAPSHOT,
    )

    assert rc == 1
    assert not output_root.exists()


def test_bc_runner_all_schedules_isolated_pair_processes_without_stage_state_leak(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)
    manifest_path, output_root = _manifest_output_root(tmp_path)
    started: list[dict[str, object]] = []
    lock = threading.Lock()
    all_first_batch_started = threading.Event()
    release = threading.Event()

    def forbidden_stage(data_dir: Path, env: dict[str, str]) -> int:
        raise AssertionError("all must not call in-process stage runner")

    def fake_pair_process(pair: bc_runner.ManifestPair, output_root: Path, source: Path, env: dict[str, str]) -> int:
        with lock:
            started.append(
                {
                    "pair_id": pair["pair_id"],
                    "condition_order": pair["condition_order"],
                    "backend": env["BC_SNI_BACKEND_PORT"],
                    "api": env["BC_SNI_API_PORT"],
                    "audit_root": env["BC_SNI_PAIR_AUDIT_ROOT"],
                    "rag_binding_root": env["BC_SNI_PAIR_RAG_BINDING_ROOT"],
                }
            )
            if len(started) == 1:
                all_first_batch_started.set()
        release.wait(1)
        return 0

    def run_all() -> None:
        rc = bc_runner.main(
            [
                "--all",
                "--output-root",
                str(output_root),
                "--manifest",
                str(manifest_path),
                "--source",
                str(source),
            ],
            stage_runner=forbidden_stage,
            collection_snapshot=lambda _api_url: stack.BC_COLLECTION_SNAPSHOT,
            pair_process_runner=fake_pair_process,
        )
        assert rc == 0

    thread = threading.Thread(target=run_all)
    thread.start()
    assert all_first_batch_started.wait(1)
    with lock:
        first_batch = list(started)
    release.set()
    thread.join(2)

    assert not thread.is_alive()
    assert len(started) == 10
    assert [entry["pair_id"] for entry in first_batch] == ["01"]
    assert [entry["backend"] for entry in first_batch] == ["5000"]
    assert [entry["api"] for entry in first_batch] == ["8882"]
    assert len({entry["audit_root"] for entry in started}) == 10
    assert len({entry["rag_binding_root"] for entry in started}) == 10
    assert next(entry for entry in started if entry["pair_id"] == "01")["condition_order"] == [
        "no-SNI",
        "SNI",
    ]


def test_bc_runner_metrics_count_terminal_synthesis_repair(tmp_path: Path) -> None:
    data_dir = tmp_path / "condition"
    data_dir.mkdir()
    _successful_condition_artifacts(data_dir)
    with (data_dir / "rag_audit.jsonl").open("a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "endpoint": "agentic_search",
                    "collection_uuid": stack.BC_COLLECTION_ID,
                    "use_wiki_context": False,
                    "success": False,
                    "error_type": "NoRelevantContext",
                    "result_count": 0,
                }
            )
            + "\n"
        )

    metrics = bc_runner.extract_metrics(data_dir)

    assert metrics["parts"] == {
        "repair_attempt_count": 2,
        "terminal_repair_count": 1,
        "total_repair_count": 3,
        "changed_sections": 5,
    }
    assert metrics["synthesis"] == {
        "repair_attempt_count": 3,
        "terminal_repair_count": 1,
        "total_repair_count": 4,
        "changed_claims": 4,
    }
    assert metrics["retrieval"] == {
        "attempt_count": 2,
        "positive_result_count": 1,
        "zero_hit_count": 1,
        "unique_query_count": 0,
        "duplicate_attempt_count": 0,
        "unique_result_pmid_count": 0,
        "retrieval_cache_hits": 0,
        "elapsed_seconds_total": 0,
    }
    assert metrics["artifacts"]["part1_final.md"]["initial_error_count"] == 1
    assert metrics["artifacts"]["part1_final.md"]["final_error_count"] == 0
    assert metrics["artifacts"]["synthesis.md"]["initial_error_count"] == 3


def test_bc_runner_metrics_aggregate_rag_observability(tmp_path: Path) -> None:
    data_dir = tmp_path / "condition"
    data_dir.mkdir()
    _successful_condition_artifacts(data_dir)
    (data_dir / "rag_audit.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "endpoint": "agentic_search",
                        "collection_uuid": stack.BC_COLLECTION_ID,
                        "use_wiki_context": False,
                        "success": True,
                        "error_type": None,
                        "result_count": 2,
                        "query_sha256": "query-a",
                        "elapsed_seconds": 1.25,
                        "result_pmids": ["12345678", "87654321"],
                    }
                ),
                json.dumps(
                    {
                        "endpoint": "agentic_search",
                        "collection_uuid": stack.BC_COLLECTION_ID,
                        "use_wiki_context": False,
                        "success": True,
                        "error_type": None,
                        "result_count": 1,
                        "query_sha256": "query-a",
                        "elapsed_seconds": 0.75,
                        "result_pmids": ["87654321", "22222222"],
                    }
                ),
                json.dumps(
                    {
                        "endpoint": "agentic_search",
                        "collection_uuid": stack.BC_COLLECTION_ID,
                        "use_wiki_context": False,
                        "success": False,
                        "error_type": "NoRelevantContext",
                        "result_count": 0,
                        "query_sha256": "query-b",
                        "elapsed_seconds": 0.5,
                        "result_pmids": [],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (data_dir / "parts_guardrail_result.json").write_text(
        json.dumps({"claim_selection": {"retrieval_cache_hits": 2}}),
        encoding="utf-8",
    )
    (data_dir / "synthesis_validation.json").write_text(
        json.dumps(
            {
                "synthesis_guardrail": {
                    "claim_selection": {"retrieval_cache_hits": 3}
                }
            }
        ),
        encoding="utf-8",
    )

    metrics = bc_runner.extract_metrics(data_dir)

    assert metrics["retrieval"] == {
        "attempt_count": 3,
        "positive_result_count": 2,
        "zero_hit_count": 1,
        "unique_query_count": 2,
        "duplicate_attempt_count": 1,
        "unique_result_pmid_count": 3,
        "retrieval_cache_hits": 5,
        "elapsed_seconds_total": 2.5,
    }


def test_bc_runner_accepts_no_relevant_context_zero_hit_audit(tmp_path: Path) -> None:
    data_dir = tmp_path / "condition"
    data_dir.mkdir()
    (data_dir / "rag_audit.jsonl").write_text(
        json.dumps(
            {
                "endpoint": "agentic_search",
                "collection_uuid": stack.BC_COLLECTION_ID,
                "use_wiki_context": False,
                "success": False,
                "error_type": "NoRelevantContext",
                "result_count": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    bc_runner._validate_rag_audit(data_dir, bc_runner.CONDITION_BY_LABEL["no-SNI"])


def test_bc_runner_rejects_non_no_relevant_context_error_audit(tmp_path: Path) -> None:
    data_dir = tmp_path / "condition"
    data_dir.mkdir()
    (data_dir / "rag_audit.jsonl").write_text(
        json.dumps(
            {
                "endpoint": "agentic_search",
                "collection_uuid": stack.BC_COLLECTION_ID,
                "use_wiki_context": False,
                "success": False,
                "error_type": "TimeoutError",
                "result_count": 0,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="invalid RAG audit record"):
        bc_runner._validate_rag_audit(data_dir, bc_runner.CONDITION_BY_LABEL["no-SNI"])


def test_bc_runner_rejects_malformed_zero_hit_result_count(tmp_path: Path) -> None:
    data_dir = tmp_path / "condition"
    data_dir.mkdir()
    (data_dir / "rag_audit.jsonl").write_text(
        json.dumps(
            {
                "endpoint": "agentic_search",
                "collection_uuid": stack.BC_COLLECTION_ID,
                "use_wiki_context": False,
                "success": False,
                "error_type": "NoRelevantContext",
                "result_count": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="invalid RAG audit record"):
        bc_runner._validate_rag_audit(data_dir, bc_runner.CONDITION_BY_LABEL["no-SNI"])


def test_bc_runner_fails_on_collection_drift_or_invalid_audit(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)
    manifest_path, audit_output = _manifest_output_root(tmp_path)
    drift_manifest, drift_output = _manifest_output_root(tmp_path / "drift-root")

    def fake_stage(data_dir: Path, env: dict[str, str]) -> int:
        _successful_condition_artifacts(data_dir)
        (data_dir / "rag_audit.jsonl").write_text(
            json.dumps(
                {
                    "endpoint": "agentic_search",
                    "collection_uuid": stack.BC_COLLECTION_ID,
                    "use_wiki_context": "wiki-on" in data_dir.parts,
                    "success": False,
                    "error_type": "RuntimeError",
                    "result_count": 0,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return 0

    audit_rc = bc_runner.main(
        [
            "--pair",
            "1",
            "--output-root",
            str(audit_output),
            "--manifest",
            str(manifest_path),
            "--source",
            str(source),
        ],
        stage_runner=fake_stage,
        collection_snapshot=lambda _api_url: stack.BC_COLLECTION_SNAPSHOT,
        collection_pmids=lambda _api_url: _pmids_100(),
    )
    drift_rc = bc_runner.main(
        [
            "--pair",
            "1",
            "--output-root",
            str(drift_output),
            "--manifest",
            str(drift_manifest),
            "--source",
            str(source),
        ],
        stage_runner=lambda data_dir, env: (_successful_condition_artifacts(data_dir) or 0),
        collection_snapshot=lambda _api_url: stack.BC_COLLECTION_SNAPSHOT | {"chunk_count": 1552},
        collection_pmids=lambda _api_url: _pmids_100(),
    )

    assert audit_rc == 1
    assert drift_rc == 1


def test_bc_runner_rejects_output_root_inside_source_before_copy(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)
    manifest_path, _output = _manifest_output_root(tmp_path)
    output_root = source / "nested-runs"

    rc = bc_runner.main(
        [
            "--pair",
            "1",
            "--output-root",
            str(output_root),
            "--manifest",
            str(manifest_path),
            "--source",
            str(source),
        ],
        stage_runner=lambda data_dir, env: 0,
        collection_snapshot=lambda _api_url: stack.BC_COLLECTION_SNAPSHOT,
    )

    assert rc == 1
    assert not output_root.exists()


def test_bc_runner_preserves_post_stage_failure_evidence_and_metrics(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)
    manifest_path, output_root = _manifest_output_root(tmp_path)

    def fake_stage(data_dir: Path, env: dict[str, str]) -> int:
        _successful_condition_artifacts(data_dir)
        (data_dir / "rag_audit.jsonl").write_text(
            json.dumps(
                {
                    "endpoint": "agentic_search",
                    "collection_uuid": stack.BC_COLLECTION_ID,
                    "use_wiki_context": "wiki-on" in data_dir.parts,
                    "success": False,
                    "error_type": "TimeoutError",
                    "result_count": 0,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return 0

    rc = bc_runner.main(
        [
            "--pair",
            "1",
            "--output-root",
            str(output_root),
            "--manifest",
            str(manifest_path),
            "--source",
            str(source),
        ],
        stage_runner=fake_stage,
        collection_snapshot=lambda _api_url: stack.BC_COLLECTION_SNAPSHOT,
        collection_pmids=lambda _api_url: _pmids_100(),
    )

    failed_dir = output_root / "pair-01" / "wiki-off"
    manifest = json.loads((failed_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert rc == 1
    assert (failed_dir / "after" / "part1_final.md").exists()
    assert manifest["return_status"] == "failed"
    assert manifest["error"]["message"].startswith("invalid RAG audit record")
    assert manifest["metrics"]["synthesis"]["total_repair_count"] == 4


def test_bc_runner_fails_when_audit_is_missing(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)
    manifest_path, output_root = _manifest_output_root(tmp_path)

    def fake_stage(data_dir: Path, env: dict[str, str]) -> int:
        _successful_condition_artifacts(data_dir)
        (data_dir / "rag_audit.jsonl").unlink()
        return 0

    rc = bc_runner.main(
        [
            "--pair",
            "1",
            "--output-root",
            str(output_root),
            "--manifest",
            str(manifest_path),
            "--source",
            str(source),
        ],
        stage_runner=fake_stage,
        collection_snapshot=lambda _api_url: stack.BC_COLLECTION_SNAPSHOT,
        collection_pmids=lambda _api_url: _pmids_100(),
    )

    assert rc == 1


def test_bc_runner_fails_when_final_guardrail_errors_remain(tmp_path: Path) -> None:
    source = _minimal_source(tmp_path)
    manifest_path, output_root = _manifest_output_root(tmp_path)

    def fake_stage(data_dir: Path, env: dict[str, str]) -> int:
        _successful_condition_artifacts(data_dir)
        (data_dir / "report_validation_final.json").write_text(
            json.dumps({"issues": [{"file": "part2_final.md", "severity": "error"}]}),
            encoding="utf-8",
        )
        return 0

    rc = bc_runner.main(
        [
            "--pair",
            "1",
            "--output-root",
            str(output_root),
            "--manifest",
            str(manifest_path),
            "--source",
            str(source),
        ],
        stage_runner=fake_stage,
        collection_snapshot=lambda _api_url: stack.BC_COLLECTION_SNAPSHOT,
        collection_pmids=lambda _api_url: _pmids_100(),
    )

    assert rc == 1


def test_bc_runner_smoke_is_dry_manifest_preflight(tmp_path: Path, capsys) -> None:
    source = _minimal_source(tmp_path)
    _manifest_path, output_root = _manifest_output_root(tmp_path)
    seen: list[str] = []

    def fake_stage(data_dir: Path, env: dict[str, str]) -> int:
        seen.append(str(data_dir.relative_to(tmp_path / "runs")))
        _successful_condition_artifacts(data_dir)
        return 0

    rc = bc_runner.main(
        [
            "--smoke",
            "--output-root",
            str(output_root),
            "--source",
            str(source),
        ],
        stage_runner=fake_stage,
        collection_snapshot=lambda _api_url: (_ for _ in ()).throw(AssertionError("no API call")),
    )

    assert rc == 0
    assert seen == []
    assert not output_root.exists()
    plan = json.loads(capsys.readouterr().out)
    assert plan["ok"] is True
    assert [[item["pair_id"] for item in wave] for wave in plan["schedule"]] == [
        [f"{idx:02d}"] for idx in range(1, 11)
    ]

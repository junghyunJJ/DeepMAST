import json
from email.message import Message
from pathlib import Path
from typing import cast
from urllib.error import HTTPError

from scripts import sni_ablation_api_stack as stack

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

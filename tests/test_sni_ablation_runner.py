import json
from pathlib import Path

from scripts import sni_ablation_api_stack as stack


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
            return {"status": "healthy"}
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen3.5:122b"}]}
        if url.endswith("/collections/abc"):
            return {"uuid": "abc", "name": "baseline", "stats": {"documents": 7}}
        if url.endswith("/agentic-search"):
            use_wiki = dict(payload or {})["use_wiki_context"]
            return {
                "generation": "ok",
                "steps": [
                    {"wiki_context_status": "selected" if use_wiki else "disabled"}
                ],
            }
        raise AssertionError(url)

    rc = stack.main(
        [
            "smoke",
            "--collection-id",
            "abc",
            "--expected-collection",
            '{"uuid":"abc","name":"baseline","stats":{"documents":7}}',
            "--question",
            "Which SNI behavior is active?",
            "--report",
            str(report_path),
            "--sgcp-rag-dir",
            str(tmp_path),
            "--env-file",
            str(env_file),
        ],
        http=fake_http,
    )

    assert rc == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is True
    assert {api["backend_port"] for api in report["apis"]} == {4000, 5000, 6000, 7000}
    assert all(api["model"]["ok"] for api in report["apis"])
    assert all(api["collection"]["ok"] for api in report["apis"])
    assert all(api["agentic"]["wiki_on"]["status"] == "selected" for api in report["apis"])
    assert all(api["agentic"]["wiki_off"]["status"] == "disabled" for api in report["apis"])
    assert "secret" not in report_path.read_text(encoding="utf-8")
    assert any(payload and dict(payload)["use_wiki_context"] is True for _, _, payload in calls)
    assert any(payload and dict(payload)["use_wiki_context"] is False for _, _, payload in calls)


def test_smoke_fails_when_collection_snapshot_changes(tmp_path: Path) -> None:
    def fake_http(method: str, url: str, payload: object | None = None) -> object:
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen3.5:122b"}]}
        if url.endswith("/health"):
            return {"status": "healthy"}
        if "/collections/" in url and not url.endswith("/agentic-search"):
            return {"uuid": "abc", "name": "changed", "stats": {"documents": 8}}
        return {"steps": [{"wiki_context_status": "selected"}]}

    rc = stack.main(
        [
            "smoke",
            "--collection-id",
            "abc",
            "--expected-collection",
            '{"uuid":"abc","name":"baseline","stats":{"documents":7}}',
            "--question",
            "Which SNI behavior is active?",
            "--report",
            str(tmp_path / "smoke.json"),
            "--sgcp-rag-dir",
            str(tmp_path),
            "--env-file",
            str(tmp_path / ".env"),
        ],
        http=fake_http,
    )

    assert rc == 1


def test_smoke_records_endpoint_errors_in_report(tmp_path: Path) -> None:
    def fake_http(method: str, url: str, payload: object | None = None) -> object:
        if url.endswith("/health"):
            return {"status": "healthy"}
        if url.endswith("/api/tags"):
            return {"models": [{"name": "qwen3.5:122b"}]}
        if url.endswith("/collections/abc"):
            return {"uuid": "abc", "name": "baseline", "stats": {"documents": 7}}
        raise TimeoutError("timed out")

    report_path = tmp_path / "smoke.json"
    rc = stack.main(
        [
            "smoke",
            "--collection-id",
            "abc",
            "--expected-collection",
            '{"uuid":"abc","name":"baseline","stats":{"documents":7}}',
            "--question",
            "Which SNI behavior is active?",
            "--report",
            str(report_path),
            "--sgcp-rag-dir",
            str(tmp_path),
            "--env-file",
            str(tmp_path / ".env"),
        ],
        http=fake_http,
    )

    assert rc == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] is False
    assert report["apis"][0]["agentic"]["wiki_on"]["error"] == "TimeoutError"


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

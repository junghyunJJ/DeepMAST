from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib import request

COMPOSE_FILE = Path(__file__).with_name("sgcp_rag_sni_ablation.compose.yml")
PROJECT_NAME = "sgcp-sni-ablation"
MODEL = "qwen3.5:122b"
HTTP_TIMEOUT_SECONDS = 300
BC_COLLECTION_ID = "a208e916-bd32-405a-9eee-de4cd82b2a3b"
BC_COLLECTION_SNAPSHOT: dict[str, object] = {
    "uuid": BC_COLLECTION_ID,
    "name": "deep_interpreter_bc_cfd96ddb_all",
    "metadata": {"type": "literature_rag", "created_by": "deep_interpreter"},
    "document_count": 100,
    "chunk_count": 1553,
}
APIS = (
    {"service": "sgcp-sni-api-4000", "api_port": 8881, "backend_port": 4000},
    {"service": "sgcp-sni-api-5000", "api_port": 8882, "backend_port": 5000},
    {"service": "sgcp-sni-api-6000", "api_port": 8883, "backend_port": 6000},
    {"service": "sgcp-sni-api-7000", "api_port": 8884, "backend_port": 7000},
)

Docker = Callable[[list[str]], object]
Http = Callable[[str, str, object | None], object]
HealthHttp = Callable[[str, float], object]
Sleep = Callable[[float], object]
Clock = Callable[[], float]


def _docker(cmd: list[str]) -> None:
    subprocess.check_call(cmd)


def _http_json(
    method: str,
    url: str,
    payload: object | None,
    *,
    timeout_seconds: float,
) -> object:
    body = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"} if body else {}
    req = request.Request(url, data=body, headers=headers, method=method)
    with request.urlopen(req, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode() or "{}")


def _http(method: str, url: str, payload: object | None = None) -> object:
    return _http_json(method, url, payload, timeout_seconds=HTTP_TIMEOUT_SECONDS)


def _health_http(url: str, timeout_seconds: float) -> object:
    return _http_json("GET", url, None, timeout_seconds=timeout_seconds)


def _compose_args(action: str, env_file: Path) -> list[str]:
    base = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(COMPOSE_FILE),
        "--project-name",
        PROJECT_NAME,
    ]
    services = [api["service"] for api in APIS]
    if action == "up":
        return base + ["up", "-d", "--no-deps", *services]
    if action == "down":
        return base + ["rm", "-sf", *services]
    return base + ["ps", *services]


def _health_url(api: dict[str, object]) -> str:
    return f"http://localhost:{api['api_port']}/health"


def _readiness_errors(health_http: HealthHttp, timeout_seconds: float) -> list[str]:
    errors: list[str] = []
    for api in APIS:
        url = _health_url(api)
        try:
            response = health_http(url, timeout_seconds)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{url} {type(exc).__name__}: {exc}")
            break
        status = response.get("status") if isinstance(response, dict) else None
        if status != "ok":
            errors.append(f"{url} status={status}")
    return errors


def _wait_ready(
    health_http: HealthHttp,
    sleep: Sleep,
    clock: Clock,
    *,
    timeout_seconds: float,
    interval_seconds: float,
) -> int:
    deadline = clock() + timeout_seconds
    while True:
        remaining = max(0.0, deadline - clock())
        errors = _readiness_errors(health_http, remaining)
        if not errors:
            return 0
        if clock() >= deadline:
            print(
                "unready ablation API endpoints: " + "; ".join(errors),
                file=sys.stderr,
            )
            return 1
        sleep(interval_seconds)


def _with_runtime_env(
    args: argparse.Namespace,
    docker: Docker,
    action: str,
    http: Http,
    health_http: HealthHttp,
    sleep: Sleep,
    clock: Clock,
) -> int:
    previous = {
        "SGCP_RAG_DIR": os.environ.get("SGCP_RAG_DIR"),
        "SGCP_RAG_ENV_FILE": os.environ.get("SGCP_RAG_ENV_FILE"),
    }
    os.environ["SGCP_RAG_DIR"] = str(args.sgcp_rag_dir)
    os.environ["SGCP_RAG_ENV_FILE"] = str(args.env_file)
    try:
        docker(_compose_args(action, args.env_file))
        if action == "up":
            return _wait_ready(
                health_http,
                sleep,
                clock,
                timeout_seconds=args.ready_timeout,
                interval_seconds=args.ready_interval,
            )
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    return 0


def _has_model(tags: object) -> bool:
    if not isinstance(tags, dict):
        return False
    models = tags.get("models")
    return isinstance(models, list) and any(
        isinstance(model, dict) and model.get("name") == MODEL for model in models
    )


def _agentic_case(
    http: Http,
    api_port: int,
    collection_id: str,
    question: str,
    use_wiki_context: bool,
    expected_status: str,
) -> dict[str, Any]:
    payload = {
        "question": question,
        "llm_provider": "ollama",
        "llm_model": MODEL,
        "use_wiki_context": use_wiki_context,
    }
    result = http(
        "POST",
        f"http://localhost:{api_port}/collections/{collection_id}/agentic-search",
        payload,
    )
    observed_status = result.get("wiki_context_status") if isinstance(result, dict) else None
    return {
        "ok": observed_status == expected_status,
        "expected_status": expected_status,
        "observed_status": observed_status,
    }


def _error(exc: Exception) -> dict[str, Any]:
    error: dict[str, Any] = {"type": type(exc).__name__, "message": str(exc)}
    for attr in ("code", "reason", "url"):
        value = getattr(exc, attr, None)
        if value is not None:
            error[attr] = value
    return {"ok": False, "error": error}


def _fixed_collection_error(args: argparse.Namespace) -> dict[str, Any] | None:
    if args.collection_id != BC_COLLECTION_ID:
        return {
            "type": "FixedCollectionMismatch",
            "message": f"smoke requires collection {BC_COLLECTION_ID}",
        }
    if args.expected_collection is None:
        return None
    try:
        expected_collection = json.loads(args.expected_collection)
    except json.JSONDecodeError as exc:
        return {"type": type(exc).__name__, "message": str(exc)}
    if expected_collection != BC_COLLECTION_SNAPSHOT:
        return {
            "type": "FixedCollectionMismatch",
            "message": "smoke expected collection must match the fixed BC snapshot",
        }
    return None


def _smoke(args: argparse.Namespace, http: Http) -> int:
    report_path = Path(args.report)
    fixed_error = _fixed_collection_error(args)
    if fixed_error is not None:
        report_path.write_text(
            json.dumps({"ok": False, "error": fixed_error}, indent=2) + "\n",
            encoding="utf-8",
        )
        return 1
    report: dict[str, Any] = {"ok": True, "model": MODEL, "apis": []}
    for api in APIS:
        api_port = int(api["api_port"])
        backend_port = int(api["backend_port"])
        try:
            health_response = http("GET", f"http://localhost:{api_port}/health", None)
            health_status = (
                health_response.get("status")
                if isinstance(health_response, dict)
                else None
            )
            health = {"ok": health_status == "ok", "status": health_status}
        except Exception as exc:  # noqa: BLE001
            health = _error(exc)
        try:
            tags = http("GET", f"http://localhost:{backend_port}/api/tags", None)
            model = {"ok": _has_model(tags), "expected": MODEL}
        except Exception as exc:  # noqa: BLE001
            model = _error(exc) | {"expected": MODEL}
        try:
            collection = http(
                "GET", f"http://localhost:{api_port}/collections/{args.collection_id}", None
            )
            collection_check = {"ok": collection == BC_COLLECTION_SNAPSHOT}
        except Exception as exc:  # noqa: BLE001
            collection_check = _error(exc)
        try:
            wiki_on = _agentic_case(
                http,
                api_port,
                args.collection_id,
                args.question,
                True,
                args.expected_wiki_on_status,
            )
        except Exception as exc:  # noqa: BLE001
            wiki_on = _error(exc)
        try:
            wiki_off = _agentic_case(
                http,
                api_port,
                args.collection_id,
                args.question,
                False,
                args.expected_wiki_off_status,
            )
        except Exception as exc:  # noqa: BLE001
            wiki_off = _error(exc)
        api_report = {
            "service": api["service"],
            "api_port": api_port,
            "backend_port": backend_port,
            "health": health,
            "model": model,
            "collection": collection_check,
            "agentic": {
                "wiki_on": wiki_on,
                "wiki_off": wiki_off,
            },
        }
        checks = [
            api_report["health"]["ok"],
            api_report["model"]["ok"],
            api_report["collection"]["ok"],
            api_report["agentic"]["wiki_on"]["ok"],
            api_report["agentic"]["wiki_off"]["ok"],
        ]
        api_report["ok"] = all(checks)
        report["apis"].append(api_report)
    report["ok"] = all(api["ok"] for api in report["apis"])
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--sgcp-rag-dir",
        type=Path,
        default=Path("/Users/jungj2/Dropbox/Metadata/mcp/sgcp-rag"),
    )
    common.add_argument(
        "--env-file",
        type=Path,
        default=Path("/Users/jungj2/Dropbox/Metadata/mcp/sgcp-rag/.env"),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser("up", parents=[common])
    up.add_argument("--ready-timeout", type=float, default=600.0)
    up.add_argument("--ready-interval", type=float, default=5.0)
    for command in ("down", "status"):
        sub.add_parser(command, parents=[common])
    smoke = sub.add_parser("smoke", parents=[common])
    smoke.add_argument("--collection-id", required=True)
    smoke.add_argument("--expected-collection")
    smoke.add_argument("--question", required=True)
    smoke.add_argument("--report", required=True)
    smoke.add_argument("--expected-wiki-on-status", default="selected")
    smoke.add_argument("--expected-wiki-off-status", default="disabled")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    docker: Docker = _docker,
    http: Http = _http,
    health_http: HealthHttp | None = None,
    sleep: Sleep = time.sleep,
    clock: Clock = time.monotonic,
) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "smoke":
        return _smoke(args, http)
    readiness_http = health_http
    if readiness_http is None:
        readiness_http = _health_http if http is _http else lambda url, timeout: http("GET", url, None)
    return _with_runtime_env(
        args,
        docker,
        args.command,
        http,
        readiness_http,
        sleep,
        clock,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

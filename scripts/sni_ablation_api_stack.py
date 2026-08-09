from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib import request

COMPOSE_FILE = Path(__file__).with_name("sgcp_rag_sni_ablation.compose.yml")
PROJECT_NAME = "sgcp-sni-ablation"
MODEL = "qwen3.5:122b"
HTTP_TIMEOUT_SECONDS = 300
APIS = (
    {"service": "sgcp-sni-api-4000", "api_port": 8881, "backend_port": 4000},
    {"service": "sgcp-sni-api-5000", "api_port": 8882, "backend_port": 5000},
    {"service": "sgcp-sni-api-6000", "api_port": 8883, "backend_port": 6000},
    {"service": "sgcp-sni-api-7000", "api_port": 8884, "backend_port": 7000},
)

Docker = Callable[[list[str]], object]
Http = Callable[[str, str, object | None], object]


def _docker(cmd: list[str]) -> None:
    subprocess.check_call(cmd)


def _http(method: str, url: str, payload: object | None = None) -> object:
    body = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"} if body else {}
    req = request.Request(url, data=body, headers=headers, method=method)
    with request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode() or "{}")


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


def _with_runtime_env(args: argparse.Namespace, docker: Docker, action: str) -> int:
    previous = {
        "SGCP_RAG_DIR": os.environ.get("SGCP_RAG_DIR"),
        "SGCP_RAG_ENV_FILE": os.environ.get("SGCP_RAG_ENV_FILE"),
    }
    os.environ["SGCP_RAG_DIR"] = str(args.sgcp_rag_dir)
    os.environ["SGCP_RAG_ENV_FILE"] = str(args.env_file)
    try:
        docker(_compose_args(action, args.env_file))
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


def _status_in(value: object, expected: str) -> bool:
    if value == expected:
        return True
    if isinstance(value, dict):
        return any(_status_in(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_status_in(item, expected) for item in value)
    return False


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
    ok = _status_in(result, expected_status)
    return {"ok": ok, "status": expected_status if ok else None}


def _error(exc: Exception) -> dict[str, Any]:
    return {"ok": False, "error": type(exc).__name__}


def _smoke(args: argparse.Namespace, http: Http) -> int:
    expected_collection = json.loads(args.expected_collection)
    report: dict[str, Any] = {"ok": True, "model": MODEL, "apis": []}
    for api in APIS:
        api_port = int(api["api_port"])
        backend_port = int(api["backend_port"])
        try:
            health = {"ok": bool(http("GET", f"http://localhost:{api_port}/health", None))}
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
            collection_check = {"ok": collection == expected_collection}
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
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
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
    for command in ("up", "down", "status"):
        sub.add_parser(command, parents=[common])
    smoke = sub.add_parser("smoke", parents=[common])
    smoke.add_argument("--collection-id", required=True)
    smoke.add_argument("--expected-collection", required=True)
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
) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "smoke":
        return _smoke(args, http)
    return _with_runtime_env(args, docker, args.command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

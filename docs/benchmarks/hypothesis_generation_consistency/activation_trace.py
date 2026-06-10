from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Sequence

ADDED_EXPANDED6_SKILL_NAMES = frozenset(
    ("compare-census-gene-pair-by-cell-type", "string-database")
)


def skill_name_from_read_skill_path(skill_path: str) -> str | None:
    path = PurePosixPath(skill_path)
    parts = path.parts
    if len(parts) < 3 or parts[-1] != "SKILL.md":
        return None

    for index, part in enumerate(parts[:-2]):
        if part == "skills" and index + 2 < len(parts):
            return parts[index + 1]
    return None


def extract_read_skill_file_calls(
    *,
    node_path: str,
    node_name: str,
    node_data: Any,
    exposed_skill_names: Sequence[str],
    scope: str = "hypothesis_writer",
) -> list[dict[str, Any]]:
    if scope and scope != node_name and scope not in node_path:
        return []

    exposed = set(exposed_skill_names)
    calls: list[dict[str, Any]] = []
    for message in _messages_from_node_data(node_data):
        for tool_call in getattr(message, "tool_calls", []) or []:
            if (
                not isinstance(tool_call, dict)
                or tool_call.get("name") != "read_skill_file"
            ):
                continue

            args = tool_call.get("args") or {}
            if not isinstance(args, dict):
                continue

            skill_path = args.get("skill_path")
            if not isinstance(skill_path, str):
                continue

            skill_name = skill_name_from_read_skill_path(skill_path)
            if skill_name is None:
                continue

            calls.append(
                {
                    "skill_name": skill_name,
                    "skill_path": skill_path,
                    "tool_call_id": tool_call.get("id"),
                    "node_path": node_path,
                    "node_name": node_name,
                    "registered": skill_name in exposed,
                }
            )
    return calls


def summarize_activation_trace(
    *,
    exposed_skill_names: Sequence[str],
    hypothesis_writer_calls: Sequence[dict[str, Any]],
    all_read_skill_calls: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    exposed = tuple(exposed_skill_names)
    activated_skill_names = sorted(
        {
            call["skill_name"]
            for call in hypothesis_writer_calls
            if call.get("skill_name") in exposed
        }
    )
    activated_added_skill_names = [
        skill_name
        for skill_name in activated_skill_names
        if skill_name in ADDED_EXPANDED6_SKILL_NAMES
    ]

    all_calls = list(
        hypothesis_writer_calls if all_read_skill_calls is None else all_read_skill_calls
    )
    writer_calls = list(hypothesis_writer_calls)
    return {
        "exposed_skill_names": list(exposed),
        "hypothesis_writer_read_skill_file_calls": writer_calls,
        "all_read_skill_file_calls": all_calls,
        "activated_skill_names": activated_skill_names,
        "activated_added_skill_names": activated_added_skill_names,
        "activation_count": len(activated_skill_names),
        "added_activation_count": len(activated_added_skill_names),
    }


def _messages_from_node_data(node_data: Any) -> Sequence[Any]:
    if isinstance(node_data, dict):
        messages = node_data.get("messages", [])
        if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes)):
            return messages
    return []

#!/usr/bin/env python3
"""Check required skill coverage from simple JSON lists or activation traces."""

from __future__ import annotations

import argparse
import json
from pathlib import PurePosixPath
from typing import Any


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _skill_name_from_path(skill_path: str) -> str | None:
    parts = PurePosixPath(skill_path).parts
    for index, part in enumerate(parts):
        if part == "skills" and index + 1 < len(parts):
            return parts[index + 1]
    return None


def _strings(value: Any) -> set[str]:
    if isinstance(value, str):
        return {item.strip() for item in value.split(",") if item.strip()}
    if isinstance(value, list):
        return {item for item in value if isinstance(item, str) and item}
    return set()


def _collect_required_skill_names(value: Any) -> set[str]:
    names: set[str] = set()

    if isinstance(value, str):
        return _strings(value)

    if isinstance(value, list):
        names.update(_strings(value))
        return names

    if isinstance(value, dict):
        for key in ("required_skill_names", "required_skills"):
            names.update(_strings(value.get(key)))

    return names


def _collect_activated_skill_names(value: Any) -> set[str]:
    names: set[str] = set()

    if isinstance(value, str):
        return _strings(value)

    if isinstance(value, list):
        names.update(_strings(value))
        for item in value:
            names.update(_collect_activated_skill_names(item))
        return names

    if isinstance(value, dict):
        for key in ("activated_skill_names", "activated_domain_skills"):
            names.update(_strings(value.get(key)))

        tool_name = value.get("name") or value.get("tool_name")
        args = value.get("args") or value.get("arguments") or {}
        if tool_name == "read_skill_file" and isinstance(args, dict):
            skill_path = args.get("skill_path")
            if isinstance(skill_path, str):
                skill_name = _skill_name_from_path(skill_path)
                if skill_name:
                    names.add(skill_name)

        skill_name = value.get("skill_name")
        if isinstance(skill_name, str) and skill_name:
            names.add(skill_name)

        for key in (
            "tool_history",
            "activation_trace",
            "all_read_skill_file_calls",
            "hypothesis_writer_read_skill_file_calls",
        ):
            names.update(_collect_activated_skill_names(value.get(key)))

    return names


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check whether activated skills cover required skills."
    )
    parser.add_argument("--required", required=True, help="JSON required skill data")
    parser.add_argument("--activated", required=True, help="JSON activated skill data")
    args = parser.parse_args()

    required = sorted(_collect_required_skill_names(_load_json(args.required)))
    activated = sorted(_collect_activated_skill_names(_load_json(args.activated)))
    missing = sorted(set(required) - set(activated))

    print(
        json.dumps(
            {
                "required_skill_names": required,
                "activated_skill_names": activated,
                "missing_required_skills": missing,
                "coverage_complete": not missing,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

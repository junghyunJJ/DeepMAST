"""Core Suite task count and category balance checks."""

from __future__ import annotations

from collections import Counter

from evaluation.schema import ALLOWED_TASK_CATEGORIES, load_yaml


def test_core_suite_has_24_tasks():
    payload = load_yaml("evaluation/core_suite/tasks_v1.yaml")
    assert len(payload["tasks"]) == 24


def test_core_suite_category_balance():
    payload = load_yaml("evaluation/core_suite/tasks_v1.yaml")
    counts = Counter(task["category"] for task in payload["tasks"])
    assert counts == {
        "known_biology": 12,
        "literature_grounding": 6,
        "hitl": 3,
        "failure_recovery": 3,
    }


def test_core_suite_categories_are_allowed():
    payload = load_yaml("evaluation/core_suite/tasks_v1.yaml")
    categories = {task["category"] for task in payload["tasks"]}
    assert categories <= ALLOWED_TASK_CATEGORIES

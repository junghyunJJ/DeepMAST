"""Bound report-writer tools that cannot escape the active run directory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from langchain_core.tools.structured import StructuredTool

from src.agents.drug_target.tools import load_evidence_files, save_drug_md


def _resolve_run_dir(data_dir: str | Path) -> Path:
    path = Path(data_dir).expanduser().resolve()
    if (
        not path.exists()
        or not path.is_dir()
        or path == Path(path.anchor)
        or (path / ".git").exists()
    ):
        raise ValueError("data_dir must be an existing non-root per-run directory")
    return path


def _invoke(tool: BaseTool | Any, **kwargs: Any) -> Any:
    function = getattr(tool, "func", None)
    if callable(function):
        return function(**kwargs)
    invoke = getattr(tool, "invoke", None)
    if callable(invoke):
        return invoke(kwargs)
    return tool(**kwargs)


def production_hypothesis_evidence_tool(data_dir: str | Path) -> StructuredTool:
    """Bind ``load_evidence_files`` to the report repair's hypothesis scope."""

    run_dir = _resolve_run_dir(data_dir)

    def load_evidence_files_for_repair(data_dir: str = "", scope: str = "all") -> Any:
        _ = data_dir, scope
        return _invoke(
            load_evidence_files,
            data_dir=str(run_dir),
            scope="hypothesis",
        )

    return StructuredTool.from_function(
        func=load_evidence_files_for_repair,
        name="load_evidence_files",
        description=(
            "Load the configured run's hypothesis-scoped evidence. "
            "The data directory and scope are fixed for this repair run."
        ),
    )


def production_save_drug_md_tool(data_dir: str | Path) -> StructuredTool:
    """Bind ``save_drug_md`` to the active report run without marker stripping."""

    run_dir = _resolve_run_dir(data_dir)

    def save_drug_md_for_repair(
        content: str | dict | list,
        data_dir: str = "",
        strip_unexpanded_markers: bool = False,
    ) -> Any:
        _ = data_dir, strip_unexpanded_markers
        return _invoke(
            save_drug_md,
            data_dir=str(run_dir),
            content=content,
            strip_unexpanded_markers=False,
        )

    return StructuredTool.from_function(
        func=save_drug_md_for_repair,
        name="save_drug_md",
        description=(
            "Save drug.md only in the configured repair run. "
            "Unexpanded markers are retained for deterministic validation."
        ),
    )

"""Bound production-report tools that cannot escape the active run."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Collection
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool
from langchain_core.tools.structured import StructuredTool

from src.agents.drug_target.tools import (
    load_evidence_files,
    save_drug_md,
    save_evidence,
    save_target_assessment,
)
from src.agents.drug_target.tools.stage_logic import build_evidence_summary
from src.agents.drug_target.deterministic_report import (
    build_report_data,
    render_hybrid_report,
)
from src.agents.drug_target.hybrid_report_sections import (
    REPORT_SECTIONS_FILENAME,
    canonicalize_report_sections,
)


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


def _invoke(tool: Any, **kwargs: Any) -> Any:
    function = getattr(tool, "func", None)
    if callable(function):
        return function(**kwargs)
    invoke = getattr(tool, "invoke", None)
    if callable(invoke):
        return invoke(kwargs)
    if callable(tool):
        return tool(**kwargs)
    raise TypeError("tool must expose func, invoke, or be callable")


def _bound_evidence_tool(data_dir: str | Path, scope: str) -> StructuredTool:
    run_dir = _resolve_run_dir(data_dir)

    def load_evidence_files_for_run(data_dir: str = "", scope: str = "all") -> Any:
        _ = data_dir, scope
        return _invoke(load_evidence_files, data_dir=str(run_dir), scope=scope_for_run)

    scope_for_run = scope
    return StructuredTool.from_function(
        func=load_evidence_files_for_run,
        name="load_evidence_files",
        description="Load evidence only from the configured guarded report run.",
    )


def production_assessment_evidence_tool(data_dir: str | Path) -> StructuredTool:
    """Bind evidence assessment reads to the safe assessment scope."""

    return _bound_evidence_tool(data_dir, "assessment")


def production_hypothesis_evidence_tool(data_dir: str | Path) -> StructuredTool:
    """Bind report-writer reads to the safe hypothesis scope."""

    return _bound_evidence_tool(data_dir, "hypothesis")


def production_evidence_summary_tool(data_dir: str | Path) -> StructuredTool:
    """Bind the reference card to this run and disable legacy hypotheses."""

    run_dir = _resolve_run_dir(data_dir)

    def build_evidence_summary_for_run(
        data_dir: str = "", include_legacy_hypothesis: bool = False
    ) -> Any:
        _ = data_dir, include_legacy_hypothesis
        return _invoke(
            build_evidence_summary,
            data_dir=str(run_dir),
            include_legacy_hypothesis=False,
        )

    return StructuredTool.from_function(
        func=build_evidence_summary_for_run,
        name="build_evidence_summary",
        description="Build the guarded run's non-legacy reference card.",
    )


def _is_forbidden_prior_report_output(filename: str) -> bool:
    name = Path(filename).name.casefold()
    return (name.startswith("hypothesis_report") and name.endswith(".json")) or name == "report_data.json"


def production_assessment_save_evidence_tool(data_dir: str | Path) -> StructuredTool:
    """Bind evidence saves to this run and reserve report-owned outputs."""

    run_dir = _resolve_run_dir(data_dir)

    def save_evidence_for_run(
        data_dir: str = "", filename: str = "", data: str | dict | list = ""
    ) -> Any:
        _ = data_dir
        if _is_forbidden_prior_report_output(filename):
            return json.dumps(
                {
                    "saved": False,
                    "path": str(run_dir / "evidence" / Path(filename).name),
                    "errors": ["reserved guarded report output; save_evidence is not allowed"],
                },
                indent=2,
            )
        return _invoke(
            save_evidence,
            data_dir=str(run_dir),
            filename=filename,
            data=data,
        )

    return StructuredTool.from_function(
        func=save_evidence_for_run,
        name="save_evidence",
        description="Save evidence only in the configured run; report outputs are reserved.",
    )


def production_save_target_assessment_tool(data_dir: str | Path) -> StructuredTool:
    """Bind target_assessment.json writes to the active report run."""

    run_dir = _resolve_run_dir(data_dir)

    def save_target_assessment_for_run(
        data_dir: str = "",
        project_meta: str | dict = "",
        druggability_matrix: str | list = "",
        featured_candidates_deep_dive: str | list = "",
    ) -> Any:
        _ = data_dir
        return _invoke(
            save_target_assessment,
            data_dir=str(run_dir),
            project_meta=project_meta,
            druggability_matrix=druggability_matrix,
            featured_candidates_deep_dive=featured_candidates_deep_dive,
        )

    return StructuredTool.from_function(
        func=save_target_assessment_for_run,
        name="save_target_assessment",
        description="Save target_assessment.json only in the configured report run.",
    )


def production_save_drug_md_tool(data_dir: str | Path) -> StructuredTool:
    """Bind ``save_drug_md`` without allowing placeholder stripping."""

    run_dir = _resolve_run_dir(data_dir)

    def save_drug_md_for_run(
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
        func=save_drug_md_for_run,
        name="save_drug_md",
        description="Save drug.md only in the configured run; markers stay visible.",
    )


_HYBRID_ARTIFACTS = (
    REPORT_SECTIONS_FILENAME,
    "report_data.json",
    "target_assessment.json",
    "drug.md",
    "drug_report_render.json",
)


def _clear_hybrid_artifacts(run_dir: Path) -> None:
    """Remove stale renderer-owned artifacts after a rejected sections payload."""

    from src.agents.drug_target.report_guardrails import clear_derived_report_artifacts

    clear_derived_report_artifacts(
        run_dir,
        include_audits=True,
        include_sources=True,
    )
    for name in _HYBRID_ARTIFACTS:
        path = run_dir / name
        for candidate in (path, path.with_suffix(f"{path.suffix}.tmp")):
            candidate.unlink(missing_ok=True)


def _hybrid_source_paths(run_dir: Path) -> set[str]:
    evidence_dir = run_dir / "evidence"
    if not evidence_dir.is_dir():
        return set()
    return {
        f"evidence/{path.name}"
        for path in evidence_dir.glob("*.json")
        if not _is_forbidden_prior_report_output(path.name)
    }


def production_save_report_sections_tool(
    data_dir: str | Path,
    disease: str,
) -> StructuredTool:
    """Bind canonical hybrid-section rendering to one guarded report run."""

    run_dir = _resolve_run_dir(data_dir)

    def save_report_sections_for_run(payload: dict[str, Any]) -> str:
        try:
            report_data = build_report_data(
                str(run_dir),
                disease,
                hypothesis_data={"hypotheses": []},
                hypothesis_source=REPORT_SECTIONS_FILENAME,
            )
            if not report_data.get("valid"):
                raise ValueError("deterministic report data is invalid")
            canonical, errors = canonicalize_report_sections(
                payload,
                run_dir / "evidence",
                _hybrid_source_paths(run_dir),
                report_data,
            )
            if canonical is None:
                _clear_hybrid_artifacts(run_dir)
                return json.dumps({"saved": False, "errors": errors})

            with tempfile.TemporaryDirectory(
                dir=run_dir,
                prefix=".report-sections-",
            ) as staging_name:
                staging = Path(staging_name)
                (staging / "evidence").symlink_to(
                    run_dir / "evidence",
                    target_is_directory=True,
                )
                lr_candidates = run_dir / "lr_candidates.json"
                if lr_candidates.exists():
                    (staging / "lr_candidates.json").symlink_to(lr_candidates)
                markdown, _ = render_hybrid_report(str(staging), disease, canonical)
                for name in _HYBRID_ARTIFACTS:
                    if not (staging / name).is_file():
                        raise ValueError(f"hybrid renderer did not create {name}")
                _clear_hybrid_artifacts(run_dir)
                for name in _HYBRID_ARTIFACTS:
                    (staging / name).replace(run_dir / name)

            return json.dumps(
                {
                    "saved": True,
                    "artifacts": {
                        name: str(run_dir / name) for name in _HYBRID_ARTIFACTS
                    },
                    "payload_sha256": hashlib.sha256(
                        json.dumps(
                            canonical,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest(),
                    "markdown_sha256": hashlib.sha256(
                        markdown.encode("utf-8")
                    ).hexdigest(),
                },
                ensure_ascii=False,
            )
        except Exception as exc:
            _clear_hybrid_artifacts(run_dir)
            return json.dumps({"saved": False, "errors": [str(exc)]})

    return StructuredTool.from_function(
        func=save_report_sections_for_run,
        name="save_report_sections",
        description="Validate canonical report sections and render the guarded report.",
    )


def production_skill_reader_tool(
    skills_dir: str | Path,
    allowed_skill_names: Collection[str],
) -> StructuredTool:
    """Read only files canonically contained by one listed skill directory."""

    root = Path(skills_dir).expanduser().resolve()
    allowed = frozenset(allowed_skill_names)

    def read_skill_file_for_run(skill_path: str, offset: int = 0, limit: int = 2000) -> str:
        requested = Path(skill_path)
        if requested.is_absolute():
            candidate = requested.resolve()
        else:
            relative = Path(skill_path)
            if relative.parts[:1] == ("skills",):
                relative = Path(*relative.parts[1:])
            candidate = (root / relative).resolve()
        permitted = any(
            candidate.is_relative_to((root / name).resolve()) for name in allowed
        )
        if not permitted:
            return f"Error: Skill file '{skill_path}' is not in the allowed skills"
        try:
            lines = candidate.read_text(encoding="utf-8").splitlines()
        except OSError:
            return f"Error: Skill file '{skill_path}' not found"
        start = max(0, int(offset))
        count = max(0, min(int(limit), 2000))
        return "\n".join(
            f"{line_no:>6}\t{line}"
            for line_no, line in enumerate(lines[start : start + count], start=start + 1)
        )

    return StructuredTool.from_function(
        func=read_skill_file_for_run,
        name="read_skill_file",
        description="Read a bounded file from an allow-listed production skill only.",
    )

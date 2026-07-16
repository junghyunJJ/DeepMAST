"""Bounded validation, repair, and fail-closed publication for ``drug.md``."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from langchain.agents import create_agent

from src.agents.model import create_llm
from src.agents.drug_target.deterministic_report import (
    build_report_data,
    validate_report_data,
)
from src.agents.drug_target.part4_candidate_selector import (
    PART4_CANDIDATE_SELECTION_SCHEMA_VERSION,
    generate_part4_candidate_selection,
    part4_candidate_selector_provider_from_config,
)
from src.agents.drug_target.production_report_tools import (
    production_hypothesis_evidence_tool,
    production_save_drug_md_tool,
)
from src.agents.drug_target.subagents.prompts import REPORT_WRITER_PROMPT
from src.agents.drug_target.therapeutic_synthesis import (
    PART4_SYNTHESIS_SCHEMA_VERSION,
    build_part4_therapeutic_synthesis,
    render_part4_therapeutic_synthesis_markdown,
)
from src.agents.drug_target.tools import validate_drug_report_finalization
from src.agents.drug_target.tools.drug_report_html import (
    build_drug_html_context,
    parse_drug_md,
    render_drug_html,
)


MAX_DRUG_REPORT_REPAIR_PASSES = 3
PUBLICATION_ARTIFACTS = (
    "part4_candidate_selection.json",
    "part4_therapeutic_synthesis.md",
    "drug_report.html",
)
GUARDRAIL_AUDIT_ARTIFACTS = (
    "drug_report_validation_initial.json",
    "drug_report_validation_final.json",
)
_MAX_STORED_ERROR_CHARS = 500


def _resolve_safe_run_dir(data_dir: str | Path) -> Path:
    """Resolve only an existing per-run directory; never fall back to env/CWD."""

    path = Path(data_dir).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise ValueError("data_dir must be an existing run directory")
    if path == Path(path.anchor):
        raise ValueError("data_dir must not be the filesystem root run directory")
    if (path / ".git").exists():
        raise ValueError("data_dir must not be a repository run directory")
    return path


def _artifact_paths(
    data_dir: Path,
    names: tuple[str, ...],
) -> tuple[Path, ...]:
    paths: list[Path] = []
    for name in names:
        path = data_dir / name
        paths.extend((path, path.with_suffix(f"{path.suffix}.tmp")))
    return tuple(paths)


def clear_derived_report_artifacts(
    data_dir: str | Path,
    *,
    include_audits: bool = False,
    include_sources: bool = False,
) -> None:
    """Remove only derived outputs after validating the run-directory boundary."""

    run_dir = _resolve_safe_run_dir(data_dir)
    names: list[str] = list(PUBLICATION_ARTIFACTS)
    if include_audits:
        names.extend(GUARDRAIL_AUDIT_ARTIFACTS)
    if include_sources:
        names.extend(("drug.md", "target_assessment.json"))
    for path in _artifact_paths(run_dir, tuple(names)):
        if path.exists():
            path.unlink()


def _validate(data_dir: Path) -> dict[str, Any]:
    tool = getattr(validate_drug_report_finalization, "func", None)
    if callable(tool):
        result = tool(data_dir=str(data_dir), publication_mode="agent_markdown")
    else:
        result = validate_drug_report_finalization.invoke(
            {"data_dir": str(data_dir), "publication_mode": "agent_markdown"}
        )
    if isinstance(result, str):
        parsed = json.loads(result)
    else:
        parsed = result
    if not isinstance(parsed, dict):
        raise TypeError("validate_drug_report_finalization returned a non-object payload")
    return parsed


def _hard_issues(validation: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        issue
        for issue in validation.get("issues", [])
        if isinstance(issue, dict) and str(issue.get("severity", "")).lower() != "warning"
    ]


def _nonrepairable_check_failure(validation: Mapping[str, Any]) -> bool:
    checks = validation.get("checks")
    checks = checks if isinstance(checks, Mapping) else {}
    for name in ("data_dir", "required_artifacts", "target_assessment"):
        check = checks.get(name)
        if isinstance(check, Mapping) and check.get("status") == "fail":
            return True
    drug_check = checks.get("validate_drug_md")
    raw = drug_check.get("raw") if isinstance(drug_check, Mapping) else None
    return isinstance(raw, Mapping) and bool(str(raw.get("error") or "").strip())


def _bounded_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text[:_MAX_STORED_ERROR_CHARS]


def _audit_payload(
    validation: Mapping[str, Any],
    *,
    status: str,
    repair_attempt_count: int,
    changed_repair_count: int,
    publication_status: str,
    repair_error: str | None = None,
    publication_error: str | None = None,
) -> dict[str, Any]:
    payload = copy.deepcopy(dict(validation))
    payload["guardrail"] = {
        "status": status,
        "repair_attempt_count": repair_attempt_count,
        "changed_repair_count": changed_repair_count,
        "max_repair_passes": MAX_DRUG_REPORT_REPAIR_PASSES,
        **({"repair_error": repair_error} if repair_error else {}),
    }
    payload["publication"] = {
        "status": publication_status,
        **({"error": publication_error} if publication_error else {}),
    }
    return payload


def _write_audit(
    data_dir: str | Path,
    name: str,
    validation: Mapping[str, Any],
    **metadata: Any,
) -> None:
    run_dir = _resolve_safe_run_dir(data_dir)
    path = run_dir / name
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    payload = _audit_payload(validation, **metadata)
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def _repair_drug_md(
    data_dir: Path,
    issues: list[dict[str, Any]],
    *,
    provider: str | None,
    disease: str,
) -> bool:
    """Ask the repair-only agent once, then report whether Markdown changed."""

    current_path = data_dir / "drug.md"
    current_markdown = current_path.read_text(encoding="utf-8")
    before = _sha256(current_path)
    repair_prompt = f"""## REPAIR MODE

Repair the existing drug.md in place. Fix only the listed validation issues.
Do not rebuild evidence, target_assessment.json, Part 4, or HTML.
Call save_drug_md exactly once with strip_unexpanded_markers=False after the repair.

Data directory: {json.dumps(str(data_dir), ensure_ascii=False)}
Disease: {json.dumps(disease or "unspecified", ensure_ascii=False)}

Validation issues:
{json.dumps(issues, ensure_ascii=False, indent=2)}

Current drug.md:
{current_markdown}
"""
    from src.agents.drug_target.middleware import DrugTargetManagedFilesystemGuardMiddleware

    agent = create_agent(
        model=create_llm(provider=provider),
        tools=[
            production_hypothesis_evidence_tool(data_dir),
            production_save_drug_md_tool(data_dir),
        ],
        system_prompt=REPORT_WRITER_PROMPT,
        middleware=[
            DrugTargetManagedFilesystemGuardMiddleware(
                data_dir,
                data_dir_tool_names={"load_evidence_files", "save_drug_md"},
            )
        ],
    )
    agent.invoke({"messages": [{"role": "user", "content": repair_prompt}]})
    return _sha256(current_path) != before


def _required_text(value: object, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Section 4 hypothesis is missing {field}")
    return text


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _hypothesis_payload_from_markdown(markdown: str) -> dict[str, Any]:
    context = parse_drug_md(markdown)
    parsed = context.get("hypothesis")
    if not isinstance(parsed, list) or not parsed:
        raise ValueError("Section 4 has no parseable hypotheses")

    hypotheses: list[dict[str, Any]] = []
    for index, value in enumerate(parsed, start=1):
        if not isinstance(value, Mapping):
            raise ValueError("Section 4 contains a malformed hypothesis")
        genes = _string_list(value.get("genes"))
        if not genes:
            raise ValueError("Section 4 hypothesis is missing at least one gene")
        hypotheses.append(
            {
                "rank": value.get("rank", index),
                "title": _required_text(value.get("title"), "title"),
                "category": _required_text(value.get("category"), "category"),
                "core_claim": _required_text(value.get("core_claim"), "core claim"),
                "biological_entities": {
                    "genes": genes,
                    "pathways": _string_list(value.get("pathways")),
                    "cell_types": _string_list(value.get("cell_types")),
                    "drugs": _string_list(value.get("drugs")),
                },
                "falsifiable_prediction": _required_text(
                    value.get("falsifiable_prediction"), "falsifiable prediction"
                ),
                "validation_approach": _required_text(
                    value.get("validation_approach"), "validation approach"
                ),
                "evidence_references": ["drug.md"],
            }
        )
    return {"hypotheses": hypotheses}


def _selected_genes(synthesis: Mapping[str, Any]) -> list[str]:
    candidates = synthesis.get("featured_candidates")
    if not isinstance(candidates, list):
        return []
    return [
        str(candidate.get("gene") or "").strip()
        for candidate in candidates
        if isinstance(candidate, Mapping) and str(candidate.get("gene") or "").strip()
    ]


async def _publish_report_outputs(
    data_dir: str | Path,
    *,
    disease: str,
    provider: str | None = None,
) -> dict[str, Any]:
    """Publish all derived files atomically after all in-memory checks pass."""

    run_dir = _resolve_safe_run_dir(data_dir)
    temporary_paths: list[Path] = []
    try:
        payload = _hypothesis_payload_from_markdown(
            (run_dir / "drug.md").read_text(encoding="utf-8")
        )
        report_data = build_report_data(
            str(run_dir),
            disease,
            hypothesis_data=payload,
        )
        issues = validate_report_data(report_data)
        if issues:
            raise ValueError("deterministic report data failed validation")

        validation = {"valid": True, "issues": []}
        deterministic_synthesis = build_part4_therapeutic_synthesis(
            report_data,
            validation=validation,
        )
        selector_config: dict[str, Any] = (
            {"configurable": {"llm_provider": provider}} if provider else {}
        )
        selector_provider = part4_candidate_selector_provider_from_config(selector_config)
        selection = await generate_part4_candidate_selection(
            report_data,
            deterministic_selected_genes=_selected_genes(deterministic_synthesis),
            provider=selector_provider,
            data_dir=run_dir,
            config=selector_config,
        )
        if (
            not isinstance(selection, Mapping)
            or selection.get("schema_version") != PART4_CANDIDATE_SELECTION_SCHEMA_VERSION
            or not isinstance(selection.get("selected_genes"), list)
        ):
            raise ValueError("Part 4 candidate selection payload is invalid")

        synthesis = build_part4_therapeutic_synthesis(
            report_data,
            validation=validation,
            candidate_selection_payload=selection,
        )
        if synthesis.get("schema_version") != PART4_SYNTHESIS_SCHEMA_VERSION:
            raise ValueError("Part 4 therapeutic synthesis schema is invalid")
        part4_markdown = render_part4_therapeutic_synthesis_markdown(synthesis)
        if not part4_markdown.strip():
            raise ValueError("Part 4 therapeutic synthesis Markdown is blank")

        html_context = build_drug_html_context(
            str(run_dir),
            allow_legacy_hypothesis_fallback=False,
        )
        html = render_drug_html(html_context)
        if not html.strip() or "<html" not in html.lower():
            raise ValueError("drug report HTML is blank or not an HTML document")

        rendered = {
            "part4_candidate_selection.json": json.dumps(
                dict(selection), indent=2, ensure_ascii=False
            )
            + "\n",
            "part4_therapeutic_synthesis.md": part4_markdown,
            "drug_report.html": html,
        }
        for name, content in rendered.items():
            path = run_dir / name
            temporary = path.with_suffix(f"{path.suffix}.tmp")
            temporary.write_text(content, encoding="utf-8")
            temporary_paths.append(temporary)

        json.loads((run_dir / "part4_candidate_selection.json.tmp").read_text(encoding="utf-8"))
        if any(not path.exists() or path.stat().st_size == 0 for path in temporary_paths):
            raise ValueError("publication temporary artifact is empty")
        for temporary in temporary_paths:
            final = temporary.with_suffix("")
            temporary.replace(final)
        return {"status": "published", "artifact_count": len(PUBLICATION_ARTIFACTS)}
    except Exception:
        for path in temporary_paths:
            if path.exists():
                path.unlink()
        clear_derived_report_artifacts(run_dir)
        raise


def _result(
    *,
    status: str,
    initial: Mapping[str, Any],
    final: Mapping[str, Any],
    repair_attempt_count: int,
    changed_repair_count: int,
    publication_status: str,
    repair_error: str | None = None,
    publication_error: str | None = None,
) -> dict[str, Any]:
    hard = _hard_issues(final)
    return {
        "status": status,
        "initial_issue_count": len(initial.get("issues", [])),
        "initial_error_count": len(_hard_issues(initial)),
        "repair_attempt_count": repair_attempt_count,
        "changed_repair_count": changed_repair_count,
        "final_issue_count": len(final.get("issues", [])),
        "final_error_count": len(hard),
        "publication_status": publication_status,
        **({"repair_error": repair_error} if repair_error else {}),
        **({"publication_error": publication_error} if publication_error else {}),
    }


def _write_final_failure(
    data_dir: Path,
    initial: Mapping[str, Any],
    final: Mapping[str, Any],
    *,
    repair_attempt_count: int,
    changed_repair_count: int,
    repair_error: str | None = None,
    publication_error: str | None = None,
) -> dict[str, Any]:
    clear_derived_report_artifacts(data_dir)
    _write_audit(
        data_dir,
        "drug_report_validation_final.json",
        final,
        status="failed",
        repair_attempt_count=repair_attempt_count,
        changed_repair_count=changed_repair_count,
        publication_status="failed",
        repair_error=repair_error,
        publication_error=publication_error,
    )
    return _result(
        status="failed",
        initial=initial,
        final=final,
        repair_attempt_count=repair_attempt_count,
        changed_repair_count=changed_repair_count,
        publication_status="failed",
        repair_error=repair_error,
        publication_error=publication_error,
    )


def run_drug_report_guardrail(
    data_dir: str | Path,
    *,
    provider: str | None = None,
    disease: str = "",
) -> dict[str, Any]:
    """Validate, repair no more than three times, then publish as one transaction."""

    run_dir = _resolve_safe_run_dir(data_dir)
    clear_derived_report_artifacts(run_dir, include_audits=True)
    initial = _validate(run_dir)
    _write_audit(
        run_dir,
        "drug_report_validation_initial.json",
        initial,
        status="pending",
        repair_attempt_count=0,
        changed_repair_count=0,
        publication_status="pending",
    )

    final = initial
    attempts = 0
    changes = 0
    if _nonrepairable_check_failure(final):
        return _write_final_failure(
            run_dir,
            initial,
            final,
            repair_attempt_count=attempts,
            changed_repair_count=changes,
        )

    while _hard_issues(final) and attempts < MAX_DRUG_REPORT_REPAIR_PASSES:
        try:
            changed = _repair_drug_md(
                run_dir,
                _hard_issues(final),
                provider=provider,
                disease=disease,
            )
            attempts += 1
        except Exception as exc:  # noqa: BLE001 - audit the provider boundary
            attempts += 1
            return _write_final_failure(
                run_dir,
                initial,
                final,
                repair_attempt_count=attempts,
                changed_repair_count=changes,
                repair_error=_bounded_error(exc),
            )
        if changed:
            changes += 1
        final = _validate(run_dir)
        if _nonrepairable_check_failure(final):
            return _write_final_failure(
                run_dir,
                initial,
                final,
                repair_attempt_count=attempts,
                changed_repair_count=changes,
            )
        if not changed:
            break

    if _hard_issues(final):
        return _write_final_failure(
            run_dir,
            initial,
            final,
            repair_attempt_count=attempts,
            changed_repair_count=changes,
        )

    try:
        asyncio.run(_publish_report_outputs(run_dir, disease=disease, provider=provider))
        if any(
            not (run_dir / name).exists() or (run_dir / name).stat().st_size == 0
            for name in PUBLICATION_ARTIFACTS
        ):
            raise RuntimeError("publication did not produce every required artifact")
    except Exception as exc:  # noqa: BLE001 - retain source/audit diagnostics
        return _write_final_failure(
            run_dir,
            initial,
            final,
            repair_attempt_count=attempts,
            changed_repair_count=changes,
            publication_error=_bounded_error(exc),
        )
    try:
        _write_audit(
            run_dir,
            "drug_report_validation_final.json",
            final,
            status="passed",
            repair_attempt_count=attempts,
            changed_repair_count=changes,
            publication_status="passed",
        )
    except Exception as audit_error:
        final_audit_tmp = (run_dir / "drug_report_validation_final.json").with_suffix(
            ".json.tmp"
        )
        try:
            if final_audit_tmp.exists():
                final_audit_tmp.unlink()
        except Exception as temp_cleanup_error:
            audit_error.add_note(
                f"Failed to remove final audit temporary file: {temp_cleanup_error}"
            )
        finally:
            clear_derived_report_artifacts(run_dir)
        raise
    return _result(
        status="passed",
        initial=initial,
        final=final,
        repair_attempt_count=attempts,
        changed_repair_count=changes,
        publication_status="passed",
    )

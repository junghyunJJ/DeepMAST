"""Summarizer CompiledSubAgent for audited drug target report finalization."""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import BackendFactory, BackendProtocol
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from src.agents.drug_target.subagents.summarizer.fs_backend import (
    LoggingAndFallbackFilesystemBackend,
)

_lifecycle_logger = logging.getLogger("drug_target.lifecycle")


def _emit_lifecycle(phase: str, data_dir: str) -> None:
    """Emit one structured lifecycle event (CP-P1-003 compliant)."""
    _lifecycle_logger.info(
        json.dumps(
            {
                "event": "critic_slice_lifecycle",
                "phase": phase,
                "data_dir": data_dir,
                "timestamp": time.time(),
            }
        )
    )

from src.agents.drug_target.subagents.prompts import CRITIC_PROMPT, REPORT_WRITER_PROMPT
from src.agents.drug_target.tools import (
    build_evidence_summary,
    render_drug_md_from_expansions,
    validate_drug_md,
    validate_drug_report_finalization,
)


def _build_disk_backend(data_dir: str) -> FilesystemBackend:
    """Build a LoggingAndFallbackFilesystemBackend rooted at data_dir with virtual path mode.

    Virtual mode ensures that built-in filesystem tools (ls, read_file, glob)
    resolve paths like /evidence/pair_001.json to data_dir/evidence/pair_001.json
    on real disk rather than against an in-memory StateBackend.

    Returns a ``LoggingAndFallbackFilesystemBackend`` (subclass of
    ``FilesystemBackend``) so every ls/glob call is logged as structured JSON
    for observability (T3).
    """
    return LoggingAndFallbackFilesystemBackend(root_dir=data_dir, virtual_mode=True)


def _invoke_tool_json(tool: Any, **kwargs: Any) -> dict[str, Any]:
    """Invoke a LangChain tool or plain callable and parse its JSON result."""
    func = getattr(tool, "func", None)
    if callable(func):
        raw = func(**kwargs)
    elif hasattr(tool, "invoke"):
        raw = tool.invoke(kwargs)
    else:
        raw = tool(**kwargs)
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return {"raw": raw}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return parsed if isinstance(parsed, dict) else {"raw": parsed}


def _copy_if_exists(src: Path, dst: Path) -> None:
    if src.exists():
        shutil.copyfile(src, dst)


def _unlink_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _message_content(value: Any) -> str:
    if hasattr(value, "content"):
        return str(value.content)
    if isinstance(value, dict) and "content" in value:
        return str(value["content"])
    return str(value)


def _last_message_content(result: Any) -> str:
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list) and messages:
            return _message_content(messages[-1])
        if "content" in result:
            return str(result["content"])
    return _message_content(result)


def _message_contents(result: Any) -> list[str]:
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list) and messages:
            return [_message_content(message) for message in messages]
        if "content" in result:
            return [str(result["content"])]
    return [_message_content(result)]


def _json_objects_from_text(text: str) -> list[dict[str, Any]]:
    chunks = [match.group(1) for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)]
    chunks.append(text)
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    for chunk in chunks:
        cursor = 0
        while cursor < len(chunk):
            start = chunk.find("{", cursor)
            if start == -1:
                break
            try:
                parsed, offset = decoder.raw_decode(chunk[start:])
            except json.JSONDecodeError:
                cursor = start + 1
                continue
            if isinstance(parsed, dict):
                objects.append(parsed)
            cursor = start + max(offset, 1)
    return objects


def _coerce_report_expansions(candidate: dict[str, Any]) -> dict[str, Any] | None:
    if candidate.get("schema_version") == "report_expansions.v1":
        return candidate
    if candidate.get("report_expansions_version") == "v1":
        return candidate
    if isinstance(candidate.get("slots"), list):
        return candidate
    if isinstance(candidate.get("expansions"), list):
        return candidate
    if isinstance(candidate.get("expansions"), dict):
        return candidate
    if isinstance(candidate.get("report_expansions"), list):
        return candidate
    if isinstance(candidate.get("report_expansions"), dict):
        return candidate
    for wrapper_key in ("expansions", "report_expansions"):
        wrapped = candidate.get(wrapper_key)
        if isinstance(wrapped, dict):
            return _coerce_report_expansions(wrapped)
    return None


def _extract_report_expansions(result: Any) -> dict[str, Any] | None:
    for content in reversed(_message_contents(result)):
        for candidate in _json_objects_from_text(content):
            expansions = _coerce_report_expansions(candidate)
            if expansions is not None:
                return expansions
    return None


def _writer_slots(expansions: dict[str, Any]) -> list[dict[str, Any]] | None:
    slots = expansions.get("slots")
    if not isinstance(slots, list):
        for alias in ("expansions", "report_expansions"):
            alias_value = expansions.get(alias)
            if isinstance(alias_value, list):
                slots = alias_value
                break
    if not isinstance(slots, list):
        return None
    normalized: list[dict[str, Any]] = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        slot_copy = dict(slot)
        if "sentences" not in slot_copy and isinstance(slot_copy.get("expansions"), list):
            slot_copy["sentences"] = slot_copy["expansions"]
        normalized.append(slot_copy)
    return normalized


def _writer_expansion_contract_errors(base: Path, expansions: dict[str, Any]) -> list[dict[str, str]]:
    ref_path = base / "drug_report_reference_card.json"
    if not ref_path.exists():
        return []
    try:
        reference_card = json.loads(ref_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    required_slots = [
        str(slot.get("slot_id"))
        for slot in reference_card.get("expansion_slots", [])
        if isinstance(slot, dict) and slot.get("slot_id")
    ]
    if not required_slots:
        return []
    slots = _writer_slots(expansions)
    if slots is None:
        return [{
            "code": "WRITER_EXPANSIONS_JSON_INVALID",
            "message": "writer report_expansions.v1 JSON must include slots as a list",
        }]
    if not slots:
        return [{
            "code": "WRITER_EXPANSIONS_JSON_EMPTY",
            "message": "writer report_expansions.v1 JSON must include every required slot",
        }]
    by_id = {
        str(slot.get("slot_id")): slot
        for slot in slots
        if slot.get("slot_id")
    }
    errors: list[dict[str, str]] = []
    for slot_id in required_slots:
        slot = by_id.get(slot_id)
        if slot is None:
            errors.append({
                "code": "WRITER_EXPANSIONS_JSON_MISSING_SLOT",
                "message": f"writer report_expansions.v1 JSON missing required slot_id: {slot_id}",
            })
            continue
        sentences = slot.get("sentences")
        if not isinstance(sentences, list) or not sentences:
            errors.append({
                "code": "WRITER_EXPANSIONS_JSON_EMPTY_SLOT",
                "message": f"writer slot_id {slot_id} must include at least one sentence",
            })
    return errors


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("critic output must be a JSON object")
    return parsed


def _virtualize_paths_for_instruction(value: Any, root: Path) -> Any:
    """Replace host absolute run paths with backend virtual-root paths."""
    root_text = str(root)
    root_prefix = root_text.rstrip("/") + "/"
    if isinstance(value, Path):
        return _virtualize_paths_for_instruction(str(value), root)
    if isinstance(value, str):
        if value == root_text:
            return "/"
        if value.startswith(root_prefix):
            return "/" + value[len(root_prefix) :]
        return value
    if isinstance(value, list):
        return [_virtualize_paths_for_instruction(item, root) for item in value]
    if isinstance(value, dict):
        return {
            key: _virtualize_paths_for_instruction(item, root)
            for key, item in value.items()
        }
    return value


def _critic_has_blockers(report: dict[str, Any]) -> bool:
    if report.get("passed") is not True:
        return True
    for finding in report.get("findings", []) or []:
        if isinstance(finding, dict) and finding.get("severity") in {"P0", "P1"}:
            return True
    for verdict in report.get("claim_verdicts", []) or []:
        if isinstance(verdict, dict) and verdict.get("verdict") == "FAIL":
            return True
    return False


_BLOCKING_VALIDATE_DRUG_MD_FINDINGS: frozenset[str] = frozenset(
    {
        "FABRICATED_DRUG_NAME",
        "FABRICATED_FILE_REFERENCE",
        "WRONG_APPROVAL_YEAR",
        "PRECLINICAL_CALLED_APPROVED",
        "UNSUPPORTED_CLINICAL_STATUS",
        "UNGROUNDED_MECHANISM",
        "UNANCHORED_SENTENCE",
        "SOURCE_PROVENANCE_MISSING",
        "SOURCE_PROVENANCE_MISMATCH",
    }
)

_RENDERER_SCOPED_PROSE_FINDINGS: frozenset[str] = frozenset(
    {
        "FABRICATED_DRUG_NAME",
        "UNGROUNDED_MECHANISM",
        "UNANCHORED_SENTENCE",
    }
)

_VALIDATOR_FINDING_TYPES: frozenset[str] = _BLOCKING_VALIDATE_DRUG_MD_FINDINGS.union(
    {
        "PRECLINICAL_CALLED_APPROVED",
        "UNCITED_QUANTITATIVE",
        "MISSING_DISEASE_SCOPE_NOTE",
    }
)


def _iter_dict_values(value: Any) -> list[dict[str, Any]]:
    dicts: list[dict[str, Any]] = []
    if isinstance(value, dict):
        dicts.append(value)
        for item in value.values():
            dicts.extend(_iter_dict_values(item))
    elif isinstance(value, list):
        for item in value:
            dicts.extend(_iter_dict_values(item))
    return dicts


def _validation_finding_types(validation: dict[str, Any]) -> set[str]:
    types: set[str] = set()
    for item in _iter_dict_values(validation):
        finding_type = item.get("type")
        if isinstance(finding_type, str):
            types.add(finding_type)
    return types


def _critic_claimed_validator_types(finding: dict[str, Any]) -> set[str]:
    text = json.dumps(finding, ensure_ascii=False)
    if "validate_drug_md" not in text and "validator" not in text.lower():
        return set()
    return {kind for kind in _VALIDATOR_FINDING_TYPES if kind in text}


def _critic_finding_contradicts_validation(
    finding: dict[str, Any], validation: dict[str, Any]
) -> bool:
    claimed = _critic_claimed_validator_types(finding)
    if not claimed:
        return False
    actual = _validation_finding_types(validation)
    return not claimed.intersection(actual)


def _critic_validation_contradictions(
    report: dict[str, Any], validation: dict[str, Any]
) -> list[dict[str, Any]]:
    findings = report.get("findings", []) or []
    if not isinstance(findings, list):
        return []
    contradictions: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict) or finding.get("severity") not in {"P0", "P1"}:
            continue
        if not _critic_finding_contradicts_validation(finding, validation):
            continue
        contradictions.append(
            {
                "severity": finding.get("severity"),
                "issue": finding.get("issue"),
                "claimed_validator_types": sorted(_critic_claimed_validator_types(finding)),
                "actual_validator_types": sorted(_validation_finding_types(validation)),
            }
        )
    return contradictions


def _severity_counts(findings: list[Any]) -> dict[str, int]:
    counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    for finding in findings:
        if isinstance(finding, dict) and finding.get("severity") in counts:
            counts[str(finding["severity"])] += 1
    return counts


def _mark_critic_contradiction_failure(
    report: dict[str, Any], contradictions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Preserve critic output but make validator-contradicting critic output blocking."""
    marked = dict(report)
    findings = list(marked.get("findings", []) or [])
    if not isinstance(findings, list):
        findings = []
    findings.append(
        {
            "severity": "P0",
            "issue": "critic output contradicted supplied validate_drug_md JSON",
            "evidence": contradictions,
            "repair": (
                "Return CriticOutput that only cites validator finding types present "
                "in the supplied validate_drug_md JSON."
            ),
        }
    )
    marked["findings"] = findings
    marked["severity_counts"] = _severity_counts(findings)
    marked["passed"] = False
    marked["host_critic_contradictions"] = contradictions
    return marked


def _validation_has_blockers(result: dict[str, Any], base: Path | None = None) -> bool:
    if result.get("valid") is not True or bool(result.get("issues")):
        return True
    renderer_expansion_texts: tuple[str, ...] = ()
    _finding_matches_renderer_expansion = None
    if base is not None:
        try:
            from src.agents.drug_target.tools.stage_logic import (  # noqa: PLC0415
                _finding_matches_renderer_expansion,
                _load_renderer_expansion_texts,
            )
            renderer_expansion_texts = _load_renderer_expansion_texts(base)
        except Exception:
            renderer_expansion_texts = ()
    for finding in result.get("findings", []) or []:
        if (
            isinstance(finding, dict)
            and finding.get("type") in _BLOCKING_VALIDATE_DRUG_MD_FINDINGS
        ):
            if (
                base is not None
                and finding.get("type") in _RENDERER_SCOPED_PROSE_FINDINGS
                and callable(_finding_matches_renderer_expansion)
                and not _finding_matches_renderer_expansion(finding, renderer_expansion_texts)
            ):
                continue
            return True
    return False


def _reference_card_guidance(base: Path) -> str:
    ref_path = base / "drug_report_reference_card.json"
    try:
        reference_card = json.loads(ref_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    from src.agents.drug_target.tools.report_expansion_schema import (  # noqa: PLC0415
        _fallback_provenance,
    )

    slots = reference_card.get("expansion_slots", [])
    provenance = reference_card.get("provenance_index", {})
    slot_lines = [
        (
            f"- {slot.get('slot_id')}: {slot.get('instruction', '')}"
            + (
                "; preferred_provenance="
                f"{preferred.get('source_file')}::{preferred.get('source_field')}"
                f" ({preferred.get('source_class')})"
                if isinstance((preferred := _fallback_provenance(reference_card, slot)), dict)
                else ""
            )
        )
        for slot in slots
        if isinstance(slot, dict)
    ]
    provenance_lines = []
    if isinstance(provenance, dict):
        for item in provenance.values():
            if not isinstance(item, dict):
                continue
            provenance_lines.append(
                "- "
                f"source_file={item.get('source_file')}; "
                f"source_field={item.get('source_field')}; "
                f"source_class={item.get('source_class')}"
            )
            if len(provenance_lines) >= 20:
                break
    return (
        "\nRequired expansion slots:\n"
        + "\n".join(slot_lines)
        + "\n\nAllowed source provenance entries (choose matching entries; use claim_type=\"interpretation\" for interpretive prose):\n"
        + "\n".join(provenance_lines)
    )


class DeterministicSummarizerRunnable(Runnable):
    """Host-controlled summarizer loop.

    The LLM writer only creates/repairs ``report_expansions.json``. This
    Runnable owns evidence summary construction, rendering, validation, critic
    persistence, bounded repair, and finalization.
    """

    def __init__(
        self,
        *,
        report_writer: Runnable,
        critic: Runnable,
        data_dir: str | None = None,
        max_repairs: int = 2,
    ) -> None:
        self.report_writer = report_writer
        self.critic = critic
        self.data_dir = data_dir
        self.max_repairs = max_repairs

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> dict[str, Any]:  # noqa: A002
        original = input if isinstance(input, dict) else {}
        state = dict(original)
        messages = list(state.get("messages", []))
        try:
            content = self._run(config=config)
        except Exception as exc:  # pragma: no cover - defensive fail-closed path
            content = (
                "SUMMARIZER_STATUS: FAIL\n"
                f"- Deterministic summarizer raised: {type(exc).__name__}: {exc}"
            )
        state["messages"] = messages + [AIMessage(content=content)]
        return state

    def _run(self, *, config: Any = None) -> str:
        if not self.data_dir:
            return (
                "SUMMARIZER_STATUS: FAIL\n"
                "- Deterministic summarizer requires data_dir."
            )
        base = Path(self.data_dir).expanduser().resolve()
        evidence_dir = base / "evidence"
        if not base.exists() or not evidence_dir.exists():
            return (
                "SUMMARIZER_STATUS: FAIL\n"
                f"- Missing data_dir or evidence directory: {base}"
            )

        from src.agents.drug_target.subagents.configs import (  # noqa: PLC0415
            cleanup_critic_slices,
            filter_hypothesis_evidence_files,
            write_critic_slices,
        )
        from src.agents.drug_target.tools.report_expansion_schema import (  # noqa: PLC0415
            validate_report_expansions,
        )

        filter_hypothesis_evidence_files(str(base))
        summary = _invoke_tool_json(build_evidence_summary, data_dir=str(base))
        if summary.get("error"):
            return (
                "SUMMARIZER_STATUS: FAIL\n"
                f"- build_evidence_summary failed: {summary['error']}"
            )

        expansions_path = base / "report_expansions.json"
        _unlink_if_exists(expansions_path)
        _unlink_if_exists(base / "drug_report_render.json")

        writer_result = self._invoke_child(
            self.report_writer,
            self._initial_writer_instruction(base),
            config=config,
        )
        writer_persist = self._persist_writer_expansions(
            base,
            writer_result,
            allow_writer_saved_file=True,
        )
        if writer_persist.get("saved") is not True:
            writer_result = self._invoke_child(
                self.report_writer,
                self._initial_writer_retry_instruction(
                    base,
                    writer_persist=writer_persist,
                    writer_result=writer_result,
                ),
                config=config,
            )
            writer_persist = self._persist_writer_expansions(
                base,
                writer_result,
                allow_writer_saved_file=True,
            )
        if writer_persist.get("saved") is not True:
            _unlink_if_exists(expansions_path)
            return (
                "SUMMARIZER_STATUS: FAIL\n"
                "- report_writer did not create report_expansions.json.\n"
                f"- host_persist_result: {json.dumps(writer_persist, ensure_ascii=False)[:3000]}\n"
                f"- writer_result: {_last_message_content(writer_result)[:3000]}"
            )

        expansions = json.loads(expansions_path.read_text(encoding="utf-8"))
        _, expansion_errors = validate_report_expansions(base, expansions)
        if expansion_errors:
            return (
                "SUMMARIZER_STATUS: FAIL\n"
                "- report_expansions.json failed schema validation before render.\n"
                f"- errors: {json.dumps(expansion_errors[:5], ensure_ascii=False)}"
            )
        _copy_if_exists(expansions_path, base / "report_expansions.initial.json")

        render_result = self._render_and_snapshot(base, "initial")
        validation = _invoke_tool_json(validate_drug_md, data_dir=base)
        critic_report = self._run_critic(
            base,
            validation=validation,
            render_result=render_result,
            label="initial",
            config=config,
            write_critic_slices=write_critic_slices,
            cleanup_critic_slices=cleanup_critic_slices,
        )

        for repair_index in range(1, self.max_repairs + 1):
            if not _validation_has_blockers(validation, base) and not _critic_has_blockers(critic_report):
                break
            if not _validation_has_blockers(validation, base) and _critic_has_blockers(critic_report):
                finalization_without_critic = _invoke_tool_json(
                    validate_drug_report_finalization,
                    data_dir=str(base),
                    require_critic=False,
                )
                if finalization_without_critic.get("valid") is True:
                    critic_report = self._run_critic(
                        base,
                        validation=validation,
                        render_result=render_result,
                        label=f"critic_recheck_{repair_index}",
                        config=config,
                        write_critic_slices=write_critic_slices,
                        cleanup_critic_slices=cleanup_critic_slices,
                        critic_context=(
                            "critic_recheck_context: Host validate_drug_md and "
                            "finalization without critic both passed. Keep P0/P1 "
                            "only for concrete factual contradictions you can cite "
                            "from the current files; otherwise downgrade advisory "
                            "concerns to P2/P3 and set passed=true.\n"
                            f"previous_critic_report: {json.dumps(critic_report, ensure_ascii=False)}\n"
                            f"finalization_without_critic: {json.dumps(finalization_without_critic, ensure_ascii=False)}\n"
                        ),
                    )
                    if not _critic_has_blockers(critic_report):
                        break
            previous_expansions_text = (
                expansions_path.read_text(encoding="utf-8")
                if expansions_path.exists()
                else None
            )
            _unlink_if_exists(expansions_path)
            repair_result = self._invoke_child(
                self.report_writer,
                self._repair_writer_instruction(
                    base,
                    validation=validation,
                    critic_report=critic_report,
                    repair_index=repair_index,
                ),
                config=config,
            )
            repair_persist = self._persist_writer_expansions(
                base,
                repair_result,
                allow_writer_saved_file=True,
            )
            if repair_persist.get("saved") is not True:
                if previous_expansions_text is not None:
                    expansions_path.write_text(previous_expansions_text, encoding="utf-8")
                critic_report = {
                    "passed": False,
                    "findings": [
                        {
                            "severity": "P0",
                            "issue": "report_writer did not return valid report_expansions.json during repair",
                            "evidence": json.dumps(repair_persist, ensure_ascii=False),
                            "repair": "Return a complete report_expansions.v1 JSON object with every required slot.",
                        }
                    ],
                    "claim_verdicts": [],
                    "repair_instructions": [],
                }
                (evidence_dir / "critic_report.json").write_text(
                    json.dumps(critic_report, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                break
            if not expansions_path.exists():
                break
            expansions = json.loads(expansions_path.read_text(encoding="utf-8"))
            _, expansion_errors = validate_report_expansions(base, expansions)
            if expansion_errors:
                critic_report = {
                    "passed": False,
                    "findings": [
                        {
                            "severity": "P0",
                            "issue": "report_expansions.json failed validation after repair",
                            "evidence": json.dumps(expansion_errors[:5], ensure_ascii=False),
                            "repair": "Repair report_expansions.json only.",
                        }
                    ],
                    "claim_verdicts": [],
                    "repair_instructions": [],
                }
                (evidence_dir / "critic_report.json").write_text(
                    json.dumps(critic_report, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                continue
            _copy_if_exists(expansions_path, base / f"report_expansions.repair_{repair_index}.json")
            render_result = self._render_and_snapshot(base, f"repair_{repair_index}")
            validation = _invoke_tool_json(validate_drug_md, data_dir=base)
            critic_report = self._run_critic(
                base,
                validation=validation,
                render_result=render_result,
                label=f"repair_{repair_index}",
                config=config,
                write_critic_slices=write_critic_slices,
                cleanup_critic_slices=cleanup_critic_slices,
            )

        finalization = _invoke_tool_json(
            validate_drug_report_finalization,
            data_dir=str(base),
            require_critic=True,
        )
        if finalization.get("valid") is True:
            return (
                "SUMMARIZER_STATUS: PASS\n"
                "- finalization valid=true\n"
                f"- issue_count={finalization.get('issue_count', 0)}\n"
                "- critic_report.json passed required critic gate"
            )
        return (
            "SUMMARIZER_STATUS: FAIL\n"
            "- Finalization failed; drug.md remains a draft.\n"
            f"- issues: {json.dumps(finalization.get('issues', []), ensure_ascii=False)}"
        )

    def _invoke_child(self, child: Runnable, instruction: str, *, config: Any = None) -> Any:
        payload = {"messages": [HumanMessage(content=instruction)]}
        if config is not None:
            return child.invoke(payload, config)
        return child.invoke(payload)

    def _persist_writer_expansions(
        self,
        base: Path,
        writer_result: Any,
        *,
        allow_writer_saved_file: bool = False,
    ) -> dict[str, Any]:
        expansions = _extract_report_expansions(writer_result)
        loaded_writer_saved_file = False
        exp_path = base / "report_expansions.json"
        if expansions is None:
            if allow_writer_saved_file and exp_path.exists():
                try:
                    expansions = json.loads(exp_path.read_text(encoding="utf-8"))
                    loaded_writer_saved_file = True
                except Exception as exc:
                    _unlink_if_exists(exp_path)
                    return {
                        "saved": False,
                        "path": str(exp_path),
                        "errors": [
                            {
                                "code": "WRITER_EXPANSIONS_JSON_INVALID",
                                "message": f"writer-saved report_expansions.json is not parseable: {exc}",
                            }
                        ],
                        "host_persisted_from_writer_json": False,
                    }
            else:
                _unlink_if_exists(exp_path)
                return {
                    "saved": False,
                    "path": str(exp_path),
                    "errors": [
                        {
                            "code": "WRITER_EXPANSIONS_JSON_MISSING",
                            "message": "writer did not return or save a report_expansions.v1 JSON object",
                        }
                    ],
                    "host_persisted_from_writer_json": False,
                }
        contract_errors = _writer_expansion_contract_errors(base, expansions)
        if contract_errors and allow_writer_saved_file and exp_path.exists():
            try:
                saved_expansions = json.loads(exp_path.read_text(encoding="utf-8"))
            except Exception as exc:
                _unlink_if_exists(exp_path)
                return {
                    "saved": False,
                    "path": str(exp_path),
                    "errors": [
                        {
                            "code": "WRITER_EXPANSIONS_JSON_INVALID",
                            "message": f"writer-saved report_expansions.json is not parseable: {exc}",
                        }
                    ],
                    "host_persisted_from_writer_json": False,
                }
            saved_contract_errors = _writer_expansion_contract_errors(base, saved_expansions)
            if not saved_contract_errors:
                expansions = saved_expansions
                loaded_writer_saved_file = True
                contract_errors = []
            else:
                contract_errors = saved_contract_errors
        if contract_errors:
            _unlink_if_exists(exp_path)
            return {
                "saved": False,
                "path": str(exp_path),
                "errors": contract_errors,
                "host_persisted_from_writer_json": False,
            }

        from src.agents.drug_target.tools.report_expansion_schema import (  # noqa: PLC0415
            save_report_expansions,
        )

        result = _invoke_tool_json(
            save_report_expansions,
            data_dir=str(base),
            expansions=expansions,
        )
        result["host_persisted_from_writer_json"] = result.get("saved") is True
        if loaded_writer_saved_file:
            result["host_loaded_writer_saved_file"] = True
        return result

    def _render_and_snapshot(self, base: Path, label: str) -> dict[str, Any]:
        result = _invoke_tool_json(render_drug_md_from_expansions, data_dir=str(base))
        _copy_if_exists(base / "drug_report_render.json", base / f"drug_report_render.{label}.json")
        _copy_if_exists(base / "drug.md", base / f"drug.{label}.md")
        return result

    def _run_critic(
        self,
        base: Path,
        *,
        validation: dict[str, Any],
        render_result: dict[str, Any],
        label: str,
        config: Any,
        write_critic_slices: Any,
        cleanup_critic_slices: Any,
        critic_context: str = "",
    ) -> dict[str, Any]:
        evidence_dir = base / "evidence"
        write_critic_slices(str(base))
        try:
            result = self._invoke_child(
                self.critic,
                self._critic_instruction(
                    base,
                    validation=validation,
                    render_result=render_result,
                    label=label,
                    critic_context=critic_context,
                ),
                config=config,
            )
        finally:
            cleanup_critic_slices(str(base))

        try:
            report = _parse_json_object(_last_message_content(result))
        except Exception as exc:
            report = {
                "passed": False,
                "severity_counts": {"P0": 1, "P1": 0, "P2": 0, "P3": 0},
                "checked_gates": ["critic_output_parse"],
                "findings": [
                    {
                        "severity": "P0",
                        "issue": "critic output was not parseable CriticOutput JSON",
                        "evidence": str(exc),
                        "repair": "Return JSON conforming to CriticOutput.",
                    }
                ],
                "repair_instructions": [],
                "claim_verdicts": [],
            }
        contradictions = _critic_validation_contradictions(report, validation)
        if contradictions:
            retry_result = self._invoke_child(
                self.critic,
                self._critic_retry_instruction(
                    base,
                    validation=validation,
                    render_result=render_result,
                    label=label,
                    previous_report=report,
                    contradictions=contradictions,
                ),
                config=config,
            )
            try:
                retry_report = _parse_json_object(_last_message_content(retry_result))
            except Exception as exc:
                retry_report = {
                    "passed": False,
                    "severity_counts": {"P0": 1, "P1": 0, "P2": 0, "P3": 0},
                    "checked_gates": ["critic_output_parse_retry"],
                    "findings": [
                        {
                            "severity": "P0",
                            "issue": "critic retry output was not parseable CriticOutput JSON",
                            "evidence": str(exc),
                            "repair": "Return JSON conforming to CriticOutput.",
                        }
                    ],
                    "repair_instructions": [],
                    "claim_verdicts": [],
                }
            retry_contradictions = _critic_validation_contradictions(
                retry_report,
                validation,
            )
            report = (
                _mark_critic_contradiction_failure(retry_report, retry_contradictions)
                if retry_contradictions
                else retry_report
            )
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "critic_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _copy_if_exists(
            evidence_dir / "critic_report.json",
            evidence_dir / f"critic_report.{label}.json",
        )
        return report

    def _initial_writer_instruction(self, base: Path) -> str:
        return (
            "Generate report_expansions.json for the deterministic renderer.\n"
            f"data_dir: {base}\n"
            "build_evidence_summary has already run exactly once. Do not call it.\n"
            "Do not write drug.md, target_assessment.json, or renderer artifacts.\n"
            "Do not use file-edit or patch tools; the host persists validated JSON.\n"
            "If filesystem listing/reading is unavailable or returns empty, do not block. "
            "The host-embedded slot and provenance inventory below is sufficient to write "
            "conservative, evidence-limited report_expansions.v1 JSON.\n"
            "You MUST call save_report_expansions(data_dir, expansions) with the complete JSON. "
            f"Required call shape: save_report_expansions(data_dir={str(base)!r}, "
            "expansions={\"schema_version\":\"report_expansions.v1\",\"slots\":[...]}). "
            "Never call save_report_expansions with only status/path/slot_count or without the "
            "expansions object. If the tool rejects a call, fix the arguments and call it again.\n"
            "After the tool call, return a compact JSON status; include the full JSON in the "
            "final response only if it fits comfortably.\n"
            "The final JSON must include a non-empty `slots` list with every required slot_id; "
            "do not return an empty object, an empty slots list, or a slot-id keyed object.\n"
            "Do not use generic placeholder prose such as 'summarized conservatively from "
            "the current reference card' or 'evidence-limited local context'. Write a "
            "specific sentence for each slot using the supplied slot_id, gene, and preferred provenance.\n"
            "Use drug_report_reference_card.json as the authoritative source.\n"
            "The save_report_expansions tool fills reference_card_hash automatically; "
            "do not try to compute it.\n"
            "Each slot must include at least one sentence. Each sentence must include "
            "source_fields and source_provenance with source_file/source_field/source_class "
            "from the provenance index. For interpretive prose, set claim_type=\"interpretation\" "
            "and end the sentence text with [source: <source_field>].\n"
            f"{_reference_card_guidance(base)}"
        )

    def _initial_writer_retry_instruction(
        self,
        base: Path,
        *,
        writer_persist: dict[str, Any],
        writer_result: Any,
    ) -> str:
        return (
            "## INITIAL EXPANSION RETRY\n"
            "The previous report_writer result did not create a valid canonical "
            "report_expansions.json. Retry once with a complete replacement.\n"
            f"data_dir: {base}\n"
            "Do not call build_evidence_summary, render_drug_md_from_expansions, or save_drug_md.\n"
            "Do not use file-edit or patch tools.\n"
            f"host_persist_result: {json.dumps(writer_persist, ensure_ascii=False)}\n"
            f"previous_writer_result: {_last_message_content(writer_result)[:2000]}\n"
            "You MUST call save_report_expansions(data_dir, expansions) with the full "
            "report_expansions.v1 JSON object. Required call shape: "
            f"save_report_expansions(data_dir={str(base)!r}, "
            "expansions={\"schema_version\":\"report_expansions.v1\",\"slots\":[...]}). "
            "Never pass only data_dir, path, status, slot_count, or missing_slots. "
            "If a tool call is rejected, immediately call it again with the full expansions payload.\n"
            "The JSON must include every required slot_id below and each slot must contain "
            "at least one sentence with source_fields and source_provenance.\n"
            "Do not use generic placeholder prose such as 'summarized conservatively from "
            "the current reference card' or 'evidence-limited local context'.\n"
            f"{_reference_card_guidance(base)}"
        )

    def _repair_writer_instruction(
        self,
        base: Path,
        *,
        validation: dict[str, Any],
        critic_report: dict[str, Any],
        repair_index: int,
    ) -> str:
        return (
            "## REPAIR MODE\n"
            f"Repair attempt: {repair_index} of {self.max_repairs}\n"
            f"data_dir: {base}\n"
            "Modify only report_expansions.json via save_report_expansions.\n"
            "Do not use file-edit or patch tools; the host persists validated JSON.\n"
            "If filesystem listing/reading is unavailable or returns empty, do not block. "
            "Use the host-embedded slot and provenance inventory below to produce a "
            "complete conservative replacement.\n"
            "You MUST call save_report_expansions(data_dir, expansions) with the complete replacement JSON. "
            f"Required call shape: save_report_expansions(data_dir={str(base)!r}, "
            "expansions={\"schema_version\":\"report_expansions.v1\",\"slots\":[...]}). "
            "Never call save_report_expansions with only status/path/slot_count or without the "
            "expansions object. If the tool rejects a call, fix the arguments and call it again.\n"
            "After the tool call, return a compact JSON status; include the full JSON in the "
            "final response only if it fits comfortably.\n"
            "The replacement JSON must include a non-empty `slots` list with every required slot_id.\n"
            "Do not use generic placeholder prose such as 'summarized conservatively from "
            "the current reference card' or 'evidence-limited local context'.\n"
            "Do not call build_evidence_summary, render_drug_md_from_expansions, or save_drug_md.\n"
            f"validator: {json.dumps(validation, ensure_ascii=False)}\n"
            f"critic: {json.dumps(critic_report, ensure_ascii=False)}\n"
            f"{_reference_card_guidance(base)}"
        )

    def _critic_instruction(
        self,
        base: Path,
        *,
        validation: dict[str, Any],
        render_result: dict[str, Any],
        label: str,
        critic_context: str = "",
    ) -> str:
        virtual_validation = _virtualize_paths_for_instruction(validation, base)
        virtual_render_result = _virtualize_paths_for_instruction(render_result, base)
        return (
            "Audit the current deterministic drug report and return CriticOutput JSON only.\n"
            "Filesystem tools are rooted at the run data directory; use virtual-root paths only.\n"
            "Read /drug.md, /drug_report_render.json, /report_expansions.json, "
            "/drug_report_reference_card.json, /evidence/resolved_drugs.json, "
            "and /evidence/_critic_slices/*.json.\n"
            "Do not read/glob host absolute paths from validator metadata; convert them to "
            "the matching virtual-root path first.\n"
            "The host has already run validation; use the supplied validation JSON unless "
            "you need an explicit re-check.\n"
            "Do not report validate_drug_md finding types unless they are present in the "
            "supplied validate_drug_md JSON. The required disease_scope note is not a drug "
            "claim and must not be classified as FABRICATED_DRUG_NAME.\n"
            "Set passed=false only for P0/P1 findings or FAIL claim_verdicts; P2/P3 "
            "recommendations are advisory and should keep passed=true.\n"
            "Treat exact Section 4 template fields copied from /evidence/_critic_slices/_hypothesis.json "
            "(hypothesis_metadata plus hypothesis_report core_claim, evidence_references, "
            "biological_entities, falsifiable_prediction, and validation_approach) as grounded.\n"
            f"render_label: {label}\n"
            f"{critic_context}"
            f"validate_drug_md: {json.dumps(virtual_validation, ensure_ascii=False)}\n"
            f"render_result: {json.dumps(virtual_render_result, ensure_ascii=False)}"
        )

    def _critic_retry_instruction(
        self,
        base: Path,
        *,
        validation: dict[str, Any],
        render_result: dict[str, Any],
        label: str,
        previous_report: dict[str, Any],
        contradictions: list[dict[str, Any]],
    ) -> str:
        virtual_validation = _virtualize_paths_for_instruction(validation, base)
        virtual_render_result = _virtualize_paths_for_instruction(render_result, base)
        return (
            "Audit retry: the previous CriticOutput contradicted the supplied "
            "validate_drug_md JSON.\n"
            "Return corrected CriticOutput JSON only. Do not report validator finding "
            "types unless they are present in the supplied validate_drug_md JSON. "
            "If no supported P0/P1 issue remains, set passed=true and keep any P2/P3 "
            "findings advisory.\n"
            "The required disease_scope note is not a drug claim and must not be "
            "classified as FABRICATED_DRUG_NAME.\n"
            "Use virtual-root paths only when reading files.\n"
            f"render_label: {label}\n"
            f"contradictions: {json.dumps(contradictions, ensure_ascii=False)}\n"
            f"previous_report: {json.dumps(previous_report, ensure_ascii=False)}\n"
            f"validate_drug_md: {json.dumps(virtual_validation, ensure_ascii=False)}\n"
            f"render_result: {json.dumps(virtual_render_result, ensure_ascii=False)}"
        )


def create_summarizer_agent(
    *,
    model: str | BaseChatModel | None = None,
    backend: BackendProtocol | BackendFactory | None = None,
    inner_subagents: Sequence[dict[str, Any]] = (),
    tools: Sequence[BaseTool | Any] | None = None,
    data_dir: str | None = None,
) -> Runnable:
    """Create the deterministic report-finalization Runnable.

    The host Python loop owns build -> render -> validate -> critic -> repair
    -> finalization. Child LLM runnables are limited to report_expansions
    writing/repair and critic critique.

    Args:
        model: LLM model string or BaseChatModel instance.
        backend: Explicit backend to use.  Mutually exclusive with ``data_dir``.
        inner_subagents: Sequence of inner subagent config dicts.
        tools: Override tool list.  Defaults to the standard summarizer tool set.
        data_dir: Root directory for on-disk evidence files.  When provided the
            factory builds a ``FilesystemBackend(root_dir=data_dir,
            virtual_mode=True)`` automatically.  Mutually exclusive with
            ``backend`` — pass one or the other, never both.

    Raises:
        ValueError: If both ``backend`` and ``data_dir`` are provided.
    """
    if backend is not None and data_dir is not None:
        raise ValueError(
            "create_summarizer_agent: pass either `backend` or `data_dir`, not both. "
            "When `data_dir` is provided, the factory builds the FilesystemBackend automatically."
        )
    if backend is None and data_dir is not None:
        backend = _build_disk_backend(data_dir)

    child_configs = list(inner_subagents)
    if not child_configs:
        from src.agents.drug_target.subagents.configs import SUBAGENT_CONFIGS  # noqa: PLC0415

        child_configs = [
            {
                **SUBAGENT_CONFIGS["report_writer"],
                "tools": list(SUBAGENT_CONFIGS["report_writer"]["tools"]),
            },
            {
                **SUBAGENT_CONFIGS["critic"],
                "tools": list(SUBAGENT_CONFIGS["critic"]["tools"]),
            },
        ]

    by_name = {str(config.get("name")): config for config in child_configs}
    report_writer_config = by_name.get("report_writer", {})
    critic_config = by_name.get("critic", {})

    report_writer = create_deep_agent(
        model=report_writer_config.get("model", model),
        tools=list(report_writer_config.get("tools", tools or [])),
        system_prompt=str(report_writer_config.get("system_prompt", REPORT_WRITER_PROMPT)),
        backend=backend,
        middleware=list(report_writer_config.get("middleware", [])),
    ).with_config({"recursion_limit": 3000})
    critic = create_deep_agent(
        model=critic_config.get("model", model),
        tools=list(critic_config.get("tools", [])),
        system_prompt=str(critic_config.get("system_prompt", CRITIC_PROMPT)),
        backend=backend,
        middleware=list(critic_config.get("middleware", [])),
    ).with_config({"recursion_limit": 3000})

    return DeterministicSummarizerRunnable(
        report_writer=report_writer,
        critic=critic,
        data_dir=data_dir,
        max_repairs=2,
    )


class _CriticSliceWrapper:
    """Thin lifecycle wrapper: write slices -> invoke agent -> cleanup slices.

    This is NOT a LangGraph node or DeepAgent — it is a minimal callable that
    satisfies the Runnable protocol used by DeepAgents CompiledSubAgent.  The
    only public method is ``invoke``; ``with_config`` delegates to the inner
    agent so that recursion_limit and other config flow through unchanged.
    """

    def __init__(self, agent: Runnable, *, data_dir: str) -> None:
        self._agent = agent
        self._data_dir = data_dir

    # ------------------------------------------------------------------
    # Runnable protocol: delegate with_config so callers can chain it
    # ------------------------------------------------------------------

    def with_config(self, config: Any, **kwargs: Any) -> "_CriticSliceWrapper":
        new_agent = self._agent.with_config(config, **kwargs)
        return _CriticSliceWrapper(new_agent, data_dir=self._data_dir)

    # ------------------------------------------------------------------
    # Core: write slices, invoke, cleanup
    # ------------------------------------------------------------------

    def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:  # noqa: A002
        """Write critic slices, run the inner agent, then clean up."""
        # Lazy import to avoid circular dependency:
        # summarizer/agent.py <- configs.py <- summarizer/__init__.py
        from src.agents.drug_target.subagents.configs import (  # noqa: PLC0415
            cleanup_critic_slices,
            filter_hypothesis_evidence_files,
            write_critic_slices,
        )
        _emit_lifecycle("before_filter", self._data_dir)
        filter_hypothesis_evidence_files(self._data_dir)
        _emit_lifecycle("before_write", self._data_dir)
        write_critic_slices(self._data_dir)
        _emit_lifecycle("before_invoke", self._data_dir)
        try:
            if config is not None:
                return self._agent.invoke(input, config, **kwargs)
            return self._agent.invoke(input, **kwargs)
        finally:
            _emit_lifecycle("after_invoke", self._data_dir)
            cleanup_critic_slices(self._data_dir)
            _emit_lifecycle("after_cleanup", self._data_dir)

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:  # noqa: A002
        """Async variant: write critic slices, run the inner agent, then clean up."""
        from src.agents.drug_target.subagents.configs import (  # noqa: PLC0415
            cleanup_critic_slices,
            filter_hypothesis_evidence_files,
            write_critic_slices,
        )
        _emit_lifecycle("before_filter", self._data_dir)
        filter_hypothesis_evidence_files(self._data_dir)
        _emit_lifecycle("before_write", self._data_dir)
        write_critic_slices(self._data_dir)
        _emit_lifecycle("before_invoke", self._data_dir)
        try:
            if config is not None:
                return await self._agent.ainvoke(input, config, **kwargs)
            return await self._agent.ainvoke(input, **kwargs)
        finally:
            _emit_lifecycle("after_invoke", self._data_dir)
            cleanup_critic_slices(self._data_dir)
            _emit_lifecycle("after_cleanup", self._data_dir)


def wrap_summarizer_with_critic_slices(
    agent: Runnable,
    *,
    data_dir: str,
) -> _CriticSliceWrapper:
    """Wrap a summarizer agent with critic-slice lifecycle management.

    Writes evidence/_critic_slices/ before the agent runs and removes it
    afterward (unless OMB_CRITIC_SLICES_KEEP=1 is set in the environment).

    Args:
        agent: The compiled summarizer Runnable to wrap.
        data_dir: Path to the run's working directory (parent of ``evidence/``).

    Returns:
        A ``_CriticSliceWrapper`` that satisfies the Runnable invoke protocol.
    """
    return _CriticSliceWrapper(agent, data_dir=data_dir)


def get_summarizer_subagent(
    *,
    model: str | BaseChatModel | None = None,
    backend: BackendProtocol | BackendFactory | None = None,
    inner_subagents: Sequence[dict[str, Any]] = (),
    data_dir: str | None = None,
) -> dict[str, Any]:
    """Return the summarizer in DeepAgents CompiledSubAgent format.

    When ``data_dir`` is provided the returned runnable is wrapped with
    ``_CriticSliceWrapper`` so that per-gene critic slices are written to
    ``evidence/_critic_slices/`` before the first critic call and removed
    afterward.
    """
    agent = create_summarizer_agent(
        model=model,
        backend=backend,
        data_dir=data_dir,
        inner_subagents=inner_subagents,
    )

    runnable: Runnable | _CriticSliceWrapper
    if data_dir is not None:
        runnable = wrap_summarizer_with_critic_slices(agent, data_dir=data_dir)
    else:
        runnable = agent

    return {
        "name": "summarizer",
        "description": (
            "Autonomous audited report finalizer. Runs report_writer, "
            "deterministic validators, read-only critic, and bounded repair "
            "loop before reporting pass/fail."
        ),
        "runnable": runnable,
    }


__all__ = [
    "DeterministicSummarizerRunnable",
    "create_summarizer_agent",
    "get_summarizer_subagent",
    "wrap_summarizer_with_critic_slices",
]

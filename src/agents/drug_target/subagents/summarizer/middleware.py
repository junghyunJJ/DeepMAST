"""Summarizer-specific AgentMiddleware implementations.

Middlewares:
1. BuildEvidenceSummaryGuardMiddleware: Allow build_evidence_summary exactly
   once per agent run; block subsequent calls with a structured error.
2. RepairCycleCounterMiddleware: Block the third task(subagent_type="report_writer")
   after 2 non-converging critic cycles.
"""

from __future__ import annotations

import json
import hashlib
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

logger = logging.getLogger(__name__)

_BUILD_EVIDENCE_TOOL = "build_evidence_summary"


def _canonical_payload_hash(value: Any) -> str:
    try:
        payload = json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)
    except TypeError:
        payload = str(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class BuildEvidenceSummaryGuardMiddleware(AgentMiddleware):
    """Allow build_evidence_summary exactly once per agent run.

    On the second invocation within the same middleware instance, returns a
    blocked ToolMessage directing the agent to follow REPAIR MODE without
    rebuilding the evidence summary skeleton.
    """

    def __init__(self) -> None:
        super().__init__()
        self._call_count: int = 0

    def _is_build_evidence(self, request: ToolCallRequest) -> bool:
        return request.tool_call.get("name") == _BUILD_EVIDENCE_TOOL

    def _blocked_response(self, request: ToolCallRequest) -> ToolMessage:
        payload = {
            "already_invoked": True,
            "error": (
                "build_evidence_summary has already been called once in this agent run. "
                "The drug.md skeleton already exists on disk. "
                "STOP — do NOT call build_evidence_summary again. "
                "Follow REPAIR MODE: load_evidence_files('drug.md') then patch in-place."
            ),
        }
        return ToolMessage(
            content=json.dumps(payload),
            tool_call_id=request.tool_call.get("id", ""),
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if self._is_build_evidence(request):
            if self._call_count >= 1:
                logger.warning(
                    "BuildEvidenceSummaryGuardMiddleware: blocking duplicate "
                    "build_evidence_summary call (count=%d)",
                    self._call_count,
                )
                return self._blocked_response(request)
            self._call_count += 1
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if self._is_build_evidence(request):
            if self._call_count >= 1:
                logger.warning(
                    "BuildEvidenceSummaryGuardMiddleware: blocking duplicate "
                    "build_evidence_summary call (count=%d)",
                    self._call_count,
                )
                return self._blocked_response(request)
            self._call_count += 1
        return await handler(request)


_REPORT_WRITER_SUBAGENT = "report_writer"
_MAX_REPAIR_CYCLES_DEFAULT = 2


class RepairCycleCounterMiddleware(AgentMiddleware):
    """Block the third task(subagent_type="report_writer") after max_cycles.

    Inner subagents (critic, report_writer) are dispatched via the deepagents
    built-in `task` tool. This middleware tracks how many times the
    report_writer subagent has been invoked and blocks the (max_cycles+1)th
    call, returning a BLOCKED ToolMessage with the last known critic findings.
    """

    def __init__(self, *, max_cycles: int = _MAX_REPAIR_CYCLES_DEFAULT) -> None:
        super().__init__()
        self._max_cycles = max_cycles
        self._report_writer_count: int = 0
        self._last_critic_findings: str = ""

    def _subagent_type(self, request: ToolCallRequest) -> str | None:
        if request.tool_call.get("name") != "task":
            return None
        args = request.tool_call.get("args") or {}
        if isinstance(args, dict):
            return args.get("subagent_type")
        return None

    def _blocked_response(self, request: ToolCallRequest) -> ToolMessage:
        payload = {
            "status": "BLOCKED",
            "reason": (
                f"report_writer has been invoked {self._report_writer_count} time(s). "
                f"Max repair cycles ({self._max_cycles}) reached. "
                "The report has not converged after the allowed repair attempts. "
                "Terminate this run and surface the critic findings below."
            ),
            "critic_findings": self._last_critic_findings or "No findings recorded.",
        }
        return ToolMessage(
            content=json.dumps(payload),
            tool_call_id=request.tool_call.get("id", ""),
        )

    def _handle_critic_result(self, result: ToolMessage | Command) -> None:
        """Extract critic findings from tool result for use in BLOCKED message."""
        if isinstance(result, ToolMessage):
            self._last_critic_findings = str(result.content)
        elif isinstance(result, Command):
            # Command may wrap a ToolMessage in its update
            update = getattr(result, "update", None)
            if isinstance(update, dict):
                msgs = update.get("messages", [])
                if msgs:
                    last = msgs[-1]
                    if isinstance(last, ToolMessage):
                        self._last_critic_findings = str(last.content)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        subagent = self._subagent_type(request)
        if subagent == _REPORT_WRITER_SUBAGENT:
            if self._report_writer_count >= self._max_cycles:
                logger.warning(
                    "RepairCycleCounterMiddleware: blocking report_writer "
                    "(count=%d, max=%d)",
                    self._report_writer_count,
                    self._max_cycles,
                )
                return self._blocked_response(request)
            self._report_writer_count += 1
            result = handler(request)
            return result
        result = handler(request)
        if subagent == "critic":
            self._handle_critic_result(result)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        subagent = self._subagent_type(request)
        if subagent == _REPORT_WRITER_SUBAGENT:
            if self._report_writer_count >= self._max_cycles:
                logger.warning(
                    "RepairCycleCounterMiddleware: blocking report_writer "
                    "(count=%d, max=%d)",
                    self._report_writer_count,
                    self._max_cycles,
                )
                return self._blocked_response(request)
            self._report_writer_count += 1
            result = await handler(request)
            return result
        result = await handler(request)
        if subagent == "critic":
            self._handle_critic_result(result)
        return result


_SAVE_DRUG_MD_TOOL = "save_drug_md"
_ANNOTATION_RE = re.compile(r"\[source:[^\]]+\]")
_SENTENCE_END_RE = re.compile(r"[.!?]")
_DEFAULT_ANNOTATION_THRESHOLD = 10


def _is_prose_line(line: str) -> bool:
    """Mirror of stage_logic._is_expand_prose: not header / table / list."""
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith("|") or stripped.startswith("#"):
        return False
    if re.match(r"[-*]\s+|^\d+\.\s+", stripped):
        return False
    return True


def _count_prose_sentences(content: str) -> int:
    """Count sentence-end punctuation occurrences across prose lines.

    Mirrors the heuristic used by the UNANCHORED_SENTENCE validator: prose
    lines are non-empty lines that are not headers, tables, or list items.
    """
    total = 0
    for line in content.splitlines():
        if not _is_prose_line(line):
            continue
        total += len(_SENTENCE_END_RE.findall(line))
    return total


class AnnotationDensityMiddleware(AgentMiddleware):
    """Reject ``save_drug_md`` when EXPAND-region prose is under-annotated.

    Prompt-only enforcement of per-sentence ``[source: <field>]`` annotations
    proved unreliable on local LLMs (1/20 in the qwen3.5:35b run). This
    middleware intercepts ``save_drug_md`` tool calls and counts
    ``[source:...]`` markers in the saved content. When the document already
    contains enough prose sentences to warrant annotation
    (``prose_sentences >= threshold``) but the annotation count is below the
    threshold, the call is rejected with a structured error directing the
    writer to add annotations before retrying.

    Documents shorter than ``threshold`` prose sentences pass through — the
    UNANCHORED_SENTENCE validator already covers them at validation time, and
    failing tiny saves here would block legitimate degenerate cases.
    """

    def __init__(self, *, threshold: int = _DEFAULT_ANNOTATION_THRESHOLD) -> None:
        super().__init__()
        self._threshold = threshold

    def _evaluate(self, request: ToolCallRequest) -> ToolMessage | None:
        if request.tool_call.get("name") != _SAVE_DRUG_MD_TOOL:
            return None
        args = request.tool_call.get("args") or {}
        content = ""
        if isinstance(args, dict):
            raw = args.get("content")
            if isinstance(raw, str):
                content = raw
        if not content:
            return None
        prose_sentences = _count_prose_sentences(content)
        if prose_sentences < self._threshold:
            return None
        annotation_count = len(_ANNOTATION_RE.findall(content))
        if annotation_count >= self._threshold:
            return None
        deficit = self._threshold - annotation_count
        payload = {
            "ok": False,
            "error": (
                f"Annotation density too low: found {annotation_count} "
                f"`[source: <field>]` annotations across {prose_sentences} prose "
                f"sentences, need >= {self._threshold}. Add `[source: <field>]` "
                f"to at least {deficit} more EXPAND-region sentences before saving."
            ),
            "annotation_count": annotation_count,
            "prose_sentences": prose_sentences,
            "threshold": self._threshold,
        }
        logger.warning(
            "AnnotationDensityMiddleware: blocking save_drug_md "
            "(annotations=%d, prose=%d, threshold=%d)",
            annotation_count,
            prose_sentences,
            self._threshold,
        )
        return ToolMessage(
            content=json.dumps(payload),
            tool_call_id=request.tool_call.get("id", ""),
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        rejection = self._evaluate(request)
        if rejection is not None:
            return rejection
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        rejection = self._evaluate(request)
        if rejection is not None:
            return rejection
        return await handler(request)


class HypothesisRetryLoopMiddleware(AgentMiddleware):
    """Block unchanged retries after a deterministic hypothesis-save rejection."""

    def __init__(self) -> None:
        super().__init__()
        self._rejected_payload_hashes: set[str] = set()

    def _payload_for_request(self, request: ToolCallRequest) -> Any | None:
        tool_name = request.tool_call.get("name")
        args = request.tool_call.get("args") or {}
        if not isinstance(args, dict):
            return None
        if tool_name == "save_hypothesis_report":
            return args.get("report")
        if tool_name == "save_evidence" and args.get("filename") == "hypothesis_report.json":
            return args.get("data")
        return None

    def _blocked_response(self, request: ToolCallRequest, payload_hash: str) -> ToolMessage:
        payload = {
            "saved": False,
            "error": (
                "Identical hypothesis_report payload was already rejected by a "
                "deterministic save gate. Mutate the payload according to the "
                "previous errors before retrying."
            ),
            "payload_hash": payload_hash,
        }
        return ToolMessage(
            content=json.dumps(payload),
            tool_call_id=request.tool_call.get("id", ""),
        )

    def _record_if_rejected(self, payload_hash: str, result: ToolMessage | Command) -> None:
        if not isinstance(result, ToolMessage):
            return
        try:
            parsed = json.loads(str(result.content))
        except Exception:
            return
        if isinstance(parsed, dict) and parsed.get("saved") is False:
            self._rejected_payload_hashes.add(payload_hash)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        payload = self._payload_for_request(request)
        if payload is None:
            return handler(request)
        payload_hash = _canonical_payload_hash(payload)
        if payload_hash in self._rejected_payload_hashes:
            return self._blocked_response(request, payload_hash)
        result = handler(request)
        self._record_if_rejected(payload_hash, result)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        payload = self._payload_for_request(request)
        if payload is None:
            return await handler(request)
        payload_hash = _canonical_payload_hash(payload)
        if payload_hash in self._rejected_payload_hashes:
            return self._blocked_response(request, payload_hash)
        result = await handler(request)
        self._record_if_rejected(payload_hash, result)
        return result


class FrozenTemplateSpanMiddleware(AgentMiddleware):
    """Reject legacy save_drug_md calls that mutate non-EXPAND template spans."""

    def __init__(self, *, data_dir: str | None = None) -> None:
        super().__init__()
        self._data_dir = data_dir

    def _static_spans_preserved(self, template: str, candidate: str) -> bool:
        spans = [span for span in re.split(r"<!--\s*EXPAND:.*?-->", template, flags=re.DOTALL) if span]
        position = 0
        for span in spans:
            found = candidate.find(span, position)
            if found == -1:
                return False
            position = found + len(span)
        return True

    def _evaluate(self, request: ToolCallRequest) -> ToolMessage | None:
        if request.tool_call.get("name") != _SAVE_DRUG_MD_TOOL or not self._data_dir:
            return None
        args = request.tool_call.get("args") or {}
        if not isinstance(args, dict) or not isinstance(args.get("content"), str):
            return None
        try:
            from pathlib import Path

            card_path = Path(self._data_dir) / "drug_report_reference_card.json"
            if not card_path.exists():
                return None
            card = json.loads(card_path.read_text(encoding="utf-8"))
            template = card.get("markdown_template")
            if not isinstance(template, str) or not template:
                return None
        except Exception:
            return None
        if self._static_spans_preserved(template, args["content"]):
            return None
        payload = {
            "saved": False,
            "error": (
                "save_drug_md candidate mutates frozen non-EXPAND template spans. "
                "Use save_report_expansions followed by render_drug_md_from_expansions, "
                "or preserve all table/headings/score spans exactly."
            ),
        }
        return ToolMessage(
            content=json.dumps(payload),
            tool_call_id=request.tool_call.get("id", ""),
        )

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        rejection = self._evaluate(request)
        if rejection is not None:
            return rejection
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        rejection = self._evaluate(request)
        if rejection is not None:
            return rejection
        return await handler(request)


__all__ = [
    "AnnotationDensityMiddleware",
    "BuildEvidenceSummaryGuardMiddleware",
    "FrozenTemplateSpanMiddleware",
    "HypothesisRetryLoopMiddleware",
    "RepairCycleCounterMiddleware",
]

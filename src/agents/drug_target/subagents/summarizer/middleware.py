"""Middleware retained after the summarizer simplification (2026-05-13).

Surviving classes:

1. ``SummarizerFinalizationGuardMiddleware`` — adapted fail-closed gate.
   Captures the result of ``validate_drug_md`` and blocks
   ``generate_drug_html_report`` unless the most recent ``validate_drug_md``
   call returned ``valid=true``. This is the single mechanical protection
   that prevents the summarizer LLM from declaring ``SUMMARIZER_STATUS: PASS``
   without a real validator pass when the LLM is later instructed to render
   the HTML.

2. ``HypothesisRetryLoopMiddleware`` — out of scope for the summarizer
   simplification; used by the ``hypothesis_writer`` subagent to suppress
   identical-payload retries against the deterministic save gate.

Removed in the 2026-05-13 simplification:

- ``BuildEvidenceSummaryGuardMiddleware`` (duplicate-call protection moved to
  prompt-level guidance).
- ``RepairCycleCounterMiddleware`` (retry budget moved to prompt-level
  guidance: max 2 ``save_report_expansions`` retries).
- ``AnnotationDensityMiddleware`` (no ``save_drug_md`` tool to guard;
  ``validate_drug_md`` already covers annotation density at validation time).
- ``FrozenTemplateSpanMiddleware`` (deterministic template assembly is now
  the job of ``render_drug_md_from_expansions``; the LLM never writes
  ``drug.md`` directly).
"""

from __future__ import annotations

import copy
import json
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from src.agents.drug_target.tools.report_expansion_schema import canonical_json_hash

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Critic envelope schema constants
# ---------------------------------------------------------------------------

_CRITIC_ENVELOPE_VERSION = "summarizer_critic_review.v1"
_REPORT_EXPANSIONS_VERSION = "report_expansions.v1"


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class EnvelopeParseError(ValueError):
    """Raised when a critic task envelope cannot be parsed or violates invariants."""


# ---------------------------------------------------------------------------
# Envelope dataclass
# ---------------------------------------------------------------------------


@dataclass
class CriticEnvelope:
    """Typed representation of the summarizer→critic task envelope."""

    schema_version: str
    payload_hash: str  # LLM-supplied; NOT trusted for gate logic
    payload: dict[str, Any]  # Must conform to report_expansions.v1 structure
    provenance_context: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Envelope parser
# ---------------------------------------------------------------------------


def _load_critic_envelope_raw(description: Any) -> dict[str, Any]:
    """Load the raw critic envelope from JSON text or provider-decoded objects."""
    if isinstance(description, str):
        try:
            raw = json.loads(description)
        except (json.JSONDecodeError, ValueError) as exc:
            raise EnvelopeParseError(f"envelope is not valid JSON: {exc}") from exc
    elif isinstance(description, Mapping):
        raw = dict(description)
    else:
        raise EnvelopeParseError(
            "envelope description must be a JSON string or object; "
            f"got {type(description).__name__}"
        )

    if not isinstance(raw, dict):
        raise EnvelopeParseError("envelope must be a JSON object")
    return raw


def canonical_critic_description(description: Any) -> str:
    """Return the JSON string form required by DeepAgents' task(description=...)."""
    raw = _load_critic_envelope_raw(description)
    try:
        return json.dumps(raw, ensure_ascii=False, sort_keys=True)
    except TypeError as exc:
        raise EnvelopeParseError(f"envelope is not JSON serializable: {exc}") from exc


def parse_critic_envelope(description: Any) -> CriticEnvelope:
    """Parse the JSON envelope from the summarizer's task(subagent_type="critic", description=...) call.

    Returns a typed CriticEnvelope or raises EnvelopeParseError with a
    human-readable reason.

    Accepts a JSON string or an already-decoded mapping. Rejects: non-JSON,
    wrong schema_version, missing fields, payload that does not carry a
    report_expansions.v1 schema_version.
    """
    raw = _load_critic_envelope_raw(description)

    schema_version = raw.get("schema_version")
    if schema_version is None:
        raise EnvelopeParseError(
            f"envelope missing required field 'schema_version'; "
            f"expected '{_CRITIC_ENVELOPE_VERSION}'"
        )
    if schema_version != _CRITIC_ENVELOPE_VERSION:
        raise EnvelopeParseError(
            f"envelope schema_version '{schema_version}' is not supported; "
            f"expected '{_CRITIC_ENVELOPE_VERSION}'"
        )

    if "payload_hash" not in raw:
        raise EnvelopeParseError("envelope missing required field 'payload_hash'")

    payload = raw.get("payload")
    if payload is None:
        raise EnvelopeParseError("envelope missing required field 'payload'")
    if not isinstance(payload, dict):
        raise EnvelopeParseError("envelope 'payload' must be a JSON object")

    payload_sv = payload.get("schema_version")
    if payload_sv != _REPORT_EXPANSIONS_VERSION:
        raise EnvelopeParseError(
            f"payload schema_version '{payload_sv}' is not supported; "
            f"expected '{_REPORT_EXPANSIONS_VERSION}'"
        )

    if not isinstance(payload.get("slots"), list):
        raise EnvelopeParseError("payload missing required field 'slots' (must be a list)")

    provenance_context = raw.get("provenance_context") or {}
    if not isinstance(provenance_context, dict):
        provenance_context = {}

    return CriticEnvelope(
        schema_version=schema_version,
        payload_hash=str(raw["payload_hash"]),
        payload=payload,
        provenance_context=provenance_context,
    )


# ---------------------------------------------------------------------------
# Shared payload normalization
# ---------------------------------------------------------------------------


def normalize_expansions_for_hash(payload: Any) -> dict:
    """Produce the canonical dict shape used as input to canonical_json_hash.

    Accepts:
    - raw dict (from request.tool_call["args"]["expansions"])
    - Pydantic ReportExpansionsPayload instance (or model_dump output)

    Strategy: strip ``reference_card_hash`` from the normalized output on
    both sides. This means a payload with the field omitted and one with
    any concrete derived value produce identical hashes — the hash commits
    only to ``schema_version`` and ``slots``. This is the safest choice
    because the critic envelope is built *before* ``save_report_expansions``
    auto-derives the reference_card_hash from disk, so the critic can never
    supply the correct derived value anyway.
    """
    from pydantic import BaseModel  # local import to avoid circular deps

    if isinstance(payload, BaseModel):
        as_dict: dict = payload.model_dump()
    elif isinstance(payload, dict):
        as_dict = dict(payload)
    else:
        raise EnvelopeParseError(
            f"normalize_expansions_for_hash: unsupported payload type {type(payload).__name__}"
        )

    # Strip the derived/optional field so both sides hash identically
    as_dict.pop("reference_card_hash", None)
    return as_dict


# ---------------------------------------------------------------------------
# Compute envelope payload hash (uses normalize, ignores LLM-supplied hash)
# ---------------------------------------------------------------------------


def compute_envelope_payload_hash(envelope: CriticEnvelope) -> str:
    """Compute the real canonical hash of envelope.payload.

    The LLM-supplied ``envelope.payload_hash`` is NOT used. Gate middleware
    (task #7) must call this function and compare against what
    ``save_report_expansions`` is about to receive.
    """
    return canonical_json_hash(normalize_expansions_for_hash(envelope.payload))


# ---------------------------------------------------------------------------
# Cited-only provenance validator
# ---------------------------------------------------------------------------


def validate_cited_only_provenance(envelope: CriticEnvelope) -> None:
    """Raise EnvelopeParseError if any provenance_context entry references a
    (source_file, source_field) that is not actually cited in the
    corresponding slot's sentences.

    Token-budget critical — full provenance_index is forbidden in the
    envelope; only cited entries may appear.
    """
    if not envelope.provenance_context:
        return

    # Build a map of slot_id -> set of (source_file, source_field) cited
    cited_by_slot: dict[str, set[tuple[str, str]]] = {}
    slots = envelope.payload.get("slots") or []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        slot_id = str(slot.get("slot_id") or "")
        cited: set[tuple[str, str]] = set()
        for sentence in slot.get("sentences") or []:
            if not isinstance(sentence, dict):
                continue
            prov = sentence.get("source_provenance")
            if not isinstance(prov, dict):
                continue
            sf = prov.get("source_file")
            field_name = prov.get("source_field")
            if sf and field_name:
                cited.add((str(sf), str(field_name)))
        cited_by_slot[slot_id] = cited

    # Validate each provenance_context entry
    for slot_id, ctx in envelope.provenance_context.items():
        if not isinstance(ctx, dict):
            continue
        cited_set = cited_by_slot.get(slot_id, set())
        for entry in ctx.get("cited_provenance_entries") or []:
            if not isinstance(entry, dict):
                continue
            sf = str(entry.get("source_file") or "")
            field_name = str(entry.get("source_field") or "")
            if (sf, field_name) not in cited_set:
                raise EnvelopeParseError(
                    f"provenance_context['{slot_id}'] references "
                    f"({sf!r}, {field_name!r}) which is not cited in any "
                    f"sentence of that slot — only cited sources are allowed "
                    f"in the envelope (token-budget constraint)"
                )


class HypothesisRetryLoopMiddleware(AgentMiddleware):
    """Block unchanged retries after a deterministic hypothesis-save rejection.

    Used by the ``hypothesis_writer`` subagent. Out of scope for the
    2026-05-13 summarizer simplification.
    """

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
        payload_hash = canonical_json_hash(payload)
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
        payload_hash = canonical_json_hash(payload)
        if payload_hash in self._rejected_payload_hashes:
            return self._blocked_response(request, payload_hash)
        result = await handler(request)
        self._record_if_rejected(payload_hash, result)
        return result


_VALIDATOR_TOOL = "validate_drug_md"
_GUARDED_FINALIZATION_TOOL = "generate_drug_html_report"
_CRITIC_TASK_TOOL = "task"
_CRITIC_SUBAGENT_TYPE = "critic"
_SAVE_EXPANSIONS_TOOL = "save_report_expansions"


# ---------------------------------------------------------------------------
# CriticGateMiddleware — captures critic results and gates save_report_expansions
# ---------------------------------------------------------------------------


class CriticGateMiddleware(AgentMiddleware):
    """Gate ``save_report_expansions`` on a prior valid critic review.

    Two responsibilities:

    **Capture phase** — when the summarizer calls ``task(subagent_type='critic', ...)``:
    1. Parse the envelope from the description via ``parse_critic_envelope``.
    2. Run the handler.
    3. Extract the critic JSON from both possible result shapes:
       - Direct ``ToolMessage`` (test fakes / sync path)
       - ``Command(update={'messages': [ToolMessage]})`` (real DeepAgents path)
    4. Store ``critic_called``, ``last_valid``, ``last_findings``, and the
       *trusted* payload hash computed from the envelope (not from LLM output).

    **Gate phase** — when the summarizer calls ``save_report_expansions(...)``:
    1. Hash the request expansions **before** calling ``handler(request)``
       because ``save_report_expansions`` mutates ``reference_card_hash``
       during its own validation pass — the pre-handler hash is the only
       stable reference point.
    2. Block (return a ``ToolMessage`` error) if:
       - ``critic_called is False``
       - ``last_valid is False``
       - ``last_payload_hash != current_hash``
    3. Otherwise allow the call through.

    **Reset** — ``before_agent`` clears all state so each summarizer run
    starts fresh.
    """

    def __init__(self) -> None:
        super().__init__()
        self._critic_called: bool = False
        self._last_valid: bool = False
        self._last_findings: list[dict[str, Any]] = []
        self._last_payload_hash: str | None = None

    # ------------------------------------------------------------------
    # before_agent — per-run state reset
    # ------------------------------------------------------------------

    def before_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        """Clear all per-run state so each summarizer invocation starts fresh."""
        self._critic_called = False
        self._last_valid = False
        self._last_findings = []
        self._last_payload_hash = None
        return None

    async def abefore_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        """Async variant of before_agent."""
        return self.before_agent(state, runtime)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_critic_task(self, request: ToolCallRequest) -> bool:
        if request.tool_call.get("name") != _CRITIC_TASK_TOOL:
            return False
        args = request.tool_call.get("args") or {}
        return args.get("subagent_type") == _CRITIC_SUBAGENT_TYPE

    def _is_save_expansions(self, request: ToolCallRequest) -> bool:
        return request.tool_call.get("name") == _SAVE_EXPANSIONS_TOOL

    def _extract_critic_content(self, result: ToolMessage | Command) -> str | None:
        """Extract the raw critic JSON string from either result shape."""
        if isinstance(result, ToolMessage):
            return str(result.content)
        if isinstance(result, Command):
            messages = (result.update or {}).get("messages")
            if messages:
                last = messages[-1]
                if isinstance(last, ToolMessage):
                    return str(last.content)
        return None

    def _capture_critic_result(
        self, envelope: CriticEnvelope, result: ToolMessage | Command
    ) -> None:
        """Parse critic output and update internal state."""
        trusted_hash = compute_envelope_payload_hash(envelope)
        content = self._extract_critic_content(result)
        if content is None:
            logger.warning("CriticGateMiddleware: could not extract critic content from result")
            self._critic_called = True
            self._last_valid = False
            self._last_findings = [{"reason": "critic returned unrecognized result shape"}]
            self._last_payload_hash = None
            return

        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("CriticGateMiddleware: critic JSON parse failed: %s", exc)
            self._critic_called = True
            self._last_valid = False
            self._last_findings = [{"reason": f"critic output is not valid JSON: {exc}"}]
            self._last_payload_hash = None
            return

        if not isinstance(parsed, dict):
            self._critic_called = True
            self._last_valid = False
            self._last_findings = [{"reason": "critic output is not a JSON object"}]
            self._last_payload_hash = None
            return

        findings: list[dict[str, Any]] = parsed.get("findings") or []
        has_blocker = any(
            f.get("severity") == "blocker" for f in findings if isinstance(f, dict)
        )
        critic_valid = bool(parsed.get("valid")) and not has_blocker

        # Validate cited-only provenance AFTER envelope is parsed and BEFORE hash is stored.
        try:
            validate_cited_only_provenance(envelope)
        except EnvelopeParseError as exc:
            logger.warning("CriticGateMiddleware: cited-only provenance violation: %s", exc)
            self._critic_called = True
            self._last_valid = False
            self._last_findings = [{"reason": "uncited provenance entry", "severity": "blocker"}]
            self._last_payload_hash = None
            return

        self._critic_called = True
        self._last_valid = critic_valid
        self._last_findings = findings
        self._last_payload_hash = trusted_hash

    def _blocked_response(self, request: ToolCallRequest, message: str) -> ToolMessage:
        return ToolMessage(
            content=message,
            tool_call_id=request.tool_call.get("id", ""),
        )

    def _mark_invalid_critic_envelope(self, exc: EnvelopeParseError) -> None:
        self._critic_called = True
        self._last_valid = False
        self._last_findings = [{"reason": str(exc)}]
        self._last_payload_hash = None

    def _invalid_critic_envelope_response(
        self, request: ToolCallRequest, exc: EnvelopeParseError
    ) -> ToolMessage:
        return self._blocked_response(
            request,
            f"CRITIC_GATE: invalid critic envelope description — {exc}. "
            "Rebuild the critic envelope as JSON and re-run task(critic).",
        )

    def _prepare_critic_envelope(
        self, request: ToolCallRequest
    ) -> tuple[CriticEnvelope, str]:
        args = request.tool_call.get("args") or {}
        description = args.get("description") or ""
        envelope = parse_critic_envelope(description)
        return envelope, canonical_critic_description(description)

    # ------------------------------------------------------------------
    # Findings sanitization for ToolMessage re-injection
    # ------------------------------------------------------------------

    _CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
    _STRING_FIELD_NAMES = ("sentence", "reason", "repair_instruction")
    _MAX_FINDINGS = 5
    _MAX_FIELD_LEN = 500

    @classmethod
    def _safe_findings_for_message(
        cls, findings: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Return a sanitized deep-copy of findings for ToolMessage re-injection.

        Defenses applied:
        1. Cap to first 5 findings; append an omission marker if truncated.
        2. Truncate string fields (sentence, reason, repair_instruction) to 500 chars.
        3. Strip control characters (\\x00-\\x08, \\x0b, \\x0c, \\x0e-\\x1f, \\x7f)
           from all string fields; keep \\n, \\r, \\t for readability.
        """
        total = len(findings)
        truncated = findings[: cls._MAX_FINDINGS]
        safe: list[dict[str, Any]] = []

        for finding in truncated:
            entry: dict[str, Any] = copy.deepcopy(finding)
            for field_name in cls._STRING_FIELD_NAMES:
                value = entry.get(field_name)
                if not isinstance(value, str):
                    continue
                value = cls._CONTROL_CHAR_RE.sub("", value)
                if len(value) > cls._MAX_FIELD_LEN:
                    value = value[: cls._MAX_FIELD_LEN] + "..."
                entry[field_name] = value
            safe.append(entry)

        if total > cls._MAX_FINDINGS:
            omitted = total - cls._MAX_FINDINGS
            safe.append({"reason": f"...{omitted} more findings omitted", "severity": "info"})

        return safe

    def _check_save_gate(self, request: ToolCallRequest) -> ToolMessage | None:
        """Return a blocking ToolMessage or None if the save is allowed.

        The hash is computed HERE (before handler is called) because
        save_report_expansions mutates reference_card_hash during its own
        validation pass. Computing the hash pre-handler is the only way to
        get a stable value that matches what the critic reviewed.
        """
        if not self._critic_called:
            return self._blocked_response(
                request,
                "CRITIC_GATE: critic was not called before save; "
                "rebuild envelope and call task(subagent_type='critic', ...) first",
            )

        if not self._last_valid:
            safe_findings = self._safe_findings_for_message(self._last_findings)
            findings_text = json.dumps(safe_findings, ensure_ascii=False)
            return self._blocked_response(
                request,
                f"CRITIC_GATE: invalid — critic review failed. "
                f"Resolve the following findings before retrying save: {findings_text}",
            )

        args = request.tool_call.get("args") or {}
        expansions = args.get("expansions") or {}
        try:
            current_hash = canonical_json_hash(normalize_expansions_for_hash(expansions))
        except Exception as exc:
            logger.warning("CriticGateMiddleware: hash computation failed: %s", exc)
            return self._blocked_response(
                request,
                f"CRITIC_GATE: could not hash save payload: {exc}",
            )

        if self._last_payload_hash != current_hash:
            return self._blocked_response(
                request,
                f"CRITIC_GATE: payload mismatch — critic reviewed a different payload. "
                f"critic_hash={self._last_payload_hash!r} save_hash={current_hash!r}. "
                "Rebuild the critic envelope with the current expansions and re-run task(critic).",
            )

        return None

    # ------------------------------------------------------------------
    # wrap_tool_call (sync)
    # ------------------------------------------------------------------

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        if self._is_critic_task(request):
            try:
                envelope, normalized_description = self._prepare_critic_envelope(request)
            except EnvelopeParseError as exc:
                logger.warning("CriticGateMiddleware: envelope parse failed: %s", exc)
                self._mark_invalid_critic_envelope(exc)
                return self._invalid_critic_envelope_response(request, exc)
            request.tool_call["args"]["description"] = normalized_description
            result = handler(request)
            self._capture_critic_result(envelope, result)
            return result

        if self._is_save_expansions(request):
            blocked = self._check_save_gate(request)
            if blocked is not None:
                return blocked
            return handler(request)

        return handler(request)

    # ------------------------------------------------------------------
    # awrap_tool_call (async)
    # ------------------------------------------------------------------

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        if self._is_critic_task(request):
            try:
                envelope, normalized_description = self._prepare_critic_envelope(request)
            except EnvelopeParseError as exc:
                logger.warning("CriticGateMiddleware: envelope parse failed (async): %s", exc)
                self._mark_invalid_critic_envelope(exc)
                return self._invalid_critic_envelope_response(request, exc)
            request.tool_call["args"]["description"] = normalized_description
            result = await handler(request)
            self._capture_critic_result(envelope, result)
            return result

        if self._is_save_expansions(request):
            blocked = self._check_save_gate(request)
            if blocked is not None:
                return blocked
            return await handler(request)

        return await handler(request)


class SummarizerFinalizationGuardMiddleware(AgentMiddleware):
    """Block ``generate_drug_html_report`` until ``validate_drug_md`` passes.

    Mechanical fail-closed gate retained from the pre-simplification
    architecture and adapted to the new tool surface (2026-05-13):

    - Captures the result of every ``validate_drug_md`` call and records
      whether the most recent call returned ``valid=true``.
    - Blocks ``generate_drug_html_report`` when:
        (a) ``validate_drug_md`` has never been called in this run, OR
        (b) the most recent ``validate_drug_md`` returned ``valid=false``,
            ambiguous, or malformed output.
    - Allows the call through only after a clean ``valid=true``.

    The summarizer LLM is also instructed via the system prompt to follow the
    same contract; this middleware is the mechanical backstop.
    """

    def __init__(self) -> None:
        super().__init__()
        self._validator_called: bool = False
        self._last_valid: bool | None = None

    # ------------------------------------------------------------------
    # before_agent — per-run state reset
    # ------------------------------------------------------------------

    def before_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        """Clear all per-run state so each summarizer invocation starts fresh."""
        self._validator_called = False
        self._last_valid = None
        return None

    async def abefore_agent(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        """Async variant of before_agent."""
        return self.before_agent(state, runtime)

    def _is_validator(self, request: ToolCallRequest) -> bool:
        return request.tool_call.get("name") == _VALIDATOR_TOOL

    def _is_guarded_finalization(self, request: ToolCallRequest) -> bool:
        return request.tool_call.get("name") == _GUARDED_FINALIZATION_TOOL

    def _capture_validator_result(self, result: ToolMessage | Command) -> None:
        """Read ``valid`` from the validator's JSON ToolMessage content."""
        if not isinstance(result, ToolMessage):
            return
        try:
            parsed = json.loads(str(result.content))
        except (ValueError, TypeError) as exc:
            logger.warning("validate_drug_md JSON parse failed: %s", exc)
            self._validator_called = True
            self._last_valid = False
            return
        if isinstance(parsed, dict) and "valid" in parsed:
            self._validator_called = True
            self._last_valid = bool(parsed["valid"])
        else:
            logger.warning(
                "validate_drug_md result missing 'valid' key; treating as invalid"
            )
            self._validator_called = True
            self._last_valid = False

    def _blocked(self, request: ToolCallRequest, reason: str) -> ToolMessage:
        payload = {
            "ok": False,
            "error": reason,
            "blocked_by": "SummarizerFinalizationGuard",
        }
        return ToolMessage(
            content=json.dumps(payload),
            tool_call_id=request.tool_call.get("id", ""),
        )

    def _check_gate(self, request: ToolCallRequest) -> ToolMessage | None:
        if not self._is_guarded_finalization(request):
            return None
        if not self._validator_called:
            return self._blocked(
                request,
                "validate_drug_md must be called and return valid=true "
                "before generate_drug_html_report.",
            )
        if self._last_valid is not True:
            return self._blocked(
                request,
                "validate_drug_md returned valid=false; cannot finalize. "
                "Fix the offending sections via save_report_expansions and "
                "re-validate before retrying.",
            )
        return None

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        blocked = self._check_gate(request)
        if blocked is not None:
            return blocked
        result = handler(request)
        if self._is_validator(request):
            self._capture_validator_result(result)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        blocked = self._check_gate(request)
        if blocked is not None:
            return blocked
        result = await handler(request)
        if self._is_validator(request):
            self._capture_validator_result(result)
        return result


__all__ = [
    "CriticEnvelope",
    "CriticGateMiddleware",
    "EnvelopeParseError",
    "HypothesisRetryLoopMiddleware",
    "SummarizerFinalizationGuardMiddleware",
    "compute_envelope_payload_hash",
    "normalize_expansions_for_hash",
    "parse_critic_envelope",
    "validate_cited_only_provenance",
]

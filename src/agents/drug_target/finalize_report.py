"""LangGraph node: finalize_report.

Production finalization delegates to the no-LLM deterministic report MVP path.
The former report-expansion implementation remains available as an explicit
legacy path for transition tests and debugging.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from pathlib import Path
from typing import cast

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools.structured import StructuredTool
from pydantic import ValidationError

from src.agents.drug_target.finalize_report_prompts import (
    FINALIZE_REPORT_SYSTEM_PROMPT,
    FINALIZE_REPORT_USER_TEMPLATE,
)
from src.agents.drug_target.tools import (
    build_evidence_summary as _build_evidence_summary_tool,
    finalize_stage1_artifacts as _finalize_stage1_artifacts_tool,
    generate_drug_html_report as _generate_drug_html_report_tool,
    load_evidence_files as _load_evidence_files_tool,
    render_drug_md_from_expansions as _render_drug_md_tool,
    save_report_expansions as _save_report_expansions_tool,
    validate_drug_report_finalization as _validate_drug_report_finalization_tool,
)

# Cast each tool import to StructuredTool for type-safe .func access via _call_tool.
_build_evidence_summary_st = cast(StructuredTool, _build_evidence_summary_tool)
_load_evidence_files_st = cast(StructuredTool, _load_evidence_files_tool)
_save_report_expansions_st = cast(StructuredTool, _save_report_expansions_tool)
_render_drug_md_st = cast(StructuredTool, _render_drug_md_tool)
_generate_drug_html_st = cast(StructuredTool, _generate_drug_html_report_tool)
_finalize_stage1_st = cast(StructuredTool, _finalize_stage1_artifacts_tool)
_validate_finalization_st = cast(StructuredTool, _validate_drug_report_finalization_tool)
from src.agents.drug_target.tools.report_expansion_schema import (
    EXPANSION_SCHEMA_SPEC_FILE,
    ReportExpansionsPayload,
    canonical_json_hash,
    validate_report_expansions,
)
from src.agents.drug_target.validators import validate_cited_only_provenance

logger = logging.getLogger(__name__)


def _call_tool(tool: StructuredTool, **kwargs):  # type: ignore[return]
    """Call a StructuredTool's underlying function directly (bypasses LangChain wrapper).

    StructuredTool.func is typed as ``Callable | None``; this helper asserts
    non-None so call sites are clean and pyright is satisfied via the
    ``# type: ignore[return]`` on the signature.
    """
    assert tool.func is not None, f"StructuredTool {tool.name!r} has no .func"
    return tool.func(**kwargs)

_REFERENCE_CARD_FILE = "drug_report_reference_card.json"
# Evidence-token fail-closed budget. Sized for a 256K-context deployment
# (qwen3.5 native 262,144): the gate measures evidence only, so we leave
# ~56K headroom for reference_card (~34K) + spec (~2K) + output (~4K) +
# tokenizer-estimate slack. Evidence beyond this is fail-closed
# (evidence_budget_exceeded) rather than silently truncated by the model.
# Deployments with smaller context windows should lower this accordingly.
_TOKEN_BUDGET = 200_000
_COMPACTION_TRIGGER_RATIO = 0.80
_OT_COMPACT_TOP_N = 3
_OT_COMPACT_SCHEMA = "drug_target.ot_per_target_summary.v1"


def _estimate_json_tokens(payload: dict) -> int:
    return len(json.dumps(payload, ensure_ascii=False)) // 4


def _featured_gene_set(reference_card: dict) -> set[str]:
    genes: set[str] = set()
    for raw in reference_card.get("stage3_candidates", []) or []:
        gene = raw.get("gene") if isinstance(raw, dict) else raw
        if gene:
            genes.add(str(gene).strip().upper())
    for card in reference_card.get("featured_genes", []) or []:
        if isinstance(card, dict) and card.get("gene"):
            genes.add(str(card["gene"]).strip().upper())
    return genes


def _list_count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _target_drug_rows(payload: dict) -> list[dict]:
    target_drugs = payload.get("target_drugs")
    rows = target_drugs.get("rows") if isinstance(target_drugs, dict) else []
    return rows if isinstance(rows, list) else []


def _target_drug_count(payload: dict) -> int:
    target_drugs = payload.get("target_drugs")
    if isinstance(target_drugs, dict) and isinstance(target_drugs.get("count"), int):
        return target_drugs["count"]
    return len(_target_drug_rows(payload))


def _compact_disease_evidence(entry: dict) -> dict:
    return {
        key: entry[key]
        for key in (
            "datasourceId",
            "datatypeId",
            "score",
            "studyId",
            "literature",
            "url",
            "targetId",
            "diseaseId",
        )
        if key in entry
    }


def _compact_association(entry: dict) -> dict:
    return {
        key: entry[key]
        for key in ("disease", "score", "datatypeScores", "evidenceCount")
        if key in entry
    }


def _compact_target_drug(entry: dict) -> dict:
    return {
        key: entry[key]
        for key in (
            "maxClinicalStage",
            "drug",
            "diseases",
            "mechanismOfAction",
            "target",
        )
        if key in entry
    }


def _compact_ot_payload(filename: str, payload: dict, top_n: int = _OT_COMPACT_TOP_N) -> dict:
    target_info = payload.get("target_info") if isinstance(payload.get("target_info"), dict) else {}
    disease_evidence = payload.get("disease_evidence")
    associations = payload.get("associations")
    target_drug_rows = _target_drug_rows(payload)
    errors = payload.get("errors")
    return {
        "_compact_schema": _OT_COMPACT_SCHEMA,
        "_source_file": f"evidence/{filename}",
        "_source_hash": canonical_json_hash(payload),
        "_original_token_estimate": _estimate_json_tokens(payload),
        "gene_symbol": payload.get("gene_symbol"),
        "disease": payload.get("disease"),
        "ensembl_id": payload.get("ensembl_id"),
        "target_identity": {
            "id": target_info.get("id"),
            "approvedSymbol": target_info.get("approvedSymbol"),
            "approvedName": target_info.get("approvedName"),
            "biotype": target_info.get("biotype"),
        },
        "counts": {
            "disease_evidence": _list_count(disease_evidence),
            "associations_loaded": _list_count(associations),
            "associations_total": payload.get("associations_total_count", _list_count(associations)),
            "target_drugs": _target_drug_count(payload),
            "target_drugs_loaded": len(target_drug_rows),
            "tractability": _list_count(target_info.get("tractability")),
            "safety_liabilities": _list_count(target_info.get("safetyLiabilities")),
            "errors": _list_count(errors),
        },
        "flags": {
            "executed": payload.get("executed"),
            "associations_truncated": payload.get("associations_truncated"),
            "disease_evidence_truncated": payload.get("disease_evidence_truncated"),
            "has_errors": bool(errors),
        },
        "top_disease_evidence": [
            _compact_disease_evidence(entry)
            for entry in (disease_evidence[:top_n] if isinstance(disease_evidence, list) else [])
            if isinstance(entry, dict)
        ],
        "top_associations": [
            _compact_association(entry)
            for entry in (associations[:top_n] if isinstance(associations, list) else [])
            if isinstance(entry, dict)
        ],
        "top_target_drugs": [
            _compact_target_drug(entry)
            for entry in target_drug_rows[:top_n]
            if isinstance(entry, dict)
        ],
        "provenance_source_fields_preserved": [
            "gene_symbol",
            "disease",
            "ensembl_id",
            "target_info",
            "disease_evidence",
            "associations",
            "target_drugs",
            "errors",
        ],
    }


def _compact_evidence_for_budget(
    evidence: dict,
    reference_card: dict,
    top_n: int = _OT_COMPACT_TOP_N,
) -> dict:
    compacted = copy.deepcopy(evidence)
    files = compacted.get("files")
    if not isinstance(files, dict):
        return compacted

    featured_genes = _featured_gene_set(reference_card)
    for filename, payload in list(files.items()):
        if not (
            isinstance(filename, str)
            and filename.startswith("ot_")
            and filename.endswith(".json")
            and isinstance(payload, dict)
        ):
            continue
        gene = filename.removeprefix("ot_").removesuffix(".json").strip().upper()
        if gene in featured_genes:
            continue
        files[filename] = _compact_ot_payload(filename, payload, top_n=top_n)
    return compacted


def _compact_evidence_if_needed(evidence: dict, reference_card: dict) -> tuple[dict, int]:
    token_estimate = _estimate_json_tokens(evidence)
    if token_estimate < int(_TOKEN_BUDGET * _COMPACTION_TRIGGER_RATIO):
        return evidence, token_estimate

    compacted = _compact_evidence_for_budget(evidence, reference_card)
    compacted_token_estimate = _estimate_json_tokens(compacted)
    if compacted_token_estimate >= token_estimate:
        return evidence, token_estimate

    logger.info(
        "compacted evidence payload: %d -> %d tokens",
        token_estimate,
        compacted_token_estimate,
    )
    return compacted, compacted_token_estimate


# ---------------------------------------------------------------------------
# Entry function (≤30 lines per plan §2.1 Decision 9)
# ---------------------------------------------------------------------------


async def finalize_report(state: dict, config: RunnableConfig) -> dict:
    """Production finalizer node. Returns a LangGraph state-update dict."""
    from src.agents.drug_target.deterministic_report import finalize_report_mvp

    return await finalize_report_mvp(state, config)


async def finalize_report_legacy(state: dict, config: RunnableConfig) -> dict:
    """Legacy report-expansion node (1 LLM call). Returns state-update dict."""
    data_dir: str = state["data_dir"]
    disease: str = state["disease"]
    _ok: dict = {"report_finalization_error": None, "evidence_truncated": False}
    # Always regenerate from current evidence. A prior-run drug.md must NOT
    # short-circuit finalization: on a reused workspace with different input
    # that would silently return stale results (and skip validation).
    evidence, spec, reference_card = _load_expansion_inputs(data_dir, disease)
    evidence, token_estimate = _compact_evidence_if_needed(evidence, reference_card)
    if token_estimate > _TOKEN_BUDGET:
        logger.warning("evidence budget exceeded: %d > %d", token_estimate, _TOKEN_BUDGET)
        return {"report_finalization_error": f"evidence_budget_exceeded: {token_estimate} > {_TOKEN_BUDGET}", "evidence_truncated": True}
    from src.agents.model import create_llm  # local import — mirrors agent.py:39
    model = create_llm(os.getenv("LLM_PROVIDER", "openrouter")).bind(temperature=0)
    payload, llm_error = _llm_fill_expansions_once(model, spec, evidence, reference_card, config)
    if payload is None:
        return {"report_finalization_error": f"llm_call_failed_after_retries: {llm_error}", "evidence_truncated": False}
    errors = _persist_and_validate(data_dir, payload, reference_card)
    if errors:
        return {"report_finalization_error": _classify_validation_error(errors), "evidence_truncated": False}
    _render_outputs(data_dir, payload)
    workspace_errors = _finalize_workspace(data_dir)
    if workspace_errors:
        reason = workspace_errors[0].get("reason", str(workspace_errors[0]))
        return {"report_finalization_error": f"finalization_validation_failed: {reason}", "evidence_truncated": False}
    return _ok


def _classify_validation_error(errors: list[dict]) -> str:
    """Map validation errors to their error-class string.

    cited_only errors win over schema errors — a hallucination signal is more
    actionable than a generic parse error even when both fire for the same key.
    """
    cited_errors = [e for e in errors if e.get("validator") == "cited_only"]
    if cited_errors:
        return f"cited_only_violation: {len(cited_errors)} errors; first={cited_errors[0]}"
    return f"validation_failed: {len(errors)} errors; first={errors[0]}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_expansion_inputs(data_dir: str, disease: str) -> tuple[dict, dict, dict]:  # noqa: ARG001
    """Step 1: load evidence, spec, and reference_card from data_dir.

    Args:
        data_dir: Workspace directory.
        disease: Disease context (unused here; injected for future use).

    Returns:
        (evidence_dict, spec_dict, reference_card_dict)
    """
    base = Path(data_dir).expanduser().resolve()

    # Build reference_card + spec from evidence on disk. Idempotent: rewrites
    # both files. With the summarizer subagent removed (Phase 3 task #8), this
    # Explicit legacy super-graph and traced compatibility callers invoke this
    # makes _load_expansion_inputs self-contained.
    _call_tool(
        _build_evidence_summary_st,
        data_dir=str(base),
        include_legacy_hypothesis=True,
    )

    # Evidence — load_evidence_files returns a JSON string
    raw_evidence = _call_tool(_load_evidence_files_st, data_dir=str(base))
    evidence: dict = json.loads(raw_evidence) if isinstance(raw_evidence, str) else raw_evidence

    # Reference card — written by build_evidence_summary → persist_drug_report_reference_card
    ref_path = base / _REFERENCE_CARD_FILE
    reference_card: dict = json.loads(ref_path.read_text(encoding="utf-8")) if ref_path.exists() else {}

    # Expansion schema spec — written alongside reference card
    spec_path = base / EXPANSION_SCHEMA_SPEC_FILE
    spec: dict = json.loads(spec_path.read_text(encoding="utf-8")) if spec_path.exists() else {}

    return evidence, spec, reference_card


def _llm_fill_expansions_once(
    model,
    spec: dict,
    evidence: dict,
    reference_card: dict,
    config: RunnableConfig,
) -> tuple[ReportExpansionsPayload | None, str | None]:
    """Step 2: single structured-output LLM call with 2-attempt retry.

    Returns (payload, None) on success, (None, error_repr) on failure.

    Catches: pydantic.ValidationError, OutputParserException, and
    provider-side LangChainException after with_retry exhausts attempts.
    """
    prompt = [
        SystemMessage(content=FINALIZE_REPORT_SYSTEM_PROMPT),
        HumanMessage(
            content=FINALIZE_REPORT_USER_TEMPLATE.format(
                spec_json=json.dumps(spec, ensure_ascii=False),
                reference_card_json=json.dumps(reference_card, ensure_ascii=False),
                evidence_summary_json=json.dumps(evidence, ensure_ascii=False),
            )
        ),
    ]
    chain = model.with_structured_output(ReportExpansionsPayload).with_retry(stop_after_attempt=2)
    try:
        payload: ReportExpansionsPayload = chain.invoke(prompt, config=config)
    except (ValidationError, OutputParserException, Exception) as exc:
        return None, repr(exc)

    # R4: schema_version post-fill (Decision 2 — unconditional)
    if payload.schema_version != "report_expansions.v1":
        logger.warning("R4: schema_version post-filled (was %r)", payload.schema_version)
        object.__setattr__(payload, "schema_version", "report_expansions.v1")

    return payload, None


def _persist_and_validate(
    data_dir: str,
    payload: ReportExpansionsPayload,
    reference_card: dict,
) -> list[dict]:
    """Step 3: schema validation + cited-only validation; atomic save on pass.

    Returns a combined errors list (empty = success). Each error dict has a
    ``validator`` key of ``"schema"`` or ``"cited_only"``.
    """
    # Host-side post-fill of source_value from reference_card. The LLM only
    # cites (source_file, source_field); the actual value is looked up here
    # so SOURCE_PROVENANCE_MISMATCH cannot fire from LLM placeholder values
    # (e.g. [0,1,2,...]). This avoids the JSON-schema impedance where
    # reference-card values can be list[dict] but our typed-union schema
    # only permits list[scalar].
    _post_fill_source_values_from_reference(payload, reference_card)

    # 3.a — schema validation. validate_report_expansions returns
    # (reference_card, errors) — its FIRST element is the reference card, NOT
    # the expansions. It also mutates `expansions_dict` in place (auto-derives
    # reference_card_hash), so we persist that same dict on success.
    expansions_dict = payload.model_dump()
    _, schema_errors = validate_report_expansions(
        data_dir=data_dir, expansions=expansions_dict
    )
    schema_errs = [{"validator": "schema", **e} for e in (schema_errors or [])]

    # 3.b — cited-only provenance validation
    cited_errs = [
        {"validator": "cited_only", **e}
        for e in validate_cited_only_provenance(payload, reference_card)
    ]

    errors = schema_errs + cited_errs
    if not errors:
        _call_tool(
            _save_report_expansions_st, data_dir=data_dir, expansions=expansions_dict
        )

    return errors


def _post_fill_source_values_from_reference(
    payload: ReportExpansionsPayload, reference_card: dict
) -> None:
    """Overwrite LLM-submitted source_value with reference_card lookup.

    The LLM cites ``(source_file, source_field)`` and ``claim_type`` but
    cannot reliably emit the actual reference-card value when it is a
    ``list[dict]`` — the JSON schema we expose to the provider only types
    list elements as scalars. Host-side post-fill resolves this by looking
    the value up from the reference card's provenance index before
    validation. The post-fill respects ``claim_type``:

    - ``direct_value``: source_value = raw reference value.
    - ``count``: source_value = ``len(ref_value)`` if list, else 0.
    - ``absence``: source_value = ``[]`` (an empty marker).

    Aligns with plan §2.1 Decision 10/11: LLM cites, host verifies +
    supplies the canonical value.
    """
    from src.agents.drug_target.tools.report_expansion_schema import (
        _build_provenance_index,
    )

    index = _build_provenance_index(reference_card)
    for slot in payload.slots:
        for sentence in slot.sentences:
            prov = sentence.source_provenance
            key = f"{prov.source_file}::{prov.source_field}"
            entry = index.get(key)
            if entry is None:
                continue
            ref_value = entry.get("source_value")
            if prov.claim_type == "count":
                prov.source_value = len(ref_value) if isinstance(ref_value, list) else 0
            elif prov.claim_type == "absence":
                prov.source_value = []
            else:  # direct_value (default)
                prov.source_value = ref_value


def _render_outputs(data_dir: str, payload: ReportExpansionsPayload) -> None:  # noqa: ARG001
    """Step 4: render drug.md and the HTML report.

    Both writes are atomic (the tools write internally). target_assessment.json
    is intentionally NOT written here: build_evidence_summary already produces
    it deterministically in the structured contract shape
    ({project_meta, druggability_matrix (with is_featured rows),
    featured_candidates_deep_dive}) that wrapper_agent's featured-pair
    extraction depends on. Overwriting it with payload.model_dump() (the
    report_expansions schema) would break that consumer; the expansions
    payload is persisted to report_expansions.json instead.
    """
    base = Path(data_dir).expanduser().resolve()

    # drug.md — tool writes it internally
    _call_tool(_render_drug_md_st, data_dir=str(base))

    # HTML report — tool writes it internally
    _call_tool(_generate_drug_html_st, data_dir=str(base))


def _finalize_workspace(data_dir: str) -> list[dict]:
    """Step 5: finalize stage1 artifacts and validate report finalization.

    Returns a list of error dicts (empty = success). Each dict has a
    ``validator`` key of ``"finalization"`` and a ``"reason"`` key.
    """
    # finalize_stage1_artifacts is the tool exported from tools/__init__.py
    # (maps to stage1_normalization.finalize_stage1_artifacts)
    _call_tool(_finalize_stage1_st, data_dir=data_dir)

    # validate_drug_report_finalization returns a JSON string
    raw = _call_tool(_validate_finalization_st, data_dir=data_dir)
    result: dict = json.loads(raw) if isinstance(raw, str) else raw

    if not result.get("valid", True):
        issues = result.get("issues", [])
        reason = issues[0].get("message", str(issues[0])) if issues else "unknown"
        return [{"validator": "finalization", "reason": reason}]

    return []

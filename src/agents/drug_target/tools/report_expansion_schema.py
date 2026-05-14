"""Structured report expansion schema and save tool."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

REFERENCE_CARD_VERSION = "drug_report_reference_card.v1"
REPORT_EXPANSIONS_VERSION = "report_expansions.v1"
EXPANSION_SCHEMA_SPEC_FILE = "expansion_schema_spec.json"
_EXPAND_RE = re.compile(r"<!--\s*EXPAND(?:_SLOT)?:\s*(.*?)\s*-->", re.DOTALL)


# =============================================================================
# Pydantic schema for `save_report_expansions(expansions=...)` (2026-05-14)
# =============================================================================
#
# The previous tool signature `expansions: dict` was opaque to LangChain's
# @tool auto-schema — LLMs received no advertised structure and had to
# reverse-engineer the deeply-nested payload from the offloaded reference
# card. Live-smoke runs against gpt-5.4 surfaced this as the dominant
# failure mode (sentences-empty, RENDER_SOURCE_HASH_MISMATCH oscillation).
#
# These Pydantic models advertise the *structural* shape via the tool
# description. Instance-specific valid values (concrete slot_ids and
# provenance keys for the active gene set) come from the companion
# discovery file ``expansion_schema_spec.json`` written by
# ``persist_drug_report_reference_card``.


class SourceProvenance(BaseModel):
    """Anchor for one factual sentence in the on-disk evidence."""

    source_file: str = Field(
        description=(
            "Evidence file path (e.g. 'evidence/ot_TGFB1.json'). Must be a "
            "key prefix from expansion_schema_spec.valid_provenance_keys."
        )
    )
    source_field: str = Field(
        description=(
            "JSON field within the source file (e.g. 'clinical_drugs'). "
            "The (source_file, source_field) pair must appear in "
            "expansion_schema_spec.valid_provenance_keys."
        )
    )
    source_class: str = Field(
        description=(
            "Provenance class, e.g. 'opentargets_clinical' or "
            "'chembl_preclinical'. Read this verbatim from the "
            "provenance_index entry — do not invent."
        )
    )
    claim_type: str = Field(
        default="direct_value",
        description=(
            "How the claim relates to the source value: 'direct_value' "
            "(value must equal the source), 'count' (value is len of the "
            "source), or 'absence' (source must be empty)."
        ),
    )
    source_value: Any = Field(
        default=None,
        description=(
            "The actual value pulled from the reference-card provenance "
            "index. For 'direct_value' it must match the index entry."
        ),
    )


class SentenceItem(BaseModel):
    """One factual sentence of narrative interpretation."""

    text: str = Field(description="One complete sentence.")
    source_fields: list[str] = Field(
        description=(
            "Field names this sentence cites. Use the same field name(s) "
            "you put in source_provenance.source_field."
        )
    )
    source_provenance: SourceProvenance = Field(
        description="Anchor to the reference-card provenance index."
    )


class SlotItem(BaseModel):
    """One expansion slot (a specific section/gene/rank location)."""

    slot_id: str = Field(
        description=(
            "Exactly one entry from "
            "expansion_schema_spec.required_slot_ids."
        )
    )
    sentences: list[SentenceItem] = Field(
        min_length=1,
        description=(
            "At least one SentenceItem. The full sentence schema is the "
            "shape advertised here and mirrored by "
            "expansion_schema_spec.example_sentence."
        ),
    )


class ReportExpansionsPayload(BaseModel):
    """Schema-validated payload for ``save_report_expansions``."""

    schema_version: Literal["report_expansions.v1"] = Field(
        default="report_expansions.v1",
        description="MUST be exactly 'report_expansions.v1'.",
    )
    reference_card_hash: str | None = Field(
        default=None,
        description=(
            "OPTIONAL — leave it unset. The tool auto-derives the hash "
            "from drug_report_reference_card.json on disk. Do NOT attempt "
            "to compute canonical-JSON SHA256 manually."
        ),
    )
    slots: list[SlotItem] = Field(
        description=(
            "One entry per required_slot_id from "
            "expansion_schema_spec.required_slot_ids."
        ),
    )


def canonical_json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_json_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_dumps(value).encode("utf-8")).hexdigest()


def _slug(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", text.strip().lower()).strip("_")
    return slug or "expansion"


def extract_expansion_slots(markdown_template: str) -> list[dict]:
    """Derive fallback slot ids from EXPAND markers when no context exists."""
    slots: list[dict] = []
    for idx, match in enumerate(_EXPAND_RE.finditer(markdown_template or ""), start=1):
        instruction = " ".join(match.group(1).split())
        slot = _slug(instruction)
        if slot.startswith("add_"):
            slot = slot[4:]
        if slot == "summary":
            slot = "add_summary"
        slots.append({
            "slot_id": f"section:executive_summary|slot:{slot}",
            "section": "executive_summary",
            "slot": slot,
            "instruction": instruction,
            "ordinal": idx,
        })
    return slots


def _slot_id(section: str, slot: str, *, gene: str | None = None, rank: int | None = None) -> str:
    parts = [f"section:{section}"]
    if gene:
        parts.append(f"gene:{gene.strip().upper()}")
    if rank is not None:
        parts.append(f"rank:{rank}")
    parts.append(f"slot:{slot}")
    return "|".join(parts)


def build_expansion_slots(reference_card: dict) -> list[dict]:
    """Build stable slot inventory from template order and Reference Card context."""
    explicit = reference_card.get("expansion_slots")
    if isinstance(explicit, list) and explicit:
        return explicit

    markers = extract_expansion_slots(reference_card.get("markdown_template", ""))
    genes = [
        str(gene).strip().upper()
        for gene in reference_card.get("stage3_candidates", [])
        if str(gene).strip()
    ]
    hypotheses = reference_card.get("hypothesis_data", {}).get("hypotheses", [])
    ranks = [
        int(h.get("rank"))
        for h in hypotheses
        if isinstance(h, dict) and str(h.get("rank", "")).isdigit()
    ]
    counters = {"drug": 0, "bio": 0, "rubric": 0, "hyp": 0}
    slots: list[dict] = []
    for marker in markers:
        instruction = str(marker.get("instruction", ""))
        low = instruction.lower()
        section = "executive_summary"
        slot = "add_summary"
        gene = None
        rank = None
        if "therapeutic opportunities" in low:
            slot = "therapeutic_opportunities"
        elif "overall scoring landscape" in low:
            section, slot = "druggability_matrix", "scoring_landscape"
        elif "l-r pairs passed" in low or "biological validation" in low:
            section, slot = "stage1_filter", "filter_interpretation"
        elif "what drugs exist" in low:
            section, slot = "featured_candidate", "drug_profile"
            gene = genes[counters["drug"]] if counters["drug"] < len(genes) else None
            counters["drug"] += 1
        elif "biological context" in low:
            section, slot = "featured_candidate", "biological_context"
            gene = genes[counters["bio"]] if counters["bio"] < len(genes) else None
            counters["bio"] += 1
        elif "therapeutic recommendation" in low:
            section, slot = "featured_candidate", "rubric_recommendation"
            gene = genes[counters["rubric"]] if counters["rubric"] < len(genes) else None
            counters["rubric"] += 1
        elif "hypothesis generation" in low or "key themes" in low:
            section, slot = "hypothesis_summary", "themes"
        elif "therapeutic implications" in low:
            section, slot = "hypothesis", "therapeutic_implications"
            rank = ranks[counters["hyp"]] if counters["hyp"] < len(ranks) else counters["hyp"] + 1
            counters["hyp"] += 1
        elif "recommendations" in low or "next steps" in low:
            section, slot = "summary", "recommendations"
        slots.append({
            "slot_id": _slot_id(section, slot, gene=gene, rank=rank),
            "section": section,
            "slot": slot,
            "gene": gene,
            "rank": rank,
            "instruction": instruction,
            "ordinal": marker.get("ordinal"),
        })
    return slots


def _build_provenance_index(reference_card: dict) -> dict:
    index: dict[str, dict] = {}
    for card in reference_card.get("featured_genes", []) or []:
        if not isinstance(card, dict):
            continue
        gene = str(card.get("gene") or "").upper()
        stage3 = card.get("stage3")
        if not gene or not isinstance(stage3, dict):
            continue
        for field, source_file, source_class in (
            ("clinical_drugs", f"evidence/ot_{gene}.json", "opentargets_clinical"),
            (
                "preclinical_compounds",
                f"evidence/stage3_{gene}.json",
                "chembl_preclinical",
            ),
        ):
            index[f"{source_file}::{field}"] = {
                "source_file": source_file,
                "source_field": field,
                "source_class": source_class,
                "source_value": stage3.get(field, []),
            }
    return index


def build_expansion_schema_spec(reference_card: dict) -> dict:
    """Build a compact schema-discovery payload from the reference card.

    The summarizer LLM reads this file (separate from the large reference
    card) to learn the run-specific slot IDs and one concrete sentence
    example pinned to a real provenance entry. Keeping the spec in its own
    small file ensures it stays inside the deepagents FilesystemMiddleware
    inline-result window and never gets offloaded.
    """
    expansion_slots = reference_card.get("expansion_slots", []) or []
    provenance_index = reference_card.get("provenance_index", {}) or {}

    required_slot_ids = [
        str(slot["slot_id"])
        for slot in expansion_slots
        if isinstance(slot, dict) and slot.get("slot_id")
    ]
    valid_provenance_keys = sorted(provenance_index.keys())

    # Anchor the example sentence to a real provenance entry when available
    # so the LLM has a copy-paste-ready template that already validates.
    if valid_provenance_keys:
        first_key = valid_provenance_keys[0]
        entry = provenance_index.get(first_key, {}) if isinstance(
            provenance_index.get(first_key), dict
        ) else {}
        example_source_file = str(entry.get("source_file") or "")
        example_source_field = str(entry.get("source_field") or "")
        example_source_class = str(entry.get("source_class") or "")
        example_source_value = entry.get("source_value")
    else:
        example_source_file = "evidence/<file>.json"
        example_source_field = "<field>"
        example_source_class = "<source_class>"
        example_source_value = None

    example_sentence = {
        "text": (
            f"Replace this with one factual sentence interpreting "
            f"{example_source_field} from {example_source_file}."
        ),
        "source_fields": [example_source_field],
        "source_provenance": {
            "source_file": example_source_file,
            "source_field": example_source_field,
            "source_class": example_source_class,
            "claim_type": "direct_value",
            "source_value": example_source_value,
        },
    }

    return {
        "schema_version": REPORT_EXPANSIONS_VERSION,
        "instruction": (
            "Author one SlotItem per required_slot_id. Each SlotItem has a "
            "non-empty sentences list. Each sentence has the shape shown in "
            "example_sentence, with source_provenance keyed on a valid "
            "(source_file, source_field) pair from valid_provenance_keys. "
            "Do not invent source_file or source_field values that are not "
            "in this list. Omit reference_card_hash from your payload — "
            "save_report_expansions auto-derives it from disk."
        ),
        "required_slot_ids": required_slot_ids,
        "example_sentence": example_sentence,
        "valid_provenance_keys": valid_provenance_keys,
    }


def persist_drug_report_reference_card(data_dir: str | Path, reference_card: dict) -> dict:
    """Persist the canonical Reference Card used by report rendering.

    Also writes the compact ``expansion_schema_spec.json`` next to the
    reference card so the summarizer LLM can discover run-specific slot
    IDs and the provenance shape without parsing the large reference card.
    """
    base = Path(data_dir).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    card = dict(reference_card)
    card["schema_version"] = REFERENCE_CARD_VERSION
    card["expansion_slots"] = build_expansion_slots(card)
    if not isinstance(card.get("provenance_index"), dict):
        card["provenance_index"] = _build_provenance_index(card)
    path = base / "drug_report_reference_card.json"
    path.write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")

    spec = build_expansion_schema_spec(card)
    spec_path = base / EXPANSION_SCHEMA_SPEC_FILE
    spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    return card


def _is_empty_source_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _provenance_error(sentence: dict, provenance_index: dict | None = None) -> dict | None:
    prov = sentence.get("source_provenance")
    if not isinstance(prov, dict):
        return {
            "code": "SOURCE_PROVENANCE_MISSING",
            "message": "factual expansion sentence requires source_provenance",
        }
    source_file = str(prov.get("source_file") or "")
    source_field = str(prov.get("source_field") or "")
    source_class = str(prov.get("source_class") or "")
    claim_type = str(prov.get("claim_type") or "")
    source_value = prov.get("source_value")
    actual = None
    if isinstance(provenance_index, dict):
        actual = provenance_index.get(f"{source_file}::{source_field}")
    if not isinstance(actual, dict):
        return {
            "code": "SOURCE_PROVENANCE_MISSING",
            "message": "source file/field is absent from reference-card provenance index",
            "source_file": source_file,
            "source_field": source_field,
        }

    source_value = actual.get("source_value")
    expected_class = actual.get("source_class")
    if expected_class and source_class != expected_class:
        return {
            "code": "SOURCE_PROVENANCE_MISMATCH",
            "message": "submitted source_class differs from reference-card provenance index",
            "source_file": source_file,
            "source_class": source_class,
            "expected_source_class": expected_class,
        }

    if claim_type == "absence" and not _is_empty_source_value(source_value):
        return {
            "code": "FALSE_ABSENCE_CLAIM",
            "message": "absence claim cites a non-empty source value",
            "source_file": source_file,
            "source_field": source_field,
        }
    if claim_type == "count":
        expected_count = len(source_value) if isinstance(source_value, (list, dict, str)) else source_value
        submitted = prov.get("source_value")
        if submitted != expected_count:
            return {
                "code": "SOURCE_PROVENANCE_MISMATCH",
                "message": "count claim does not match reference-card source value",
                "source_file": source_file,
                "source_field": source_field,
                "expected_count": expected_count,
                "submitted_count": submitted,
            }
    elif claim_type == "direct_value":
        submitted = prov.get("source_value")
        if submitted != source_value:
            return {
                "code": "SOURCE_PROVENANCE_MISMATCH",
                "message": "direct-value claim does not match reference-card source value",
                "source_file": source_file,
                "source_field": source_field,
                "expected_value": source_value,
                "submitted_value": submitted,
            }
    if source_file.startswith("evidence/stage3_") and "preclinical" in source_field:
        if source_class != "chembl_preclinical":
            return {
                "code": "SOURCE_PROVENANCE_MISMATCH",
                "message": "stage3 preclinical fields must use chembl_preclinical provenance",
                "source_file": source_file,
                "source_class": source_class,
            }
    if source_file.startswith("evidence/ot_") and source_class == "chembl_preclinical":
        return {
            "code": "SOURCE_PROVENANCE_MISMATCH",
            "message": "OpenTargets files cannot be cited as ChEMBL preclinical provenance",
            "source_file": source_file,
            "source_class": source_class,
        }
    return None


def validate_report_expansions(data_dir: str | Path, expansions: dict) -> tuple[dict | None, list[dict]]:
    base = Path(data_dir).expanduser().resolve()
    ref_path = base / "drug_report_reference_card.json"
    errors: list[dict] = []
    if not ref_path.exists():
        return None, [{
            "code": "MISSING_REFERENCE_CARD",
            "message": "drug_report_reference_card.json is required",
        }]
    reference_card = json.loads(ref_path.read_text(encoding="utf-8"))
    required_slots = [
        str(slot.get("slot_id"))
        for slot in reference_card.get("expansion_slots", [])
        if isinstance(slot, dict) and slot.get("slot_id")
    ]
    if not required_slots:
        required_slots = [slot["slot_id"] for slot in build_expansion_slots(reference_card)]
    if expansions.get("schema_version") != REPORT_EXPANSIONS_VERSION:
        errors.append({
            "code": "REPORT_EXPANSIONS_INVALID",
            "message": "schema_version must be report_expansions.v1",
        })
    # `reference_card_hash` is OPTIONAL on the input payload. When the LLM
    # omits it (the recommended path — the post-2026-05-13 SUMMARIZER_PROMPT
    # tells callers not to invent a SHA256), auto-derive it from the on-disk
    # reference card. When the caller does supply a hash, validate the
    # match strictly and surface both values for one-turn self-correction.
    # Mutating ``expansions`` in place is intentional: the caller persists
    # the result to ``report_expansions.json`` so the on-disk payload stays
    # self-describing.
    expected_hash = canonical_json_hash(reference_card)
    supplied_hash = expansions.get("reference_card_hash")
    if supplied_hash is None:
        expansions["reference_card_hash"] = expected_hash
    elif supplied_hash != expected_hash:
        errors.append({
            "code": "RENDER_SOURCE_HASH_MISMATCH",
            "message": "reference_card_hash does not match drug_report_reference_card.json",
            "expected": expected_hash,
            "supplied": supplied_hash,
        })

    slots = expansions.get("slots")
    if not isinstance(slots, list):
        slots = []
        errors.append({
            "code": "REPORT_EXPANSIONS_INVALID",
            "message": "slots must be a list",
        })
    seen: dict[str, int] = {}
    for slot in slots:
        slot_id = str(slot.get("slot_id") if isinstance(slot, dict) else "")
        seen[slot_id] = seen.get(slot_id, 0) + 1
        if slot_id not in required_slots:
            errors.append({
                "code": "REPORT_EXPANSIONS_INVALID",
                "message": f"unknown slot_id: {slot_id}",
            })
            continue
        sentences = slot.get("sentences") if isinstance(slot, dict) else None
        if not isinstance(sentences, list) or not sentences:
            errors.append({
                "code": "REPORT_EXPANSIONS_INVALID",
                "message": (
                    f"{slot_id} must include at least one sentence — each "
                    "sentence is {text: str, source_fields: list[str], "
                    "source_provenance: {source_file, source_field, "
                    "source_class, claim_type, source_value}}. See "
                    f"{EXPANSION_SCHEMA_SPEC_FILE}.example_sentence."
                ),
            })
            continue
        for sentence in sentences:
            if not isinstance(sentence, dict):
                errors.append({
                    "code": "REPORT_EXPANSIONS_INVALID",
                    "message": f"{slot_id} sentence must be an object",
                })
                continue
            if not sentence.get("source_fields"):
                errors.append({
                    "code": "SOURCE_PROVENANCE_MISSING",
                    "message": f"{slot_id} sentence must include source_fields",
                })
            prov_error = _provenance_error(
                sentence,
                reference_card.get("provenance_index"),
            )
            if prov_error:
                errors.append(prov_error)

    missing = sorted(set(required_slots) - set(seen))
    extra_duplicates = sorted(slot_id for slot_id, count in seen.items() if count > 1)
    for slot_id in missing:
        errors.append({
            "code": "REPORT_EXPANSIONS_INVALID",
            "message": f"missing required slot_id: {slot_id}",
        })
    for slot_id in extra_duplicates:
        errors.append({
            "code": "REPORT_EXPANSIONS_INVALID",
            "message": f"duplicate slot_id: {slot_id}",
        })

    return reference_card, errors


@tool
def save_report_expansions(
    data_dir: str,
    expansions: ReportExpansionsPayload,
) -> str:
    """Validate and persist ``report_expansions.json``.

    Authors per-section Markdown expansions for the drug-target report.
    The ``expansions`` payload is structurally validated by Pydantic
    against the model advertised in this tool's args_schema; instance-
    specific values (legal slot_ids, legal provenance keys) come from
    ``<data_dir>/expansion_schema_spec.json`` (created by
    ``build_evidence_summary``).

    Args:
        data_dir: Run working directory.
        expansions: ReportExpansionsPayload with schema_version, optional
            reference_card_hash (auto-derived if omitted), and a slots
            list. Each slot has a slot_id (from
            expansion_schema_spec.required_slot_ids) and a non-empty
            sentences list. Each sentence has text + source_fields +
            source_provenance (source_file, source_field, source_class,
            claim_type, source_value) — pin every provenance to a key in
            expansion_schema_spec.valid_provenance_keys.

    Returns:
        JSON string with shape
        ``{"saved": bool, "path": "...", "errors": [...]}``. When
        ``saved`` is True the file at ``path`` mirrors the validated
        payload (with the auto-derived reference_card_hash filled in).
    """
    base = Path(data_dir).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    # ``expansions`` may arrive as a Pydantic instance (LangChain tool
    # invocation) or as a raw dict (direct .invoke({"expansions": {...}})
    # call from tests / scripts). Normalize to a mutable dict so the
    # existing in-place hash auto-derive in validate_report_expansions
    # carries through to the persisted JSON.
    if isinstance(expansions, BaseModel):
        expansions_dict = expansions.model_dump()
    else:
        expansions_dict = dict(expansions)
    _, errors = validate_report_expansions(base, expansions_dict)
    result = {
        "saved": False,
        "path": str(base / "report_expansions.json"),
        "errors": errors,
    }
    if errors:
        return json.dumps(result, indent=2)
    (base / "report_expansions.json").write_text(
        json.dumps(expansions_dict, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    result["saved"] = True
    return json.dumps(result, indent=2)

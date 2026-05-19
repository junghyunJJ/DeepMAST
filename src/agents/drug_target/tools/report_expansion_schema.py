"""Structured report expansion schema and save tool."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

REFERENCE_CARD_VERSION = "drug_report_reference_card.v1"
REPORT_EXPANSIONS_VERSION = "report_expansions.v1"
EXPANSION_SCHEMA_SPEC_FILE = "expansion_schema_spec.json"
_EXPAND_RE = re.compile(r"<!--\s*EXPAND(?:_SLOT)?:\s*(.*?)\s*-->", re.DOTALL)
_SOURCE_TAG_RE = re.compile(r"\[source:\s*([^\]]+)\]", re.IGNORECASE)
_AMBIGUOUS_SOURCE_TAG_FIELDS = {
    "clinical_drugs",
    "preclinical_compounds",
    "matched_drugs",
    "indications",
}


# ---------------------------------------------------------------------------
# Path-traversal guard for tool ``data_dir`` arguments (PR #19 round 7 — DS-1)
#
# ``save_report_expansions`` and ``lookup_provenance_value`` accept a
# ``data_dir`` value that originates in LLM-controlled tool arguments. The
# round-7 code review (DS-1, HIGH) flagged this as a path-traversal surface
# because:
#   - ``save_report_expansions`` calls ``base.mkdir(parents=True,
#     exist_ok=True)`` and then writes ``report_expansions.json`` — an
#     attacker-controlled LLM message could place files outside the run
#     workspace.
#   - ``lookup_provenance_value`` reads ``drug_report_reference_card.json``
#     under the supplied path — a probing path can leak file existence
#     elsewhere on the host.
#
# The guard validates the resolved path against an allowlist of runtime
# workspace roots. By default it accepts paths under the OS temp directory
# (covers pytest's ``tmp_path`` fixture and the production
# ``/tmp/deep_interpreter_workspace`` fallback) plus any environment-
# configured workspace roots (``DRUG_TARGET_DATA_DIR``,
# ``DEEP_INTERPRETER_DATA_DIR``, or the colon-separated explicit override
# ``DRUG_TARGET_ALLOWED_DATA_DIRS``). Out-of-bounds paths produce a
# structured error envelope; ``base.mkdir(...)`` runs only after validation
# succeeds.
# ---------------------------------------------------------------------------

_PRODUCTION_WORKSPACE_FALLBACK = "/tmp/deep_interpreter_workspace"


def _default_allowed_data_roots() -> list[Path]:
    """Build the default allowed_roots list for ``_validate_data_dir``.

    Order is irrelevant for the membership check but the assembled list is
    surfaced in error payloads to help debug rejected paths.
    """
    roots: list[Path] = []
    # OS-level temp dir — covers pytest ``tmp_path`` on macOS and Linux.
    try:
        roots.append(Path(tempfile.gettempdir()).resolve())
    except (OSError, RuntimeError):
        pass
    for env_key in ("DRUG_TARGET_DATA_DIR", "DEEP_INTERPRETER_DATA_DIR"):
        val = os.getenv(env_key)
        if not val:
            continue
        try:
            roots.append(Path(val).expanduser().resolve())
        except (OSError, RuntimeError):
            continue
    override = os.getenv("DRUG_TARGET_ALLOWED_DATA_DIRS")
    if override:
        for part in override.split(os.pathsep):
            part = part.strip()
            if not part:
                continue
            try:
                roots.append(Path(part).expanduser().resolve())
            except (OSError, RuntimeError):
                continue
    try:
        roots.append(Path(_PRODUCTION_WORKSPACE_FALLBACK).resolve())
    except (OSError, RuntimeError):
        pass
    return roots


def _validate_data_dir(
    data_dir: str | Path,
    allowed_roots: list[str | Path] | None = None,
) -> tuple[Path | None, dict | None]:
    """Resolve ``data_dir`` and confirm it falls under an allowed root.

    Returns ``(resolved_path, None)`` on success and ``(None, error_dict)``
    on rejection. Callers must NOT create directories before calling this
    function — out-of-bounds ``mkdir`` is the defect we are closing.
    """
    if allowed_roots is None:
        roots = _default_allowed_data_roots()
    else:
        roots = []
        for raw in allowed_roots:
            try:
                roots.append(Path(raw).expanduser().resolve())
            except (OSError, RuntimeError):
                continue
    if not roots:
        return None, {
            "code": "DATA_DIR_NO_ALLOWED_ROOTS",
            "message": (
                "no allowed workspace roots are configured; set "
                "DRUG_TARGET_DATA_DIR, DEEP_INTERPRETER_DATA_DIR, or "
                "DRUG_TARGET_ALLOWED_DATA_DIRS"
            ),
        }
    try:
        resolved = Path(data_dir).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        return None, {
            "code": "DATA_DIR_INVALID",
            "message": f"data_dir could not be resolved: {exc}",
            "data_dir": str(data_dir),
        }
    for root in roots:
        try:
            resolved.relative_to(root)
            return resolved, None
        except ValueError:
            continue
    return None, {
        "code": "DATA_DIR_OUT_OF_BOUNDS",
        "message": (
            "data_dir is not under any allowed workspace root. Set "
            "DRUG_TARGET_DATA_DIR / DEEP_INTERPRETER_DATA_DIR to the run "
            "directory, or pass a path under the OS temp dir or "
            f"{_PRODUCTION_WORKSPACE_FALLBACK}."
        ),
        "data_dir": str(data_dir),
        "resolved": str(resolved),
        "allowed_roots": [str(r) for r in roots],
    }


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
    fallback_quality: str | None = Field(
        default=None,
        description=(
            "Optional host-recovery marker. Set to 'degraded' only when a "
            "deterministic recovery path could not match the sentence to a "
            "slot-specific provenance entry."
        ),
    )
    fallback_reason: str | None = Field(
        default=None,
        description="Optional reason for fallback_quality='degraded'.",
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
    seen_slot_ids: set[str] = set()
    for marker in markers:
        instruction = str(marker.get("instruction", ""))
        low = instruction.lower()
        section = "executive_summary"
        slot = "add_summary"
        gene = None
        rank = None
        # Issue #21: test specific per-card / per-hypothesis phrases BEFORE
        # broader section-level phrases. The drug-profile marker's
        # instruction text contains "therapeutic opportunities" as a
        # *negative* constraint ("Do NOT speculate about ... therapeutic
        # opportunities ..."), so the broad executive-summary branch must
        # come last among the substring tests it could otherwise absorb.
        if "what drugs exist" in low:
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
        elif "therapeutic implications" in low:
            section, slot = "hypothesis", "therapeutic_implications"
            rank = ranks[counters["hyp"]] if counters["hyp"] < len(ranks) else counters["hyp"] + 1
            counters["hyp"] += 1
        elif "therapeutic opportunities" in low:
            slot = "therapeutic_opportunities"
        elif "overall scoring landscape" in low:
            section, slot = "druggability_matrix", "scoring_landscape"
        elif "l-r pairs passed" in low or "biological validation" in low:
            section, slot = "stage1_filter", "filter_interpretation"
        elif "hypothesis generation" in low or "key themes" in low:
            section, slot = "hypothesis_summary", "themes"
        elif "recommendations" in low or "next steps" in low:
            section, slot = "summary", "recommendations"
        slot_id = _slot_id(section, slot, gene=gene, rank=rank)
        # Fail loud on duplicate construction (issue #21, fix option 3).
        # A duplicate at this point means either (a) the substring chain
        # mapped two semantically distinct markers to the same category,
        # or (b) the template contains literally repeated EXPAND markers.
        # Either way the silent producer-loss class of bug — where
        # ``validate_report_expansions`` only checks for duplicates in
        # the *submitted* payload, not the *required* list — must surface
        # at construction time, not after the live LLM has dropped prose.
        if slot_id in seen_slot_ids:
            raise ValueError(
                f"build_expansion_slots produced duplicate slot_id: "
                f"{slot_id!r}. Inspect the EXPAND marker classification "
                f"chain — a more-specific phrase match must precede the "
                f"broader one that absorbed this marker. Triggering "
                f"instruction: {instruction!r}"
            )
        seen_slot_ids.add(slot_id)
        slots.append({
            "slot_id": slot_id,
            "section": section,
            "slot": slot,
            "gene": gene,
            "rank": rank,
            "instruction": instruction,
            "ordinal": marker.get("ordinal"),
        })
    return slots


# Rubric fields admitted as first-class provenance citations (Issue #22).
# These match the keys built by ``rubric_by_gene`` in
# ``stage_logic.py:2014-2030``. Each (gene, rubric_field) pair becomes its
# own index key ``evidence/assessment_results.json::<GENE>::<field>`` with
# a scalar ``source_value``. The per-gene key shape (gene embedded in
# ``source_field``) preserves byte-equality of ``direct_value`` claims and
# blocks wrong-gene hallucinations at the key level.
RUBRIC_FIELDS: tuple[str, ...] = (
    "classification",
    "priority",
    "validated_total",
    "exploratory_total",
    "combined_total",
    "existing_drug_evidence",
    "clinical_trial_activity",
    "safety_profile",
    "gwas_support",
    "tractability",
    "biological_plausibility",
    "novelty_opportunity",
    "stage3_candidate",
)
RUBRIC_SOURCE_FILE = "evidence/assessment_results.json"
RUBRIC_SOURCE_CLASS = "deepmast_rubric"


def _build_provenance_index(reference_card: dict) -> dict:
    """Build the provenance index used by ``_provenance_error``.

    Two passes:
      1. Per-gene drug-evidence entries (existing shape, unchanged):
         ``evidence/ot_<GENE>.json::clinical_drugs`` and
         ``evidence/stage3_<GENE>.json::preclinical_compounds``.
      2. Per-gene rubric entries — each ``(gene, rubric_field)`` pair gets
         its own key ``evidence/assessment_results.json::<GENE>::<field>``
         with a scalar ``source_value``. This satisfies the validator's
         byte-equality check (``_provenance_error`` ~line 567) without
         modifying validator code, and each gene's score is gated by its
         own key — fabricated gene segments produce ``None`` at lookup.
    """
    index: dict[str, dict] = {}
    for card in reference_card.get("featured_genes", []) or []:
        if not isinstance(card, dict):
            continue
        gene = str(card.get("gene") or "").upper()
        if not gene:
            continue

        # Pass 1: drug-evidence entries (shape unchanged).
        stage3 = card.get("stage3")
        if isinstance(stage3, dict):
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

        # Pass 2: rubric entries — per-gene, per-field, scalar value.
        rubric = card.get("rubric")
        if not isinstance(rubric, dict):
            continue
        for field in RUBRIC_FIELDS:
            if field not in rubric:
                continue
            source_field = f"{gene}::{field}"
            index[f"{RUBRIC_SOURCE_FILE}::{source_field}"] = {
                "source_file": RUBRIC_SOURCE_FILE,
                "source_field": source_field,
                "source_class": RUBRIC_SOURCE_CLASS,
                "source_value": rubric[field],
            }
    return index


def _pick_example_key(keys: list[str]) -> str | None:
    """Pick the example_sentence anchor for ``build_expansion_schema_spec``.

    Prefer a drug-evidence key (``evidence/ot_*`` or ``evidence/stage3_*``)
    over a rubric key so the example sentence preserves the existing
    drug-citation behavioral anchor for all models. Rubric keys sort
    alphabetically BEFORE drug keys, so plain ``sorted()[0]`` would shift
    the anchor; this helper restores the original ordering bias.
    """
    for key in keys:
        if key.startswith("evidence/ot_") or key.startswith("evidence/stage3_"):
            return key
    return keys[0] if keys else None


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
        first_key = _pick_example_key(valid_provenance_keys)
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


def _source_tag_error(sentence: dict) -> dict | None:
    text = str(sentence.get("text") or "")
    tags = _SOURCE_TAG_RE.findall(text)
    if not tags:
        return None
    prov = sentence.get("source_provenance")
    if not isinstance(prov, dict):
        return None
    source_field = str(prov.get("source_field") or "")
    field_leaf = source_field.rsplit("::", 1)[-1].rsplit(".", 1)[-1].casefold()
    source_class = str(prov.get("source_class") or "").casefold()
    if not source_class:
        return None
    matched_expected = False
    for tag in tags:
        labels = [part.strip() for part in tag.split(",")]
        for label in labels:
            if not label:
                continue
            label_cf = label.casefold()
            if ":" in label_cf:
                tag_source_class, tag_source_field = label_cf.split(":", 1)
            else:
                tag_source_class, tag_source_field = "", label_cf
            tag_field_leaf = tag_source_field.rsplit("::", 1)[-1].rsplit(".", 1)[-1]
            is_ambiguous_tag = tag_field_leaf in _AMBIGUOUS_SOURCE_TAG_FIELDS
            is_ambiguous_source = field_leaf in _AMBIGUOUS_SOURCE_TAG_FIELDS
            if not is_ambiguous_tag and not is_ambiguous_source:
                continue
            if not tag_source_class:
                return {
                    "code": "SOURCE_TAG_TOO_GENERIC",
                    "message": (
                        "source tag for ambiguous drug evidence must include source_class "
                        "to distinguish OpenTargets clinical from ChEMBL preclinical fields"
                    ),
                    "source_field": source_field,
                    "source_class": prov.get("source_class"),
                    "submitted_tag": label,
                    "expected": f"{prov.get('source_class')}:{field_leaf}",
                }
            if tag_source_class != source_class or tag_field_leaf != field_leaf:
                return {
                    "code": "SOURCE_TAG_PROVENANCE_MISMATCH",
                    "message": (
                        "source tag class/field does not match sentence source_provenance"
                    ),
                    "source_field": source_field,
                    "source_class": prov.get("source_class"),
                    "submitted_tag": label,
                    "expected": f"{prov.get('source_class')}:{field_leaf}",
                }
            matched_expected = True
    if field_leaf in _AMBIGUOUS_SOURCE_TAG_FIELDS and not matched_expected:
        return {
            "code": "SOURCE_TAG_PROVENANCE_MISMATCH",
            "message": (
                "ambiguous drug evidence source tag must cite the same "
                "source_class and source_field as source_provenance"
            ),
            "source_field": source_field,
            "source_class": prov.get("source_class"),
            "expected": f"{prov.get('source_class')}:{field_leaf}",
        }
    return None


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
            tag_error = _source_tag_error(sentence)
            if tag_error:
                errors.append(tag_error)

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
    # Path-traversal guard (DS-1). MUST run BEFORE ``base.mkdir(...)`` —
    # the defect we are closing is "mkdir on an LLM-controlled path".
    base, guard_error = _validate_data_dir(data_dir)
    if guard_error is not None or base is None:
        return json.dumps(
            {
                "saved": False,
                "path": None,
                "errors": [guard_error] if guard_error else [],
            },
            indent=2,
        )
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


@tool
def lookup_provenance_value(
    data_dir: str,
    source_file: str,
    source_field: str,
) -> str:
    """Look up the canonical source_value for a (source_file, source_field) pair.

    Reads ``<data_dir>/drug_report_reference_card.json`` and returns the
    matching entry from the ``provenance_index``. Use this tool when
    authoring sentences for ``save_report_expansions`` so that the
    ``source_provenance.source_value`` field is anchored to the exact
    value indexed on disk — the validator requires byte-equality (for
    ``direct_value`` claims) or length-equality (for ``count`` claims),
    and live-smoke evidence (PR #19 round 5) showed gpt-5.4 cannot
    reliably transcribe nested object values from the offloaded
    reference card. Always call this tool for each citation BEFORE
    composing the sentence; copy the returned ``source_value`` verbatim
    into your ``source_provenance.source_value`` field.

    Args:
        data_dir: Run working directory containing
            ``drug_report_reference_card.json``.
        source_file: Evidence file path, e.g. ``"evidence/ot_TGFB1.json"``.
        source_field: JSON field within that file, e.g.
            ``"clinical_drugs"``. The (source_file, source_field) pair
            must appear in ``valid_provenance_keys`` from
            ``expansion_schema_spec.json``.

    Returns:
        JSON string. On hit:
            ``{"ok": true, "source_file": ..., "source_field": ...,
               "source_class": ..., "source_value": <verbatim>}``
        On miss the ``valid_provenance_keys`` list is included so the
        caller can recover:
            ``{"ok": false, "error": "...", "valid_provenance_keys": [...]}``
    """
    # Path-traversal guard (DS-1). Reject probing paths before any disk
    # access so an attacker-controlled value cannot leak file-existence
    # information from outside the runtime workspace.
    base, guard_error = _validate_data_dir(data_dir)
    if guard_error is not None or base is None:
        payload: dict[str, Any] = {"ok": False}
        if guard_error:
            payload.update(guard_error)
            payload.setdefault("error", guard_error.get("message", "invalid data_dir"))
        return json.dumps(payload, indent=2)
    ref_path = base / "drug_report_reference_card.json"
    if not ref_path.exists():
        return json.dumps(
            {
                "ok": False,
                "error": (
                    "drug_report_reference_card.json not found at "
                    f"{ref_path} — call build_evidence_summary first."
                ),
            },
            indent=2,
        )
    try:
        card = json.loads(ref_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return json.dumps(
            {"ok": False, "error": f"failed to load reference card: {exc}"},
            indent=2,
        )

    index = card.get("provenance_index")
    if not isinstance(index, dict):
        return json.dumps(
            {
                "ok": False,
                "error": "reference card has no provenance_index",
            },
            indent=2,
        )

    key = f"{source_file}::{source_field}"
    entry = index.get(key)
    if not isinstance(entry, dict):
        return json.dumps(
            {
                "ok": False,
                "error": (
                    f"({source_file}, {source_field}) not in "
                    "provenance_index — pick a key from "
                    "valid_provenance_keys."
                ),
                "valid_provenance_keys": sorted(index.keys()),
            },
            indent=2,
        )

    return json.dumps(
        {
            "ok": True,
            "source_file": str(entry.get("source_file") or source_file),
            "source_field": str(entry.get("source_field") or source_field),
            "source_class": str(entry.get("source_class") or ""),
            "source_value": entry.get("source_value"),
        },
        indent=2,
        ensure_ascii=False,
    )

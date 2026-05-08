"""Structured report expansion schema and save tool."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

REFERENCE_CARD_VERSION = "drug_report_reference_card.v1"
REPORT_EXPANSIONS_VERSION = "report_expansions.v1"
_EXPAND_RE = re.compile(r"<!--\s*EXPAND(?:_SLOT)?:\s*(.*?)\s*-->", re.DOTALL)


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
        if "what drugs exist" in low:
            section, slot = "featured_candidate", "drug_profile"
            gene = genes[counters["drug"]] if counters["drug"] < len(genes) else None
            counters["drug"] += 1
        elif "therapeutic opportunities" in low:
            slot = "therapeutic_opportunities"
        elif "overall scoring landscape" in low:
            section, slot = "druggability_matrix", "scoring_landscape"
        elif "l-r pairs passed" in low or "biological validation" in low:
            section, slot = "stage1_filter", "filter_interpretation"
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

    rubric_values: dict[str, dict[str, Any]] = {}
    for card in reference_card.get("featured_genes", []) or []:
        if not isinstance(card, dict):
            continue
        gene = str(card.get("gene") or "").upper()
        rubric = card.get("rubric")
        if not gene or not isinstance(rubric, dict):
            continue
        for field, value in rubric.items():
            rubric_values.setdefault(str(field), {})[gene] = value
    for row in reference_card.get("all_genes_druggability", []) or []:
        if not isinstance(row, dict):
            continue
        gene = str(row.get("gene") or "").upper()
        if not gene:
            continue
        for field, value in row.items():
            if field == "gene":
                continue
            rubric_values.setdefault(str(field), {}).setdefault(gene, value)
    for field, values in rubric_values.items():
        index[f"drug_report_reference_card.json::{field}"] = {
            "source_file": "drug_report_reference_card.json",
            "source_field": field,
            "source_class": "reference_card",
            "source_value": values,
        }

    for field in (
        "stage3_candidates",
        "stage1_filter_results",
        "hypothesis_data",
        "known_drugs_disease_level",
        "data_limitations",
    ):
        if field in reference_card:
            index[f"drug_report_reference_card.json::{field}"] = {
                "source_file": "drug_report_reference_card.json",
                "source_field": field,
                "source_class": "reference_card",
                "source_value": reference_card.get(field),
            }

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


def _source_field_candidates(source_fields: Any) -> list[str]:
    if isinstance(source_fields, str):
        fields = [source_fields]
    elif isinstance(source_fields, list):
        fields = [str(item) for item in source_fields if str(item)]
    else:
        fields = []
    candidates: list[str] = []
    for field in fields:
        for candidate in (field, field.rsplit(".", 1)[-1]):
            if candidate and candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _claim_type_for_sentence(sentence: dict, provenance: dict | None = None) -> str:
    claim_type = str(sentence.get("claim_type") or "")
    if not claim_type and isinstance(provenance, dict):
        claim_type = str(provenance.get("claim_type") or "")
    if claim_type:
        return claim_type
    return "interpretation" if sentence.get("interpretation") is not False else ""


def _provenance_key(provenance: dict) -> str:
    return f"{provenance.get('source_file') or ''}::{provenance.get('source_field') or ''}"


def _with_claim_type(provenance: dict, claim_type: str) -> dict:
    normalized = {
        "source_file": provenance.get("source_file"),
        "source_field": provenance.get("source_field"),
        "source_class": provenance.get("source_class"),
    }
    if claim_type:
        normalized["claim_type"] = claim_type
    if "source_value" in provenance and claim_type in {"count", "direct_value", "absence"}:
        normalized["source_value"] = provenance.get("source_value")
    return normalized


def _lookup_provenance(
    reference_card: dict,
    *,
    source_fields: Any,
    preferred_source_file: str = "",
) -> dict | None:
    provenance_index = reference_card.get("provenance_index")
    if not isinstance(provenance_index, dict):
        return None
    fields = _source_field_candidates(source_fields)
    entries = [
        entry
        for entry in provenance_index.values()
        if isinstance(entry, dict)
    ]
    for field in fields:
        for entry in entries:
            if (
                preferred_source_file
                and entry.get("source_file") == preferred_source_file
                and entry.get("source_field") == field
            ):
                return entry
    if preferred_source_file.startswith("evidence/") and any(
        field in {"clinical_drugs", "preclinical_compounds"} for field in fields
    ):
        return None
    for field in fields:
        for entry in entries:
            if entry.get("source_field") == field:
                return entry
    return None


def _slot_preferred_provenance_keys(slot: dict | None) -> list[str]:
    if not isinstance(slot, dict):
        return []
    section = str(slot.get("section") or _section_id_from_slot_id(str(slot.get("slot_id") or "")) or "")
    slot_name = str(slot.get("slot") or _slot_name_from_slot_id(str(slot.get("slot_id") or "")) or "")
    gene = str(slot.get("gene") or _gene_from_slot_id(str(slot.get("slot_id") or "")) or "").upper()
    if section == "stage1_filter":
        return ["drug_report_reference_card.json::stage1_filter_results"]
    if section == "druggability_matrix":
        return [
            "drug_report_reference_card.json::combined_total",
            "drug_report_reference_card.json::classification",
            "drug_report_reference_card.json::validated_total",
            "drug_report_reference_card.json::exploratory_total",
        ]
    if section == "executive_summary" and slot_name == "therapeutic_opportunities":
        return [
            "drug_report_reference_card.json::stage3_candidates",
            "drug_report_reference_card.json::classification",
            "drug_report_reference_card.json::priority",
            "drug_report_reference_card.json::combined_total",
        ]
    if section == "featured_candidate":
        if slot_name == "drug_profile" and gene:
            return [
                f"evidence/ot_{gene}.json::clinical_drugs",
                f"evidence/stage3_{gene}.json::preclinical_compounds",
            ]
        if slot_name == "biological_context":
            return ["drug_report_reference_card.json::stage1_filter_results"]
        if slot_name == "rubric_recommendation":
            return [
                "drug_report_reference_card.json::combined_total",
                "drug_report_reference_card.json::classification",
                "drug_report_reference_card.json::priority",
                "drug_report_reference_card.json::stage3_candidate",
            ]
    if section in {"hypothesis", "hypothesis_summary"}:
        return ["drug_report_reference_card.json::hypothesis_data"]
    if section == "summary":
        return [
            "drug_report_reference_card.json::stage3_candidates",
            "drug_report_reference_card.json::stage1_filter_results",
            "drug_report_reference_card.json::hypothesis_data",
            "drug_report_reference_card.json::data_limitations",
        ]
    return []


def _slot_preferred_provenance(reference_card: dict, slot: dict | None) -> dict | None:
    provenance_index = reference_card.get("provenance_index")
    if not isinstance(provenance_index, dict):
        return None
    for key in _slot_preferred_provenance_keys(slot):
        candidate = provenance_index.get(key)
        if isinstance(candidate, dict):
            return candidate
    return None


def _slot_allowed_source_fields(slot: dict | None) -> set[str]:
    return {
        key.split("::", 1)[1]
        for key in _slot_preferred_provenance_keys(slot)
        if "::" in key
    }


def _set_sentence_provenance(
    sentence: dict,
    provenance: dict,
    claim_type: str,
    *,
    fallback_slot: dict | None = None,
) -> dict:
    normalized = dict(sentence)
    source_field = str(provenance.get("source_field") or "")
    if fallback_slot is not None:
        normalized["text"] = _fallback_text(fallback_slot, provenance)
    if source_field:
        normalized["source_fields"] = [source_field]
    normalized["source_provenance"] = _with_claim_type(provenance, claim_type)
    return normalized


def _normalize_sentence_provenance(
    sentence: dict,
    reference_card: dict,
    slot: dict | None = None,
) -> dict:
    normalized = dict(sentence)
    raw_provenance = normalized.get("source_provenance")
    if isinstance(raw_provenance, list):
        candidates = [item for item in raw_provenance if isinstance(item, dict)]
    elif isinstance(raw_provenance, dict):
        candidates = [raw_provenance]
    else:
        candidates = []

    source_fields = normalized.get("source_fields")
    if not source_fields and candidates:
        source_field = candidates[0].get("source_field")
        if source_field:
            normalized["source_fields"] = [source_field]
            source_fields = normalized["source_fields"]

    provenance_index = reference_card.get("provenance_index")
    allowed_fields = _slot_allowed_source_fields(slot)
    preferred = _slot_preferred_provenance(reference_card, slot)
    if isinstance(provenance_index, dict):
        for candidate in candidates:
            if (
                _provenance_key(candidate) in provenance_index
                and (
                    not allowed_fields
                    or str(candidate.get("source_field") or "") in allowed_fields
                )
            ):
                return _set_sentence_provenance(
                    normalized,
                    candidate,
                    _claim_type_for_sentence(normalized, candidate),
                )

    preferred_source_file = str(candidates[0].get("source_file") or "") if candidates else ""
    matched = _lookup_provenance(
        reference_card,
        source_fields=source_fields,
        preferred_source_file=preferred_source_file,
    )
    if matched is not None and (
        not allowed_fields
        or str(matched.get("source_field") or "") in allowed_fields
    ):
        normalized = _set_sentence_provenance(
            normalized,
            matched,
            _claim_type_for_sentence(normalized, matched),
        )
    elif preferred is not None:
        normalized = _set_sentence_provenance(
            normalized,
            preferred,
            _claim_type_for_sentence(normalized, preferred),
            fallback_slot=slot,
        )
    elif candidates:
        normalized["source_provenance"] = _with_claim_type(
            candidates[0],
            _claim_type_for_sentence(normalized, candidates[0]),
        )
    return normalized


def _section_id_from_slot_id(slot_id: str) -> str | None:
    for part in slot_id.split("|"):
        if part.startswith("section:"):
            return part.split(":", 1)[1]
    return None


def _slot_name_from_slot_id(slot_id: str) -> str | None:
    for part in slot_id.split("|"):
        if part.startswith("slot:"):
            return part.split(":", 1)[1]
    return None


def _gene_from_slot_id(slot_id: str) -> str | None:
    for part in slot_id.split("|"):
        if part.startswith("gene:"):
            return part.split(":", 1)[1]
    return None


def _fallback_provenance(reference_card: dict, slot: dict) -> dict | None:
    provenance_index = reference_card.get("provenance_index")
    if not isinstance(provenance_index, dict):
        return None
    for key in _slot_preferred_provenance_keys(slot):
        candidate = provenance_index.get(key)
        if isinstance(candidate, dict):
            return candidate
    gene = str(slot.get("gene") or "").upper()
    preferences: list[str] = []
    if gene:
        if slot.get("slot") == "drug_profile":
            preferences.extend([
                f"evidence/ot_{gene}.json::clinical_drugs",
                f"evidence/stage3_{gene}.json::preclinical_compounds",
            ])
        preferences.extend([
            "drug_report_reference_card.json::combined_total",
            "drug_report_reference_card.json::classification",
            "drug_report_reference_card.json::stage3_candidate",
        ])
    else:
        preferences.extend([
            "drug_report_reference_card.json::stage3_candidates",
            "drug_report_reference_card.json::combined_total",
            "drug_report_reference_card.json::stage1_filter_results",
            "drug_report_reference_card.json::hypothesis_data",
            "drug_report_reference_card.json::data_limitations",
        ])
    for key in preferences:
        candidate = provenance_index.get(key)
        if isinstance(candidate, dict):
            return candidate
    for candidate in provenance_index.values():
        if isinstance(candidate, dict):
            return candidate
    return None


def _fallback_text(slot: dict, provenance: dict) -> str:
    gene = str(slot.get("gene") or "").upper()
    source_field = str(provenance.get("source_field") or "reference_card")
    section = str(slot.get("section") or _section_id_from_slot_id(str(slot.get("slot_id") or "")) or "section")
    slot_name = str(slot.get("slot") or "summary")
    if gene:
        subject = f"{gene} {slot_name.replace('_', ' ')}"
    else:
        subject = f"{section.replace('_', ' ')} {slot_name.replace('_', ' ')}"
    return (
        f"{subject} is summarized conservatively from the current reference card "
        f"and should be interpreted as evidence-limited local context. [source: {source_field}]"
    )


def _normalize_report_expansions_payload(base: Path, expansions: dict) -> dict:
    normalized = dict(expansions or {})
    if "slots" not in normalized:
        for alias in ("expansions", "report_expansions"):
            if isinstance(normalized.get(alias), list):
                normalized["slots"] = normalized.pop(alias)
                break
            if isinstance(normalized.get(alias), dict):
                normalized["slots"] = []
                normalized.pop(alias, None)
                break
    if isinstance(normalized.get("expansions"), list):
        normalized.pop("expansions", None)
    if isinstance(normalized.get("report_expansions"), list):
        normalized.pop("report_expansions", None)
    if normalized.get("report_expansions_version") == "v1":
        normalized["schema_version"] = REPORT_EXPANSIONS_VERSION
    if "schema_version" not in normalized and isinstance(normalized.get("slots"), list):
        normalized["schema_version"] = REPORT_EXPANSIONS_VERSION

    ref_path = base / "drug_report_reference_card.json"
    if not ref_path.exists() or not isinstance(normalized.get("slots"), list):
        return normalized

    reference_card = json.loads(ref_path.read_text(encoding="utf-8"))
    slots: list[dict] = []
    for slot in normalized["slots"]:
        if not isinstance(slot, dict):
            slots.append(slot)
            continue
        slot_copy = dict(slot)
        slot_id = str(slot_copy.get("slot_id") or "")
        if "section_id" not in slot_copy:
            section_id = _section_id_from_slot_id(slot_id)
            if section_id:
                slot_copy["section_id"] = section_id
        if "sentences" not in slot_copy and isinstance(slot_copy.get("expansions"), list):
            slot_copy["sentences"] = slot_copy.pop("expansions")
        else:
            slot_copy.pop("expansions", None)
        sentences = slot_copy.get("sentences")
        if isinstance(sentences, list):
            slot_copy["sentences"] = [
                _normalize_sentence_provenance(sentence, reference_card, slot_copy)
                if isinstance(sentence, dict)
                else sentence
                for sentence in sentences
            ]
        slots.append(slot_copy)
    normalized["slots"] = slots
    return normalized


def persist_drug_report_reference_card(data_dir: str | Path, reference_card: dict) -> dict:
    """Persist the canonical Reference Card used by report rendering."""
    base = Path(data_dir).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    card = dict(reference_card)
    card["schema_version"] = REFERENCE_CARD_VERSION
    card["expansion_slots"] = build_expansion_slots(card)
    if not isinstance(card.get("provenance_index"), dict):
        card["provenance_index"] = _build_provenance_index(card)
    if isinstance(card.get("disease_scope"), dict):
        card["provenance_index"].setdefault(
            "drug_report_reference_card.json::disease_scope",
            {
                "source_file": "drug_report_reference_card.json",
                "source_field": "disease_scope",
                "source_class": "reference_card",
                "source_value": card["disease_scope"],
            },
        )
    path = base / "drug_report_reference_card.json"
    path.write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")
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
    expected_hash = canonical_json_hash(reference_card)
    if expansions.get("reference_card_hash") != expected_hash:
        errors.append({
            "code": "RENDER_SOURCE_HASH_MISMATCH",
            "message": "reference_card_hash does not match drug_report_reference_card.json",
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
                "message": f"{slot_id} must include at least one sentence",
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
def save_report_expansions(data_dir: str, expansions: dict) -> str:
    """Validate and persist report_expansions.json."""
    base = Path(data_dir).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    normalized_expansions = _normalize_report_expansions_payload(
        base,
        expansions,
    )
    ref_path = base / "drug_report_reference_card.json"
    if ref_path.exists():
        reference_card = json.loads(ref_path.read_text(encoding="utf-8"))
        normalized_expansions["reference_card_hash"] = canonical_json_hash(reference_card)
    _, errors = validate_report_expansions(base, normalized_expansions)
    result = {
        "saved": False,
        "path": str(base / "report_expansions.json"),
        "errors": errors,
        "reference_card_hash": normalized_expansions.get("reference_card_hash"),
    }
    if errors:
        return json.dumps(result, indent=2)
    (base / "report_expansions.json").write_text(
        json.dumps(normalized_expansions, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    result["saved"] = True
    return json.dumps(result, indent=2)

"""Tests for critic task envelope parser and normalization helpers (task #6).

RED phase: all tests must fail before implementation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_slot(
    slot_id: str = "section:executive_summary|slot:add_summary",
    source_file: str = "evidence/ot_CD4.json",
    source_field: str = "clinical_drugs",
) -> dict:
    return {
        "slot_id": slot_id,
        "sentences": [
            {
                "text": "CD4 has clinical drugs.",
                "source_fields": [source_field],
                "source_provenance": {
                    "source_file": source_file,
                    "source_field": source_field,
                    "source_class": "opentargets_clinical",
                    "claim_type": "direct_value",
                    "source_value": ["ibalizumab"],
                },
            }
        ],
    }


def _make_payload(
    slots: list[dict] | None = None,
    reference_card_hash: str | None = None,
    include_ref_hash: bool = False,
) -> dict:
    payload: dict[str, Any] = {
        "schema_version": "report_expansions.v1",
        "slots": slots if slots is not None else [_make_slot()],
    }
    if include_ref_hash:
        payload["reference_card_hash"] = reference_card_hash
    return payload


def _make_envelope(
    payload: dict | None = None,
    payload_hash: str = "somehash",
    schema_version: str = "summarizer_critic_review.v1",
    provenance_context: dict | None = None,
) -> dict:
    if payload is None:
        payload = _make_payload()
    return {
        "schema_version": schema_version,
        "payload_hash": payload_hash,
        "payload": payload,
        "provenance_context": provenance_context or {},
    }


# ---------------------------------------------------------------------------
# Test 1: Envelope parser requires schema_version, payload, payload_hash
# ---------------------------------------------------------------------------


def test_critic_task_envelope_requires_schema_version_payload_and_hash():
    """parse_critic_envelope must return CriticEnvelope on a valid input and
    raise EnvelopeParseError when required top-level fields are missing."""
    from src.agents.drug_target.subagents.summarizer.middleware import (
        CriticEnvelope,
        EnvelopeParseError,
        parse_critic_envelope,
    )

    # Valid envelope parses without error
    valid = _make_envelope()
    envelope = parse_critic_envelope(json.dumps(valid))
    assert isinstance(envelope, CriticEnvelope)
    assert envelope.schema_version == "summarizer_critic_review.v1"
    assert envelope.payload_hash == "somehash"
    assert envelope.payload["schema_version"] == "report_expansions.v1"

    # Missing schema_version
    missing_sv = _make_envelope()
    del missing_sv["schema_version"]
    with pytest.raises(EnvelopeParseError, match="schema_version"):
        parse_critic_envelope(json.dumps(missing_sv))

    # Wrong schema_version value
    wrong_sv = _make_envelope(schema_version="wrong.v0")
    with pytest.raises(EnvelopeParseError, match="schema_version"):
        parse_critic_envelope(json.dumps(wrong_sv))

    # Missing payload_hash
    missing_hash = _make_envelope()
    del missing_hash["payload_hash"]
    with pytest.raises(EnvelopeParseError, match="payload_hash"):
        parse_critic_envelope(json.dumps(missing_hash))

    # Missing payload
    missing_payload = _make_envelope()
    del missing_payload["payload"]
    with pytest.raises(EnvelopeParseError, match="payload"):
        parse_critic_envelope(json.dumps(missing_payload))

    # Payload with wrong schema_version
    bad_payload_sv = _make_envelope(payload={
        "schema_version": "wrong.v99",
        "slots": [_make_slot()],
    })
    with pytest.raises(EnvelopeParseError, match="payload.*schema_version|schema_version.*payload"):
        parse_critic_envelope(json.dumps(bad_payload_sv))

    # Non-JSON input
    with pytest.raises(EnvelopeParseError):
        parse_critic_envelope("not json at all")


# ---------------------------------------------------------------------------
# Test 2: LLM-supplied payload_hash is distrusted — compute_envelope_payload_hash
# ---------------------------------------------------------------------------


def test_critic_task_envelope_rejects_llm_hash_mismatch():
    """compute_envelope_payload_hash returns the real hash; the LLM-supplied
    payload_hash field on the envelope may differ (and that is expected —
    middleware must use compute_envelope_payload_hash, not envelope.payload_hash)."""
    from src.agents.drug_target.subagents.summarizer.middleware import (
        CriticEnvelope,
        compute_envelope_payload_hash,
        parse_critic_envelope,
    )

    payload = _make_payload()
    deliberately_wrong_hash = "llm_supplied_wrong_hash_abc123"
    envelope_dict = _make_envelope(payload=payload, payload_hash=deliberately_wrong_hash)

    envelope = parse_critic_envelope(json.dumps(envelope_dict))
    real_hash = compute_envelope_payload_hash(envelope)

    # The LLM-supplied hash is preserved on the object (for telemetry)
    assert envelope.payload_hash == deliberately_wrong_hash
    # But the computed hash differs from the wrong LLM hash
    assert real_hash != deliberately_wrong_hash
    # And the computed hash is a non-empty hex string (SHA256 = 64 chars)
    assert len(real_hash) == 64
    assert all(c in "0123456789abcdef" for c in real_hash)


# ---------------------------------------------------------------------------
# Test 3: validate_cited_only_provenance rejects uncited provenance entries
# ---------------------------------------------------------------------------


def test_critic_envelope_excludes_uncited_provenance_entries():
    """validate_cited_only_provenance must raise EnvelopeParseError when a
    provenance_context entry references a (source_file, source_field) that
    does not appear in the corresponding slot's sentences citations."""
    from src.agents.drug_target.subagents.summarizer.middleware import (
        EnvelopeParseError,
        parse_critic_envelope,
        validate_cited_only_provenance,
    )

    slot_id = "section:executive_summary|slot:add_summary"
    slot = _make_slot(
        slot_id=slot_id,
        source_file="evidence/ot_CD4.json",
        source_field="clinical_drugs",
    )

    # provenance_context references a (source_file, source_field) NOT cited in the slot
    provenance_context = {
        slot_id: {
            "cited_source_values": [],
            "cited_provenance_entries": [
                {
                    "source_file": "evidence/ot_TGFB1.json",  # not cited in slot sentences
                    "source_field": "clinical_drugs",
                }
            ],
        }
    }

    envelope_dict = _make_envelope(
        payload=_make_payload(slots=[slot]),
        provenance_context=provenance_context,
    )
    envelope = parse_critic_envelope(json.dumps(envelope_dict))

    with pytest.raises(EnvelopeParseError, match="not cited|uncited|provenance"):
        validate_cited_only_provenance(envelope)

    # Correct provenance_context — same source as cited in slot — must pass
    valid_provenance_context = {
        slot_id: {
            "cited_source_values": [],
            "cited_provenance_entries": [
                {
                    "source_file": "evidence/ot_CD4.json",
                    "source_field": "clinical_drugs",
                }
            ],
        }
    }
    valid_envelope_dict = _make_envelope(
        payload=_make_payload(slots=[slot]),
        provenance_context=valid_provenance_context,
    )
    valid_envelope = parse_critic_envelope(json.dumps(valid_envelope_dict))
    # Must not raise
    validate_cited_only_provenance(valid_envelope)


# ---------------------------------------------------------------------------
# Test 4: normalize_expansions_for_hash handles omitted vs. auto-derived reference_card_hash
# ---------------------------------------------------------------------------


def test_critic_save_hash_matches_when_reference_card_hash_omitted_then_auto_derived():
    """Payloads with reference_card_hash omitted and with a filled-in derived
    value must produce the same canonical hash after normalization — because
    normalize_expansions_for_hash strips reference_card_hash from both sides."""
    from src.agents.drug_target.subagents.summarizer.middleware import (
        normalize_expansions_for_hash,
    )
    from src.agents.drug_target.tools.report_expansion_schema import canonical_json_hash

    slots = [_make_slot()]

    # Payload with reference_card_hash omitted
    payload_no_hash = _make_payload(slots=slots, include_ref_hash=False)

    # Payload with reference_card_hash filled in (simulating auto-derive)
    derived_hash = "abc123derived456"
    payload_with_hash = _make_payload(slots=slots, include_ref_hash=True, reference_card_hash=derived_hash)

    normalized_no_hash = normalize_expansions_for_hash(payload_no_hash)
    normalized_with_hash = normalize_expansions_for_hash(payload_with_hash)

    hash_no_hash = canonical_json_hash(normalized_no_hash)
    hash_with_hash = canonical_json_hash(normalized_with_hash)

    assert hash_no_hash == hash_with_hash, (
        "normalize_expansions_for_hash must strip reference_card_hash so that "
        "omitted and auto-derived payloads produce the same canonical hash"
    )

    # The normalized dict must NOT contain reference_card_hash
    assert "reference_card_hash" not in normalized_no_hash
    assert "reference_card_hash" not in normalized_with_hash


# ---------------------------------------------------------------------------
# Test 5: normalize_expansions_for_hash is consistent across raw dict and Pydantic shape
# ---------------------------------------------------------------------------


def test_critic_save_hash_matches_for_raw_dict_and_pydantic_payload_shapes():
    """normalize_expansions_for_hash must produce the same canonical hash
    whether the input is a raw dict or the output of ReportExpansionsPayload.model_dump()."""
    from src.agents.drug_target.subagents.summarizer.middleware import (
        normalize_expansions_for_hash,
    )
    from src.agents.drug_target.tools.report_expansion_schema import (
        ReportExpansionsPayload,
        SlotItem,
        SentenceItem,
        SourceProvenance,
        canonical_json_hash,
    )

    # Build a minimal raw dict payload
    raw_payload = {
        "schema_version": "report_expansions.v1",
        "slots": [
            {
                "slot_id": "section:executive_summary|slot:add_summary",
                "sentences": [
                    {
                        "text": "TGFB1 has 3 clinical drugs.",
                        "source_fields": ["clinical_drugs"],
                        "source_provenance": {
                            "source_file": "evidence/ot_TGFB1.json",
                            "source_field": "clinical_drugs",
                            "source_class": "opentargets_clinical",
                            "claim_type": "direct_value",
                            "source_value": ["drug_a", "drug_b", "drug_c"],
                        },
                    }
                ],
            }
        ],
    }

    # Build the equivalent Pydantic model_dump
    pydantic_model = ReportExpansionsPayload(
        schema_version="report_expansions.v1",
        slots=[
            SlotItem(
                slot_id="section:executive_summary|slot:add_summary",
                sentences=[
                    SentenceItem(
                        text="TGFB1 has 3 clinical drugs.",
                        source_fields=["clinical_drugs"],
                        source_provenance=SourceProvenance(
                            source_file="evidence/ot_TGFB1.json",
                            source_field="clinical_drugs",
                            source_class="opentargets_clinical",
                            claim_type="direct_value",
                            source_value=["drug_a", "drug_b", "drug_c"],
                        ),
                    )
                ],
            )
        ],
    )
    pydantic_dump = pydantic_model.model_dump()

    normalized_raw = normalize_expansions_for_hash(raw_payload)
    normalized_pydantic = normalize_expansions_for_hash(pydantic_dump)

    hash_raw = canonical_json_hash(normalized_raw)
    hash_pydantic = canonical_json_hash(normalized_pydantic)

    assert hash_raw == hash_pydantic, (
        "normalize_expansions_for_hash must produce identical canonical hash "
        "for raw dict and Pydantic model_dump() of the same logical payload"
    )

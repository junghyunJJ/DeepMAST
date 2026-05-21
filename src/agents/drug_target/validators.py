from __future__ import annotations

from src.agents.drug_target.tools.report_expansion_schema import (
    ReportExpansionsPayload,
    # _build_provenance_index is private by convention but we accept the import
    # here because validators.py is an internal sibling module, not a public
    # consumer, and changing the visibility is out of scope for this task.
    _build_provenance_index,
)


def validate_cited_only_provenance(
    payload: ReportExpansionsPayload,
    reference_card: dict,
) -> list[dict]:
    """Verify every sentence's source_provenance is present in reference_card.

    For each SentenceItem in payload.slots[*].sentences:
      - Read source_provenance.source_file and source_provenance.source_field.
      - Compute the provenance index key as ``f"{source_file}::{source_field}"``.
      - If the key is not in the reference_card's provenance index, emit an
        error dict.

    The reference_card's provenance index is built via
    ``_build_provenance_index(reference_card)`` (already used by
    ``validate_report_expansions``); we reuse it so the citation rule matches
    the index that the rest of the validation chain depends on.

    Args:
        payload: Structured-output result from the LLM.
        reference_card: The drug_report_reference_card dict read from disk.

    Returns:
        A list of error dicts. Empty list means all sentences are properly
        cited. Each error dict has shape::

            {"slot_id": str,
             "sentence_index": int,
             "source_value": str,  # the missing "{source_file}::{source_field}" key
             "reason": str}        # human-readable explanation

        Does NOT raise — the caller (finalize_report) is responsible for
        surfacing errors via the ``report_finalization_error`` state field.
    """
    index = _build_provenance_index(reference_card)
    errors: list[dict] = []

    for slot in payload.slots:
        for sentence_index, sentence in enumerate(slot.sentences):
            source_file = sentence.source_provenance.source_file
            source_field = sentence.source_provenance.source_field

            if not source_file or not source_field:
                errors.append(
                    {
                        "slot_id": slot.slot_id,
                        "sentence_index": sentence_index,
                        "source_value": "",
                        "reason": "source_provenance missing source_file or source_field",
                    }
                )
                continue

            key = f"{source_file}::{source_field}"
            if key not in index:
                errors.append(
                    {
                        "slot_id": slot.slot_id,
                        "sentence_index": sentence_index,
                        "source_value": key,
                        "reason": (
                            f"key {key!r} not found in reference_card provenance index"
                        ),
                    }
                )

    return errors


__all__ = ["validate_cited_only_provenance"]

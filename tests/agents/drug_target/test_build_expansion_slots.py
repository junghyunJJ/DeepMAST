"""Regression tests for ``build_expansion_slots`` slot-id classification.

Issue #21 background
--------------------
``build_expansion_slots`` classifies each ``<!-- EXPAND: ... -->`` marker
in the report template by substring-matching the instruction text against
a hard-coded if/elif chain. Before the fix, the chain tested the broad
phrase ``"therapeutic opportunities"`` BEFORE the more specific phrase
``"what drugs exist"``. The per-card drug-profile marker

    <!-- EXPAND: Describe what drugs exist and their approved indications.
                 Do NOT speculate about repurposing potential or
                 therapeutic opportunities for the study disease. -->

contains both substrings, so every per-card drug-profile marker (one
per featured candidate) was silently misclassified as the Executive
Summary's ``slot:therapeutic_opportunities``. With N featured cards the
reference card's ``required_slot_ids`` ended up with N+1 duplicate
entries pointing at a single Executive-Summary slot, masking the loss of
all per-card drug-profile prose.

The fix has two parts:
  1. Reorder the classification chain so the specific featured-card
     phrases (``"what drugs exist"``, ``"biological context"``,
     ``"therapeutic recommendation"``, ``"therapeutic implications"``)
     are tested BEFORE broader executive-summary phrases that may also
     appear as negative constraints.
  2. Raise ``ValueError`` at construction time when two markers reach
     the same ``slot_id`` — fail loud so future template edits cannot
     reintroduce the silent-loss class of bug.

Acceptance criteria from the issue body:
  * ``build_expansion_slots(reference_card)`` from the
    ``baseline_hallucinated`` fixture produces zero duplicate
    ``slot_id``s.
  * Round-trip test no longer needs the ``dict.fromkeys`` dedupe
    workaround.
  * New unit test asserts ``build_expansion_slots`` rejects a
    hand-crafted reference card containing duplicate-inducing markers.
"""

from __future__ import annotations

from collections import Counter

import pytest

from src.agents.drug_target.tools.report_expansion_schema import (
    build_expansion_slots,
)


# Exact marker text from skills/drug-target-reporting/templates/drug_report.md.j2
# line 123 — kept in this module verbatim so a future template edit that
# changes the marker wording does not silently void this regression test.
_DRUG_PROFILE_MARKER_INSTRUCTION = (
    "Describe what drugs exist and their approved indications. "
    "Do NOT speculate about repurposing potential or therapeutic "
    "opportunities for the study disease. State only what is known "
    "from the listed data."
)

_EXEC_SUMMARY_THERAPEUTIC_OPPORTUNITIES_INSTRUCTION = (
    "Add 2-3 sentences summarizing key therapeutic opportunities"
)


def _marker(instruction: str) -> str:
    return f"<!-- EXPAND: {instruction} -->"


def test_drug_profile_marker_classifies_as_drug_profile_not_therapeutic_opportunities() -> None:
    """The drug-profile marker's instruction contains ``"therapeutic
    opportunities"`` as a *negative* constraint. The classifier MUST
    bind it to ``slot:drug_profile`` under ``featured_candidate``, not
    to the Executive Summary's ``slot:therapeutic_opportunities``.

    This is the minimal regression for issue #21.
    """
    card = {
        "markdown_template": _marker(_DRUG_PROFILE_MARKER_INSTRUCTION),
        "stage3_candidates": ["TGFB1"],
    }
    slots = build_expansion_slots(card)
    assert len(slots) == 1
    slot = slots[0]
    assert slot["section"] == "featured_candidate", slot
    assert slot["slot"] == "drug_profile", slot
    assert slot["gene"] == "TGFB1", slot
    assert slot["slot_id"] == (
        "section:featured_candidate|gene:TGFB1|slot:drug_profile"
    ), slot


def test_baseline_hallucinated_template_produces_zero_duplicate_slot_ids() -> None:
    """Reconstruct the baseline_hallucinated template marker layout and
    assert no duplicate slot_ids are produced. Acceptance criterion #1.

    Pre-fix the per-card drug-profile marker (repeated once per featured
    card) silently aliased to the Executive Summary's
    ``slot:therapeutic_opportunities`` slot, so 4 stage3 candidates
    produced 4 duplicates of that single slot_id.
    """
    n_featured = 4
    per_card_block = (
        _marker(_DRUG_PROFILE_MARKER_INSTRUCTION)
        + "\n"
        + _marker("Interpret biological context and pathway relevance")
        + "\n"
        + _marker("Add therapeutic recommendation based on evidence")
        + "\n"
    )
    template = (
        _marker(_EXEC_SUMMARY_THERAPEUTIC_OPPORTUNITIES_INSTRUCTION)
        + "\n"
        + _marker("Add 2-3 sentences interpreting the overall scoring landscape")
        + "\n"
        + _marker(
            "Add 2-3 sentences interpreting which L-R pairs passed "
            "biological validation and the implications for target selection"
        )
        + "\n"
        + (per_card_block * n_featured)
        + _marker(
            "Add 2-3 sentences summarizing the hypothesis generation "
            "approach and key themes"
        )
        + "\n"
        + _marker(
            "Add recommendations for validated targets, exploratory "
            "targets, and next steps"
        )
    )
    card = {
        "markdown_template": template,
        "stage3_candidates": ["CD4", "MUC1", "FN1", "ITGB2"],
    }
    slots = build_expansion_slots(card)
    slot_ids = [s["slot_id"] for s in slots]
    duplicates = [sid for sid, count in Counter(slot_ids).items() if count > 1]
    assert duplicates == [], (
        f"build_expansion_slots produced duplicate slot_ids: "
        f"{duplicates}. Full id list: {slot_ids}"
    )
    # Every per-card slot must be bound to a real gene; pre-fix the
    # drug-profile counter never advanced because the per-card marker
    # was being absorbed into the executive_summary branch.
    drug_profile_genes = sorted(
        s.get("gene") for s in slots if s["slot"] == "drug_profile"
    )
    assert drug_profile_genes == ["CD4", "FN1", "ITGB2", "MUC1"], slots


def test_build_expansion_slots_raises_on_duplicate_inducing_markers() -> None:
    """Acceptance criterion #3: a hand-crafted reference card whose
    markers naturally collide on a single ``slot_id`` MUST raise at
    construction time, not silently produce a corrupt list.

    Two markers with no matching keywords both fall through to the
    default ``section:executive_summary|slot:add_summary`` branch and
    therefore collide deterministically.
    """
    card = {
        "markdown_template": (
            _marker("Provide a free-form note one.")
            + "\n"
            + _marker("Provide a free-form note two.")
        ),
    }
    with pytest.raises(ValueError, match="duplicate slot_id"):
        build_expansion_slots(card)


def test_build_expansion_slots_returns_explicit_expansion_slots_unchanged() -> None:
    """When the reference card already supplies an explicit
    ``expansion_slots`` list, ``build_expansion_slots`` MUST return it
    verbatim — the duplicate-detection guard added by issue #21 applies
    only to slots derived from EXPAND markers, not to a pre-built list.

    Some callers (tests, downstream renderers) pass curated slots
    directly; rejecting their input would be a scope-creep regression.
    """
    pre_built = [
        {
            "slot_id": "section:executive_summary|slot:add_summary",
            "section": "executive_summary",
            "slot": "add_summary",
        }
    ]
    card = {
        "markdown_template": "ignored when expansion_slots is set",
        "expansion_slots": pre_built,
    }
    assert build_expansion_slots(card) is pre_built

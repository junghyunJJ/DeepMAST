"""RED tests for new validate_drug_md flags (T2 — TDD).

These tests will FAIL until T3-T7 land in src/agents/drug_target/tools/stage_logic.py.

Reference spec: .omb/plans/2026-04-29-drug-target-flag-spec.md

Helper note: the current validate_drug_md returns {"valid": ..., "issues": [...]}
(key = "issues").  T3-T7 will migrate to {"valid": ..., "findings": [...]} per the
spec.  This helper reads both keys and merges them so collection does not raise
KeyError — each individual test then fails on AssertionError when the new type
is absent, which is the correct RED state.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.drug_target.tools import validate_drug_md

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "synthetic"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _findings(data_dir: Path) -> list[dict]:
    """Run validator and return findings list.

    Merges both the legacy 'issues' key and the forthcoming 'findings' key so
    collection never raises KeyError regardless of which T3-T7 phase has landed.
    Tests fail on AssertionError when a new flag type is absent — correct RED state.
    """
    impl = getattr(validate_drug_md, "func", None) or validate_drug_md
    result_raw = impl(data_dir)
    result = json.loads(result_raw) if isinstance(result_raw, str) else result_raw
    return result.get("findings", []) + result.get("issues", [])


def _flag_types(findings: list[dict]) -> set[str]:
    return {f["type"] for f in findings}


# ---------------------------------------------------------------------------
# FABRICATED_DRUG_NAME (T3)
# ---------------------------------------------------------------------------


class TestFabricatedDrugName:
    """DRUG_NAME in EXPAND prose absent from resolved_drugs + stage3 allowlist."""

    def test_fires_on_drug_absent_from_allowlist(self):
        """Unknownol appears in prose but is not in resolved_drugs.json or
        stage3_FOO.json — FABRICATED_DRUG_NAME must fire."""
        findings = _findings(FIXTURE_ROOT / "fabricated_drug")
        assert "FABRICATED_DRUG_NAME" in _flag_types(findings), (
            f"Expected FABRICATED_DRUG_NAME in findings; got types: {_flag_types(findings)}"
        )

    def test_snippet_contains_fabricated_name(self):
        """The finding snippet must reference the unknown drug name."""
        findings = _findings(FIXTURE_ROOT / "fabricated_drug")
        fabricated = [f for f in findings if f["type"] == "FABRICATED_DRUG_NAME"]
        assert any(
            "unknownol" in (f.get("snippet") or "").casefold() for f in fabricated
        ), f"Expected 'unknownol' in a FABRICATED_DRUG_NAME snippet; got: {fabricated}"

    def test_does_not_fire_in_table_row(self):
        """Drug names inside markdown table rows are exempt from this flag."""
        findings = _findings(FIXTURE_ROOT / "fabricated_drug")
        for f in findings:
            if f["type"] == "FABRICATED_DRUG_NAME":
                snippet = (f.get("snippet") or "").strip()
                assert not snippet.startswith("|"), (
                    f"FABRICATED_DRUG_NAME fired on a table row: {snippet!r}"
                )

    def test_does_not_fire_in_code_block(self):
        """Drug names inside fenced code blocks must not trigger this flag."""
        findings = _findings(FIXTURE_ROOT / "fabricated_drug")
        for f in findings:
            if f["type"] == "FABRICATED_DRUG_NAME":
                assert "```" not in (f.get("snippet") or ""), (
                    f"FABRICATED_DRUG_NAME fired inside a code block: {f}"
                )

    def test_does_not_fire_on_not_available_literal(self):
        """Lines containing 'not available in source data' are exempt."""
        findings = _findings(FIXTURE_ROOT / "fabricated_drug")
        for f in findings:
            assert "not available in source data" not in (
                f.get("snippet") or ""
            ).casefold(), (
                f"Flag {f['type']} fired on a carve-out line: {f.get('snippet')!r}"
            )


# ---------------------------------------------------------------------------
# FABRICATED_FILE_REFERENCE (T4)
# ---------------------------------------------------------------------------


class TestFabricatedFileReference:
    """References to _FAILED files or non-existent JSON files in prose."""

    def test_fires_on_failed_suffix_bullet(self):
        """Bullet item containing stage1_*.json_FAILED must fire unconditionally."""
        findings = _findings(FIXTURE_ROOT / "fabricated_file_ref")
        flagged = [f for f in findings if f["type"] == "FABRICATED_FILE_REFERENCE"]
        assert flagged, (
            "Expected at least one FABRICATED_FILE_REFERENCE finding; "
            f"got types: {_flag_types(findings)}"
        )
        assert any("_FAILED" in (f.get("snippet") or "") for f in flagged), (
            f"Expected a _FAILED snippet among FABRICATED_FILE_REFERENCE findings; got: {flagged}"
        )

    def test_fires_on_failed_suffix_in_prose(self):
        """'From stage1_*.json_FAILED' in prose must fire as P0."""
        findings = _findings(FIXTURE_ROOT / "fabricated_file_ref")
        flagged = [f for f in findings if f["type"] == "FABRICATED_FILE_REFERENCE"]
        assert any("From stage" in (f.get("snippet") or "") for f in flagged), (
            f"Expected 'From stage..._FAILED' prose in a finding snippet; got: {flagged}"
        )

    def test_fires_on_bracket_form_missing_file(self):
        """[from stage3_GHOST.json] references a file absent from evidence_dir."""
        findings = _findings(FIXTURE_ROOT / "fabricated_file_ref")
        flagged = [f for f in findings if f["type"] == "FABRICATED_FILE_REFERENCE"]
        assert any("[from " in (f.get("snippet") or "") for f in flagged), (
            f"Expected bracket-form reference in FABRICATED_FILE_REFERENCE snippet; got: {flagged}"
        )

    def test_does_not_fire_in_code_block(self):
        """File references inside fenced code blocks must not fire."""
        findings = _findings(FIXTURE_ROOT / "fabricated_file_ref")
        for f in findings:
            if f["type"] == "FABRICATED_FILE_REFERENCE":
                assert "```" not in (f.get("snippet") or ""), (
                    f"FABRICATED_FILE_REFERENCE fired inside code block: {f}"
                )

    def test_does_not_fire_on_not_available_literal(self):
        """Lines containing 'not available in source data' are exempt."""
        findings = _findings(FIXTURE_ROOT / "fabricated_file_ref")
        for f in findings:
            assert "not available in source data" not in (
                f.get("snippet") or ""
            ).casefold()


# ---------------------------------------------------------------------------
# WRONG_APPROVAL_YEAR extension (T5)
# ---------------------------------------------------------------------------


class TestWrongApprovalYearExtension:
    """Extended WRONG_APPROVAL_YEAR: fires when drug absent OR first_approval null."""

    def test_fires_when_drug_not_in_evidence(self):
        """Ghostacin claims approval in 2020 but is not in resolved_drugs.json."""
        findings = _findings(FIXTURE_ROOT / "wrong_approval_year")
        flagged = [f for f in findings if f["type"] == "WRONG_APPROVAL_YEAR"]
        assert flagged, (
            "Expected WRONG_APPROVAL_YEAR findings; "
            f"got types: {_flag_types(findings)}"
        )
        assert any(
            "ghostacin" in (f.get("snippet") or "").casefold() for f in flagged
        ), f"Expected 'ghostacin' in a WRONG_APPROVAL_YEAR snippet; got: {flagged}"

    def test_fires_when_first_approval_field_missing(self):
        """DRUG_Y is in resolved_drugs.json but first_approval is null."""
        findings = _findings(FIXTURE_ROOT / "wrong_approval_year")
        flagged = [f for f in findings if f["type"] == "WRONG_APPROVAL_YEAR"]
        assert any(
            "drug_y" in (f.get("snippet") or "").casefold() for f in flagged
        ), f"Expected 'drug_y' in a WRONG_APPROVAL_YEAR snippet; got: {flagged}"

    def test_does_not_fire_on_drug_x_with_matching_year(self):
        """DRUG_X has first_approval=2018 and the fixture cites 2018 — must not fire."""
        findings = _findings(FIXTURE_ROOT / "wrong_approval_year")
        for f in findings:
            if f["type"] == "WRONG_APPROVAL_YEAR":
                snippet = (f.get("snippet") or "").casefold()
                # DRUG_X at year 2018 is correctly cited — must not appear in WRONG_APPROVAL_YEAR
                # (it appears in an annotated sentence with [source: first_approval])
                if "drug_x" in snippet and "2018" in snippet:
                    # The annotated DRUG_X line should be exempt
                    assert "[source:" in (f.get("snippet") or "").casefold() is False, (
                        f"WRONG_APPROVAL_YEAR fired on correctly-cited DRUG_X line: {f}"
                    )

    def test_does_not_fire_on_not_available_literal(self):
        """Lines containing 'not available in source data' are exempt."""
        findings = _findings(FIXTURE_ROOT / "wrong_approval_year")
        for f in findings:
            assert "not available in source data" not in (
                f.get("snippet") or ""
            ).casefold()

    def test_does_not_fire_in_code_block(self):
        """Approval year claims inside code blocks must not fire."""
        findings = _findings(FIXTURE_ROOT / "wrong_approval_year")
        for f in findings:
            if f["type"] == "WRONG_APPROVAL_YEAR":
                assert "```" not in (f.get("snippet") or "")


# ---------------------------------------------------------------------------
# UNGROUNDED_MECHANISM (T6)
# ---------------------------------------------------------------------------


class TestUngroundedMechanism:
    """Mechanism verb near drug name in EXPAND prose but MoA field empty or mismatched."""

    def test_fires_when_mechanism_field_empty(self):
        """DRUG_Y has empty mechanism_of_action; prose says it 'inhibits FOO'."""
        findings = _findings(FIXTURE_ROOT / "ungrounded_mechanism")
        flagged = [f for f in findings if f["type"] == "UNGROUNDED_MECHANISM"]
        assert flagged, (
            "Expected UNGROUNDED_MECHANISM findings; "
            f"got types: {_flag_types(findings)}"
        )
        assert any(
            "drug_y" in (f.get("snippet") or "").casefold() for f in flagged
        ), f"Expected 'drug_y' in an UNGROUNDED_MECHANISM snippet; got: {flagged}"

    def test_does_not_fire_when_verb_matches_field(self):
        """DRUG_X mechanism_of_action contains 'inhibitor'; prose says 'DRUG_X inhibits'.
        The verb stem matches the field — must NOT fire."""
        findings = _findings(FIXTURE_ROOT / "ungrounded_mechanism")
        flagged = [f for f in findings if f["type"] == "UNGROUNDED_MECHANISM"]
        assert not any(
            "drug_x" in (f.get("snippet") or "").casefold() for f in flagged
        ), f"UNGROUNDED_MECHANISM incorrectly fired on DRUG_X (grounded mechanism): {flagged}"

    def test_does_not_fire_with_source_annotation(self):
        """Sentence with [source: mechanism_of_action] must be exempt."""
        findings = _findings(FIXTURE_ROOT / "ungrounded_mechanism")
        flagged = [f for f in findings if f["type"] == "UNGROUNDED_MECHANISM"]
        assert not any(
            "[source: mechanism_of_action]" in (f.get("snippet") or "") for f in flagged
        ), f"UNGROUNDED_MECHANISM fired on an annotated sentence: {flagged}"

    def test_does_not_fire_on_not_available_literal(self):
        """Lines containing 'not available in source data' are exempt."""
        findings = _findings(FIXTURE_ROOT / "ungrounded_mechanism")
        for f in findings:
            assert "not available in source data" not in (
                f.get("snippet") or ""
            ).casefold()

    def test_does_not_fire_in_code_block(self):
        """Mechanism verbs inside code blocks must not fire."""
        findings = _findings(FIXTURE_ROOT / "ungrounded_mechanism")
        for f in findings:
            if f["type"] == "UNGROUNDED_MECHANISM":
                assert "```" not in (f.get("snippet") or "")


# ---------------------------------------------------------------------------
# UNANCHORED_SENTENCE (T7)
# ---------------------------------------------------------------------------


class TestUnanchoredSentence:
    """EXPAND-region prose sentence missing [source: <field>] or citing unknown field."""

    def test_fires_on_unannotated_expand_sentence(self):
        """First sentence has no annotation — must fire UNANCHORED_SENTENCE."""
        findings = _findings(FIXTURE_ROOT / "unanchored_sentence")
        flagged = [f for f in findings if f["type"] == "UNANCHORED_SENTENCE"]
        assert len(flagged) >= 1, (
            "Expected at least one UNANCHORED_SENTENCE finding; "
            f"got types: {_flag_types(findings)}"
        )

    def test_does_not_fire_on_valid_annotated_sentence(self):
        """The sentence '[source: name]' cites a known field — must not fire."""
        findings = _findings(FIXTURE_ROOT / "unanchored_sentence")
        flagged = [f for f in findings if f["type"] == "UNANCHORED_SENTENCE"]
        # The fixture sentence ending with "[source: name]" must not appear in findings
        for f in flagged:
            snippet = f.get("snippet") or ""
            assert "[source: name]" not in snippet, (
                f"UNANCHORED_SENTENCE fired on a valid annotated sentence: {snippet!r}"
            )

    def test_fires_on_invalid_source_field(self):
        """Sentence with '[source: fake_field]' cites a non-existent field — must fire."""
        findings = _findings(FIXTURE_ROOT / "unanchored_sentence")
        flagged = [f for f in findings if f["type"] == "UNANCHORED_SENTENCE"]
        assert any(
            "fake_field" in (f.get("actual") or f.get("snippet") or "") for f in flagged
        ), (
            f"Expected 'fake_field' referenced in an UNANCHORED_SENTENCE finding; got: {flagged}"
        )

    def test_does_not_fire_in_code_block(self):
        """Unannotated prose inside code blocks must not fire."""
        findings = _findings(FIXTURE_ROOT / "unanchored_sentence")
        for f in findings:
            if f["type"] == "UNANCHORED_SENTENCE":
                assert "```" not in (f.get("snippet") or "")

    def test_does_not_fire_on_not_available_literal(self):
        """Lines containing 'not available in source data' are exempt."""
        findings = _findings(FIXTURE_ROOT / "unanchored_sentence")
        for f in findings:
            assert "not available in source data" not in (
                f.get("snippet") or ""
            ).casefold()


# ---------------------------------------------------------------------------
# Universal carve-outs (parametrized)
# ---------------------------------------------------------------------------


class TestUniversalCarveouts:
    """Carve-out rules apply across all fixtures: not-available literal and code blocks."""

    @pytest.mark.parametrize(
        "fixture_name",
        [
            "fabricated_drug",
            "fabricated_file_ref",
            "wrong_approval_year",
            "ungrounded_mechanism",
            "unanchored_sentence",
        ],
    )
    def test_not_available_literal_exempt(self, fixture_name: str):
        """No finding of any type should have snippet containing the carve-out literal."""
        findings = _findings(FIXTURE_ROOT / fixture_name)
        for f in findings:
            assert "not available in source data" not in (
                f.get("snippet") or ""
            ).casefold(), (
                f"Flag {f['type']} fired on a 'not available in source data' line "
                f"in fixture '{fixture_name}': {f.get('snippet')!r}"
            )

    @pytest.mark.parametrize(
        "fixture_name",
        [
            "fabricated_drug",
            "fabricated_file_ref",
            "wrong_approval_year",
            "ungrounded_mechanism",
            "unanchored_sentence",
        ],
    )
    def test_code_block_content_exempt(self, fixture_name: str):
        """No finding snippet should begin with ``` (code block delimiter content)."""
        findings = _findings(FIXTURE_ROOT / fixture_name)
        for f in findings:
            assert "```" not in (f.get("snippet") or ""), (
                f"Flag {f['type']} fired on a code-block line in fixture '{fixture_name}': "
                f"{f.get('snippet')!r}"
            )

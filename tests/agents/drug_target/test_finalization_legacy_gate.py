"""RED tests for the DEEPMAST_ALLOW_LEGACY_DRUG_MD env gate in
validate_drug_report_finalization.

Plan §1.2 R7 / §1.3 D10:
  _check_renderer_metadata currently returns MISSING_RENDER_METADATA
  unconditionally at lines 3691-3698 when drug_report_reference_card.json
  exists but drug_report_render.json is absent, even when
  DEEPMAST_ALLOW_LEGACY_DRUG_MD=1.

  After Task #20 implements the gate, setting the env var to "1" must
  suppress that specific issue (legacy flow treated as valid with respect
  to renderer metadata).

Scenarios
---------
(a) env unset + render sidecar missing  → MISSING_RENDER_METADATA emitted   [expected PASS even pre-gate]
(b) env=1   + render sidecar missing    → no MISSING_RENDER_METADATA         [RED: fails until gate lands]
(c) env=1   + both sidecars present     → no MISSING_RENDER_METADATA         [env-independent path]
(d) reference_card itself missing       → no MISSING_RENDER_METADATA         [different validation path]
"""

import json
import shutil
from pathlib import Path

import pytest

from src.agents.drug_target.tools import validate_drug_report_finalization

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FIXTURE_ROOT = Path(__file__).parent / "fixtures"

# Minimal schema-valid content for drug_report_reference_card.json.
# The validator reads this file via report_expansion_schema helpers; a
# minimal JSON object with the required "schema_version" key is sufficient
# to make sidecars_present=True without triggering unrelated validation
# errors.  The real persist_drug_report_reference_card output is a richer
# dict, but these tests only care about the renderer-metadata gate.
_REFERENCE_CARD_MINIMAL = {
    "schema_version": "drug_report_reference_card.v1",
    "template_id": "drug_report.md.j2",
    "markdown_template": "# Placeholder\n",
    "expansion_slots": [],
    "source_hash": "0" * 64,
    "canonical_hash": "0" * 64,
}

# Minimal schema-valid drug_report_render.json (renderer sidecar).
_RENDER_METADATA_MINIMAL = {
    "schema_version": "drug_report_render.v1",
    "renderer": "render_drug_md_from_expansions",
    "mode": "renderer",
    "source_hashes": {
        "reference_card": "0" * 64,
        "report_expansions": "0" * 64,
        "hypothesis_report": None,
        "template": "unused",
    },
    "rendered_drug_md_sha256": "0" * 64,
    "required_slot_count": 0,
    "rendered_slot_count": 0,
    "missing_slots": [],
    "extra_slots": [],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_legacy_evidence_dir(tmp_path: Path) -> Path:
    """Create a minimal valid evidence directory that represents the legacy
    save_drug_md flow: has drug_report_reference_card.json but NOT
    drug_report_render.json.

    Copies required artifacts from the clean fixture so that unrelated
    validation checks (MISSING_REQUIRED_ARTIFACT, TARGET_ASSESSMENT_INVALID,
    etc.) do not interfere with the renderer-gate assertions.
    """
    clean = FIXTURE_ROOT / "clean"
    data_dir = tmp_path / "legacy_run"
    shutil.copytree(clean, data_dir)

    # Add the reference card (makes sidecars_present=True)
    (data_dir / "drug_report_reference_card.json").write_text(
        json.dumps(_REFERENCE_CARD_MINIMAL, indent=2),
        encoding="utf-8",
    )
    # Deliberately do NOT write drug_report_render.json

    return data_dir


def _build_full_renderer_dir(tmp_path: Path) -> Path:
    """Evidence dir with both sidecars present (reference_card + render)."""
    data_dir = _build_legacy_evidence_dir(tmp_path)

    (data_dir / "drug_report_render.json").write_text(
        json.dumps(_RENDER_METADATA_MINIMAL, indent=2),
        encoding="utf-8",
    )
    return data_dir


def _invoke(data_dir: Path) -> dict:
    """Call the @tool wrapper and return the parsed JSON response."""
    raw = validate_drug_report_finalization.invoke({"data_dir": str(data_dir)})
    return json.loads(raw)


def _has_issue(result: dict, code: str) -> bool:
    return any(issue["code"] == code for issue in result.get("issues", []))


# ---------------------------------------------------------------------------
# Scenario (a): env unset + render sidecar missing
# ---------------------------------------------------------------------------


def test_missing_render_metadata_when_env_unset_and_sidecar_absent(
    tmp_path, monkeypatch
):
    """When DEEPMAST_ALLOW_LEGACY_DRUG_MD is unset and drug_report_render.json
    is absent (but reference_card is present), the validator must emit
    MISSING_RENDER_METADATA.

    This documents the current pre-gate behaviour and should pass both before
    and after Task #20.
    """
    # Arrange
    monkeypatch.delenv("DEEPMAST_ALLOW_LEGACY_DRUG_MD", raising=False)
    data_dir = _build_legacy_evidence_dir(tmp_path)

    # Act
    result = _invoke(data_dir)

    # Assert
    assert _has_issue(result, "MISSING_RENDER_METADATA"), (
        "Expected MISSING_RENDER_METADATA when env is unset and render sidecar "
        f"is absent; got issues: {result['issues']}"
    )
    assert result["valid"] is False


# ---------------------------------------------------------------------------
# Scenario (b): env=1 + render sidecar missing  [KEY RED scenario]
# ---------------------------------------------------------------------------


def test_missing_render_metadata_suppressed_when_legacy_env_set_and_sidecar_absent(
    tmp_path, monkeypatch
):
    """When DEEPMAST_ALLOW_LEGACY_DRUG_MD=1 and drug_report_render.json is
    absent (but reference_card is present), the validator must NOT emit
    MISSING_RENDER_METADATA.

    The legacy save_drug_md pipeline does not produce drug_report_render.json;
    the env gate allows it to be treated as valid.

    RED state: this test fails until Task #20 adds the env-var check at
    stage_logic.py:3691-3698.
    """
    # Arrange
    monkeypatch.setenv("DEEPMAST_ALLOW_LEGACY_DRUG_MD", "1")
    data_dir = _build_legacy_evidence_dir(tmp_path)

    # Act
    result = _invoke(data_dir)

    # Assert — the render-metadata gate must be skipped
    missing_render_issues = [
        issue for issue in result.get("issues", [])
        if issue["code"] == "MISSING_RENDER_METADATA"
    ]
    assert missing_render_issues == [], (
        "MISSING_RENDER_METADATA must not be emitted when "
        "DEEPMAST_ALLOW_LEGACY_DRUG_MD=1 and render sidecar is absent; "
        f"got: {missing_render_issues}"
    )


# ---------------------------------------------------------------------------
# Scenario (c): env=1 + both sidecars present
# ---------------------------------------------------------------------------


def test_no_missing_render_metadata_when_both_sidecars_present_and_legacy_env_set(
    tmp_path, monkeypatch
):
    """When DEEPMAST_ALLOW_LEGACY_DRUG_MD=1 AND drug_report_render.json is
    present, MISSING_RENDER_METADATA must not be emitted regardless of the
    env gate (the render sidecar path is fully satisfied).

    This verifies that the env gate does not break the normal renderer path.
    """
    # Arrange
    monkeypatch.setenv("DEEPMAST_ALLOW_LEGACY_DRUG_MD", "1")
    data_dir = _build_full_renderer_dir(tmp_path)

    # Act
    result = _invoke(data_dir)

    # Assert
    assert not _has_issue(result, "MISSING_RENDER_METADATA"), (
        "MISSING_RENDER_METADATA must not appear when render sidecar is "
        f"present; got issues: {result['issues']}"
    )


# ---------------------------------------------------------------------------
# Scenario (d): reference_card itself missing
# ---------------------------------------------------------------------------


def test_no_missing_render_metadata_when_reference_card_absent(
    tmp_path, monkeypatch
):
    """When drug_report_reference_card.json is absent (no sidecars at all),
    the legacy-gate branch (lines 3691-3698) is never reached, so
    MISSING_RENDER_METADATA from that branch must not appear regardless of
    the env value.

    The validator may emit MISSING_RENDER_METADATA via the earlier
    sidecars_absent path (lines 3678-3690), but only if
    DEEPMAST_ALLOW_LEGACY_DRUG_MD is unset.  With env=1 that earlier branch
    returns early with no issues.

    This test sets env=1 to isolate the reference-card-absent behaviour from
    unrelated renderer checks.
    """
    # Arrange
    monkeypatch.setenv("DEEPMAST_ALLOW_LEGACY_DRUG_MD", "1")
    clean = FIXTURE_ROOT / "clean"
    data_dir = tmp_path / "no_reference_card"
    shutil.copytree(clean, data_dir)
    # Ensure no sidecars exist
    for sidecar in (
        "drug_report_reference_card.json",
        "drug_report_render.json",
        "report_expansions.json",
    ):
        (data_dir / sidecar).unlink(missing_ok=True)

    # Act
    result = _invoke(data_dir)

    # Assert — the renderer-gate branch (3691-3698) was not reached
    assert not _has_issue(result, "MISSING_RENDER_METADATA"), (
        "MISSING_RENDER_METADATA from the sidecar-present branch must not "
        "appear when reference_card itself is absent; "
        f"got issues: {result['issues']}"
    )

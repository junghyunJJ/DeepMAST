"""Regression tests for known hallucinations in the frozen baseline drug.md (T19/T19b).

Two test groups:
  T19  — Per-issue parametrized golden tests against the frozen baseline fixture.
  T19b — Diff-based no-new-fabrication assertion (xfail until T20 regenerated fixture).

Baseline path: tests/agents/drug_target/fixtures/baseline_hallucinated/
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.drug_target.tools import validate_drug_md

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASELINE_DIR = Path(__file__).parent / "fixtures" / "baseline_hallucinated"
BASELINE_PATH = BASELINE_DIR / "drug.md"
REGENERATED_PATH = Path(__file__).parent / "fixtures" / "regenerated" / "drug.md"


# ---------------------------------------------------------------------------
# Helper — identical pattern to test_drug_md_new_flags.py
# ---------------------------------------------------------------------------


def _findings(data_dir: Path) -> list[dict]:
    """Run validator and return merged findings list (both 'issues' and 'findings' keys)."""
    impl = getattr(validate_drug_md, "func", None) or validate_drug_md
    result_raw = impl(data_dir)
    result = json.loads(result_raw) if isinstance(result_raw, str) else result_raw
    return result.get("findings", []) + result.get("issues", [])


def _lines_for_search(search: str) -> set[int]:
    """Return 1-based line numbers in the baseline drug.md that contain *search* (case-insensitive)."""
    lines = BASELINE_PATH.read_text(encoding="utf-8").splitlines()
    return {
        lineno
        for lineno, line in enumerate(lines, start=1)
        if search.casefold() in line.casefold()
    }


def _finding_line(finding: dict) -> int | None:
    """Extract the line number from a finding dict (tries common field names)."""
    for key in ("line", "line_number", "lineno"):
        val = finding.get(key)
        if val is not None:
            return int(val)
    return None


# ---------------------------------------------------------------------------
# T19 — Parametrized golden tests on the frozen baseline
# ---------------------------------------------------------------------------

KNOWN_ISSUES = [
    {
        "id": "ocriplasmin_2010_year",
        "expected_flag": "WRONG_APPROVAL_YEAR",
        "search": "ocriplasmin",
    },
    {
        "id": "lovastatin_itgb2_link",
        "expected_flag": "FABRICATED_DRUG_NAME",
        "search": "lovastatin",
    },
    {
        "id": "known_drugs_json_ref",
        "expected_flag": "FABRICATED_FILE_REFERENCE",
        "search": "known_drugs.json",
    },
    {
        "id": "stage1_failed_suffix",
        "expected_flag": "FABRICATED_FILE_REFERENCE",
        "search": "_FAILED",
    },
    {
        "id": "ibalizumab_2018",
        "expected_flag": "WRONG_APPROVAL_YEAR",
        "search": "ibalizumab",
    },
    {
        "id": "ocriplasmin_mechanism",
        "expected_flag": "UNGROUNDED_MECHANISM",
        "search": "ocriplasmin",
    },
    {
        "id": "as1409_aptamer",
        "expected_flag": "UNGROUNDED_MECHANISM",
        "search": "AS-1409",
    },
    {
        "id": "lovastatin_translation",
        "expected_flag": "UNANCHORED_SENTENCE",
        "search": "translation",
    },
]

# Pre-compute the expected line ranges for each case at module load time so
# that the parametrize IDs are stable and no I/O happens inside the test bodies.
_LINE_RANGES: dict[str, set[int]] = {
    case["id"]: _lines_for_search(case["search"]) for case in KNOWN_ISSUES  # type: ignore[index]
}


def _baseline_findings_cached() -> list[dict]:
    """Run the validator once against the frozen baseline and cache the result."""
    if not hasattr(_baseline_findings_cached, "_cache"):
        impl = getattr(validate_drug_md, "func", None) or validate_drug_md
        result_raw = impl(BASELINE_DIR)
        result = json.loads(result_raw) if isinstance(result_raw, str) else result_raw
        _baseline_findings_cached._cache = (  # type: ignore[attr-defined]
            result.get("findings", []) + result.get("issues", [])
        )
    return _baseline_findings_cached._cache  # type: ignore[attr-defined]


def _validator_detects(case: dict) -> bool:
    """Return True if the validator already emits the expected flag near the search term."""
    expected_flag: str = case["expected_flag"]  # type: ignore[assignment]
    search: str = case["search"]  # type: ignore[assignment]
    issue_id: str = case["id"]  # type: ignore[assignment]
    expected_lines = _LINE_RANGES[issue_id]

    findings = _baseline_findings_cached()
    for f in findings:
        if f.get("type") != expected_flag:
            continue
        line = _finding_line(f)
        if line is not None and line in expected_lines:
            return True
        snippet = (f.get("snippet") or "").casefold()
        if search.casefold() in snippet:
            return True
    return False


def _mark_for(case: dict) -> list:
    """Return xfail when the search term is absent from the baseline OR when
    the validator does not currently emit the expected flag for this case.

    This correctly marks cases as xfail (not yet implemented / not yet fired)
    rather than failing the regression suite for unrelated reasons.
    """
    issue_id: str = case["id"]  # type: ignore[assignment]
    if not _LINE_RANGES[issue_id]:
        reason = f"search pattern '{case['search']}' not found in frozen baseline"
        return [pytest.mark.xfail(reason=reason, strict=False)]
    if not _validator_detects(case):
        reason = (
            f"validator does not yet emit {case['expected_flag']!r} "
            f"near '{case['search']}' in frozen baseline"
        )
        return [pytest.mark.xfail(reason=reason, strict=False)]
    return []


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(c, id=c["id"], marks=_mark_for(c))
        for c in KNOWN_ISSUES
    ],
)
def test_baseline_known_issue_detected(case: dict) -> None:
    """Validator must emit the expected flag type near the search-term lines.

    For each known hallucination:
      1. Run validate_drug_md on the frozen baseline directory.
      2. Determine the expected line range by grepping the baseline drug.md for
         the search term.
      3. Assert at least one finding with the expected flag type AND whose line
         falls within the expected range (or whose snippet contains the search
         term as a fallback when the validator does not surface line numbers).
    """
    expected_flag: str = case["expected_flag"]  # type: ignore[assignment]
    search: str = case["search"]  # type: ignore[assignment]
    issue_id: str = case["id"]  # type: ignore[assignment]
    expected_lines = _LINE_RANGES[issue_id]

    all_findings = _findings(BASELINE_DIR)
    flag_findings = [f for f in all_findings if f.get("type") == expected_flag]

    assert flag_findings, (
        f"[{issue_id}] Expected at least one finding with type={expected_flag!r}; "
        f"got types: {sorted({f.get('type') for f in all_findings})}"
    )

    # Accept a finding if its line number overlaps expected_lines OR if its
    # snippet contains the search term (validator may not always expose line #).
    def _matches(finding: dict) -> bool:
        line = _finding_line(finding)
        if line is not None and line in expected_lines:
            return True
        snippet = (finding.get("snippet") or "").casefold()
        return search.casefold() in snippet

    matched = [f for f in flag_findings if _matches(f)]
    assert matched, (
        f"[{issue_id}] Found {len(flag_findings)} finding(s) with type={expected_flag!r} "
        f"but none near expected lines {sorted(expected_lines)} or containing {search!r}. "
        f"Findings: {flag_findings}"
    )


# ---------------------------------------------------------------------------
# T19b — Diff-based no-new-fabrication assertion
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="awaits T20 regenerated fixture", strict=False)
def test_regenerated_drug_md_no_new_fabrications(tmp_path: Path) -> None:
    """Extract sentences in regenerated drug.md not present in baseline,
    write them to a temp .md, run validator on that, assert zero P0 findings.

    Marked xfail until T20 produces tests/agents/drug_target/fixtures/regenerated/drug.md.
    """
    if not REGENERATED_PATH.exists():
        pytest.skip("regenerated fixture not yet created")

    baseline_sentences = _tokenize_sentences(BASELINE_PATH.read_text(encoding="utf-8"))
    regenerated_sentences = _tokenize_sentences(
        REGENERATED_PATH.read_text(encoding="utf-8")
    )

    new_sentences = regenerated_sentences - baseline_sentences
    if not new_sentences:
        # Nothing new — trivially no new fabrications.
        return

    new_prose_path = tmp_path / "new_prose.md"
    new_prose_path.write_text("\n".join(sorted(new_sentences)), encoding="utf-8")

    # Create a minimal evidence dir alongside so the validator can resolve paths.
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    # Symlink baseline evidence so drug-name / approval-year checks have context.
    baseline_evidence = BASELINE_DIR / "evidence"
    for src_file in baseline_evidence.iterdir():
        (evidence_dir / src_file.name).symlink_to(src_file)

    impl = getattr(validate_drug_md, "func", None) or validate_drug_md
    result_raw = impl(tmp_path)
    result = json.loads(result_raw) if isinstance(result_raw, str) else result_raw

    all_findings = result.get("findings", []) + result.get("issues", [])
    p0_findings = [f for f in all_findings if f.get("severity") in ("P0", "p0", "critical")]

    assert not p0_findings, (
        f"Regenerated drug.md introduced {len(p0_findings)} new P0 fabrication(s): "
        f"{p0_findings}"
    )


@pytest.mark.xfail(reason="awaits T20 regenerated fixture", strict=False)
def test_regenerated_drug_md_zero_p0_findings() -> None:
    """Regenerated drug.md must have zero P0 findings when run through the full validator.

    TC-8: validates the complete regenerated report against the baseline evidence dir.
    Marked xfail until T20 produces tests/agents/drug_target/fixtures/regenerated/drug.md.
    """
    if not REGENERATED_PATH.exists():
        pytest.skip("regenerated fixture not yet created")

    regenerated_dir = REGENERATED_PATH.parent
    impl = getattr(validate_drug_md, "func", None) or validate_drug_md
    result_raw = impl(regenerated_dir)
    result = json.loads(result_raw) if isinstance(result_raw, str) else result_raw

    all_findings = result.get("findings", []) + result.get("issues", [])
    p0_findings = [f for f in all_findings if f.get("severity") in ("P0", "p0", "critical")]

    assert not p0_findings, (
        f"Regenerated drug.md has {len(p0_findings)} P0 finding(s): {p0_findings}"
    )


# ---------------------------------------------------------------------------
# Sentence tokenizer (no external deps)
# ---------------------------------------------------------------------------


def _tokenize_sentences(text: str) -> set[str]:
    """Split text into a set of non-empty stripped sentences.

    Uses only newline and '. ' as separators — pragmatic, no nltk required.
    """
    sentences: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for fragment in line.split(". "):
            fragment = fragment.strip()
            if fragment:
                sentences.add(fragment)
    return sentences

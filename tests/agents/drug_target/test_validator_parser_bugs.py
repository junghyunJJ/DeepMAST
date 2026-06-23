"""Regression tests for two validator parser bugs surfaced by GPT-5.4 run
on res_ipf_openai (2026-05-07).

F-D: WRONG_CLASSIFICATION 500-char window leaks into adjacent table rows.
     gene_manifest entry classified as 'validated_target' on its OWN row must
     NOT trigger WRONG_CLASSIFICATION when an adjacent row has 'novel_candidate'.

F-E: FABRICATED_DRUG_NAME catches gene names (e.g. THBS1, SDC2) and reserved
     pipeline phrases (e.g. 'Stage 1') that are NOT drug names.
"""

import json
from pathlib import Path

import pytest

from src.agents.drug_target.tools.stage_logic import (
    _check_fabricated_drug_name,
    _build_drug_allowlist,
    validate_drug_md,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_data_dir(tmp_path: Path, drug_text: str, assessment: dict | None = None,
                    gene_manifest: list | None = None) -> Path:
    """Populate a minimal data_dir and return the path."""
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (tmp_path / "drug.md").write_text(drug_text, encoding="utf-8")
    if assessment is not None:
        (evidence_dir / "assessment_results.json").write_text(
            json.dumps(assessment), encoding="utf-8"
        )
    if gene_manifest is not None:
        (evidence_dir / "gene_manifest.json").write_text(
            json.dumps(gene_manifest), encoding="utf-8"
        )
    return tmp_path


def _run_validate(tmp_path: Path) -> dict:
    """Call validate_drug_md (unwrap @tool) and return parsed JSON result."""
    impl = getattr(validate_drug_md, "func", None) or validate_drug_md
    return json.loads(impl(tmp_path))


def _issues_of_type(result: dict, issue_type: str) -> list[dict]:
    return [i for i in result.get("issues", []) if i.get("type") == issue_type]


def _findings_of_type(result: dict, finding_type: str) -> list[dict]:
    return [f for f in result.get("findings", []) if f.get("type") == finding_type]


# ---------------------------------------------------------------------------
# F-D: WRONG_CLASSIFICATION — line-bounded window
# ---------------------------------------------------------------------------


class TestWrongClassificationLineBounded:
    """F-D: The classification check must use line-level scope, not 500 chars."""

    def test_validated_gene_adjacent_to_novel_row_not_flagged(
        self, tmp_path: Path
    ) -> None:
        """F-D scenario 1 (the GPT-5.4 false positive).

        MUC1 is validated_target on its own druggability matrix row.
        The NEXT row belongs to a different gene with novel_candidate.
        The validator must NOT raise WRONG_CLASSIFICATION for MUC1.

        With the 500-char window the match at MUC1's row leaks into the
        next row, finding 'novel_candidate', and incorrectly fires.
        With line-bounded search only MUC1's own row is inspected.
        """
        drug_text = (
            "## Druggability Matrix\n\n"
            "| Gene | Classification | Priority | Druggable |\n"
            "| --- | --- | --- | --- |\n"
            "| MUC1 | validated_target | high | Yes |\n"
            "| OTHERGENE | novel_candidate | medium | No |\n"
            "\n"
            "### MUC1 — Classification: validated_target | Priority: high\n"
        )
        assessment = {
            "stage3_candidates": [{"gene": "MUC1"}],
            "rubric_assessment": [
                {"gene": "MUC1", "classification": "validated_target"},
            ],
        }
        data_dir = _write_data_dir(tmp_path, drug_text, assessment=assessment)
        result = _run_validate(data_dir)
        wrong = _issues_of_type(result, "WRONG_CLASSIFICATION")
        assert wrong == [], (
            f"WRONG_CLASSIFICATION falsely raised for MUC1 (validated_target) "
            f"due to adjacent novel_candidate row leaking into 500-char window. "
            f"Got: {wrong}"
        )

    def test_genuine_wrong_classification_still_caught(
        self, tmp_path: Path
    ) -> None:
        """F-D scenario 2 (true positive preserved).

        FAKEGENE is validated_target in assessment but drug.md's own row
        says novel_candidate.  WRONG_CLASSIFICATION MUST still fire.
        """
        drug_text = (
            "## Druggability Matrix\n\n"
            "| Gene | Classification | Priority |\n"
            "| --- | --- | --- |\n"
            "| FAKEGENE | novel_candidate | low |\n"
        )
        assessment = {
            "stage3_candidates": [{"gene": "FAKEGENE"}],
            "rubric_assessment": [
                {"gene": "FAKEGENE", "classification": "validated_target"},
            ],
        }
        data_dir = _write_data_dir(tmp_path, drug_text, assessment=assessment)
        result = _run_validate(data_dir)
        wrong = _issues_of_type(result, "WRONG_CLASSIFICATION")
        assert len(wrong) >= 1, (
            "WRONG_CLASSIFICATION was NOT raised for FAKEGENE whose drug.md row "
            "says novel_candidate but assessment says validated_target. "
            "The true-positive detection must be preserved."
        )


# ---------------------------------------------------------------------------
# F-E: FABRICATED_DRUG_NAME — exclude gene names and reserved phrases
# ---------------------------------------------------------------------------


class TestFabricatedDrugNameExclusions:
    """F-E: Gene symbols and pipeline-reserved phrases must not be flagged."""

    def test_gene_symbol_in_gene_manifest_not_flagged(self, tmp_path: Path) -> None:
        """F-E scenario 1 (the THBS1/SDC2 false positive).

        THBS1 is a gene in gene_manifest.json.  When it appears in prose
        like 'THBS1-CD47 interaction contexts', it must NOT be flagged as
        FABRICATED_DRUG_NAME because it is a gene symbol, not a drug.

        Before the fix, THBS1 is absent from drug_allowlist (not in
        resolved_drugs.json and no stage3_THBS1.json), so it triggers.
        After the fix, gene_manifest.json symbols are loaded into the
        allowlist and THBS1 is excluded.
        """
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        gene_manifest = [
            {"symbol": "THBS1", "is_selected_top3": False},
            {"symbol": "SDC2", "is_selected_top3": False},
        ]
        (evidence_dir / "gene_manifest.json").write_text(
            json.dumps(gene_manifest), encoding="utf-8"
        )

        allowlist = _build_drug_allowlist(evidence_dir, [])
        assert "thbs1" in allowlist, (
            "THBS1 must be in the drug allowlist after loading gene_manifest.json. "
            "Gene symbols must be excluded from FABRICATED_DRUG_NAME checks."
        )

    def test_gene_symbol_prose_not_flagged_end_to_end(self, tmp_path: Path) -> None:
        """F-E scenario 1b (end-to-end integration).

        A drug.md prose line mentioning THBS1 must not generate
        FABRICATED_DRUG_NAME when THBS1 is in gene_manifest.json.
        """
        drug_text = (
            "## MUC1 Deep Dive\n\n"
            "Network analysis highlights THBS1-CD47 and FN1-SDC2 interaction "
            "contexts in the Stage 1 filter as key pathway nodes.\n"
        )
        gene_manifest = [
            {"symbol": "THBS1", "is_selected_top3": False},
            {"symbol": "FN1", "is_selected_top3": False},
            {"symbol": "SDC2", "is_selected_top3": False},
            {"symbol": "CD47", "is_selected_top3": False},
        ]
        data_dir = _write_data_dir(
            tmp_path, drug_text, gene_manifest=gene_manifest
        )
        result = _run_validate(data_dir)
        fabricated = _findings_of_type(result, "FABRICATED_DRUG_NAME")
        # Filter to only the gene-name false positives; allow other potential finds
        gene_false_positives = [
            f for f in fabricated
            if any(g in f.get("actual", "") for g in ("THBS1", "FN1", "SDC2", "CD47"))
        ]
        assert gene_false_positives == [], (
            f"Gene symbols THBS1/FN1/SDC2/CD47 were falsely flagged as "
            f"FABRICATED_DRUG_NAME. Got: {gene_false_positives}"
        )

    def test_stage_phrase_not_flagged(self, tmp_path: Path) -> None:
        """F-E scenario 2 (the 'Stage 1' false positive).

        'Stage 1 filter' appears in prose.  'Stage' or 'Stage 1' must NOT
        be flagged as FABRICATED_DRUG_NAME because it is a pipeline
        reserved phrase, not a drug name.

        Before the fix, 'Stage' matches _DRUG_NAME_RE (Title-case 2+ chars)
        and is absent from drug_allowlist, triggering a false positive.
        After the fix, 'Stage' is in _DRUG_NAME_STOPLIST.
        """
        line = "Interaction contexts in the Stage 1 filter are key pathway nodes."
        drug_allowlist: frozenset[str] = frozenset()
        findings = _check_fabricated_drug_name(line, 1, drug_allowlist)
        stage_hits = [f for f in findings if "Stage" in f.get("actual", "")]
        assert stage_hits == [], (
            f"'Stage 1' was falsely flagged as FABRICATED_DRUG_NAME. "
            f"'Stage' must be in _DRUG_NAME_STOPLIST. Got: {stage_hits}"
        )

    @pytest.mark.parametrize(
        ("line", "blocked_terms"),
        [
            (
                "These recommendations are grounded in the available spatial, "
                "Census, OpenTargets, and ChEMBL evidence. They should be read "
                "as follow-up priorities.",
                {"They"},
            ),
            (
                "Follow-up interpretation: Treat them as the strongest "
                "interest-cell / malignant-cell proxy follow-up candidates.",
                {"Treat"},
            ),
            (
                "These recommendations cite target-disease or actionability "
                "evidence but no Stage 1/spatial grounding. Treat them as "
                "gene-level follow-up candidates.",
                {"Treat"},
            ),
        ],
    )
    def test_followup_guidance_words_not_flagged(
        self,
        line: str,
        blocked_terms: set[str],
    ) -> None:
        """F-E scenario 4: ordinary guidance words are not drug names.

        Follow-up recommendation prose can contain sentence-initial or
        post-period words like "They" and "Treat". These words must not be
        interpreted as fabricated drug names.
        """
        findings = _check_fabricated_drug_name(line, 1, frozenset())
        actual_terms = {
            finding.get("actual", "").split(" not found", 1)[0]
            for finding in findings
        }

        assert actual_terms.isdisjoint(blocked_terms), (
            f"Guidance words were falsely flagged as FABRICATED_DRUG_NAME. "
            f"Blocked={blocked_terms}; findings={findings}"
        )

    def test_celltype_resolution_labels_added_to_fabricated_drug_allowlist(
        self,
        tmp_path: Path,
    ) -> None:
        """F-E scenario 5: resolved cell-type labels are not drug names.

        The breast cancer run writes celltype_resolution.json with
        "Prolif Invasive Tumor" resolved to "malignant cell". Both labels are
        context labels, not drug names, and must be excluded from
        FABRICATED_DRUG_NAME checks.
        """
        evidence_dir = tmp_path / "evidence"
        evidence_dir.mkdir()
        (evidence_dir / "celltype_resolution.json").write_text(
            json.dumps(
                {
                    "interest_celltypes": ["Prolif Invasive Tumor"],
                    "primary_input_celltype": "Prolif Invasive Tumor",
                    "primary_resolved_celltype": "malignant cell",
                    "matches": [
                        {
                            "input_celltype": "Prolif Invasive Tumor",
                            "matched_celltype": "malignant cell",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        allowlist = _build_drug_allowlist(evidence_dir, [])

        assert "prolif invasive tumor" in allowlist
        assert "malignant cell" in allowlist

    def test_celltype_resolution_labels_not_flagged_end_to_end(
        self,
        tmp_path: Path,
    ) -> None:
        """F-E scenario 6: current breast-cancer guidance sentence is clean."""
        drug_text = (
            "## Evidence-Grounded Follow-up Recommendations\n\n"
            "These recommendations cite Stage 1 Census support for same-cell "
            "coexpression enrichment in the resolved context (Prolif Invasive "
            "Tumor; Census proxy: malignant cell). Treat them as the strongest "
            "interest-cell / malignant-cell proxy follow-up candidates, while "
            "reserving causal mechanism claims for downstream validation.\n"
        )
        data_dir = _write_data_dir(tmp_path, drug_text)
        evidence_dir = data_dir / "evidence"
        (evidence_dir / "celltype_resolution.json").write_text(
            json.dumps(
                {
                    "interest_celltypes": ["Prolif Invasive Tumor"],
                    "primary_input_celltype": "Prolif Invasive Tumor",
                    "primary_resolved_celltype": "malignant cell",
                    "matches": [
                        {
                            "input_celltype": "Prolif Invasive Tumor",
                            "matched_celltype": "malignant cell",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = _run_validate(data_dir)
        fabricated = _findings_of_type(result, "FABRICATED_DRUG_NAME")
        forbidden_actuals = [
            finding.get("actual", "")
            for finding in fabricated
            if any(
                token in finding.get("actual", "")
                for token in ("Prolif Invasive Tumor", "malignant cell", "Treat")
            )
        ]

        assert forbidden_actuals == [], (
            "Cell-type labels and guidance verbs were falsely flagged as "
            f"FABRICATED_DRUG_NAME. Got: {forbidden_actuals}"
        )

    def test_genuine_fabricated_drug_still_caught(self, tmp_path: Path) -> None:
        """F-E scenario 3 (true positive preserved).

        A genuinely fabricated drug name (not in any evidence file, not a
        gene symbol, not a reserved phrase) MUST still be flagged.
        """
        line = "Treatment with FAKEDRUG-X-99 showed significant improvement."
        drug_allowlist: frozenset[str] = frozenset()  # nothing allowed
        findings = _check_fabricated_drug_name(line, 1, drug_allowlist)
        fabricated = [f for f in findings if "FAKEDRUG" in f.get("actual", "")]
        assert len(fabricated) >= 1, (
            "FAKEDRUG-X-99 (a genuinely fabricated name absent from all evidence) "
            "was NOT flagged as FABRICATED_DRUG_NAME. True-positive detection "
            "must be preserved."
        )

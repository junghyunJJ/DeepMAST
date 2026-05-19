"""T1 RED: filter_hypothesis_evidence_files drops nonexistent evidence_files entries.

The hypothesis_writer occasionally emits `evidence_files` entries that reference
files that do not exist on disk (e.g. `known_drugs.json`). Before SUMMARIZER
consumes hypothesis_report.json, a pipeline-level filter must rewrite the file
in place, dropping any entry whose target path does not exist under
`<data_dir>/evidence/`.

Tests cover:
- Mixed existent/nonexistent entries -> nonexistent dropped, file rewritten.
- All entries exist -> file untouched, return value 0.
- Missing hypothesis_report.json -> no-op, return value 0.
- Both legacy list shape and current dict shape ({"hypotheses": [...]}).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.agents.drug_target.subagents.configs import (
    filter_hypothesis_evidence_files,
)
from src.agents.drug_target.tools import load_evidence_files


def _write_evidence(
    tmp_path: Path, *, existing_files: list[str], hyp_payload: object
) -> str:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    for fname in existing_files:
        (evidence_dir / fname).write_text("{}")
    (evidence_dir / "hypothesis_report.json").write_text(json.dumps(hyp_payload))
    return str(tmp_path)


def test_drops_nonexistent_entries_dict_shape(tmp_path: Path) -> None:
    """Current pipeline shape: {"hypotheses": [{evidence_files: [...]}]}."""
    payload = {
        "hypotheses": [
            {
                "hypothesis": "H1",
                "evidence_files": [
                    "stage3_TGFB1.json",
                    "known_drugs.json",  # NONEXISTENT
                    "stage1_pair_001.json",
                ],
            },
            {
                "hypothesis": "H2",
                "evidence_files": [
                    "stage3_MUC1.json",
                    "stage_extra.json",  # NONEXISTENT
                ],
            },
        ]
    }
    data_dir = _write_evidence(
        tmp_path,
        existing_files=[
            "stage3_TGFB1.json",
            "stage1_pair_001.json",
            "stage3_MUC1.json",
        ],
        hyp_payload=payload,
    )

    dropped = filter_hypothesis_evidence_files(data_dir)

    assert dropped == 2

    rewritten = json.loads(
        (Path(data_dir) / "evidence" / "hypothesis_report.json").read_text()
    )
    hyps = rewritten["hypotheses"]
    assert hyps[0]["evidence_files"] == [
        "stage3_TGFB1.json",
        "stage1_pair_001.json",
    ]
    assert hyps[1]["evidence_files"] == ["stage3_MUC1.json"]


def test_drops_nonexistent_entries_list_shape(tmp_path: Path) -> None:
    """Legacy/test fixture shape: top-level list of hypothesis dicts."""
    payload = [
        {
            "hypothesis": "H1",
            "evidence_files": [
                "stage3_TGFB1.json",
                "known_drugs.json",  # NONEXISTENT
            ],
        }
    ]
    data_dir = _write_evidence(
        tmp_path,
        existing_files=["stage3_TGFB1.json"],
        hyp_payload=payload,
    )

    dropped = filter_hypothesis_evidence_files(data_dir)

    assert dropped == 1
    rewritten = json.loads(
        (Path(data_dir) / "evidence" / "hypothesis_report.json").read_text()
    )
    assert rewritten[0]["evidence_files"] == ["stage3_TGFB1.json"]


def test_no_drop_when_all_exist_does_not_rewrite(tmp_path: Path) -> None:
    payload = {
        "hypotheses": [
            {"hypothesis": "H1", "evidence_files": ["stage3_TGFB1.json"]}
        ]
    }
    data_dir = _write_evidence(
        tmp_path,
        existing_files=["stage3_TGFB1.json"],
        hyp_payload=payload,
    )
    hyp_path = Path(data_dir) / "evidence" / "hypothesis_report.json"
    mtime_before = hyp_path.stat().st_mtime_ns

    dropped = filter_hypothesis_evidence_files(data_dir)

    assert dropped == 0
    # When nothing was dropped the file must not be rewritten.
    assert hyp_path.stat().st_mtime_ns == mtime_before


def test_missing_hypothesis_report_is_noop(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    assert filter_hypothesis_evidence_files(str(tmp_path)) == 0


def test_missing_evidence_dir_is_noop(tmp_path: Path) -> None:
    # data_dir without evidence/ subdir
    assert filter_hypothesis_evidence_files(str(tmp_path)) == 0


def test_handles_missing_evidence_files_key(tmp_path: Path) -> None:
    """Hypothesis without evidence_files key should be left untouched."""
    payload = {"hypotheses": [{"hypothesis": "H1"}]}
    data_dir = _write_evidence(
        tmp_path, existing_files=[], hyp_payload=payload
    )
    assert filter_hypothesis_evidence_files(data_dir) == 0


def test_drops_nonexistent_entries_from_evidence_references_key(
    tmp_path: Path,
) -> None:
    """The hypothesis_writer also emits the ``evidence_references`` key
    (different name, same semantics). The filter must clean it the same way."""
    payload = {
        "hypotheses": [
            {
                "hypothesis": "H1",
                "evidence_references": [
                    "stage3_ITGB2.json",
                    "ot_ITGB2.json",  # NONEXISTENT
                    "known_drugs.json",  # NONEXISTENT
                ],
            }
        ]
    }
    data_dir = _write_evidence(
        tmp_path, existing_files=["stage3_ITGB2.json"], hyp_payload=payload
    )

    dropped = filter_hypothesis_evidence_files(data_dir)

    assert dropped == 2
    rewritten = json.loads(
        (Path(data_dir) / "evidence" / "hypothesis_report.json").read_text()
    )
    assert rewritten["hypotheses"][0]["evidence_references"] == [
        "stage3_ITGB2.json"
    ]


def test_drops_failed_suffix_entries(tmp_path: Path) -> None:
    """Entries ending with ``_FAILED`` are always invalid in drug.md and must
    be dropped even if the underlying file (without suffix) exists."""
    payload = {
        "hypotheses": [
            {
                "hypothesis": "H6",
                "evidence_references": [
                    "stage3_CD4.json",
                    "stage1_HLA-DPA1--CD4.json_FAILED",  # _FAILED suffix
                    "stage1_HLA-DPB1--CD4.json_FAILED",  # _FAILED suffix
                ],
            }
        ]
    }
    data_dir = _write_evidence(
        tmp_path,
        # Even if a _FAILED-suffixed file existed on disk it should still be
        # dropped — the suffix itself is the marker.
        existing_files=[
            "stage3_CD4.json",
            "stage1_HLA-DPA1--CD4.json_FAILED",
        ],
        hyp_payload=payload,
    )

    dropped = filter_hypothesis_evidence_files(data_dir)

    assert dropped == 2
    rewritten = json.loads(
        (Path(data_dir) / "evidence" / "hypothesis_report.json").read_text()
    )
    assert rewritten["hypotheses"][0]["evidence_references"] == [
        "stage3_CD4.json"
    ]


def test_strips_failed_suffix_inside_prose_fields(tmp_path: Path) -> None:
    """The 122b model echoes ``stage1_HLA-DPA1--CD4.json_FAILED`` from the
    ``falsifiable_prediction`` prose verbatim. The list-key filter alone does
    not catch this. The prose pass must rewrite the suffix to ``.json``."""
    payload = {
        "hypotheses": [
            {
                "hypothesis": "From stage1_X--Y.json_FAILED, fibroblast...",
                "evidence_references": ["stage3_CD4.json"],
                "falsifiable_prediction": (
                    "From stage1_HLA-DPA1--CD4.json_FAILED, CD4+ T cell "
                    "depletion will reduce fibroblast proliferation."
                ),
                "validation_approach": (
                    "Use stage1_HLA-DPB1--CD4.json_FAILED as a guide."
                ),
            }
        ]
    }
    data_dir = _write_evidence(
        tmp_path, existing_files=["stage3_CD4.json"], hyp_payload=payload
    )

    mutations = filter_hypothesis_evidence_files(data_dir)

    # 3 prose suffix strips (hypothesis + falsifiable_prediction +
    # validation_approach); list-key did not need to drop anything.
    assert mutations == 3
    rewritten = json.loads(
        (Path(data_dir) / "evidence" / "hypothesis_report.json").read_text()
    )
    h = rewritten["hypotheses"][0]
    assert "_FAILED" not in h["hypothesis"]
    assert "_FAILED" not in h["falsifiable_prediction"]
    assert "_FAILED" not in h["validation_approach"]
    # The .json reference itself is preserved (suffix only is removed).
    assert "stage1_HLA-DPA1--CD4.json" in h["falsifiable_prediction"]


def test_filters_both_keys_in_same_hypothesis(tmp_path: Path) -> None:
    """A single hypothesis may have both keys; both must be filtered."""
    payload = {
        "hypotheses": [
            {
                "hypothesis": "Hmix",
                "evidence_files": ["stage3_TGFB1.json", "missing_a.json"],
                "evidence_references": [
                    "stage3_TGFB1.json",
                    "missing_b.json",
                ],
            }
        ]
    }
    data_dir = _write_evidence(
        tmp_path, existing_files=["stage3_TGFB1.json"], hyp_payload=payload
    )

    dropped = filter_hypothesis_evidence_files(data_dir)

    assert dropped == 2
    rewritten = json.loads(
        (Path(data_dir) / "evidence" / "hypothesis_report.json").read_text()
    )
    h = rewritten["hypotheses"][0]
    assert h["evidence_files"] == ["stage3_TGFB1.json"]
    assert h["evidence_references"] == ["stage3_TGFB1.json"]


def test_load_hypothesis_scope_exposes_failed_stage1_as_contrast_only(
    tmp_path: Path,
) -> None:
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "assessment_results.json").write_text(
        json.dumps({"stage3_candidates": [{"gene": "FN1"}, {"gene": "CD4"}]}),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_filter_results.json").write_text(
        json.dumps(
            [
                {"ligand": "FN1", "receptor": "CD4", "passed": True},
                {
                    "ligand": "FN1",
                    "receptor": "PLAUR",
                    "passed": False,
                    "failed_criteria": ["census_coexpression_p_value"],
                    "reason": "insufficient coexpression",
                },
            ]
        ),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_FN1--CD4.json").write_text(
        json.dumps({"payload": "full passed support evidence"}),
        encoding="utf-8",
    )
    (evidence_dir / "stage1_FN1--PLAUR.json").write_text(
        json.dumps(
            {
                "payload": "must not be exposed",
                "ligand": "FN1",
                "receptor": "PLAUR",
                "passed": False,
                "failed_criteria": ["census_coexpression_p_value"],
            }
        ),
        encoding="utf-8",
    )
    (evidence_dir / "stage3_FN1.json").write_text("{}", encoding="utf-8")
    (evidence_dir / "stage3_CD4.json").write_text("{}", encoding="utf-8")

    result = json.loads(
        load_evidence_files.invoke({"data_dir": str(tmp_path), "scope": "hypothesis"})
    )

    assert "stage1_FN1--CD4.json" in result["files"]
    assert "stage1_FN1--PLAUR.json" not in result["files"]
    assert result["contrast_evidence"]["stage1_FN1--PLAUR.json"] == {
        "filename": "stage1_FN1--PLAUR.json",
        "role": "negative_contrast",
        "eligible_as_support": False,
        "ligand": "FN1",
        "receptor": "PLAUR",
        "pair_key": "FN1--PLAUR",
        "passed": False,
        "failed_criteria": ["census_coexpression_p_value"],
        "reason": "insufficient coexpression",
        "citation_policy": "metadata-only negative contrast; do not cite as primary/support evidence",
    }
    assert "_FAILED" not in json.dumps(result["contrast_evidence"])

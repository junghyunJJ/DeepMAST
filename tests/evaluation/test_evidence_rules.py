"""Rules for evidence files used by Core Suite."""

from __future__ import annotations

from pathlib import Path

from evaluation.schema import (
    ALLOWED_DEEP_INTERPRETER_PARTS,
    EvidenceFile,
    load_yaml,
)


def _evidence_files() -> list[Path]:
    return [
        p
        for p in sorted(Path("evaluation/evidence").glob("*.yaml"))
        if p.name != "_template.yaml"
    ]


def test_evidence_files_exist_for_three_datasets():
    files = _evidence_files()
    assert len(files) == 3


def test_each_evidence_file_has_exactly_eight_claims_and_two_pmids():
    for path in _evidence_files():
        ef = EvidenceFile.from_dict(load_yaml(path))
        assert len(ef.claims) == 8
        parts = {claim.deep_interpreter_part for claim in ef.claims}
        assert parts == ALLOWED_DEEP_INTERPRETER_PARTS
        for claim in ef.claims:
            assert claim.pmid_primary
            assert claim.pmid_support

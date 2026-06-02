from __future__ import annotations

import json
from pathlib import Path

from src.agents.drug_target.subagents import prompts
from src.agents.drug_target.tools.evidence_loader import load_evidence_files


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_hypothesis_scope_loads_celltype_resolution_json(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    _write_json(
        evidence / "assessment_results.json",
        {"stage3_candidates": [{"gene": "FN1"}]},
    )
    _write_json(evidence / "gene_manifest.json", {"genes": ["FN1"]})
    _write_json(evidence / "known_drugs.json", {"disease": "pulmonary fibrosis"})
    _write_json(evidence / "stage1_filter_results.json", [])
    _write_json(
        evidence / "celltype_resolution.json",
        {
            "interest_celltypes": ["AT2", "Transitional AT2"],
            "primary_resolved_celltype": "pulmonary alveolar type 2 cell",
            "matches": [
                {
                    "input_celltype": "AT2",
                    "matched_celltype": "pulmonary alveolar type 2 cell",
                    "match_mode": "alias",
                    "lost_modifiers": [],
                },
                {
                    "input_celltype": "Transitional AT2",
                    "matched_celltype": "pulmonary alveolar type 2 cell",
                    "match_mode": "state_stripped_alias",
                    "lost_modifiers": ["transitional"],
                },
            ],
        },
    )

    raw = load_evidence_files.invoke({"data_dir": str(tmp_path), "scope": "hypothesis"})
    result = json.loads(raw)

    assert result["errors"] == []
    assert "celltype_resolution.json" in result["files"]
    loaded = result["files"]["celltype_resolution.json"]
    assert loaded["interest_celltypes"] == ["AT2", "Transitional AT2"]
    assert loaded["primary_resolved_celltype"] == "pulmonary alveolar type 2 cell"


def test_hypothesis_prompt_requires_interest_celltype_focus() -> None:
    text = prompts.HYPOTHESIS_WRITER_PROMPT

    assert "celltype_resolution.json" in text
    assert "interest_celltypes" in text
    assert "lost_modifiers" in text
    assert "biological_entities.cell_types" in text
    assert "Do not claim that Census separately validated a lost state modifier" in text
    assert "AT2" in text
    assert "Transitional AT2" in text

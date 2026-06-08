from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmarks import run_rag_handoff_qc as runner


def _paper(
    pmid: str,
    bucket: str,
    *,
    direct_lr_pairs: list[dict[str, str]] | None = None,
    context_lr_pairs: list[dict[str, str]] | None = None,
    journal_quality: float = 0.5,
) -> dict:
    return {
        "pmid": pmid,
        "title": f"Paper {pmid}",
        "abstract": f"Abstract {pmid} TGFB1 TGFBR2 breast cancer MAPK Fibroblast",
        "journal_quality": journal_quality,
        "evidence_bucket": bucket,
        "supported_lr_pairs": direct_lr_pairs or context_lr_pairs or [],
        "direct_lr_pairs": direct_lr_pairs or [],
        "context_lr_pairs": context_lr_pairs or [],
    }


def _candidate_payload() -> dict:
    pair = {"ligand": "TGFB1", "receptor": "TGFBR2"}
    return {
        "schema_version": "deep_interpreter_literature_candidates_v1",
        "inputs": {
            "disease": "breast cancer",
            "lr_pairs": [pair],
            "pathways": ["MAPK"],
            "celltypes": ["Fibroblast"],
        },
        "source": {"total_papers": 4, "unique_papers": 4},
        "counts": {
            "direct_lr_evidence": 1,
            "receptor_pathway_context_evidence": 1,
            "disease_only_background": 1,
            "rejected_weak_evidence": 1,
        },
        "bucket_order": [
            "direct_lr_evidence",
            "receptor_pathway_context_evidence",
            "disease_only_background",
            "rejected_weak_evidence",
        ],
        "papers": [
            _paper("direct", "direct_lr_evidence", direct_lr_pairs=[pair]),
            _paper("context", "receptor_pathway_context_evidence", context_lr_pairs=[pair]),
            _paper("background", "disease_only_background"),
            _paper("rejected", "rejected_weak_evidence"),
        ],
    }


def test_rag_handoff_qc_writes_single_policy_outputs(tmp_path: Path) -> None:
    candidate_path = tmp_path / "source" / "citation_candidates.json"
    candidate_path.parent.mkdir()
    candidate_path.write_text(json.dumps(_candidate_payload()), encoding="utf-8")
    output_dir = tmp_path / "out"

    exit_code = runner.main(
        [
            "--candidate-path",
            str(candidate_path),
            "--output-dir",
            str(output_dir),
            "--cap",
            "100",
        ]
    )

    assert exit_code == 0
    required = [
        "RAG_HANDOFF_QC_KO.md",
        "rag_handoff_qc_summary.csv",
        "rag_handoff_pair_coverage.csv",
        "rag_handoff_selected_papers.csv",
        "run_config.json",
    ]
    for filename in required:
        assert (output_dir / filename).exists()

    rows = list(csv.DictReader((output_dir / "rag_handoff_qc_summary.csv").open()))
    assert len(rows) == 1
    row = rows[0]
    assert row["policy"] == "direct_all_pair_round_robin_100"
    assert int(row["eligible_count"]) == 2
    assert int(row["selected_count"]) == 2
    assert row["eligible_all_selected"] == "True"
    assert int(row["unused_capacity_count"]) == 98
    assert int(row["available_disease_only_count"]) == 1
    assert int(row["available_rejected_count"]) == 1
    assert int(row["leakage_count"]) == 0

    handoff_path = output_dir / "selected_papers" / "source" / "papers.json"
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    assert handoff["policy"]["name"] == "direct_all_pair_round_robin_100"
    assert handoff["policy"]["cap"] == 100
    assert handoff["policy"]["eligible_all_selected"] is True
    assert [paper["pmid"] for paper in handoff["papers"]] == ["direct", "context"]

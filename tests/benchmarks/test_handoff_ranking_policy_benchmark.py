from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmarks import run_handoff_ranking_policy_benchmark as runner


def _paper(
    pmid: str,
    bucket: str,
    *,
    title: str | None = None,
    abstract: str | None = None,
    journal_quality: float = 0.5,
    supported_lr_pairs: list[dict[str, str]] | None = None,
    direct_lr_pairs: list[dict[str, str]] | None = None,
    context_lr_pairs: list[dict[str, str]] | None = None,
) -> dict:
    return {
        "pmid": pmid,
        "title": title or f"Paper {pmid}",
        "abstract": abstract or "",
        "journal_quality": journal_quality,
        "evidence_bucket": bucket,
        "supported_lr_pairs": supported_lr_pairs or [],
        "direct_lr_pairs": direct_lr_pairs or [],
        "context_lr_pairs": context_lr_pairs or [],
    }


def _candidate_payload(papers: list[dict]) -> dict:
    counts = {
        "direct_lr_evidence": 0,
        "receptor_pathway_context_evidence": 0,
        "disease_only_background": 0,
        "rejected_weak_evidence": 0,
    }
    for paper in papers:
        counts[paper["evidence_bucket"]] += 1
    return {
        "schema_version": "deep_interpreter_literature_candidates_v1",
        "inputs": {
            "disease": "breast cancer",
            "lr_pairs": [
                {"ligand": "TGFB1", "receptor": "TGFBR2"},
                {"ligand": "CXCL12", "receptor": "CD4"},
            ],
            "pathways": ["MAPK", "PI3K"],
            "celltypes": ["Macrophage"],
        },
        "source": {"total_papers": len(papers), "unique_papers": len(papers)},
        "counts": counts,
        "bucket_order": [
            "direct_lr_evidence",
            "receptor_pathway_context_evidence",
            "disease_only_background",
            "rejected_weak_evidence",
        ],
        "papers": papers,
    }


def test_active_policies_are_limited_to_first_pass_set() -> None:
    assert runner.ACTIVE_POLICIES == (
        "baseline_current",
        "bucket_lr_coverage",
        "bucket_lr_coverage_journal_tiebreak",
    )


def test_baseline_excludes_ineligible_buckets_and_preserves_bucket_order() -> None:
    payload = _candidate_payload(
        [
            _paper("context-1", "receptor_pathway_context_evidence"),
            _paper("rejected", "rejected_weak_evidence"),
            _paper("direct-1", "direct_lr_evidence"),
            _paper("background", "disease_only_background"),
            _paper("context-2", "receptor_pathway_context_evidence"),
            _paper("direct-2", "direct_lr_evidence"),
        ]
    )

    selected = runner.select_policy_papers(
        payload,
        policy="baseline_current",
        cap=40,
    )

    assert [paper["pmid"] for paper in selected] == [
        "direct-1",
        "direct-2",
        "context-1",
        "context-2",
    ]
    assert all(
        paper["evidence_bucket"]
        in {"direct_lr_evidence", "receptor_pathway_context_evidence"}
        for paper in selected
    )


def test_coverage_policy_keeps_bucket_priority_then_ranks_by_lr_and_entities() -> None:
    payload = _candidate_payload(
        [
            _paper(
                "direct-low",
                "direct_lr_evidence",
                abstract="TGFB1 appears in breast cancer.",
                supported_lr_pairs=[{"ligand": "TGFB1", "receptor": "TGFBR2"}],
            ),
            _paper(
                "context-rich",
                "receptor_pathway_context_evidence",
                abstract="MAPK PI3K macrophage breast cancer context.",
            ),
            _paper(
                "direct-high",
                "direct_lr_evidence",
                abstract="TGFB1 TGFBR2 CXCL12 CD4 MAPK breast cancer.",
                supported_lr_pairs=[
                    {"ligand": "TGFB1", "receptor": "TGFBR2"},
                    {"ligand": "CXCL12", "receptor": "CD4"},
                ],
            ),
        ]
    )

    selected = runner.select_policy_papers(
        payload,
        policy="bucket_lr_coverage",
        cap=40,
    )

    assert [paper["pmid"] for paper in selected] == [
        "direct-high",
        "direct-low",
        "context-rich",
    ]


def test_journal_policy_uses_journal_quality_only_as_tiebreaker() -> None:
    payload = _candidate_payload(
        [
            _paper(
                "context-a",
                "receptor_pathway_context_evidence",
                abstract="MAPK breast cancer context.",
                journal_quality=0.1,
            ),
            _paper(
                "context-b",
                "receptor_pathway_context_evidence",
                abstract="PI3K breast cancer context.",
                journal_quality=0.9,
            ),
            _paper(
                "context-c",
                "receptor_pathway_context_evidence",
                abstract="MAPK PI3K macrophage breast cancer context.",
                journal_quality=0.0,
            ),
        ]
    )

    coverage_only = runner.select_policy_papers(
        payload,
        policy="bucket_lr_coverage",
        cap=40,
    )
    journal_tiebreak = runner.select_policy_papers(
        payload,
        policy="bucket_lr_coverage_journal_tiebreak",
        cap=40,
    )

    assert [paper["pmid"] for paper in coverage_only] == [
        "context-c",
        "context-a",
        "context-b",
    ]
    assert [paper["pmid"] for paper in journal_tiebreak] == [
        "context-c",
        "context-b",
        "context-a",
    ]


def test_metrics_include_direct_availability_leakage_coverage_and_concentration() -> None:
    payload = _candidate_payload(
        [
            _paper(
                "direct",
                "direct_lr_evidence",
                abstract="TGFB1 TGFBR2 MAPK macrophage breast cancer.",
                supported_lr_pairs=[{"ligand": "TGFB1", "receptor": "TGFBR2"}],
                direct_lr_pairs=[{"ligand": "TGFB1", "receptor": "TGFBR2"}],
            ),
            _paper(
                "context",
                "receptor_pathway_context_evidence",
                abstract="CXCL12 CD4 PI3K breast cancer.",
                supported_lr_pairs=[{"ligand": "CXCL12", "receptor": "CD4"}],
                context_lr_pairs=[{"ligand": "CXCL12", "receptor": "CD4"}],
            ),
            _paper("background", "disease_only_background"),
            _paper("rejected", "rejected_weak_evidence"),
        ]
    )
    selected = runner.select_policy_papers(
        payload,
        policy="bucket_lr_coverage",
        cap=40,
    )

    row = runner.summarize_selection(
        candidate_id="case",
        candidate_path=Path("case/citation_candidates.json"),
        payload=payload,
        policy="bucket_lr_coverage",
        selected=selected,
        cap=40,
    )

    assert row["available_direct_count"] == 1
    assert row["selected_direct_count"] == 1
    assert row["selected_context_count"] == 1
    assert row["leakage_count"] == 0
    assert row["lr_pairs_covered_count"] == 2
    assert row["genes_covered_count"] == 4
    assert row["pathways_covered_count"] == 2
    assert row["celltypes_covered_count"] == 1
    assert row["distinct_receptors"] == 2
    assert row["receptor_hhi"] == 0.5
    assert row["distinct_pathways"] == 2


def test_cli_writes_required_outputs_and_policy_papers_json(tmp_path: Path) -> None:
    candidate_path = tmp_path / "source" / "citation_candidates.json"
    candidate_path.parent.mkdir()
    candidate_path.write_text(
        json.dumps(
            _candidate_payload(
                [
                    _paper("direct", "direct_lr_evidence"),
                    _paper("context", "receptor_pathway_context_evidence"),
                    _paper("background", "disease_only_background"),
                    _paper("rejected", "rejected_weak_evidence"),
                ]
            )
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    exit_code = runner.main(
        [
            "--candidate-path",
            str(candidate_path),
            "--output-dir",
            str(output_dir),
            "--cap",
            "2",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "ranking_policy_summary.csv").exists()
    assert (output_dir / "ranking_policy_percase.csv").exists()
    assert (output_dir / "ranking_policy_overlap.csv").exists()
    assert (output_dir / "HANDOFF_RANKING_RESULTS_KO.md").exists()

    percase_rows = list(
        csv.DictReader((output_dir / "ranking_policy_percase.csv").open())
    )
    assert {row["policy"] for row in percase_rows} == set(runner.ACTIVE_POLICIES)
    assert all(int(row["leakage_count"]) == 0 for row in percase_rows)

    for policy in runner.ACTIVE_POLICIES:
        papers_json = (
            output_dir
            / "selected_papers"
            / "source"
            / policy
            / "papers.json"
        )
        assert papers_json.exists()
        selected = json.loads(papers_json.read_text(encoding="utf-8"))["papers"]
        assert [paper["pmid"] for paper in selected] == ["direct", "context"]

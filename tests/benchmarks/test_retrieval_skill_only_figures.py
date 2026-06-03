from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from docs.benchmarks.lr_retrieval_relevance import retrieval_skill_only_figures as figures


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_papers(path: Path, pmids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"papers": [{"pmid": pmid, "title": f"Paper {pmid}"} for pmid in pmids]}),
        encoding="utf-8",
    )


def test_build_figure_tables_writes_expected_csvs_from_clean_roots(tmp_path) -> None:
    retrieval_root = tmp_path / "cci_retrieval_skill_only_qwen_full"
    content_root = tmp_path / "cci_retrieval_skill_only_content_utility_gpt54_live"
    on_filtered = retrieval_root / "workspaces" / "trial_0001_weak_on" / "papers_filtered.json"
    off_filtered = retrieval_root / "workspaces" / "trial_0002_weak_off" / "papers_filtered.json"
    _write_papers(on_filtered, ["100", "200", "300"])
    _write_papers(off_filtered, ["200", "400"])
    rows = [
        {
            "condition": "weak_on",
            "model_strength": "weak",
            "model": "qwen3.5:35b",
            "skill_on": True,
            "direct_papers": 2,
            "context_papers": 1,
            "disease_only_papers": 3,
            "rejected_papers": 4,
            "handoff_papers": 5,
            "filtered_papers_path": str(on_filtered),
        },
        {
            "condition": "weak_off",
            "model_strength": "weak",
            "model": "qwen3.5:35b",
            "skill_on": False,
            "direct_papers": 1,
            "context_papers": 1,
            "disease_only_papers": 0,
            "rejected_papers": 2,
            "handoff_papers": 2,
            "papers_path": str(off_filtered),
        },
    ]
    (retrieval_root / "summary.json").write_text(
        json.dumps({"rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    content_root.mkdir(parents=True)
    (content_root / "summary.json").write_text(json.dumps({"rows": []}), encoding="utf-8")

    written = figures.build_figure_tables(
        retrieval_root=retrieval_root,
        content_root=content_root,
    )

    table_dir = content_root / "manuscript" / "tables"
    assert written == {
        "fig2b_raw_bucket_composition": table_dir / "fig2b_raw_bucket_composition.csv",
        "fig2c_selected_count": table_dir / "fig2c_selected_count.csv",
        "fig2d_overlap": table_dir / "fig2d_overlap.csv",
    }
    bucket_rows = _read_csv(table_dir / "fig2b_raw_bucket_composition.csv")
    assert bucket_rows[0].keys() == {"model_strength", "model", "skill_arm", "bucket", "count"}
    assert {
        (row["skill_arm"], row["bucket"], row["count"])
        for row in bucket_rows
    } >= {
        ("updated_skill", "direct", "2"),
        ("updated_skill", "context", "1"),
        ("updated_skill", "disease_only", "3"),
        ("updated_skill", "rejected", "4"),
        ("updated_skill", "handoff", "5"),
        ("no_skill", "direct", "1"),
    }

    selected_rows = _read_csv(table_dir / "fig2c_selected_count.csv")
    assert selected_rows == [
        {
            "model_strength": "weak",
            "model": "qwen3.5:35b",
            "skill_arm": "updated_skill",
            "selected_count": "5",
            "direct_count": "2",
            "context_count": "1",
        },
        {
            "model_strength": "weak",
            "model": "qwen3.5:35b",
            "skill_arm": "no_skill",
            "selected_count": "2",
            "direct_count": "1",
            "context_count": "1",
        },
    ]

    overlap_rows = _read_csv(table_dir / "fig2d_overlap.csv")
    assert overlap_rows == [
        {
            "model_strength": "weak",
            "shared_pmids": "1",
            "skill_only_pmids": "2",
            "no_skill_only_pmids": "1",
        }
    ]


def test_build_figure_tables_writes_canonical_order_from_shuffled_rows(tmp_path) -> None:
    retrieval_root = tmp_path / "retrieval"
    content_root = tmp_path / "content"
    paper_paths = {
        "strong_off": retrieval_root / "workspaces" / "strong_off" / "papers_filtered.json",
        "weak_off": retrieval_root / "workspaces" / "weak_off" / "papers_filtered.json",
        "strong_on": retrieval_root / "workspaces" / "strong_on" / "papers_filtered.json",
        "weak_on": retrieval_root / "workspaces" / "weak_on" / "papers_filtered.json",
    }
    _write_papers(paper_paths["strong_off"], ["s-shared", "s-off"])
    _write_papers(paper_paths["weak_off"], ["w-shared", "w-off"])
    _write_papers(paper_paths["strong_on"], ["s-shared", "s-on"])
    _write_papers(paper_paths["weak_on"], ["w-shared", "w-on"])
    rows = [
        {
            "condition": "strong_off",
            "model_strength": "strong",
            "model": "z-model",
            "skill_on": False,
            "direct_papers": 10,
            "context_papers": 11,
            "disease_only_papers": 12,
            "rejected_papers": 13,
            "handoff_papers": 14,
            "filtered_papers_path": str(paper_paths["strong_off"]),
        },
        {
            "condition": "weak_off",
            "model_strength": "weak",
            "model": "a-model",
            "skill_on": False,
            "direct_papers": 20,
            "context_papers": 21,
            "disease_only_papers": 22,
            "rejected_papers": 23,
            "handoff_papers": 24,
            "filtered_papers_path": str(paper_paths["weak_off"]),
        },
        {
            "condition": "strong_on",
            "model_strength": "strong",
            "model": "z-model",
            "skill_on": True,
            "direct_papers": 30,
            "context_papers": 31,
            "disease_only_papers": 32,
            "rejected_papers": 33,
            "handoff_papers": 34,
            "filtered_papers_path": str(paper_paths["strong_on"]),
        },
        {
            "condition": "weak_on",
            "model_strength": "weak",
            "model": "a-model",
            "skill_on": True,
            "direct_papers": 40,
            "context_papers": 41,
            "disease_only_papers": 42,
            "rejected_papers": 43,
            "handoff_papers": 44,
            "filtered_papers_path": str(paper_paths["weak_on"]),
        },
    ]
    (retrieval_root / "summary.json").write_text(
        json.dumps({"rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    content_root.mkdir(parents=True)

    figures.build_figure_tables(retrieval_root=retrieval_root, content_root=content_root)

    table_dir = content_root / "manuscript" / "tables"
    assert [
        (row["model_strength"], row["skill_arm"], row["bucket"])
        for row in _read_csv(table_dir / "fig2b_raw_bucket_composition.csv")
    ] == [
        ("weak", "updated_skill", "direct"),
        ("weak", "updated_skill", "context"),
        ("weak", "updated_skill", "disease_only"),
        ("weak", "updated_skill", "rejected"),
        ("weak", "updated_skill", "handoff"),
        ("weak", "no_skill", "direct"),
        ("weak", "no_skill", "context"),
        ("weak", "no_skill", "disease_only"),
        ("weak", "no_skill", "rejected"),
        ("weak", "no_skill", "handoff"),
        ("strong", "updated_skill", "direct"),
        ("strong", "updated_skill", "context"),
        ("strong", "updated_skill", "disease_only"),
        ("strong", "updated_skill", "rejected"),
        ("strong", "updated_skill", "handoff"),
        ("strong", "no_skill", "direct"),
        ("strong", "no_skill", "context"),
        ("strong", "no_skill", "disease_only"),
        ("strong", "no_skill", "rejected"),
        ("strong", "no_skill", "handoff"),
    ]
    assert [
        (row["model_strength"], row["model"], row["skill_arm"])
        for row in _read_csv(table_dir / "fig2c_selected_count.csv")
    ] == [
        ("weak", "a-model", "updated_skill"),
        ("weak", "a-model", "no_skill"),
        ("strong", "z-model", "updated_skill"),
        ("strong", "z-model", "no_skill"),
    ]
    assert _read_csv(table_dir / "fig2d_overlap.csv") == [
        {
            "model_strength": "weak",
            "shared_pmids": "1",
            "skill_only_pmids": "1",
            "no_skill_only_pmids": "1",
        },
        {
            "model_strength": "strong",
            "shared_pmids": "1",
            "skill_only_pmids": "1",
            "no_skill_only_pmids": "1",
        },
    ]


def test_build_figure_tables_fails_clearly_when_summary_missing(tmp_path) -> None:
    content_root = tmp_path / "content"
    content_root.mkdir()

    try:
        figures.build_figure_tables(
            retrieval_root=tmp_path / "missing_retrieval",
            content_root=content_root,
        )
    except FileNotFoundError as exc:
        assert "summary.json" in str(exc)
    else:
        raise AssertionError("expected missing retrieval summary to fail")

"""RED tests for SEARCHER -> INTERPRETER literature handoff filtering."""

import json
from typing import Any

import pytest


def _paper(
    pmid: str,
    evidence_bucket: str,
    supported_lr_pairs: list[dict[str, str]] | None = None,
    direct_lr_pairs: list[dict[str, str]] | None = None,
    context_lr_pairs: list[dict[str, str]] | None = None,
) -> dict:
    return {
        "pmid": pmid,
        "title": f"Paper {pmid}",
        "abstract": f"Abstract for {pmid}",
        "evidence_bucket": evidence_bucket,
        "supported_lr_pairs": supported_lr_pairs or [],
        "direct_lr_pairs": direct_lr_pairs or [],
        "context_lr_pairs": context_lr_pairs or [],
    }


def _build_handoff(
    raw_papers: list[dict],
    cap: int | None = None,
    lr_pairs: list[dict[str, str]] | None = None,
) -> dict:
    from src.agents.deep_interpreter.tools.literature_handoff import (
        build_literature_handoff,
    )

    kwargs: dict[str, Any] = {"raw_papers": raw_papers}
    if cap is not None:
        kwargs["cap"] = cap
    if lr_pairs is not None:
        kwargs["lr_pairs"] = lr_pairs
    return build_literature_handoff(**kwargs)


def _build_filtered_papers_json(
    raw_papers: list[dict],
    cap: int | None = None,
    lr_pairs: list[dict[str, str]] | None = None,
) -> list[dict]:
    return _build_handoff(raw_papers, cap=cap, lr_pairs=lr_pairs)["papers"]


def test_excludes_disease_only_and_rejected_from_filtered_papers_json() -> None:
    raw_papers = [
        _paper("1", "direct_lr_evidence"),
        _paper("2", "disease_only_background"),
        _paper("3", "rejected_weak_evidence"),
        _paper("4", "receptor_pathway_context_evidence"),
    ]

    papers_json = _build_filtered_papers_json(raw_papers)

    assert [paper["pmid"] for paper in papers_json] == ["1", "4"]


def test_enforces_default_interpreter_handoff_cap_of_100() -> None:
    from src.agents.deep_interpreter.tools.literature_handoff import (
        DEFAULT_HANDOFF_CAP,
    )

    raw_papers = [
        _paper(str(index), "direct_lr_evidence")
        for index in range(105)
    ]

    papers_json = _build_filtered_papers_json(raw_papers)

    assert DEFAULT_HANDOFF_CAP == 100
    assert len(papers_json) == 100


def test_below_cap_selects_all_eligible_direct_first_and_reports_unused_capacity() -> None:
    raw_papers = [
        _paper("context-1", "receptor_pathway_context_evidence"),
        _paper("direct-1", "direct_lr_evidence"),
        _paper("background", "disease_only_background"),
        _paper("context-2", "receptor_pathway_context_evidence"),
        _paper("direct-2", "direct_lr_evidence"),
        _paper("rejected", "rejected_weak_evidence"),
    ]

    handoff = _build_handoff(raw_papers)

    assert [paper["pmid"] for paper in handoff["papers"]] == [
        "direct-1",
        "direct-2",
        "context-1",
        "context-2",
    ]
    assert handoff["policy"]["name"] == "direct_all_pair_round_robin_100"
    assert handoff["policy"]["cap"] == 100
    assert handoff["policy"]["eligible_count"] == 4
    assert handoff["policy"]["selected_count"] == 4
    assert handoff["policy"]["eligible_all_selected"] is True
    assert handoff["policy"]["unused_capacity_count"] == 96
    assert handoff["policy"]["direct_truncated_count"] == 0


def test_includes_all_direct_papers_when_direct_count_is_below_cap() -> None:
    pair_a = {"ligand": "TGFB1", "receptor": "TGFBR2"}
    pair_b = {"ligand": "CXCL12", "receptor": "CXCR4"}
    raw_papers = [
        _paper("context-a-1", "receptor_pathway_context_evidence", context_lr_pairs=[pair_a]),
        _paper("direct-1", "direct_lr_evidence", direct_lr_pairs=[pair_a]),
        _paper("context-a-2", "receptor_pathway_context_evidence", context_lr_pairs=[pair_a]),
        _paper("direct-2", "direct_lr_evidence", direct_lr_pairs=[pair_b]),
        _paper("context-b-1", "receptor_pathway_context_evidence", context_lr_pairs=[pair_b]),
        _paper("direct-3", "direct_lr_evidence", direct_lr_pairs=[pair_a]),
        _paper("context-b-2", "receptor_pathway_context_evidence", context_lr_pairs=[pair_b]),
    ]

    handoff = _build_handoff(raw_papers, cap=5, lr_pairs=[pair_a, pair_b])

    assert [paper["pmid"] for paper in handoff["papers"]] == [
        "direct-1",
        "direct-2",
        "direct-3",
        "context-a-1",
        "context-b-1",
    ]
    assert handoff["policy"]["available_direct_count"] == 3
    assert handoff["policy"]["selected_direct_count"] == 3
    assert handoff["policy"]["eligible_all_selected"] is False


def test_direct_overflow_uses_lr_pair_round_robin_before_context() -> None:
    pair_a = {"ligand": "TGFB1", "receptor": "TGFBR2"}
    pair_b = {"ligand": "CXCL12", "receptor": "CXCR4"}
    raw_papers = [
        _paper("direct-a-1", "direct_lr_evidence", direct_lr_pairs=[pair_a]),
        _paper("direct-a-2", "direct_lr_evidence", direct_lr_pairs=[pair_a]),
        _paper("direct-b-1", "direct_lr_evidence", direct_lr_pairs=[pair_b]),
        _paper("context-b-1", "receptor_pathway_context_evidence", context_lr_pairs=[pair_b]),
        _paper("direct-b-2", "direct_lr_evidence", direct_lr_pairs=[pair_b]),
        _paper("direct-unpaired", "direct_lr_evidence"),
    ]

    handoff = _build_handoff(raw_papers, cap=4, lr_pairs=[pair_a, pair_b])

    assert [paper["pmid"] for paper in handoff["papers"]] == [
        "direct-a-1",
        "direct-b-1",
        "direct-a-2",
        "direct-b-2",
    ]
    assert all(paper["evidence_bucket"] == "direct_lr_evidence" for paper in handoff["papers"])
    assert handoff["policy"]["direct_truncated_count"] == 1


def test_context_round_robin_deduplicates_multi_pair_papers_once() -> None:
    pair_a = {"ligand": "TGFB1", "receptor": "TGFBR2"}
    pair_b = {"ligand": "CXCL12", "receptor": "CXCR4"}
    raw_papers = [
        _paper("direct", "direct_lr_evidence", direct_lr_pairs=[pair_a]),
        _paper(
            "context-multi",
            "receptor_pathway_context_evidence",
            context_lr_pairs=[pair_a, pair_b],
        ),
        _paper("context-a", "receptor_pathway_context_evidence", context_lr_pairs=[pair_a]),
        _paper("context-b", "receptor_pathway_context_evidence", context_lr_pairs=[pair_b]),
    ]

    papers_json = _build_filtered_papers_json(raw_papers, cap=3, lr_pairs=[pair_a, pair_b])

    assert [paper["pmid"] for paper in papers_json] == [
        "direct",
        "context-multi",
        "context-b",
    ]


def test_unpaired_context_fallback_is_used_after_pair_scoped_context() -> None:
    pair_a = {"ligand": "TGFB1", "receptor": "TGFBR2"}
    pair_b = {"ligand": "CXCL12", "receptor": "CXCR4"}
    raw_papers = [
        _paper("direct", "direct_lr_evidence", direct_lr_pairs=[pair_a]),
        _paper("context-a", "receptor_pathway_context_evidence", context_lr_pairs=[pair_a]),
        _paper("context-unpaired-1", "receptor_pathway_context_evidence"),
        _paper("context-b", "receptor_pathway_context_evidence", context_lr_pairs=[pair_b]),
        _paper("context-unpaired-2", "receptor_pathway_context_evidence"),
    ]

    papers_json = _build_filtered_papers_json(raw_papers, cap=4, lr_pairs=[pair_a, pair_b])

    assert [paper["pmid"] for paper in papers_json] == [
        "direct",
        "context-a",
        "context-b",
        "context-unpaired-1",
    ]


def test_preserves_bucket_and_supported_lr_pairs_metadata_in_filtered_papers_json() -> None:
    supported_lr_pairs = [
        {"ligand": "TGFB1", "receptor": "TGFBR2"},
        {"ligand": "TGFB1", "receptor": "ACVR1"},
    ]
    raw_papers = [
        _paper(
            "metadata-1",
            "direct_lr_evidence",
            supported_lr_pairs=supported_lr_pairs,
        )
    ]

    papers_json = _build_filtered_papers_json(raw_papers)

    assert papers_json[0]["evidence_bucket"] == "direct_lr_evidence"
    assert papers_json[0]["supported_lr_pairs"] == supported_lr_pairs


def test_create_literature_handoff_writes_raw_bucket_audit_and_filtered_handoff(
    tmp_path,
) -> None:
    from src.agents.deep_interpreter.tools.literature_handoff import (
        create_literature_handoff,
    )

    raw_payload = {
        "papers": [
            {
                "pmid": "direct",
                "title": "TGFB1 and TGFBR2 signaling in breast cancer",
                "abstract": "TGFB1 activates TGFBR2 in breast cancer invasion.",
            },
            {
                "pmid": "background",
                "title": "Breast cancer clinical background",
                "abstract": "Breast cancer therapy and prognosis overview.",
            },
        ]
    }
    (tmp_path / "papers_raw.json").write_text(json.dumps(raw_payload), encoding="utf-8")

    result = create_literature_handoff.invoke(
        {
            "raw_papers_path": "papers_raw.json",
            "output_path": "papers.json",
            "citation_candidates_path": "citation_candidates.json",
            "data_dir": str(tmp_path),
            "disease": "breast cancer",
            "lr_pairs": [{"ligand": "TGFB1", "receptor": "TGFBR2"}],
            "cap": 40,
        }
    )

    assert result["total_handoff_papers"] == 1
    candidates = json.loads((tmp_path / "citation_candidates.json").read_text())
    handoff = json.loads((tmp_path / "papers.json").read_text())

    assert candidates["counts"]["direct_lr_evidence"] == 1
    assert candidates["counts"]["disease_only_background"] == 1
    assert [paper["pmid"] for paper in handoff["papers"]] == ["direct"]
    assert handoff["papers"][0]["evidence_bucket"] == "direct_lr_evidence"


def test_create_literature_handoff_grades_all_candidates_but_caps_selected_handoff(
    tmp_path,
) -> None:
    from src.agents.deep_interpreter.tools.literature_handoff import (
        create_literature_handoff,
    )

    lr_pair = {"ligand": "APOE", "receptor": "TREM2"}
    direct_papers = [
        {
            "pmid": f"direct-{index:03d}",
            "title": f"APOE and TREM2 signaling in idiopathic pulmonary fibrosis {index}",
            "abstract": (
                "APOE binds TREM2 in idiopathic pulmonary fibrosis macrophage models."
            ),
        }
        for index in range(105)
    ]
    non_eligible_papers = [
        {
            "pmid": f"background-{index:03d}",
            "title": f"Idiopathic pulmonary fibrosis clinical background {index}",
            "abstract": "Idiopathic pulmonary fibrosis diagnosis and progression overview.",
        }
        for index in range(3)
    ] + [
        {
            "pmid": f"rejected-{index:03d}",
            "title": f"APOE and TREM2 signaling without disease context {index}",
            "abstract": "APOE binds TREM2 in unrelated experimental systems.",
        }
        for index in range(2)
    ]
    raw_payload = {"papers": direct_papers + non_eligible_papers}
    (tmp_path / "papers_raw.json").write_text(json.dumps(raw_payload), encoding="utf-8")

    result = create_literature_handoff.invoke(
        {
            "raw_papers_path": "papers_raw.json",
            "output_path": "papers.json",
            "citation_candidates_path": "citation_candidates.json",
            "data_dir": str(tmp_path),
            "disease": "idiopathic pulmonary fibrosis",
            "lr_pairs": [lr_pair],
            "cap": 100,
        }
    )

    candidates = json.loads((tmp_path / "citation_candidates.json").read_text())
    handoff = json.loads((tmp_path / "papers.json").read_text())

    assert result["total_raw_papers"] == 110
    assert candidates["source"]["total_papers"] == 110
    assert handoff["source"]["total_papers"] == 110
    assert len(candidates["papers"]) == 110

    assert handoff["policy"]["name"] == "direct_all_pair_round_robin_100"
    assert handoff["policy"]["selected_count"] == 100
    assert handoff["policy"]["eligible_count"] == 105
    assert handoff["policy"]["eligible_all_selected"] is False
    assert handoff["policy"]["truncated_count"] == 5
    assert len(handoff["papers"]) == 100

    selected_pmids = {paper["pmid"] for paper in handoff["papers"]}
    non_eligible_pmids = {paper["pmid"] for paper in non_eligible_papers}
    assert selected_pmids.isdisjoint(non_eligible_pmids)


def test_create_literature_handoff_prefers_lr_candidates_fallback_pairs(
    tmp_path,
) -> None:
    from src.agents.deep_interpreter.tools.literature_handoff import (
        create_literature_handoff,
    )

    raw_payload = {
        "papers": [
            {
                "pmid": "candidate-direct",
                "title": "CAND00 and REC00 signaling in cancer",
                "abstract": "CAND00 binds REC00 in cancer models.",
            },
            {
                "pmid": "fallback-direct",
                "title": "FALLBACK and PAIR signaling in cancer",
                "abstract": "FALLBACK binds PAIR in cancer models.",
            },
        ]
    }
    (tmp_path / "papers_raw.json").write_text(json.dumps(raw_payload), encoding="utf-8")
    (tmp_path / "lr_candidates.json").write_text(
        json.dumps({"pairs": [{"ligand": "CAND00", "receptor": "REC00"}]}),
        encoding="utf-8",
    )
    (tmp_path / "lr_pairs_search.json").write_text(
        json.dumps({"pairs": [{"ligand": "FALLBACK", "receptor": "PAIR"}]}),
        encoding="utf-8",
    )

    result = create_literature_handoff.invoke(
        {
            "raw_papers_path": "papers_raw.json",
            "output_path": "papers.json",
            "citation_candidates_path": "citation_candidates.json",
            "data_dir": str(tmp_path),
            "disease": "cancer",
            "cap": 100,
        }
    )

    candidates = json.loads((tmp_path / "citation_candidates.json").read_text())
    handoff = json.loads((tmp_path / "papers.json").read_text())

    assert result["total_handoff_papers"] == 1
    assert candidates["counts"]["direct_lr_evidence"] == 1
    assert candidates["counts"]["disease_only_background"] == 1
    assert [paper["pmid"] for paper in handoff["papers"]] == ["candidate-direct"]


def test_create_literature_handoff_loads_root_lr_candidates_for_nested_raw_path(
    tmp_path,
) -> None:
    from src.agents.deep_interpreter.tools.literature_handoff import (
        create_literature_handoff,
    )

    nested = tmp_path / "nested"
    nested.mkdir()
    raw_payload = {
        "papers": [
            {
                "pmid": "nested-candidate-direct",
                "title": "CAND00 and REC00 signaling in cancer",
                "abstract": "CAND00 binds REC00 in cancer models.",
            }
        ]
    }
    (nested / "papers_raw.json").write_text(
        json.dumps(raw_payload),
        encoding="utf-8",
    )
    (tmp_path / "lr_candidates.json").write_text(
        json.dumps({"pairs": [{"ligand": "CAND00", "receptor": "REC00"}]}),
        encoding="utf-8",
    )

    result = create_literature_handoff.invoke(
        {
            "raw_papers_path": "nested/papers_raw.json",
            "output_path": "papers.json",
            "citation_candidates_path": "citation_candidates.json",
            "data_dir": str(tmp_path),
            "disease": "cancer",
            "cap": 100,
        }
    )

    handoff = json.loads((tmp_path / "papers.json").read_text())

    assert result["total_handoff_papers"] == 1
    assert handoff["papers"][0]["pmid"] == "nested-candidate-direct"
    assert handoff["papers"][0]["evidence_bucket"] == "direct_lr_evidence"


def test_create_literature_handoff_uses_env_data_dir_for_nested_lr_candidates(
    monkeypatch,
    tmp_path,
) -> None:
    from src.agents.deep_interpreter.tools.literature_handoff import (
        create_literature_handoff,
    )

    nested = tmp_path / "nested"
    nested.mkdir()
    raw_payload = {
        "papers": [
            {
                "pmid": "env-nested-candidate-direct",
                "title": "CAND00 and REC00 signaling in cancer",
                "abstract": "CAND00 binds REC00 in cancer models.",
            }
        ]
    }
    (nested / "papers_raw.json").write_text(
        json.dumps(raw_payload),
        encoding="utf-8",
    )
    (tmp_path / "lr_candidates.json").write_text(
        json.dumps({"pairs": [{"ligand": "CAND00", "receptor": "REC00"}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", str(tmp_path))

    result = create_literature_handoff.invoke(
        {
            "raw_papers_path": "nested/papers_raw.json",
            "output_path": "papers.json",
            "citation_candidates_path": "citation_candidates.json",
            "disease": "cancer",
            "cap": 100,
        }
    )

    handoff = json.loads((tmp_path / "papers.json").read_text())

    assert result["total_handoff_papers"] == 1
    assert handoff["papers"][0]["pmid"] == "env-nested-candidate-direct"
    assert handoff["papers"][0]["evidence_bucket"] == "direct_lr_evidence"


@pytest.mark.parametrize(
    "field",
    ["raw_papers_path", "output_path", "citation_candidates_path"],
)
def test_create_literature_handoff_rejects_paths_outside_data_dir(
    tmp_path,
    field: str,
) -> None:
    from src.agents.deep_interpreter.tools.literature_handoff import (
        create_literature_handoff,
    )

    (tmp_path / "papers_raw.json").write_text(
        json.dumps({"papers": []}),
        encoding="utf-8",
    )
    payload = {
        "raw_papers_path": "papers_raw.json",
        "output_path": "papers.json",
        "citation_candidates_path": "citation_candidates.json",
        "data_dir": str(tmp_path),
        "disease": "breast cancer",
        "lr_pairs": [],
    }
    payload[field] = "../outside.json"

    with pytest.raises(ValueError, match="within data_dir"):
        create_literature_handoff.invoke(payload)


def test_global_pathway_context_is_not_attributed_to_every_lr_pair() -> None:
    from src.agents.deep_interpreter.tools.literature_handoff import (
        grade_lr_literature_candidates,
    )

    payload = {
        "papers": [
            {
                "pmid": "pathway-only",
                "title": "VEGF signaling in breast cancer",
                "abstract": "VEGF signaling shapes breast cancer progression.",
            }
        ]
    }

    candidates = grade_lr_literature_candidates(
        payload,
        lr_pairs=[
            {"ligand": "TGFB1", "receptor": "TGFBR2"},
            {"ligand": "COL1A2", "receptor": "ITGA1"},
        ],
        disease="breast cancer",
        pathways=["VEGF signaling"],
    )

    paper = candidates["papers"][0]
    assert paper["evidence_bucket"] == "receptor_pathway_context_evidence"
    assert paper["supported_lr_pairs"] == []
    assert all(
        pair_result["receptor_pathway_context_evidence"] == 0
        for pair_result in candidates["pair_results"]
    )


def test_pair_scoped_pathway_context_is_attributed_to_only_that_pair() -> None:
    from src.agents.deep_interpreter.tools.literature_handoff import (
        grade_lr_literature_candidates,
    )

    payload = {
        "papers": [
            {
                "pmid": "pair-pathway",
                "title": "VEGF signaling in breast cancer",
                "abstract": "VEGF signaling shapes breast cancer progression.",
            }
        ]
    }

    candidates = grade_lr_literature_candidates(
        payload,
        lr_pairs=[
            {
                "ligand": "VEGFA",
                "receptor": "KDR",
                "pathways": ["VEGF signaling"],
            },
            {"ligand": "COL1A2", "receptor": "ITGA1"},
        ],
        disease="breast cancer",
        pathways=["VEGF signaling"],
    )

    paper = candidates["papers"][0]
    assert paper["evidence_bucket"] == "receptor_pathway_context_evidence"
    assert paper["supported_lr_pairs"] == [{"ligand": "VEGFA", "receptor": "KDR"}]
    assert [
        pair_result["receptor_pathway_context_evidence"]
        for pair_result in candidates["pair_results"]
    ] == [1, 0]

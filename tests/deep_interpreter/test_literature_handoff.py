"""RED tests for SEARCHER -> INTERPRETER literature handoff filtering."""

import json

import pytest


def _paper(
    pmid: str,
    evidence_bucket: str,
    supported_lr_pairs: list[dict[str, str]] | None = None,
) -> dict:
    return {
        "pmid": pmid,
        "title": f"Paper {pmid}",
        "abstract": f"Abstract for {pmid}",
        "evidence_bucket": evidence_bucket,
        "supported_lr_pairs": supported_lr_pairs or [],
    }


def _build_filtered_papers_json(raw_papers: list[dict], cap: int = 40) -> list[dict]:
    from src.agents.deep_interpreter.tools.literature_handoff import (
        build_literature_handoff,
    )

    handoff = build_literature_handoff(raw_papers=raw_papers, cap=cap)
    return handoff["papers"]


def test_excludes_disease_only_and_rejected_from_filtered_papers_json() -> None:
    raw_papers = [
        _paper("1", "direct_lr_evidence"),
        _paper("2", "disease_only_background"),
        _paper("3", "rejected_weak_evidence"),
        _paper("4", "receptor_pathway_context_evidence"),
    ]

    papers_json = _build_filtered_papers_json(raw_papers)

    assert [paper["pmid"] for paper in papers_json] == ["1", "4"]


def test_enforces_default_interpreter_handoff_cap_of_40() -> None:
    raw_papers = [
        _paper(str(index), "direct_lr_evidence")
        for index in range(45)
    ]

    papers_json = _build_filtered_papers_json(raw_papers)

    assert len(papers_json) == 40


def test_orders_direct_evidence_before_context_evidence() -> None:
    raw_papers = [
        _paper("context-1", "receptor_pathway_context_evidence"),
        _paper("direct-1", "direct_lr_evidence"),
        _paper("context-2", "receptor_pathway_context_evidence"),
        _paper("direct-2", "direct_lr_evidence"),
    ]

    papers_json = _build_filtered_papers_json(raw_papers)

    assert [paper["pmid"] for paper in papers_json] == [
        "direct-1",
        "direct-2",
        "context-1",
        "context-2",
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

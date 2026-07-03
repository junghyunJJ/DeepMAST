from pathlib import Path

from src.agents.deep_interpreter.middleware.load import get_skill_content, list_skills


REPO_ROOT = Path(__file__).resolve().parents[2]
MODE_HEADERS = [
    "## PLANNER Mode",
    "## SEARCHER Production Mode",
    "## SEARCHER Retrieval-Only Benchmark Mode",
    "## REPORTER Mode",
]


def _write_skill(root: Path, dirname: str, name: str) -> None:
    skill_dir = root / dirname
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test skill\n---\n\n# Test\n",
        encoding="utf-8",
    )


def _section_between(content: str, start_header: str, end_header: str | None) -> str:
    start = content.index(start_header)
    end = content.index(end_header, start) if end_header else len(content)
    return content[start:end]


def _normalized(content: str) -> str:
    return " ".join(content.replace("`", "").split())


def test_list_skills_skips_versioned_skill_snapshots(tmp_path: Path) -> None:
    _write_skill(tmp_path, "biomedical-literature-search", "biomedical-literature-search")
    _write_skill(
        tmp_path,
        "biomedical-literature-search_v1.3.0",
        "biomedical-literature-search",
    )

    skills = list_skills(tmp_path)

    assert [skill["path"] for skill in skills] == [
        str((tmp_path / "biomedical-literature-search" / "SKILL.md").absolute())
    ]


def test_biomedical_literature_search_role_modes_load() -> None:
    skills = list_skills(REPO_ROOT / "skills")
    skill = next(
        skill for skill in skills if skill["name"] == "biomedical-literature-search"
    )

    content = get_skill_content(skill["path"])

    assert content is not None
    for header in MODE_HEADERS:
        assert header in content

    planner = _section_between(
        content, "## PLANNER Mode", "## SEARCHER Production Mode"
    )
    production = _section_between(
        content,
        "## SEARCHER Production Mode",
        "## SEARCHER Retrieval-Only Benchmark Mode",
    )
    retrieval_only = _section_between(
        content, "## SEARCHER Retrieval-Only Benchmark Mode", "## REPORTER Mode"
    )
    reporter = _section_between(content, "## REPORTER Mode", "## Evidence Matching Rules")

    planner_normalized = _normalized(planner)
    production_normalized = _normalized(production)
    retrieval_normalized = _normalized(retrieval_only)
    reporter_normalized = _normalized(reporter)

    assert "planner_papers.json" in planner
    assert "Do not call create_literature_handoff" in planner_normalized
    assert "Do not write or overwrite papers.json" in planner_normalized

    assert "papers_raw.json" in production
    assert "create_literature_handoff" in production
    assert "citation_candidates.json" in production
    assert "filtered INTERPRETER handoff" in production
    assert "full unique raw retrieval pool to papers_raw.json" in production_normalized
    assert (
        "Do not apply the max_results or handoff cap to papers_raw.json"
    ) in production_normalized
    assert (
        "the cap is applied later by create_literature_handoff when writing "
        "papers.json"
    ) in production_normalized
    assert (
        "SEARCHER grading/QC grades all raw candidates from papers_raw.json"
    ) in production_normalized
    assert (
        "papers.json is the canonical SEARCHER-to-INTERPRETER citation source "
        "only in this mode"
    ) in production_normalized
    assert "direct_lr_evidence" in production
    assert "receptor_pathway_context_evidence" in production
    assert "cap=100" in production
    assert "cap 100 is an upper bound" in production_normalized
    assert (
        "applies cap=100 only if eligible direct/context papers exceed 100"
    ) in production_normalized
    assert "all eligible papers" in production_normalized
    assert "do not expand raw retrieval solely to fill all 100 slots" in production_normalized

    assert "papers_raw.json" in retrieval_only
    assert "Do not call create_literature_handoff" in retrieval_normalized
    assert "Do not write citation_candidates.json" in retrieval_normalized
    assert "Do not write filtered papers.json" in retrieval_normalized
    assert "legacy retrieval-only benchmark runner" in retrieval_normalized
    assert "diagnostic direct/context cap-40 filter" in retrieval_normalized
    assert (
        "not the current SEARCHER Production handoff cap"
    ) in retrieval_normalized

    assert "papers.json" in reporter
    assert "search_literature_fulltext" in reporter
    assert "synthesis_papers_raw.json" not in reporter
    assert "synthesis_citation_candidates.json" not in reporter
    assert "synthesis_papers.json" not in reporter
    assert "Do not write or overwrite canonical papers.json" in reporter_normalized

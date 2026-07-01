"""Regression tests for dynamic literature output-path contract."""

import json

import pytest

from src.agents.deep_interpreter.tools import literature as lit
from src.agents.deep_interpreter.tools.literature_handoff import load_searcher_lr_pairs


class _MockResponse:
    def __init__(self, content: str):
        self.content = content


class _MockLLM:
    def __init__(self, content: str | None = None, exc: Exception | None = None):
        self._content = content
        self._exc = exc
        self.prompts: list[str] = []

    async def ainvoke(self, messages):
        self.prompts.append(messages[0].content)
        if self._exc:
            raise self._exc
        return _MockResponse(self._content or "[]")


def test_literature_dynamic_search_timeout_is_configurable(monkeypatch):
    monkeypatch.delenv("LITERATURE_DYNAMIC_SEARCH_TIMEOUT", raising=False)
    assert lit._literature_dynamic_search_timeout() == 300.0

    monkeypatch.setenv("LITERATURE_DYNAMIC_SEARCH_TIMEOUT", "900")
    assert lit._literature_dynamic_search_timeout() == 900.0


@pytest.fixture
def isolated_literature(monkeypatch):
    async def _fake_search_with_biomcp(**_kwargs):
        return [
            {
                "pmid": "12345678",
                "title": "L1 R1 cancer signaling",
                "abstract": "L1 and R1 signaling in cancer.",
            }
        ]

    async def _fake_aliases(*_args, **_kwargs):
        return []

    async def _noop_sjr():
        return None

    monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)
    monkeypatch.setattr(lit, "_fetch_gene_aliases_from_biomcp", _fake_aliases)
    monkeypatch.setattr(lit, "_ensure_sjr_cache_loaded", _noop_sjr)


@pytest.mark.asyncio
async def test_llm_exception_iteration0_fallback_saves_output(
    monkeypatch, tmp_path, isolated_literature
):
    monkeypatch.setattr(
        lit,
        "create_llm",
        lambda **_kwargs: _MockLLM(exc=RuntimeError("llm unavailable")),
    )

    result = await lit.search_literature_dynamic_async(
        genes=["L1", "R1"],
        pathways=["MAPK"],
        celltypes=["Tumor"],
        disease="cancer",
        max_results=5,
        max_iterations=1,
        output_path="papers_raw.json",
        data_dir=str(tmp_path),
    )

    saved_path = tmp_path / "papers_raw.json"
    saved = json.loads(saved_path.read_text())
    assert saved["search_method"] == "fixed_strategy_fallback"
    assert result["saved_to"] == str(saved_path.resolve())
    assert result["total_papers"] == 1
    assert result["search_method"] == "fixed_strategy_fallback"


@pytest.mark.asyncio
async def test_invalid_empty_llm_queries_iteration0_fallback_saves_output(
    monkeypatch, tmp_path, isolated_literature
):
    monkeypatch.setattr(lit, "create_llm", lambda **_kwargs: _MockLLM("[]"))

    result = await lit.search_literature_dynamic_async(
        genes=["L1", "R1"],
        pathways=["MAPK"],
        celltypes=["Tumor"],
        disease="cancer",
        max_results=5,
        max_iterations=1,
        output_path="papers_raw.json",
        data_dir=str(tmp_path),
    )

    saved_path = tmp_path / "papers_raw.json"
    saved = json.loads(saved_path.read_text())
    assert saved["search_method"] == "fixed_strategy_fallback"
    assert result["saved_to"] == str(saved_path.resolve())
    assert result["total_papers"] == 1
    assert result["search_method"] == "fixed_strategy_fallback"


@pytest.mark.asyncio
async def test_searcher_mode_saves_full_raw_pool_before_handoff_cap(
    monkeypatch, tmp_path, isolated_literature
):
    async def _fake_search_with_biomcp(**kwargs):
        genes = kwargs.get("genes") or []
        gene = genes[0] if genes else "NO_GENE"
        return [
            {
                "pmid": f"{gene}-{index}",
                "title": f"{gene} paper {index}",
                "abstract": f"{gene} signaling in cancer.",
            }
            for index in range(2)
        ]

    monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)
    monkeypatch.setattr(lit, "create_llm", lambda **_kwargs: _MockLLM("[]"))

    result = await lit.search_literature_dynamic_async(
        genes=["G1", "G2", "G3", "G4"],
        pathways=[],
        celltypes=[],
        disease="cancer",
        max_results=3,
        max_iterations=1,
        query_cache=[
            {"genes": ["G1"], "diseases": ["cancer"], "keywords": []},
            {"genes": ["G2"], "diseases": ["cancer"], "keywords": []},
            {"genes": ["G3"], "diseases": ["cancer"], "keywords": []},
            {"genes": ["G4"], "diseases": ["cancer"], "keywords": []},
        ],
        enable_lr_pair_queries=True,
        output_path="papers_raw.json",
        data_dir=str(tmp_path),
        sort_by_journal_quality=False,
    )

    saved_path = tmp_path / "papers_raw.json"
    saved = json.loads(saved_path.read_text())
    policy = saved["raw_pool_policy"]

    assert result["total_papers"] == 8
    assert len(saved["papers"]) == 8
    assert policy["name"] == "preserve_all_unique_retrieved_candidates"
    assert policy["requested_max_results"] == 3
    assert policy["saved_raw_count"] == 8
    assert policy["internal_pool_size"] >= 300
    assert policy["handoff_cap_applied_in"] == "create_literature_handoff"


@pytest.mark.asyncio
async def test_lr_pair_mode_papers_json_preserves_max_results_cap(
    monkeypatch, tmp_path, isolated_literature
):
    async def _fake_search_with_biomcp(**kwargs):
        genes = kwargs.get("genes") or []
        gene = genes[0] if genes else "NO_GENE"
        return [
            {
                "pmid": f"{gene}-{index}",
                "title": f"{gene} paper {index}",
                "abstract": f"{gene} signaling in cancer.",
            }
            for index in range(2)
        ]

    monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)
    monkeypatch.setattr(lit, "create_llm", lambda **_kwargs: _MockLLM("[]"))

    result = await lit.search_literature_dynamic_async(
        genes=["G1", "G2", "G3", "G4"],
        pathways=[],
        celltypes=[],
        disease="cancer",
        max_results=3,
        max_iterations=1,
        query_cache=[
            {"genes": ["G1"], "diseases": ["cancer"], "keywords": []},
            {"genes": ["G2"], "diseases": ["cancer"], "keywords": []},
            {"genes": ["G3"], "diseases": ["cancer"], "keywords": []},
            {"genes": ["G4"], "diseases": ["cancer"], "keywords": []},
        ],
        enable_lr_pair_queries=True,
        output_path="papers.json",
        data_dir=str(tmp_path),
        sort_by_journal_quality=False,
    )

    saved = json.loads((tmp_path / "papers.json").read_text())

    assert result["total_papers"] == 3
    assert len(saved["papers"]) == 3
    assert saved["raw_pool_policy"]["name"] == "legacy_max_results_truncation"
    assert saved["raw_pool_policy"]["requested_max_results"] == 3
    assert saved["raw_pool_policy"]["saved_raw_count"] == 3


@pytest.mark.asyncio
async def test_searcher_cache_replay_empty_cache_injects_gene_and_lr_fanout(
    monkeypatch, tmp_path, isolated_literature
):
    async def _fake_search_with_biomcp(**kwargs):
        genes = kwargs.get("genes") or []
        gene_key = "-".join(genes) if genes else "NO_GENE"
        return [
            {
                "pmid": f"{gene_key}-cache-fanout",
                "title": f"{gene_key} cache fanout paper",
                "abstract": f"{gene_key} signaling in cancer.",
            }
        ]

    monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)
    monkeypatch.setattr(
        lit,
        "create_llm",
        lambda **_kwargs: _MockLLM(exc=RuntimeError("llm should be skipped")),
    )

    await lit.search_literature_dynamic_async(
        genes=["G1", "G2"],
        pathways=[],
        celltypes=[],
        disease="cancer",
        max_results=1,
        max_iterations=1,
        query_cache=[],
        lr_pairs=[{"ligand": "L1", "receptor": "R1"}],
        enable_lr_pair_queries=True,
        output_path="papers_raw.json",
        data_dir=str(tmp_path),
        sort_by_journal_quality=False,
    )

    saved = json.loads((tmp_path / "papers_raw.json").read_text())
    pmids = {paper["pmid"] for paper in saved["papers"]}
    query_gene_sets = {
        tuple(query.get("genes", [])) for query in saved["generated_queries"]
    }

    assert saved["query_generation_status"] == "cache_replay"
    assert saved["query_generation_error"] == ""
    assert pmids == {
        "G1-cache-fanout",
        "G2-cache-fanout",
        "L1-R1-cache-fanout",
    }
    assert query_gene_sets == {("G1",), ("G2",), ("L1", "R1")}


@pytest.mark.asyncio
async def test_non_searcher_output_uses_legacy_max_results_truncation(
    monkeypatch, tmp_path, isolated_literature
):
    async def _fake_search_with_biomcp(**_kwargs):
        return [
            {
                "pmid": f"legacy-{index}",
                "title": f"legacy paper {index}",
                "abstract": "legacy signaling in cancer.",
            }
            for index in range(4)
        ]

    monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)
    monkeypatch.setattr(lit, "create_llm", lambda **_kwargs: _MockLLM("[]"))

    await lit.search_literature_dynamic_async(
        genes=["G1"],
        pathways=[],
        celltypes=[],
        disease="cancer",
        max_results=2,
        max_iterations=1,
        query_cache=[
            {"genes": ["G1"], "diseases": ["cancer"], "keywords": []},
        ],
        output_path="papers_raw.json",
        data_dir=str(tmp_path),
        sort_by_journal_quality=False,
    )

    saved = json.loads((tmp_path / "papers_raw.json").read_text())

    assert len(saved["papers"]) == 2
    assert saved["raw_pool_policy"]["name"] == "legacy_max_results_truncation"
    assert saved["raw_pool_policy"]["saved_raw_count"] == 2


@pytest.mark.asyncio
async def test_llm_success_records_query_generation_success(
    monkeypatch, tmp_path, isolated_literature
):
    async def _fake_search_with_biomcp(**_kwargs):
        return [
            {
                "pmid": "llm-success",
                "title": "LLM success paper",
                "abstract": "G1 signaling in cancer.",
            }
        ]

    monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)
    monkeypatch.setattr(
        lit,
        "create_llm",
        lambda **_kwargs: _MockLLM(
            json.dumps([
                {"genes": ["G1"], "diseases": ["cancer"], "keywords": []},
            ])
        ),
    )

    await lit.search_literature_dynamic_async(
        genes=["G1"],
        pathways=[],
        celltypes=[],
        disease="cancer",
        max_results=1,
        max_iterations=1,
        output_path="papers_raw.json",
        data_dir=str(tmp_path),
        sort_by_journal_quality=False,
    )

    saved = json.loads((tmp_path / "papers_raw.json").read_text())

    assert saved["query_generation_status"] == "llm_success"
    assert saved["query_generation_error"] == ""


@pytest.mark.asyncio
async def test_gap_fill_llm_failure_records_query_generation_error(
    monkeypatch, tmp_path, isolated_literature
):
    async def _fake_search_with_biomcp(**kwargs):
        genes = kwargs.get("genes") or []
        gene = genes[0] if genes else "NO_GENE"
        return [
            {
                "pmid": f"{gene}-iter0",
                "title": f"{gene} iteration zero paper",
                "abstract": f"{gene} signaling in cancer.",
            }
        ]

    monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)
    monkeypatch.setattr(
        lit,
        "create_llm",
        lambda **_kwargs: _MockLLM(exc=RuntimeError("gap llm down")),
    )

    await lit.search_literature_dynamic_async(
        genes=["G1", "G2"],
        pathways=[],
        celltypes=[],
        disease="cancer",
        max_results=5,
        max_iterations=2,
        query_cache=[
            {"genes": ["G1"], "diseases": ["cancer"], "keywords": []},
        ],
        output_path="papers_raw.json",
        data_dir=str(tmp_path),
        sort_by_journal_quality=False,
    )

    saved = json.loads((tmp_path / "papers_raw.json").read_text())

    assert saved["query_generation_status"] == "llm_failed_gap_fill"
    assert "iteration=1" in saved["query_generation_error"]
    assert "gap llm down" in saved["query_generation_error"]


@pytest.mark.asyncio
async def test_searcher_mode_saves_full_raw_pool_with_journal_quality_sort(
    monkeypatch, tmp_path, isolated_literature
):
    async def _fake_search_with_biomcp(**kwargs):
        genes = kwargs.get("genes") or []
        gene = genes[0] if genes else "NO_GENE"
        return [
            {
                "pmid": f"{gene}-ranked-{index}",
                "title": f"{gene} ranked paper {index}",
                "abstract": f"{gene} signaling in cancer.",
                "journal_quality": 10 - index,
            }
            for index in range(2)
        ]

    async def _noop_sjr():
        return None

    monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)
    monkeypatch.setattr(lit, "_ensure_sjr_cache_loaded", _noop_sjr)
    monkeypatch.setattr(lit, "create_llm", lambda **_kwargs: _MockLLM("[]"))

    await lit.search_literature_dynamic_async(
        genes=["G1", "G2", "G3", "G4"],
        pathways=[],
        celltypes=[],
        disease="cancer",
        max_results=3,
        max_iterations=1,
        query_cache=[
            {"genes": ["G1"], "diseases": ["cancer"], "keywords": []},
            {"genes": ["G2"], "diseases": ["cancer"], "keywords": []},
            {"genes": ["G3"], "diseases": ["cancer"], "keywords": []},
            {"genes": ["G4"], "diseases": ["cancer"], "keywords": []},
        ],
        enable_lr_pair_queries=True,
        output_path="papers_raw.json",
        data_dir=str(tmp_path),
    )

    saved = json.loads((tmp_path / "papers_raw.json").read_text())

    assert len(saved["papers"]) == 8
    assert len(saved["papers"]) > 3
    assert saved["raw_pool_policy"]["saved_raw_count"] == 8
    assert saved["query_generation_status"] == "cache_replay"


@pytest.mark.asyncio
async def test_searcher_llm_failure_records_deterministic_fallback_status(
    monkeypatch, tmp_path, isolated_literature
):
    async def _fake_search_with_biomcp(**kwargs):
        genes = kwargs.get("genes") or []
        gene = genes[0] if genes else "NO_GENE"
        return [
            {
                "pmid": f"{gene}-fallback",
                "title": f"{gene} fallback paper",
                "abstract": f"{gene} signaling in cancer.",
            }
        ]

    monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)
    monkeypatch.setattr(
        lit,
        "create_llm",
        lambda **_kwargs: _MockLLM(exc=RuntimeError("llm unavailable")),
    )

    await lit.search_literature_dynamic_async(
        genes=["G1", "G2"],
        pathways=[],
        celltypes=[],
        disease="cancer",
        max_results=1,
        max_iterations=1,
        enable_lr_pair_queries=True,
        output_path="papers_raw.json",
        data_dir=str(tmp_path),
        sort_by_journal_quality=False,
    )

    saved = json.loads((tmp_path / "papers_raw.json").read_text())

    assert saved["query_generation_status"] == "llm_failed_deterministic_fallback"
    assert "llm unavailable" in saved["query_generation_error"]
    assert len(saved["papers"]) == 2


@pytest.mark.asyncio
async def test_searcher_empty_llm_queries_records_deterministic_fallback_status(
    monkeypatch, tmp_path, isolated_literature
):
    async def _fake_search_with_biomcp(**kwargs):
        genes = kwargs.get("genes") or []
        gene = genes[0] if genes else "NO_GENE"
        return [
            {
                "pmid": f"{gene}-empty-fallback",
                "title": f"{gene} empty fallback paper",
                "abstract": f"{gene} signaling in cancer.",
            }
        ]

    monkeypatch.setattr(lit, "_search_with_biomcp", _fake_search_with_biomcp)
    monkeypatch.setattr(lit, "create_llm", lambda **_kwargs: _MockLLM("[]"))

    await lit.search_literature_dynamic_async(
        genes=["G1", "G2"],
        pathways=[],
        celltypes=[],
        disease="cancer",
        max_results=1,
        max_iterations=1,
        enable_lr_pair_queries=True,
        output_path="papers_raw.json",
        data_dir=str(tmp_path),
        sort_by_journal_quality=False,
    )

    saved = json.loads((tmp_path / "papers_raw.json").read_text())

    assert saved["query_generation_status"] == "llm_empty_deterministic_fallback"
    assert saved["query_generation_error"]
    assert len(saved["papers"]) == 2


@pytest.mark.asyncio
async def test_output_path_traversal_raises_and_writes_nothing(
    monkeypatch, tmp_path, isolated_literature
):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    outside_path = tmp_path / "outside.json"
    monkeypatch.setattr(lit, "create_llm", lambda **_kwargs: _MockLLM("[]"))

    with pytest.raises(ValueError):
        await lit.search_literature_dynamic_async(
            genes=[],
            pathways=[],
            celltypes=[],
            disease="cancer",
            max_results=5,
            max_iterations=1,
            query_cache=[
                {
                    "genes": [],
                    "diseases": ["cancer"],
                    "keywords": ["tumor signaling"],
                }
            ],
            output_path="../outside.json",
            data_dir=str(data_dir),
            sort_by_journal_quality=False,
        )

    assert not outside_path.exists()


def test_sync_wrapper_uses_env_data_dir_for_lr_pair_prompt(
    monkeypatch, tmp_path, isolated_literature
):
    pairs_file = tmp_path / "lr_pairs_search.json"
    pairs_file.write_text(
        json.dumps({"pairs": [{"ligand": "L1", "receptor": "R1", "score": 0.9}]})
    )
    monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", str(tmp_path))

    llm = _MockLLM(
        json.dumps([
            {
                "genes": [],
                "diseases": ["cancer"],
                "keywords": ["L1 R1 signaling"],
            }
        ])
    )
    monkeypatch.setattr(lit, "create_llm", lambda **_kwargs: llm)

    lit.search_literature_dynamic.invoke(
        {
            "genes": [],
            "pathways": [],
            "celltypes": [],
            "disease": "cancer",
            "max_results": 5,
            "max_iterations": 1,
            "enable_lr_pair_queries": True,
            "sort_by_journal_quality": False,
        }
    )

    assert llm.prompts
    assert "L1-R1" in llm.prompts[0]


def test_searcher_lr_pair_loader_prefers_lr_candidates_json(tmp_path):
    candidate_pairs = [
        {"ligand": f"CAND{i:02d}", "receptor": f"REC{i:02d}", "rank": i + 1}
        for i in range(30)
    ]
    (tmp_path / "lr_candidates.json").write_text(
        json.dumps({"pairs": candidate_pairs})
    )
    (tmp_path / "lr_pairs_search.json").write_text(
        json.dumps({"pairs": [{"ligand": "FALLBACK", "receptor": "PAIR"}]})
    )

    pairs, source = load_searcher_lr_pairs(str(tmp_path))

    assert source.endswith("lr_candidates.json")
    assert len(pairs) == 30
    assert pairs[0]["ligand"] == "CAND00"
    assert pairs[-1]["receptor"] == "REC29"


def test_searcher_lr_pair_loader_falls_back_to_lr_pairs_search_json(tmp_path):
    (tmp_path / "lr_candidates.json").write_text(json.dumps({"pairs": []}))
    (tmp_path / "lr_pairs_search.json").write_text(
        json.dumps({"pairs": [{"ligand": "L1", "receptor": "R1"}]})
    )

    pairs, source = load_searcher_lr_pairs(str(tmp_path))

    assert source.endswith("lr_pairs_search.json")
    assert pairs == [{"ligand": "L1", "receptor": "R1"}]


def test_sync_wrapper_prefers_lr_candidates_for_lr_pair_prompt(
    monkeypatch, tmp_path, isolated_literature
):
    candidate_pairs = [
        {"ligand": f"CAND{i:02d}", "receptor": f"REC{i:02d}", "rank": i + 1}
        for i in range(30)
    ]
    (tmp_path / "lr_candidates.json").write_text(
        json.dumps({"pairs": candidate_pairs})
    )
    (tmp_path / "lr_pairs_search.json").write_text(
        json.dumps({"pairs": [{"ligand": "FALLBACK", "receptor": "PAIR"}]})
    )
    monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", str(tmp_path))

    llm = _MockLLM(
        json.dumps([
            {
                "genes": [],
                "diseases": ["cancer"],
                "keywords": ["candidate signaling"],
            }
        ])
    )
    monkeypatch.setattr(lit, "create_llm", lambda **_kwargs: llm)

    lit.search_literature_dynamic.invoke(
        {
            "genes": [],
            "pathways": [],
            "celltypes": [],
            "disease": "cancer",
            "max_results": 5,
            "max_iterations": 1,
            "enable_lr_pair_queries": True,
            "sort_by_journal_quality": False,
        }
    )

    assert llm.prompts
    assert "CAND00-REC00" in llm.prompts[0]
    assert "CAND09-REC09" in llm.prompts[0]
    assert "FALLBACK-PAIR" not in llm.prompts[0]


@pytest.mark.asyncio
async def test_virtual_workspace_data_dir_uses_env_real_workspace(
    monkeypatch, tmp_path, isolated_literature
):
    monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", str(tmp_path))

    result = await lit.search_literature_dynamic_async(
        genes=[],
        pathways=[],
        celltypes=[],
        disease="cancer",
        max_results=5,
        max_iterations=1,
        query_cache=[
            {
                "genes": [],
                "diseases": ["cancer"],
                "keywords": ["tumor signaling"],
            }
        ],
        output_path="papers_raw.json",
        data_dir="/workspace",
        sort_by_journal_quality=False,
    )

    saved_path = tmp_path / "papers_raw.json"
    assert saved_path.exists()
    assert result["saved_to"] == str(saved_path.resolve())

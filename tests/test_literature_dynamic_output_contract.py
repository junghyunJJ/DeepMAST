"""Regression tests for dynamic literature output-path contract."""

import json

import pytest

from src.agents.deep_interpreter.tools import literature as lit


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

"""Tests for RAG path resolution and JSON repair helpers."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from src.agents.deep_interpreter.tools import literature_rag
from src.agents.deep_interpreter.tools.literature_rag import (
    _rag_collection_key,
    _repair_json,
    _resolve_papers_path,
)


# =============================================================================
# _resolve_papers_path tests
# =============================================================================
class TestResolvePathDirect:
    """Test path resolution when file exists at given path."""

    def test_existing_absolute_path(self, tmp_path):
        f = tmp_path / "papers.json"
        f.write_text("{}")
        result = _resolve_papers_path(str(f))
        assert result == str(f.resolve())

    def test_existing_relative_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "papers.json").write_text("{}")
        result = _resolve_papers_path("papers.json")
        assert result == str((tmp_path / "papers.json").resolve())


class TestResolvePathVirtual:
    """Test virtual path resolution via data_dir parameter."""

    def test_virtual_path_resolves_to_data_dir(self, tmp_path):
        f = tmp_path / "papers.json"
        f.write_text("{}")
        result = _resolve_papers_path("/papers.json", data_dir=str(tmp_path))
        assert result == str(f.resolve())

    def test_virtual_path_synthesis(self, tmp_path):
        f = tmp_path / "synthesis_papers.json"
        f.write_text("{}")
        result = _resolve_papers_path("/synthesis_papers.json", data_dir=str(tmp_path))
        assert result == str(f.resolve())

    def test_virtual_path_with_subdirectory(self, tmp_path):
        """Virtual path strips directory component and uses basename."""
        f = tmp_path / "papers.json"
        f.write_text("{}")
        result = _resolve_papers_path("/some/deep/papers.json", data_dir=str(tmp_path))
        assert result == str(f.resolve())


class TestResolvePathEnvVar:
    """Test virtual path resolution via DEEP_INTERPRETER_DATA_DIR env var fallback."""

    def test_env_var_fallback_resolves_path(self, tmp_path, monkeypatch):
        """When data_dir param is empty, _resolve_papers_path uses env var."""
        f = tmp_path / "papers.json"
        f.write_text("{}")
        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", str(tmp_path))
        result = _resolve_papers_path("/papers.json")
        assert result == str(f.resolve())

    def test_explicit_data_dir_takes_priority_over_env(self, tmp_path, monkeypatch):
        """Explicit data_dir param should be used even if env var is set."""
        explicit_dir = tmp_path / "explicit"
        explicit_dir.mkdir()
        env_dir = tmp_path / "envdir"
        env_dir.mkdir()

        f = explicit_dir / "papers.json"
        f.write_text("{}")

        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", str(env_dir))
        result = _resolve_papers_path("/papers.json", data_dir=str(explicit_dir))
        assert result == str(f.resolve())

    def test_env_var_not_used_when_file_exists_directly(self, tmp_path, monkeypatch):
        """Direct path match (step 1) should take priority over env var."""
        f = tmp_path / "papers.json"
        f.write_text("{}")
        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", "/some/other/dir")
        result = _resolve_papers_path(str(f))
        assert result == str(f.resolve())


class TestDataDirEnvVarIsolation:
    """Test DEEP_INTERPRETER_DATA_DIR env var set/get isolation."""

    def test_set_and_get(self, monkeypatch):
        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", "/tmp/test_dir")
        assert os.getenv("DEEP_INTERPRETER_DATA_DIR") == "/tmp/test_dir"

    def test_default_is_empty(self, monkeypatch):
        monkeypatch.delenv("DEEP_INTERPRETER_DATA_DIR", raising=False)
        assert os.getenv("DEEP_INTERPRETER_DATA_DIR", "") == ""

    def test_overwrite(self, monkeypatch):
        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", "/first")
        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", "/second")
        assert os.getenv("DEEP_INTERPRETER_DATA_DIR") == "/second"


class TestRagCollectionNamespace:
    def test_legacy_part_name_when_no_data_dir_or_env(self, monkeypatch):
        monkeypatch.delenv("DEEP_INTERPRETER_DATA_DIR", raising=False)

        assert _rag_collection_key("all") == "all"
        assert _rag_collection_key("synthesis") == "synthesis"

    def test_data_dir_namespaces_collection_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEEP_INTERPRETER_DATA_DIR", raising=False)
        data_dir = tmp_path / "tmp_final_ipf"
        data_dir.mkdir()

        key = _rag_collection_key("all", str(data_dir))

        assert key.startswith("tmp_final_ipf_")
        assert key.endswith("_all")
        assert key != "all"

    def test_same_basename_different_parent_gets_different_key(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEEP_INTERPRETER_DATA_DIR", raising=False)
        first = tmp_path / "a" / "run"
        second = tmp_path / "b" / "run"
        first.mkdir(parents=True)
        second.mkdir(parents=True)

        assert _rag_collection_key("synthesis", str(first)) != _rag_collection_key(
            "synthesis", str(second)
        )

    def test_env_data_dir_is_used_when_explicit_data_dir_missing(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "final_bc"
        data_dir.mkdir()
        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", str(data_dir))

        key = _rag_collection_key("all")

        assert key.startswith("final_bc_")
        assert key.endswith("_all")


class TestRagCollectionNamespaceRouting:
    @pytest.mark.asyncio
    async def test_prepare_rag_for_interpretation_indexes_namespaced_key(
        self, tmp_path, monkeypatch
    ):
        papers_path = tmp_path / "papers.json"
        papers_path.write_text(json.dumps({"papers": [{"pmid": "12345678"}]}))
        paper_file = tmp_path / "pmid_12345678.txt"
        paper_file.write_text("full text")
        captured = {}

        async def fake_check_rag_availability():
            return True

        async def fake_download_papers_for_rag(pmids, output_dir):
            return {
                "12345678": {
                    "success": True,
                    "file_path": str(paper_file),
                    "source": "test",
                }
            }

        async def fake_index_papers_to_vectordb(file_paths, collection_name):
            captured["file_paths"] = file_paths
            captured["collection_name"] = collection_name
            return {
                "success": True,
                "collection_id": "collection-id",
                "collection_name": f"deep_interpreter_{collection_name}",
                "sni_mode": True,
                "sni_rebuild": '{"status":"success"}',
                "sni_message": "SNI rebuild completed",
            }

        monkeypatch.setattr(
            literature_rag, "check_rag_availability", fake_check_rag_availability
        )
        monkeypatch.setattr(
            literature_rag, "download_papers_for_rag", fake_download_papers_for_rag
        )
        monkeypatch.setattr(
            literature_rag, "index_papers_to_vectordb", fake_index_papers_to_vectordb
        )

        result = await literature_rag.prepare_rag_for_interpretation(
            str(papers_path),
            part_name="all",
            data_dir=str(tmp_path),
        )

        expected_key = _rag_collection_key("all", str(tmp_path))
        assert captured["collection_name"] == expected_key
        assert captured["file_paths"] == [str(paper_file)]
        assert result["collection_key"] == expected_key
        assert result["collection_part_name"] == "all"
        assert result["collection_name"] == f"deep_interpreter_{expected_key}"
        assert result["sni_mode"] is True
        assert result["sni_rebuild"] == '{"status":"success"}'
        assert result["sni_message"] == "SNI rebuild completed"

    def test_search_literature_fulltext_uses_namespaced_key(self, tmp_path, monkeypatch):
        literature_rag.reset_rag_state()
        literature_rag._RAG_STATE["available"] = True
        captured = {}

        async def fake_search_fulltext_rag(query, collection_name, limit):
            captured["query"] = query
            captured["collection_name"] = collection_name
            captured["limit"] = limit
            return [{"page_content": "matched text"}]

        monkeypatch.setattr(literature_rag, "search_fulltext_rag", fake_search_fulltext_rag)

        result = literature_rag.search_literature_fulltext.invoke(
            {
                "query": "ICAM1 fibrosis",
                "part_name": "all",
                "limit": 3,
                "data_dir": str(tmp_path),
            }
        )

        assert result == [{"page_content": "matched text"}]
        assert captured["collection_name"] == _rag_collection_key("all", str(tmp_path))
        assert captured["query"] == "ICAM1 fibrosis"
        assert captured["limit"] == 3

    def test_search_literature_fulltext_strict_raises_rag_search_error(
        self, tmp_path, monkeypatch
    ):
        literature_rag.reset_rag_state()
        literature_rag._RAG_STATE["available"] = True

        async def failing_search_fulltext_rag(
            query, collection_name, limit, strict: bool = False
        ):
            if not strict:
                return []
            assert strict is True
            raise RuntimeError("rag backend down")

        monkeypatch.setattr(
            literature_rag, "search_fulltext_rag", failing_search_fulltext_rag
        )

        default_result = literature_rag.search_literature_fulltext.invoke(
            {
                "query": "ICAM1 fibrosis",
                "part_name": "all",
                "limit": 3,
                "data_dir": str(tmp_path),
            }
        )
        assert default_result == []

        with pytest.raises(literature_rag.RAGSearchError):
            literature_rag.search_literature_fulltext.invoke(
                {
                    "query": "ICAM1 fibrosis",
                    "part_name": "all",
                    "limit": 3,
                    "data_dir": str(tmp_path),
                    "strict": True,
                }
            )

    def test_search_literature_fulltext_missing_collection_default_empty_strict_raises(
        self, tmp_path, monkeypatch
    ):
        literature_rag.reset_rag_state()
        literature_rag._RAG_STATE["available"] = True

        async def missing_collection(collection_name):
            return None

        monkeypatch.setattr(
            literature_rag, "_lookup_collection_from_db", missing_collection
        )

        args = {
            "query": "ICAM1 fibrosis",
            "part_name": "all",
            "limit": 3,
            "data_dir": str(tmp_path),
        }

        assert literature_rag.search_literature_fulltext.invoke(args) == []

        with pytest.raises(literature_rag.RAGSearchError):
            literature_rag.search_literature_fulltext.invoke({**args, "strict": True})

    def test_search_literature_fulltext_unavailable_default_empty_strict_raises(
        self, tmp_path
    ):
        literature_rag.reset_rag_state()
        literature_rag._RAG_STATE["available"] = False
        args = {
            "query": "ICAM1 fibrosis",
            "part_name": "all",
            "limit": 3,
            "data_dir": str(tmp_path),
        }

        assert literature_rag.search_literature_fulltext.invoke(args) == []

        with pytest.raises(literature_rag.RAGSearchError):
            literature_rag.search_literature_fulltext.invoke({**args, "strict": True})

    def test_validate_claim_fulltext_uses_namespaced_key(self, tmp_path, monkeypatch):
        literature_rag.reset_rag_state()
        literature_rag._RAG_STATE["available"] = True
        captured = {}

        async def fake_validate_claim_with_rag(claim, pmid, collection_name):
            captured["claim"] = claim
            captured["pmid"] = pmid
            captured["collection_name"] = collection_name
            return {"valid": True, "confidence": 0.9}

        monkeypatch.setattr(
            literature_rag, "validate_claim_with_rag", fake_validate_claim_with_rag
        )

        result = literature_rag.validate_claim_fulltext.invoke(
            {
                "claim": "ICAM1 is involved in fibrosis",
                "pmid": "12345678",
                "part_name": "all",
                "data_dir": str(tmp_path),
            }
        )

        assert result == {"valid": True, "confidence": 0.9}
        assert captured["collection_name"] == _rag_collection_key("all", str(tmp_path))
        assert captured["claim"] == "ICAM1 is involved in fibrosis"
        assert captured["pmid"] == "12345678"


class TestRagSniIntegration:
    @pytest.mark.asyncio
    async def test_index_papers_rebuilds_llm_wiki_after_new_index(self, monkeypatch):
        literature_rag.reset_rag_state()

        class FakeTool:
            def __init__(self, name, result):
                self.name = name
                self.result = result
                self.calls = []

            async def ainvoke(self, args):
                self.calls.append(args)
                return self.result

        create = FakeTool("create_collection", {"id": "collection-id"})
        add_docs = FakeTool("add_documents_from_files", {"added_chunk_ids": ["chunk-1"]})
        rebuild = FakeTool("rebuild_llm_wiki", '{"status":"success"}')

        async def fake_tools():
            return [create, add_docs, rebuild]

        monkeypatch.setattr(literature_rag, "_get_cci_rag_tools", fake_tools)

        result = await literature_rag.index_papers_to_vectordb(
            ["/tmp/paper.txt"],
            "all",
        )

        assert result["success"] is True
        assert result["collection_id"] == "collection-id"
        assert result["sni_mode"] is True
        assert add_docs.calls[0]["chunk_size"] == 3000
        assert add_docs.calls[0]["chunk_overlap"] == 200
        assert rebuild.calls == [{"collection_id": "collection-id"}]

    @pytest.mark.asyncio
    async def test_index_papers_batches_large_uploads(self, monkeypatch):
        literature_rag.reset_rag_state()

        class FakeTool:
            def __init__(self, name, result):
                self.name = name
                self.result = result
                self.calls = []

            async def ainvoke(self, args):
                self.calls.append(args)
                return self.result

        create = FakeTool("create_collection", {"id": "collection-id"})
        add_docs = FakeTool("add_documents_from_files", {"added_chunk_ids": ["chunk"]})
        rebuild = FakeTool("rebuild_llm_wiki", '{"status":"success"}')

        async def fake_tools():
            return [create, add_docs, rebuild]

        monkeypatch.setattr(literature_rag, "_get_cci_rag_tools", fake_tools)

        files = [f"/tmp/paper-{index}.txt" for index in range(21)]
        result = await literature_rag.index_papers_to_vectordb(files, "all")

        assert result["success"] is True
        assert [len(call["file_paths"]) for call in add_docs.calls] == [20, 1]

    @pytest.mark.asyncio
    async def test_index_papers_deletes_new_partial_collection_after_batch_failure(
        self, monkeypatch
    ):
        literature_rag.reset_rag_state()

        class FakeTool:
            def __init__(self, name, results):
                self.name = name
                self.results = iter(results)
                self.calls = []

            async def ainvoke(self, args):
                self.calls.append(args)
                return next(self.results)

        create = FakeTool("create_collection", [{"id": "collection-id"}])
        add_docs = FakeTool(
            "add_documents_from_files",
            [{"added_chunk_ids": ["chunk-1"]}, {"added_chunk_ids": []}],
        )
        delete = FakeTool("delete_collection", ["deleted"])

        async def fake_tools():
            return [create, add_docs, delete]

        monkeypatch.setattr(literature_rag, "_get_cci_rag_tools", fake_tools)

        result = await literature_rag.index_papers_to_vectordb(
            [f"/tmp/paper-{index}.txt" for index in range(21)], "all"
        )

        assert result["success"] is False
        assert delete.calls == [{"collection_id": "collection-id"}]
        assert "all" not in literature_rag._RAG_STATE["collection_ids"]

    @pytest.mark.asyncio
    async def test_index_papers_accepts_mcp_success_text(self, monkeypatch):
        literature_rag.reset_rag_state()

        class FakeTool:
            def __init__(self, name, result):
                self.name = name
                self.result = result

            async def ainvoke(self, _args):
                return self.result

        create = FakeTool("create_collection", {"id": "collection-id"})
        add_docs = FakeTool(
            "add_documents_from_files",
            [{"text": "Uploaded 1 file(s) successfully! Created 3 total chunks."}],
        )
        rebuild = FakeTool("rebuild_llm_wiki", '{"status":"success"}')

        async def fake_tools():
            return [create, add_docs, rebuild]

        monkeypatch.setattr(literature_rag, "_get_cci_rag_tools", fake_tools)

        result = await literature_rag.index_papers_to_vectordb(["/tmp/paper.txt"], "all")

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_index_papers_skips_llm_wiki_rebuild_for_existing_collection(
        self, monkeypatch
    ):
        literature_rag.reset_rag_state()

        class FakeTool:
            def __init__(self, name, result):
                self.name = name
                self.result = result
                self.calls = []

            async def ainvoke(self, args):
                self.calls.append(args)
                return self.result

        list_collections = FakeTool(
            "list_collections",
            [{"name": "deep_interpreter_all", "id": "collection-id"}],
        )
        add_docs = FakeTool("add_documents_from_files", {"added_chunk_ids": ["chunk-1"]})
        rebuild = FakeTool("rebuild_llm_wiki", '{"status":"success"}')

        async def fake_tools():
            return [list_collections, add_docs, rebuild]

        monkeypatch.setattr(literature_rag, "_get_cci_rag_tools", fake_tools)

        result = await literature_rag.index_papers_to_vectordb(
            ["/tmp/paper.txt"],
            "all",
        )

        assert result["success"] is True
        assert result["already_indexed"] is True
        assert result["sni_mode"] is False
        assert add_docs.calls == []
        assert rebuild.calls == []

    @pytest.mark.asyncio
    async def test_search_fulltext_rag_prefers_agentic_search_with_wiki_context(
        self, monkeypatch
    ):
        monkeypatch.delenv("DEEP_INTERPRETER_USE_WIKI_CONTEXT", raising=False)
        literature_rag.reset_rag_state()
        literature_rag._RAG_STATE["collection_ids"]["all"] = "collection-id"

        class FakeTool:
            name = "agentic_search"

            def __init__(self):
                self.calls = []

            async def ainvoke(self, args):
                self.calls.append(args)
                return json.dumps(
                    {
                        "answer": "ICAM1 is linked to fibrosis.",
                        "sources": [
                            {
                                "content": (
                                    "ICAM1 supports inflammatory fibroblast signaling."
                                ),
                                "metadata": {"filename": "pmid_12345678.txt"},
                                "score": 0.91,
                            }
                        ],
                        "steps": ["wiki_promotion: promoted 1/1 refs"],
                        "selected_wiki_pages": [{"title": "ICAM1 fibrosis"}],
                        "wiki_context_status": "selected",
                    }
                )

        agentic = FakeTool()

        async def fake_tools():
            return [agentic]

        monkeypatch.setattr(literature_rag, "_get_cci_rag_tools", fake_tools)

        result = await literature_rag.search_fulltext_rag(
            "ICAM1 fibrosis",
            "all",
            limit=5,
        )

        assert agentic.calls == [
            {
                "collection_id": "collection-id",
                "question": "ICAM1 fibrosis",
                "search_type": "hybrid",
                "search_limit": 5,
                "max_rewrites": 3,
                "use_wiki_context": True,
            }
        ]
        assert result[0]["page_content"] == (
            "ICAM1 supports inflammatory fibroblast signaling."
        )
        assert result[0]["metadata"]["filename"] == "pmid_12345678.txt"
        assert result[0]["metadata"]["rag_backend"] == "agentic_search"
        assert result[0]["metadata"]["wiki_context_status"] == "selected"

    @pytest.mark.asyncio
    async def test_search_fulltext_rag_can_disable_wiki_context_per_run(
        self, tmp_path, monkeypatch
    ):
        literature_rag.reset_rag_state()
        literature_rag._RAG_STATE["collection_ids"]["all"] = "collection-id"
        monkeypatch.setenv("DEEP_INTERPRETER_USE_WIKI_CONTEXT", "false")
        monkeypatch.setenv(
            "DEEP_INTERPRETER_RAG_AUDIT_PATH", str(tmp_path / "rag-audit.jsonl")
        )

        class FakeTool:
            name = "agentic_search"

            def __init__(self):
                self.calls = []

            async def ainvoke(self, args):
                self.calls.append(args)
                return {
                    "sources": [
                        {
                            "content": "ICAM1 supports inflammatory fibroblast signaling.",
                            "metadata": {"filename": "pmid_12345678.txt"},
                            "score": 0.91,
                        }
                    ],
                    "wiki_context_status": "disabled",
                }

        agentic = FakeTool()

        async def fake_tools():
            return [agentic]

        monkeypatch.setattr(literature_rag, "_get_cci_rag_tools", fake_tools)

        result = await literature_rag.search_fulltext_rag(
            "ICAM1 fibrosis",
            "all",
            limit=5,
        )

        assert agentic.calls == [
            {
                "collection_id": "collection-id",
                "question": "ICAM1 fibrosis",
                "search_type": "hybrid",
                "search_limit": 5,
                "max_rewrites": 3,
                "use_wiki_context": False,
            }
        ]
        assert result[0]["page_content"] == (
            "ICAM1 supports inflammatory fibroblast signaling."
        )
        audit = json.loads((tmp_path / "rag-audit.jsonl").read_text())
        assert audit == {
            "endpoint": "agentic_search",
            "collection_uuid": "collection-id",
            "use_wiki_context": False,
            "success": True,
            "result_count": 1,
            "error_type": None,
        }

    @pytest.mark.asyncio
    async def test_search_fulltext_rag_fixed_collection_override_bypasses_name_resolution(
        self, tmp_path, monkeypatch
    ):
        literature_rag.reset_rag_state()
        literature_rag._RAG_STATE["collection_ids"][
            "model supplied mismatched collection key"
        ] = "wrong-cache-id"
        monkeypatch.setenv("DEEP_INTERPRETER_FIXED_COLLECTION_ID", "fixed-collection-id")
        monkeypatch.setenv(
            "DEEP_INTERPRETER_RAG_AUDIT_PATH", str(tmp_path / "rag-audit.jsonl")
        )

        class FakeTool:
            name = "agentic_search"

            def __init__(self):
                self.calls = []

            async def ainvoke(self, args):
                self.calls.append(args)
                return {
                    "sources": [
                        {
                            "content": "fixed collection chunk",
                            "metadata": {"filename": "pmid_12345678.txt"},
                            "score": 0.91,
                        }
                    ],
                    "wiki_context_status": "selected",
                }

        agentic = FakeTool()

        async def fake_tools():
            return [agentic]

        async def lookup_must_not_run(collection_name):
            raise AssertionError(f"DB lookup should not run for {collection_name}")

        monkeypatch.setattr(literature_rag, "_get_cci_rag_tools", fake_tools)
        monkeypatch.setattr(literature_rag, "_lookup_collection_from_db", lookup_must_not_run)

        result = await literature_rag.search_fulltext_rag(
            "ICAM1 fibrosis",
            "model supplied mismatched collection key",
            limit=5,
        )

        assert agentic.calls[0]["collection_id"] == "fixed-collection-id"
        assert result[0]["page_content"] == "fixed collection chunk"

        literature_rag._RAG_STATE["collection_ids"].clear()
        result = await literature_rag.search_fulltext_rag(
            "ICAM1 fibrosis",
            "uncached model supplied key",
            limit=5,
        )

        assert agentic.calls[1]["collection_id"] == "fixed-collection-id"
        assert result[0]["page_content"] == "fixed collection chunk"
        audit_records = [
            json.loads(line)
            for line in (tmp_path / "rag-audit.jsonl").read_text().splitlines()
        ]
        assert [record["collection_uuid"] for record in audit_records] == [
            "fixed-collection-id",
            "fixed-collection-id",
        ]

    @pytest.mark.asyncio
    async def test_search_fulltext_rag_required_agentic_raises_before_fallback(
        self, monkeypatch
    ):
        literature_rag.reset_rag_state()
        literature_rag._RAG_STATE["collection_ids"]["all"] = "collection-id"
        monkeypatch.setenv("DEEP_INTERPRETER_REQUIRE_AGENTIC_RAG", "true")

        class EmptyAgenticTool:
            name = "agentic_search"

            async def ainvoke(self, args):
                return {"sources": []}

        async def fake_tools():
            return [EmptyAgenticTool()]

        async def fallback_must_not_run(query, num_queries=5):
            raise AssertionError("multi-query fallback should not run")

        monkeypatch.setattr(literature_rag, "_get_cci_rag_tools", fake_tools)
        monkeypatch.setattr(literature_rag, "generate_multi_query", fallback_must_not_run)

        with pytest.raises(literature_rag.RAGSearchError):
            await literature_rag.search_fulltext_rag("ICAM1 fibrosis", "all", limit=5)

    @pytest.mark.asyncio
    async def test_search_fulltext_rag_audit_write_failure_keeps_agentic_result(
        self, tmp_path, monkeypatch
    ):
        literature_rag.reset_rag_state()
        literature_rag._RAG_STATE["collection_ids"]["all"] = "collection-id"
        not_a_dir = tmp_path / "not-a-dir"
        not_a_dir.write_text("file blocks audit directory creation")
        monkeypatch.setenv("DEEP_INTERPRETER_RAG_AUDIT_PATH", str(not_a_dir / "audit.jsonl"))

        class FakeTool:
            name = "agentic_search"

            async def ainvoke(self, args):
                return {
                    "sources": [
                        {
                            "content": "agentic chunk survives audit failure",
                            "metadata": {"filename": "pmid_12345678.txt"},
                            "score": 0.91,
                        }
                    ]
                }

        async def fake_tools():
            return [FakeTool()]

        async def fallback_must_not_run(query, num_queries=5):
            raise AssertionError("multi-query fallback should not run")

        monkeypatch.setattr(literature_rag, "_get_cci_rag_tools", fake_tools)
        monkeypatch.setattr(literature_rag, "generate_multi_query", fallback_must_not_run)

        result = await literature_rag.search_fulltext_rag(
            "ICAM1 fibrosis",
            "all",
            limit=5,
        )

        assert result[0]["page_content"] == "agentic chunk survives audit failure"

    @pytest.mark.asyncio
    async def test_search_fulltext_rag_falls_back_when_agentic_search_fails(
        self, monkeypatch
    ):
        literature_rag.reset_rag_state()
        literature_rag._RAG_STATE["collection_ids"]["all"] = "collection-id"

        class FailingAgenticTool:
            name = "agentic_search"

            async def ainvoke(self, args):
                raise RuntimeError("agentic unavailable")

        async def fake_tools():
            return [FailingAgenticTool()]

        async def fake_generate_multi_query(query, num_queries=5):
            return [query]

        async def fake_search_single_query(query, collection_id, limit, search_type):
            return [
                {
                    "page_content": "fallback chunk",
                    "metadata": {"filename": "pmid_12345678.txt"},
                    "score": 0.7,
                }
            ]

        monkeypatch.setattr(literature_rag, "_get_cci_rag_tools", fake_tools)
        monkeypatch.setattr(
            literature_rag, "generate_multi_query", fake_generate_multi_query
        )
        monkeypatch.setattr(
            literature_rag, "_search_single_query", fake_search_single_query
        )

        result = await literature_rag.search_fulltext_rag(
            "ICAM1 fibrosis",
            "all",
            limit=5,
        )

        assert result == [
            {
                "page_content": "fallback chunk",
                "metadata": {"filename": "pmid_12345678.txt"},
                "score": 0.7,
            }
        ]

    @pytest.mark.asyncio
    async def test_search_fulltext_rag_default_returns_empty_when_all_standard_queries_error(
        self, monkeypatch
    ):
        literature_rag.reset_rag_state()
        literature_rag._RAG_STATE["collection_ids"]["all"] = "collection-id"

        async def fake_agentic_search_with_sni(query, collection_id, limit, search_type):
            return []

        async def fake_generate_multi_query(query, num_queries=5):
            return [query, f"{query} mechanism"]

        async def failing_search_single_query(query, collection_id, limit, search_type):
            raise RuntimeError(f"standard search failed for {query}")

        monkeypatch.setattr(
            literature_rag,
            "_agentic_search_with_sni",
            fake_agentic_search_with_sni,
        )
        monkeypatch.setattr(
            literature_rag, "generate_multi_query", fake_generate_multi_query
        )
        monkeypatch.setattr(
            literature_rag, "_search_single_query", failing_search_single_query
        )

        result = await literature_rag.search_fulltext_rag("ICAM1 fibrosis", "all")

        assert result == []

    @pytest.mark.asyncio
    async def test_search_fulltext_rag_strict_raises_when_all_standard_queries_error(
        self, monkeypatch
    ):
        literature_rag.reset_rag_state()
        literature_rag._RAG_STATE["collection_ids"]["all"] = "collection-id"

        async def fake_agentic_search_with_sni(query, collection_id, limit, search_type):
            return []

        async def fake_generate_multi_query(query, num_queries=5):
            return [query, f"{query} mechanism"]

        async def failing_search_single_query(
            query, collection_id, limit, search_type, strict: bool = False
        ):
            raise RuntimeError(f"standard search failed for {query}")

        monkeypatch.setattr(
            literature_rag,
            "_agentic_search_with_sni",
            fake_agentic_search_with_sni,
        )
        monkeypatch.setattr(
            literature_rag, "generate_multi_query", fake_generate_multi_query
        )
        monkeypatch.setattr(
            literature_rag, "_search_single_query", failing_search_single_query
        )

        with pytest.raises(literature_rag.RAGSearchError):
            await literature_rag.search_fulltext_rag(
                "ICAM1 fibrosis", "all", strict=True
            )

    @pytest.mark.asyncio
    async def test_search_fulltext_rag_strict_returns_empty_for_successful_zero_hits(
        self, monkeypatch
    ):
        literature_rag.reset_rag_state()
        literature_rag._RAG_STATE["collection_ids"]["all"] = "collection-id"

        async def fake_agentic_search_with_sni(query, collection_id, limit, search_type):
            return []

        async def fake_generate_multi_query(query, num_queries=5):
            return [query]

        saw_strict = False

        async def zero_hit_search_single_query(
            query, collection_id, limit, search_type, strict: bool = False
        ):
            nonlocal saw_strict
            saw_strict = strict
            return []

        monkeypatch.setattr(
            literature_rag,
            "_agentic_search_with_sni",
            fake_agentic_search_with_sni,
        )
        monkeypatch.setattr(
            literature_rag, "generate_multi_query", fake_generate_multi_query
        )
        monkeypatch.setattr(
            literature_rag, "_search_single_query", zero_hit_search_single_query
        )

        result = await literature_rag.search_fulltext_rag(
            "ICAM1 fibrosis", "all", strict=True
        )

        assert result == []
        assert saw_strict is True


class TestResolvePathFallback:
    """Test fallback CWD resolution when file not found."""

    def test_fallback_when_no_data_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DEEP_INTERPRETER_DATA_DIR", raising=False)
        result = _resolve_papers_path("/nonexistent.json")
        # Should still return a resolved absolute path (even if file doesn't exist)
        assert Path(result).is_absolute()

    def test_fallback_when_file_not_in_data_dir(self, tmp_path):
        result = _resolve_papers_path("/missing_file.json", data_dir=str(tmp_path))
        assert Path(result).is_absolute()


# =============================================================================
# _repair_json tests
# =============================================================================
class TestRepairJsonValid:
    """Test that valid JSON passes through unchanged."""

    def test_valid_dict(self):
        data = {"papers": [{"pmid": "123"}]}
        result = _repair_json(json.dumps(data))
        assert result == data

    def test_valid_list(self):
        data = [{"pmid": "123"}, {"pmid": "456"}]
        result = _repair_json(json.dumps(data))
        assert result == data

    def test_valid_empty_object(self):
        assert _repair_json("{}") == {}

    def test_valid_empty_array(self):
        assert _repair_json("[]") == []


class TestRepairJsonTrailingComma:
    """Test repair of trailing commas (common LLM error)."""

    def test_trailing_comma_in_array(self):
        raw = '{"papers": [{"pmid": "123"},]}'
        result = _repair_json(raw)
        assert result == {"papers": [{"pmid": "123"}]}

    def test_trailing_comma_in_object(self):
        raw = '{"key": "value",}'
        result = _repair_json(raw)
        assert result == {"key": "value"}

    def test_multiple_trailing_commas(self):
        raw = '{"a": [1, 2, 3,], "b": {"x": 1,},}'
        result = _repair_json(raw)
        assert result == {"a": [1, 2, 3], "b": {"x": 1}}


class TestRepairJsonBraces:
    """Test repair of mismatched braces/brackets."""

    def test_extra_closing_brace(self):
        raw = '{"papers": [{"pmid": "123"}]}}'
        result = _repair_json(raw)
        assert result == {"papers": [{"pmid": "123"}]}

    def test_missing_closing_brace(self):
        raw = '{"papers": [{"pmid": "123"}]'
        result = _repair_json(raw)
        assert result == {"papers": [{"pmid": "123"}]}

    def test_extra_closing_bracket(self):
        raw = '[{"pmid": "123"}]]'
        result = _repair_json(raw)
        assert result == [{"pmid": "123"}]

    def test_missing_closing_bracket(self):
        raw = '[{"pmid": "123"}'
        result = _repair_json(raw)
        assert result == [{"pmid": "123"}]


class TestRepairJsonCombined:
    """Test combined errors (trailing comma + brace issues)."""

    def test_trailing_comma_and_missing_brace(self):
        """Simulates actual papers.json corruption."""
        raw = '{"papers": [{"pmid": "123"}, {"pmid": "456"},]'
        result = _repair_json(raw)
        assert result == {"papers": [{"pmid": "123"}, {"pmid": "456"}]}

    def test_trailing_comma_and_extra_brace(self):
        raw = '{"papers": [{"pmid": "123"},]}}'
        result = _repair_json(raw)
        assert result == {"papers": [{"pmid": "123"}]}


class TestRepairJsonUnrecoverable:
    """Test that truly broken JSON still raises."""

    def test_completely_invalid(self):
        with pytest.raises(json.JSONDecodeError):
            _repair_json("not json at all")

    def test_truncated_string(self):
        with pytest.raises(json.JSONDecodeError):
            _repair_json('{"key": "unterminated')

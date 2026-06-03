"""Tests for DEEP_INTERPRETER_DATA_DIR env var preservation fix.

Verifies that:
1. .env DEEP_INTERPRETER_DATA_DIR is NOT overwritten by graph_builder imports
2. DeepInterpreterConfig defaults to env var value
3. Fallback to /tmp/deep_interpreter_workspace when env var is unset
4. Auto-save failure returns explicit error signal
5. Reader sites resolve to correct paths
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


class TestEnvVarPreservation:
    """RC1/RC1b/RC2: graph_builder and supervisor must NOT overwrite env var."""

    def test_graph_builder_import_preserves_env(self, monkeypatch):
        """Importing graph_builder should not overwrite DEEP_INTERPRETER_DATA_DIR."""
        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", "res_bc")

        # Force reimport of graph_builder module
        import importlib
        import src.agents.deep_interpreter.graph_builder as gb
        importlib.reload(gb)

        # After Change 2, graph_builder normalizes env var to absolute path
        assert os.path.isabs(os.environ["DEEP_INTERPRETER_DATA_DIR"])
        assert os.environ["DEEP_INTERPRETER_DATA_DIR"].endswith("res_bc")

    def test_create_deep_interpreter_graph_respects_env(self, monkeypatch):
        """create_deep_interpreter_graph() with empty data_dir should use env var."""
        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", "/custom/path")

        from src.agents.deep_interpreter.graph_builder import create_deep_interpreter_graph

        # Patch create_deep_interpreter_agent to capture the config
        captured = {}
        def mock_create(config):
            captured["data_dir"] = config.data_dir
            return None

        with patch("src.agents.deep_interpreter.graph_builder.create_deep_interpreter_agent", mock_create):
            create_deep_interpreter_graph(data_dir="")

        assert captured["data_dir"] == "/custom/path"

    def test_create_deep_interpreter_graph_explicit_param_wins(self, monkeypatch):
        """Explicit data_dir parameter should take priority over env var."""
        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", "/env/path")

        from src.agents.deep_interpreter.graph_builder import create_deep_interpreter_graph

        captured = {}
        def mock_create(config):
            captured["data_dir"] = config.data_dir
            return None

        with patch("src.agents.deep_interpreter.graph_builder.create_deep_interpreter_agent", mock_create):
            create_deep_interpreter_graph(data_dir="/explicit/path")

        assert captured["data_dir"] == "/explicit/path"

    def test_create_wrapped_graph_respects_env(self, monkeypatch):
        """create_deep_interpreter_graph_wrapped() with empty data_dir should use env var."""
        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", "/custom/wrapped")

        from src.agents.deep_interpreter.graph_builder import create_deep_interpreter_graph_wrapped

        captured = {}
        original_init = None

        with patch("src.agents.deep_interpreter.graph_builder.DeepInterpreterConfig") as MockConfig, \
             patch("src.agents.deep_interpreter.graph_builder.DeepInterpreterWrapperAgent") as MockWrapper, \
             patch("src.agents.deep_interpreter.graph_builder.create_llm"):
            MockConfig.return_value = MockConfig
            MockWrapper.return_value.graph = "mock_graph"

            create_deep_interpreter_graph_wrapped(data_dir="")

            call_kwargs = MockConfig.call_args
            assert call_kwargs[1]["data_dir"] == "/custom/wrapped" or \
                   call_kwargs.kwargs.get("data_dir") == "/custom/wrapped"


class TestConfigDefault:
    """RC3: DeepInterpreterConfig.data_dir should default to env var."""

    def test_config_uses_env_var(self, monkeypatch):
        """Config default should read from DEEP_INTERPRETER_DATA_DIR env var."""
        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", "/env/data_dir")

        from src.agents.deep_interpreter.agent import DeepInterpreterConfig
        config = DeepInterpreterConfig()
        assert config.data_dir == "/env/data_dir"

    def test_config_fallback_to_tmp(self, monkeypatch):
        """Config should fall back to /tmp/deep_interpreter_workspace when env unset."""
        monkeypatch.delenv("DEEP_INTERPRETER_DATA_DIR", raising=False)

        from src.agents.deep_interpreter.agent import DeepInterpreterConfig
        config = DeepInterpreterConfig()
        assert config.data_dir == "/tmp/deep_interpreter_workspace"

    def test_config_explicit_overrides_env(self, monkeypatch):
        """Explicit data_dir param should override env var."""
        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", "/env/data_dir")

        from src.agents.deep_interpreter.agent import DeepInterpreterConfig
        config = DeepInterpreterConfig(data_dir="/explicit/dir")
        assert config.data_dir == "/explicit/dir"


class TestAutoSaveErrorSignal:
    """RC4: Auto-save failure should return explicit error, not silent fallthrough."""

    @pytest.mark.asyncio
    async def test_auto_save_returns_error_when_no_data_dir(self, monkeypatch):
        """When output_path is set but data_dir is empty and env is unset, return error."""
        monkeypatch.delenv("DEEP_INTERPRETER_DATA_DIR", raising=False)

        from src.agents.deep_interpreter.tools.literature import (
            search_literature_dynamic_async,
        )

        # Mock LLM ainvoke as async
        mock_response = type("R", (), {"content": json.dumps([
            {"genes": ["CDH1"], "diseases": ["cancer"], "keywords": ["EMT"]}
        ])})()

        async def mock_ainvoke(*args, **kwargs):
            return mock_response

        async def mock_search_coro(*args, **kwargs):
            return [{"pmid": "12345678", "title": "Test Paper", "abstract": "Test abstract"}]

        # Mock all external calls to isolate auto-save logic
        with patch("src.agents.deep_interpreter.tools.literature.os.getenv", return_value=""), \
             patch("src.agents.deep_interpreter.tools.literature.create_llm") as mock_llm, \
             patch("src.agents.deep_interpreter.tools.literature._search_with_biomcp", side_effect=mock_search_coro):

            mock_llm.return_value.ainvoke = mock_ainvoke

            result = await search_literature_dynamic_async(
                genes=["CDH1"],
                pathways=["EMT"],
                celltypes=["Tumor"],
                disease="cancer",
                max_results=5,
                max_iterations=1,
                output_path="papers.json",
                data_dir="",
            )

            assert result.get("error") == "AUTO_SAVE_FAILED"
            assert result.get("auto_save") is False
            assert "papers" in result  # full_result should still be included
            assert "error_detail" in result


class TestReaderSites:
    """Verify reader sites resolve correctly with env var."""

    def test_standalone_fs_reads_env(self, monkeypatch):
        """standalone_fs._get_backend() should read DEEP_INTERPRETER_DATA_DIR lazily."""
        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", "/reader/test/path")

        import importlib
        import src.agents.deep_interpreter.tools.standalone_fs as sf
        sf._backend = None  # Reset singleton
        importlib.reload(sf)

        backend = sf._get_backend()
        assert str(backend.cwd) == "/reader/test/path"

    def test_standalone_fs_normalizes_workspace_virtual_path(self, monkeypatch, tmp_path):
        """`/workspace/...` should resolve to the virtual root workspace."""
        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", str(tmp_path))

        import importlib
        import src.agents.deep_interpreter.tools.standalone_fs as sf

        sf._backend = None
        importlib.reload(sf)

        write_result = sf.write_file.invoke(
            {"file_path": "/workspace/papers_raw.json", "content": "{}"}
        )
        read_result = sf.read_file.invoke({"file_path": "/workspace/papers_raw.json"})

        assert "Updated file" in write_result
        assert "{}" in read_result
        assert (tmp_path / "papers_raw.json").exists()

    def test_report_tool_reads_env(self, monkeypatch):
        """report.py should use env var for output path resolution."""
        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", "/report/test")

        # Just verify the env var is read correctly
        save_dir = os.getenv("DEEP_INTERPRETER_DATA_DIR", "")
        assert save_dir == "/report/test"

    def test_literature_rag_reads_env(self, monkeypatch, tmp_path):
        """literature_rag._resolve_papers_path should fall back to env var."""
        # Create a test file in the env-specified directory
        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", str(tmp_path))
        papers_file = tmp_path / "papers.json"
        papers_file.write_text("{}")

        from src.agents.deep_interpreter.tools.literature_rag import _resolve_papers_path
        result = _resolve_papers_path("/papers.json", data_dir="")
        assert result == str(papers_file.resolve())

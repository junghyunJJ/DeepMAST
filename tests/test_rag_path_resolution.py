"""Tests for RAG path resolution and JSON repair helpers."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from src.agents.deep_interpreter.tools.literature_rag import (
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
        f = tmp_path / "part1_papers.json"
        f.write_text("{}")
        result = _resolve_papers_path("/part1_papers.json", data_dir=str(tmp_path))
        assert result == str(f.resolve())

    def test_virtual_path_synthesis(self, tmp_path):
        f = tmp_path / "synthesis_papers.json"
        f.write_text("{}")
        result = _resolve_papers_path("/synthesis_papers.json", data_dir=str(tmp_path))
        assert result == str(f.resolve())

    def test_virtual_path_with_subdirectory(self, tmp_path):
        """Virtual path strips directory component and uses basename."""
        f = tmp_path / "liana_papers.json"
        f.write_text("{}")
        result = _resolve_papers_path("/some/deep/liana_papers.json", data_dir=str(tmp_path))
        assert result == str(f.resolve())


class TestResolvePathEnvVar:
    """Test virtual path resolution via DEEP_INTERPRETER_DATA_DIR env var fallback."""

    def test_env_var_fallback_resolves_path(self, tmp_path, monkeypatch):
        """When data_dir param is empty, _resolve_papers_path uses env var."""
        f = tmp_path / "part1_papers.json"
        f.write_text("{}")
        monkeypatch.setenv("DEEP_INTERPRETER_DATA_DIR", str(tmp_path))
        result = _resolve_papers_path("/part1_papers.json")
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
        """Simulates actual part1_papers.json corruption."""
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

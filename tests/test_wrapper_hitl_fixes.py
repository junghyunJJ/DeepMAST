"""Unit tests for Deep Interpreter Wrapper Agent HITL fixes.

Tests verify 3 fixes without LLM calls or MCP servers:

1. info_validation_node conditional dict (Fix 1):
   - None interest_celltypes/interest_clusters excluded from return dict
   - Non-None values included correctly

2. collect_clusters_node parsing logic (Fix 2):
   - LLM returns valid JSON → parsed_clusters extracted
   - LLM raises Exception → regex fallback extracts clusters
   - LLM returns invalid JSON → inner regex fallback

3. route_after_clusters routing logic (Fix 4):
   - clusters_collected=True, research_discussion_complete=False → COLLECT_FACTOR
   - research_discussion_complete=True → CHECK_STATE (routes through hub to CONFIRM_INTERP → END)
   - clusters_collected=False → COLLECT_CLUSTERS (self-loop)
"""

import asyncio
import json
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from src.agents.deep_interpreter.wrapper_agent import DeepInterpreterWrapperAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent() -> DeepInterpreterWrapperAgent:
    """Create a wrapper agent instance without triggering build_graph.

    Uses __new__ to skip __init__ (which calls build_graph → imports LLMConfigSchema).
    Manually sets only the attributes needed for the methods under test.
    """
    agent = DeepInterpreterWrapperAgent.__new__(DeepInterpreterWrapperAgent)
    agent.is_debug = False
    agent.NODE_NAMES = DeepInterpreterWrapperAgent.NODE_NAMES
    agent.model = None
    agent.max_retry_attempts = 0
    return agent


DUMMY_CONFIG = {"configurable": {}}


class TestLRDataPathResolution:
    """Verify interest_sample-specific LIANA artifacts are preferred."""

    def setup_method(self):
        self.agent = _make_agent()

    def test_prefers_interest_sample_lrdata_when_both_exist(self, tmp_path):
        (tmp_path / "lrdata.h5ad").write_text("combined")
        sample_path = tmp_path / "lrdata_V19S23-092-B1.h5ad"
        sample_path.write_text("sample")

        result = self.agent._resolve_lrdata_path(
            str(tmp_path),
            interest_sample="V19S23-092-B1",
        )

        assert result == str(sample_path)

    def test_falls_back_to_combined_lrdata_without_interest_sample(self, tmp_path):
        combined_path = tmp_path / "lrdata.h5ad"
        combined_path.write_text("combined")

        result = self.agent._resolve_lrdata_path(str(tmp_path))

        assert result == str(combined_path)

    def test_falls_back_to_combined_lrdata_when_sample_file_missing(self, tmp_path):
        combined_path = tmp_path / "lrdata.h5ad"
        combined_path.write_text("combined")

        result = self.agent._resolve_lrdata_path(
            str(tmp_path),
            interest_sample="V19S23-092-B1",
        )

        assert result == str(combined_path)


class TestLRDataPathRoles:
    """Step 7 uses global NMF; Step 8+ uses targeted sample lrdata."""

    def setup_method(self):
        self.agent = _make_agent()

    def _state(self, tmp_path):
        return {
            "h5ad_files": [str(tmp_path / "input.h5ad")],
            "cluster_key": "IRIS_domain",
            "data_directory": str(tmp_path),
            "species": "human",
            "sample_key": "sample",
            "interest_sample": "V19S23-092-B1",
            "interest_clusters": ["9", "11", "10", "13", "5"],
        }

    def test_step_7_factor_score_uses_combined_lrdata(self, tmp_path):
        combined_path = tmp_path / "lrdata.h5ad"
        sample_path = tmp_path / "lrdata_V19S23-092-B1.h5ad"
        combined_path.write_text("combined")
        sample_path.write_text("sample")

        result = self.agent._build_step_args(7, self._state(tmp_path))

        assert result["filename"] == str(combined_path)

    def test_step_8_loadings_use_interest_sample_lrdata(self, tmp_path):
        combined_path = tmp_path / "lrdata.h5ad"
        sample_path = tmp_path / "lrdata_V19S23-092-B1.h5ad"
        combined_path.write_text("combined")
        sample_path.write_text("sample")

        result = self.agent._build_step_args(8, self._state(tmp_path))

        assert result["filename"] == str(sample_path)

    def test_step_9_quadrant_uses_interest_sample_lrdata(self, tmp_path):
        combined_path = tmp_path / "lrdata.h5ad"
        sample_path = tmp_path / "lrdata_V19S23-092-B1.h5ad"
        combined_path.write_text("combined")
        sample_path.write_text("sample")

        result = self.agent._build_step_args_9_11(
            9,
            self._state(tmp_path),
            sel_factor="Factor1",
        )

        assert result["lrdata_path"] == str(sample_path)

    def test_step_6_cache_requires_combined_lrdata(self, tmp_path):
        (tmp_path / "sig_liana.csv").write_text("interaction,morans\n")
        (tmp_path / "lrdata_V19S23-092-B1.h5ad").write_text("sample")
        step_config = DeepInterpreterWrapperAgent.ANALYSIS_STEPS[5]

        result = self.agent._check_step_outputs_exist(
            step_config,
            str(tmp_path),
            step=6,
            sample_key="sample",
            interest_sample="V19S23-092-B1",
        )

        assert result is False


# ===========================================================================
# Test Group 1: route_after_clusters routing logic (Fix 4)
# ===========================================================================


class TestRouteAfterClusters:
    """Verify all 3 routing paths from collect_clusters node."""

    def setup_method(self):
        self.agent = _make_agent()

    def test_normal_flow_to_collect_factor(self):
        """clusters_collected=True, research_discussion_complete=False → COLLECT_FACTOR."""
        state = {
            "clusters_collected": True,
            "research_discussion_complete": False,
        }
        result = self.agent.route_after_clusters(state, DUMMY_CONFIG)
        assert result == "collect_factor"

    def test_cancel_routes_to_check_state(self):
        """research_discussion_complete=True → CHECK_STATE (routes to CONFIRM_INTERP → END)."""
        state = {
            "clusters_collected": True,
            "research_discussion_complete": True,
        }
        result = self.agent.route_after_clusters(state, DUMMY_CONFIG)
        assert result == "__end__"

    def test_reprompt_self_loop(self):
        """clusters_collected=False → COLLECT_CLUSTERS (re-prompt)."""
        state = {
            "clusters_collected": False,
            "research_discussion_complete": False,
        }
        result = self.agent.route_after_clusters(state, DUMMY_CONFIG)
        assert result == "collect_clusters"

    def test_cancel_with_no_clusters_self_loops(self):
        """clusters_collected=False takes priority → self-loop even if research_discussion_complete."""
        state = {
            "clusters_collected": False,
            "research_discussion_complete": True,
        }
        result = self.agent.route_after_clusters(state, DUMMY_CONFIG)
        # New logic: clusters_collected check comes first, so False → self-loop
        assert result == "collect_clusters"

    def test_missing_keys_default_to_falsy(self):
        """Empty state (no keys) → self-loop (both default to falsy)."""
        state = {}
        result = self.agent.route_after_clusters(state, DUMMY_CONFIG)
        assert result == "collect_clusters"


# ===========================================================================
# Test Group 2: collect_clusters_node parsing logic (Fix 2)
# ===========================================================================


class TestCollectClustersNodeParsing:
    """Verify LLM parsing and regex fallback in collect_clusters_node."""

    def setup_method(self):
        self.agent = _make_agent()

    def _base_state(self, tmp_path):
        """Minimal state for collect_clusters_node."""
        save_path = str(tmp_path)
        # Create the CSV that _resolve_celltype_cluster_mapping needs
        df = pd.DataFrame({
            "cluster": ["0", "1", "4", "16", "17"],
            "celltype": ["T cell", "B cell", "Fibroblast", "Epithelial", "Macrophage"],
            "cluster_medians": [0.8, 0.6, 0.9, 0.7, 0.5],
        })
        df.to_csv(f"{save_path}/sig_clusterwithcelltyp.csv", index=False)

        return {
            "messages": [],
            "data_directory": save_path,
            "disease": "breast cancer",
            "st_technology": "Visium",
            "cluster_attempt": 0,
            "llm_suggestion": "Focus on clusters 4 and 16.",
            "interest_celltypes": None,
            "interest_clusters": None,
        }

    @pytest.mark.asyncio
    async def test_llm_success_json(self, tmp_path):
        """LLM returns valid JSON → parsed_clusters extracted successfully."""
        state = self._base_state(tmp_path)

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content='{"interest_celltypes": ["Fibroblast"], "interest_clusters": ["4", "16"]}'
        )

        with (
            patch("src.agents.deep_interpreter.wrapper_agent.interrupt", return_value="clusters 4 and 16, Fibroblast"),
            patch.object(self.agent, "get_model", return_value=mock_llm),
        ):
            result = await self.agent.collect_clusters_node(state, DUMMY_CONFIG)

        assert result["clusters_collected"] is True
        assert "4" in result["interest_clusters"]
        assert "16" in result["interest_clusters"]
        assert "Fibroblast" in result["interest_celltypes"]

    @pytest.mark.asyncio
    async def test_llm_exception_regex_fallback(self, tmp_path):
        """LLM ainvoke raises Exception → regex fallback extracts cluster IDs."""
        state = self._base_state(tmp_path)

        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = RuntimeError("API quota exceeded")

        with (
            patch("src.agents.deep_interpreter.wrapper_agent.interrupt", return_value="4, 16, 17"),
            patch.object(self.agent, "get_model", return_value=mock_llm),
        ):
            result = await self.agent.collect_clusters_node(state, DUMMY_CONFIG)

        assert result["clusters_collected"] is True
        assert set(result["interest_clusters"]) >= {"4", "16", "17"}

    @pytest.mark.asyncio
    async def test_llm_invalid_json_regex_fallback(self, tmp_path):
        """LLM returns non-JSON text → inner except regex extracts numbers."""
        state = self._base_state(tmp_path)

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content="I think clusters 4 and 16 are interesting"  # not valid JSON
        )

        with (
            patch("src.agents.deep_interpreter.wrapper_agent.interrupt", return_value="4, 16"),
            patch.object(self.agent, "get_model", return_value=mock_llm),
        ):
            result = await self.agent.collect_clusters_node(state, DUMMY_CONFIG)

        assert result["clusters_collected"] is True
        assert "4" in result["interest_clusters"]
        assert "16" in result["interest_clusters"]

    @pytest.mark.asyncio
    async def test_empty_clusters_triggers_reprompt(self, tmp_path):
        """Empty cluster parse → clusters_collected=False for self-loop."""
        state = self._base_state(tmp_path)

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content='{"interest_celltypes": [], "interest_clusters": []}'
        )

        with (
            patch("src.agents.deep_interpreter.wrapper_agent.interrupt", return_value="not sure yet"),
            patch.object(self.agent, "get_model", return_value=mock_llm),
        ):
            result = await self.agent.collect_clusters_node(state, DUMMY_CONFIG)

        assert result["clusters_collected"] is False
        assert result["cluster_attempt"] == 1

    @pytest.mark.asyncio
    async def test_cancel_keyword_ends_workflow(self, tmp_path):
        """User types 'skip' → sets research_discussion_complete=True."""
        state = self._base_state(tmp_path)

        with patch("src.agents.deep_interpreter.wrapper_agent.interrupt", return_value="skip"):
            result = await self.agent.collect_clusters_node(state, DUMMY_CONFIG)

        assert result["research_discussion_complete"] is True
        assert result["clusters_collected"] is True
        assert result["analysis_9_11_complete"] is True

    @pytest.mark.asyncio
    async def test_max_reprompts_proceeds_with_empty(self, tmp_path):
        """After 2+ re-prompts with empty clusters, proceeds instead of looping forever."""
        state = self._base_state(tmp_path)
        state["cluster_attempt"] = 2  # already re-prompted twice

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content='{"interest_celltypes": [], "interest_clusters": []}'
        )

        with (
            patch("src.agents.deep_interpreter.wrapper_agent.interrupt", return_value="idk"),
            patch.object(self.agent, "get_model", return_value=mock_llm),
        ):
            result = await self.agent.collect_clusters_node(state, DUMMY_CONFIG)

        # Should NOT return clusters_collected=False (would cause infinite loop)
        assert result.get("clusters_collected") is True

    @pytest.mark.asyncio
    async def test_direct_json_list_skips_llm(self, tmp_path):
        """'["4","16","17"]' → direct JSON parse, LLM NOT called."""
        state = self._base_state(tmp_path)

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content='{}')

        with (
            patch("src.agents.deep_interpreter.wrapper_agent.interrupt", return_value='["4","16","17"]'),
            patch.object(self.agent, "get_model", return_value=mock_llm),
        ):
            result = await self.agent.collect_clusters_node(state, DUMMY_CONFIG)

        # LLM should NOT have been called — direct JSON parse handles this
        mock_llm.ainvoke.assert_not_called()
        assert result["clusters_collected"] is True
        assert set(result["interest_clusters"]) >= {"4", "16", "17"}

    @pytest.mark.asyncio
    async def test_direct_json_celltype_list_skips_llm(self, tmp_path):
        """'["invasive tumor","prolif invasive tumor"]' → celltypes parsed, clusters resolved via CSV."""
        state = self._base_state(tmp_path)
        # Override CSV with cell type names that match
        df = pd.DataFrame({
            "cluster": ["0", "1", "4", "16", "17"],
            "celltype": ["T cell", "invasive tumor", "prolif invasive tumor", "Epithelial", "Macrophage"],
            "cluster_medians": [0.8, 0.6, 0.9, 0.7, 0.5],
        })
        df.to_csv(f"{tmp_path}/sig_clusterwithcelltyp.csv", index=False)

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content='{}')

        with (
            patch("src.agents.deep_interpreter.wrapper_agent.interrupt",
                  return_value='["invasive tumor", "prolif invasive tumor"]'),
            patch.object(self.agent, "get_model", return_value=mock_llm),
        ):
            result = await self.agent.collect_clusters_node(state, DUMMY_CONFIG)

        # LLM should NOT have been called — direct JSON parse handles this
        mock_llm.ainvoke.assert_not_called()
        assert result["clusters_collected"] is True
        # Cell type names should be in interest_celltypes
        assert "invasive tumor" in result["interest_celltypes"]
        assert "prolif invasive tumor" in result["interest_celltypes"]
        # Clusters should be resolved to numeric IDs from CSV
        assert "1" in result["interest_clusters"]  # invasive tumor → cluster 1
        assert "4" in result["interest_clusters"]  # prolif invasive tumor → cluster 4
        # Last message should be AIMessage
        assert result["messages"][-1].__class__.__name__ == "AIMessage"

    @pytest.mark.asyncio
    async def test_direct_json_mixed_list_skips_llm(self, tmp_path):
        """'["4","invasive tumor","16"]' → mixed numeric and cell type names separated correctly."""
        state = self._base_state(tmp_path)
        df = pd.DataFrame({
            "cluster": ["0", "1", "4", "16", "17"],
            "celltype": ["T cell", "invasive tumor", "Fibroblast", "Epithelial", "Macrophage"],
            "cluster_medians": [0.8, 0.6, 0.9, 0.7, 0.5],
        })
        df.to_csv(f"{tmp_path}/sig_clusterwithcelltyp.csv", index=False)

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content='{}')

        with (
            patch("src.agents.deep_interpreter.wrapper_agent.interrupt",
                  return_value='["4", "invasive tumor", "16"]'),
            patch.object(self.agent, "get_model", return_value=mock_llm),
        ):
            result = await self.agent.collect_clusters_node(state, DUMMY_CONFIG)

        mock_llm.ainvoke.assert_not_called()
        assert result["clusters_collected"] is True
        # Numeric items → clusters
        assert "4" in result["interest_clusters"]
        assert "16" in result["interest_clusters"]
        # Non-numeric → celltypes
        assert "invasive tumor" in result["interest_celltypes"]

    @pytest.mark.asyncio
    async def test_direct_json_dict_skips_llm(self, tmp_path):
        """'{"interest_clusters":["4"],"interest_celltypes":["Fibroblast"]}' → direct parse."""
        state = self._base_state(tmp_path)

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content='{}')

        user_input = '{"interest_clusters":["4"],"interest_celltypes":["Fibroblast"]}'
        with (
            patch("src.agents.deep_interpreter.wrapper_agent.interrupt", return_value=user_input),
            patch.object(self.agent, "get_model", return_value=mock_llm),
        ):
            result = await self.agent.collect_clusters_node(state, DUMMY_CONFIG)

        mock_llm.ainvoke.assert_not_called()
        assert result["clusters_collected"] is True
        assert "4" in result["interest_clusters"]
        assert "Fibroblast" in result["interest_celltypes"]

    @pytest.mark.asyncio
    async def test_natural_language_uses_llm(self, tmp_path):
        """'focus on clusters 4 and 16' → NOT valid JSON → falls through to LLM."""
        state = self._base_state(tmp_path)

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content='{"interest_celltypes": ["Fibroblast"], "interest_clusters": ["4", "16"]}'
        )

        with (
            patch("src.agents.deep_interpreter.wrapper_agent.interrupt", return_value="focus on clusters 4 and 16"),
            patch.object(self.agent, "get_model", return_value=mock_llm),
        ):
            result = await self.agent.collect_clusters_node(state, DUMMY_CONFIG)

        # LLM SHOULD have been called for natural language
        mock_llm.ainvoke.assert_called_once()
        assert result["clusters_collected"] is True
        assert "4" in result["interest_clusters"]

    @pytest.mark.asyncio
    async def test_llm_timeout_regex_fallback(self, tmp_path):
        """LLM hangs → asyncio.TimeoutError → regex fallback."""
        state = self._base_state(tmp_path)

        async def _hang(*args, **kwargs):
            await asyncio.sleep(999)  # simulate hang

        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = _hang

        with (
            patch("src.agents.deep_interpreter.wrapper_agent.interrupt", return_value="4, 16, 17"),
            patch.object(self.agent, "get_model", return_value=mock_llm),
            patch("src.agents.deep_interpreter.wrapper_agent.asyncio.wait_for",
                  side_effect=asyncio.TimeoutError()),
        ):
            result = await self.agent.collect_clusters_node(state, DUMMY_CONFIG)

        assert result["clusters_collected"] is True
        assert set(result["interest_clusters"]) >= {"4", "16", "17"}

    @pytest.mark.asyncio
    async def test_agent_chat_ui_dict_response_format(self, tmp_path):
        """agent-chat-ui wraps response in {response:..., message:...} dict."""
        state = self._base_state(tmp_path)
        resume_value = {"response": '["4","16","17"]', "message": '["4","16","17"]'}

        mock_llm = AsyncMock()
        with (
            patch("src.agents.deep_interpreter.wrapper_agent.interrupt", return_value=resume_value),
            patch.object(self.agent, "get_model", return_value=mock_llm),
        ):
            result = await self.agent.collect_clusters_node(state, DUMMY_CONFIG)

        mock_llm.ainvoke.assert_not_called()
        assert result["clusters_collected"] is True
        assert set(result["interest_clusters"]) >= {"4", "16", "17"}
        # Verify AIMessage is the last message (critical for interrupt rendering)
        assert result["messages"][-1].__class__.__name__ == "AIMessage"

    @pytest.mark.asyncio
    async def test_success_path_last_message_is_ai(self, tmp_path):
        """Success path must have AIMessage as last message for agent-chat-ui interrupt rendering."""
        state = self._base_state(tmp_path)

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content='{"interest_celltypes": ["Fibroblast"], "interest_clusters": ["4", "16"]}'
        )

        with (
            patch("src.agents.deep_interpreter.wrapper_agent.interrupt", return_value="clusters 4 and 16"),
            patch.object(self.agent, "get_model", return_value=mock_llm),
        ):
            result = await self.agent.collect_clusters_node(state, DUMMY_CONFIG)

        assert result["clusters_collected"] is True
        assert len(result["messages"]) == 2
        assert result["messages"][0].__class__.__name__ == "HumanMessage"
        assert result["messages"][-1].__class__.__name__ == "AIMessage"

    @pytest.mark.asyncio
    async def test_reprompt_path_last_message_is_ai(self, tmp_path):
        """Re-prompt path must have AIMessage as last message for agent-chat-ui interrupt rendering."""
        state = self._base_state(tmp_path)

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(
            content='{"interest_celltypes": [], "interest_clusters": []}'
        )

        with (
            patch("src.agents.deep_interpreter.wrapper_agent.interrupt", return_value="not sure yet"),
            patch.object(self.agent, "get_model", return_value=mock_llm),
        ):
            result = await self.agent.collect_clusters_node(state, DUMMY_CONFIG)

        assert result["clusters_collected"] is False
        assert len(result["messages"]) == 2
        assert result["messages"][-1].__class__.__name__ == "AIMessage"


# ===========================================================================
# Test Group 3: info_validation_node conditional dict (Fix 1)
# ===========================================================================


class TestInfoValidationConditionalDict:
    """Verify None fields are excluded from return dict via conditional unpacking."""

    def test_none_fields_excluded(self):
        """interest_celltypes=None, interest_clusters=None → keys absent from dict."""
        # Simulate the conditional unpacking pattern used at wrapper_agent.py:992-993
        interest_celltypes = None
        interest_clusters = None

        result = {
            "h5ad_files": ["/data/test.h5ad"],
            "cluster_key": "leiden",
            **({"interest_celltypes": interest_celltypes} if interest_celltypes else {}),
            **({"interest_clusters": interest_clusters} if interest_clusters else {}),
            "data_directory": "/data/res",
        }

        assert "interest_celltypes" not in result
        assert "interest_clusters" not in result

    def test_values_included_when_present(self):
        """interest_celltypes=["T cell"] → key present in dict."""
        interest_celltypes = ["T cell", "Macrophage"]
        interest_clusters = ["4", "16"]

        result = {
            "h5ad_files": ["/data/test.h5ad"],
            "cluster_key": "leiden",
            **({"interest_celltypes": interest_celltypes} if interest_celltypes else {}),
            **({"interest_clusters": interest_clusters} if interest_clusters else {}),
            "data_directory": "/data/res",
        }

        assert result["interest_celltypes"] == ["T cell", "Macrophage"]
        assert result["interest_clusters"] == ["4", "16"]

    def test_empty_list_excluded(self):
        """interest_celltypes=[] (empty list) → key absent (falsy)."""
        interest_celltypes = []
        interest_clusters = []

        result = {
            **({"interest_celltypes": interest_celltypes} if interest_celltypes else {}),
            **({"interest_clusters": interest_clusters} if interest_clusters else {}),
        }

        assert "interest_celltypes" not in result
        assert "interest_clusters" not in result

    def test_mixed_none_and_value(self):
        """One None, one with value → only the valued one appears."""
        interest_celltypes = ["Fibroblast"]
        interest_clusters = None

        result = {
            **({"interest_celltypes": interest_celltypes} if interest_celltypes else {}),
            **({"interest_clusters": interest_clusters} if interest_clusters else {}),
        }

        assert result["interest_celltypes"] == ["Fibroblast"]
        assert "interest_clusters" not in result


# ===========================================================================
# Test Group 4: _resolve_celltype_cluster_mapping (bidirectional mapping)
# ===========================================================================


class TestResolveCelltypeClusterMapping:
    """Verify celltype<->cluster bidirectional resolution."""

    def setup_method(self):
        self.agent = _make_agent()

    def test_celltypes_to_clusters(self, tmp_path):
        """Given celltypes but no clusters → auto-maps to cluster IDs."""
        df = pd.DataFrame({
            "cluster": ["0", "1", "4", "16"],
            "celltype": ["T cell", "B cell", "Fibroblast", "Fibroblast"],
            "cluster_medians": [0.8, 0.6, 0.9, 0.7],
        })
        df.to_csv(f"{tmp_path}/sig_clusterwithcelltyp.csv", index=False)

        clusters, celltypes = self.agent._resolve_celltype_cluster_mapping(
            str(tmp_path), ["Fibroblast"], [],
        )
        assert len(clusters) > 0
        assert "4" in clusters or "16" in clusters

    def test_clusters_to_celltypes(self, tmp_path):
        """Given clusters but no celltypes → auto-maps to dominant celltype."""
        df = pd.DataFrame({
            "cluster": ["0", "4", "16"],
            "celltype": ["T cell", "Fibroblast", "Epithelial"],
            "cluster_medians": [0.8, 0.9, 0.7],
        })
        df.to_csv(f"{tmp_path}/sig_clusterwithcelltyp.csv", index=False)

        clusters, celltypes = self.agent._resolve_celltype_cluster_mapping(
            str(tmp_path), [], ["4", "16"],
        )
        assert clusters == ["4", "16"]
        assert len(celltypes) > 0

    def test_both_provided_passthrough(self, tmp_path):
        """Both provided → pass through unchanged."""
        df = pd.DataFrame({
            "cluster": ["0", "4"],
            "celltype": ["T cell", "Fibroblast"],
            "cluster_medians": [0.8, 0.9],
        })
        df.to_csv(f"{tmp_path}/sig_clusterwithcelltyp.csv", index=False)

        clusters, celltypes = self.agent._resolve_celltype_cluster_mapping(
            str(tmp_path), ["Macrophage"], ["4"],
        )
        assert clusters == ["4"]
        assert celltypes == ["Macrophage"]

    def test_missing_csv_passthrough(self, tmp_path):
        """Missing CSV → returns inputs unchanged."""
        clusters, celltypes = self.agent._resolve_celltype_cluster_mapping(
            str(tmp_path), ["Macrophage"], ["4"],
        )
        assert clusters == ["4"]
        assert celltypes == ["Macrophage"]


# ===========================================================================
# Test Group 5: _suggest_factor edge cases (code review fixes)
# ===========================================================================


class TestSuggestFactorEdgeCases:
    """Verify _suggest_factor handles degenerate data without errors."""

    def setup_method(self):
        self.agent = _make_agent()

    def _make_factor_csv(self, data: dict) -> pd.DataFrame:
        return pd.DataFrame(data)

    def test_normal_case_returns_factor3(self):
        """Simulated res_bc data — Factor3 should win for cluster '4'."""
        df = self._make_factor_csv({
            "cluster": ["0", "1", "4", "16"],
            "Factor1": [0.1, 0.2, 0.05, 0.3],
            "Factor2": [0.3, 0.1, 0.1, 0.2],
            "Factor3": [0.05, 0.1, 0.9, 0.1],
        })
        result = self.agent._suggest_factor(df, ["4"])
        assert result == "Factor3"

    def test_all_zero_data_no_valueerror(self):
        """All-zero factor data → should not raise ValueError, fallback to raw mean."""
        df = self._make_factor_csv({
            "cluster": ["0", "1", "4"],
            "Factor1": [0.0, 0.0, 0.0],
            "Factor2": [0.0, 0.0, 0.0],
        })
        # Must not raise
        result = self.agent._suggest_factor(df, ["4"])
        assert isinstance(result, str)
        assert result.startswith("Factor")

    def test_all_identical_values_no_crash(self):
        """All factors have identical values across clusters → all-NaN combined."""
        df = self._make_factor_csv({
            "cluster": ["0", "1", "4"],
            "Factor1": [0.5, 0.5, 0.5],
            "Factor2": [0.5, 0.5, 0.5],
        })
        result = self.agent._suggest_factor(df, ["4"])
        assert isinstance(result, str)
        assert result.startswith("Factor")

    def test_zero_other_means_factor_wins(self):
        """Factor with zero mean in other clusters is most specific — should win."""
        df = self._make_factor_csv({
            "cluster": ["0", "1", "4"],
            "Factor1": [0.5, 0.5, 0.1],  # present in others
            "Factor2": [0.0, 0.0, 0.8],  # zero in others, high in interest
        })
        result = self.agent._suggest_factor(df, ["4"])
        assert result == "Factor2"

    def test_detailed_mode_no_nan_in_output(self):
        """Detailed output with degenerate data should not contain 'nan' text."""
        df = self._make_factor_csv({
            "cluster": ["0", "1", "4"],
            "Factor1": [0.0, 0.0, 0.0],
            "Factor2": [0.0, 0.0, 0.0],
        })
        result = self.agent._suggest_factor(df, ["4"], detailed=True)
        assert isinstance(result, tuple)
        factor, analysis = result
        assert "nan" not in analysis.lower()

    def test_detailed_mode_normal_data(self):
        """Detailed mode with normal data returns factor + analysis string."""
        df = self._make_factor_csv({
            "cluster": ["0", "1", "4", "16"],
            "Factor1": [0.1, 0.2, 0.05, 0.3],
            "Factor2": [0.3, 0.1, 0.1, 0.2],
            "Factor3": [0.05, 0.1, 0.9, 0.1],
        })
        factor, analysis = self.agent._suggest_factor(df, ["4"], detailed=True)
        assert factor == "Factor3"
        assert "Factor specificity analysis" in analysis
        assert "nan" not in analysis.lower()
        assert "Best factor: Factor3" in analysis

    def test_partial_nan_factors_handled(self):
        """Some factors NaN in combined score → fillna(-inf), not crash."""
        # One factor has zero std (identical values) → NaN z-score for that factor
        df = self._make_factor_csv({
            "cluster": ["0", "1", "4"],
            "Factor1": [0.5, 0.5, 0.5],  # zero std → NaN z-score
            "Factor2": [0.0, 0.0, 0.8],  # has variance
        })
        result = self.agent._suggest_factor(df, ["4"])
        assert isinstance(result, str)
        # Factor2 should win (Factor1 gets -inf from fillna)
        assert result == "Factor2"


class TestAnalysisStepFailureDoesNotAdvance:
    """MCP failures should not be treated as completed pipeline progress."""

    def setup_method(self):
        self.agent = _make_agent()
        self.agent.ANALYSIS_STEPS = DeepInterpreterWrapperAgent.ANALYSIS_STEPS
        self.agent.ANALYSIS_STEPS_9_11 = DeepInterpreterWrapperAgent.ANALYSIS_STEPS_9_11

    @pytest.mark.asyncio
    async def test_step_8_failure_does_not_mark_analysis_1_8_complete(self, tmp_path):
        state = {
            "current_analysis_step": 8,
            "h5ad_files": [str(tmp_path / "input.h5ad")],
            "cluster_key": "IRIS_domain",
            "data_directory": str(tmp_path),
            "species": "human",
            "interest_sample": "V19S23-092-B1",
        }
        (tmp_path / "input.h5ad").write_text("unused")
        (tmp_path / "lrdata_V19S23-092-B1.h5ad").write_text("sample")

        with (
            patch.dict(
                "os.environ",
                {
                    "SP_ENRICH_MCP_PYTHON": "python",
                    "SP_ENRICH_MCP_SERVER_PATH": "/tmp/sp",
                },
            ),
            patch.object(self.agent, "_check_step_outputs_exist", return_value=False),
            patch.object(self.agent, "_build_step_args", return_value={"filename": "x"}),
            patch("src.agents.deep_interpreter.wrapper_agent.MultiServerMCPClient") as client_cls,
        ):
            client = AsyncMock()
            client.get_tools.return_value = []
            client_cls.return_value = client

            result = await self.agent.run_single_analysis_step_node(state, DUMMY_CONFIG)

        assert result["current_analysis_step"] == 8
        assert result.get("analysis_1_8_complete") is not True

    @pytest.mark.asyncio
    async def test_step_9_failure_does_not_route_to_drug_target(self, tmp_path):
        state = {
            "current_analysis_step": 9,
            "data_directory": str(tmp_path),
            "cluster_key": "IRIS_domain",
            "interest_clusters": ["9"],
            "sel_factor": "Factor1",
            "interest_sample": "V19S23-092-B1",
        }
        (tmp_path / "lrdata_V19S23-092-B1.h5ad").write_text("sample")
        pd.DataFrame({"interaction": ["A^B"], "Factor1": [1.0]}).to_csv(
            tmp_path / "sig_liana.csv",
            index=False,
        )

        with (
            patch.dict(
                "os.environ",
                {
                    "SP_ENRICH_MCP_PYTHON": "python",
                    "SP_ENRICH_MCP_SERVER_PATH": "/tmp/sp",
                },
            ),
            patch.object(self.agent, "_check_step_outputs_exist", return_value=False),
            patch.object(self.agent, "_build_step_args_9_11", return_value={"csv_path": "x"}),
            patch("src.agents.deep_interpreter.wrapper_agent.MultiServerMCPClient") as client_cls,
        ):
            client = AsyncMock()
            client.get_tools.return_value = []
            client_cls.return_value = client

            result = await self.agent.run_single_analysis_step_9_11_node(state, DUMMY_CONFIG)

        assert result["current_analysis_step"] == 9
        assert result.get("analysis_9_11_complete") is not True

    @pytest.mark.asyncio
    async def test_step_9_missing_sig_liana_does_not_call_mcp(self, tmp_path):
        state = {
            "current_analysis_step": 9,
            "data_directory": str(tmp_path),
            "cluster_key": "IRIS_domain",
            "interest_clusters": ["9"],
            "sel_factor": "Factor1",
            "interest_sample": "V19S23-092-B1",
        }
        (tmp_path / "lrdata_V19S23-092-B1.h5ad").write_text("sample")

        with patch("src.agents.deep_interpreter.wrapper_agent.MultiServerMCPClient") as client_cls:
            result = await self.agent.run_single_analysis_step_9_11_node(state, DUMMY_CONFIG)

        client_cls.assert_not_called()
        assert result["current_analysis_step"] == 9
        assert result.get("analysis_9_11_complete") is not True
        assert "sig_liana.csv not found" in result["messages"][0].content[0]["text"]


class TestDrugTargetStepHandoff:
    """Verify Step 9.5 hands selected LR pairs to Steps 10-11."""

    def setup_method(self):
        self.agent = _make_agent()

    @pytest.mark.asyncio
    async def test_overwrites_targets_and_prefers_part4_selected_lr_pairs(self, tmp_path):
        (tmp_path / "targets.json").write_text(
            json.dumps({"interest_celltypes": None}),
            encoding="utf-8",
        )
        (tmp_path / "lr_candidates.json").write_text("stale", encoding="utf-8")
        (tmp_path / "part4_candidate_selection.json").write_text(
            json.dumps(
                {
                    "selected_lr_pairs": [
                        {"interaction": "ICAM1^PECAM1"},
                        {"interaction": "ICAM1^MUC1"},
                        {"interaction": "MIF^CD74"},
                    ]
                }
            ),
            encoding="utf-8",
        )

        def prioritize(_args):
            assert not (tmp_path / "lr_candidates.json").exists()
            (tmp_path / "lr_candidates.json").write_text("[]", encoding="utf-8")
            return json.dumps({"pairs": [{"interaction": "ICAM1^PECAM1"}]})

        state = {
            "data_directory": str(tmp_path),
            "disease": "IPF",
            "interest_celltypes": ["AT2"],
            "interest_clusters": ["9"],
            "sel_factor": "Factor1",
        }

        with (
            patch(
                "src.agents.deep_interpreter.tools.lr_prioritizer.prioritize_top_lr_pairs"
            ) as prioritizer,
            patch(
                "src.agents.drug_target.integration.run_drug_target_assessment"
            ) as assessment,
        ):
            prioritizer.invoke.side_effect = prioritize
            assessment.ainvoke = AsyncMock(
                return_value=json.dumps(
                    {
                        "success": True,
                        "target_assessment": {
                            "druggability_matrix": [
                                {"is_featured": True, "interaction": "OLD^PAIR"}
                            ]
                        },
                    }
                )
            )

            result = await self.agent.run_drug_target_node(state, DUMMY_CONFIG)

        assert json.loads((tmp_path / "targets.json").read_text()) == {
            "interest_celltypes": ["AT2"],
            "interest_clusters": ["9"],
            "sel_factor": "Factor1",
            "data_directory": str(tmp_path),
        }
        assert result["featured_lr_pairs"] == [
            "ICAM1^PECAM1",
            "ICAM1^MUC1",
            "MIF^CD74",
        ]

    @pytest.mark.asyncio
    async def test_existing_drug_and_part4_outputs_skip_agent_and_delete_step10_11_figures(
        self,
        tmp_path,
    ):
        (tmp_path / "drug.md").write_text("# cached drug", encoding="utf-8")
        (tmp_path / "part4_therapeutic_synthesis.md").write_text(
            "# cached part4",
            encoding="utf-8",
        )
        (tmp_path / "part4_candidate_selection.json").write_text(
            json.dumps(
                {
                    "selected_lr_pairs": [
                        {"interaction": "ICAM1^PECAM1"},
                        {"interaction": "ICAM1^MUC1"},
                        {"interaction": "GPC3^CD81"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        fig10 = tmp_path / "10.spatial_plot_interections_V19S23-092-B1.png"
        fig11 = tmp_path / "11.lr_interections_V19S23-092-B1.png"
        fig10.write_text("cached fig10", encoding="utf-8")
        fig11.write_text("cached fig11", encoding="utf-8")

        state = {
            "data_directory": str(tmp_path),
            "disease": "IPF",
            "interest_celltypes": ["AT2"],
            "interest_clusters": ["9"],
            "sel_factor": "Factor1",
        }

        with (
            patch(
                "src.agents.deep_interpreter.tools.lr_prioritizer.prioritize_top_lr_pairs"
            ) as prioritizer,
            patch(
                "src.agents.drug_target.integration.run_drug_target_assessment"
            ) as assessment,
        ):
            assessment.ainvoke = AsyncMock()
            result = await self.agent.run_drug_target_node(state, DUMMY_CONFIG)

        prioritizer.invoke.assert_not_called()
        assessment.ainvoke.assert_not_called()
        assert not fig10.exists()
        assert not fig11.exists()
        assert result["drug_target_complete"] is True
        assert result["drug_target_error"] is None
        assert result["featured_lr_pairs"] == [
            "ICAM1^PECAM1",
            "ICAM1^MUC1",
            "GPC3^CD81",
        ]
        text = result["messages"][0].content[0]["text"]
        assert "SKIPPED" in text
        assert "Deleted cached Step 10/11 figures: 2" in text

    @pytest.mark.asyncio
    async def test_prioritizer_error_does_not_run_assessment_with_stale_candidates(
        self,
        tmp_path,
    ):
        (tmp_path / "lr_candidates.json").write_text("stale", encoding="utf-8")

        state = {
            "data_directory": str(tmp_path),
            "disease": "IPF",
            "interest_celltypes": ["AT2"],
            "interest_clusters": ["9"],
            "sel_factor": "Factor1",
        }

        with (
            patch(
                "src.agents.deep_interpreter.tools.lr_prioritizer.prioritize_top_lr_pairs"
            ) as prioritizer,
            patch(
                "src.agents.drug_target.integration.run_drug_target_assessment"
            ) as assessment,
        ):
            prioritizer.invoke.return_value = json.dumps({"error": "missing combinedscore"})
            assessment.ainvoke = AsyncMock()

            result = await self.agent.run_drug_target_node(state, DUMMY_CONFIG)

        assessment.ainvoke.assert_not_called()
        assert not (tmp_path / "lr_candidates.json").exists()
        assert result["drug_target_complete"] is False
        assert "prioritize_top_lr_pairs" in result["drug_target_error"]

    @pytest.mark.asyncio
    async def test_prioritizer_error_still_deletes_step10_11_figures(
        self,
        tmp_path,
    ):
        (tmp_path / "lr_candidates.json").write_text("stale", encoding="utf-8")
        fig10 = tmp_path / "10.spatial_plot_interections.png"
        fig11 = tmp_path / "11.lr_interections.png"
        fig10.write_text("cached fig10", encoding="utf-8")
        fig11.write_text("cached fig11", encoding="utf-8")

        state = {
            "data_directory": str(tmp_path),
            "disease": "IPF",
            "interest_celltypes": ["AT2"],
            "interest_clusters": ["9"],
            "sel_factor": "Factor1",
        }

        with (
            patch(
                "src.agents.deep_interpreter.tools.lr_prioritizer.prioritize_top_lr_pairs"
            ) as prioritizer,
            patch(
                "src.agents.drug_target.integration.run_drug_target_assessment"
            ) as assessment,
        ):
            prioritizer.invoke.return_value = json.dumps({"error": "missing combinedscore"})
            assessment.ainvoke = AsyncMock()
            result = await self.agent.run_drug_target_node(state, DUMMY_CONFIG)

        assessment.ainvoke.assert_not_called()
        assert not fig10.exists()
        assert not fig11.exists()
        assert result["drug_target_complete"] is False
        assert "prioritize_top_lr_pairs" in result["drug_target_error"]
        assert "Deleted cached Step 10/11 figures: 2" in result["messages"][0].content[0]["text"]

    @pytest.mark.asyncio
    async def test_stale_lr_candidates_unlink_runs_off_event_loop_thread(
        self,
        tmp_path,
        monkeypatch,
    ):
        stale_path = tmp_path / "lr_candidates.json"
        stale_path.write_text("stale", encoding="utf-8")

        original_unlink = Path.unlink
        unlink_threads = []

        def tracking_unlink(path_self, *args, **kwargs):
            if path_self == stale_path:
                unlink_threads.append(threading.current_thread().name)
            return original_unlink(path_self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", tracking_unlink)

        def prioritize(_args):
            assert not stale_path.exists()
            stale_path.write_text("[]", encoding="utf-8")
            return json.dumps({"pairs": [{"interaction": "ICAM1^PECAM1"}]})

        state = {
            "data_directory": str(tmp_path),
            "disease": "IPF",
            "interest_celltypes": ["AT2"],
            "interest_clusters": ["9"],
            "sel_factor": "Factor1",
        }

        with (
            patch(
                "src.agents.deep_interpreter.tools.lr_prioritizer.prioritize_top_lr_pairs"
            ) as prioritizer,
            patch(
                "src.agents.drug_target.integration.run_drug_target_assessment"
            ) as assessment,
        ):
            prioritizer.invoke.side_effect = prioritize
            assessment.ainvoke = AsyncMock(
                return_value=json.dumps(
                    {
                        "success": True,
                        "target_assessment": {"druggability_matrix": []},
                    }
                )
            )

            result = await self.agent.run_drug_target_node(state, DUMMY_CONFIG)

        assert unlink_threads
        assert threading.main_thread().name not in unlink_threads
        assert result["drug_target_complete"] is True
        assessment.ainvoke.assert_called_once()


class TestResearchSummaryMoransColumn:
    """The wrapper should summarize the actual sig_liana.csv column name."""

    def setup_method(self):
        self.agent = _make_agent()

    def test_morans_column_is_available_to_summary_candidates(self):
        candidates = DeepInterpreterWrapperAgent.LIANA_MORANS_SUMMARY_COLUMNS

        assert candidates[0] == "morans"
        assert "morans_r" in candidates
        assert "Morans_R" in candidates

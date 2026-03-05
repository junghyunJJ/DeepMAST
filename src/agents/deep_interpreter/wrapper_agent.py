"""Deep Interpreter Wrapper Agent - Full spatial analysis pipeline with MCP.

This module implements a wrapper agent that manages the complete spatial
analysis pipeline before invoking the Deep Agent for interpretation.

Architecture (10-node graph):
1.  check_state: Route to next incomplete phase
2.  info_collection: Collect h5ad files, keys, directories from user
3.  info_validation: Validate collected information
4.  run_single_analysis_step: Execute spatial analysis Steps 1-8 via MCP (one step per loop iteration)
5a. prepare_research_summary: CSV reads + LLM suggestion (no interrupt, runs ONCE)
5b. collect_clusters: 1x interrupt() for cluster/celltype selection (re-prompts if empty)
5c. collect_factor: 1x interrupt() for NMF factor selection
6.  run_single_analysis_step_9_11: Execute targeted analysis Steps 9-11 via MCP (one step per loop iteration)
7.  confirm_interpretation: HITL confirmation before expensive Deep Agent invocation
8.  invoke_deep_agent: Invoke Deep Agent for interpretation/report generation

Each interrupt() is in its own node to prevent re-execution of expensive
CSV reads and LLM calls on resume.

MCP Server: sp-enrich-mcp (FastMCP, stdio transport)
Pattern Reference: STPipelineBuilderAgent (st_pipeline_info_agent.py)
"""

import asyncio
import base64
import json
import logging
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, ClassVar, Literal

import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from src.base import BaseAgent
from src.base.util import CANCEL_KEYWORDS
from src.agents.deep_interpreter.info_extraction import DeepInterpreterInfoExtraction
from src.agents.deep_interpreter.wrapper_state import DeepInterpreterWrapperState

logger = logging.getLogger(__name__)


class DeepInterpreterWrapperAgent(BaseAgent):
    """Wrapper agent for Deep Interpreter with full spatial analysis pipeline.

    Graph Flow (10 nodes):
        START → check_state
          ├─(need_info)──→ info_collection ←─┐
          │                     ↓              │
          │               info_validation ─────┘
          │                     ↓ (complete)
          ├─(info_complete)───→ run_single_analysis_step ←──┐
          │                          ↓ (loop)               │
          │                     route_after_step ────────────┘
          │                          ↓ (done)
          ├─(analysis done)──→ prepare_research_summary (no interrupt, runs ONCE)
          │                          ↓
          │                    collect_clusters (1x interrupt, re-prompts if empty)
          │                          ↓
          │                    collect_factor (1x interrupt)
          │                          ↓
          ├─(research done)──→ run_single_analysis_step_9_11 ←──┐
          │                          ↓ (loop)                    │
          │                     route_after_step_9_11 ───────────┘
          │                          ↓ (done)
          ├─(9-11 done)──────→ confirm_interpretation (interrupt() HITL)
          │                          ↓
          └─(confirmed)──────→ invoke_deep_agent → END
    """

    NODE_NAMES: ClassVar[dict[str, str]] = {
        "CHECK_STATE": "check_state",
        "INFO_COL": "info_collection",
        "INFO_VAL": "info_validation",
        "RUN_SINGLE_STEP": "run_single_analysis_step",
        "PREPARE_RESEARCH": "prepare_research_summary",
        "COLLECT_CLUSTERS": "collect_clusters",
        "COLLECT_FACTOR": "collect_factor",
        "RUN_SINGLE_STEP_9_11": "run_single_analysis_step_9_11",
        "CONFIRM_INTERP": "confirm_interpretation",
        "INVOKE_DEEP": "invoke_deep_agent",
    }

    ANALYSIS_STEPS = [
        {"step": 1, "tool": "plot_cluster", "desc": "Spatial clustering",
         "figures": ["1.cluster_spatial.png"], "data_files": []},
        {"step": 2, "tool": "runplot_clusterwithcelltyp", "desc": "Cluster-celltype heatmap",
         "figures": ["2.celltype_heatmap_analysis.png"], "data_files": ["sig_clusterwithcelltyp.csv"]},
        {"step": 3, "tool": "plot_neighborhood_enrichment", "desc": "Neighborhood enrichment",
         "figures": ["3.neighborhood_enrichment_squidpy.png"], "data_files": ["res_nhood_enrichment.csv"]},
        {"step": 4, "tool": "runplot_pathway_enrich", "desc": "Pathway enrichment",
         "figures": ["4.spatial_enrich_decoupler.png"], "data_files": ["sig_PathwayEnrich_decoupler.csv"]},
        {"step": 5, "tool": "runplot_spatial_relationship", "desc": "Spatial relationships (MISTy)",
         "figures": ["5.spatial_relation_MISTy.png"], "data_files": ["res_SpatialRelationship_MISTy.csv"]},
        {"step": 6, "tool": "run_lianap", "desc": "LIANA+ CCI analysis (10+ min)",
         "figures": ["6.liana_MoransR.png"], "data_files": ["sig_liana.csv", "lrdata.h5ad"]},
        {"step": 7, "tool": "runplot_liana_factorscore", "desc": "NMF factor scores",
         "figures": [], "data_files": ["res_liana_cluster_factor.csv"]},
        {"step": 8, "tool": "runplot_liana_loadings", "desc": "NMF loadings",
         "figures": ["7.factor_spatial_NMF.png", "8.pathway_factor_heatmap.png"],
         "data_files": ["sig_liana_pathway_factor.csv"]},
    ]

    ANALYSIS_STEPS_9_11 = [
        {"step": 9, "tool": "plot_liana_nmf", "desc": "NMF quadrant plot",
         "figures": ["9.quadrant_analysis.png"], "data_files": ["sel_interest_sig_liana.csv"]},
        {"step": 10, "tool": "plot_liana_spatial_interections", "desc": "Spatial LR interactions",
         "figures": ["10.spatial_plot_interections.png"], "data_files": []},
        {"step": 11, "tool": "plot_liana_interections", "desc": "Cluster-level LR interactions",
         "figures": ["11.lr_interections.png"], "data_files": []},
    ]

    SYSTEM_TEMPLATE: ClassVar[str] = """You are a Deep Interpreter assistant for spatial transcriptomics analysis.

Your job is to collect essential information from the user to configure the analysis pipeline.

You must collect the following information:

1. **h5ad_files**: Path(s) to .h5ad file(s)
   - Example: "/path/to/n_adata.h5ad"

2. **cluster_key**: Column name in adata.obs for cluster assignments
   - Example: "leiden", "louvain", "clusters"

3. **celltype_key** (optional for Visium, required for MERFISH/Xenium/CosMx/seqFISH):
   - Column name in adata.obs for cell type annotations

4. **sample_key** (required if multiple samples):
   - Column name for sample ID in adata.obs

5. **interest_sample** (optional, for multi-sample datasets):
   - Specific sample to analyze for LIANA+ CCI

6. **data_directory**: Output directory for results (res/ folder)
   - Example: "/path/to/results/res"

7. **interest_celltypes** (optional):
   - Cell types to focus CCI analysis on, if the user mentions them
   - Example: ["Macrophage", "Fibroblast", "Invasive Tumor"]

8. **interest_clusters** (optional):
   - Cluster IDs to focus CCI analysis on, if the user mentions them
   - Example: ["4", "16", "17"]

## Pre-populated Fields (from Supervisor)
The following may already be available - only ask if missing:
- st_technology: ST platform type
- disease: Disease/phenotype
- species: "human" or "mouse"
- sample_count: Number of samples

## Guidelines

- Ask for h5ad_files and cluster_key first if not provided
- Then ask for data_directory
- If sample_count > 1, ask for sample_key and optionally interest_sample
- For single-cell platforms (MERFISH, Xenium, CosMx, seqFISH), require celltype_key
- If the user mentions specific clusters or cell types of interest, include them as interest_clusters/interest_celltypes
- Accept various input formats flexibly

## CRITICAL RULES

- DO NOT call the DeepInterpreterInfoExtraction tool until you have at minimum:
  1. h5ad_files (at least one valid path)
  2. cluster_key
  3. data_directory
- Parse all paths as strings
- If user provides all info in one message, call the tool immediately

## Example

User: "I have breast cancer Visium data at /data/n_adata.h5ad, cluster_key='leiden', save to /data/res"
Assistant: [Calls DeepInterpreterInfoExtraction with:
  h5ad_files=["/data/n_adata.h5ad"],
  cluster_key="leiden",
  data_directory="/data/res",
  disease="breast cancer",
  st_technology="Visium"]

User: "Analyze /data/n_adata.h5ad with cluster_key='leiden', save to /data/res. Focus on clusters 4 and 16, especially Macrophage and Fibroblast interactions."
Assistant: [Calls DeepInterpreterInfoExtraction with:
  h5ad_files=["/data/n_adata.h5ad"],
  cluster_key="leiden",
  data_directory="/data/res",
  interest_clusters=["4", "16"],
  interest_celltypes=["Macrophage", "Fibroblast"]]

After you have confirmed ALL required information, call the DeepInterpreterInfoExtraction tool."""

    def __init__(
        self,
        model: Any,
        state_schema: Any = DeepInterpreterWrapperState,
        config_schema: Any | None = None,
        input_schema: Any | None = None,
        output_schema: Any | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
        max_retry_attempts: int = 2,
        agent_name: str | None = None,
        is_debug: bool = True,
        deep_agent_config: Any | None = None,
    ) -> None:
        """Initialize the wrapper agent.

        Args:
            model: LLM model to use for info collection
            state_schema: State schema class
            config_schema: Optional config schema
            input_schema: Optional input schema
            output_schema: Optional output schema
            checkpointer: Optional checkpointer for persistence
            store: Optional store for state
            max_retry_attempts: Max retries for LLM calls
            agent_name: Name for the agent
            is_debug: Enable debug logging
            deep_agent_config: Configuration for the Deep Agent
        """
        super().__init__(
            model=model,
            state_schema=state_schema,
            config_schema=config_schema,
            input_schema=input_schema,
            output_schema=output_schema,
            checkpointer=checkpointer,
            store=store,
            max_retry_attempts=max_retry_attempts,
            agent_name=agent_name or "DeepInterpreterWrapperAgent",
            is_debug=is_debug,
        )
        # Bind DeepInterpreterInfoExtraction tool to LLM
        self.llm_with_tool = self.model.bind_tools([DeepInterpreterInfoExtraction])
        # Deep Agent config - store for later use
        self.deep_agent_config = deep_agent_config
        # Deep Agent will be created on-demand
        self._deep_agent = None

    # ===== Helper Methods =====

    def get_deep_agent(
        self,
        data_directory: str,
        provider_override: str | None = None,
        preselected_targets: dict | None = None,
    ):
        """Get or create the Deep Agent instance with correct data_dir.

        Creates a fresh Deep Agent with per-invocation config to avoid
        concurrency bugs from mutating shared config.

        Args:
            data_directory: Path to analysis results directory
            provider_override: Optional LLM provider from runtime config
            preselected_targets: Optional target config to pre-write as /targets.json

        Returns:
            Compiled Deep Agent runnable
        """
        from src.agents.deep_interpreter.agent import (
            create_deep_interpreter_agent,
            DeepInterpreterConfig,
        )

        if self.deep_agent_config is not None:
            # Create a copy to avoid mutating shared config
            config_copy = deepcopy(self.deep_agent_config)
            config_copy.data_dir = str(data_directory)
            if provider_override:
                config_copy.provider = provider_override
            return create_deep_interpreter_agent(
                config_copy,
                preselected_targets=preselected_targets,
            )
        else:
            kwargs = {"data_dir": str(data_directory)}
            if provider_override:
                kwargs["provider"] = provider_override
            config = DeepInterpreterConfig(**kwargs)
            return create_deep_interpreter_agent(
                config,
                preselected_targets=preselected_targets,
            )

    def _build_research_summary(
        self,
        celltype_csv: pd.DataFrame,
        factor_csv: pd.DataFrame,
        state: dict,
        nhood_csv: pd.DataFrame | None = None,
        pathway_csv: pd.DataFrame | None = None,
        misty_csv: pd.DataFrame | None = None,
        pathway_factor_csv: pd.DataFrame | None = None,
        liana_summary: str | None = None,
    ) -> str:
        """Build a summary of analysis results for research discussion.

        Args:
            celltype_csv: DataFrame from sig_clusterwithcelltyp.csv
            factor_csv: DataFrame from res_liana_cluster_factor.csv
            state: Current wrapper state
            nhood_csv: DataFrame from res_nhood_enrichment.csv (optional)
            pathway_csv: DataFrame from sig_PathwayEnrich_decoupler.csv (optional)
            misty_csv: DataFrame from res_SpatialRelationship_MISTy.csv (optional)
            pathway_factor_csv: DataFrame from sig_liana_pathway_factor.csv (optional)
            liana_summary: Compact summary string from sig_liana.csv (optional)

        Returns:
            Formatted summary string
        """
        summary_parts = []

        # Disease and technology context
        disease = state.get("disease", "unknown")
        st_tech = state.get("st_technology", "unknown")
        summary_parts.append(f"## Analysis Context\n- Disease: {disease}\n- Platform: {st_tech}")

        # Cluster-celltype mapping
        summary_parts.append("\n## Cluster-Cell Type Mapping")
        summary_parts.append(celltype_csv.to_string(index=False))

        # Neighborhood enrichment (spatial co-localization)
        if nhood_csv is not None:
            summary_parts.append("\n## Neighborhood Enrichment (Spatial Co-localization)")
            summary_parts.append("Which cluster pairs are spatially proximal (z-scores):")
            summary_parts.append(nhood_csv.to_string(index=False))

        # Pathway enrichment per cluster
        if pathway_csv is not None:
            summary_parts.append("\n## Pathway Enrichment per Cluster")
            summary_parts.append("Active pathways per cluster (e.g., NFkB, EGFR, Hypoxia):")
            summary_parts.append(pathway_csv.to_string(index=False))

        # Spatial pathway-celltype relationships (MISTy)
        if misty_csv is not None:
            summary_parts.append("\n## Spatial Pathway-Cell Type Relationships (MISTy)")
            summary_parts.append("Which pathways spatially predict which cell types:")
            summary_parts.append(misty_csv.to_string(index=False))

        # Factor scores
        summary_parts.append("\n## NMF Factor-Cluster Scores")
        summary_parts.append(factor_csv.to_string(index=False))

        # NMF factor-pathway associations
        if pathway_factor_csv is not None:
            summary_parts.append("\n## NMF Factor-Pathway Associations")
            summary_parts.append("Which pathways drive each NMF factor:")
            summary_parts.append(pathway_factor_csv.to_string(index=False))

        # L-R interaction landscape summary
        if liana_summary is not None:
            summary_parts.append("\n## L-R Interaction Landscape (Summary)")
            summary_parts.append(liana_summary)

        return "\n".join(summary_parts)

    def _suggest_factor(
        self,
        factor_csv: pd.DataFrame,
        interest_clusters: list[str],
        detailed: bool = False,
    ) -> str | tuple[str, str]:
        """Suggest the best NMF factor using specificity-aware combined scoring.

        Algorithm ported from sp-enrich-mcp sel_factor():
        1. Compute mean factor scores for interest clusters
        2. Compute fold change vs other clusters
        3. Compute Z-score specificity
        4. Combined score = 0.5 * Z-score + 0.5 * (fold_change - 1)

        Args:
            factor_csv: DataFrame from res_liana_cluster_factor.csv
            interest_clusters: List of cluster IDs selected by user
            detailed: If True, return (best_factor, analysis_summary) tuple

        Returns:
            Factor name (e.g. "Factor3"), or tuple of (factor_name, analysis_text)
            if detailed=True
        """
        cluster_col = factor_csv.columns[0]
        factor_cols = [c for c in factor_csv.columns if c.startswith("Factor")]

        if not factor_cols:
            return ("Factor_0", "No factor columns found.") if detailed else "Factor_0"

        df = factor_csv.copy()
        df[cluster_col] = df[cluster_col].astype(str)
        filtered = df[df[cluster_col].isin(interest_clusters)]

        if filtered.empty:
            logger.debug(
                "No matching clusters in factor CSV. interest=%s, available=%s",
                interest_clusters, df[cluster_col].unique().tolist(),
            )
            fallback = factor_cols[0]
            return (fallback, "No matching clusters found.") if detailed else fallback

        # Per-cluster means (already aggregated in CSV)
        df_grouped = df.set_index(cluster_col)[factor_cols]
        interest_means = df_grouped.loc[
            df_grouped.index.isin(interest_clusters)
        ].mean()

        other_clusters = [c for c in df_grouped.index if c not in interest_clusters]
        if not other_clusters:
            best = str(interest_means.idxmax())
            summary = f"Only interest clusters present. Best by mean: {best}"
            return (best, summary) if detailed else best

        other_means = df_grouped.loc[other_clusters].mean()

        # Fold change (interest / others)
        fold_change = interest_means / other_means.clip(lower=1e-10)

        # Z-score specificity
        global_mean = df_grouped.mean()
        global_std = df_grouped.std()
        z_scores = (df_grouped - global_mean) / global_std.replace(0, float("nan"))
        interest_z = z_scores.loc[z_scores.index.isin(interest_clusters)].mean()

        # Combined score (same weights as sel_factor)
        combined = interest_z * 0.5 + (fold_change - 1) * 0.5
        if combined.isna().all():
            best_factor = str(interest_means.idxmax())
            if detailed:
                return best_factor, "All factors have identical scores; selected by highest raw mean."
            return best_factor
        combined = combined.fillna(-float("inf"))
        best_factor = str(combined.idxmax())

        if not detailed:
            return best_factor

        # Build analysis summary for prompt injection
        fold_display = fold_change.fillna(0.0)
        z_display = interest_z.fillna(0.0)
        combined_display = combined.replace(-float("inf"), 0.0)
        lines = [f"Factor specificity analysis for clusters {interest_clusters}:"]
        for f in factor_cols:
            lines.append(
                f"  {f}: mean={interest_means[f]:.3f}, "
                f"fold_change={fold_display[f]:.2f}x, "
                f"z_score={z_display[f]:.3f}, "
                f"combined={combined_display[f]:.3f}"
            )
        lines.append(f"Best factor: {best_factor} (highest combined specificity score)")
        return best_factor, "\n".join(lines)

    def _resolve_celltype_cluster_mapping(
        self,
        save_path: str,
        parsed_celltypes: list[str],
        parsed_clusters: list[str],
        max_clusters_per_celltype: int = 5,
    ) -> tuple[list[str], list[str]]:
        """Bidirectional celltype<->cluster mapping using sig_clusterwithcelltyp.csv.

        - If celltypes provided but no clusters: fuzzy substring match -> extract cluster IDs
        - If clusters provided but no celltypes: look up dominant celltypes per cluster
        - If both provided or both empty: pass through unchanged

        Args:
            save_path: Path to results directory containing sig_clusterwithcelltyp.csv
            parsed_celltypes: User-provided celltype names (may be partial, e.g. "tumor")
            parsed_clusters: User-provided cluster IDs (numeric strings)
            max_clusters_per_celltype: Max clusters to return per matched celltype

        Returns:
            Tuple of (resolved_clusters, resolved_celltypes)
        """
        try:
            ct_csv = pd.read_csv(f"{save_path}/sig_clusterwithcelltyp.csv")
        except FileNotFoundError:
            logger.warning("sig_clusterwithcelltyp.csv not found, skipping celltype<->cluster mapping")
            return parsed_clusters, parsed_celltypes

        # Validate required columns and non-empty
        required_cols = {"cluster", "celltype", "cluster_medians"}
        missing = required_cols - set(ct_csv.columns)
        if missing or ct_csv.empty:
            logger.warning(
                "sig_clusterwithcelltyp.csv missing columns %s or empty, skipping mapping. Available: %s",
                missing, list(ct_csv.columns),
            )
            return parsed_clusters, parsed_celltypes

        resolved_clusters = list(parsed_clusters)
        resolved_celltypes = list(parsed_celltypes)

        # Direction 1: celltypes -> clusters (when user gave celltypes but no cluster IDs)
        if not resolved_clusters and resolved_celltypes:
            # Build combined mask (single filter pass, avoids O(n^2) concat)
            masks = []
            for ct_query in resolved_celltypes:
                escaped = re.escape(ct_query)  # Safety for special chars like "T Cell & Tumor"
                masks.append(ct_csv["celltype"].str.contains(escaped, case=False, na=False))
            combined_mask = pd.concat(masks, axis=1).any(axis=1) if masks else pd.Series([False] * len(ct_csv))
            matched_rows = ct_csv[combined_mask]

            if not matched_rows.empty:
                matched_rows = matched_rows.drop_duplicates(subset=["cluster", "celltype"])
                matched_rows = matched_rows.sort_values("cluster_medians", ascending=False)
                resolved_clusters = [
                    str(c) for c in matched_rows["cluster"].unique()[:max_clusters_per_celltype]
                ]
                resolved_celltypes = list(matched_rows["celltype"].unique())
                logger.info(
                    "Auto-mapped celltypes %s -> clusters %s (matched: %s)",
                    parsed_celltypes, resolved_clusters, resolved_celltypes,
                )

        # Direction 2: clusters -> celltypes (when user gave cluster IDs but no celltypes)
        elif not resolved_celltypes and resolved_clusters:
            ct_csv_copy = ct_csv.copy()
            ct_csv_copy["cluster"] = ct_csv_copy["cluster"].astype(str)
            matched = ct_csv_copy[ct_csv_copy["cluster"].isin(resolved_clusters)]
            if not matched.empty:
                dominant = matched.sort_values("cluster_medians", ascending=False)
                dominant = dominant.drop_duplicates(subset=["cluster"], keep="first")
                resolved_celltypes = list(dominant["celltype"].unique())
                logger.info(
                    "Auto-mapped clusters %s -> celltypes %s",
                    parsed_clusters, resolved_celltypes,
                )

        return resolved_clusters, resolved_celltypes

    def _build_step_args(self, step: int, state: dict) -> dict:
        """Build MCP tool arguments for Steps 1-8."""
        h5ad_files = state.get("h5ad_files") or []
        if not h5ad_files:
            raise ValueError("h5ad_files is empty or not set in state. Info collection may have failed.")
        filename = h5ad_files[0]
        organism = state.get("species") or "human"
        cluster_key = state["cluster_key"]
        celltype_key = state.get("celltype_key")
        sample_key = state.get("sample_key")
        interest_sample = state.get("interest_sample")
        save_path = state["data_directory"]
        lrdata_path = f"{save_path}/lrdata.h5ad"

        if step == 1:
            args = {"filename": filename, "cluster_key": cluster_key, "save_path": save_path}
            if sample_key:
                args["sample_key"] = sample_key
            return args

        if step == 2:
            args = {"filename": filename, "cluster_key": cluster_key, "save_path": save_path}
            if celltype_key:
                args["celltype_key"] = celltype_key
            return args

        if step == 3:
            return {"filename": filename, "cluster_key": cluster_key, "save_path": save_path}

        if step == 4:
            return {"filename": filename, "cluster_key": cluster_key,
                    "organism": organism, "geneset": "progeny", "save_path": save_path}

        if step == 5:
            args = {"filename": filename, "cluster_key": cluster_key,
                    "organism": organism, "geneset": "progeny", "save_path": save_path}
            if celltype_key:
                args["celltype_key"] = celltype_key
            return args

        if step == 6:
            args = {"filename": filename, "organism": organism,
                    "platform": "auto", "save_path": save_path}
            if sample_key:
                args["sample_key"] = sample_key
            if interest_sample:
                args["interest_sample"] = interest_sample
            return args

        if step == 7:
            args = {"filename": lrdata_path, "cluster_key": cluster_key, "save_path": save_path}
            if sample_key:
                args["sample_key"] = sample_key
            return args

        if step == 8:
            return {"filename": lrdata_path, "organism": organism,
                    "geneset": "progeny", "save_path": save_path}

        return {}

    def _build_step_args_9_11(self, step: int, state: dict, sel_factor: str) -> dict:
        """Build MCP tool arguments for Steps 9-11."""
        save_path = state["data_directory"]
        lrdata_path = f"{save_path}/lrdata.h5ad"
        csv_path = f"{save_path}/sig_liana.csv"
        cluster_key = state["cluster_key"]
        sample_key = state.get("sample_key")
        sel_interest_cluster = state["interest_clusters"]

        if step == 9:
            return {
                "lrdata_path": lrdata_path,
                "csv_path": csv_path,
                "cluster_key": cluster_key,
                "sel_interest_cluster": sel_interest_cluster,
                "sel_factor": sel_factor,
                "save_path": save_path,
            }

        # Steps 10-11: read top 3 interactions from Step 9 output CSV
        # CSV is pre-sorted by combinedscore (descending) in Step 9
        sel_interactions_csv = f"{save_path}/sel_interest_sig_liana.csv"
        try:
            sel_interactions_df = pd.read_csv(sel_interactions_csv)
            if "interaction" not in sel_interactions_df.columns:
                logger.error(f"'interaction' column not found in {sel_interactions_csv}. Available: {list(sel_interactions_df.columns)}")
                sel_interactions = []
            else:
                sel_interactions = sel_interactions_df["interaction"].head(3).tolist()
        except FileNotFoundError:
            logger.error(f"sel_interest_sig_liana.csv not found at {sel_interactions_csv}. Step 9 may have failed.")
            sel_interactions = []
        except Exception as e:
            logger.error(f"Failed to read {sel_interactions_csv}: {e}")
            sel_interactions = []

        if step == 10:
            args = {
                "filename": lrdata_path,
                "sel_interactions": sel_interactions,
                "cluster_key": cluster_key,
                "save_path": save_path,
            }
            if sample_key:
                args["sample_key"] = sample_key
            return args

        if step == 11:
            args = {
                "filename": lrdata_path,
                "cluster_key": cluster_key,
                "sel_interactions": sel_interactions,
                "sel_interest_cluster": sel_interest_cluster,
                "save_path": save_path,
            }
            if sample_key:
                args["sample_key"] = sample_key
            return args

        return {}

    def _build_step_message(self, step, step_config, status, save_path, error_msg, total_steps=8):
        """Build multimodal message with progress bar and base64 figure."""
        content_parts = []

        # Text progress
        bar = "=" * step + "." * (total_steps - step)
        text = f"**Step {step}/{total_steps}: {step_config['desc']}** [{bar}]\n"
        if status == "completed":
            text += "Completed successfully"
        elif status == "skipped":
            text += "Skipped (output files already exist)"
        else:
            text += f"Failed: {error_msg}"
        content_parts.append({"type": "text", "text": text})

        # Image(s) using Base64ContentBlock format
        if status in ("completed", "skipped"):
            for fig_name in step_config["figures"]:
                fig_path = f"{save_path}/{fig_name}"
                if os.path.exists(fig_path):
                    try:
                        img_bytes = self._read_and_resize(fig_path)
                        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                        content_parts.append({
                            "type": "image",
                            "source_type": "base64",
                            "mime_type": "image/png",
                            "data": img_b64,
                            "metadata": {"name": fig_name},
                        })
                    except Exception:
                        content_parts.append({"type": "text", "text": f"\n[Figure not readable: {fig_name}]"})
                else:
                    content_parts.append({"type": "text", "text": f"\n[Figure not found: {fig_name}]"})

        return content_parts

    def _read_and_resize(self, fig_path, max_bytes=2_000_000):
        """Read figure, resize if >2MB to limit checkpoint growth."""
        file_size = os.path.getsize(fig_path)
        if file_size <= max_bytes:
            with open(fig_path, "rb") as f:
                return f.read()
        # Try resize with PIL, fall back to raw bytes
        try:
            from PIL import Image
            import io
            img = Image.open(fig_path)
            img.thumbnail((1200, 900), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue()
        except Exception:
            # PIL unavailable or failed — return raw bytes as fallback
            with open(fig_path, "rb") as f:
                return f.read()

    def _check_step_outputs_exist(self, step_config: dict, save_path: str) -> bool:
        """Check if ALL expected output files for a step exist on disk.

        Uses data_files as canonical indicator. For figure-only steps (no data_files),
        falls back to checking figures.
        """
        expected = step_config.get("data_files", []) or step_config.get("figures", [])
        if not expected:
            return False  # No outputs defined — cannot skip
        return all(os.path.exists(f"{save_path}/{f}") for f in expected)

    # ===== Node Initialization =====

    def init_nodes(self, graph: StateGraph):
        """Initialize nodes in the graph."""
        graph.add_node(self.get_node_name("CHECK_STATE"), self.check_state_node)
        graph.add_node(self.get_node_name("INFO_COL"), self.info_collection_node)
        graph.add_node(self.get_node_name("INFO_VAL"), self.info_validation_node)
        graph.add_node(self.get_node_name("RUN_SINGLE_STEP"), self.run_single_analysis_step_node)
        graph.add_node(self.get_node_name("PREPARE_RESEARCH"), self.prepare_research_summary_node)
        graph.add_node(self.get_node_name("COLLECT_CLUSTERS"), self.collect_clusters_node)
        graph.add_node(self.get_node_name("COLLECT_FACTOR"), self.collect_factor_node)
        graph.add_node(self.get_node_name("RUN_SINGLE_STEP_9_11"), self.run_single_analysis_step_9_11_node)
        graph.add_node(self.get_node_name("CONFIRM_INTERP"), self.confirm_interpretation_node)
        graph.add_node(self.get_node_name("INVOKE_DEEP"), self.invoke_deep_agent_node)

    def init_edges(self, graph: StateGraph):
        """Initialize edges in the graph."""
        check_state = self.get_node_name("CHECK_STATE")
        info_col = self.get_node_name("INFO_COL")
        info_val = self.get_node_name("INFO_VAL")
        run_single_step = self.get_node_name("RUN_SINGLE_STEP")
        prepare_research = self.get_node_name("PREPARE_RESEARCH")
        collect_clusters = self.get_node_name("COLLECT_CLUSTERS")
        collect_factor = self.get_node_name("COLLECT_FACTOR")
        run_single_step_9_11 = self.get_node_name("RUN_SINGLE_STEP_9_11")
        confirm_interp = self.get_node_name("CONFIRM_INTERP")
        invoke_deep = self.get_node_name("INVOKE_DEEP")

        # START → check_state
        graph.add_edge(START, check_state)

        # check_state → conditional routing to next incomplete phase
        graph.add_conditional_edges(
            check_state,
            self.route_after_check,
            [info_col, run_single_step, prepare_research, collect_clusters,
             collect_factor, run_single_step_9_11, confirm_interp, invoke_deep],
        )

        # info_collection → [END | info_validation | info_collection]
        graph.add_conditional_edges(
            info_col,
            self.get_state,
            [END, info_val, info_col],
        )

        # info_validation → [info_collection | run_single_step]
        graph.add_conditional_edges(
            info_val,
            self.route_after_validation,
            [info_col, run_single_step],
        )

        # run_single_step → loop or proceed to prepare_research
        graph.add_conditional_edges(
            run_single_step,
            self.route_after_step,
            [run_single_step, prepare_research],
        )

        # prepare_research → collect_clusters (always)
        graph.add_edge(prepare_research, collect_clusters)

        # collect_clusters → self-loop (re-prompt), collect_factor, OR END (if user cancels)
        graph.add_conditional_edges(
            collect_clusters, self.route_after_clusters,
            [collect_clusters, collect_factor, END],
        )

        # collect_factor → run_single_step_9_11 OR END (if user cancels)
        graph.add_conditional_edges(
            collect_factor, self.route_after_factor,
            [run_single_step_9_11, END],
        )

        # run_single_step_9_11 → loop or proceed to confirm
        graph.add_conditional_edges(
            run_single_step_9_11,
            self.route_after_step_9_11,
            [run_single_step_9_11, confirm_interp],
        )

        # confirm_interpretation → invoke_deep_agent OR END (if user declines)
        graph.add_conditional_edges(
            confirm_interp,
            self.route_after_confirmation,
            [invoke_deep, END],
        )

        # invoke_deep_agent → END
        graph.add_edge(invoke_deep, END)

    # ===== Routing Functions =====

    def route_after_check(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> str:
        """Route from check_state to the next incomplete phase.

        NOTE: On happy path, only the first branch (info_complete) is reached
        from START. Other branches document phase order and enable future
        skip-ahead (e.g., Supervisor pre-populating info_complete=True).
        """
        if not state.get("info_complete"):
            return self.get_node_name("INFO_COL")
        if not state.get("analysis_1_8_complete"):
            return self.get_node_name("RUN_SINGLE_STEP")
        # Research discussion sub-phase routing
        if not state.get("research_summary_prepared"):
            return self.get_node_name("PREPARE_RESEARCH")
        if not state.get("clusters_collected"):
            return self.get_node_name("COLLECT_CLUSTERS")
        if not state.get("research_discussion_complete"):
            return self.get_node_name("COLLECT_FACTOR")
        if not state.get("analysis_9_11_complete"):
            return self.get_node_name("RUN_SINGLE_STEP_9_11")
        if not state.get("interpretation_confirmed"):
            return self.get_node_name("CONFIRM_INTERP")
        return self.get_node_name("INVOKE_DEEP")

    def route_after_validation(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> str:
        """Route after info_validation: back to info_collection or forward to analysis."""
        if state.get("info_complete"):
            return self.get_node_name("RUN_SINGLE_STEP")
        return self.get_node_name("INFO_COL")

    def get_state(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> Literal["__end__", "info_validation", "info_collection"]:
        """Determine next state based on message type."""
        messages = state["messages"]

        if isinstance(messages[-1], AIMessage) and messages[-1].tool_calls:
            return self.get_node_name("INFO_VAL")

        if not isinstance(messages[-1], HumanMessage):
            return END

        return self.get_node_name("INFO_COL")

    def route_after_step(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> str:
        """Route after single analysis step: loop or proceed to prepare_research."""
        if state.get("analysis_1_8_complete"):
            return self.get_node_name("PREPARE_RESEARCH")
        return self.get_node_name("RUN_SINGLE_STEP")

    def route_after_step_9_11(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> str:
        """Route after single analysis step 9-11: loop or proceed to confirm."""
        if state.get("analysis_9_11_complete"):
            return self.get_node_name("CONFIRM_INTERP")
        return self.get_node_name("RUN_SINGLE_STEP_9_11")

    def route_after_clusters(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> str:
        """Route after cluster collection: self-loop, proceed to factor, or check_state if cancelled."""
        cc = state.get("clusters_collected")
        if self.is_debug:
            print(f"route_after_clusters: clusters_collected={cc}, research_discussion_complete={state.get('research_discussion_complete')}")
        if not cc:
            return self.get_node_name("COLLECT_CLUSTERS")  # self-loop for re-prompt
        # If cancelled during cluster collection, research_discussion_complete
        # and interpretation_confirmed=False are already set by the node.
        # Route directly to END to avoid double-ask via confirm_interpretation.
        if state.get("research_discussion_complete"):
            return END
        return self.get_node_name("COLLECT_FACTOR")

    def route_after_factor(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> str:
        """Route after factor collection: proceed to steps 9-11 or END if cancelled."""
        if state.get("analysis_9_11_complete"):
            return END
        return self.get_node_name("RUN_SINGLE_STEP_9_11")

    def route_after_confirmation(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> str:
        """Route after confirmation: invoke Deep Agent or end if user declined."""
        if state.get("interpretation_confirmed"):
            return self.get_node_name("INVOKE_DEEP")
        return END

    # ===== Node 1: Check State =====

    async def check_state_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """Entry-point router: routes to the first incomplete phase on graph start.

        NOTE: This node is entered exactly once (from START) on the happy path.
        It is NOT re-entered during normal execution. The routing table in
        route_after_check() documents the phase ordering; actual phase
        transitions are handled by dedicated route_after_* functions.

        Preserved for: (a) consistency with Executor/Supervisor hub pattern,
        (b) readable routing table, (c) future Supervisor skip-ahead option.
        """
        return {}

    # ===== Node 2: Info Collection =====

    def get_messages_with_system(
        self, messages: list, state: dict
    ) -> list:
        """Combine messages with system template, including pre-populated context."""
        system_content = self.SYSTEM_TEMPLATE

        # Add pre-populated fields context
        pre_populated = []
        if state.get("st_technology"):
            pre_populated.append(f"- st_technology: {state['st_technology']}")
        if state.get("disease"):
            pre_populated.append(f"- disease: {state['disease']}")
        if state.get("species"):
            pre_populated.append(f"- species: {state['species']}")
        if state.get("sample_count"):
            pre_populated.append(f"- sample_count: {state['sample_count']}")

        if pre_populated:
            system_content += f"\n\n## Pre-populated Information (already known)\n" + "\n".join(pre_populated)
            system_content += "\nDo NOT ask the user for these fields again. Include them in the tool call."

        return [SystemMessage(content=system_content)] + messages

    async def info_collection_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig
    ) -> dict:
        """Collect Deep Interpreter analysis information from user."""
        try:
            messages = self.get_messages_with_system(state["messages"], state)
            model = self.get_model(config)
            llm_with_tool = model.bind_tools([DeepInterpreterInfoExtraction])
            response = await llm_with_tool.ainvoke(messages)
            return {"messages": [response]}
        except Exception as e:
            if self.is_debug:
                print(f"Error in info_collection_node: {e}")
            raise

    # ===== Node 3: Info Validation =====

    async def info_validation_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """Validate and extract information from tool calls."""
        last_message = state["messages"][-1]

        if not isinstance(last_message, AIMessage):
            raise ValueError("Expected AIMessage with tool call")

        if not last_message.tool_calls:
            raise ValueError("No tool calls found")

        tool_call = last_message.tool_calls[0]
        tool_call_id = tool_call.get("id")
        tool_args = tool_call.get("args", {})

        if not tool_call_id:
            raise ValueError("Missing tool_call_id")

        # Extract fields
        h5ad_files = tool_args.get("h5ad_files")
        cluster_key = tool_args.get("cluster_key")
        data_directory = tool_args.get("data_directory")

        # Validate required fields
        if not h5ad_files or len(h5ad_files) == 0:
            return {
                "messages": [
                    ToolMessage(
                        content="Error: h5ad_files is required. Please provide path(s) to .h5ad file(s).",
                        tool_call_id=tool_call_id,
                    )
                ],
                "info_complete": False,
            }

        if not cluster_key:
            return {
                "messages": [
                    ToolMessage(
                        content="Error: cluster_key is required. Please provide the column name for cluster assignments.",
                        tool_call_id=tool_call_id,
                    )
                ],
                "info_complete": False,
            }

        if not data_directory:
            return {
                "messages": [
                    ToolMessage(
                        content="Error: data_directory is required. Please provide the output directory path.",
                        tool_call_id=tool_call_id,
                    )
                ],
                "info_complete": False,
            }

        # Validate h5ad paths exist
        resolved_paths = []
        for path_str in h5ad_files:
            p = Path(path_str).expanduser().resolve()
            if not await asyncio.to_thread(p.exists):
                return {
                    "messages": [
                        ToolMessage(
                            content=f"Error: h5ad file not found: {p}. Please check the path.",
                            tool_call_id=tool_call_id,
                        )
                    ],
                    "info_complete": False,
                }
            resolved_paths.append(str(p))

        # Resolve data directory
        data_path = Path(data_directory).expanduser().resolve()
        await asyncio.to_thread(data_path.mkdir, parents=True, exist_ok=True)

        # Extract optional/shared fields
        st_technology = tool_args.get("st_technology") or state.get("st_technology")
        disease = tool_args.get("disease") or state.get("disease")
        species = tool_args.get("species") or state.get("species")
        sample_count = tool_args.get("sample_count") or state.get("sample_count")
        celltype_key = tool_args.get("celltype_key")
        sample_key = tool_args.get("sample_key")
        interest_sample = tool_args.get("interest_sample")
        interest_celltypes = tool_args.get("interest_celltypes")
        interest_clusters = tool_args.get("interest_clusters")

        # Validate sample_key for multi-sample
        if sample_count and sample_count > 1 and not sample_key:
            return {
                "messages": [
                    ToolMessage(
                        content="Error: sample_key is required when sample_count > 1. Please provide the sample column name.",
                        tool_call_id=tool_call_id,
                    )
                ],
                "info_complete": False,
            }

        if self.is_debug:
            print("Info collection complete:")
            print(f"  h5ad_files: {resolved_paths}")
            print(f"  cluster_key: {cluster_key}")
            print(f"  data_directory: {data_path}")
            print(f"  st_technology: {st_technology}")

        return {
            "messages": [
                ToolMessage(
                    content=(
                        f"Configuration collected:\n"
                        f"- h5ad files: {resolved_paths}\n"
                        f"- cluster_key: {cluster_key}\n"
                        f"- data_directory: {data_path}\n"
                        f"- st_technology: {st_technology}\n"
                        f"- disease: {disease}\n"
                        f"\nProceeding to spatial analysis pipeline (Steps 1-8)..."
                    ),
                    tool_call_id=tool_call_id,
                )
            ],
            "h5ad_files": resolved_paths,
            "cluster_key": cluster_key,
            "celltype_key": celltype_key,
            "sample_key": sample_key,
            "interest_sample": interest_sample,
            **({"interest_celltypes": interest_celltypes} if interest_celltypes else {}),
            **({"interest_clusters": interest_clusters} if interest_clusters else {}),
            "data_directory": str(data_path),
            "st_technology": st_technology,
            "disease": disease,
            "species": species,
            "sample_count": sample_count,
            "info_complete": True,
        }

    # ===== Node 4: Run Single Analysis Step (Loop Pattern) =====

    async def run_single_analysis_step_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig
    ) -> dict:
        """Execute ONE spatial analysis step per invocation (Steps 1-8).

        This node is called repeatedly via a conditional edge loop.
        Each invocation runs one MCP tool and returns a multimodal
        message with progress bar and inline base64 figure.
        """
        current_step = state.get("current_analysis_step") or 1
        step_config = self.ANALYSIS_STEPS[current_step - 1]
        save_path = state["data_directory"]

        # Dependency check: Steps 7-8 need lrdata.h5ad from Step 6
        if current_step in (7, 8):
            lrdata_path = f"{save_path}/lrdata.h5ad"
            if not os.path.exists(lrdata_path):
                message_content = [{"type": "text",
                    "text": f"**Step {current_step}/8: {step_config['desc']}** - SKIPPED (lrdata.h5ad not found, Step 6 may have failed)"}]
                is_last = current_step >= 8
                return {
                    "current_analysis_step": current_step + 1 if not is_last else current_step,
                    "messages": [AIMessage(content=message_content)],
                    **({"analysis_1_8_complete": True} if is_last else {}),
                }

        # Skip check: if all output files already exist, skip MCP call
        configurable = (config or {}).get("configurable", {})
        force_rerun = configurable.get("force_rerun", False)

        if not force_rerun and self._check_step_outputs_exist(step_config, save_path):
            if self.is_debug:
                print(f"Step {current_step}/8: {step_config['desc']} - SKIPPED (cached)")
            message_content = self._build_step_message(
                current_step, step_config, "skipped", save_path, None
            )
            is_last = current_step >= 8
            update = {
                "current_analysis_step": current_step + 1 if not is_last else current_step,
                "messages": [AIMessage(content=message_content)],
            }
            if is_last:
                update["analysis_1_8_complete"] = True
            return update

        # Build tool args
        tool_args = self._build_step_args(current_step, state)

        # Get MCP server paths
        sp_python = os.getenv("SP_ENRICH_MCP_PYTHON")
        sp_server_path = os.getenv("SP_ENRICH_MCP_SERVER_PATH")

        if not sp_python or not sp_server_path:
            raise ValueError(
                "SP_ENRICH_MCP_PYTHON and SP_ENRICH_MCP_SERVER_PATH environment variables must be set"
            )

        if self.is_debug:
            print(f"Step {current_step}/8: {step_config['desc']} - Starting")

        # Call MCP tool with safe lifecycle (async with auto-cleanup)
        try:
            client = MultiServerMCPClient({
                "sp-enrich-mcp": {
                    "command": sp_python,
                    "args": [f"{sp_server_path}/server.py"],
                    "transport": "stdio",
                }
            })
            tools = await client.get_tools()
            tool = next((t for t in tools if t.name == step_config["tool"]
                         or t.name.endswith(f'__{step_config["tool"]}')), None)
            if tool is None:
                raise ValueError(f"Tool {step_config['tool']} not found")
            result = await tool.ainvoke(tool_args)
            status = "completed"
            error_msg = None
        except Exception as e:
            status = "failed"
            error_msg = str(e)

        if self.is_debug:
            print(f"Step {current_step}/8: {step_config['desc']} - {status}")

        # Build multimodal message with base64 figure
        message_content = self._build_step_message(
            current_step, step_config, status, save_path, error_msg
        )

        is_last = current_step >= 8
        update = {
            "current_analysis_step": current_step + 1 if not is_last else current_step,
            "messages": [AIMessage(content=message_content)],
        }
        if is_last:
            update["analysis_1_8_complete"] = True

        return update

    # ===== Node 5a: Prepare Research Summary (no interrupt, runs ONCE) =====

    async def prepare_research_summary_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig
    ) -> dict:
        """Read CSVs and generate LLM suggestion. No interrupt — runs once.

        Stores llm_suggestion in state so collect_clusters can use it
        without re-running this expensive work on resume.
        """
        save_path = state["data_directory"]

        # Read analysis outputs — required CSVs
        try:
            celltype_csv = pd.read_csv(f"{save_path}/sig_clusterwithcelltyp.csv")
        except FileNotFoundError:
            celltype_csv = pd.DataFrame({"note": ["celltype analysis was skipped (no celltype_key)"]})

        try:
            factor_csv = pd.read_csv(f"{save_path}/res_liana_cluster_factor.csv")
        except FileNotFoundError:
            raise ValueError(
                f"res_liana_cluster_factor.csv not found in {save_path}. "
                "Steps 1-8 may not have completed successfully."
            )

        # Read additional CSVs — all optional, gracefully skip if missing
        nhood_csv = None
        try:
            nhood_csv = pd.read_csv(f"{save_path}/res_nhood_enrichment.csv")
        except FileNotFoundError:
            logger.debug("res_nhood_enrichment.csv not found — skipping neighborhood enrichment context")

        pathway_csv = None
        try:
            pathway_csv = pd.read_csv(f"{save_path}/sig_PathwayEnrich_decoupler.csv")
        except FileNotFoundError:
            logger.debug("sig_PathwayEnrich_decoupler.csv not found — skipping pathway enrichment context")

        misty_csv = None
        try:
            misty_csv = pd.read_csv(f"{save_path}/res_SpatialRelationship_MISTy.csv")
        except FileNotFoundError:
            logger.debug("res_SpatialRelationship_MISTy.csv not found — skipping MISTy context")

        pathway_factor_csv = None
        try:
            pathway_factor_csv = pd.read_csv(f"{save_path}/sig_liana_pathway_factor.csv")
        except FileNotFoundError:
            logger.debug("sig_liana_pathway_factor.csv not found — skipping factor-pathway context")

        # sig_liana.csv — summarize only (can be 1000+ rows)
        liana_summary = None
        try:
            liana_df = pd.read_csv(f"{save_path}/sig_liana.csv")
            summary_lines = []
            # Count of significant L-R pairs per factor
            factor_cols_liana = [c for c in liana_df.columns if c.startswith("Factor")]
            if factor_cols_liana:
                # Each factor column has scores; count non-null entries per factor
                pair_counts = {f: int(liana_df[f].notna().sum()) for f in factor_cols_liana}
                summary_lines.append(f"Significant L-R pairs per factor: {pair_counts}")
            # Top 5 L-R pairs by Moran's R score (if column exists)
            morans_col = None
            for candidate in ["morans_r", "MoransR", "morans_R", "Morans_R"]:
                if candidate in liana_df.columns:
                    morans_col = candidate
                    break
            if morans_col:
                top5 = liana_df.nlargest(5, morans_col)
                interaction_col = "interaction" if "interaction" in top5.columns else top5.columns[0]
                top5_str = top5[[interaction_col, morans_col]].to_string(index=False)
                summary_lines.append(f"Top 5 L-R pairs by Moran's R:\n{top5_str}")
            # Unique pathway count
            pathway_col = None
            for candidate in ["pathway", "Pathway", "pathway_name"]:
                if candidate in liana_df.columns:
                    pathway_col = candidate
                    break
            if pathway_col:
                n_pathways = liana_df[pathway_col].nunique()
                summary_lines.append(f"Unique pathways represented: {n_pathways}")
            summary_lines.append(f"Total significant L-R pairs: {len(liana_df)}")
            liana_summary = "\n".join(summary_lines)
        except FileNotFoundError:
            logger.debug("sig_liana.csv not found — skipping L-R landscape summary")

        summary = self._build_research_summary(
            celltype_csv, factor_csv, state,
            nhood_csv=nhood_csv,
            pathway_csv=pathway_csv,
            misty_csv=misty_csv,
            pathway_factor_csv=pathway_factor_csv,
            liana_summary=liana_summary,
        )

        # Resolve pre-populated interest targets for LLM prompt enrichment
        pre_celltypes = state.get("interest_celltypes") or []
        pre_clusters = state.get("interest_clusters") or []
        user_preference_context = ""
        resolved_clusters: list[str] = []

        if pre_celltypes or pre_clusters:
            resolved_clusters, resolved_celltypes = self._resolve_celltype_cluster_mapping(
                save_path, pre_celltypes, pre_clusters,
            )
            # Build context string for LLM prompt
            parts = []
            if pre_celltypes:
                parts.append(f"- Pre-selected cell types: {pre_celltypes}")
            if pre_clusters:
                parts.append(f"- Pre-selected clusters: {pre_clusters}")
            if resolved_clusters and resolved_clusters != pre_clusters:
                parts.append(f"- Auto-resolved clusters (from cell types): {resolved_clusters}")
            if resolved_celltypes and resolved_celltypes != pre_celltypes:
                parts.append(f"- Auto-resolved cell types (from clusters): {resolved_celltypes}")
            user_preference_context = "\n".join(parts)

            if self.is_debug:
                print(f"Pre-populated targets resolved: clusters={resolved_clusters}, celltypes={resolved_celltypes}")

        # Compute data-driven factor suggestion when pre-populated clusters available
        computed_factor_hint = ""
        if pre_clusters or (pre_celltypes and resolved_clusters):
            effective_clusters = resolved_clusters if resolved_clusters else pre_clusters
            best_factor, factor_analysis = self._suggest_factor(
                factor_csv, [str(c) for c in effective_clusters], detailed=True,
            )
            computed_factor_hint = (
                f"\n\nDATA-DRIVEN FACTOR ANALYSIS:\n{factor_analysis}\n"
                "Use this mathematical analysis to recommend the correct NMF factor. "
                "Do NOT override this with pathway narrative alone."
            )

            if self.is_debug:
                print(f"Computed factor: {best_factor}\n{factor_analysis}")

        # LLM suggests interest_clusters and interest_celltypes based on disease context
        disease = state.get("disease", "unknown")
        system_content = (
            f"You are analyzing {disease} spatial transcriptomics data. "
            "Based on the comprehensive analysis summary below, suggest which clusters "
            "and cell types are most relevant for investigating cell-cell interactions. "
            "Consider ALL evidence: cell type composition, spatial co-localization, "
            "active pathways, spatial relationships, and NMF factor-pathway associations. "
            "Also suggest the most informative NMF factor. Choose the factor with the highest "
            "mean score across your suggested clusters in the NMF Factor-Cluster Scores table — "
            "a factor specific to interest clusters (high fold-change vs others) is more informative "
            "than one that is high across all clusters. "
            "Be specific about WHY each cluster/celltype is interesting."
        )

        if user_preference_context:
            system_content += (
                "\n\nIMPORTANT: The user has pre-selected targets of interest. "
                "Prioritize these in your suggestion and explain how the analysis data "
                "supports or challenges each selection:\n"
                + user_preference_context
            )

        if computed_factor_hint:
            system_content += computed_factor_hint

        try:
            llm_result = await asyncio.wait_for(
                self.get_model(config).ainvoke([
                    SystemMessage(content=system_content),
                    HumanMessage(content=f"Analysis results:\n{summary}\n\nSuggest interest clusters and cell types."),
                ]),
                timeout=60.0,
            )
        except asyncio.TimeoutError:
            logger.error("LLM suggestion timed out after 60s. Using fallback.")
            llm_result = type('obj', (object,), {
                'content': 'Suggestion unavailable (LLM timeout). Please select clusters based on the heatmap above.'
            })()

        if self.is_debug:
            print("Research summary prepared and LLM suggestion cached.")

        return {
            "research_summary_prepared": True,
            "llm_suggestion": llm_result.content,
        }

    # ===== Node 5b: Collect Clusters (single interrupt, self-loop for re-prompt) =====

    async def collect_clusters_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig
    ) -> dict:
        """HITL cluster/celltype selection with exactly ONE interrupt() per invocation.

        Uses cluster_attempt state to decide prompt text:
          attempt=0 → full AI suggestion prompt
          attempt>=1 → re-prompt asking specifically for cluster IDs

        On empty clusters: returns clusters_collected=False so route_after_clusters
        loops back to this node (self-loop pattern). Max 2 re-prompts before
        proceeding with empty clusters to prevent infinite loops.
        """
        attempt = state.get("cluster_attempt") or 0
        save_path = state["data_directory"]
        disease = state.get("disease", "unknown")
        st_tech = state.get("st_technology", "unknown")

        # Build prompt based on attempt number
        if attempt == 0:
            llm_suggestion_text = state.get("llm_suggestion", "No suggestion available.")

            # Check for pre-populated values from initial user message
            pre_celltypes = state.get("interest_celltypes")
            pre_clusters = state.get("interest_clusters")

            if pre_celltypes or pre_clusters:
                pre_pop_section = "\n## Your Initial Selections (from your first message)\n"
                if pre_celltypes:
                    pre_pop_section += f"- interest_celltypes: {json.dumps(pre_celltypes)}\n"
                if pre_clusters:
                    pre_pop_section += f"- interest_clusters: {json.dumps(pre_clusters)}\n"
                pre_pop_section += "\nThese are pre-filled below. Confirm or modify as needed.\n"
            else:
                pre_pop_section = ""

            celltypes_default = json.dumps(pre_celltypes) if pre_celltypes else '(e.g., ["Invasive Tumor", "Fibroblast", "Macrophage"])'
            clusters_default = json.dumps(pre_clusters) if pre_clusters else '(e.g., ["4", "16", "17"])'

            prompt = f"""## Analysis Context
- Disease: {disease}
- Platform: {st_tech}

## AI Suggestion
{llm_suggestion_text}
{pre_pop_section}
Please review the image at: `{save_path}/2.celltype_heatmap_analysis.png`

**Confirm or modify:**
- interest_celltypes: {celltypes_default}
- interest_clusters: {clusters_default}

Please provide your selections as JSON or natural language."""
        else:
            prompt = (
                "**No clusters were detected in your response.** "
                "Steps 9-11 require at least one cluster.\n\n"
                "Please provide interest_clusters as a list of cluster IDs "
                "(e.g., [\"4\", \"16\", \"17\"] or just: 4, 16, 17)."
            )

        # Single unconditional interrupt — always reached
        response = interrupt(value={"message": prompt})

        # Parse response
        if isinstance(response, dict):
            actual_response = response.get("response", response.get("message", str(response)))
        else:
            actual_response = str(response)

        logger.info("collect_clusters: raw=%r, parsed=%r", response, actual_response)

        # Check for cancel/skip
        if actual_response.lower().strip() in CANCEL_KEYWORDS:
            logger.info("User cancelled at cluster selection (attempt %d). Ending workflow.", attempt)
            return {
                "clusters_collected": True,
                "research_discussion_complete": True,
                "analysis_9_11_complete": True,
                "interpretation_confirmed": False,
                "messages": [AIMessage(content="Research discussion cancelled by user.")],
            }

        # Phase 1: Try direct JSON parse (no LLM needed for structured input like '["4","16","17"]')
        parsed_celltypes = []
        parsed_clusters = []
        try:
            direct_parsed = json.loads(actual_response)
            if isinstance(direct_parsed, list):
                # Separate numeric cluster IDs from non-numeric cell type names
                for item in direct_parsed:
                    s = str(item).strip()
                    if s.isdigit():
                        parsed_clusters.append(s)
                    else:
                        parsed_celltypes.append(s)
            elif isinstance(direct_parsed, dict):
                parsed_clusters = [str(x) for x in direct_parsed.get("interest_clusters", [])]
                parsed_celltypes = direct_parsed.get("interest_celltypes", [])
            if self.is_debug:
                print(f"Direct JSON parse succeeded: clusters={parsed_clusters}, celltypes={parsed_celltypes}")
        except (json.JSONDecodeError, TypeError, ValueError):
            pass  # Not valid JSON — fall through to LLM parsing

        # Phase 2: LLM parsing with timeout (only for natural language input)
        if not parsed_clusters and not parsed_celltypes:
            try:
                parse_result = await asyncio.wait_for(
                    self.get_model(config).ainvoke([
                        SystemMessage(content=(
                            "Extract interest_celltypes and interest_clusters from the user's response. "
                            "Return ONLY valid JSON: {\"interest_celltypes\": [...], \"interest_clusters\": [...]}\n"
                            "Cluster IDs must be strings (e.g. \"4\" not 4)."
                        )),
                        HumanMessage(content=actual_response),
                    ]),
                    timeout=30.0,
                )

                try:
                    raw_content = parse_result.content.strip()
                    # Strip markdown fences (LLMs often wrap JSON in ```json ... ```)
                    if raw_content.startswith("```"):
                        raw_content = re.sub(r'^```(?:json)?\s*', '', raw_content)
                        raw_content = re.sub(r'\s*```$', '', raw_content)
                    parsed = json.loads(raw_content)
                    parsed_celltypes = parsed.get("interest_celltypes", [])
                    parsed_clusters = parsed.get("interest_clusters", [])
                except (json.JSONDecodeError, AttributeError) as e:
                    logger.warning(f"JSON parse failed: {e}. Raw: {parse_result.content[:200]}")
                    # Regex fallback: extract cluster numbers and quoted/single-quoted cell type strings
                    cluster_match = re.findall(r'\b(\d+)\b', actual_response)
                    parsed_clusters = cluster_match[:10] if cluster_match else []
                    celltype_match = re.findall(
                        r'"([^"]+)"|\'([^\']+)\'|(?:^|,)\s*([A-Z][a-zA-Z\s]+?)(?=\s*,|\s*$)',
                        actual_response,
                    )
                    # Flatten regex groups (each match is a tuple of 3 groups, only one is non-empty)
                    parsed_celltypes = [g for groups in celltype_match for g in groups if g] if celltype_match else []
            except asyncio.TimeoutError:
                logger.error("LLM parsing timed out after 30s. Falling back to regex extraction.")
                cluster_match = re.findall(r'\b(\d+)\b', actual_response)
                parsed_clusters = cluster_match[:10] if cluster_match else []
                celltype_match = re.findall(
                    r'"([^"]+)"|\'([^\']+)\'|(?:^|,)\s*([A-Z][a-zA-Z\s]+?)(?=\s*,|\s*$)',
                    actual_response,
                )
                parsed_celltypes = [g for groups in celltype_match for g in groups if g] if celltype_match else []
            except Exception as e:
                logger.error(f"LLM parsing call failed: {e}. Falling back to regex extraction.")
                cluster_match = re.findall(r'\b(\d+)\b', actual_response)
                parsed_clusters = cluster_match[:10] if cluster_match else []
                celltype_match = re.findall(
                    r'"([^"]+)"|\'([^\']+)\'|(?:^|,)\s*([A-Z][a-zA-Z\s]+?)(?=\s*,|\s*$)',
                    actual_response,
                )
                parsed_celltypes = [g for groups in celltype_match for g in groups if g] if celltype_match else []

        # Authoritative resolution (post-HITL) — distinct from prompt-enrichment
        # resolution in prepare_research_summary_node
        parsed_clusters, parsed_celltypes = self._resolve_celltype_cluster_mapping(
            save_path, parsed_celltypes, parsed_clusters,
        )

        # If clusters empty: self-loop for re-prompt (up to 2 re-prompts)
        if not parsed_clusters:
            if attempt >= 2:
                logger.error("Still no clusters after %d re-prompts. Proceeding with empty clusters.", attempt)
                # Fall through to success path with empty clusters (don't loop forever)
            else:
                logger.warning("Empty cluster selection (attempt %d). Will re-prompt.", attempt)
                # Preserve celltypes from first attempt if we got some
                update = {
                    "cluster_attempt": attempt + 1,
                    "clusters_collected": False,  # triggers self-loop via route_after_clusters
                    "messages": [
                        HumanMessage(content=actual_response),
                        AIMessage(content="No clusters detected in your response. Let me ask again..."),
                    ],
                }
                if parsed_celltypes:
                    update["interest_celltypes"] = parsed_celltypes
                return update

        if self.is_debug:
            print(f"Clusters collected: {parsed_clusters}, celltypes: {parsed_celltypes}")

        # Merge celltypes: use newly parsed ones, or fall back to state (from previous attempt)
        final_celltypes = parsed_celltypes or state.get("interest_celltypes") or []

        return {
            "interest_celltypes": final_celltypes,
            "interest_clusters": parsed_clusters,
            "clusters_collected": True,
            "messages": [
                HumanMessage(content=actual_response),
                AIMessage(content=f"Selected clusters: {parsed_clusters}, cell types: {final_celltypes}. Proceeding to NMF factor selection..."),
            ],
        }

    # ===== Node 5c: Collect Factor (1x interrupt) =====

    async def collect_factor_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """HITL factor selection with single interrupt().

        Reads interest_clusters from state to compute best factor suggestion.
        """
        save_path = state["data_directory"]
        parsed_clusters = state.get("interest_clusters") or []

        # Read factor CSV for suggestion computation
        try:
            factor_csv = pd.read_csv(f"{save_path}/res_liana_cluster_factor.csv")
        except FileNotFoundError:
            logger.warning(
                "res_liana_cluster_factor.csv not found in %s. "
                "Using default factor. Steps 1-8 may not have completed.",
                save_path,
            )
            sel_factor_suggestion = "Factor_0"
            available_factors = ["Factor_0"]
            # Skip CSV-based suggestion, jump to interrupt with defaults
            prompt2 = f"""Please review the image at: `{save_path}/7.factor_spatial_NMF.png`

**Note:** Factor CSV not found — defaulting to {sel_factor_suggestion}.

Available factors: {available_factors}
**Confirm or modify sel_factor:**"""

            response2 = interrupt(value={"message": prompt2})

            if isinstance(response2, dict):
                actual_response2 = response2.get("response", response2.get("message", str(response2)))
            else:
                actual_response2 = str(response2)

            logger.info("collect_factor (fallback): raw=%r, parsed=%r", response2, actual_response2)

            if actual_response2.lower().strip() in CANCEL_KEYWORDS:
                logger.info("User cancelled at factor selection. Ending workflow.")
                return {
                    "research_discussion_complete": True,
                    "analysis_9_11_complete": True,
                    "interpretation_confirmed": False,
                    "messages": [AIMessage(content="Factor selection cancelled by user.")],
                }

            parsed_factor = sel_factor_suggestion
            response2_lower = actual_response2.lower().strip()
            if "factor" in response2_lower:
                match = re.search(r"factor[_\s]?(\d+)", response2_lower)
                if match:
                    num = match.group(1)
                    candidate = f"Factor_{num}"
                    if candidate not in available_factors:
                        candidate = f"Factor{num}"
                    parsed_factor = candidate

            return {
                "sel_factor": parsed_factor,
                "research_discussion_complete": True,
                "current_analysis_step": 9,
                "messages": [HumanMessage(content=actual_response2)],
            }

        sel_factor_suggestion = self._suggest_factor(factor_csv, parsed_clusters)
        available_factors = [c for c in factor_csv.columns if c.startswith("Factor")]

        prompt2 = f"""Please review the image at: `{save_path}/7.factor_spatial_NMF.png`

Based on the cluster-factor analysis, **{sel_factor_suggestion}** has the highest association with your selected clusters {parsed_clusters}.

Available factors: {available_factors}
**Confirm or modify sel_factor:**"""

        response2 = interrupt(value={"message": prompt2})

        if isinstance(response2, dict):
            actual_response2 = response2.get("response", response2.get("message", str(response2)))
        else:
            actual_response2 = str(response2)

        logger.info("collect_factor: raw=%r, parsed=%r", response2, actual_response2)

        # Check for cancel/skip
        if actual_response2.lower().strip() in CANCEL_KEYWORDS:
            logger.info("User cancelled at factor selection. Ending workflow.")
            return {
                "research_discussion_complete": True,
                "analysis_9_11_complete": True,
                "interpretation_confirmed": False,
                "messages": [AIMessage(content="Factor selection cancelled by user.")],
            }

        # Parse factor selection
        parsed_factor = sel_factor_suggestion  # default
        response2_lower = actual_response2.lower().strip()
        if "factor" in response2_lower:
            match = re.search(r"factor[_\s]?(\d+)", response2_lower)
            if match:
                num = match.group(1)
                candidate = f"Factor_{num}"
                if candidate not in available_factors:
                    candidate = f"Factor{num}"  # Try without underscore
                if candidate in available_factors:
                    parsed_factor = candidate
                else:
                    logger.warning(
                        f"User selected Factor_{num}/Factor{num} but not in available: {available_factors}. "
                        f"Using suggestion: {sel_factor_suggestion}"
                    )
        elif response2_lower in ("yes", "ok", "confirm", "y", "sure", "accepted"):
            parsed_factor = sel_factor_suggestion

        if self.is_debug:
            print(f"Research discussion complete:")
            print(f"  interest_clusters: {parsed_clusters}")
            print(f"  sel_factor: {parsed_factor}")

        return {
            "sel_factor": parsed_factor,
            "research_discussion_complete": True,
            "current_analysis_step": 9,  # Reset for Steps 9-11 phase
            "messages": [HumanMessage(content=actual_response2)],
        }

    # ===== Node 6: Run Single Analysis Step 9-11 (Loop Pattern) =====

    async def run_single_analysis_step_9_11_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig
    ) -> dict:
        """Execute ONE targeted analysis step per invocation (Steps 9-11).

        Same loop pattern as Steps 1-8 but with different tool args
        and dependency on HITL outputs (interest_clusters, sel_factor).
        """
        current_step = state.get("current_analysis_step") or 9
        step_idx = current_step - 9  # 0, 1, 2
        step_config = self.ANALYSIS_STEPS_9_11[step_idx]
        save_path = state["data_directory"]

        # Validate sel_factor on first entry (step 9 only)
        sel_factor = state["sel_factor"]
        if current_step == 9:
            csv_path = f"{save_path}/sig_liana.csv"
            try:
                sig_headers = pd.read_csv(csv_path, index_col=0, nrows=0)
                available = [c for c in sig_headers.columns if c.startswith("Factor")]
                if sel_factor not in available and available:
                    sel_factor = available[0]
            except FileNotFoundError:
                pass

        # Dependency check: Steps 10-11 need sel_interest_sig_liana.csv from Step 9
        if current_step in (10, 11):
            csv_path = f"{save_path}/sel_interest_sig_liana.csv"
            if not os.path.exists(csv_path):
                message_content = [{"type": "text",
                    "text": f"**Step {current_step}/11: {step_config['desc']}** - SKIPPED (sel_interest_sig_liana.csv not found)"}]
                is_last = current_step >= 11
                return {
                    "current_analysis_step": current_step + 1 if not is_last else current_step,
                    "messages": [AIMessage(content=message_content)],
                    **({"analysis_9_11_complete": True} if is_last else {}),
                }

        # Skip check: if all output files already exist, skip MCP call
        configurable = (config or {}).get("configurable", {})
        force_rerun = configurable.get("force_rerun", False)

        if not force_rerun and self._check_step_outputs_exist(step_config, save_path):
            if self.is_debug:
                print(f"Step {current_step}/11: {step_config['desc']} - SKIPPED (cached)")
            message_content = self._build_step_message(
                current_step, step_config, "skipped", save_path, None, total_steps=11
            )
            is_last = current_step >= 11
            update = {
                "current_analysis_step": current_step + 1 if not is_last else current_step,
                "messages": [AIMessage(content=message_content)],
            }
            if is_last:
                update["analysis_9_11_complete"] = True
            return update

        # Build tool args
        tool_args = self._build_step_args_9_11(current_step, state, sel_factor)

        # Get MCP server paths
        sp_python = os.getenv("SP_ENRICH_MCP_PYTHON")
        sp_server_path = os.getenv("SP_ENRICH_MCP_SERVER_PATH")

        if not sp_python or not sp_server_path:
            raise ValueError(
                "SP_ENRICH_MCP_PYTHON and SP_ENRICH_MCP_SERVER_PATH environment variables must be set"
            )

        if self.is_debug:
            print(f"Step {current_step}/11: {step_config['desc']} - Starting")

        # Call MCP tool with safe lifecycle
        try:
            client = MultiServerMCPClient({
                "sp-enrich-mcp": {
                    "command": sp_python,
                    "args": [f"{sp_server_path}/server.py"],
                    "transport": "stdio",
                }
            })
            tools = await client.get_tools()
            tool = next((t for t in tools if t.name == step_config["tool"]
                         or t.name.endswith(f'__{step_config["tool"]}')), None)
            if tool is None:
                raise ValueError(f"Tool {step_config['tool']} not found")
            result = await tool.ainvoke(tool_args)
            status = "completed"
            error_msg = None
        except Exception as e:
            status = "failed"
            error_msg = str(e)

        if self.is_debug:
            print(f"Step {current_step}/11: {step_config['desc']} - {status}")

        # Build multimodal message
        message_content = self._build_step_message(
            current_step, step_config, status, save_path, error_msg, total_steps=11
        )

        is_last = current_step >= 11
        update = {
            "current_analysis_step": current_step + 1 if not is_last else current_step,
            "messages": [AIMessage(content=message_content)],
        }
        if is_last:
            update["analysis_9_11_complete"] = True

        return update

    # ===== Node 7: Confirm Interpretation (HITL) =====

    async def confirm_interpretation_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig  # noqa: ARG002
    ) -> dict:
        """HITL confirmation before invoking the expensive Deep Agent pipeline.

        Uses interrupt() to ask the user whether to proceed with full
        interpretation after all analysis steps (1-11) are complete.
        """
        save_path = state["data_directory"]
        prompt = (
            f"All analyses are complete (Steps 1-11).\n"
            f"Results directory: `{save_path}`\n\n"
            f"Would you like to proceed with full interpretation?\n"
            f"(Deep Interpreter will search literature and generate an interpretation report)\n\n"
            f"Type 'yes' to proceed, or 'no'/'skip' to cancel."
        )
        response = interrupt(value={"message": prompt})

        # Check if user wants to cancel
        response_str = str(response).strip().lower()
        if isinstance(response, dict):
            response_str = response.get("response", response.get("message", str(response))).strip().lower()

        if not response_str or response_str in CANCEL_KEYWORDS:
            logger.info("User declined interpretation. Ending workflow.")
            return {
                "interpretation_confirmed": False,
                "messages": [HumanMessage(content=str(response))],
            }

        return {
            "interpretation_confirmed": True,
            "messages": [HumanMessage(content=str(response))],
        }

    # ===== Node 8: Invoke Deep Agent =====

    async def invoke_deep_agent_node(
        self, state: DeepInterpreterWrapperState, config: RunnableConfig
    ) -> dict:
        """Invoke the Deep Agent for CCI interpretation and report generation.

        Creates a per-invocation Deep Agent with fresh config to avoid
        concurrency issues from mutating shared config.
        """
        data_directory = state.get("data_directory")
        if not data_directory:
            raise ValueError("data_directory is required but not set in state")

        if self.is_debug:
            print(f"Invoking Deep Agent for: {data_directory}")

        # Build initial message with embedded targets
        targets_content = {
            "interest_clusters": state.get("interest_clusters"),
            "interest_celltypes": state.get("interest_celltypes"),
            "sel_factor": state.get("sel_factor"),
            "data_directory": str(data_directory),
        }

        # Get or create Deep Agent with per-invocation config
        configurable = (config or {}).get("configurable", {})
        provider_override = (configurable.get("llm_provider") or "").strip() or None
        deep_agent = await asyncio.to_thread(
            self.get_deep_agent,
            data_directory,
            provider_override=provider_override,
            preselected_targets=targets_content,
        )

        initial_message = f"""Interpret the CCI analysis results in {data_directory}.

## PRE-SELECTED TARGET CONFIGURATION
The following targets have been pre-selected by the user (DO NOT ask for user input):

```json
{json.dumps(targets_content, indent=2)}
```

IMPORTANT: /targets.json is already pre-written by the wrapper/framework.
The planner should read /targets.json and proceed directly to strategic planning."""

        try:
            result = await deep_agent.ainvoke(
                {"messages": [{"role": "user", "content": initial_message}]},
                config=config,
            )

            if self.is_debug:
                print("Deep Agent invocation complete")

            deep_messages = result.get("messages", [])

            try:
                result_summary = {
                    "status": "completed",
                    "message_count": len(deep_messages),
                }
                serialized_result = json.dumps(result_summary)
            except (TypeError, ValueError):
                serialized_result = json.dumps({"status": "completed"})

            # Convert to safe AIMessage summaries for checkpoint serialization
            safe_messages = []
            for msg in deep_messages:
                try:
                    if hasattr(msg, "content") and msg.content:
                        safe_messages.append(AIMessage(content=str(msg.content)))
                except Exception:
                    continue

            if not safe_messages:
                safe_messages = [AIMessage(content="Deep Interpreter analysis completed.")]

            return {
                "deep_agent_result": serialized_result,
                "messages": safe_messages,
            }
        except Exception as e:
            if self.is_debug:
                print(f"Error invoking Deep Agent: {e}")
            raise


__all__ = ["DeepInterpreterWrapperAgent"]

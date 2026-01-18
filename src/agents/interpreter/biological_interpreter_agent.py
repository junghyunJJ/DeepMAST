"""Biological Interpreter Agent - Deep Agent for CCI interpretation.

This agent interprets pre-computed Cell-Cell Interaction (CCI) analysis results
and generates comprehensive HTML reports with biological insights.

Supports dual-mode workflow:
- Mode A (cluster_to_celltype): User provides interest_clusters, agent finds celltypes
- Mode B (celltype_to_cluster): User provides interest_celltypes, agent finds clusters

Deep Agent features:
- Strategic planning with hypothesis generation
- Iterative refinement with quality reflection
- Literature-based evidence gathering
- Cross-part synthesis for coherent narrative
"""

import os
from datetime import datetime
from typing import Any, ClassVar, Literal, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from src.base import BaseAgent
from src.agents.interpreter.biological_interpreter_state import (
    BiologicalInterpreterState,
    DEFAULT_WEIGHT_CONFIG,
)


class BiologicalInterpreterConfig(BaseModel):
    """Configuration for Biological Interpreter analysis.

    This Pydantic model validates and documents the configuration options
    that users can review and modify via the config_collection HITL node.
    """

    results_dir: str = Field(
        default="res/",
        description="Directory containing pre-computed analysis results"
    )
    adata_path: Optional[str] = Field(
        default=None,
        description="Path to normalized adata file (n_*adata.h5ad)"
    )
    organism: Literal["human", "mouse"] = Field(
        default="human",
        description="Organism for pathway databases"
    )
    cluster_key: str = Field(
        default="celltype_niche",
        description="Cluster column name in adata.obs"
    )
    force_regenerate: bool = Field(
        default=False,
        description="Force regeneration of all analyses"
    )
    skip_existing: bool = Field(
        default=True,
        description="Skip analyses if output files exist"
    )


class BiologicalInterpreterAgent(BaseAgent):
    """Deep Agent for biological interpretation of CCI analysis results.

    This agent follows a sequential workflow:
    1. Load pre-computed results
    2. Get user targets (HITL)
    3. Strategic planning
    4. Part 1 interpretation (5 analyses)
    5. Part 2 interpretation (4 analyses with factor/LR selection)
    6. Part 3 interpretation (spatial L-R visualization)
    7. Cross-part synthesis
    8. Literature search for evidence
    9. Quality reflection (with refinement loop)
    10. HTML report generation
    """

    NODE_NAMES: ClassVar[dict[str, str]] = {
        # Config validation nodes (before load_results)
        "CHECK_CONFIG": "check_config",
        "CONFIG_COLLECTION": "config_collection",
        "CONFIG_VALIDATION": "config_validation",

        # Foundation nodes
        "LOAD_RESULTS": "load_results",
        "GET_USER_TARGETS": "get_user_targets",
        "DETERMINE_MODE": "determine_analysis_mode",
        "STRATEGIC_PLANNING": "strategic_planning",

        # Part 1 nodes
        "INTERP_SPATIAL": "interp_spatial",
        "INTERP_CELLTYPE": "interp_celltype",
        "INTERP_NHOOD": "interp_nhood",
        "INTERP_DECOUPLER": "interp_decoupler",
        "INTERP_MISTY": "interp_misty",
        "PART1_SYNTHESIS": "part1_synthesis",
        "AUTO_SELECT_TARGETS": "auto_select_targets",

        # Part 2 nodes
        "INTERP_MORANS": "interp_liana_moransR",
        "INTERP_NMF": "interp_nmf_factors",
        "INTERP_PATHWAY_FACTOR": "interp_pathway_factor",
        "PREPARE_CELLTYPES": "prepare_celltypes_for_ctsvg",
        "INTERP_CTSVG": "interp_ctsvg",

        # Part 3 nodes
        "INTERP_SPATIAL_LR": "interp_spatial_lr",
        "INTERP_LR_SUMMARY": "interp_lr_summary",

        # Deep Agent nodes
        "CROSS_PART_SYNTHESIS": "cross_part_synthesis",
        "LITERATURE_SEARCH": "literature_search",
        "QUALITY_REFLECTION": "quality_reflection",
        "TARGETED_REFINEMENT": "targeted_refinement",

        # Output nodes
        "GENERATE_REPORT": "generate_html_report",
    }

    def __init__(
        self,
        model: BaseChatModel,
        state_schema: Any = BiologicalInterpreterState,
        config_schema: Any | None = None,
        input_schema: Any | None = None,
        output_schema: Any | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
        max_retry_attempts: int = 2,
        agent_name: str | None = None,
        is_debug: bool = True,
    ) -> None:
        super().__init__(
            model=model,
            state_schema=state_schema,
            config_schema=config_schema,
            input_schema=input_schema,
            output_schema=output_schema,
            checkpointer=checkpointer,
            store=store,
            max_retry_attempts=max_retry_attempts,
            agent_name=agent_name or "BiologicalInterpreterAgent",
            is_debug=is_debug,
        )

    # =========================================================================
    # GRAPH INITIALIZATION
    # =========================================================================

    def init_nodes(self, graph: StateGraph):
        """Initialize all nodes in the graph."""

        # Config validation nodes (before load_results)
        graph.add_node(self.get_node_name("CHECK_CONFIG"), self.check_config_node)
        graph.add_node(self.get_node_name("CONFIG_COLLECTION"), self.config_collection_node)
        graph.add_node(self.get_node_name("CONFIG_VALIDATION"), self.config_validation_node)

        # Foundation nodes
        graph.add_node(self.get_node_name("LOAD_RESULTS"), self.load_results_node)
        graph.add_node(self.get_node_name("GET_USER_TARGETS"), self.get_user_targets_node)
        graph.add_node(self.get_node_name("DETERMINE_MODE"), self.determine_mode_node)
        graph.add_node(self.get_node_name("STRATEGIC_PLANNING"), self.strategic_planning_node)

        # Part 1 nodes
        graph.add_node(self.get_node_name("INTERP_SPATIAL"), self.interp_spatial_node)
        graph.add_node(self.get_node_name("INTERP_CELLTYPE"), self.interp_celltype_node)
        graph.add_node(self.get_node_name("INTERP_NHOOD"), self.interp_nhood_node)
        graph.add_node(self.get_node_name("INTERP_DECOUPLER"), self.interp_decoupler_node)
        graph.add_node(self.get_node_name("INTERP_MISTY"), self.interp_misty_node)
        graph.add_node(self.get_node_name("PART1_SYNTHESIS"), self.part1_synthesis_node)
        graph.add_node(self.get_node_name("AUTO_SELECT_TARGETS"), self.auto_select_targets_node)

        # Part 2 nodes
        graph.add_node(self.get_node_name("INTERP_MORANS"), self.interp_morans_node)
        graph.add_node(self.get_node_name("INTERP_NMF"), self.interp_nmf_node)
        graph.add_node(self.get_node_name("INTERP_PATHWAY_FACTOR"), self.interp_pathway_factor_node)
        graph.add_node(self.get_node_name("PREPARE_CELLTYPES"), self.prepare_celltypes_node)
        graph.add_node(self.get_node_name("INTERP_CTSVG"), self.interp_ctsvg_node)

        # Part 3 nodes
        graph.add_node(self.get_node_name("INTERP_SPATIAL_LR"), self.interp_spatial_lr_node)
        graph.add_node(self.get_node_name("INTERP_LR_SUMMARY"), self.interp_lr_summary_node)

        # Deep Agent nodes
        graph.add_node(self.get_node_name("CROSS_PART_SYNTHESIS"), self.cross_part_synthesis_node)
        graph.add_node(self.get_node_name("LITERATURE_SEARCH"), self.literature_search_node)
        graph.add_node(self.get_node_name("QUALITY_REFLECTION"), self.quality_reflection_node)
        graph.add_node(self.get_node_name("TARGETED_REFINEMENT"), self.targeted_refinement_node)

        # Output nodes
        graph.add_node(self.get_node_name("GENERATE_REPORT"), self.generate_report_node)

    def init_edges(self, graph: StateGraph):
        """Initialize all edges in the graph."""

        # START -> check_config
        graph.add_edge(START, self.get_node_name("CHECK_CONFIG"))

        # check_config -> conditional: config_collection (if review needed) OR config_validation (if complete)
        graph.add_conditional_edges(
            self.get_node_name("CHECK_CONFIG"),
            self.route_after_config_check,
            [
                self.get_node_name("CONFIG_COLLECTION"),
                self.get_node_name("CONFIG_VALIDATION"),
            ]
        )

        # config_collection -> config_validation
        graph.add_edge(
            self.get_node_name("CONFIG_COLLECTION"),
            self.get_node_name("CONFIG_VALIDATION")
        )

        # config_validation -> load_results
        graph.add_edge(
            self.get_node_name("CONFIG_VALIDATION"),
            self.get_node_name("LOAD_RESULTS")
        )

        # load_results -> get_user_targets (HITL)
        graph.add_edge(
            self.get_node_name("LOAD_RESULTS"),
            self.get_node_name("GET_USER_TARGETS")
        )

        # get_user_targets -> determine_mode
        graph.add_edge(
            self.get_node_name("GET_USER_TARGETS"),
            self.get_node_name("DETERMINE_MODE")
        )

        # determine_mode -> strategic_planning
        graph.add_edge(
            self.get_node_name("DETERMINE_MODE"),
            self.get_node_name("STRATEGIC_PLANNING")
        )

        # strategic_planning -> Part 1 (parallel interpretation)
        # For simplicity, we chain them sequentially. Could use Send for parallelism.
        graph.add_edge(
            self.get_node_name("STRATEGIC_PLANNING"),
            self.get_node_name("INTERP_SPATIAL")
        )

        # Part 1 chain: spatial -> celltype -> nhood -> decoupler -> misty -> synthesis
        graph.add_edge(
            self.get_node_name("INTERP_SPATIAL"),
            self.get_node_name("INTERP_CELLTYPE")
        )
        graph.add_edge(
            self.get_node_name("INTERP_CELLTYPE"),
            self.get_node_name("INTERP_NHOOD")
        )
        graph.add_edge(
            self.get_node_name("INTERP_NHOOD"),
            self.get_node_name("INTERP_DECOUPLER")
        )
        graph.add_edge(
            self.get_node_name("INTERP_DECOUPLER"),
            self.get_node_name("INTERP_MISTY")
        )
        graph.add_edge(
            self.get_node_name("INTERP_MISTY"),
            self.get_node_name("PART1_SYNTHESIS")
        )

        # part1_synthesis -> auto_select_targets
        graph.add_edge(
            self.get_node_name("PART1_SYNTHESIS"),
            self.get_node_name("AUTO_SELECT_TARGETS")
        )

        # auto_select_targets -> Part 2 (morans)
        graph.add_edge(
            self.get_node_name("AUTO_SELECT_TARGETS"),
            self.get_node_name("INTERP_MORANS")
        )

        # Part 2 chain: morans -> nmf -> pathway_factor -> prepare_celltypes -> ctsvg
        graph.add_edge(
            self.get_node_name("INTERP_MORANS"),
            self.get_node_name("INTERP_NMF")
        )
        graph.add_edge(
            self.get_node_name("INTERP_NMF"),
            self.get_node_name("INTERP_PATHWAY_FACTOR")
        )
        graph.add_edge(
            self.get_node_name("INTERP_PATHWAY_FACTOR"),
            self.get_node_name("PREPARE_CELLTYPES")
        )
        graph.add_edge(
            self.get_node_name("PREPARE_CELLTYPES"),
            self.get_node_name("INTERP_CTSVG")
        )

        # ctsvg -> Part 3 (spatial_lr)
        graph.add_edge(
            self.get_node_name("INTERP_CTSVG"),
            self.get_node_name("INTERP_SPATIAL_LR")
        )

        # Part 3 chain: spatial_lr -> lr_summary
        graph.add_edge(
            self.get_node_name("INTERP_SPATIAL_LR"),
            self.get_node_name("INTERP_LR_SUMMARY")
        )

        # lr_summary -> cross_part_synthesis
        graph.add_edge(
            self.get_node_name("INTERP_LR_SUMMARY"),
            self.get_node_name("CROSS_PART_SYNTHESIS")
        )

        # cross_part_synthesis -> literature_search
        graph.add_edge(
            self.get_node_name("CROSS_PART_SYNTHESIS"),
            self.get_node_name("LITERATURE_SEARCH")
        )

        # literature_search -> quality_reflection
        graph.add_edge(
            self.get_node_name("LITERATURE_SEARCH"),
            self.get_node_name("QUALITY_REFLECTION")
        )

        # quality_reflection -> conditional: PASS or REFINE
        graph.add_conditional_edges(
            self.get_node_name("QUALITY_REFLECTION"),
            self.route_after_reflection,
            [
                self.get_node_name("GENERATE_REPORT"),
                self.get_node_name("TARGETED_REFINEMENT"),
            ]
        )

        # targeted_refinement -> cross_part_synthesis (loop back)
        graph.add_edge(
            self.get_node_name("TARGETED_REFINEMENT"),
            self.get_node_name("CROSS_PART_SYNTHESIS")
        )

        # generate_report -> END
        graph.add_edge(self.get_node_name("GENERATE_REPORT"), END)

    # =========================================================================
    # ROUTING FUNCTIONS
    # =========================================================================

    def route_after_config_check(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> str:
        """Route after config check: to collection (if review needed) or validation (if complete)."""
        require_review = state.get("require_config_review", False)

        if require_review:
            if self.is_debug:
                print("Config review required, routing to config_collection")
            return self.get_node_name("CONFIG_COLLECTION")

        if self.is_debug:
            print("Config complete, skipping to config_validation")
        return self.get_node_name("CONFIG_VALIDATION")

    def route_after_reflection(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> str:
        """Route after quality reflection: PASS to report or REFINE."""
        reflection = state.get("reflection_result")
        refinement_count = state.get("refinement_count", 0)

        # Max 3 refinement iterations
        if refinement_count >= 3:
            if self.is_debug:
                print("Max refinement iterations reached, proceeding to report")
            return self.get_node_name("GENERATE_REPORT")

        if reflection and reflection.get("decision") == "pass":
            return self.get_node_name("GENERATE_REPORT")

        return self.get_node_name("TARGETED_REFINEMENT")

    # =========================================================================
    # CONFIG VALIDATION NODES
    # =========================================================================

    async def check_config_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Check if configuration is complete or needs user review.

        Determines whether to skip to config_validation (all required values present)
        or route to config_collection (needs user input).
        """
        results_dir = state.get("results_dir")
        adata_path = state.get("adata_path")

        # Check if results_dir exists and has files
        results_dir_valid = results_dir and os.path.isdir(results_dir)

        # Determine if review is needed
        # Review is needed if: no results_dir OR results_dir doesn't exist
        require_review = not results_dir_valid

        if self.is_debug:
            print(f"Config check: results_dir={results_dir}, valid={results_dir_valid}")
            print(f"Config check: adata_path={adata_path}")
            print(f"Config check: require_review={require_review}")

        return {
            "require_config_review": require_review,
            "messages": [
                AIMessage(content=f"Configuration check: {'review needed' if require_review else 'complete'}")
            ]
        }

    async def config_collection_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """HITL node: Display current config and get user confirmation/updates.

        Allows users to review and modify analysis configuration before proceeding.
        """
        # Get current config values with defaults
        current_config = BiologicalInterpreterConfig(
            results_dir=state.get("results_dir", "res/"),
            adata_path=state.get("adata_path"),
            organism=state.get("organism", "human"),
            cluster_key=state.get("cluster_key", "celltype_niche"),
            force_regenerate=state.get("force_regenerate", False),
            skip_existing=state.get("skip_existing", True),
        )

        # Format config for display
        prompt_message = f"""📋 **Analysis Configuration Review**

Current settings:
```
- Results Directory: {current_config.results_dir}
- AData Path: {current_config.adata_path or 'Not specified'}
- Organism: {current_config.organism}
- Cluster Key: {current_config.cluster_key}
- Force Regenerate: {current_config.force_regenerate}
- Skip Existing: {current_config.skip_existing}
```

**Options:**
1️⃣ **Proceed** - Continue with current settings
2️⃣ **Update** - Provide new configuration values

To update, provide values in this format:
```
results_dir: /path/to/results
adata_path: /path/to/n_adata.h5ad
organism: human
cluster_key: celltype_niche
force_regenerate: false
skip_existing: true
```

Please enter your choice (1/proceed or 2/update with values):"""

        user_response = interrupt(value={"message": prompt_message})

        # Parse user response
        if isinstance(user_response, dict):
            response_text = user_response.get("response", str(user_response))
        else:
            response_text = str(user_response)

        response_lower = response_text.lower().strip()

        # Check if user wants to proceed with current settings
        if response_lower in ("1", "proceed", "yes", "ok", "continue"):
            if self.is_debug:
                print("User confirmed current config settings")
            return {
                "messages": [HumanMessage(content="Proceeding with current settings")]
            }

        # Parse configuration updates
        updates = self._parse_config_updates(response_text)

        if self.is_debug:
            print(f"Config updates from user: {updates}")

        return {
            **updates,
            "messages": [HumanMessage(content=response_text)]
        }

    def _parse_config_updates(self, response: str) -> dict:
        """Parse user response to extract configuration updates."""
        updates = {}

        # Parse key: value pairs
        for line in response.split("\n"):
            line = line.strip()
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip().lower().replace(" ", "_")
                value = value.strip()

                # Map to state fields
                if key == "results_dir":
                    updates["results_dir"] = value
                elif key == "adata_path":
                    updates["adata_path"] = value if value.lower() != "none" else None
                elif key == "organism":
                    if value.lower() in ("human", "mouse"):
                        updates["organism"] = value.lower()
                elif key == "cluster_key":
                    updates["cluster_key"] = value
                elif key == "force_regenerate":
                    updates["force_regenerate"] = value.lower() in ("true", "yes", "1")
                elif key == "skip_existing":
                    updates["skip_existing"] = value.lower() in ("true", "yes", "1")

        return updates

    async def config_validation_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Validate configuration before proceeding to load_results.

        Checks:
        - results_dir exists (or can be created)
        - adata_path exists (if specified)
        - Required files are accessible
        """
        results_dir = state.get("results_dir", "res/")
        adata_path = state.get("adata_path")

        validation_errors = []
        validation_warnings = []

        # Validate results_dir
        if not results_dir:
            results_dir = "res/"

        if not os.path.isdir(results_dir):
            # Try to create if it doesn't exist
            try:
                os.makedirs(results_dir, exist_ok=True)
                validation_warnings.append(f"Created results directory: {results_dir}")
            except OSError as e:
                validation_errors.append(f"Cannot create results directory '{results_dir}': {e}")

        # Validate adata_path if specified
        if adata_path:
            if not os.path.isfile(adata_path):
                validation_errors.append(f"AData file not found: {adata_path}")
            elif not adata_path.endswith(".h5ad"):
                validation_warnings.append(f"AData file may not be in h5ad format: {adata_path}")

        # Handle validation results
        if validation_errors:
            error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in validation_errors)
            if self.is_debug:
                print(error_msg)
            raise ValueError(error_msg)

        if validation_warnings and self.is_debug:
            print("Configuration warnings:")
            for w in validation_warnings:
                print(f"  - {w}")

        if self.is_debug:
            print("Configuration validation passed")

        return {
            "config_validated": True,
            "results_dir": results_dir,  # Ensure default is set
            "messages": [
                AIMessage(content="Configuration validated successfully.")
            ]
        }

    # =========================================================================
    # FOUNDATION NODES
    # =========================================================================

    async def load_results_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Load pre-computed analysis results, generating missing ones if needed."""
        from src.agents.interpreter.nodes.load_results import (
            load_all_results,
            load_results_with_generation,
            check_missing_files,
            get_missing_files_summary,
        )

        results_dir = state.get("results_dir", "res/")
        force_regenerate = state.get("force_regenerate", False)
        skip_existing = state.get("skip_existing", True)
        adata_path = state.get("adata_path")
        organism = state.get("organism", "human")
        cluster_key = state.get("cluster_key", "celltype_niche")

        if self.is_debug:
            print("Checking for pre-computed analysis results...")
            missing = check_missing_files(results_dir)
            if missing["part1"] or missing["part2"]:
                print(f"Missing analyses detected:\n{get_missing_files_summary(results_dir)}")
            else:
                print("All analysis files found.")

        try:
            # Check if generation is needed
            if force_regenerate or not skip_existing:
                # Force regeneration mode
                if self.is_debug:
                    print("Force regeneration mode enabled. Generating analyses...")

                result = await load_results_with_generation(
                    results_dir=results_dir,
                    adata_path=adata_path,
                    force_regenerate=force_regenerate,
                    organism=organism,
                    cluster_key=cluster_key,
                )

                if result.get("generated"):
                    if self.is_debug:
                        print(f"Generated {len(result['generated'])} analyses")

                if result.get("failed"):
                    if self.is_debug:
                        print(f"Failed to generate {len(result['failed'])} analyses (skipped)")

                return {
                    "part1_results": result.get("part1_results", {}),
                    "part2_results": result.get("part2_results", {}),
                    "generated_analyses": result.get("generated", []),
                    "failed_analyses": result.get("failed", []),
                    "messages": [
                        AIMessage(content=f"Analysis results loaded. Generated: {len(result.get('generated', []))}, Skipped: {len(result.get('failed', []))}")
                    ]
                }

            # Check for missing files and generate if adata_path is provided
            missing = check_missing_files(results_dir)
            needs_generation = (
                adata_path is not None and
                (missing["part1"] or missing["part2"])
            )

            if needs_generation:
                if self.is_debug:
                    print(f"Generating missing analyses with adata_path: {adata_path}")

                result = await load_results_with_generation(
                    results_dir=results_dir,
                    adata_path=adata_path,
                    force_regenerate=False,
                    organism=organism,
                    cluster_key=cluster_key,
                )

                return {
                    "part1_results": result.get("part1_results", {}),
                    "part2_results": result.get("part2_results", {}),
                    "generated_analyses": result.get("generated", []),
                    "failed_analyses": result.get("failed", []),
                    "messages": [
                        AIMessage(content=f"Analysis results loaded. Generated: {len(result.get('generated', []))}, Skipped: {len(result.get('failed', []))}")
                    ]
                }

            # Standard load without generation
            part1_results, part2_results = await load_all_results(results_dir)

            if self.is_debug:
                print(f"Loaded Part1 results: {list(part1_results.keys())}")
                print(f"Loaded Part2 results: {list(part2_results.keys())}")

            return {
                "part1_results": part1_results,
                "part2_results": part2_results,
                "generated_analyses": [],
                "failed_analyses": [],
                "messages": [
                    AIMessage(content="Analysis results loaded successfully.")
                ]
            }
        except Exception as e:
            if self.is_debug:
                print(f"Error loading results: {e}")
            raise

    async def get_user_targets_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """HITL node: Get user's interest targets (clusters or celltypes)."""

        # Check if already provided in initial state
        if state.get("interest_clusters") or state.get("interest_celltypes"):
            if self.is_debug:
                print("User targets already provided in initial state")
            return {}

        # Otherwise, interrupt to get user input
        prompt_message = """Please specify your analysis target:

**Option A - Clusters of Interest:**
Provide cluster names/numbers to find associated cell types.
Example: "4, 17, 14" or "Cluster 4, Cluster 17"

**Option B - Cell Types of Interest:**
Provide cell type names to find associated clusters.
Example: "Invasive Tumor, Prolif Invasive Tumor"

**Optional - Research Question:**
Add any specific research focus.
Example: "Focus on hypoxia-related pathways"

Please enter your targets:"""

        user_response = interrupt(value={"message": prompt_message})

        # Parse user response
        if isinstance(user_response, dict):
            response_text = user_response.get("response", str(user_response))
        else:
            response_text = str(user_response)

        # Simple parsing logic - can be enhanced with LLM
        parsed = self._parse_user_targets(response_text)

        return {
            "interest_clusters": parsed.get("clusters"),
            "interest_celltypes": parsed.get("celltypes"),
            "research_question": parsed.get("research_question"),
            "messages": [HumanMessage(content=response_text)]
        }

    def _parse_user_targets(self, response: str) -> dict:
        """Parse user response to extract clusters, celltypes, and research question."""
        result = {
            "clusters": None,
            "celltypes": None,
            "research_question": None
        }

        response_lower = response.lower()

        # Check for cluster indicators
        cluster_keywords = ["cluster", "클러스터"]
        celltype_keywords = ["cell type", "celltype", "tumor", "invasive", "셀타입"]

        has_cluster_mention = any(kw in response_lower for kw in cluster_keywords)
        has_celltype_mention = any(kw in response_lower for kw in celltype_keywords)

        # If numbers without celltype keywords, assume clusters
        import re
        numbers = re.findall(r'\b\d+\b', response)

        if has_cluster_mention or (numbers and not has_celltype_mention):
            result["clusters"] = numbers if numbers else None
        elif has_celltype_mention:
            # Extract celltype names (comma separated or common patterns)
            celltypes = [ct.strip() for ct in response.split(",")]
            result["celltypes"] = celltypes

        # Check for research question
        if "focus" in response_lower or "관심" in response_lower:
            result["research_question"] = response

        return result

    async def determine_mode_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Determine analysis mode based on user input."""

        has_clusters = state.get("interest_clusters") is not None
        has_celltypes = state.get("interest_celltypes") is not None

        if has_clusters and has_celltypes:
            # If both provided, prioritize clusters (Mode A)
            mode = "cluster_to_celltype"
        elif has_clusters:
            mode = "cluster_to_celltype"
        elif has_celltypes:
            mode = "celltype_to_cluster"
        else:
            raise ValueError("No interest_clusters or interest_celltypes provided")

        if self.is_debug:
            print(f"Analysis mode determined: {mode}")
            if mode == "cluster_to_celltype":
                print(f"  Interest clusters: {state.get('interest_clusters')}")
            else:
                print(f"  Interest celltypes: {state.get('interest_celltypes')}")

        return {
            "analysis_mode": mode,
            "messages": [
                AIMessage(content=f"Analysis mode: {mode}")
            ]
        }

    async def strategic_planning_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Deep Agent: Strategic planning with hypothesis generation."""
        from src.agents.interpreter.nodes.strategic_planning import create_analysis_plan

        if self.is_debug:
            print("Creating strategic analysis plan...")

        plan = await create_analysis_plan(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        return {
            "analysis_plan": plan,
            "messages": [
                AIMessage(content="Strategic analysis plan created.")
            ]
        }

    # =========================================================================
    # PART 1 NODES
    # =========================================================================

    async def interp_spatial_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Interpret Part1-1: Spatial clustering analysis."""
        from src.agents.interpreter.nodes.part1_interpretation import interpret_spatial

        interpretation = await interpret_spatial(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        current_interps = state.get("part1_interpretations") or {}
        current_interps["spatial"] = interpretation

        return {"part1_interpretations": current_interps}

    async def interp_celltype_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Interpret Part1-2: Cell type composition analysis."""
        from src.agents.interpreter.nodes.part1_interpretation import interpret_celltype

        interpretation = await interpret_celltype(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        current_interps = state.get("part1_interpretations") or {}
        current_interps["celltype"] = interpretation

        return {"part1_interpretations": current_interps}

    async def interp_nhood_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Interpret Part1-3: Neighborhood enrichment analysis."""
        from src.agents.interpreter.nodes.part1_interpretation import interpret_nhood

        interpretation = await interpret_nhood(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        current_interps = state.get("part1_interpretations") or {}
        current_interps["nhood"] = interpretation

        return {"part1_interpretations": current_interps}

    async def interp_decoupler_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Interpret Part1-4: Spatial pathway enrichment (Decoupler)."""
        from src.agents.interpreter.nodes.part1_interpretation import interpret_decoupler

        interpretation = await interpret_decoupler(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        current_interps = state.get("part1_interpretations") or {}
        current_interps["decoupler"] = interpretation

        return {"part1_interpretations": current_interps}

    async def interp_misty_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Interpret Part1-5: Spatial pathway-celltype relationship (MISTy)."""
        from src.agents.interpreter.nodes.part1_interpretation import interpret_misty

        interpretation = await interpret_misty(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        current_interps = state.get("part1_interpretations") or {}
        current_interps["misty"] = interpretation

        return {"part1_interpretations": current_interps}

    async def part1_synthesis_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Synthesize Part 1 interpretations."""
        from src.agents.interpreter.nodes.part1_interpretation import synthesize_part1

        synthesis = await synthesize_part1(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        current_interps = state.get("part1_interpretations") or {}
        current_interps["synthesis"] = synthesis

        return {"part1_interpretations": current_interps}

    async def auto_select_targets_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Automatically select targets based on Part 1 analysis and mode."""
        from src.agents.interpreter.nodes.part1_interpretation import auto_select_targets

        result = await auto_select_targets(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        return result

    # =========================================================================
    # PART 2 NODES
    # =========================================================================

    async def interp_morans_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Interpret Part2-6: LIANA Moran's R analysis."""
        from src.agents.interpreter.nodes.part2_interpretation import interpret_morans

        interpretation = await interpret_morans(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        current_interps = state.get("part2_interpretations") or {}
        current_interps["morans"] = interpretation

        return {"part2_interpretations": current_interps}

    async def interp_nmf_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Interpret Part2-7: NMF factor analysis and select factor."""
        from src.agents.interpreter.nodes.part2_interpretation import interpret_nmf_and_select_factor

        result = await interpret_nmf_and_select_factor(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        current_interps = state.get("part2_interpretations") or {}
        current_interps["nmf"] = result.get("interpretation", "")

        return {
            "part2_interpretations": current_interps,
            "selected_factor": result.get("selected_factor"),
            "factor_selection_rationale": result.get("rationale"),
            "factor_reference_clusters": result.get("reference_clusters"),
        }

    async def interp_pathway_factor_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Interpret Part2-8: Pathway-factor analysis and compare with Part1."""
        from src.agents.interpreter.nodes.part2_interpretation import interpret_pathway_factor

        result = await interpret_pathway_factor(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        current_interps = state.get("part2_interpretations") or {}
        current_interps["pathway_factor"] = result.get("interpretation", "")

        return {
            "part2_interpretations": current_interps,
            "pathway_comparison": result.get("pathway_comparison"),
        }

    async def prepare_celltypes_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Prepare celltypes for ctSVG analysis based on mode."""
        mode = state.get("analysis_mode")

        if mode == "cluster_to_celltype":
            # Mode A: Use derived celltypes from Part1
            final_celltypes = state.get("selected_celltypes", [])
            source = "derived"
        else:
            # Mode B: Use user-specified celltypes
            final_celltypes = state.get("interest_celltypes", [])
            source = "user_specified"

        if self.is_debug:
            print(f"Prepared celltypes for ctSVG: {final_celltypes} (source: {source})")

        return {
            "final_celltypes_for_ctsvg": final_celltypes,
            "celltype_source": source,
        }

    async def interp_ctsvg_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Interpret Part2-9: ctSVG analysis and select L-R pairs."""
        from src.agents.interpreter.nodes.part2_interpretation import interpret_ctsvg_and_select_lr

        result = await interpret_ctsvg_and_select_lr(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        current_interps = state.get("part2_interpretations") or {}
        current_interps["ctsvg"] = result.get("interpretation", "")

        return {
            "part2_interpretations": current_interps,
            "scoring_weights": result.get("scoring_weights"),
            "selected_lr_pairs": result.get("selected_lr_pairs"),
            "lr_scores": result.get("lr_scores"),
            "lr_selection_rationale": result.get("rationale"),
        }

    # =========================================================================
    # PART 3 NODES
    # =========================================================================

    async def interp_spatial_lr_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Interpret Part3-10: Spatial L-R expression patterns."""
        from src.agents.interpreter.nodes.part3_interpretation import interpret_spatial_lr

        interpretation = await interpret_spatial_lr(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        current_interps = state.get("part3_interpretations") or {}
        current_interps["spatial_lr"] = interpretation

        return {"part3_interpretations": current_interps}

    async def interp_lr_summary_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Interpret Part3-11: L-R interaction summary."""
        from src.agents.interpreter.nodes.part3_interpretation import interpret_lr_summary

        interpretation = await interpret_lr_summary(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        current_interps = state.get("part3_interpretations") or {}
        current_interps["lr_summary"] = interpretation

        return {"part3_interpretations": current_interps}

    # =========================================================================
    # DEEP AGENT NODES
    # =========================================================================

    async def cross_part_synthesis_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Deep Agent: Cross-part synthesis for coherent narrative."""
        from src.agents.interpreter.nodes.synthesis import cross_part_synthesis

        result = await cross_part_synthesis(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        return {
            "integrated_narrative": result.get("narrative"),
            "claims": result.get("claims"),
        }

    async def literature_search_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Deep Agent: Search literature for evidence supporting claims."""
        from src.agents.interpreter.nodes.literature_search import search_for_evidence

        evidence = await search_for_evidence(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        return {"literature_evidence": evidence}

    async def quality_reflection_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Deep Agent: Quality reflection and decision to pass or refine."""
        from src.agents.interpreter.nodes.quality_reflection import reflect_on_quality

        result = await reflect_on_quality(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        return {"reflection_result": result}

    async def targeted_refinement_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Deep Agent: Targeted refinement of identified issues."""
        from src.agents.interpreter.nodes.quality_reflection import targeted_refinement

        refinement_count = state.get("refinement_count", 0)

        if self.is_debug:
            print(f"Targeted refinement iteration {refinement_count + 1}")

        result = await targeted_refinement(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        return {
            **result,
            "refinement_count": refinement_count + 1
        }

    # =========================================================================
    # OUTPUT NODES
    # =========================================================================

    async def generate_report_node(
        self, state: BiologicalInterpreterState, config: RunnableConfig
    ) -> dict:
        """Generate final HTML report and save to results_dir."""
        from src.agents.interpreter.nodes.report_generator import generate_html_report

        html = await generate_html_report(
            state=state,
            model=self.model,
            is_debug=self.is_debug
        )

        # Save HTML report to results_dir
        results_dir = state.get("results_dir")
        saved_path = None

        if results_dir and os.path.isdir(results_dir):
            # Generate filename with timestamp for uniqueness
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_filename = f"cci_interpretation_report_{timestamp}.html"
            saved_path = os.path.join(results_dir, report_filename)

            with open(saved_path, "w", encoding="utf-8") as f:
                f.write(html)

            if self.is_debug:
                print(f"HTML report saved to: {saved_path}")

        message = (
            f"HTML report generated and saved to: {saved_path}"
            if saved_path
            else "HTML report generated (no results_dir specified, not saved to file)"
        )

        return {
            "html_report": html,
            "messages": [AIMessage(content=message)],
        }

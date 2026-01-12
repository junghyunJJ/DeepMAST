"""CCI Interpreter Agent - Biological interpretation of CCI analysis results.

This agent analyzes Cell-Cell Interaction results from spatial transcriptomics
and generates comprehensive HTML reports with literature-backed interpretations.
"""

import json
import os
from pathlib import Path
from typing import Any, ClassVar, Optional

import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import create_react_agent
from langchain_mcp_adapters.client import MultiServerMCPClient
from dotenv import load_dotenv

from src.base import BaseAgent
from src.agents.interpreter.cci_interpreter_state import (
    CCIInterpreterState,
    get_initial_state,
)
from src.prompts.interpreter_prompts import (
    PART1_SYSTEM_PROMPT,
    HTML_REPORT_TEMPLATE,
    create_part1_analysis_prompt,
    create_part1_consolidation_prompt,
    create_part2_analysis_prompt,
    create_part3_analysis_prompt,
    create_literature_search_prompt,
    create_verification_prompt,
    create_report_generation_prompt,
    get_pathway_descriptions,
)

load_dotenv(override=True)


class CCIInterpreterAgent(BaseAgent):
    """Agent for biological interpretation of CCI analysis results.

    This agent follows an 8-node workflow:
    1. load_data - Read all CSVs from result directory
    2. part1_analysis - Analyze pre-CCI results (3-5 iterations)
    3. part2_analysis - Analyze CCI/NMF results
    4. part3_analysis - Analyze L-R pair visualizations
    5. literature_search - Search for supporting literature
    6. paper_download - Download papers to RAG
    7. verification - Verify interpretations using RAG
    8. report_generation - Generate HTML report
    """

    NODE_NAMES: ClassVar[dict[str, str]] = {
        "LOAD_DATA": "load_data",
        "PART1_ANALYSIS": "part1_analysis",
        "PART2_ANALYSIS": "part2_analysis",
        "PART3_ANALYSIS": "part3_analysis",
        "LITERATURE_SEARCH": "literature_search",
        "PAPER_DOWNLOAD": "paper_download",
        "VERIFICATION": "verification",
        "REPORT_GEN": "report_generation",
    }

    # Collection name for RAG storage
    RAG_COLLECTION_NAME = "CCIAgent_interpretor"

    def __init__(
        self,
        model: Any,
        state_schema: Any = CCIInterpreterState,
        checkpointer: Any = None,
        is_debug: bool = True,
        max_part1_iterations: int = 3,
        **kwargs,
    ):
        """Initialize CCI Interpreter Agent.

        Args:
            model: Language model to use
            state_schema: State schema (default: CCIInterpreterState)
            checkpointer: Optional checkpointer for state persistence
            is_debug: Enable debug mode
            max_part1_iterations: Maximum iterations for Part 1 analysis (default: 3)
            **kwargs: Additional arguments passed to BaseAgent
        """
        self.max_part1_iterations = max_part1_iterations
        self.mcp_client: Optional[MultiServerMCPClient] = None

        super().__init__(
            model=model,
            state_schema=state_schema,
            checkpointer=checkpointer or MemorySaver(),
            is_debug=is_debug,
            agent_name="CCIInterpreterAgent",
            **kwargs,
        )

    # ===== MCP Client Management =====

    async def _init_mcp_client(self) -> MultiServerMCPClient:
        """Initialize MCP client with required servers."""
        if self.mcp_client is not None:
            return self.mcp_client

        # Get paths from environment variables
        langconnect_python = os.getenv(
            "LANGCONNECT_PYTHON",
            "/Users/jungj2/Dropbox/Metadata/mcp/langconnect/.venv/bin/python"
        )
        langconnect_server = os.getenv(
            "LANGCONNECT_SERVER",
            "/Users/jungj2/Dropbox/Metadata/mcp/langconnect/mcp_server.py"
        )
        api_base_url = os.getenv("API_BASE_URL", "http://localhost:8080")

        if self.is_debug:
            print(f"[DEBUG] Initializing MCP clients...")
            print(f"  - LANGCONNECT_PYTHON: {langconnect_python}")
            print(f"  - API_BASE_URL: {api_base_url}")

        self.mcp_client = MultiServerMCPClient({
            "server-sequential-thinking": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
                "transport": "stdio",
            },
            "langconnect-rag": {
                "command": langconnect_python,
                "args": [langconnect_server],
                "env": {"API_BASE_URL": api_base_url},
                "transport": "stdio",
            },
            "biomcp": {
                "command": "uvx",
                "args": ["--from", "biomcp", "biomcp", "run"],
                "transport": "stdio",
            },
            "pubmed-download": {
                "command": "uvx",
                "args": ["--from", "pubmed-download-mcp", "pubmed-download-mcp"],
                "transport": "stdio",
            },
        })

        return self.mcp_client

    async def _get_mcp_tools(self) -> list:
        """Get tools from all MCP servers."""
        client = await self._init_mcp_client()
        tools = await client.get_tools()
        if self.is_debug:
            print(f"[DEBUG] Loaded {len(tools)} tools from MCP servers")
        return tools

    # ===== Graph Building =====

    def init_nodes(self, graph: StateGraph):
        """Initialize graph nodes."""
        graph.add_node(self.get_node_name("LOAD_DATA"), self.load_data_node)
        graph.add_node(self.get_node_name("PART1_ANALYSIS"), self.part1_analysis_node)
        graph.add_node(self.get_node_name("PART2_ANALYSIS"), self.part2_analysis_node)
        graph.add_node(self.get_node_name("PART3_ANALYSIS"), self.part3_analysis_node)
        graph.add_node(self.get_node_name("LITERATURE_SEARCH"), self.literature_search_node)
        graph.add_node(self.get_node_name("PAPER_DOWNLOAD"), self.paper_download_node)
        graph.add_node(self.get_node_name("VERIFICATION"), self.verification_node)
        graph.add_node(self.get_node_name("REPORT_GEN"), self.report_generation_node)

    def init_edges(self, graph: StateGraph):
        """Initialize graph edges."""
        # Linear workflow
        graph.add_edge(START, self.get_node_name("LOAD_DATA"))
        graph.add_edge(self.get_node_name("LOAD_DATA"), self.get_node_name("PART1_ANALYSIS"))

        # Part 1 may loop for iterations
        graph.add_conditional_edges(
            self.get_node_name("PART1_ANALYSIS"),
            self._should_continue_part1,
            {
                "continue": self.get_node_name("PART1_ANALYSIS"),
                "next": self.get_node_name("PART2_ANALYSIS"),
            }
        )

        graph.add_edge(self.get_node_name("PART2_ANALYSIS"), self.get_node_name("PART3_ANALYSIS"))
        graph.add_edge(self.get_node_name("PART3_ANALYSIS"), self.get_node_name("LITERATURE_SEARCH"))
        graph.add_edge(self.get_node_name("LITERATURE_SEARCH"), self.get_node_name("PAPER_DOWNLOAD"))
        graph.add_edge(self.get_node_name("PAPER_DOWNLOAD"), self.get_node_name("VERIFICATION"))
        graph.add_edge(self.get_node_name("VERIFICATION"), self.get_node_name("REPORT_GEN"))
        graph.add_edge(self.get_node_name("REPORT_GEN"), END)

    def _should_continue_part1(self, state: CCIInterpreterState) -> str:
        """Determine if Part 1 should continue iterating."""
        iteration_count = state.get("part1_iteration_count", 0)

        if iteration_count < self.max_part1_iterations:
            return "continue"
        return "next"

    # ===== Node Implementations =====

    async def load_data_node(
        self, state: CCIInterpreterState, config: RunnableConfig
    ) -> dict:
        """Load all CSV data from result directory."""
        if self.is_debug:
            print(f"\n{'='*60}")
            print(f"[NODE] load_data_node")
            print(f"{'='*60}")

        result_dir = Path(state["result_dir"])

        # Define CSV files to load
        csv_files = {
            "sig_clusterwithcelltyp": "sig_clusterwithcelltyp.csv",
            "res_nhood_enrichment": "res_nhood_enrichment.csv",
            "sig_pathway_decoupler": "sig_PathwayEnrich_decoupler.csv",
            "res_spatial_misty": "res_SpatialRelationship_MISTy.csv",
            "sig_liana": "sig_liana.csv",
            "res_liana_cluster_factor": "res_liana_cluster_factor.csv",
            "sig_liana_pathway_factor": "sig_liana_pathway_factor.csv",
            "interest_anno_sig_liana": "interest_anno_sig_liana.csv",
        }

        loaded_data = {}

        for key, filename in csv_files.items():
            filepath = result_dir / filename
            if filepath.exists():
                try:
                    df = pd.read_csv(filepath)
                    # Store as CSV string for state (limited rows for context)
                    if len(df) > 50:
                        loaded_data[key] = df.head(50).to_csv(index=False)
                    else:
                        loaded_data[key] = df.to_csv(index=False)

                    if self.is_debug:
                        print(f"  [LOADED] {filename}: {len(df)} rows")
                except Exception as e:
                    if self.is_debug:
                        print(f"  [ERROR] Failed to load {filename}: {e}")
                    loaded_data[key] = None
            else:
                if self.is_debug:
                    print(f"  [MISSING] {filename}")
                loaded_data[key] = None

        return {
            **loaded_data,
            "data_loaded": True,
            "messages": [
                AIMessage(content=f"Loaded data from {result_dir}. Ready for analysis.")
            ],
        }

    async def part1_analysis_node(
        self, state: CCIInterpreterState, config: RunnableConfig
    ) -> dict:
        """Analyze Part 1 results (pre-CCI) with iterative refinement."""
        iteration = state.get("part1_iteration_count", 0) + 1

        if self.is_debug:
            print(f"\n{'='*60}")
            print(f"[NODE] part1_analysis_node - Iteration {iteration}/{self.max_part1_iterations}")
            print(f"{'='*60}")

        # Get MCP tools
        tools = await self._get_mcp_tools()

        # Filter to sequential thinking tools for structured analysis
        seq_tools = [t for t in tools if "sequentialthinking" in t.name.lower()]

        # Create system prompt
        system_prompt = PART1_SYSTEM_PROMPT.format(
            pathway_descriptions=get_pathway_descriptions(),
            disease_context=state.get("disease_context", "cancer")
        )

        # Create analysis prompt
        user_prompt = create_part1_analysis_prompt(state, iteration)

        # Create ReAct agent for analysis
        agent = create_react_agent(
            model=self.model,
            tools=seq_tools if seq_tools else tools,
            prompt=system_prompt,
        )

        # Run analysis
        result = await agent.ainvoke({
            "messages": [HumanMessage(content=user_prompt)]
        })

        # Extract selection from response
        response_content = ""
        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage) and msg.content:
                response_content = msg.content
                break

        # Try to parse JSON selection from response
        selection = self._extract_json_from_response(response_content)

        # Update selections list
        current_selections = state.get("part1_selections") or []
        if selection:
            current_selections.append(selection)

        # Check if we need to consolidate
        updates = {
            "part1_iteration_count": iteration,
            "part1_selections": current_selections,
            "messages": [
                AIMessage(content=f"Part 1 Analysis Iteration {iteration} complete.\n{response_content[:500]}...")
            ],
        }

        # If this is the last iteration, consolidate
        if iteration >= self.max_part1_iterations:
            consolidated = await self._consolidate_part1_selections(current_selections, state)
            updates["final_part1_selection"] = consolidated
            updates["part1_complete"] = True
            updates["part1_interpretation"] = self._generate_part1_interpretation(consolidated, state)

            if self.is_debug:
                print(f"  [CONSOLIDATED] Final selection: {consolidated}")

        return updates

    async def _consolidate_part1_selections(
        self, selections: list[dict], state: CCIInterpreterState
    ) -> dict:
        """Consolidate multiple Part 1 iteration results."""
        if not selections:
            return {"clusters": [], "cell_types": [], "pathways": [], "reasoning": "No selections made"}

        if len(selections) == 1:
            return selections[0]

        # Use LLM to consolidate
        prompt = create_part1_consolidation_prompt(
            selections,
            state.get("disease_context", "cancer")
        )

        response = await self.model.ainvoke([HumanMessage(content=prompt)])
        consolidated = self._extract_json_from_response(response.content)

        if consolidated:
            return consolidated

        # Fallback: merge most common elements
        from collections import Counter

        all_clusters = []
        all_celltypes = []
        all_pathways = []

        for sel in selections:
            all_clusters.extend(sel.get("clusters", []))
            all_celltypes.extend(sel.get("cell_types", []))
            all_pathways.extend(sel.get("pathways", []))

        cluster_counts = Counter(all_clusters)
        celltype_counts = Counter(all_celltypes)
        pathway_counts = Counter(all_pathways)

        return {
            "clusters": [c for c, _ in cluster_counts.most_common(3)],
            "cell_types": [ct for ct, _ in celltype_counts.most_common(5)],
            "pathways": [p for p, _ in pathway_counts.most_common(4)],
            "reasoning": "Consolidated from multiple iterations based on frequency",
        }

    def _generate_part1_interpretation(self, selection: dict, state: CCIInterpreterState) -> str:
        """Generate Part 1 biological interpretation text."""
        clusters = selection.get("clusters", [])
        cell_types = selection.get("cell_types", [])
        pathways = selection.get("pathways", [])
        reasoning = selection.get("reasoning", "")

        return f"""
## Part 1 Summary: Pre-CCI Analysis

### Selected Spatial Clusters
The analysis identified **{', '.join(clusters)}** as the most biologically relevant clusters
in the {state.get('disease_context', 'cancer')} context.

### Associated Cell Types
These clusters show significant enrichment for: **{', '.join(cell_types)}**

### Key Pathways
Pathway analysis reveals activation of: **{', '.join(pathways)}**

### Biological Interpretation
{reasoning}
"""

    async def part2_analysis_node(
        self, state: CCIInterpreterState, config: RunnableConfig
    ) -> dict:
        """Analyze Part 2 results (CCI/NMF analysis)."""
        if self.is_debug:
            print(f"\n{'='*60}")
            print(f"[NODE] part2_analysis_node")
            print(f"{'='*60}")

        part1_selection = state.get("final_part1_selection") or {}

        # Get MCP tools
        tools = await self._get_mcp_tools()
        seq_tools = [t for t in tools if "sequentialthinking" in t.name.lower()]

        # Create analysis prompt
        prompt = create_part2_analysis_prompt(state, part1_selection)

        # Create agent
        agent = create_react_agent(
            model=self.model,
            tools=seq_tools if seq_tools else tools,
            prompt="You are an expert in cell-cell interaction analysis and NMF pattern discovery.",
        )

        result = await agent.ainvoke({
            "messages": [HumanMessage(content=prompt)]
        })

        # Extract response
        response_content = ""
        for msg in reversed(result.get("messages", [])):
            if isinstance(msg, AIMessage) and msg.content:
                response_content = msg.content
                break

        selection = self._extract_json_from_response(response_content)
        interpretation = self._generate_part2_interpretation(selection, part1_selection, state)

        return {
            "part2_selection": selection,
            "part2_complete": True,
            "part2_interpretation": interpretation,
            "messages": [AIMessage(content=f"Part 2 Analysis complete.\n{response_content[:500]}...")],
        }

    def _generate_part2_interpretation(
        self, selection: dict, part1_selection: dict, state: CCIInterpreterState
    ) -> str:
        """Generate Part 2 biological interpretation."""
        if not selection:
            return "Part 2 analysis pending."

        factor = selection.get("selected_factor", "N/A")
        pathways = selection.get("factor_pathways", [])
        lr_pairs = selection.get("top_lr_pairs", [])

        return f"""
## Part 2 Summary: CCI Analysis with NMF

### Selected Intercellular Pattern
**{factor}** shows the strongest association with previously identified clusters
({', '.join(part1_selection.get('clusters', []))}).

### Factor-Associated Pathways
This pattern is enriched for: **{', '.join(pathways)}**

### Top Ligand-Receptor Pairs
Key signaling interactions identified:
{chr(10).join(f'- {lr}' for lr in lr_pairs)}

### Biological Significance
These L-R pairs represent active signaling axes in the {state.get('disease_context', 'cancer')}
microenvironment, potentially mediating communication between {', '.join(part1_selection.get('cell_types', []))}.
"""

    async def part3_analysis_node(
        self, state: CCIInterpreterState, config: RunnableConfig
    ) -> dict:
        """Analyze Part 3 results (L-R pair visualizations)."""
        if self.is_debug:
            print(f"\n{'='*60}")
            print(f"[NODE] part3_analysis_node")
            print(f"{'='*60}")

        part1_selection = state.get("final_part1_selection") or {}
        part2_selection = state.get("part2_selection") or {}

        prompt = create_part3_analysis_prompt(state, part1_selection, part2_selection)

        response = await self.model.ainvoke([HumanMessage(content=prompt)])
        interpretation = response.content

        return {
            "part3_complete": True,
            "part3_interpretation": interpretation,
            "messages": [AIMessage(content="Part 3 Analysis complete.")],
        }

    async def literature_search_node(
        self, state: CCIInterpreterState, config: RunnableConfig
    ) -> dict:
        """Search for supporting literature using biomcp."""
        if self.is_debug:
            print(f"\n{'='*60}")
            print(f"[NODE] literature_search_node")
            print(f"{'='*60}")

        part1_selection = state.get("final_part1_selection") or {}
        part2_selection = state.get("part2_selection") or {}

        # Get MCP tools
        tools = await self._get_mcp_tools()
        biomcp_tools = [t for t in tools if "article" in t.name.lower() or "search" in t.name.lower()]

        prompt = create_literature_search_prompt(
            part1_selection,
            part2_selection,
            state.get("disease_context", "cancer")
        )

        # Create agent for literature search
        agent = create_react_agent(
            model=self.model,
            tools=biomcp_tools if biomcp_tools else tools,
            prompt="You are a literature research specialist. Search PubMed for relevant papers.",
        )

        result = await agent.ainvoke({
            "messages": [HumanMessage(content=prompt)]
        })

        # Extract PMIDs from response
        pmids = self._extract_pmids_from_messages(result.get("messages", []))

        if self.is_debug:
            print(f"  [FOUND] {len(pmids)} PMIDs")

        return {
            "literature_searched": True,
            "pmid_list": pmids,
            "messages": [AIMessage(content=f"Found {len(pmids)} relevant papers.")],
        }

    def _extract_pmids_from_messages(self, messages: list) -> list[str]:
        """Extract PMIDs from message content."""
        import re

        pmids = set()
        for msg in messages:
            if hasattr(msg, "content") and msg.content:
                # Find PMID patterns
                found = re.findall(r'\b(\d{7,8})\b', str(msg.content))
                pmids.update(found)

        return list(pmids)[:20]  # Limit to 20 papers

    async def paper_download_node(
        self, state: CCIInterpreterState, config: RunnableConfig
    ) -> dict:
        """Download papers and add to RAG collection."""
        if self.is_debug:
            print(f"\n{'='*60}")
            print(f"[NODE] paper_download_node")
            print(f"{'='*60}")

        pmids = state.get("pmid_list", [])

        if not pmids:
            return {
                "papers_downloaded": True,
                "messages": [AIMessage(content="No papers to download.")],
            }

        # Get MCP tools
        tools = await self._get_mcp_tools()

        # Find RAG and download tools
        rag_tools = [t for t in tools if "collection" in t.name.lower() or "document" in t.name.lower()]
        download_tools = [t for t in tools if "download" in t.name.lower()]

        combined_tools = rag_tools + download_tools

        # Create agent for paper download and RAG storage
        download_prompt = f"""Download the following papers and add them to the '{self.RAG_COLLECTION_NAME}' collection.

PMIDs to download: {pmids[:10]}  # Limit to 10 papers

Steps:
1. First check if collection '{self.RAG_COLLECTION_NAME}' exists, create if not
2. For each PMID, use download_paper tool
3. Add downloaded content to the collection using add_documents

Note: If download fails for some papers, continue with others.
"""

        agent = create_react_agent(
            model=self.model,
            tools=combined_tools if combined_tools else tools,
            prompt="You are a research assistant managing a paper collection.",
        )

        result = await agent.ainvoke({
            "messages": [HumanMessage(content=download_prompt)]
        })

        return {
            "papers_downloaded": True,
            "rag_collection_id": self.RAG_COLLECTION_NAME,
            "messages": [AIMessage(content="Papers downloaded and added to RAG.")],
        }

    async def verification_node(
        self, state: CCIInterpreterState, config: RunnableConfig
    ) -> dict:
        """Verify interpretations using RAG search."""
        if self.is_debug:
            print(f"\n{'='*60}")
            print(f"[NODE] verification_node")
            print(f"{'='*60}")

        # Get interpretations to verify
        interpretations = []
        if state.get("part1_interpretation"):
            interpretations.append(("Part 1", state["part1_interpretation"]))
        if state.get("part2_interpretation"):
            interpretations.append(("Part 2", state["part2_interpretation"]))
        if state.get("part3_interpretation"):
            interpretations.append(("Part 3", state["part3_interpretation"]))

        if not interpretations:
            return {
                "verification_complete": True,
                "messages": [AIMessage(content="No interpretations to verify.")],
            }

        # Get RAG tools
        tools = await self._get_mcp_tools()
        rag_tools = [t for t in tools if "search" in t.name.lower() or "query" in t.name.lower()]

        verified_content = []

        for part_name, interpretation in interpretations:
            prompt = create_verification_prompt(interpretation)

            agent = create_react_agent(
                model=self.model,
                tools=rag_tools if rag_tools else tools,
                prompt="You are a scientific fact-checker. Verify claims using the paper collection.",
            )

            result = await agent.ainvoke({
                "messages": [HumanMessage(content=prompt)]
            })

            # Get response
            for msg in reversed(result.get("messages", [])):
                if isinstance(msg, AIMessage) and msg.content:
                    verified_content.append(f"## {part_name} Verification\n{msg.content}")
                    break

        # Generate summary
        summary = await self._generate_summary(state, verified_content)

        return {
            "verification_complete": True,
            "summary_interpretation": summary,
            "messages": [AIMessage(content="Verification complete.")],
        }

    async def _generate_summary(
        self, state: CCIInterpreterState, verified_content: list[str]
    ) -> str:
        """Generate overall summary interpretation."""
        part1_sel = state.get("final_part1_selection") or {}
        part2_sel = state.get("part2_selection") or {}

        prompt = f"""Generate a comprehensive summary of the CCI analysis findings.

## Key Findings:

### Spatial Context
- Clusters: {part1_sel.get('clusters', [])}
- Cell Types: {part1_sel.get('cell_types', [])}

### Signaling Patterns
- Key Factor: {part2_sel.get('selected_factor', 'N/A')}
- Pathways: {part1_sel.get('pathways', [])} + {part2_sel.get('factor_pathways', [])}
- L-R Pairs: {part2_sel.get('top_lr_pairs', [])}

### Disease Context: {state.get('disease_context', 'cancer')}

### Verified Content:
{chr(10).join(verified_content)}

Provide a cohesive summary of biological implications and potential therapeutic targets.
"""

        response = await self.model.ainvoke([HumanMessage(content=prompt)])
        return response.content

    async def report_generation_node(
        self, state: CCIInterpreterState, config: RunnableConfig
    ) -> dict:
        """Generate final HTML report."""
        if self.is_debug:
            print(f"\n{'='*60}")
            print(f"[NODE] report_generation_node")
            print(f"{'='*60}")

        # Generate HTML content for each part
        part1_content = self._generate_part1_html(state)
        part2_content = self._generate_part2_html(state)
        part3_content = self._generate_part3_html(state)
        summary_content = self._generate_summary_html(state)

        # Fill template
        html_content = HTML_REPORT_TEMPLATE.format(
            disease_context=state.get("disease_context", "Cancer").title(),
            part1_content=part1_content,
            part2_content=part2_content,
            part3_content=part3_content,
            summary_content=summary_content,
        )

        # Save report
        output_dir = Path(state["output_dir"])
        output_path = output_dir / "cci_interpretation_report.html"

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        if self.is_debug:
            print(f"  [SAVED] Report saved to: {output_path}")

        # Also save JSON results
        json_path = output_dir / "cci_interpretation_results.json"
        results = {
            "part1_selection": state.get("final_part1_selection"),
            "part2_selection": state.get("part2_selection"),
            "pmids": state.get("pmid_list", []),
            "disease_context": state.get("disease_context"),
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        return {
            "report_generated": True,
            "html_report_path": str(output_path),
            "json_results_path": str(json_path),
            "messages": [AIMessage(content=f"Report generated: {output_path}")],
        }

    # ===== HTML Generation Helpers =====

    def _generate_part1_html(self, state: CCIInterpreterState) -> str:
        """Generate Part 1 HTML content."""
        result_dir = Path(state["result_dir"])

        figures = [
            ("1.spatial.png", "Figure 1: Spatial Clustering Analysis", "Spatial distribution of identified clusters"),
            ("2.celltype_heatmap_analysis.png", "Figure 2: Cell Type Composition", "Scaled median cell-type compositions within each cluster"),
            ("3.neighborhood_enrichment_squidpy.png", "Figure 3: Neighborhood Enrichment", "Spatial proximity enrichment scores between clusters"),
            ("4.spatial_enrich_decoupler.png", "Figure 4: Pathway Enrichment (Decoupler)", "PROGENy pathway enrichment per spatial cluster"),
            ("5.spatial_relation_MISTy.png", "Figure 5: Spatial Relationships (MISTy)", "Cell type - pathway spatial relationships"),
        ]

        html = "<h2>Part 1: Pre-CCI Analysis</h2>\n"

        for filename, title, caption in figures:
            img_path = result_dir / filename
            if img_path.exists():
                html += f"""
<div class="analysis-section">
    <h3>{title}</h3>
    <div class="figure-container">
        <img src="{img_path}" alt="{title}">
        <p class="figure-caption">{caption}</p>
    </div>
</div>
"""

        # Add interpretation
        interpretation = state.get("part1_interpretation", "")
        if interpretation:
            html += f"""
<div class="interpretation">
    <h4>Biological Interpretation</h4>
    {interpretation.replace(chr(10), '<br>')}
</div>
"""

        return html

    def _generate_part2_html(self, state: CCIInterpreterState) -> str:
        """Generate Part 2 HTML content."""
        result_dir = Path(state["result_dir"])

        figures = [
            ("6.liana_MoransR.png", "Figure 6: CCI Analysis (LIANA)", "Ligand-receptor pairs with Moran's R values"),
            ("7.factor_spatial_NMF.png", "Figure 7: NMF Factor Scores", "Spatial distribution of intercellular patterns"),
            ("8.pathway_factor_heatmap.png", "Figure 8: Pathway Enrichment by Factor", "Pathway enrichment for each NMF factor"),
            ("9.quadrant_analysis.png", "Figure 9: ctSVG Analysis", "Quadrant analysis of Moran's R vs Factor loading"),
        ]

        html = "<h2>Part 2: CCI Analysis with NMF</h2>\n"

        for filename, title, caption in figures:
            img_path = result_dir / filename
            if img_path.exists():
                html += f"""
<div class="analysis-section">
    <h3>{title}</h3>
    <div class="figure-container">
        <img src="{img_path}" alt="{title}">
        <p class="figure-caption">{caption}</p>
    </div>
</div>
"""

        interpretation = state.get("part2_interpretation", "")
        if interpretation:
            html += f"""
<div class="interpretation">
    <h4>Biological Interpretation</h4>
    {interpretation.replace(chr(10), '<br>')}
</div>
"""

        return html

    def _generate_part3_html(self, state: CCIInterpreterState) -> str:
        """Generate Part 3 HTML content with paginated table."""
        result_dir = Path(state["result_dir"])

        figures = [
            ("10.spatial_LR.png", "Figure 10: Spatial L-R Plots", "Spatial expression patterns of selected L-R pairs"),
            ("11.summary_LR.png", "Figure 11: L-R Interaction Summary", "Summary of ligand-receptor interactions"),
        ]

        html = "<h2>Part 3: Ligand-Receptor Pair Analysis</h2>\n"

        for filename, title, caption in figures:
            img_path = result_dir / filename
            if img_path.exists():
                html += f"""
<div class="analysis-section">
    <h3>{title}</h3>
    <div class="figure-container">
        <img src="{img_path}" alt="{title}">
        <p class="figure-caption">{caption}</p>
    </div>
</div>
"""

        # Add paginated table
        lr_table = self._generate_lr_table(state)
        html += lr_table

        interpretation = state.get("part3_interpretation", "")
        if interpretation:
            html += f"""
<div class="interpretation">
    <h4>Biological Interpretation</h4>
    {interpretation.replace(chr(10), '<br>')}
</div>
"""

        return html

    def _generate_lr_table(self, state: CCIInterpreterState) -> str:
        """Generate paginated L-R table HTML."""
        lr_data = state.get("interest_anno_sig_liana")

        if not lr_data:
            return "<p>No L-R data available.</p>"

        try:
            import io
            df = pd.read_csv(io.StringIO(lr_data))

            # Select key columns
            columns = ["liana_interaction", "ligand", "receptor", "morans", "progeny", "disease"]
            available_cols = [c for c in columns if c in df.columns]

            if not available_cols:
                available_cols = df.columns[:6].tolist()

            df_display = df[available_cols].head(20)

            # Generate table HTML
            table_html = """
<div class="analysis-section">
    <h3>Selected Ligand-Receptor Pairs</h3>
    <table id="lr-table">
        <thead>
            <tr>
"""
            for col in available_cols:
                table_html += f"                <th>{col}</th>\n"

            table_html += """            </tr>
        </thead>
        <tbody>
"""
            for _, row in df_display.iterrows():
                table_html += "            <tr>\n"
                for col in available_cols:
                    val = row[col]
                    if pd.isna(val):
                        val = "-"
                    elif isinstance(val, float):
                        val = f"{val:.4f}"
                    table_html += f"                <td>{val}</td>\n"
                table_html += "            </tr>\n"

            table_html += """        </tbody>
    </table>
    <div class="pagination">
        <button onclick="showPage(1)">1</button>
        <button onclick="showPage(2)">2</button>
        <button onclick="showPage(3)">3</button>
        <button onclick="showPage(4)">4</button>
    </div>
</div>
"""
            return table_html

        except Exception as e:
            return f"<p>Error generating table: {e}</p>"

    def _generate_summary_html(self, state: CCIInterpreterState) -> str:
        """Generate Summary HTML content."""
        summary = state.get("summary_interpretation", "")
        pmids = state.get("pmid_list", [])

        html = "<h2>Summary: Integrated Findings</h2>\n"

        if summary:
            html += f"""
<div class="summary-box">
    {summary.replace(chr(10), '<br>')}
</div>
"""

        # Add references
        if pmids:
            html += """
<div class="analysis-section">
    <h3>References</h3>
    <ul>
"""
            for pmid in pmids[:15]:
                html += f'        <li><a href="https://pubmed.ncbi.nlm.nih.gov/{pmid}/" class="reference" target="_blank">PMID: {pmid}</a></li>\n'

            html += """    </ul>
</div>
"""

        return html

    # ===== Utility Methods =====

    def _extract_json_from_response(self, content: str) -> Optional[dict]:
        """Extract JSON object from LLM response."""
        import re

        if not content:
            return None

        # Try to find JSON block
        json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find raw JSON object
        try:
            # Find first { and last }
            start = content.find('{')
            end = content.rfind('}')
            if start != -1 and end != -1:
                return json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            pass

        return None

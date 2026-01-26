"""PubMed RAG Agent - Literature search and question answering.

This agent answers biological questions using a hybrid RAG approach:
1. Search existing mast_pubmed collection (CCI-RAG)
2. LLM judges if results are sufficient
3. If insufficient: search PubMed, download papers, add to collection
4. Generate answer with sequential-thinking (inline PMID citations)

MCP Servers Used:
- CCI-RAG: Vector search in mast_pubmed collection
- biomcp: Article search (article_searcher only, NOT article_getter)
- pubmed-download: Download full-text papers
- sequential-thinking: Structured answer generation
"""

import asyncio
import os
from typing import Any, ClassVar, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field

from src.base import BaseAgent
from src.agents.pubmedrag.pubmedrag_state import (
    PubMedRAGState,
    DownloadedPaper,
    PaperMetadata,
    RAGResult,
    RelevanceJudgment,
)


# =============================================================================
# Pydantic Models for Structured LLM Output
# =============================================================================

class RelevanceJudgmentOutput(BaseModel):
    """LLM output for relevance judgment."""
    sufficient: bool = Field(description="Whether existing RAG results are sufficient to answer the query")
    reason: str = Field(description="Explanation for the judgment")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0", ge=0.0, le=1.0)


class MultiQueryOutput(BaseModel):
    """LLM output for multi-query generation."""
    queries: list[str] = Field(
        description="List of 3-5 PubMed-optimized search queries with MeSH terms and keywords",
        min_length=1,
        max_length=5
    )
    rationale: str = Field(description="Brief explanation of query strategy")


class PaperSelectionOutput(BaseModel):
    """LLM output for selecting top papers to download."""
    selected_pmids: list[str] = Field(
        description="List of top 5 most relevant PMIDs to download",
        max_length=5
    )
    selection_rationale: str = Field(description="Why these papers were selected")


class AnswerOutput(BaseModel):
    """LLM output for final answer generation."""
    answer: str = Field(description="Comprehensive answer with inline (PMID: xxxxx) citations")
    cited_pmids: list[str] = Field(description="List of PMIDs cited in the answer")
    confidence: str = Field(description="Overall confidence: high, medium, or low")


# =============================================================================
# MCP Client Manager
# =============================================================================

class MCPClientManager:
    """Manages MCP client connections as a lazy singleton.

    Usage:
        manager = MCPClientManager()
        async with manager.get_client() as client:
            tools = await client.get_tools()
    """

    _instance: Optional["MCPClientManager"] = None
    _client = None
    _config: dict = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def configure(
        self,
        cci_rag_python: str,
        cci_rag_server: str,
        cci_rag_base_url: str,
        pubmed_email: str = "",
        jina_api: str = "",
    ):
        """Configure MCP server connections."""
        self._config = {
            "server-sequential-thinking": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
                "transport": "stdio",
            },
            "CCI-RAG": {
                "command": cci_rag_python,
                "args": [cci_rag_server],
                "env": {"API_BASE_URL": cci_rag_base_url},
                "transport": "stdio",
            },
            "pubmed-download": {
                "command": "/Users/jungj2/.local/bin/uv",
                "args": [
                    "--directory",
                    "/Users/jungj2/Dropbox/Metadata/mcp/pubmed_download_mcp",
                    "run",
                    "server.py"
                ],
                "env": {
                    "PUBMED_EMAIL": pubmed_email,
                    "JINA_API": jina_api,
                },
                "transport": "stdio",
            },
            "biomcp": {
                "command": "/Users/jungj2/.local/bin/uv",
                "args": ["run", "--with", "biomcp-python", "biomcp", "run"],
                "env": {},
                "transport": "stdio",
            },
        }

    async def get_client(self):
        """Get or create MCP client (async context manager)."""
        from langchain_mcp_adapters.client import MultiServerMCPClient

        if not self._config:
            # Load from environment if not configured
            self.configure(
                cci_rag_python=os.getenv("CCI_RAG_PYTHON", "python"),
                cci_rag_server=os.getenv("CCI_RAG_SERVER", ""),
                cci_rag_base_url=os.getenv("CCI_RAG_BASE_URL", ""),
                pubmed_email=os.getenv("PUBMED_EMAIL", ""),
                jina_api=os.getenv("JINA_API", ""),
            )

        return MultiServerMCPClient(self._config)

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> Any:
        """Call a specific MCP tool.

        Args:
            server_name: Name of the MCP server (e.g., "CCI-RAG", "biomcp")
            tool_name: Name of the tool to call
            arguments: Tool arguments

        Returns:
            Tool result
        """
        async with await self.get_client() as client:
            tools = await client.get_tools()

            # Find the tool by name
            target_tool = None
            for tool in tools:
                # Tool names are typically formatted as "server_name__tool_name"
                if tool.name == f"{server_name}__{tool_name}" or tool.name == tool_name:
                    target_tool = tool
                    break

            if target_tool is None:
                raise ValueError(f"Tool '{tool_name}' not found in server '{server_name}'")

            # Invoke the tool
            result = await target_tool.ainvoke(arguments)
            return result


# =============================================================================
# PubMedRAG Agent
# =============================================================================

class PubMedRAGAgent(BaseAgent):
    """PubMed RAG Agent for literature-based question answering.

    Workflow:
    1. Search existing mast_pubmed collection
    2. LLM judges relevance (sufficient → answer, insufficient → search PubMed)
    3. Multi-query rewrite for PubMed search
    4. Search PubMed via biomcp article_searcher
    5. Download top 5 papers via pubmed-download
    6. Add to mast_pubmed collection
    7. RAG with new documents
    8. Generate answer with sequential-thinking (inline PMID citations)
    """

    NODE_NAMES: ClassVar[dict[str, str]] = {
        # RAG Phase
        "SEARCH_EXISTING_RAG": "search_existing_rag",
        "JUDGE_RELEVANCE": "judge_relevance",

        # PubMed Search Phase
        "REWRITE_QUERY": "rewrite_query",
        "SEARCH_PUBMED": "search_pubmed",
        "SELECT_PAPERS": "select_papers",
        "DOWNLOAD_PAPERS": "download_papers",

        # Collection Phase
        "ADD_TO_COLLECTION": "add_to_collection",
        "RAG_WITH_NEW_DOCS": "rag_with_new_docs",

        # Answer Generation
        "GENERATE_ANSWER": "generate_answer",
    }

    # Collection name in CCI-RAG
    COLLECTION_NAME = "mast_pubmed"

    # Maximum papers to download
    MAX_PAPERS = 5

    def __init__(
        self,
        model: BaseChatModel,
        state_schema: Any = PubMedRAGState,
        config_schema: Any | None = None,
        input_schema: Any | None = None,
        output_schema: Any | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        store: BaseStore | None = None,
        max_retry_attempts: int = 2,
        agent_name: str | None = None,
        is_debug: bool = True,
    ) -> None:
        # Initialize MCP client manager
        self.mcp_manager = MCPClientManager()

        super().__init__(
            model=model,
            state_schema=state_schema,
            config_schema=config_schema,
            input_schema=input_schema,
            output_schema=output_schema,
            checkpointer=checkpointer,
            store=store,
            max_retry_attempts=max_retry_attempts,
            agent_name=agent_name or "PubMedRAGAgent",
            is_debug=is_debug,
        )

    # =========================================================================
    # GRAPH INITIALIZATION
    # =========================================================================

    def init_nodes(self, graph: StateGraph):
        """Initialize all nodes in the graph."""
        # RAG Phase
        graph.add_node(self.get_node_name("SEARCH_EXISTING_RAG"), self.search_existing_rag_node)
        graph.add_node(self.get_node_name("JUDGE_RELEVANCE"), self.judge_relevance_node)

        # PubMed Search Phase
        graph.add_node(self.get_node_name("REWRITE_QUERY"), self.rewrite_query_node)
        graph.add_node(self.get_node_name("SEARCH_PUBMED"), self.search_pubmed_node)
        graph.add_node(self.get_node_name("SELECT_PAPERS"), self.select_papers_node)
        graph.add_node(self.get_node_name("DOWNLOAD_PAPERS"), self.download_papers_node)

        # Collection Phase
        graph.add_node(self.get_node_name("ADD_TO_COLLECTION"), self.add_to_collection_node)
        graph.add_node(self.get_node_name("RAG_WITH_NEW_DOCS"), self.rag_with_new_docs_node)

        # Answer Generation
        graph.add_node(self.get_node_name("GENERATE_ANSWER"), self.generate_answer_node)

    def init_edges(self, graph: StateGraph):
        """Initialize all edges in the graph."""
        # START → search_existing_rag
        graph.add_edge(START, self.get_node_name("SEARCH_EXISTING_RAG"))

        # search_existing_rag → judge_relevance
        graph.add_edge(
            self.get_node_name("SEARCH_EXISTING_RAG"),
            self.get_node_name("JUDGE_RELEVANCE")
        )

        # judge_relevance → conditional: sufficient or insufficient
        graph.add_conditional_edges(
            self.get_node_name("JUDGE_RELEVANCE"),
            self.route_after_judgment,
            [
                self.get_node_name("GENERATE_ANSWER"),  # sufficient
                self.get_node_name("REWRITE_QUERY"),     # insufficient
            ]
        )

        # PubMed search chain
        graph.add_edge(
            self.get_node_name("REWRITE_QUERY"),
            self.get_node_name("SEARCH_PUBMED")
        )
        graph.add_edge(
            self.get_node_name("SEARCH_PUBMED"),
            self.get_node_name("SELECT_PAPERS")
        )
        graph.add_edge(
            self.get_node_name("SELECT_PAPERS"),
            self.get_node_name("DOWNLOAD_PAPERS")
        )
        graph.add_edge(
            self.get_node_name("DOWNLOAD_PAPERS"),
            self.get_node_name("ADD_TO_COLLECTION")
        )
        graph.add_edge(
            self.get_node_name("ADD_TO_COLLECTION"),
            self.get_node_name("RAG_WITH_NEW_DOCS")
        )
        graph.add_edge(
            self.get_node_name("RAG_WITH_NEW_DOCS"),
            self.get_node_name("GENERATE_ANSWER")
        )

        # generate_answer → END
        graph.add_edge(self.get_node_name("GENERATE_ANSWER"), END)

    # =========================================================================
    # ROUTING FUNCTIONS
    # =========================================================================

    def route_after_judgment(
        self, state: PubMedRAGState, config: RunnableConfig
    ) -> str:
        """Route based on relevance judgment: sufficient → answer, insufficient → search."""
        judgment = state.get("relevance_judgment")

        if judgment and judgment.get("sufficient"):
            if self.is_debug:
                print("Existing RAG results sufficient, generating answer...")
            return self.get_node_name("GENERATE_ANSWER")

        if self.is_debug:
            print("Existing RAG results insufficient, searching PubMed...")
        return self.get_node_name("REWRITE_QUERY")

    # =========================================================================
    # RAG PHASE NODES
    # =========================================================================

    async def search_existing_rag_node(
        self, state: PubMedRAGState, config: RunnableConfig
    ) -> dict:
        """Search existing mast_pubmed collection via CCI-RAG."""
        query = state.get("query", "")

        if self.is_debug:
            print(f"Searching existing collection for: {query[:100]}...")

        try:
            # Call CCI-RAG search_documents
            result = await self.mcp_manager.call_tool(
                server_name="CCI-RAG",
                tool_name="search_documents",
                arguments={
                    "collection_id": self.COLLECTION_NAME,
                    "query": query,
                    "limit": 10,
                    "search_type": "hybrid",
                }
            )

            # Parse results
            rag_results: list[RAGResult] = []
            if isinstance(result, list):
                for item in result:
                    rag_results.append({
                        "document_id": item.get("id", ""),
                        "content": item.get("content", ""),
                        "score": item.get("score", 0.0),
                        "metadata": item.get("metadata", {}),
                    })

            if self.is_debug:
                print(f"Found {len(rag_results)} existing documents")

            return {
                "existing_rag_results": rag_results,
                "messages": [AIMessage(content=f"Found {len(rag_results)} relevant documents in existing collection.")]
            }

        except Exception as e:
            if self.is_debug:
                print(f"Error searching existing collection: {e}")

            # Graceful degradation: proceed with empty results
            return {
                "existing_rag_results": [],
                "error_message": f"Could not search existing collection: {str(e)}",
                "messages": [AIMessage(content="No existing documents found, will search PubMed.")]
            }

    async def judge_relevance_node(
        self, state: PubMedRAGState, config: RunnableConfig
    ) -> dict:
        """LLM judges if existing RAG results are sufficient."""
        query = state.get("query", "")
        rag_results = state.get("existing_rag_results", [])

        # If no results, definitely insufficient
        if not rag_results:
            return {
                "relevance_judgment": {
                    "sufficient": False,
                    "reason": "No existing documents found in collection",
                    "confidence": 1.0,
                },
                "workflow_path": "new_search_needed",
            }

        # Prepare context for LLM
        context_text = "\n\n---\n\n".join([
            f"Document {i+1} (score: {r.get('score', 0):.3f}):\n{r.get('content', '')[:1000]}..."
            for i, r in enumerate(rag_results[:5])
        ])

        prompt = f"""You are evaluating whether the following retrieved documents are SUFFICIENT to comprehensively answer a biological research question.

**Question:** {query}

**Retrieved Documents:**
{context_text}

**Evaluation Criteria:**
1. Do the documents directly address the question's main topic?
2. Is there enough detail to provide a substantive answer?
3. Are the documents from relevant, recent research?

If the documents provide good coverage of the topic, mark as sufficient.
If the documents are tangentially related, outdated, or lack depth, mark as insufficient.

Respond with your judgment."""

        # Use structured output
        structured_model = self.model.with_structured_output(RelevanceJudgmentOutput)

        try:
            judgment_output = await structured_model.ainvoke([HumanMessage(content=prompt)])

            judgment: RelevanceJudgment = {
                "sufficient": judgment_output.sufficient,
                "reason": judgment_output.reason,
                "confidence": judgment_output.confidence,
            }

            workflow_path = "existing_sufficient" if judgment["sufficient"] else "new_search_needed"

            if self.is_debug:
                print(f"Relevance judgment: sufficient={judgment['sufficient']}, reason={judgment['reason'][:100]}")

            return {
                "relevance_judgment": judgment,
                "workflow_path": workflow_path,
                "messages": [AIMessage(content=f"Relevance judgment: {'sufficient' if judgment['sufficient'] else 'insufficient'}. {judgment['reason']}")]
            }

        except Exception as e:
            if self.is_debug:
                print(f"Error in relevance judgment: {e}")

            # Default to searching PubMed on error
            return {
                "relevance_judgment": {
                    "sufficient": False,
                    "reason": f"Could not evaluate relevance: {str(e)}",
                    "confidence": 0.0,
                },
                "workflow_path": "new_search_needed",
            }

    # =========================================================================
    # PUBMED SEARCH PHASE NODES
    # =========================================================================

    async def rewrite_query_node(
        self, state: PubMedRAGState, config: RunnableConfig
    ) -> dict:
        """LLM rewrites query into multiple PubMed-optimized queries."""
        query = state.get("query", "")

        prompt = f"""You are a biomedical literature search expert. Convert the following research question into 3-5 optimized PubMed search queries.

**Original Question:** {query}

**Guidelines:**
1. Use MeSH terms where appropriate (e.g., "Neoplasms"[MeSH])
2. Include synonyms and related terms
3. Vary query specificity (broad to narrow)
4. Focus on recent, high-impact literature
5. Use Boolean operators (AND, OR, NOT)

Example queries:
- "EGFR"[MeSH] AND "lung neoplasms"[MeSH] AND "signal transduction"
- EGFR signaling pathway lung cancer
- "epidermal growth factor receptor" AND tumor AND therapy

Generate optimized queries for the given question."""

        structured_model = self.model.with_structured_output(MultiQueryOutput)

        try:
            output = await structured_model.ainvoke([HumanMessage(content=prompt)])

            if self.is_debug:
                print(f"Generated {len(output.queries)} PubMed queries")
                for i, q in enumerate(output.queries):
                    print(f"  Query {i+1}: {q[:80]}...")

            return {
                "rewritten_queries": output.queries,
                "messages": [AIMessage(content=f"Generated {len(output.queries)} optimized PubMed queries.")]
            }

        except Exception as e:
            if self.is_debug:
                print(f"Error in query rewrite: {e}")

            # Fallback: use original query
            return {
                "rewritten_queries": [query],
                "messages": [AIMessage(content="Using original query for PubMed search.")]
            }

    async def search_pubmed_node(
        self, state: PubMedRAGState, config: RunnableConfig
    ) -> dict:
        """Search PubMed via biomcp article_searcher (parallel queries)."""
        queries = state.get("rewritten_queries", [])

        if not queries:
            return {
                "search_results": [],
                "error_message": "No queries available for PubMed search",
            }

        if self.is_debug:
            print(f"Searching PubMed with {len(queries)} queries...")

        all_results: list[PaperMetadata] = []
        seen_pmids: set[str] = set()

        # Search with each query
        for query in queries:
            try:
                result = await self.mcp_manager.call_tool(
                    server_name="biomcp",
                    tool_name="article_searcher",
                    arguments={
                        "query": query,
                        "max_results": 10,
                    }
                )

                # Parse results
                if isinstance(result, list):
                    for item in result:
                        pmid = str(item.get("pmid", ""))
                        if pmid and pmid not in seen_pmids:
                            seen_pmids.add(pmid)
                            all_results.append({
                                "pmid": pmid,
                                "title": item.get("title", ""),
                                "authors": item.get("authors", ""),
                                "journal": item.get("journal", ""),
                                "year": item.get("year", ""),
                                "abstract": item.get("abstract", ""),
                            })

            except Exception as e:
                if self.is_debug:
                    print(f"Error searching with query '{query[:50]}...': {e}")
                continue

        if self.is_debug:
            print(f"Found {len(all_results)} unique papers from PubMed")

        return {
            "search_results": all_results,
            "messages": [AIMessage(content=f"Found {len(all_results)} papers from PubMed search.")]
        }

    async def select_papers_node(
        self, state: PubMedRAGState, config: RunnableConfig
    ) -> dict:
        """LLM selects top 5 most relevant papers to download."""
        query = state.get("query", "")
        search_results = state.get("search_results", [])

        if not search_results:
            return {
                "selected_pmids": [],
                "error_message": "No search results to select from",
            }

        # If 5 or fewer results, select all
        if len(search_results) <= self.MAX_PAPERS:
            pmids = [r["pmid"] for r in search_results]
            return {
                "selected_pmids": pmids,
                "messages": [AIMessage(content=f"Selected all {len(pmids)} papers for download.")]
            }

        # Format papers for LLM
        papers_text = "\n\n".join([
            f"PMID: {r['pmid']}\nTitle: {r['title']}\nJournal: {r.get('journal', 'N/A')} ({r.get('year', 'N/A')})\nAbstract: {r.get('abstract', 'N/A')[:500]}..."
            for r in search_results[:20]  # Limit to top 20 for context
        ])

        prompt = f"""You are selecting the most relevant papers for a research question.

**Research Question:** {query}

**Available Papers:**
{papers_text}

Select the TOP 5 most relevant papers that will best answer the research question.
Consider:
1. Direct relevance to the question
2. Recency (prefer recent papers)
3. Impact (prefer high-impact journals)
4. Complementary coverage (avoid redundant papers)

Return the PMIDs of your top 5 selections."""

        structured_model = self.model.with_structured_output(PaperSelectionOutput)

        try:
            output = await structured_model.ainvoke([HumanMessage(content=prompt)])

            # Validate PMIDs exist in search results
            valid_pmids = {r["pmid"] for r in search_results}
            selected = [p for p in output.selected_pmids if p in valid_pmids][:self.MAX_PAPERS]

            if self.is_debug:
                print(f"Selected {len(selected)} papers: {selected}")

            return {
                "selected_pmids": selected,
                "messages": [AIMessage(content=f"Selected {len(selected)} papers for download.")]
            }

        except Exception as e:
            if self.is_debug:
                print(f"Error in paper selection: {e}")

            # Fallback: select first MAX_PAPERS
            fallback_pmids = [r["pmid"] for r in search_results[:self.MAX_PAPERS]]
            return {
                "selected_pmids": fallback_pmids,
                "messages": [AIMessage(content=f"Selected first {len(fallback_pmids)} papers for download.")]
            }

    async def download_papers_node(
        self, state: PubMedRAGState, config: RunnableConfig
    ) -> dict:
        """Download selected papers via pubmed-download MCP."""
        selected_pmids = state.get("selected_pmids", [])

        if not selected_pmids:
            return {
                "downloaded_papers": [],
                "failed_downloads": [],
                "error_message": "No PMIDs selected for download",
            }

        if self.is_debug:
            print(f"Downloading {len(selected_pmids)} papers...")

        downloaded: list[DownloadedPaper] = []
        failed: list[str] = []

        # Find metadata for selected PMIDs
        search_results = state.get("search_results", [])
        pmid_to_metadata = {r["pmid"]: r for r in search_results}

        # Download each paper
        for pmid in selected_pmids:
            try:
                result = await self.mcp_manager.call_tool(
                    server_name="pubmed-download",
                    tool_name="download_paper",
                    arguments={"pmid": pmid}
                )

                # Extract content from result
                content = ""
                if isinstance(result, dict):
                    content = result.get("content", result.get("text", str(result)))
                elif isinstance(result, str):
                    content = result

                if content:
                    metadata = pmid_to_metadata.get(pmid, {"pmid": pmid, "title": ""})
                    downloaded.append({
                        "pmid": pmid,
                        "title": metadata.get("title", ""),
                        "content": content,
                        "metadata": metadata,
                    })
                    if self.is_debug:
                        print(f"  Downloaded PMID:{pmid} ({len(content)} chars)")
                else:
                    failed.append(pmid)
                    if self.is_debug:
                        print(f"  Failed PMID:{pmid} (empty content)")

            except Exception as e:
                failed.append(pmid)
                if self.is_debug:
                    print(f"  Failed PMID:{pmid}: {e}")

        # Graceful degradation message
        message = f"Downloaded {len(downloaded)} papers."
        if failed:
            message += f" Failed to download {len(failed)} papers: {', '.join(failed)}"

        return {
            "downloaded_papers": downloaded,
            "failed_downloads": failed,
            "messages": [AIMessage(content=message)]
        }

    # =========================================================================
    # COLLECTION PHASE NODES
    # =========================================================================

    async def add_to_collection_node(
        self, state: PubMedRAGState, config: RunnableConfig
    ) -> dict:
        """Add downloaded papers to mast_pubmed collection."""
        downloaded_papers = state.get("downloaded_papers", [])

        if not downloaded_papers:
            return {
                "added_document_ids": [],
                "error_message": "No papers to add to collection",
            }

        if self.is_debug:
            print(f"Adding {len(downloaded_papers)} papers to collection...")

        added_ids: list[str] = []

        for paper in downloaded_papers:
            try:
                # Format document with metadata
                doc_content = f"""# {paper['title']}

**PMID:** {paper['pmid']}
**Authors:** {paper.get('metadata', {}).get('authors', 'N/A')}
**Journal:** {paper.get('metadata', {}).get('journal', 'N/A')} ({paper.get('metadata', {}).get('year', 'N/A')})

---

{paper['content']}
"""

                result = await self.mcp_manager.call_tool(
                    server_name="CCI-RAG",
                    tool_name="add_documents",
                    arguments={
                        "collection_id": self.COLLECTION_NAME,
                        "text": doc_content,
                        "metadata": {
                            "pmid": paper["pmid"],
                            "title": paper["title"],
                            "source": "pubmed",
                        }
                    }
                )

                # Extract document ID from result
                doc_id = paper["pmid"]  # Use PMID as fallback ID
                if isinstance(result, dict) and "id" in result:
                    doc_id = result["id"]

                added_ids.append(doc_id)
                if self.is_debug:
                    print(f"  Added PMID:{paper['pmid']} to collection")

            except Exception as e:
                if self.is_debug:
                    print(f"  Failed to add PMID:{paper['pmid']}: {e}")

        return {
            "added_document_ids": added_ids,
            "messages": [AIMessage(content=f"Added {len(added_ids)} papers to collection.")]
        }

    async def rag_with_new_docs_node(
        self, state: PubMedRAGState, config: RunnableConfig
    ) -> dict:
        """Perform RAG search with newly added documents."""
        query = state.get("query", "")

        if self.is_debug:
            print("Performing RAG search with updated collection...")

        try:
            result = await self.mcp_manager.call_tool(
                server_name="CCI-RAG",
                tool_name="search_documents",
                arguments={
                    "collection_id": self.COLLECTION_NAME,
                    "query": query,
                    "limit": 15,  # More results since we added new docs
                    "search_type": "hybrid",
                }
            )

            rag_results: list[RAGResult] = []
            if isinstance(result, list):
                for item in result:
                    rag_results.append({
                        "document_id": item.get("id", ""),
                        "content": item.get("content", ""),
                        "score": item.get("score", 0.0),
                        "metadata": item.get("metadata", {}),
                    })

            if self.is_debug:
                print(f"RAG search returned {len(rag_results)} documents")

            return {
                "final_rag_results": rag_results,
                "messages": [AIMessage(content=f"RAG search found {len(rag_results)} relevant documents.")]
            }

        except Exception as e:
            if self.is_debug:
                print(f"Error in RAG search: {e}")

            # Use downloaded papers directly as fallback
            downloaded = state.get("downloaded_papers", [])
            fallback_results = [
                {
                    "document_id": p["pmid"],
                    "content": p["content"],
                    "score": 1.0,
                    "metadata": p.get("metadata", {}),
                }
                for p in downloaded
            ]

            return {
                "final_rag_results": fallback_results,
                "error_message": f"RAG search failed, using downloaded papers directly: {str(e)}",
            }

    # =========================================================================
    # ANSWER GENERATION NODE
    # =========================================================================

    async def generate_answer_node(
        self, state: PubMedRAGState, config: RunnableConfig
    ) -> dict:
        """Generate final answer using sequential-thinking with inline PMID citations."""
        query = state.get("query", "")
        workflow_path = state.get("workflow_path", "")

        # Get RAG results based on workflow path
        if workflow_path == "existing_sufficient":
            rag_results = state.get("existing_rag_results", [])
        else:
            rag_results = state.get("final_rag_results", [])
            if not rag_results:
                rag_results = state.get("existing_rag_results", [])

        # Build context from RAG results
        context_parts = []
        pmid_map = {}  # Track PMIDs for citation

        for i, result in enumerate(rag_results[:10]):
            metadata = result.get("metadata", {})
            pmid = metadata.get("pmid", f"doc_{i}")
            pmid_map[f"doc_{i}"] = pmid

            context_parts.append(f"""
[Document {i+1}] PMID: {pmid}
{result.get('content', '')[:2000]}...
""")

        context_text = "\n---\n".join(context_parts)

        # Prepare prompt for sequential-thinking
        thinking_prompt = f"""You are a biomedical research assistant answering a question using provided literature.

**Question:** {query}

**Retrieved Literature:**
{context_text}

**Instructions:**
1. Think step by step about how to answer the question
2. Synthesize information from multiple sources
3. Include inline citations using format: (PMID: xxxxx)
4. Every factual claim must have a citation
5. Acknowledge limitations or gaps in the literature
6. Provide a comprehensive, scientifically accurate answer

Generate your answer with proper PMID citations inline."""

        if self.is_debug:
            print("Generating answer with sequential-thinking...")

        try:
            # Use sequential-thinking for structured reasoning
            thinking_result = await self.mcp_manager.call_tool(
                server_name="server-sequential-thinking",
                tool_name="sequentialthinking",
                arguments={
                    "thought": thinking_prompt,
                    "thoughtNumber": 1,
                    "totalThoughts": 3,
                    "nextThoughtNeeded": True,
                }
            )

            # Continue thinking process
            final_thoughts = [thinking_result]
            for i in range(2, 4):
                next_result = await self.mcp_manager.call_tool(
                    server_name="server-sequential-thinking",
                    tool_name="sequentialthinking",
                    arguments={
                        "thought": f"Continue reasoning about: {query}",
                        "thoughtNumber": i,
                        "totalThoughts": 3,
                        "nextThoughtNeeded": i < 3,
                    }
                )
                final_thoughts.append(next_result)

            # Combine thoughts into final answer
            combined_thoughts = "\n\n".join([
                str(t.get("thought", t) if isinstance(t, dict) else t)
                for t in final_thoughts
            ])

        except Exception as e:
            if self.is_debug:
                print(f"Sequential thinking error: {e}, falling back to direct generation")
            combined_thoughts = ""

        # Generate final structured answer
        final_prompt = f"""Based on the literature and analysis, provide a comprehensive answer to:

**Question:** {query}

**Literature Context:**
{context_text}

{f"**Analysis Notes:** {combined_thoughts}" if combined_thoughts else ""}

**Format Requirements:**
- Comprehensive answer addressing all aspects of the question
- Every factual claim must have inline citation: (PMID: xxxxx)
- Scientific accuracy and precision
- Acknowledge any limitations in the available evidence
- Conclude with a brief summary

Generate your final answer now."""

        structured_model = self.model.with_structured_output(AnswerOutput)

        try:
            output = await structured_model.ainvoke([HumanMessage(content=final_prompt)])

            if self.is_debug:
                print(f"Generated answer with {len(output.cited_pmids)} citations")

            return {
                "answer": output.answer,
                "cited_pmids": output.cited_pmids,
                "messages": [AIMessage(content=output.answer)]
            }

        except Exception as e:
            if self.is_debug:
                print(f"Error generating structured answer: {e}")

            # Fallback to unstructured generation
            fallback_response = await self.model.ainvoke([HumanMessage(content=final_prompt)])

            return {
                "answer": fallback_response.content,
                "cited_pmids": list(pmid_map.values()),
                "error_message": f"Used fallback answer generation: {str(e)}",
                "messages": [AIMessage(content=fallback_response.content)]
            }

"""State schema for PubMedRAG Agent.

This module defines the state structure for the PubMed RAG agent
which performs literature search, retrieval, and question answering.
"""

from typing import Annotated, Literal, Optional, TypedDict
from langgraph.graph.message import add_messages


class PaperMetadata(TypedDict):
    """Metadata for a downloaded paper."""
    pmid: str
    title: str
    authors: Optional[str]
    journal: Optional[str]
    year: Optional[str]
    abstract: Optional[str]


class DownloadedPaper(TypedDict):
    """A downloaded paper with full text content."""
    pmid: str
    title: str
    content: str  # Full text markdown
    metadata: PaperMetadata


class RAGResult(TypedDict):
    """A single RAG search result."""
    document_id: str
    content: str
    score: float
    metadata: Optional[dict]


class RelevanceJudgment(TypedDict):
    """LLM's judgment on RAG result relevance."""
    sufficient: bool
    reason: str
    confidence: float  # 0.0 - 1.0


class PubMedRAGState(TypedDict):
    """State schema for PubMedRAG Agent.

    Workflow:
    1. search_existing_rag: Search existing mast_pubmed collection
    2. judge_relevance: LLM judges if results are sufficient
    3. (if insufficient) rewrite_query: LLM generates multiple PubMed queries
    4. (if insufficient) search_pubmed: Search PubMed via biomcp article_searcher
    5. (if insufficient) download_papers: Download top 5 papers
    6. (if insufficient) add_to_collection: Add to mast_pubmed collection
    7. (if insufficient) rag_with_new_docs: RAG with newly added documents
    8. generate_answer: Generate final answer with sequential-thinking
    """

    # === Message History ===
    messages: Annotated[list, add_messages]

    # === Input ===
    query: str  # User's biological question

    # === RAG Phase (Existing Collection) ===
    existing_rag_results: Optional[list[RAGResult]]
    relevance_judgment: Optional[RelevanceJudgment]

    # === Query Rewrite Phase (Multi-Query) ===
    rewritten_queries: Optional[list[str]]  # Multiple PubMed-optimized queries

    # === PubMed Search Phase ===
    search_results: Optional[list[PaperMetadata]]  # biomcp article_searcher results
    selected_pmids: Optional[list[str]]  # Top 5 selected PMIDs for download

    # === Download Phase ===
    downloaded_papers: Optional[list[DownloadedPaper]]
    failed_downloads: Optional[list[str]]  # Failed PMIDs (graceful degradation)

    # === Collection Phase ===
    added_document_ids: Optional[list[str]]  # Document IDs added to collection

    # === Final RAG Phase (After Adding New Docs) ===
    final_rag_results: Optional[list[RAGResult]]

    # === Output ===
    answer: Optional[str]  # Final answer with inline PMID citations
    cited_pmids: Optional[list[str]]  # PMIDs cited in the answer

    # === Workflow Control ===
    workflow_path: Optional[Literal["existing_sufficient", "new_search_needed"]]
    error_message: Optional[str]  # For graceful degradation reporting

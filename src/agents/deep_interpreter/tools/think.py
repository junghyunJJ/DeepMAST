"""Think tool for Deep Interpreter Agent.

This tool provides quality validation using the reflection-tool MCP server
with iteration tracking for the quality validation loop.
"""

import re

from langchain_core.tools import tool

from src.agents.deep_interpreter.tools.mcp_clients import (
    invoke_biomedical_thinking,
    invoke_reflection_tool,
    run_async,
)


@tool
def think_tool(
    reflection: str,
    iteration: int = 1,
    max_iterations: int = 3,
    score_threshold: float = 0.7,
) -> dict:
    """Quality validation using reflection-tool MCP server.

    This tool uses the reflection-tool's think_tool for structured quality
    validation with iteration tracking. Use this to validate interpretation
    quality and determine if refinement is needed.

    Args:
        reflection: The reflection prompt for quality evaluation. Should include:
            - The interpretation text to evaluate
            - Criteria for evaluation (statistics, references, mechanism, specificity)
            - Format for scoring output
        iteration: Current iteration number (1-based)
        max_iterations: Maximum allowed iterations (default 3)
        score_threshold: Minimum score to pass (default 0.7)

    Returns:
        Dictionary with:
        - success: Whether the tool invocation succeeded
        - result: The reflection result text
        - iteration: Current iteration number
        - should_continue: Whether to continue refining (based on score and iterations)
        - parsed_score: Extracted score if found in result
    """
    # Build enhanced reflection with iteration context
    enhanced_reflection = f"""## Quality Validation (Iteration {iteration}/{max_iterations})

{reflection}

## Evaluation Output Format

Please evaluate and provide:
1. **Overall Score** (0.0-1.0): Based on statistics, references, mechanism, specificity
2. **Passed** (yes/no): Score >= {score_threshold}?
3. **Specific Feedback**: What needs improvement?
4. **Recommendation**: Continue refinement or accept current version?

Current iteration: {iteration}
Max iterations: {max_iterations}
Score threshold: {score_threshold}
"""

    try:
        result = run_async(invoke_reflection_tool(enhanced_reflection), timeout=60)

        # Parse score from result if available
        parsed_score = None
        if result.get("success") and result.get("result"):
            result_text = result["result"].lower()
            score_match = re.search(r'overall\s+score[:\s]*(\d+\.?\d*)', result_text)
            if not score_match:
                # Fallback: match generic "score" pattern
                score_match = re.search(r'score[:\s]*(\d+\.?\d*)', result_text)
            if score_match:
                parsed_score = min(float(score_match.group(1)), 1.0)

        # Determine if should continue
        should_continue = False
        if iteration < max_iterations:
            if parsed_score is not None and parsed_score < score_threshold:
                should_continue = True
            elif "no" in result.get("result", "").lower() and "passed" in result.get("result", "").lower():
                should_continue = True

        return {
            "success": result.get("success", False),
            "result": result.get("result"),
            "error": result.get("error"),
            "iteration": iteration,
            "max_iterations": max_iterations,
            "score_threshold": score_threshold,
            "parsed_score": parsed_score,
            "should_continue": should_continue,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "result": None,
            "iteration": iteration,
            "max_iterations": max_iterations,
            "score_threshold": score_threshold,
            "parsed_score": None,
            "should_continue": False,
        }


@tool
def analyze_research_question(
    question: str,
    context: str = "",
    analysis_type: str = "auto",
) -> dict:
    """Decompose a biomedical research question into structured sub-questions with entity extraction.

    This tool analyzes a complex biomedical question and:
    1. Extracts entities (genes, pathways, cell types, diseases)
    2. Classifies question type (cci_mechanism, spatial_pattern, pathway, etc.)
    3. Decomposes into focused sub-questions for targeted literature search
    4. Suggests search strategy and estimates search rounds

    Use this BEFORE literature search to structure your query approach.

    Args:
        question: The biomedical research question to analyze.
            Example: "Does TGFB1-TGFBR2 signaling drive EMT in breast cancer fibroblasts?"
        context: Optional context from analysis data (cell types, pathways found).
        analysis_type: Question type hint. "spatial_pattern", "cci_mechanism",
            "pathway", "gene_function", or "auto" (default).

    Returns:
        Dictionary with:
        - question_type: Classified question type
        - complexity: "simple", "moderate", or "multi_hop"
        - sub_questions: List of focused sub-questions with priority and search_focus
        - entities: Extracted genes, pathways, celltypes, diseases
        - suggested_strategy: Recommended search approach
        - estimated_search_rounds: Expected number of search iterations
    """
    arguments = {
        "research_question": question,
        "context": context,
        "analysis_type": analysis_type,
    }

    try:
        result = run_async(
            invoke_biomedical_thinking("analyze_and_decompose", arguments),
            timeout=30
        )

        if result.get("success"):
            return result["result"]
        return {"error": result.get("error", "Unknown error"), "success": False}

    except Exception as e:
        return {"error": str(e), "success": False}


@tool
def expand_search_entities(
    genes: list[str] | None = None,
    pathways: list[str] | None = None,
    celltypes: list[str] | None = None,
    diseases: list[str] | None = None,
    expand_aliases: bool = True,
    expand_mesh: bool = True,
    expand_related: bool = False,
) -> dict:
    """Expand biomedical entities with MeSH terms, aliases, and subtypes for PubMed search.

    Takes entities extracted from analyze_research_question (or manually specified)
    and expands them with:
    - Gene aliases (e.g., TGFB1 → TGF-beta-1, TGF-β1)
    - MeSH term mappings (e.g., TGFB1 → "Transforming Growth Factor beta1"[mh])
    - Cell type subtypes (e.g., Fibroblast → CAF, myofibroblast)
    - Disease subtypes (e.g., breast cancer → DCIS, TNBC, HER2+)

    Returns ready-to-use PubMed query fragments in pubmed_query_fragments.

    Args:
        genes: Gene symbols to expand. Example: ["TGFB1", "TGFBR2"]
        pathways: Pathway names. Example: ["EMT", "TGF-beta signaling"]
        celltypes: Cell type names. Example: ["Fibroblast", "Epithelial cell"]
        diseases: Disease names. Example: ["breast cancer"]
        expand_aliases: Expand gene aliases (default True).
        expand_mesh: Look up MeSH terms (default True).
        expand_related: Find related genes - slower (default False).

    Returns:
        Dictionary with:
        - expanded_genes: Gene info with aliases, MeSH IDs
        - expanded_pathways: Pathway info with MeSH, keywords
        - expanded_celltypes: Cell type info with MeSH, subtypes
        - expanded_diseases: Disease info with MeSH, subtypes
        - pubmed_query_fragments: Ready-to-use PubMed query strings
        - coverage_stats: Expansion statistics
    """
    arguments = {
        "genes": genes or [],
        "pathways": pathways or [],
        "celltypes": celltypes or [],
        "diseases": diseases or [],
        "expand_aliases": expand_aliases,
        "expand_mesh": expand_mesh,
        "expand_related": expand_related,
    }

    try:
        result = run_async(
            invoke_biomedical_thinking("expand_entities", arguments),
            timeout=60
        )

        if result.get("success"):
            return result["result"]
        return {"error": result.get("error", "Unknown error"), "success": False}

    except Exception as e:
        return {"error": str(e), "success": False}


@tool
def build_search_queries(
    sub_questions: list[dict],
    pubmed_query_fragments: dict,
    question_type: str = "general",
    suggested_strategy: str = "balanced",
    max_queries: int = 5,
    disease_context: str = "",
) -> dict:
    """Build optimized PubMed queries from Stage 1-2 outputs.

    Combines sub-questions (Stage 1) with MeSH-enriched query fragments (Stage 2)
    into ready-to-use PubMed queries using strategy-aware composition.

    Use AFTER analyze_research_question + expand_search_entities.
    Returns queries ready for search_pubmed_advanced.

    Args:
        sub_questions: Sub-questions from analyze_research_question output.
        pubmed_query_fragments: Query fragments from expand_search_entities output.
        question_type: Question type from analyze_research_question (default "general").
        suggested_strategy: Strategy from analyze_research_question (default "balanced").
        max_queries: Maximum queries to generate (default 5).
        disease_context: Optional disease context string.

    Returns:
        Dictionary with search_queries (ready-to-use PubMed query strings),
        iteration_roadmap, total_queries, and strategy_applied.
    """
    arguments = {
        "sub_questions": sub_questions,
        "pubmed_query_fragments": pubmed_query_fragments,
        "question_type": question_type,
        "suggested_strategy": suggested_strategy,
        "max_queries": max_queries,
        "disease_context": disease_context,
    }

    try:
        result = run_async(
            invoke_biomedical_thinking("build_search_queries", arguments),
            timeout=60
        )

        if result.get("success"):
            return result["result"]
        return {"error": result.get("error", "Unknown error"), "success": False}

    except Exception as e:
        return {"error": str(e), "success": False}


@tool
def evaluate_search_results(
    papers: list[dict],
    sub_questions: list[dict],
    entities: dict,
    question_type: str = "general",
) -> dict:
    """Evaluate search results against sub-questions and entities.

    Assesses coverage of search results by checking paper relevance to
    each sub-question and tracking entity coverage (genes, pathways, celltypes).

    Use AFTER search_pubmed_advanced to assess if results are sufficient
    or if gap-fill searches are needed.

    Args:
        papers: Search results as list of {pmid, title, abstract} dicts.
        sub_questions: Sub-questions from analyze_research_question output.
        entities: Extracted entities from analyze_research_question output.
        question_type: Question type from analyze_research_question (default "general").

    Returns:
        Dictionary with sub_question_coverage, entity_coverage, gap_analysis,
        overall_score, and recommendation.
    """
    arguments = {
        "papers": papers,
        "sub_questions": sub_questions,
        "entities": entities,
        "question_type": question_type,
    }

    try:
        result = run_async(
            invoke_biomedical_thinking("evaluate_search_results", arguments),
            timeout=60
        )

        if result.get("success"):
            return result["result"]
        return {"error": result.get("error", "Unknown error"), "success": False}

    except Exception as e:
        return {"error": str(e), "success": False}

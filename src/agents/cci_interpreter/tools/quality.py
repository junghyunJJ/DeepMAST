"""Quality validation tool for CCI Interpreter Agent.

This tool validates interpretation quality using LLM reflection
and provides scores for biological plausibility, evidence coverage,
and scientific rigor.
"""

import asyncio
import json
import re
from typing import Optional

from langchain_core.tools import tool
from langchain_mcp_adapters.client import MultiServerMCPClient


# Reflection-tool MCP server configuration (stdio transport)
REFLECTION_TOOL_CONFIG = {
    "command": "/Users/jungj2/Dropbox/Metadata/mcp/reflection_tool/.venv/bin/fastmcp",
    "args": ["run", "/Users/jungj2/Dropbox/Metadata/mcp/reflection_tool/server.py"],
    "transport": "stdio",
}

# Quality criteria weights
QUALITY_CRITERIA = {
    "statistics": {
        "weight": 0.25,
        "description": "Includes at least 2 quantitative statistics",
        "check_patterns": [
            r"\d+\.?\d*%",  # Percentages
            r"p\s*[<>=]\s*\d+\.?\d*",  # P-values
            r"r\s*[=:]\s*\d+\.?\d*",  # Correlation
            r"fold\s*change",  # Fold change
            r"\d+\s*(cells?|spots?|clusters?)",  # Counts
        ],
    },
    "references": {
        "weight": 0.25,
        "description": "Includes at least 2 literature references (PMIDs)",
        "check_patterns": [
            r"PMID[:\s]*\d+",
            r"pubmed.*?\d+",
            r"\[\d+\]",  # Numbered citations
        ],
    },
    "mechanism": {
        "weight": 0.25,
        "description": "Describes a clear biological mechanism",
        "keywords": [
            "signaling", "pathway", "interaction", "receptor",
            "ligand", "activation", "inhibition", "expression",
            "regulation", "secretion", "binding", "cascade",
        ],
    },
    "specificity": {
        "weight": 0.25,
        "description": "Avoids vague or generic statements",
        "negative_patterns": [
            r"might\s+be",
            r"could\s+potentially",
            r"further\s+research\s+is\s+needed",
            r"interestingly",
            r"it\s+is\s+important\s+to\s+note",
        ],
    },
}


def _count_pattern_matches(text: str, patterns: list[str]) -> int:
    """Count regex pattern matches in text."""
    count = 0
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        count += len(matches)
    return count


def _count_keyword_matches(text: str, keywords: list[str]) -> int:
    """Count keyword occurrences in text."""
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_lower)


def _calculate_basic_score(interpretation: str, references: list[dict]) -> dict:
    """Calculate a basic quality score without LLM.

    Args:
        interpretation: The interpretation text
        references: List of reference dictionaries

    Returns:
        Dictionary with score components
    """
    scores = {}

    # Statistics check
    stats_count = _count_pattern_matches(
        interpretation,
        QUALITY_CRITERIA["statistics"]["check_patterns"]
    )
    scores["statistics_score"] = min(stats_count / 2, 1.0)

    # References check
    ref_count = len(references) if references else 0
    ref_patterns = _count_pattern_matches(
        interpretation,
        QUALITY_CRITERIA["references"]["check_patterns"]
    )
    scores["references_score"] = min((ref_count + ref_patterns) / 2, 1.0)

    # Mechanism check
    mechanism_count = _count_keyword_matches(
        interpretation,
        QUALITY_CRITERIA["mechanism"]["keywords"]
    )
    scores["mechanism_score"] = min(mechanism_count / 3, 1.0)

    # Specificity check (negative patterns reduce score)
    negative_count = _count_pattern_matches(
        interpretation,
        QUALITY_CRITERIA["specificity"]["negative_patterns"]
    )
    scores["specificity_score"] = max(1.0 - (negative_count * 0.2), 0.0)

    # Calculate weighted total
    total_score = (
        scores["statistics_score"] * QUALITY_CRITERIA["statistics"]["weight"] +
        scores["references_score"] * QUALITY_CRITERIA["references"]["weight"] +
        scores["mechanism_score"] * QUALITY_CRITERIA["mechanism"]["weight"] +
        scores["specificity_score"] * QUALITY_CRITERIA["specificity"]["weight"]
    )

    # Generate feedback
    feedback_parts = []
    if scores["statistics_score"] < 0.5:
        feedback_parts.append("Add more quantitative statistics (p-values, percentages)")
    if scores["references_score"] < 0.5:
        feedback_parts.append("Include more literature references with PMIDs")
    if scores["mechanism_score"] < 0.5:
        feedback_parts.append("Clarify the biological mechanism being described")
    if scores["specificity_score"] < 0.7:
        feedback_parts.append("Make claims more specific and concrete")

    return {
        "score": round(total_score, 3),
        "statistics_score": round(scores["statistics_score"], 3),
        "references_score": round(scores["references_score"], 3),
        "mechanism_score": round(scores["mechanism_score"], 3),
        "specificity_score": round(scores["specificity_score"], 3),
        "feedback": " | ".join(feedback_parts) if feedback_parts else "Quality criteria met.",
        "passed": total_score >= 0.7,
    }


async def _validate_with_reflection_tool(
    interpretation: str,
    references: list[dict],
) -> Optional[dict]:
    """Validate interpretation using reflection-tool MCP server.

    Args:
        interpretation: The interpretation text
        references: List of reference dictionaries

    Returns:
        Dictionary with LLM-based quality assessment, or None if unavailable
    """
    try:
        async with MultiServerMCPClient(
            {"reflection": REFLECTION_TOOL_CONFIG}
        ) as client:
            tools = client.get_tools()

            # Find think_tool
            think_tool = None
            for tool_obj in tools:
                if hasattr(tool_obj, 'name') and 'think' in tool_obj.name:
                    think_tool = tool_obj
                    break

            if think_tool is None:
                return None

            # Construct reflection prompt
            ref_summary = f"{len(references)} references" if references else "No references"
            reflection_text = f"""Evaluate this CCI interpretation for quality:

**Interpretation** (first 800 chars):
{interpretation[:800]}...

**References**: {ref_summary}

**Quality Criteria**:
1. Statistics: Has at least 2 quantitative statistics (p-values, fold changes, percentages)
2. References: Has at least 2 literature citations (PMIDs)
3. Mechanism: Describes a clear biological mechanism
4. Specificity: Avoids vague language, makes concrete claims

**Learned**:
- Statistics present: [count]
- References present: [count]
- Mechanism clarity: [clear/unclear]
- Specificity: [high/medium/low]

**Gap**:
- What is missing or weak?

**Next**:
- Overall Score: [0.0-1.0]
- Passed: [yes/no] (threshold: 0.7)
- Recommendations: [specific improvements]"""

            result = await think_tool.ainvoke({"reflection": reflection_text})

            # Parse result
            return _parse_reflection_result(result)

    except Exception as e:
        print(f"Reflection-tool connection failed: {e}")
        return None


def _parse_reflection_result(result: str) -> dict:
    """Parse reflection-tool result into structured quality assessment."""
    assessment = {
        "llm_validated": True,
        "raw_reflection": str(result)[:500],
    }

    result_str = str(result).lower()

    # Extract score if mentioned
    score_match = re.search(r'score[:\s]*(\d+\.?\d*)', result_str)
    if score_match:
        assessment["llm_score"] = min(float(score_match.group(1)), 1.0)

    # Check for passed/failed
    if "passed" in result_str or "yes" in result_str:
        assessment["llm_passed"] = True
    elif "failed" in result_str or "no" in result_str:
        assessment["llm_passed"] = False

    return assessment


@tool
def validate_quality(
    interpretation: str,
    references: list[dict],
    use_llm: bool = True,
) -> dict:
    """Validate the quality of a CCI interpretation.

    This tool evaluates an interpretation against quality criteria:
    - Statistics: At least 2 quantitative statistics
    - References: At least 2 literature references (PMIDs)
    - Mechanism: Clear biological mechanism described
    - Specificity: Avoids vague or generic statements

    A score >= 0.7 is considered passing quality.

    Args:
        interpretation: The interpretation text to validate
        references: List of reference dictionaries with PMIDs
        use_llm: Whether to use LLM validation via reflection-tool (default True)

    Returns:
        Dictionary with:
        - score: Overall quality score (0.0-1.0)
        - statistics_score: Statistics criteria score
        - references_score: References criteria score
        - mechanism_score: Mechanism clarity score
        - specificity_score: Specificity score
        - feedback: Specific improvement suggestions
        - passed: Whether score >= 0.7 threshold
    """
    # Calculate basic score
    result = _calculate_basic_score(interpretation, references)

    # Optionally enhance with LLM validation
    if use_llm:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        _validate_with_reflection_tool(interpretation, references)
                    )
                    llm_result = future.result(timeout=30)
            else:
                llm_result = asyncio.run(
                    _validate_with_reflection_tool(interpretation, references)
                )

            if llm_result:
                result.update(llm_result)

                # Adjust score if LLM provides one
                if "llm_score" in llm_result:
                    # Average basic and LLM scores
                    result["score"] = round(
                        (result["score"] + llm_result["llm_score"]) / 2, 3
                    )
                    result["passed"] = result["score"] >= 0.7

        except Exception:
            # LLM validation failed, use basic score only
            pass

    return result


def get_improvement_suggestions(validation_result: dict) -> list[str]:
    """Generate specific improvement suggestions based on validation result.

    Args:
        validation_result: Result from validate_quality

    Returns:
        List of specific improvement suggestions
    """
    suggestions = []

    if validation_result.get("statistics_score", 0) < 0.5:
        suggestions.extend([
            "Add p-values for significant findings",
            "Include percentages for composition changes",
            "Report fold changes for differential expression",
        ])

    if validation_result.get("references_score", 0) < 0.5:
        suggestions.extend([
            "Search PubMed for supporting literature",
            "Add PMID citations for key claims",
            "Reference established pathway databases",
        ])

    if validation_result.get("mechanism_score", 0) < 0.5:
        suggestions.extend([
            "Describe the signaling cascade involved",
            "Explain ligand-receptor binding dynamics",
            "Connect pathway activation to phenotype",
        ])

    if validation_result.get("specificity_score", 0) < 0.7:
        suggestions.extend([
            "Replace 'might be' with definitive statements",
            "Remove hedging language ('potentially', 'could')",
            "State specific cell types and interactions",
        ])

    return suggestions


@tool
def validate_claim_literature(
    claim: str,
    pmid: str,
    paper_abstract: str,
) -> dict:
    """Validate that a biological claim is supported by the cited paper.

    This tool checks whether a specific claim made in the interpretation
    is actually supported by the abstract of the cited paper. It returns
    an alignment assessment and recommendation.

    Args:
        claim: The biological claim to validate (e.g., "CDH1 is involved in EMT")
        pmid: The PMID of the cited paper
        paper_abstract: The abstract text of the cited paper

    Returns:
        Dictionary with:
        - alignment: "strong" | "weak" | "unsupported" - how well the paper supports the claim
        - evidence_quote: Relevant sentence from the abstract (if found)
        - recommendation: "keep" | "revise" | "mark_novel"
        - confidence: 0.0-1.0 confidence score
        - reasoning: Brief explanation of the assessment
    """
    if not claim or not paper_abstract:
        return {
            "alignment": "unsupported",
            "evidence_quote": "",
            "recommendation": "mark_novel",
            "confidence": 0.0,
            "reasoning": "Missing claim or abstract text",
        }

    # Extract key terms from the claim
    claim_lower = claim.lower()
    abstract_lower = paper_abstract.lower()

    # Key biological terms to match
    key_terms = []

    # Extract gene names (uppercase patterns)
    gene_matches = re.findall(r'\b([A-Z][A-Z0-9]{2,})\b', claim)
    key_terms.extend([g.lower() for g in gene_matches])

    # Extract biological keywords
    bio_keywords = [
        "expression", "signaling", "pathway", "interaction", "activation",
        "inhibition", "receptor", "ligand", "secretion", "binding",
        "upregulated", "downregulated", "induced", "suppressed",
        "promotes", "inhibits", "mediates", "regulates", "associated",
        "correlated", "enriched", "depleted", "tumor", "cancer",
        "spatial", "co-localized", "adjacent", "neighboring",
    ]

    claim_keywords = [kw for kw in bio_keywords if kw in claim_lower]
    key_terms.extend(claim_keywords)

    if not key_terms:
        # Fallback: simple word overlap
        claim_words = set(claim_lower.split())
        abstract_words = set(abstract_lower.split())
        overlap = claim_words.intersection(abstract_words)
        overlap_ratio = len(overlap) / len(claim_words) if claim_words else 0

        if overlap_ratio > 0.5:
            alignment = "weak"
            recommendation = "keep"
            confidence = 0.4
        else:
            alignment = "unsupported"
            recommendation = "mark_novel"
            confidence = 0.2

        return {
            "alignment": alignment,
            "evidence_quote": "",
            "recommendation": recommendation,
            "confidence": confidence,
            "reasoning": f"Word overlap ratio: {overlap_ratio:.2f}",
        }

    # Count matching terms
    matching_terms = []
    for term in key_terms:
        if term in abstract_lower:
            matching_terms.append(term)

    match_ratio = len(matching_terms) / len(key_terms) if key_terms else 0

    # Find evidence quote - sentence containing most terms
    sentences = re.split(r'[.!?]', paper_abstract)
    best_sentence = ""
    best_score = 0

    for sentence in sentences:
        sentence_lower = sentence.lower()
        score = sum(1 for term in matching_terms if term in sentence_lower)
        if score > best_score:
            best_score = score
            best_sentence = sentence.strip()

    # Determine alignment
    if match_ratio >= 0.6 and best_score >= 2:
        alignment = "strong"
        recommendation = "keep"
        confidence = min(0.9, match_ratio + 0.2)
    elif match_ratio >= 0.3 or best_score >= 1:
        alignment = "weak"
        recommendation = "keep"
        confidence = min(0.7, match_ratio + 0.1)
    else:
        alignment = "unsupported"
        recommendation = "mark_novel"
        confidence = max(0.1, match_ratio)

    # Check for contradictory evidence
    # General contradiction patterns
    general_contradiction_patterns = [
        r"no\s+(?:significant\s+)?(?:difference|association|correlation|connection|effect|impact)",
        r"failed\s+to\s+(?:show|demonstrate|find|detect|observe)",
        r"did\s+not\s+(?:support|confirm|show|find|observe)",
        r"(?:was|were)\s+not\s+(?:observed|detected|found|seen)",
        r"contrary\s+to",
        r"in\s+contrast",
        r"no\s+evidence\s+(?:of|for|that)",
        r"lack\s+of\s+(?:association|correlation|connection)",
        r"independent\s+of",
        r"unrelated\s+to",
    ]

    # Check if any claim terms appear in a negation context
    claim_genes = [g.lower() for g in re.findall(r'\b([A-Z][A-Z0-9]{2,})\b', claim)]
    has_term_specific_negation = False

    for gene in claim_genes:
        # Look for negation patterns near the gene name
        negation_near_term = re.search(
            rf'(?:no|not|without|lack(?:ing)?|absent)\s+(?:\w+\s+){{0,3}}{gene}',
            abstract_lower
        )
        if negation_near_term:
            has_term_specific_negation = True
            break

        # Check for "X was not Y" patterns with potential words in between
        negation_pattern = re.search(
            rf'{gene}\s+(?:\w+\s+){{0,2}}(?:was|were|is|are)\s+not\s+(?:observed|detected|found|associated|seen)',
            abstract_lower
        )
        if negation_pattern:
            has_term_specific_negation = True
            break

        # Check for "no X" or "lack of X" patterns
        no_term_pattern = re.search(
            rf'(?:no|lack\s+of|absence\s+of)\s+(?:\w+\s+){{0,2}}{gene}',
            abstract_lower
        )
        if no_term_pattern:
            has_term_specific_negation = True
            break

    # Apply contradictions
    if has_term_specific_negation:
        if alignment == "strong":
            alignment = "unsupported"
            recommendation = "revise"
            confidence *= 0.3
        elif alignment == "weak":
            alignment = "unsupported"
            recommendation = "revise"
            confidence *= 0.4
    else:
        for pattern in general_contradiction_patterns:
            if re.search(pattern, abstract_lower):
                if alignment == "strong":
                    alignment = "weak"
                    recommendation = "revise"
                    confidence *= 0.7
                elif alignment == "weak":
                    alignment = "unsupported"
                    recommendation = "revise"
                    confidence *= 0.5
                break

    reasoning = f"Matched {len(matching_terms)}/{len(key_terms)} terms"
    if matching_terms:
        reasoning += f": {', '.join(matching_terms[:5])}"

    return {
        "alignment": alignment,
        "evidence_quote": best_sentence[:300] if best_sentence else "",
        "recommendation": recommendation,
        "confidence": round(confidence, 3),
        "reasoning": reasoning,
    }


def get_claim_validation_summary(validations: list[dict]) -> dict:
    """Summarize claim validation results.

    Args:
        validations: List of validation results from validate_claim_literature

    Returns:
        Dictionary with summary statistics
    """
    if not validations:
        return {
            "total_claims": 0,
            "strong_support": 0,
            "weak_support": 0,
            "unsupported": 0,
            "needs_revision": 0,
            "novel_findings": 0,
            "overall_confidence": 0.0,
        }

    strong = sum(1 for v in validations if v.get("alignment") == "strong")
    weak = sum(1 for v in validations if v.get("alignment") == "weak")
    unsupported = sum(1 for v in validations if v.get("alignment") == "unsupported")
    revisions = sum(1 for v in validations if v.get("recommendation") == "revise")
    novel = sum(1 for v in validations if v.get("recommendation") == "mark_novel")
    avg_confidence = sum(v.get("confidence", 0) for v in validations) / len(validations)

    return {
        "total_claims": len(validations),
        "strong_support": strong,
        "weak_support": weak,
        "unsupported": unsupported,
        "needs_revision": revisions,
        "novel_findings": novel,
        "overall_confidence": round(avg_confidence, 3),
    }
